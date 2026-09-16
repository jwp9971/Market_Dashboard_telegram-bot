import os
import sys
from datetime import datetime, timedelta, timezone

import yfinance as yf
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from metrics import (MAX_AGE_MARKET_DAYS, CHANGE_PCT, UNIT_USD, Metric,
                     mark_staleness, to_iso_date)

# Alpaca is optional now. Import failures must not take down the Yahoo path,
# so everything Alpaca-specific is guarded.
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import Adjustment, DataFeed
    ALPACA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without alpaca-py
    StockHistoricalDataClient = StockBarsRequest = TimeFrame = None
    Adjustment = DataFeed = None
    ALPACA_AVAILABLE = False

# Where ETF prices come from.
#
# "alpaca" (default) is the freshest: a live run on 2026-09-16 at 01:08 UTC --
# five hours after the Sep 15 close -- got Sep 15 bars from Alpaca's path but
# only Sep 14 from the batched Yahoo download, one full session behind on all
# 22 rows. Freshness beats the one problem Yahoo solved, because a stale D/D
# is wrong on every row while a frozen ticker is wrong on one.
#
# "yahoo" batches all 22 symbols into one request and returns consolidated,
# split- and dividend-adjusted closes. It fixes thinly traded names -- AIHY
# reported 0.00% over both a day and a week on Alpaca's IEX fallback, and real
# moves on Yahoo -- but lags a session at the hour this report runs.
#
# Either way, sessions_behind() now reports the lag rather than leaving it to
# be noticed by eye.
ETF_SOURCE = (os.getenv("ETF_SOURCE") or "alpaca").strip().lower()

ALPACA_API_KEY = (os.getenv("ALPACA_API_KEY") or "").strip() or None
ALPACA_SECRET_KEY = (os.getenv("ALPACA_SECRET_KEY") or "").strip() or None

FEEDS = {"sip": DataFeed.SIP, "iex": DataFeed.IEX} if ALPACA_AVAILABLE else {}
PREFERRED_FEED = (os.getenv("ALPACA_FEED") or "sip").strip().lower()
ADJUSTMENT = Adjustment.SPLIT if ALPACA_AVAILABLE else None

MACRO_ETFS = {
    # Indices
    "DIA": "Dow Jones",
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    # Bonds
    "HYG": "High Yield Bonds",
    # Bitcoin
    "IBIT": "Bitcoin",
    # Geography
    "EWY": "Korea",
    "EWJ": "Japan",
    "IEMG": "Emerging Markets (Broad)",
}

BROAD_INDUSTRY_ETFS = {
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
}

THEME_ETFS = {
    "SOXX": "Semiconductors",
    "IGV": "Software",
    "PAVE": "Infrastructure",
    "ITA": "Aerospace & Defense",
    "DRAM": "Memory & Storage",
    "AIHY": "AI Hyperscale",
    "BUG": "Cybersecurity",
    "NCLD": "Neoclouds",
}

# The group keys get_sector_snapshot() returns. analyst.py and dashboard.py
# import this instead of hardcoding key names, so renaming a group here is a
# one-line change that can't silently orphan a downstream consumer.
SECTOR_GROUP_KEYS = ("macro", "broad_industry", "theme")

ETF_GROUPS = {
    "macro": MACRO_ETFS,
    "broad_industry": BROAD_INDUSTRY_ETFS,
    "theme": THEME_ETFS,
}

GROUP_TITLES = {
    "macro": "Indices / Bonds / Bitcoin / Geography",
    "broad_industry": "Broad Industry",
    "theme": "Theme",
}


def all_symbols():
    return [symbol for key in SECTOR_GROUP_KEYS for symbol in ETF_GROUPS[key]]


def all_metrics(sector_snapshot):
    """Flattens every group into one list, in group order."""
    return [m for key in SECTOR_GROUP_KEYS
            for m in (sector_snapshot or {}).get(key, []) or []]


def _new_metric(symbol, label, source):
    return Metric(key=symbol, label=label, symbol=symbol, unit=UNIT_USD,
                  change_kind=CHANGE_PCT, source=source,
                  max_age_days=MAX_AGE_MARKET_DAYS)


