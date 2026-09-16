"""
Session-aware freshness.

The calendar-day staleness tolerance cannot see a source that is consistently
one session late: Sep 14 data on Sep 16 is two calendar days, well inside the
4-day window. The 2026-09-16 01:08 UTC run was exactly that -- every ETF row
one session behind -- and the gate stayed silent. This is that gap closed.
"""
from datetime import datetime, timezone

import pytest

import dashboard
import sectors
from metrics import Metric, last_expected_session, sessions_behind


def utc(year, month, day, hour):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


# --- which session a report should be covering ----------------------------

@pytest.mark.parametrize("now,expected", [
    # Before the close hour, today's session is not complete yet.
    (utc(2026, 9, 15, 13), "2026-09-14"),   # Tue 13:00Z, Mon's close is latest
    (utc(2026, 9, 15, 23), "2026-09-15"),   # Tue 23:00Z, Tue has closed
    (utc(2026, 9, 16, 1),  "2026-09-15"),   # Wed 01:00Z == Tue 21:00 ET
    # Weekends walk back to Friday.
    (utc(2026, 9, 13, 23), "2026-09-11"),   # Sun night -> Friday
    (utc(2026, 9, 12, 23), "2026-09-11"),   # Sat night -> Friday
    (utc(2026, 9, 14, 1),  "2026-09-11"),   # Mon 01:00Z, still Friday's close
])
def test_last_expected_session(now, expected):
    assert last_expected_session(now).isoformat() == expected


def test_the_timezone_of_now_does_not_shift_the_boundary():
    """A KST instant and the same moment in UTC must agree."""
    kst = timezone(dashboard.KST.utcoffset(None))
    moment = utc(2026, 9, 16, 1)
    assert last_expected_session(moment) == last_expected_session(moment.astimezone(kst))


def test_a_naive_datetime_is_read_as_utc():
    assert last_expected_session(datetime(2026, 9, 16, 1)) == \
        last_expected_session(utc(2026, 9, 16, 1))


# --- counting the lag ------------------------------------------------------

def test_the_run_that_prompted_this_is_one_session_behind():
    """2026-09-16 01:08 UTC, five hours after the Sep 15 close, ETFs Sep 14."""
    assert sessions_behind("2026-09-14", utc(2026, 9, 16, 1)) == 1


def test_current_data_is_zero_behind():
    assert sessions_behind("2026-09-15", utc(2026, 9, 16, 1)) == 0


def test_a_weekend_is_not_a_lag():
    """Friday's close read on Monday morning KST is current, not 3 days late."""
    assert sessions_behind("2026-09-11", utc(2026, 9, 14, 1)) == 0


def test_the_lag_is_counted_in_weekdays_not_calendar_days():
    # Thursday data, read the following Tuesday night: Fri, Mon, Tue = 3.
    assert sessions_behind("2026-09-10", utc(2026, 9, 15, 23)) == 3


def test_an_unusable_date_returns_none():
    assert sessions_behind(None, utc(2026, 9, 16, 1)) is None
    assert sessions_behind("not-a-date", utc(2026, 9, 16, 1)) is None


# --- how it reaches the reader --------------------------------------------

def _healthy_macro():
    """is_data_degraded also checks the required macro keys; supply them so
    these tests isolate the session-lag behaviour."""
    return {k: Metric(key=k, label=k, value=1.0, day_change=0.1,
                      as_of="2026-09-15")
            for k in dashboard.REQUIRED_MACRO_KEYS}


def _sectors(as_of):
    snap = {key: [Metric(key=s, label=s, symbol=s, value=100.0, day_change=0.1,
                         as_of=as_of)
                  for s in list(sectors.ETF_GROUPS[key])[:2]]
            for key in sectors.SECTOR_GROUP_KEYS}
    snap["price_source"] = "alpaca:iex"
    snap["price_source_note"] = None
    return snap


def test_a_one_session_lag_is_reported():
    out = dashboard.format_dashboard({}, _sectors("2026-09-14"), now=utc(2026, 9, 16, 1))
    assert "1 session behind the expected Sep 15 close" in out


def test_a_multi_session_lag_is_pluralised():
    out = dashboard.format_dashboard({}, _sectors("2026-09-11"), now=utc(2026, 9, 16, 1))
    assert "2 sessions behind" in out


def test_current_data_produces_no_lag_note():
    out = dashboard.format_dashboard({}, _sectors("2026-09-15"), now=utc(2026, 9, 16, 1))
    assert "behind the expected" not in out


# --- what fails the run, and what only gets mentioned ----------------------

def test_one_session_is_reported_but_does_not_fail_the_run():
    """A single market holiday looks identical to a one-session lag, and this
    check has no holiday calendar. Reporting it is right; failing on it would
    turn every holiday red."""
    assert dashboard.is_data_degraded(
        _healthy_macro(), _sectors("2026-09-14"), now=utc(2026, 9, 16, 1)) is False


def test_two_sessions_behind_fails_the_run():
    """No single holiday can open a two-session gap."""
    assert dashboard.is_data_degraded(
        _healthy_macro(), _sectors("2026-09-11"), now=utc(2026, 9, 16, 1)) is True


def test_the_degrade_threshold_is_explicit():
    assert dashboard.SESSION_LAG_DEGRADES_AT == 2


def test_thanksgiving_only_reads_as_one_session_behind():
    """US markets close Thanksgiving Thursday but trade the Friday, so the
    latest close read on Monday night is Friday's -- one behind, reported but
    not failing. This is why the single-holiday case is safe."""
    assert sessions_behind("2026-11-27", utc(2026, 11, 30, 23)) == 1


def test_two_consecutive_weekday_closures_are_the_known_false_positive():
    """If the market ever closed two weekdays running -- which in practice
    happens only for exceptional events, not scheduled holidays -- the lag
    would read as 2 and fail the run. Recorded in the README as the accepted
    cost of having no holiday calendar."""
    assert sessions_behind("2026-11-25", utc(2026, 11, 30, 23)) == 3
