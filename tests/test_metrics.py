"""The structured record that replaced formatted-string passing."""
import pytest

from metrics import (
    CHANGE_LEVEL, CHANGE_PCT, UNIT_INDEX, UNIT_KRW, UNIT_PERCENT, UNIT_RATIO,
    UNIT_USD, Metric, as_of_range, to_iso_date,
)


def test_status_is_derived_not_assigned():
    assert Metric(key="k", label="l").status == "missing"
    assert Metric(key="k", label="l", value=1.0).status == "partial"
    assert Metric(key="k", label="l", value=1.0, day_change=0.5).status == "ok"
    assert Metric(key="k", label="l", value=1.0, error="boom").status == "error"


def test_usable_covers_ok_and_partial_only():
    assert Metric(key="k", label="l", value=1.0, day_change=0.1).is_usable
    assert Metric(key="k", label="l", value=1.0).is_usable
    assert not Metric(key="k", label="l").is_usable
    assert not Metric(key="k", label="l", error="boom").is_usable


def test_change_is_read_by_horizon_name():
    m = Metric(key="k", label="l", value=1.0,
               day_change=1.5, week_change=-2.5, month_change=3.5)
    assert m.change("D/D") == 1.5
    assert m.change("1W") == -2.5
    assert m.change("1M") == 3.5
    assert m.change("1Y") is None


def test_percent_changes_render_with_arrows():
    m = Metric(key="VIX", label="VIX", value=18.42,
               day_change=5.0, week_change=-10.0, change_kind=CHANGE_PCT)
    assert m.render() == "18.42 (▲5.00% D/D | ▼10.00% 1W)"


def test_level_changes_render_in_points():
    m = Metric(key="10Y", label="10Y Treasury", value=4.1, day_change=-0.05,
               unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL)
    assert m.render() == "4.10% (▼0.05pts D/D)"


@pytest.mark.parametrize("unit,value,expected", [
    (UNIT_USD, 2510.4, "$2,510.40"),
    (UNIT_KRW, 1380.5, "₩1,380.5"),
    (UNIT_PERCENT, 4.1, "4.10%"),
    (UNIT_RATIO, 581.08, "581.1"),
    (UNIT_RATIO, 1234.56, "1,234.6"),
    (UNIT_INDEX, 18.423, "18.42"),
])
def test_value_formatting_per_unit(unit, value, expected):
    assert Metric(key="k", label="l", value=value, unit=unit).format_value() == expected


def test_missing_value_renders_na_not_a_number():
    assert Metric(key="k", label="l").render() == "N/A"
    assert Metric(key="k", label="l", error="auth failed").render() == "N/A (auth failed)"


def test_missing_day_change_is_flagged_in_the_change_line():
    m = Metric(key="k", label="l", value=1.0, week_change=2.0)
    assert "D/D N/A" in m.render()


def test_render_line_includes_the_symbol_when_present():
    m = Metric(key="SPY", label="S&P 500", symbol="SPY", value=612.4,
               day_change=0.42, unit=UNIT_USD)
    assert m.render_line() == "S&P 500 (SPY): $612.40 (▲0.42% D/D)"
    assert Metric(key="VIX", label="VIX", value=18.0).render_line().startswith("VIX: ")


@pytest.mark.parametrize("raw,expected", [
    ("2026-09-12", "2026-09-12"),
    ("2026-09-12T00:00:00-04:00", "2026-09-12"),
    ("2026-09-12 00:00:00", "2026-09-12"),
    (None, None),
    ("", None),
])
def test_to_iso_date_normalises_source_formats(raw, expected):
    assert to_iso_date(raw) == expected


def test_as_of_is_rendered_human_readable():
    assert Metric(key="k", label="l", as_of="2026-09-12").format_as_of() == "Sep 12"
    assert Metric(key="k", label="l").format_as_of() == ""


def test_as_of_range_spans_the_inputs():
    metrics = [
        Metric(key="a", label="a", as_of="2026-09-12"),
        Metric(key="b", label="b", as_of="2026-09-10"),
        Metric(key="c", label="c"),
    ]
    assert as_of_range(metrics) == ("2026-09-10", "2026-09-12")
    assert as_of_range([]) == (None, None)
