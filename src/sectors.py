import os
import sys
from datetime import datetime, timedelta

import yfinance as yf
import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

ALPACA_API_KEY = (os.getenv("ALPACA_API_KEY") or "").strip() or None
ALPACA_SECRET_KEY = (os.getenv("ALPACA_SECRET_KEY") or "").strip() or None
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"

US_ETFS = {
    "DIA": "Dow Jones",
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "SOXX": "Semiconductors",
    "PAVE": "Infrastructure",
    "IGV": "Software",
    "ITA": "Aerospace & Defense",
    "DRAM": "Memory & Storage",
}

KR_PROXY = {
    "EWY": "Korea (MSCI South Korea ETF)",
}


def get_alpaca_client():
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        print("Alpaca credentials are not configured; skipping sector fetch")
        return None
    try:
        return tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, api_version='v2')
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


def get_bars_change(api, ticker):
    """
    Fetches ~40 calendar days of daily bars from Alpaca in a single
    request (comfortably covers the ~25 trading days needed for the
    month lookback), and derives day/week/month percent changes from it.
    """
    try:
        start = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
        bars = api.get_bars(ticker, "1Day", start=start, limit=40).df

        if bars is None or bars.empty or len(bars) < 2:
            return None, None, None, None, None

        closes = bars["close"]
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
        timestamp = bars.index[-1].isoformat()

        return current_close, day_change, week_change, month_change, timestamp
    except Exception as e:
        print(f"Bar fetch error for {ticker}: {e}")
        return None, None, None, None, None


def get_exchange_rate():
    """
    Alpaca has no FX data, so USD/KRW is sourced from yfinance —
    same reliable source macro.py already uses successfully.
    """
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


def get_us_etf_data(api):
    results, market_time = [], None
    for symbol, name in US_ETFS.items():
        _, day_change, week_change, month_change, ts = get_bars_change(api, symbol)
        if day_change is not None:
            if not market_time and ts:
                market_time = ts
            results.append(f"{name} ({symbol}): {format_change_line(day_change, week_change, month_change)}")
        else:
            results.append(f"{name} ({symbol}): Data unavailable")
    return results, market_time


def get_kr_etf_data(api):
    results, market_time = [], None
    for symbol, name in KR_PROXY.items():
        _, day_change, week_change, month_change, ts = get_bars_change(api, symbol)
        if day_change is not None:
            if not market_time and ts:
                market_time = ts
            results.append(f"{name} ({symbol}): {format_change_line(day_change, week_change, month_change)}")
        else:
            results.append(f"{name} ({symbol}): Data unavailable")
    return results, market_time


def get_sector_snapshot():
    api = get_alpaca_client()
    if not api:
        return {"us": ["Auth failed"], "kr": ["Auth failed"], "fx": "N/A", "us_time": None, "kr_time": None}

    snapshot = {}
    us_data, us_time = get_us_etf_data(api)
    kr_data, kr_time = get_kr_etf_data(api)
    snapshot["us"] = us_data
    snapshot["kr"] = kr_data
    snapshot["us_time"] = us_time
    snapshot["kr_time"] = kr_time

    rate, arrow = get_exchange_rate()
    snapshot["fx"] = f"₩{rate} {arrow}" if rate else "N/A"

    return snapshot


if __name__ == "__main__":
    api = get_alpaca_client()
    if not api:
        print("Auth failed. Check your ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")
    else:
        print("✅ Auth successful\n")
        us_lines, _ = get_us_etf_data(api)
        print("🇺🇸 US ETFs:")
        for line in us_lines:
            print(f"  {line}")
        kr_lines, _ = get_kr_etf_data(api)
        print("\n🇰🇷 Korea Proxy:")
        for line in kr_lines:
            print(f"  {line}")
        rate, arrow = get_exchange_rate()
        print(f"\n💱 USD/KRW: ₩{rate} {arrow}")
