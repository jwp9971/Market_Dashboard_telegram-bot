"""
The fallback must never invert the day's signal.

It now reads numeric fields off the structured record. Before Stage 2 it
searched formatted strings for arrow glyphs, so a risk-off day whose weekly
numbers happened to be risk-on produced the exact opposite read.
"""
import analyst
from metrics import CHANGE_LEVEL, CHANGE_PCT, UNIT_PERCENT, Metric


def _macro(vix=None, ten=None, hy=None, ig=None, vix_w=None, hy_w=None, spread=None):
    return {
        "VIX": Metric(key="VIX", label="VIX", value=18.0,
                      day_change=vix, week_change=vix_w, change_kind=CHANGE_PCT),
        "10Y": Metric(key="10Y", label="10Y Treasury", value=4.10, day_change=ten,
                      unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL),
        "HY OAS": Metric(key="HY OAS", label="HY OAS", value=3.20,
                         day_change=hy, week_change=hy_w, change_kind=CHANGE_LEVEL),
        "IG OAS": Metric(key="IG OAS", label="IG OAS", value=0.92,
                         day_change=ig, change_kind=CHANGE_LEVEL),
        "2s10s": Metric(key="2s10s", label="2s10s Spread", value=0.38, day_change=spread,
                        unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL),
    }


def _sectors(day_changes, group="macro"):
    metrics = [
        Metric(key=f"E{i}", label=f"ETF{i}", symbol=f"E{i}", value=100.0, day_change=c)
        for i, c in enumerate(day_changes)
    ]
    snapshot = {"macro": [], "broad_industry": [], "theme": []}
    snapshot[group] = metrics
    return snapshot


def _read_line(text):
    """The Read: line is the headline claim -- this is what used to invert."""
    return next(l for l in text.splitlines() if l.startswith("Read:"))


def test_change_reads_the_named_horizon_only():
    macro = {"VIX": Metric(key="VIX", label="VIX", value=18.0,
                           day_change=5.0, week_change=-10.0, month_change=-12.0)}
    assert analyst._change(macro, "VIX", "D/D") == 5.0
    assert analyst._change(macro, "VIX", "1W") == -10.0
    assert analyst._change(macro, "VIX", "1M") == -12.0
    assert analyst._change(macro, "NOPE") is None
    assert analyst._change({}, "VIX") is None


def test_risk_off_day_is_not_reported_as_improving():
    """The exact case that inverted before: risk-off day, risk-on week.

    VIX up and HY OAS widening on the day is risk-off. The old code saw the
    down-arrows in the 1W text and announced improving risk appetite.
    """
    macro = _macro(vix=5.0, ten=-0.05, hy=0.10, vix_w=-10.0, hy_w=-0.15)
    out = analyst.generate_fallback_analysis(macro, _sectors([1.0, -1.0]))
    read = _read_line(out)
    assert "under pressure" in read
    assert "improved" not in read
    # The weekly divergence belongs in "what doesn't fit", not the headline.
    assert "runs against the week" in out


def test_risk_on_day_is_reported_as_improving():
    out = analyst.generate_fallback_analysis(
        _macro(vix=-4.0, ten=0.03, hy=-0.08), _sectors([1.0, 2.0]))
    assert "improved" in _read_line(out)


def test_conflicting_vol_and_credit_refuses_a_regime_call():
    out = analyst.generate_fallback_analysis(
        _macro(vix=-4.0, ten=0.01, hy=0.09), _sectors([0.5]))
    assert "disagreed" in _read_line(out)


def test_the_why_line_quotes_the_actual_daily_numbers():
    out = analyst.generate_fallback_analysis(
        _macro(vix=5.0, ten=-0.05, hy=0.10), _sectors([1.0, -1.0]))
    why = next(l for l in out.splitlines() if l.startswith("Why"))
    assert "5.00%" in why and "0.10pts" in why
    assert "1 of 2 tracked ETFs" in why


def test_ig_oas_and_the_curve_are_reported_when_available():
    out = analyst.generate_fallback_analysis(
        _macro(vix=5.0, ten=-0.05, hy=0.10, ig=0.03, spread=-0.02), _sectors([1.0]))
    assert "IG OAS widened 0.03pts" in out
    assert "2s10s flattened 0.02pts" in out


def test_credit_tiers_disagreeing_is_surfaced():
    out = analyst.generate_fallback_analysis(
        _macro(vix=2.0, ten=0.01, hy=0.10, ig=-0.02), _sectors([1.0]))
    assert "opposite directions" in out


def test_every_claim_is_labelled_day_over_day():
    out = analyst.generate_fallback_analysis(
        _macro(vix=-4.0, ten=0.03, hy=-0.08), _sectors([1.0]))
    assert "day-over-day" in out.lower()
    assert "on the day" in out


def test_empty_input_says_insufficient_rather_than_guessing():
    out = analyst.generate_fallback_analysis({}, {})
    assert "Insufficient data" in out
    for phrase in ("improved", "under pressure", "dispersion"):
        assert phrase not in out


def test_missing_macro_series_are_disclosed():
    out = analyst.generate_fallback_analysis(
        {"VIX": Metric(key="VIX", label="VIX")}, _sectors([1.0, -1.0, 0.5]))
    assert "Data gaps" in out


def test_breadth_counts_all_three_groups():
    snapshot = {
        "macro": [Metric(key="A", label="A", value=1.0, day_change=1.0)],
        "broad_industry": [Metric(key="B", label="B", value=1.0, day_change=-1.0)],
        "theme": [Metric(key="C", label="C", value=1.0, day_change=1.0)],
    }
    assert analyst._sector_breadth(snapshot) == (2, 1)


def test_breadth_ignores_metrics_with_no_reading():
    snapshot = {"macro": [
        Metric(key="A", label="A", value=1.0, day_change=1.0),
        Metric(key="B", label="B", error="auth failed"),
    ], "broad_industry": [], "theme": []}
    assert analyst._sector_breadth(snapshot) == (1, 0)
