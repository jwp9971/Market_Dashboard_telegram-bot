import os
import sys
from datetime import datetime, timedelta

import yfinance as yf
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

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


def get_alpaca_client():
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("Alpaca credentials are not configured; skipping sector fetch")
        return None
    try:
        return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    except Exception as e:
        print(f"Alpaca client error: {e}")
        return None


def format_change_line(day_change, week_change=None, month_change=None):
    day_arrow = "▲" if day_change is not None and day_change >= 0 else "▼"
    day_text = f"{day_arrow}{abs(day_change):.2f}% D/D" if day_change is not None else "D/D N/A"

    parts = [day_text]
    if week_change is not None:
        week_arrow = "▲" if week_change >= 0 else "▼"
        parts.append(f"{week_arrow}{abs(week_change):.2f}% 1W")
    if month_change is not None:
        month_arrow = "▲" if month_change >= 0 else "▼"
        parts.append(f"{month_arrow}{abs(month_change):.2f}% 1M")

    return " | ".join(parts)


def get_bars_change(client, ticker):
    try:
        end = datetime.now()
        start = end - timedelta(days=40)
        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed=DataFeed.IEX,
        )
        bars = client.get_stock_bars(request)
        df = bars.df

        if df is None or df.empty:
            return None, None, None, None, None

        if ticker in df.index.get_level_values(0):
            df = df.loc[ticker]

        closes = df["close"]
        if len(closes) < 2:
            return None, None, None, None, None

        current_close = float(closes.iloc[-1])

        def pct_change(offset):
            if len(closes) <= offset:
                return None
            prior = float(closes.iloc[-1 - offset])
            if prior == 0:
                return None
            return round(((current_close - prior) / prior) * 100, 2)

        day_change = pct_change(1)
        week_change = pct_change(5)
        month_change = pct_change(21)

        ts = closes.index[-1]
        timestamp = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        return current_close, day_change, week_change, month_change, timestamp
    except Exception as e:
        print(f"Bar fetch error for {ticker}: {e}")
        return None, None, None, None, None


def get_exchange_rate():
    try:
        history = yf.Ticker("USDKRW=X").history(period="5d", interval="1d").dropna()
        if len(history) < 2:
            return None, None
        current = float(history["Close"].iloc[-1])
        prev = float(history["Close"].iloc[-2])
        arrow = "▲" if current >= prev else "▼"
        return round(current, 1), arrow
    except Exception as e:
        print(f"Exchange rate error: {e}")
        return None, None


def get_etf_group_data(client, etf_dict):
    results, group_time = [], None
    for symbol, name in etf_dict.items():
        _, day_change, week_change, month_change, ts = get_bars_change(client, symbol)
        if day_change is not None:
            if not group_time and ts:
                group_time = ts
            results.append(f"{name} ({symbol}): {format_change_line(day_change, week_change, month_change)}")
        else:
            results.append(f"{name} ({symbol}): Data unavailable")
    return results, group_time


def _format_fx():
    rate, arrow = get_exchange_rate()
    return f"₩{rate} {arrow}" if rate else "N/A"


def get_sector_snapshot():
    client = get_alpaca_client()
    if not client:
        # FX comes from Yahoo, not Alpaca, so it is still available here.
        return {
            "macro": ["Auth failed"],
            "broad_industry": ["Auth failed"],
            "theme": ["Auth failed"],
            "fx": _format_fx(),
            "market_time": None,
        }

    macro_data, macro_time = get_etf_group_data(client, MACRO_ETFS)
    industry_data, industry_time = get_etf_group_data(client, BROAD_INDUSTRY_ETFS)
    theme_data, theme_time = get_etf_group_data(client, THEME_ETFS)

    return {
        "macro": macro_data,
        "broad_industry": industry_data,
        "theme": theme_data,
        "market_time": macro_time or industry_time or theme_time,
        "fx": _format_fx(),
    }


if __name__ == "__main__":
    client = get_alpaca_client()
    if not client:
        print("Auth failed. Check your ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")
    else:
        print("✅ Auth successful\n")
        for label, group in [("🌍 MACRO", MACRO_ETFS), ("🏭 BROAD INDUSTRY", BROAD_INDUSTRY_ETFS), ("🎯 THEME", THEME_ETFS)]:
            lines, _ = get_etf_group_data(client, group)
            print(f"{label}:")
            for line in lines:
                print(f"  {line}")
            print()
        rate, arrow = get_exchange_rate()
        print(f"💱 USD/KRW: ₩{rate} {arrow}")
