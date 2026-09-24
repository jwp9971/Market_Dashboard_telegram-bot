"""
The Massive client: rate limiting, retries, cache and call budget.

Runs on a fake clock and a fake HTTP function, so a minute of waiting takes no
time and nothing reaches the network. The fixtures are synthetic (see
tests/fixtures/massive/README.md).
"""
import json
import os

import pytest
import requests

import massive_client
from massive_client import (MassiveAuthError, MassiveBudgetExceeded,
                            MassiveClient, MassiveHTTPError,
                            MassiveRateLimitError, RateLimiter)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "massive")
KEY = "test-key-not-real"
GROUPED = "/v2/aggs/grouped/locale/us/market/stocks/2026-09-15"


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


class FakeClock:
    """time.monotonic and time.sleep that share one hand-moved counter."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeHTTP:
    """Plays back scripted responses and remembers every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.requests.append({"url": url, "params": params, "headers": headers})
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response


def ok(body=None):
    return FakeResponse(200, body if body is not None else load("grouped_daily.json"))


def make_client(tmp_path, http, clock=None, **kwargs):
    clock = clock or FakeClock()
    return MassiveClient(api_key=KEY, cache_dir=str(tmp_path / "cache"),
                         clock=clock, sleep=clock.sleep, http_get=http, **kwargs)


# --- rate limiter ------------------------------------------------------------

def test_five_calls_go_straight_through_and_the_sixth_waits_out_the_minute():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    for _ in range(5):
        assert limiter.acquire("stocks") == 0
    waited = limiter.acquire("stocks")
    assert waited == pytest.approx(61.0)          # 60 s window + 1 s margin
    assert clock.now == pytest.approx(1061.0)


def test_spaced_out_calls_never_wait():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    for _ in range(12):
        assert limiter.acquire("stocks") == 0
        clock.now += 13                             # slower than 5 a minute
    assert clock.slept == []


def test_asset_classes_do_not_block_each_other():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    for _ in range(5):
        limiter.acquire("stocks")
    assert limiter.acquire("economy") == 0
    assert limiter.acquire("futures") == 0
    assert clock.slept == []


def test_a_client_run_of_seven_calls_in_one_class_waits_once(tmp_path):
    # Calls 1-5 go at once; call 6 waits until they have all left the window,
    # so call 7 then fits without a second wait.
    clock = FakeClock()
    client = make_client(tmp_path, FakeHTTP(ok()), clock=clock)
    for day in range(7):
        client.get(f"/v2/aggs/grouped/locale/us/market/stocks/2026-09-{day + 1:02d}")
    assert clock.slept == [pytest.approx(61.0)]
    assert client.calls_by_class == {"stocks": 7}


# --- key handling ------------------------------------------------------------

