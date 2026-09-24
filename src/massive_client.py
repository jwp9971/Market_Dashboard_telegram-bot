"""
The one door to the Massive REST API (weekly commentary).

The free Basic plan allows 5 requests a minute per asset class, each class
counted on its own, and answers 429 past that with no Retry-After header.
Every call goes through MassiveClient.get() so that limit, retries, the
on-disk cache and a per-run call budget are enforced in one place.

Massive's terms forbid publishing its data to third parties. This repo is
public and so are its Actions logs, so nothing here prints a data value --
only the endpoint, status, result count and wait time. The key travels in a
header, never in a URL, a log line or a cache file, and cache/ is gitignored.
"""
import hashlib
import json
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

BASE_URL = "https://api.massive.com"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE_DIR = os.path.join(ROOT, "cache", "massive")

# One bucket per asset class. Economy (/fed/...) is not named in Massive's
# rate-limit docs, so it gets its own bucket at the same conservative limit;
# reference and cross-asset endpoints are documented as a separate bucket.
ASSET_CLASSES = ("stocks", "economy", "futures", "currencies", "reference")
CALLS_PER_WINDOW = 5
WINDOW_SECONDS = 60.0
# Clock skew between us and Massive: wait a little past the minute.
WINDOW_MARGIN_SECONDS = 1.0

# A run that needs more than this is a bug (a loop over dates, say), and at
# 5 a minute it would also take a long time to find out.
DEFAULT_MAX_CALLS = 40

REQUEST_TIMEOUT_SECONDS = 30
# No Retry-After header, so wait out a full window before trying again.
RATE_LIMIT_BACKOFF_SECONDS = 60.0
RATE_LIMIT_RETRIES = 2
SERVER_ERROR_BACKOFFS = (5.0, 15.0)


class MassiveError(Exception):
    """Base class for every failure this module raises."""


class MassiveAuthError(MassiveError):
    """Missing or rejected key, or data the plan does not include (401/403)."""


class MassiveRateLimitError(MassiveError):
    """Still answering 429 after the retries."""


class MassiveHTTPError(MassiveError):
    """Any other failed request."""


class MassiveBudgetExceeded(MassiveError):
    """The per-run call budget is used up; raised before the request is sent."""


class RateLimiter:
    """
    Remembers the last few call times per asset class and makes a call wait
    until the oldest of them has left the window.

    A rolling window never exceeds the limit in any 60 seconds, so it is safe
    whether Massive counts a rolling or a clock minute, and a small run is not
    slowed down: the first five calls in a class go straight through.
    """

    def __init__(self, calls_per_window=CALLS_PER_WINDOW,
                 window_seconds=WINDOW_SECONDS,
                 margin_seconds=WINDOW_MARGIN_SECONDS,
                 clock=time.monotonic, sleep=time.sleep):
        self.calls_per_window = calls_per_window
        self.window_seconds = window_seconds
        self.margin_seconds = margin_seconds
        self.clock = clock
        self.sleep = sleep
        self._calls = {}

    def acquire(self, asset_class):
        """Blocks until one more call in this class fits. Returns seconds waited."""
        calls = self._calls.setdefault(asset_class, deque())
        waited = 0.0
        now = self.clock()
        if len(calls) >= self.calls_per_window:
            wait = calls[0] + self.window_seconds + self.margin_seconds - now
            if wait > 0:
                self.sleep(wait)
                waited = wait
                now = self.clock()
        calls.append(now)
        while len(calls) > self.calls_per_window:
            calls.popleft()
        return waited


def _message(response):
    """The API's own short explanation from an error body, if any."""
    try:
        body = response.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    text = body.get("message") or body.get("error") or ""
    return str(text)[:200]


def _results_count(body):
    results = body.get("results") if isinstance(body, dict) else None
    return len(results) if isinstance(results, list) else 0


