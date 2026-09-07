import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

TOSS_CLIENT_ID = (os.getenv("TOSS_APP_KEY") or "").strip() or None
TOSS_CLIENT_SECRET = (os.getenv("TOSS_APP_SECRET") or "").strip() or None
TOSS_BASE = "https://openapi.tossinvest.com"

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
    "EWJ": "Japan MSCI",
}

KR_ETFS = {
    "069500": "KODEX 200",
    "091160": "KODEX 반도체",
    "305720": "KODEX 2차전지산업",
    "091170": "KODEX 은행",
    "244580": "KODEX 바이오",
    "487240": "KODEX AI전력핵심설비",
    "466920": "SOL 조선TOP3플러스",
    "449450": "PLUS K방산",
}


def get_toss_token():
    if not TOSS_CLIENT_ID or not TOSS_CLIENT_SECRET:
        print("TOSS credentials are not configured; skipping sector fetch")
        return None

    try:
        response = requests.post(
            f"{TOSS_BASE}/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": TOSS_CLIENT_ID,
                "client_secret": TOSS_CLIENT_SECRET,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if "access_token" in data:
            return data["access_token"]
        else:
            print(f"Toss auth error: {data}")
            return None
    except Exception as e:
        print(f"Toss auth error: {e}")
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


def get_candle_change(token, symbol, retries=2, backoff_seconds=2):
    """
    Fetches 25 daily candles for a symbol. Retries once or twice on
    a 429 (rate limit) with a short backoff, since Toss's API can
    throttle bursts when many tickers are requested back-to-back.
    """
    for attempt in range(retries + 1):
        try:
            response = requests.get(
                f"{TOSS_BASE}/api/v1/candles",
                headers={"Authorization": f"Bearer {token}"},
                params={"symbol": symbol, "interval": "1d", "count": 25},
                timeout=15,
            )

            if response.status_code == 429:
                if attempt < retries:
                    print(f"Rate limited on {symbol}, retrying in {backoff_seconds}s...")
                    time.sleep(backoff_seconds)
                    continue
                else:
                    print(f"Rate limited on {symbol}, out of retries")
                    return None, None, None, None, None

            response.raise_for_status()
            data = response.json()
            candles = data.get("result", {}).get("candles", [])

            if len(candles) < 2:
                return None, None, None, None, None

            current_close = float(candles[0]["closePrice"])
            prev_close = float(candles[1]["closePrice"])
            day_change = round(((current_close - prev_close) / prev_close) * 100, 2)

            week_change = None
            if len(candles) >= 8:
                week_close = float(candles[7]["closePrice"])
                week_change = round(((current_close - week_close) / week_close) * 100, 2)

            month_change = None
            if len(candles) >= 23:
                month_close = float(candles[22]["closePrice"])
                month_change = round(((current_close - month_close) / month_close) * 100, 2)

            timestamp = candles[0].get("timestamp")
            return current_close, day_change, week_change, month_change, timestamp

        except Exception as e:
            print(f"Candle error for {symbol}: {e}")
            return None, None, None, None, None

    return None, None, None, None, None


def get_exchange_rate(token):
    try:
        response = requests.get(
            f"{TOSS_BASE}/api/v1/exchange-rate",
            headers={"Authorization": f"Bearer {token}"},
            params={"baseCurrency": "USD", "quoteCurrency": "KRW"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        result = data.get("result", {})
        rate = result.get("rate")
        change_type = result.get("rateChangeType", "")
        arrow = "▲" if change_type == "UP" else "▼" if change_type == "DOWN" else "─"
        return rate, arrow
    except Exception as e:
        print(f"Exchange rate error: {e}")
        return None, None


def get_us_etf_data(token):
    results = []
    market_time = None
    for symbol, name in US_ETFS.items():
        _, day_change, week_change, month_change, ts = get_candle_change(token, symbol)
        if day_change is not None:
            if not market_time and ts:
                market_time = ts
            results.append(f"{name} ({symbol}): {format_change_line(day_change, week_change, month_change)}")
        else:
            results.append(f"{name} ({symbol}): Data unavailable")
        time.sleep(0.3)  # small pacing gap to avoid bursting the rate limit
    return results, market_time


def get_kr_etf_data(token):
    results = []
    market_time = None
    for code, name in KR_ETFS.items():
        _, day_change, week_change, month_change, ts = get_candle_change(token, code)
        if day_change is not None:
            if not market_time and ts:
                market_time = ts
            results.append(f"{name}: {format_change_line(day_change, week_change, month_change)}")
        else:
            results.append(f"{name}: Data unavailable")
        time.sleep(0.3)  # small pacing gap to avoid bursting the rate limit
    return results, market_time


def get_sector_snapshot():
    token = get_toss_token()
    if not token:
        return {"us": ["Auth failed"], "kr": ["Auth failed"], "fx": "N/A", "us_time": None, "kr_time": None}

    snapshot = {}
    us_data, us_time = get_us_etf_data(token)
    kr_data, kr_time = get_kr_etf_data(token)
    snapshot["us"] = us_data
    snapshot["kr"] = kr_data
    snapshot["us_time"] = us_time
    snapshot["kr_time"] = kr_time

    rate, arrow = get_exchange_rate(token)
    snapshot["fx"] = f"₩{rate} {arrow}" if rate else "N/A"

    return snapshot


if __name__ == "__main__":
    token = get_toss_token()
    if not token:
        print("Auth failed. Check your TOSS_APP_KEY and TOSS_APP_SECRET in .env")
    else:
        print("✅ Auth successful\n")

        us_lines, _ = get_us_etf_data(token)
        print("🇺🇸 US ETFs:")
        for line in us_lines:
            print(f"  {line}")

        kr_lines, _ = get_kr_etf_data(token)
        print("\n🇰🇷 Korean ETFs:")
        for line in kr_lines:
            print(f"  {line}")

        rate, arrow = get_exchange_rate(token)
        print(f"\n💱 USD/KRW: ₩{rate} {arrow}")