def test_the_key_travels_in_the_header_only(tmp_path):
    http = FakeHTTP(ok())
    client = make_client(tmp_path, http)
    client.get(GROUPED, {"adjusted": "true"}, cache=True)

    sent = http.requests[0]
    assert sent["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert KEY not in sent["url"]
    assert KEY not in json.dumps(sent["params"])

    cached = client.cache_path("stocks", GROUPED, {"adjusted": "true"})
    assert KEY not in cached
    with open(cached, encoding="utf-8") as handle:
        assert KEY not in handle.read()


def test_the_key_is_refused_as_a_query_parameter(tmp_path):
    client = make_client(tmp_path, FakeHTTP(ok()))
    with pytest.raises(ValueError):
        client.get(GROUPED, {"apiKey": KEY})


def test_a_missing_key_fails_with_a_clear_message(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    with pytest.raises(MassiveAuthError, match="MASSIVE_API_KEY is not set"):
        MassiveClient(api_key=None)


def test_the_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "  from-env  ")
    assert MassiveClient().api_key == "from-env"


# --- cache ---------------------------------------------------------------------

def test_a_cache_hit_makes_no_request_and_costs_no_budget(tmp_path):
    http = FakeHTTP(ok())
    client = make_client(tmp_path, http)
    first = client.get(GROUPED, cache=True)
    second = client.get(GROUPED, cache=True)
    assert first == second == load("grouped_daily.json")
    assert len(http.requests) == 1
    assert client.calls_made == 1 and client.cache_hits == 1


def test_the_cache_survives_into_a_new_client(tmp_path):
    make_client(tmp_path, FakeHTTP(ok())).get(GROUPED, cache=True)
    http = FakeHTTP(ok())
    make_client(tmp_path, http).get(GROUPED, cache=True)
    assert http.requests == []


def test_uncached_calls_never_write(tmp_path):
    client = make_client(tmp_path, FakeHTTP(ok()))
    client.get(GROUPED)
    assert not (tmp_path / "cache").exists()


def test_different_params_are_different_cache_entries(tmp_path):
    http = FakeHTTP(ok())
    client = make_client(tmp_path, http)
    client.get(GROUPED, {"adjusted": "true"}, cache=True)
    client.get(GROUPED, {"adjusted": "false"}, cache=True)
    assert len(http.requests) == 2


def test_a_corrupt_cache_file_is_refetched(tmp_path):
    http = FakeHTTP(ok())
    client = make_client(tmp_path, http)
    client.get(GROUPED, cache=True)
    with open(client.cache_path("stocks", GROUPED, {}), "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert client.get(GROUPED, cache=True) == load("grouped_daily.json")
    assert len(http.requests) == 2


# --- retries -------------------------------------------------------------------

def test_a_429_waits_a_full_minute_then_succeeds(tmp_path):
    clock = FakeClock()
    http = FakeHTTP(FakeResponse(429, load("error_429.json")), ok())
    client = make_client(tmp_path, http, clock=clock)
    assert client.get(GROUPED) == load("grouped_daily.json")
    assert clock.slept == [massive_client.RATE_LIMIT_BACKOFF_SECONDS]
    assert client.calls_made == 2                  # the retry is a real call


def test_repeated_429s_give_up_with_a_clear_error(tmp_path):
    http = FakeHTTP(FakeResponse(429, load("error_429.json")))
    client = make_client(tmp_path, http)
    with pytest.raises(MassiveRateLimitError):
        client.get(GROUPED)
    assert len(http.requests) == 1 + massive_client.RATE_LIMIT_RETRIES


def test_a_403_stops_at_once_and_says_why(tmp_path):
    http = FakeHTTP(FakeResponse(403, load("error_403.json")))
    client = make_client(tmp_path, http)
    with pytest.raises(MassiveAuthError, match="not entitled"):
        client.get(GROUPED)
    assert len(http.requests) == 1


def test_server_errors_and_dropped_connections_are_retried(tmp_path):
    clock = FakeClock()
    http = FakeHTTP(FakeResponse(503, {}), requests.RequestException("reset"), ok())
    client = make_client(tmp_path, http, clock=clock)
    assert client.get(GROUPED) == load("grouped_daily.json")
    assert clock.slept == list(massive_client.SERVER_ERROR_BACKOFFS)


def test_other_client_errors_are_not_retried(tmp_path):
    http = FakeHTTP(FakeResponse(404, {"status": "ERROR", "message": "not found"}))
    client = make_client(tmp_path, http)
    with pytest.raises(MassiveHTTPError, match="404"):
        client.get(GROUPED)
    assert len(http.requests) == 1


# --- budget --------------------------------------------------------------------

def test_the_budget_stops_the_call_before_it_is_sent(tmp_path):
    http = FakeHTTP(ok())
    client = make_client(tmp_path, http, max_calls=2)
    client.get(GROUPED)
    client.get(GROUPED)
    with pytest.raises(MassiveBudgetExceeded):
        client.get(GROUPED)
    assert len(http.requests) == 2


def test_the_budget_counts_retries(tmp_path):
    http = FakeHTTP(FakeResponse(429, load("error_429.json")), ok())
    client = make_client(tmp_path, http, max_calls=1)
    with pytest.raises(MassiveBudgetExceeded):
        client.get(GROUPED)
    assert len(http.requests) == 1


# --- logging -------------------------------------------------------------------

def test_the_log_shows_counts_never_values(tmp_path, capsys):
    client = make_client(tmp_path, FakeHTTP(ok()))
    client.get(GROUPED)
    out = capsys.readouterr().out
    assert "200, 3 results" in out
    assert "101.0" not in out and "SPY" not in out and KEY not in out


def test_the_default_http_function_is_looked_up_at_call_time(tmp_path, monkeypatch):
    """So the suite's network block on requests.get also covers a default client."""
    seen = []
    monkeypatch.setattr(requests, "get",
                        lambda url, **kwargs: seen.append(url) or ok(), raising=False)
    client = MassiveClient(api_key=KEY, cache_dir=str(tmp_path),
                           clock=FakeClock(), sleep=lambda s: None)
    client.get(GROUPED)
    assert seen == [massive_client.BASE_URL + GROUPED]


def test_unknown_asset_class_is_rejected(tmp_path):
    client = make_client(tmp_path, FakeHTTP(ok()))
    with pytest.raises(ValueError):
        client.get(GROUPED, asset_class="crypto")
