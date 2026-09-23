"""
Guards the guard: the suite must not depend on the real date.

If the frozen-clock fixture in conftest is ever removed or stops covering a
module that computes freshness, these fail immediately instead of the suite
quietly starting to rot a week later.
"""
from datetime import date, datetime, timezone

import dashboard
import metrics
from conftest import FROZEN_NOW
from metrics import Metric, last_expected_session, mark_staleness


def test_metrics_sees_the_frozen_clock():
    assert metrics.datetime.now(timezone.utc) == FROZEN_NOW


def test_dashboard_sees_the_frozen_clock():
    assert dashboard.datetime.now(timezone.utc) == FROZEN_NOW


def test_default_session_comes_from_the_frozen_clock():
    assert last_expected_session() == date(2026, 9, 15)


def test_default_staleness_comes_from_the_frozen_clock():
    metric = Metric(key="k", label="k", value=1.0, day_change=0.1,
                    as_of="2026-09-12", max_age_days=4)   # 4 days before Sep 16
    mark_staleness([metric])
    assert metric.stale is False


def test_explicit_dates_still_override_the_frozen_clock():
    metric = Metric(key="k", label="k", value=1.0, day_change=0.1,
                    as_of="2026-09-12", max_age_days=4)
    mark_staleness([metric], date(2026, 9, 30))
    assert metric.stale is True


def test_real_datetimes_still_count_as_datetimes():
    """to_iso_date relies on isinstance(value, datetime); the frozen class
    must not change what that check says about real datetime objects."""
    real = datetime(2026, 9, 12, 15, 30, tzinfo=timezone.utc)
    assert metrics.to_iso_date(real) == "2026-09-12"
