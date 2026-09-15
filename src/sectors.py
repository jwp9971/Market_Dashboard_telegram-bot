import os
import sys
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from metrics import CHANGE_PCT, UNIT_USD, Metric, to_iso_date

ALPACA_API_KEY = (os.getenv("ALPACA_API_KEY") or "").strip() or None
ALPACA_SECRET_KEY = (os.getenv("ALPACA_SECRET_KEY") or "").strip() or None

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


def get_etf_metric(client, symbol, label):
    """Fetches one ETF and returns it as a Metric, including the observation
    date of the bar the changes were computed from."""
    metric = Metric(key=symbol, label=label, symbol=symbol,
                    unit=UNIT_USD, change_kind=CHANGE_PCT, source="alpaca")
    try:
        # Explicit UTC: Alpaca treats a naive datetime as UTC, so a laptop in
        # Korea and a UTC runner would otherwise request different windows.
        end = datetime.now(timezone.utc)
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=end - timedelta(days=40),
            end=end,
            feed=DataFeed.IEX,
        )
        df = client.get_stock_bars(request).df

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


def get_etf_group(client, group_key):
    return [get_etf_metric(client, symbol, label)
            for symbol, label in ETF_GROUPS[group_key].items()]


def get_sector_snapshot():
    """Returns {group_key: [Metric, ...]} for every key in SECTOR_GROUP_KEYS.

    On an auth failure every ETF still appears, marked with an error, so the
    report shows what is missing instead of going quiet.
    """
    client = get_alpaca_client()

    if not client:
        return {
            key: [Metric(key=symbol, label=label, symbol=symbol,
                         source="alpaca", error="Alpaca auth failed")
                  for symbol, label in ETF_GROUPS[key].items()]
            for key in SECTOR_GROUP_KEYS
        }

    return {key: get_etf_group(client, key) for key in SECTOR_GROUP_KEYS}


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
            for metric in get_etf_group(client, key):
                print(f"  {metric.render_line()}")
            print()