def _pct_change(series, offset):
    if series is None or len(series) <= offset:
        return None
    current = float(series.iloc[-1])
    prior = float(series.iloc[-1 - offset])
    if prior == 0:
        return None
    return round(((current - prior) / prior) * 100, 2)


# --- Yahoo (default) -------------------------------------------------------

def fetch_yahoo_frame(symbols, period="3mo"):
    """One batched request for every symbol, instead of one call per ETF."""
    return yf.download(symbols, period=period, interval="1d",
                       auto_adjust=False, group_by="ticker",
                       progress=False, threads=True)


def fetch_yahoo_single(symbol, period="3mo"):
    """
    Per-symbol fallback. Deliberately the same call shape macro.py has been
    using in production, so if the batched response is ever shaped differently
    than expected the run still produces data.
    """
    return yf.Ticker(symbol).history(period=period, interval="1d",
                                     auto_adjust=False)


def _symbol_frame(data, symbol, single):
    if data is None:
        return None
    try:
        return data if single else data[symbol]
    except (KeyError, TypeError, IndexError):
        return None


def _closes(frame):
    """
    Returns (close, adjusted).

    `close` is the real market close, which is what the report should print.
    `adjusted` is split- and dividend-adjusted, which is what the changes
    should be computed from -- otherwise an ex-dividend date renders as a
    genuine decline. The two differ only across a split or distribution.
    """
    if frame is None:
        return None, None
    try:
        close = frame["Close"].dropna()
    except (KeyError, TypeError):
        return None, None
    if close is None or len(close) == 0:
        return None, None
    try:
        adjusted = frame["Adj Close"].dropna()
        if adjusted is None or len(adjusted) == 0:
            adjusted = close
    except (KeyError, TypeError):
        adjusted = close
    return close, adjusted


def build_yahoo_metric(data, symbol, label, single=False):
    metric = _new_metric(symbol, label, "yahoo")
    close, adjusted = _closes(_symbol_frame(data, symbol, single))
    if close is None or len(close) < 2:
        metric.error = "no data"
        return metric

    metric.value = float(close.iloc[-1])
    metric.day_change = _pct_change(adjusted, 1)
    metric.week_change = _pct_change(adjusted, 5)
    metric.month_change = _pct_change(adjusted, 21)
    metric.as_of = to_iso_date(close.index[-1])
    return metric


def yahoo_snapshot(today=None):
    symbols = all_symbols()
    data, note = None, None
    try:
        data = fetch_yahoo_frame(symbols)
    except Exception as e:
        print(f"Yahoo ETF fetch failed: {type(e).__name__}")
        note = "Yahoo ETF fetch failed; no ETF data this run"

    single = len(symbols) == 1
    snapshot = {
        key: [build_yahoo_metric(data, symbol, label, single)
              for symbol, label in ETF_GROUPS[key].items()]
        for key in SECTOR_GROUP_KEYS
    }

    # If the request succeeded but nothing parsed, the batched response was
    # shaped differently than expected. Rather than report 22 empty rows,
    # retry one symbol at a time through the call shape macro.py already
    # relies on, and say in the report that it happened.
    if data is not None and not any(m.is_usable for m in all_metrics(snapshot)):
        print("Batched ETF response yielded no data; retrying per symbol")
        note = ("batched ETF fetch returned nothing; fell back to per-symbol "
                "requests")
        snapshot = {
            key: [_single_symbol_metric(symbol, label)
                  for symbol, label in ETF_GROUPS[key].items()]
            for key in SECTOR_GROUP_KEYS
        }

    snapshot["price_source"] = "yahoo"
    snapshot["price_source_note"] = note
    return snapshot


def _single_symbol_metric(symbol, label):
    try:
        return build_yahoo_metric(fetch_yahoo_single(symbol), symbol, label,
                                  single=True)
    except Exception as e:
        print(f"Yahoo fetch error for {symbol}: {type(e).__name__}")
        metric = _new_metric(symbol, label, "yahoo")
        metric.error = "fetch failed"
        return metric


# --- Alpaca (opt-in via ETF_SOURCE=alpaca) ---------------------------------

