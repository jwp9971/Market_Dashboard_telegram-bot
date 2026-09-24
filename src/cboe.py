"""
VIX from Cboe's free, keyless daily history file (weekly commentary).

Massive Basic has no VIX. Cboe's CSV is the index publisher's own record, but
it can trail by a session or more: on 2026-09-24 05:00 UTC its last row was
still 09-22. The weekly snapshot therefore falls back to Yahoo when this file
has not reached the week's last session.
"""
import csv
import io
from datetime import datetime

import requests

VIX_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def parse_vix_history(text):
    """[('YYYY-MM-DD', close), ...] from the CSV (DATE as MM/DD/YYYY)."""
    rows = []
    for record in csv.DictReader(io.StringIO(text or "")):
        try:
            day = datetime.strptime(record["DATE"].strip(), "%m/%d/%Y").date()
            close = float(record["CLOSE"])
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        rows.append((day.isoformat(), close))
    return rows


def get_vix_series(http_get=None):
    """The whole daily VIX history, oldest first, or [] if the fetch fails."""
    http_get = http_get or requests.get
    try:
        response = http_get(VIX_HISTORY_URL, timeout=30)
        if response.status_code != 200:
            print(f"Cboe VIX history -> HTTP {response.status_code}")
            return []
        rows = parse_vix_history(response.text)
        print(f"Cboe VIX history -> 200, {len(rows)} rows")
        return rows
    except requests.RequestException as e:
        print(f"Cboe VIX history failed: {type(e).__name__}")
        return []
