import math
import os
import sys

import requests
from dotenv import load_dotenv
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))

from metrics import (
    CHANGE_LEVEL,
    CHANGE_PCT,
    UNIT_INDEX,
    UNIT_KRW,
    UNIT_PERCENT,
    UNIT_RATIO,
    UNIT_USD,
    Metric,
    to_iso_date,
)

load_dotenv()

FRED_API_KEY = (os.getenv("FRED_API_KEY") or "").strip() or None


def _coerce_numeric(value):
    """Returns a finite float, or None. NaN and inf are treated as missing
    so they can never reach a formatted message as 'nan%'."""
    try:
        if value in (None, "", "nan", "NaN", "N/A", "."):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


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


def _level_change(values, offset):
    if len(values) <= offset:
        return None
    return round(values[0] - values[offset], 2)


def _subtract(a, b):
    """Difference of two optional numbers, or None if either is missing."""
    if a is None or b is None:
        return None
    return round(a - b, 2)


def get_yfinance_series(ticker):
    """
    Returns (current, day_pct, week_pct, month_pct, as_of).

    Pulls 3 months of daily history in one call so day/week/month changes all
    come from one fetch. The observation date is carried through rather than
    discarded, so the report can disclose how current each series actually is.
    """
    try:
        ticker_obj = yf.Ticker(ticker)
        history = ticker_obj.history(period="3mo", interval="1d", auto_adjust=False)
        history = history.dropna()

        if not history.empty:
            closes = history["Close"]
            current = _coerce_numeric(closes.iloc[-1])
            if current is not None:
                return (
                    current,
                    _pct_change_from_series(closes, 1),
                    _pct_change_from_series(closes, 5),
                    _pct_change_from_series(closes, 21),
                    to_iso_date(closes.index[-1]),
                )

        # Last resort: a live quote with no history to derive changes from.
        info = ticker_obj.fast_info
        return _coerce_numeric(info.last_price), None, None, None, None
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None, None, None, None, None


def get_fred_series(series_id, limit=40):
    """
    Returns (current, day_delta, week_delta, month_delta, as_of) as level
    changes in percentage points, since FRED rate/spread series are already
    expressed in %. One API call per series.
    """
    if not FRED_API_KEY:
        print("FRED_API_KEY is not set; skipping FRED series fetch for", series_id)
        return None, None, None, None, None

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
        observations = response.json().get("observations", [])

        values, dates = [], []
        for obs in observations:
            value = _coerce_numeric(obs.get("value"))
            if value is not None:
                values.append(value)
                dates.append(obs.get("date"))

        if not values:
            return None, None, None, None, None

        return (
            values[0],
            _level_change(values, 1),
            _level_change(values, 5),
            _level_change(values, 21),
            to_iso_date(dates[0]),
        )
    except requests.RequestException as e:
        # The request URL carries the API key, and requests puts the URL in
        # its exception text -- log the status and series only.
        status = getattr(getattr(e, "response", None), "status_code", "no response")
        print(f"Error fetching FRED {series_id}: HTTP {status}")
        return None, None, None, None, None
    except Exception as e:
        print(f"Unexpected error fetching FRED {series_id}: {type(e).__name__}")
        return None, None, None, None, None


def _yahoo_metric(key, label, ticker, unit=UNIT_INDEX):
    value, day, week, month, as_of = get_yfinance_series(ticker)
    return Metric(
        key=key, label=label, value=value,
        day_change=day, week_change=week, month_change=month,
        unit=unit, change_kind=CHANGE_PCT,
        as_of=as_of, source="yahoo",
    )


def _fred_metric(key, label, series_id, unit=UNIT_PERCENT):
    value, day, week, month, as_of = get_fred_series(series_id)
    return Metric(
        key=key, label=label, value=value,
        day_change=day, week_change=week, month_change=month,
        unit=unit, change_kind=CHANGE_LEVEL,
        as_of=as_of, source="fred",
    )


def get_macro_snapshot():
    """Returns an ordered {key: Metric} mapping. Every metric is always
    present; a failed fetch produces a metric with status 'missing' so the
    gap is visible rather than silently absent."""
    snapshot = {}

    snapshot["VIX"] = _yahoo_metric("VIX", "VIX", "^VIX")
    snapshot["WTI"] = _yahoo_metric("WTI", "WTI Crude", "CL=F", unit=UNIT_USD)

    gold = _yahoo_metric("Gold", "Gold", "GC=F", unit=UNIT_USD)
    copper = _yahoo_metric("Copper", "Copper", "HG=F", unit=UNIT_USD)
    snapshot["Gold"] = gold
    snapshot["Copper"] = copper
    snapshot["Gold/Copper"] = Metric(
        key="Gold/Copper", label="Gold/Copper Ratio",
        value=(round(gold.value / copper.value, 2)
               if gold.value is not None and copper.value else None),
        unit=UNIT_RATIO, tracks_changes=False,
        as_of=gold.as_of or copper.as_of, source="yahoo",
    )

    ten_y = _fred_metric("10Y", "10Y Treasury", "DGS10")
    two_y = _fred_metric("2Y", "2Y Treasury", "DGS2")
    snapshot["10Y"] = ten_y
    snapshot["2Y"] = two_y

    # A spread's change is the difference of its legs' changes, so 2s10s now
    # carries a real change line instead of a bare level.
    snapshot["2s10s"] = Metric(
        key="2s10s", label="2s10s Spread",
        value=_subtract(ten_y.value, two_y.value),
        day_change=_subtract(ten_y.day_change, two_y.day_change),
        week_change=_subtract(ten_y.week_change, two_y.week_change),
        month_change=_subtract(ten_y.month_change, two_y.month_change),
        unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL,
        as_of=ten_y.as_of or two_y.as_of, source="fred",
    )

    # Option-adjusted spreads are quoted in percent; a bare "2.91" is ambiguous.
    snapshot["HY OAS"] = _fred_metric("HY OAS", "HY OAS", "BAMLH0A0HYM2")
    snapshot["IG OAS"] = _fred_metric("IG OAS", "IG OAS", "BAMLC0A0CM")

    snapshot["DXY"] = _yahoo_metric("DXY", "Dollar Index", "DX-Y.NYB")

    # USD/KRW lives here with the other Yahoo series rather than in sectors.py,
    # where it used to be unreachable whenever Alpaca credentials failed.
    snapshot["USDKRW"] = _yahoo_metric("USDKRW", "USD/KRW", "USDKRW=X", unit=UNIT_KRW)

    return snapshot


if __name__ == "__main__":
    for metric in get_macro_snapshot().values():
        stamp = f"  [as of {metric.format_as_of()}]" if metric.as_of else ""
        print(f"  {metric.render_line()}{stamp}")