def get_alpaca_client():
    if not ALPACA_AVAILABLE:
        print("alpaca-py is not installed; cannot use ETF_SOURCE=alpaca")
        return None
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("Alpaca credentials are not configured; skipping ETF fetch")
        return None
    try:
        return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    except Exception as e:
        print(f"Alpaca client error: {e}")
        return None


def _fetch_bars(client, symbol, feed):
    end = datetime.now(timezone.utc)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=end - timedelta(days=40),
        end=end,
        feed=feed,
        adjustment=ADJUSTMENT,
    )
    return client.get_stock_bars(request).df


def resolve_feed(client, probe_symbol="SPY"):
    """
    Decides the feed once per run with a single probe request, rather than
    letting 22 fetches each fail and retry. Returns (feed_name, note); the
    note is non-empty only when the preferred feed was refused.
    """
    if PREFERRED_FEED not in FEEDS:
        return "iex", f"unknown ALPACA_FEED '{PREFERRED_FEED}'; using IEX"
    if PREFERRED_FEED == "iex":
        return "iex", None
    try:
        _fetch_bars(client, probe_symbol, FEEDS[PREFERRED_FEED])
        return PREFERRED_FEED, None
    except Exception as e:
        return "iex", (
            f"{PREFERRED_FEED.upper()} feed unavailable ({type(e).__name__}); "
            "using IEX, a single exchange -- treat thinly traded ETF closes with caution"
        )


def get_etf_metric(client, symbol, label, feed=None):
    metric = _new_metric(symbol, label, "alpaca")
    try:
        df = _fetch_bars(client, symbol, feed or FEEDS.get("iex"))

        if df is None or df.empty:
            metric.error = "no bars returned"
            return metric

        if symbol in df.index.get_level_values(0):
            df = df.loc[symbol]

        closes = df["close"]
        if len(closes) < 2:
            metric.error = "not enough history"
            return metric

        metric.value = float(closes.iloc[-1])
        metric.day_change = _pct_change(closes, 1)
        metric.week_change = _pct_change(closes, 5)
        metric.month_change = _pct_change(closes, 21)
        metric.as_of = to_iso_date(closes.index[-1])
        return metric
    except Exception as e:
        print(f"Bar fetch error for {symbol}: {type(e).__name__}")
        metric.error = "fetch failed"
        return metric


def get_etf_group(client, group_key, feed=None):
    return [get_etf_metric(client, symbol, label, feed)
            for symbol, label in ETF_GROUPS[group_key].items()]


def alpaca_snapshot(today=None):
    client = get_alpaca_client()

    if not client:
        snapshot = {
            key: [Metric(key=symbol, label=label, symbol=symbol,
                         source="alpaca", error="Alpaca auth failed")
                  for symbol, label in ETF_GROUPS[key].items()]
            for key in SECTOR_GROUP_KEYS
        }
        snapshot["price_source"] = None
        snapshot["price_source_note"] = None
        return snapshot

    feed_name, feed_note = resolve_feed(client)
    if feed_note:
        print(f"Alpaca feed: {feed_note}")

    snapshot = {key: get_etf_group(client, key, FEEDS[feed_name])
                for key in SECTOR_GROUP_KEYS}
    snapshot["price_source"] = f"alpaca:{feed_name}"
    snapshot["price_source_note"] = feed_note
    return snapshot


# --- entry point -----------------------------------------------------------

def get_sector_snapshot(today=None):
    """Returns {group_key: [Metric, ...]} for every key in SECTOR_GROUP_KEYS,
    plus "price_source" and "price_source_note" describing where the closes
    came from.

    Every tracked ETF always appears; a failure becomes an errored Metric so
    the report shows the outage per row instead of going quiet.
    """
    snapshot = (alpaca_snapshot(today) if ETF_SOURCE == "alpaca"
                else yahoo_snapshot(today))
    mark_staleness(all_metrics(snapshot), today)
    return snapshot


if __name__ == "__main__":
    snap = get_sector_snapshot()
    print(f"source: {snap.get('price_source')}")
    if snap.get("price_source_note"):
        print(f"note:   {snap['price_source_note']}")
    print()
    for key in SECTOR_GROUP_KEYS:
        print(f"{GROUP_TITLES[key]}:")
        for metric in snap[key]:
            print(f"  {metric.render_line()}")
        print()
