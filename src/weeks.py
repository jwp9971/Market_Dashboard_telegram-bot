"""
Monday-to-Friday weeks for the weekly commentary.

A week's close is the last observation inside its Mon-Fri window -- normally
Friday, Thursday when Friday is a holiday -- so no holiday calendar is
needed. 1W compares against the previous week's close, 1M four weeks back and
3M thirteen, all on week-end closes, never "the last 5 observations".

Every source hands in the same thing, a dated daily series
[(date or 'YYYY-MM-DD', value), ...] in any order, and weekly_metric() turns it
into a Metric, so the week rules live here and nowhere else.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from metrics import (CHANGE_LEVEL, CHANGE_PCT, US_SESSION_CLOSE_UTC_HOUR,
                     WEEKLY_HORIZONS, Metric, missing, to_iso_date)

FRIDAY = 4

# Weeks back for each change, keyed by the Metric field that holds it.
WEEKS_BACK = {"week_change": 1, "month_change": 4, "quarter_change": 13}
MAX_WEEKS_BACK = max(WEEKS_BACK.values())


def last_completed_week(now=None):
    """
    (monday, friday) of the latest week whose Friday US close has passed.

    Run mid-week, this is still the previous full week, so a report always
    covers the same span whenever it happens to run.
    """
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    today = now.date()
    friday = today - timedelta(days=(today.weekday() - FRIDAY) % 7)
    if friday == today and now.hour < US_SESSION_CLOSE_UTC_HOUR:
        friday -= timedelta(days=7)
    return friday - timedelta(days=FRIDAY), friday


def week_of(friday, weeks_back=0):
    """(monday, friday) of the week `weeks_back` weeks before the given one."""
    end = friday - timedelta(weeks=weeks_back)
    return end - timedelta(days=FRIDAY), end


def week_label(friday):
    """'Week of Sep 14–18', or 'Week of Sep 28 – Oct 2' across a month end."""
    monday = friday - timedelta(days=FRIDAY)
    if monday.month == friday.month:
        return f"Week of {monday.strftime('%b')} {monday.day}–{friday.day}"
    return (f"Week of {monday.strftime('%b')} {monday.day} – "
            f"{friday.strftime('%b')} {friday.day}")


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = to_iso_date(value)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date() if text else None
    except ValueError:
        return None


def normalise(series):
    """Sorted [(date, float)] with unusable rows dropped and one value per day."""
    by_day = {}
    for raw_day, value in series or ():
        day = _as_date(raw_day)
        if day is None or value is None:
            continue
        try:
            by_day[day] = float(value)
        except (TypeError, ValueError):
            continue
    return sorted(by_day.items())


def week_end_close(series, friday, weeks_back=0):
    """(date, value) of the last observation in that Mon-Fri week, or None."""
    monday, end = week_of(friday, weeks_back)
    inside = [row for row in normalise(series) if monday <= row[0] <= end]
    return inside[-1] if inside else None


def _change(current, prior, change_kind):
    if prior is None:
        return None
    if change_kind == CHANGE_LEVEL:
        return round(current - prior, 2)
    if prior == 0:
        return None
    return round((current / prior - 1) * 100, 2)


def weekly_metric(key, label, series, friday, unit, change_kind=CHANGE_PCT,
                  source="", symbol="", **kwargs):
    """
    A Metric for the week ending `friday`, with 1W / 1M / 3M changes.

    No observation inside the target week means the value is missing rather
    than quietly older: a weekly report must not present last week's number
    as this week's.
    """
    extra = dict(horizons=WEEKLY_HORIZONS, unit=unit, change_kind=change_kind, **kwargs)
    current = week_end_close(series, friday)
    if current is None:
        monday, _ = week_of(friday)
        return missing(key, label, source=source, symbol=symbol,
                       error=f"no data in the week of {monday.isoformat()}", **extra)

    as_of, value = current
    changes = {}
    for field, weeks_back in WEEKS_BACK.items():
        prior = week_end_close(series, friday, weeks_back)
        changes[field] = _change(value, prior[1] if prior else None, change_kind)

    return Metric(key=key, label=label, value=value, as_of=as_of.isoformat(),
                  source=source, symbol=symbol, **changes, **extra)
