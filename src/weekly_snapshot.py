"""
The weekly commentary's data: every number for the last completed Mon-Fri
week as a Metric with 1W / 1M / 3M changes.

    Massive  22 ETFs (grouped daily), 10Y / 2Y / 2s10s, WTI / gold / copper
    FRED     HY and IG OAS
    Cboe     VIX, falling back to Yahoo ^VIX when the Cboe file is behind
    Yahoo    DXY

Each source is isolated: one failing leaves its rows missing (with the reason)
instead of sinking the run. Running this file prints the snapshot for a local
check -- never in Actions, whose logs are public (see CLAUDE.md, Massive terms).
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import cboe
import macro
import massive
from massive_client import MassiveClient
from metrics import (CHANGE_LEVEL, CHANGE_PCT, UNIT_INDEX, UNIT_PERCENT,
                     WEEKLY_HORIZONS, missing)
from sectors import ETF_GROUPS, SECTOR_GROUP_KEYS
from weeks import last_completed_week, week_end_close, week_label, weekly_metric

# ETFs 4-6, yields 1, futures up to 15: a run needing more than this is a bug.
WEEKLY_CALL_BUDGET = 25

# FRED returns the newest observations first; 13 weeks is ~65 business days.
FRED_OBSERVATIONS = 100
YAHOO_PERIOD = "6mo"

MACRO_ORDER = ("VIX", "WTI", "Gold", "Copper", "Gold/Copper", "10Y", "2Y", "2s10s",
               "HY OAS", "IG OAS", "DXY")
MACRO_LABELS = {"VIX": "VIX", "WTI": "WTI Crude", "Gold": "Gold", "Copper": "Copper",
                "Gold/Copper": "Gold/Copper Ratio", "10Y": "10Y Treasury",
                "2Y": "2Y Treasury", "2s10s": "2s10s Spread", "HY OAS": "HY OAS",
                "IG OAS": "IG OAS", "DXY": "Dollar Index"}


def _failed(keys, source, exc):
    """Missing rows for every key a source should have produced."""
    reason = f"{source} failed: {type(exc).__name__}"
    print(reason)
    return {key: missing(key, MACRO_LABELS[key], source=source, error=reason,
                         horizons=WEEKLY_HORIZONS) for key in keys}


def vix_metric(friday, notes):
    """
    Cboe first; Yahoo when Cboe has not reached the week's last session.
    Whichever wins supplies all of the week's changes, so they come from one
    consistent series.
    """
    series, source = cboe.get_vix_series(), "cboe"
    close = week_end_close(series, friday)
    if close is None or close[0] < friday:
        fallback = macro.get_yfinance_closes("^VIX", YAHOO_PERIOD)
        other = week_end_close(fallback, friday)
        if other and (close is None or other[0] > close[0]):
            last = series[-1][0] if series else "no data"
            notes.append(f"VIX: the Cboe file ends {last}, so Yahoo ^VIX was used")
            series, source = fallback, "yahoo"
    return weekly_metric("VIX", "VIX", series, friday, UNIT_INDEX, CHANGE_PCT, source=source)


def fred_metric(key, series_id, friday):
    rows = macro.get_fred_observations(series_id, FRED_OBSERVATIONS)
    return weekly_metric(key, MACRO_LABELS[key], rows, friday, UNIT_PERCENT,
                         CHANGE_LEVEL, source="fred")


def _collect(macro_rows, keys, source, collector):
    try:
        macro_rows.update(collector())
    except Exception as exc:
        macro_rows.update(_failed(keys, source, exc))


def source_notes(contracts):
    """
    Where numbers came from -- facts only the collection knows. Notes derived
    from the rows themselves (missing, dated early, ...) are written by
    weekly_dashboard, as dashboard.py does for the daily report.
    """
    if not contracts:
        return []
    return ["Commodities: official settlement of the most-traded nearby contract ("
            + ", ".join(contracts) + ")"]


def get_weekly_snapshot(now=None, client=None):
    """
    {"week": (monday, friday), "label": str, "macro": {key: Metric},
     "etfs": {group: [Metric]}, "notes": [str], "massive_calls": int}
    """
    now = now or datetime.now(timezone.utc)
    monday, friday = last_completed_week(now)
    client = client or MassiveClient(max_calls=WEEKLY_CALL_BUDGET)
    notes, rows = [], {}

    _collect(rows, ["VIX"], "cboe", lambda: {"VIX": vix_metric(friday, notes)})
    _collect(rows, ["WTI", "Gold", "Copper", "Gold/Copper"], "massive",
             lambda: massive.get_futures_metrics(client, friday))
    _collect(rows, ["10Y", "2Y", "2s10s"], "massive",
             lambda: massive.get_yield_metrics(client, friday))
    _collect(rows, ["HY OAS"], "fred", lambda: {"HY OAS": fred_metric("HY OAS", "BAMLH0A0HYM2", friday)})
    _collect(rows, ["IG OAS"], "fred", lambda: {"IG OAS": fred_metric("IG OAS", "BAMLC0A0CM", friday)})
    _collect(rows, ["DXY"], "yahoo", lambda: {"DXY": weekly_metric(
        "DXY", "Dollar Index", macro.get_yfinance_closes("DX-Y.NYB", YAHOO_PERIOD),
        friday, UNIT_INDEX, CHANGE_PCT, source="yahoo")})

    try:
        etfs = massive.get_etf_snapshot(client, friday, now)
    except Exception as exc:
        reason = f"massive failed: {type(exc).__name__}"
        print(reason)
        etfs = {group: [missing(symbol, label, source="massive", symbol=symbol,
                                error=reason, horizons=WEEKLY_HORIZONS)
                        for symbol, label in ETF_GROUPS[group].items()]
                for group in SECTOR_GROUP_KEYS}

    macro_rows = {key: rows[key] for key in MACRO_ORDER if key in rows}
    contracts = [m.symbol for key, m in macro_rows.items()
                 if key in massive.FUTURES and m.value is not None]
    notes = notes + source_notes(contracts)
    print(f"Weekly snapshot: {client.calls_made} live Massive calls "
          f"{client.calls_by_class}, {client.cache_hits} cache hits")
    return {"week": (monday, friday), "label": week_label(friday), "macro": macro_rows,
            "etfs": etfs, "notes": notes, "massive_calls": client.calls_made}


if __name__ == "__main__":
    snapshot = get_weekly_snapshot()
    if os.getenv("GITHUB_ACTIONS") == "true":
        # Actions logs are public and Massive data may not be published.
        print("Values not printed in Actions.")
        sys.exit(0)
    print(f"\n{snapshot['label']}")
    for metric in snapshot["macro"].values():
        stamp = f"  [as of {metric.format_as_of()}]" if metric.as_of else ""
        print(f"  {metric.render_line()}{stamp}")
    for group in SECTOR_GROUP_KEYS:
        print(f"\n  {group}")
        for metric in snapshot["etfs"][group]:
            print(f"    {metric.render_line()}")
    print()
    for note in snapshot["notes"]:
        print(f"  note: {note}")
