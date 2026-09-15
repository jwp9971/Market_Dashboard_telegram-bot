import os
import sys
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment, DataFeed
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from metrics import (MAX_AGE_MARKET_DAYS, CHANGE_PCT, UNIT_USD, Metric,
                     mark_staleness, to_iso_date)

ALPACA_API_KEY = (os.getenv("ALPACA_API_KEY") or "").strip() or None
ALPACA_SECRET_KEY = (os.getenv("ALPACA_SECRET_KEY") or "").strip() or None

# IEX is a single exchange carrying a low single-digit share of consolidated
# volume, so its daily close for a thinly traded ETF can be built from a
# handful of prints -- or be missing. SIP is the consolidated tape. Prefer it,
# and if the account is not entitled, fall back but say so in the report.
FEEDS = {"sip": DataFeed.SIP, "iex": DataFeed.IEX}
PREFERRED_FEED = (os.getenv("ALPACA_FEED") or "sip").strip().lower()

# Raw prices show a split as a real move. Split adjustment is the minimum
# correct policy; dividends are deliberately NOT adjusted, so these are price
# returns, not total returns. That choice is documented in the README.
ADJUSTMENT = Adjustment.SPLIT

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

# The group keys get_sector_snapshot() returns. analyst.py and dashboard.py
# import this instead of hardcoding key names, so renaming a group here is a
# one-line change that can't silently orphan a downstream consumer.
SECTOR_GROUP_KEYS = ("macro", "broad_industry", "theme")

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


def get_alpaca_client():
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
    """Fetches one ETF as a Metric, including the observation date of the bar
    the changes were computed from."""
    metric = Metric(key=symbol, label=label, symbol=symbol,
                    unit=UNIT_USD, change_kind=CHANGE_PCT, source="alpaca",
                    max_age_days=MAX_AGE_MARKET_DAYS)
    try:
        df = _fetch_bars(client, symbol, feed or FEEDS["iex"])

        if df is None or df.empty:
            metric.error = "no bars returned"
            return metric

        if symbol in df.index.get_level_values(0):
            df = df.loc[symbol]

        closes = df["close"]
        if len(closes) < 2:
            metric.error = "not enough history"
            return metric

        current = float(closes.iloc[-1])

        def pct_change(offset):
            if len(closes) <= offset:
                return None
            prior = float(closes.iloc[-1 - offset])
            if prior == 0:
                return None
            return round(((current - prior) / prior) * 100, 2)

        metric.value = current
        metric.day_change = pct_change(1)
        metric.week_change = pct_change(5)
        metric.month_change = pct_change(21)
        metric.as_of = to_iso_date(closes.index[-1])
        return metric
    except Exception as e:
        print(f"Bar fetch error for {symbol}: {type(e).__name__}")
        metric.error = "fetch failed"
        return metric


def get_etf_group(client, group_key, feed=None):
    return [get_etf_metric(client, symbol, label, feed)
            for symbol, label in ETF_GROUPS[group_key].items()]


def get_sector_snapshot(today=None):
    """Returns {group_key: [Metric, ...]} for every key in SECTOR_GROUP_KEYS,
    plus "feed" and "feed_note" describing which tape actually served the run.

    On an auth failure every ETF still appears, marked with an error, so the
    report shows the outage per row instead of going quiet.
    """
    client = get_alpaca_client()

    if not client:
        snapshot = {
            key: [Metric(key=symbol, label=label, symbol=symbol,
                         source="alpaca", error="Alpaca auth failed")
                  for symbol, label in ETF_GROUPS[key].items()]
            for key in SECTOR_GROUP_KEYS
        }
        snapshot["feed"] = None
        snapshot["feed_note"] = None
        return snapshot

    feed_name, feed_note = resolve_feed(client)
    if feed_note:
        print(f"Alpaca feed: {feed_note}")

    snapshot = {key: get_etf_group(client, key, FEEDS[feed_name])
                for key in SECTOR_GROUP_KEYS}
    snapshot["feed"] = feed_name
    snapshot["feed_note"] = feed_note

    mark_staleness(all_metrics(snapshot), today)
    return snapshot


def all_metrics(sector_snapshot):
    """Flattens every group into one list, in group order."""
    return [m for key in SECTOR_GROUP_KEYS for m in sector_snapshot.get(key, []) or []]


if __name__ == "__main__":
    client = get_alpaca_client()
    if not client:
        print("Auth failed. Check ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")
    else:
        print("✅ Auth successful\n")
        for key in SECTOR_GROUP_KEYS:
            print(f"{GROUP_TITLES[key]}:")
            for metric in get_etf_group(client, key, FEEDS[feed_name]):
                print(f"  {metric.render_line()}")
            print()
