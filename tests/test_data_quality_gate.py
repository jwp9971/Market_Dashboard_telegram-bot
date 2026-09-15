"""
What counts as data too degraded to call a normal reading.

A report can be delivered and still not be trustworthy. This is the gate that
turns that into a non-zero exit and a visible banner.
"""
from datetime import date

import dashboard
import sectors
from metrics import MAX_AGE_MARKET_DAYS, Metric, mark_staleness


def _ok(key, label, value=1.0, as_of="2026-09-19"):
    return Metric(key=key, label=label, value=value, day_change=0.1,
                  as_of=as_of, max_age_days=MAX_AGE_MARKET_DAYS)


def _healthy_macro():
    return {k: _ok(k, k) for k in ("VIX", "HY OAS", "10Y", "2Y", "DXY")}


def _healthy_sectors():
    snap = {key: [_ok(s, s) for s in list(sectors.ETF_GROUPS[key])[:2]]
            for key in sectors.SECTOR_GROUP_KEYS}
    snap["feed"] = "sip"
    snap["feed_note"] = None
    return snap


def test_healthy_data_is_not_degraded():
    assert dashboard.is_data_degraded(_healthy_macro(), _healthy_sectors()) is False


def test_a_missing_core_series_is_degraded():
    macro = _healthy_macro()
    macro["HY OAS"] = Metric(key="HY OAS", label="HY OAS")   # no value
    assert dashboard.is_data_degraded(macro, _healthy_sectors()) is True


def test_a_missing_non_core_series_is_not_degraded():
    """One unavailable ETF should not red-flag the whole run."""
    macro = _healthy_macro()
    macro["DXY"] = Metric(key="DXY", label="Dollar Index")
    assert dashboard.is_data_degraded(macro, _healthy_sectors()) is False


def test_any_stale_series_is_degraded():
    macro = _healthy_macro()
    macro["VIX"].as_of = "2026-09-01"
    mark_staleness(macro.values(), date(2026, 9, 20))
    assert dashboard.is_data_degraded(macro, _healthy_sectors()) is True


def test_total_etf_outage_is_degraded():
    snap = {key: [Metric(key="X", label="X", error="Alpaca auth failed")]
            for key in sectors.SECTOR_GROUP_KEYS}
    snap["feed"] = None
    snap["feed_note"] = None
    assert dashboard.is_data_degraded(_healthy_macro(), snap) is True


def test_required_keys_are_the_ones_the_prompt_leans_on():
    """VIX, HY OAS and the 10Y are the regime layer the system prompt tells
    the analyst to establish before looking at a single equity number."""
    assert set(dashboard.REQUIRED_MACRO_KEYS) == {"VIX", "HY OAS", "10Y"}


def test_stale_series_are_named_in_the_footer():
    macro = _healthy_macro()
    macro["VIX"].as_of = "2026-09-01"
    mark_staleness(macro.values(), date(2026, 9, 20))
    out = dashboard.format_dashboard(macro, _healthy_sectors())
    assert "past their freshness window" in out
    assert "STALE" in out
