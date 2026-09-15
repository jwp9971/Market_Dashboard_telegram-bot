"""
Staleness gating.

Stage 2 made observation dates visible. This makes them enforced: a series
past its source's tolerance is marked, shown as stale rather than hidden, and
turns the run degraded. The tolerances are calendar days, so the tests below
pin the real calendar cases that must NOT trip -- a weekend, a long weekend,
and Thanksgiving -- because a false alarm every holiday is worse than useless.
"""
from datetime import date

import pytest

from metrics import (
    MAX_AGE_FRED_OAS, MAX_AGE_FRED_RATES, MAX_AGE_MARKET_DAYS,
    Metric, mark_staleness, stale_metrics,
)


def _m(as_of, max_age=MAX_AGE_MARKET_DAYS, value=100.0):
    return Metric(key="k", label="Thing", value=value,
                  day_change=0.5, as_of=as_of, max_age_days=max_age)


def test_age_is_counted_in_calendar_days():
    assert _m("2026-09-10").age_days(date(2026, 9, 14)) == 4
    assert _m("2026-09-14").age_days(date(2026, 9, 14)) == 0


@pytest.mark.parametrize("age,expected_stale", [
    (0, False), (3, False),
    (MAX_AGE_MARKET_DAYS, False),       # exactly at tolerance is still fresh
    (MAX_AGE_MARKET_DAYS + 1, True),    # one day past is stale
    (30, True),
])
def test_tolerance_boundary(age, expected_stale):
    today = date(2026, 9, 20)
    observed = date.fromordinal(today.toordinal() - age)
    metric = _m(observed.isoformat())
    assert metric.is_stale_at(today) is expected_stale


def test_a_metric_with_no_tolerance_is_never_stale():
    assert _m("2020-01-01", max_age=None).is_stale_at(date(2026, 9, 20)) is False


def test_a_metric_with_no_value_is_missing_not_stale():
    metric = Metric(key="k", label="Thing", as_of="2020-01-01",
                    max_age_days=MAX_AGE_MARKET_DAYS)
    mark_staleness([metric], date(2026, 9, 20))
    assert metric.status == "missing"


def test_a_metric_with_no_date_is_not_judged():
    assert _m(None).is_stale_at(date(2026, 9, 20)) is False


# --- the real calendar cases that must not produce a false alarm ----------

def test_normal_monday_morning_is_fresh():
    """Report at 08:00 Mon KST == 23:00 Sun UTC. Newest bar is Friday's."""
    assert _m("2026-09-11").is_stale_at(date(2026, 9, 13)) is False   # Fri -> Sun


def test_monday_holiday_long_weekend_is_fresh():
    """Mon closed; Tue 08:00 KST == Mon 23:00 UTC; newest bar is Friday's."""
    assert _m("2026-09-11").is_stale_at(date(2026, 9, 14)) is False   # 3 days


def test_friday_holiday_plus_weekend_is_fresh():
    """Fri closed; Mon 08:00 KST == Sun 23:00 UTC; newest bar is Thursday's."""
    assert _m("2026-09-10").is_stale_at(date(2026, 9, 13)) is False   # 3 days


def test_thanksgiving_week_is_fresh():
    """Thu+Fri closed. Mon 08:00 KST == Sun 23:00 UTC; newest bar Wednesday's.
    Four days -- the tightest normal case the tolerance has to absorb."""
    assert _m("2026-11-25").is_stale_at(date(2026, 11, 29)) is False  # Wed -> Sun


def test_a_genuinely_dead_feed_is_caught():
    assert _m("2026-09-01").is_stale_at(date(2026, 9, 20)) is True


def test_fred_oas_gets_the_longer_tolerance():
    """ICE BofA OAS lags a business day, so the same date that is fine for an
    OAS series would be fine for rates too -- but one more day is not."""
    today = date(2026, 9, 20)
    five_days_back = "2026-09-15"
    assert _m(five_days_back, max_age=MAX_AGE_FRED_OAS).is_stale_at(today) is False
    assert _m(five_days_back, max_age=MAX_AGE_FRED_RATES).is_stale_at(today) is True


# --- marking and reporting -------------------------------------------------

def test_mark_staleness_sets_the_flag_once():
    metrics = [_m("2026-09-01"), _m("2026-09-19")]
    mark_staleness(metrics, date(2026, 9, 20))
    assert [m.stale for m in metrics] == [True, False]
    assert [m.status for m in metrics] == ["stale", "ok"]


def test_status_does_not_change_when_read_later():
    """status reads the flag, not the clock, so it cannot drift mid-report."""
    metric = _m("2026-09-19")
    mark_staleness([metric], date(2026, 9, 20))
    assert metric.status == "ok"
    assert metric.status == "ok"


def test_stale_metrics_are_shown_not_hidden():
    metric = _m("2026-09-01")
    mark_staleness([metric], date(2026, 9, 20))
    rendered = metric.render()
    assert "100.00" in rendered          # the number is still there
    assert "STALE" in rendered
    assert "Sep 01" in rendered


def test_stale_is_not_usable():
    metric = _m("2026-09-01")
    mark_staleness([metric], date(2026, 9, 20))
    assert metric.is_usable is False


def test_stale_metrics_helper_filters():
    fresh, stale = _m("2026-09-19"), _m("2026-09-01")
    mark_staleness([fresh, stale], date(2026, 9, 20))
    assert stale_metrics([fresh, stale]) == [stale]
