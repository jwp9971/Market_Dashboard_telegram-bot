import os
import requests
from dotenv import load_dotenv
import yfinance as yf

load_dotenv()

FRED_API_KEY = (os.getenv("FRED_API_KEY") or "").strip() or None


def _format_number(value, digits=2):
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def _coerce_numeric(value):
    try:
        if value in (None, "", "nan", "NaN", "N/A", "."):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _arrow(value):
    return "▲" if value is not None and value >= 0 else "▼"


def format_pct_change_line(day_change, week_change=None, month_change=None):
    parts = []
    parts.append(f"{_arrow(day_change)}{abs(day_change):.2f}% D/D" if day_change is not None else "D/D N/A")
    if week_change is not None:
        parts.append(f"{_arrow(week_change)}{abs(week_change):.2f}% 1W")
    if month_change is not None:
        parts.append(f"{_arrow(month_change)}{abs(month_change):.2f}% 1M")
    return " | ".join(parts)


def format_level_change_line(day_change, week_change=None, month_change=None, unit="pts"):
    parts = []
    parts.append(f"{_arrow(day_change)}{abs(day_change):.2f}{unit} D/D" if day_change is not None else "D/D N/A")
    if week_change is not None:
        parts.append(f"{_arrow(week_change)}{abs(week_change):.2f}{unit} 1W")
    if month_change is not None:
        parts.append(f"{_arrow(month_change)}{abs(month_change):.2f}{unit} 1M")
    return " | ".join(parts)


def format_metric_value(current, change_line=None, prefix="", suffix=""):
    if current is None:
        return "N/A"
    base = f"{prefix}{_format_number(current)}{suffix}"
    if change_line:
        return f"{base} ({change_line})"
    return base


def _pct_change_from_series(closes, offset):
    try:
        if len(closes) <= offset:
            return None
        current = _coerce_numeric(closes.iloc[-1])
        prior = _coerce_numeric(closes.iloc[-1 - offset])
        if current is None or prior is None or prior == 0:
            return None
        return round(((current - prior) / prior) * 100, 2)
    except Exception:
        return None


def get_yfinance_series(ticker):
    """
    Returns (current, day_change_pct, week_change_pct, month_change_pct).
    Pulls 3 months of daily history in a single call so day/week/month
    changes all come from one fetch — no extra API calls versus before.
    """
    try:
        ticker_obj = yf.Ticker(ticker)
        history = ticker_obj.history(period="3mo", interval="1d", auto_adjust=False)
        history = history.dropna()

        if not history.empty:
            closes = history["Close"]
            current = _coerce_numeric(closes.iloc[-1])
            if current is not None:
                day_change = _pct_change_from_series(closes, 1)
                week_change = _pct_change_from_series(closes, 5)
                month_change = _pct_change_from_series(closes, 21)
                return current, day_change, week_change, month_change

        # Fallback if history is unavailable — at least return current price
        info = ticker_obj.fast_info
        current = _coerce_numeric(info.last_price)
        return current, None, None, None
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None, None, None, None


def _level_change(values, offset):
    if len(values) <= offset:
        return None
    return round(values[0] - values[offset], 2)


def get_fred_series(series_id, limit=40):
    """
    Returns (current, day_delta, week_delta, month_delta) as level
    changes (percentage points), since FRED rate/spread series are
    already expressed in %. Fetches up to `limit` recent observations
    in one call and derives day/week/month from valid (non-missing)
    values — still one API call per series, same as before.
    """
    if not FRED_API_KEY:
        print("FRED_API_KEY is not set; skipping FRED series fetch for", series_id)
        return None, None, None, None

    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        observations = data.get("observations", [])

        values = []
        for obs in observations:
            val = _coerce_numeric(obs.get("value"))
            if val is not None:
                values.append(val)

        if not values:
            return None, None, None, None

        current = values[0]
        day_change = _level_change(values, 1)
        week_change = _level_change(values, 5)
        month_change = _level_change(values, 21)

        return current, day_change, week_change, month_change
    except requests.RequestException as e:
        print(f"Error fetching FRED {series_id}: {e}")
        return None, None, None, None
    except Exception as e:
        print(f"Unexpected error fetching FRED {series_id}: {e}")
        return None, None, None, None


def get_macro_snapshot():
    snapshot = {}

    vix, vix_d, vix_w, vix_m = get_yfinance_series("^VIX")
    snapshot["VIX"] = format_metric_value(vix, format_pct_change_line(vix_d, vix_w, vix_m))

    wti, wti_d, wti_w, wti_m = get_yfinance_series("CL=F")
    snapshot["WTI"] = format_metric_value(wti, format_pct_change_line(wti_d, wti_w, wti_m), prefix="$")

    gold, gold_d, gold_w, gold_m = get_yfinance_series("GC=F")
    copper, copper_d, copper_w, copper_m = get_yfinance_series("HG=F")
    if gold and copper:
        snapshot["Gold"] = format_metric_value(gold, format_pct_change_line(gold_d, gold_w, gold_m), prefix="$")
        snapshot["Copper"] = format_metric_value(copper, format_pct_change_line(copper_d, copper_w, copper_m), prefix="$")
        snapshot["Gold/Copper Ratio"] = round(gold / copper, 2)

    ten_y, ten_y_d, ten_y_w, ten_y_m = get_fred_series("DGS10")
    two_y, two_y_d, two_y_w, two_y_m = get_fred_series("DGS2")
    snapshot["10Y Treasury"] = format_metric_value(ten_y, format_level_change_line(ten_y_d, ten_y_w, ten_y_m), suffix="%")
    snapshot["2Y Treasury"] = format_metric_value(two_y, format_level_change_line(two_y_d, two_y_w, two_y_m), suffix="%")

    if ten_y is not None and two_y is not None:
        spread = round(ten_y - two_y, 2)
        snapshot["2s10s Spread"] = f"{spread:.2f}%"

    hy_oas, hy_d, hy_w, hy_m = get_fred_series("BAMLH0A0HYM2")
    snapshot["HY OAS"] = format_metric_value(hy_oas, format_level_change_line(hy_d, hy_w, hy_m))

    ig_oas, ig_d, ig_w, ig_m = get_fred_series("BAMLC0A0CM")
    snapshot["IG OAS"] = format_metric_value(ig_oas, format_level_change_line(ig_d, ig_w, ig_m))

    dxy, dxy_d, dxy_w, dxy_m = get_yfinance_series("DX-Y.NYB")
    snapshot["Dollar Index"] = format_metric_value(dxy, format_pct_change_line(dxy_d, dxy_w, dxy_m))

    return snapshot


if __name__ == "__main__":
    data = get_macro_snapshot()
    print("\n📊 Macro Snapshot:")
    for key, value in data.items():
        print(f"  {key}: {value}")