class MassiveClient:
    def __init__(self, api_key=None, cache_dir=DEFAULT_CACHE_DIR,
                 max_calls=DEFAULT_MAX_CALLS, clock=time.monotonic,
                 sleep=time.sleep, http_get=None, limiter=None):
        self.api_key = (api_key or os.getenv("MASSIVE_API_KEY") or "").strip() or None
        if not self.api_key:
            raise MassiveAuthError(
                "MASSIVE_API_KEY is not set (add it to .env locally, "
                "or to the repository secrets for Actions)"
            )
        self.cache_dir = cache_dir
        self.max_calls = max_calls
        self.clock = clock
        self.sleep = sleep
        self.limiter = limiter or RateLimiter(clock=clock, sleep=sleep)
        # Looked up at call time, not bound here, so the test suite's network
        # block on requests.get also covers a client built with the default.
        self._http_get = http_get
        self.calls_made = 0
        self.calls_by_class = {}
        self.cache_hits = 0

    # --- public ------------------------------------------------------------

    def get(self, path, params=None, asset_class="stocks", cache=False):
        """
        GET BASE_URL + path and return the decoded JSON body.

        cache=True reads a saved answer if there is one and saves a fresh one
        otherwise. Only ask for it on data that can no longer change -- a
        past, settled date -- or an early empty answer gets frozen in place.
        """
        if asset_class not in ASSET_CLASSES:
            raise ValueError(f"unknown asset class {asset_class!r}; expected one of {ASSET_CLASSES}")
        params = dict(params or {})
        if any(str(name).lower() == "apikey" for name in params):
            raise ValueError("pass the key via the client, never as a query parameter")

        if cache:
            cached = self._read_cache(asset_class, path, params)
            if cached is not None:
                self.cache_hits += 1
                print(f"Massive {asset_class} GET {path} -> cache hit, "
                      f"{_results_count(cached)} results")
                return cached

        body = self._fetch(asset_class, path, params)
        if cache:
            self._write_cache(asset_class, path, params, body)
        return body

    # --- network -------------------------------------------------------------

    def _spend(self, asset_class, path):
        if self.calls_made >= self.max_calls:
            raise MassiveBudgetExceeded(
                f"run budget of {self.max_calls} live Massive calls is used up; "
                f"refusing {asset_class} {path}"
            )
        self.calls_made += 1
        self.calls_by_class[asset_class] = self.calls_by_class.get(asset_class, 0) + 1

    def _fetch(self, asset_class, path, params):
        http_get = self._http_get or requests.get
        headers = {"Authorization": f"Bearer {self.api_key}"}
        rate_limited = server_errors = 0

        while True:
            self._spend(asset_class, path)
            waited = self.limiter.acquire(asset_class)
            started = self.clock()
            response, status = None, None
            try:
                response = http_get(BASE_URL + path, params=params, headers=headers,
                                    timeout=REQUEST_TIMEOUT_SECONDS)
                status = response.status_code
            except requests.RequestException as exc:
                # Name only: the exception text repeats the URL and request.
                failure = type(exc).__name__
            elapsed = self.clock() - started
            wait_note = f" (waited {waited:.0f}s for the rate limit)" if waited else ""

            if status == 200:
                try:
                    body = response.json()
                except Exception:
                    raise MassiveHTTPError(f"{asset_class} {path}: HTTP 200 but the body is not JSON")
                print(f"Massive {asset_class} GET {path} -> 200, "
                      f"{_results_count(body)} results, {elapsed:.1f}s{wait_note}")
                if isinstance(body, dict) and body.get("next_url"):
                    print(f"WARNING: Massive {path} has more pages; only the first was read")
                return body

            outcome = f"HTTP {status}" if status is not None else failure
            print(f"Massive {asset_class} GET {path} -> {outcome}, {elapsed:.1f}s{wait_note}")

            if status in (401, 403):
                raise MassiveAuthError(f"{asset_class} {path}: HTTP {status} {_message(response)}".rstrip())
            if status == 429:
                if rate_limited >= RATE_LIMIT_RETRIES:
                    raise MassiveRateLimitError(
                        f"{asset_class} {path}: still rate-limited after {rate_limited} retries"
                    )
                rate_limited += 1
                self.sleep(RATE_LIMIT_BACKOFF_SECONDS)
                continue
            if status is None or status >= 500:
                if server_errors >= len(SERVER_ERROR_BACKOFFS):
                    raise MassiveHTTPError(f"{asset_class} {path}: {outcome} after {server_errors} retries")
                self.sleep(SERVER_ERROR_BACKOFFS[server_errors])
                server_errors += 1
                continue
            raise MassiveHTTPError(f"{asset_class} {path}: HTTP {status} {_message(response)}".rstrip())

    # --- cache ---------------------------------------------------------------

    def cache_path(self, asset_class, path, params):
        """cache/massive/<class>/<readable path>__<hash of path+params>.json"""
        request = json.dumps({"path": path, "params": params}, sort_keys=True, default=str)
        digest = hashlib.sha256(request.encode("utf-8")).hexdigest()[:12]
        slug = re.sub(r"[^A-Za-z0-9.-]+", "_", path).strip("_")[:80]
        return os.path.join(self.cache_dir, asset_class, f"{slug}__{digest}.json")

    def _read_cache(self, asset_class, path, params):
        file_path = self.cache_path(asset_class, path, params)
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, encoding="utf-8") as handle:
                return json.load(handle)["body"]
        except (OSError, ValueError, KeyError):
            print(f"Massive cache file unreadable, refetching: {os.path.basename(file_path)}")
            return None

    def _write_cache(self, asset_class, path, params, body):
        file_path = self.cache_path(asset_class, path, params)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        record = {
            "path": path,
            "params": params,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "body": body,
        }
        # Write then rename, so an interrupted run never leaves half a file.
        temporary = file_path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=1)
        os.replace(temporary, file_path)
