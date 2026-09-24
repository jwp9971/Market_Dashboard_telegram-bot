"""
Mon-Fri week rules (weeks.py) and the weekly horizons on Metric.

Explicit now= everywhere: the week a report covers is exactly the kind of
thing that must not depend on the day the suite happens to run.
"""
from datetime import date, datetime, timezone

from metrics import CHANGE_LEVEL, CHANGE_PCT, UNIT_PERCENT, UNIT_USD, WEEKLY_HORIZONS, Metric
from weeks import (last_completed_week, normalise, week_end_close, week_label,
                   weekly_metric)

FRIDAY = date(2026, 9, 18)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# --- which week ----------------------------------------------------------------

def test_a_weekend_run_covers_the_week_just_ended():
    assert last_completed_week(utc(2026, 9, 19, 12)) == (date(2026, 9, 14), FRIDAY)


def test_a_midweek_run_still_covers_the_last_full_week():
    assert last_completed_week(utc(2026, 9, 16, 12)) == (date(2026, 9, 7), date(2026, 9, 11))


def test_friday_only_counts_once_the_us_close_has_passed():
    assert last_completed_week(utc(2026, 9, 18, 20, 59))[1] == date(2026, 9, 11)
    assert last_completed_week(utc(2026, 9, 18, 21, 0))[1] == FRIDAY


def test_a_kst_morning_run_on_saturday_is_fridays_week():
    # 08:00 KST Saturday is 23:00 UTC Friday, after the close.
    kst_saturday_8am = utc(2026, 9, 18, 23)
    assert last_completed_week(kst_saturday_8am)[1] == FRIDAY


def test_labels_read_naturally_within_and_across_months():
    assert week_label(FRIDAY) == "Week of Sep 14–18"
    assert week_label(date(2026, 10, 2)) == "Week of Sep 28 – Oct 2"


# --- week-end closes -----------------------------------------------------------

def test_the_weeks_close_is_friday():
    series = [("2026-09-17", 1.0), ("2026-09-18", 2.0), ("2026-09-21", 3.0)]
    assert week_end_close(series, FRIDAY) == (FRIDAY, 2.0)


def test_a_holiday_friday_falls_back_to_thursday():
    # 2026-06-19 (Juneteenth) is a real Friday market holiday.
    series = [("2026-06-17", 1.0), ("2026-06-18", 2.0)]
    assert week_end_close(series, date(2026, 6, 19)) == (date(2026, 6, 18), 2.0)


def test_an_empty_week_has_no_close_rather_than_last_weeks():
    series = [("2026-09-11", 1.0)]
    assert week_end_close(series, FRIDAY) is None


def test_normalise_sorts_dedupes_and_drops_junk():
    rows = [("2026-09-18", "2"), (date(2026, 9, 17), 1.0), ("2026-09-18", 3.0),
            ("bad", 1.0), ("2026-09-16", None), ("2026-09-15", "n/a")]
    assert normalise(rows) == [(date(2026, 9, 17), 1.0), (FRIDAY, 3.0)]


# --- weekly_metric -------------------------------------------------------------

WEEKLY_SERIES = [
    ("2026-06-18", 80.0),   # 13 weeks back (Friday 06-19 was a holiday)
    ("2026-08-21", 95.0),   # 4 weeks back
    ("2026-09-11", 100.0),  # 1 week back
    ("2026-09-14", 104.0),
    ("2026-09-18", 110.0),  # this week
]


def test_percent_changes_come_from_week_end_closes():
    m = weekly_metric("SPY", "S&P 500", WEEKLY_SERIES, FRIDAY, UNIT_USD, CHANGE_PCT)
    assert m.value == 110.0 and m.as_of == "2026-09-18"
    assert m.week_change == 10.0
    assert m.month_change == 15.79
    assert m.quarter_change == 37.5
    assert m.day_change is None
    assert m.status == "ok"


def test_level_changes_for_rates():
    series = [("2026-09-11", 4.10), ("2026-09-18", 4.25)]
    m = weekly_metric("10Y", "10Y", series, FRIDAY, UNIT_PERCENT, CHANGE_LEVEL)
    assert m.week_change == 0.15
    assert m.month_change is None and m.quarter_change is None


def test_no_data_this_week_is_missing_with_a_reason():
    m = weekly_metric("VIX", "VIX", [("2026-09-11", 15.0)], FRIDAY, UNIT_USD)
    assert m.status == "error"
    assert m.error == "no data in the week of 2026-09-14"
    assert m.horizons == WEEKLY_HORIZONS


def test_weekly_rows_render_1w_1m_3m_and_no_daily_change():
    m = weekly_metric("SPY", "S&P 500", WEEKLY_SERIES, FRIDAY, UNIT_USD, CHANGE_PCT)
    text = m.render()
    assert "10.00% 1W" in text and "15.79% 1M" in text and "37.50% 3M" in text
    assert "D/D" not in text
    assert m.change("3M") == 37.5 and m.change("D/D") is None


def test_a_missing_weekly_headline_is_partial_and_says_so():
    m = weekly_metric("X", "X", [("2026-09-18", 1.0)], FRIDAY, UNIT_USD)
    assert m.status == "partial"
    assert m.render() == "$1.00 (1W N/A)"


def test_daily_records_are_unchanged_by_the_weekly_fields():
    m = Metric(key="SPY", label="S&P 500", value=100.0, week_change=1.0, unit=UNIT_USD)
    assert m.status == "partial"
    assert m.render() == "$100.00 (D/D N/A | ▲1.00% 1W)"
