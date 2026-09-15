"""
The fallback must never invert the day's signal.

Before this change it searched whole metric strings for the arrow glyphs, so
a risk-off day whose weekly numbers happened to be risk-on produced the exact
opposite read, stated confidently and with no timeframe named.
"""
import analyst


def _macro(vix, ten, hy, vix_w=None, hy_w=None):
    def line(day, week, unit):
        a = "▲" if day >= 0 else "▼"
        out = f"{a}{abs(day):.2f}{unit} D/D"
        if week is not None:
            b = "▲" if week >= 0 else "▼"
            out += f" | {b}{abs(week):.2f}{unit} 1W"
        return out
    return {
        "VIX": f"18.00 ({line(vix, vix_w, '%')})",
        "10Y Treasury": f"4.10% ({line(ten, None, 'pts')})",
        "HY OAS": f"3.20 ({line(hy, hy_w, 'pts')})",
    }


def _sectors(day_changes):
    lines = [f"ETF{i} (E{i}): {'▲' if c >= 0 else '▼'}{abs(c):.2f}% D/D"
             for i, c in enumerate(day_changes)]
    return {"macro": lines, "broad_industry": [], "theme": [], "fx": "N/A"}


def test_parse_changes_reads_each_horizon_separately():
    parsed = analyst.parse_changes("18.00 (▲5.00% D/D | ▼10.00% 1W | ▼12.00% 1M)")
    assert parsed == {"D/D": 5.0, "1W": -10.0, "1M": -12.0}


def test_parse_changes_handles_point_units():
    assert analyst.parse_changes("3.20 (▼0.05pts D/D)") == {"D/D": -0.05}


def test_parse_changes_on_junk_returns_nothing():
    assert analyst.parse_changes("N/A") == {}
    assert analyst.parse_changes(None) == {}


def _read_line(text):
    """The Read: line is the headline claim -- this is what used to invert."""
    return next(l for l in text.splitlines() if l.startswith("Read:"))


def test_risk_off_day_is_not_reported_as_improving():
    """The exact case that inverted before: risk-off day, risk-on week.

    VIX up and HY OAS widening on the day is risk-off. The old code saw the
    down-arrows in the 1W segments and announced improving risk appetite.
    """
    macro = _macro(vix=5.0, ten=-0.05, hy=0.10, vix_w=-10.0, hy_w=-0.15)
    out = analyst.generate_fallback_analysis(macro, _sectors([1.0, -1.0]))
    read = _read_line(out)
    assert "under pressure" in read
    assert "improved" not in read

    # The weekly divergence belongs in "what doesn't fit", not the headline.
    assert "runs against the week" in out


def test_risk_on_day_is_reported_as_improving():
    macro = _macro(vix=-4.0, ten=0.03, hy=-0.08)
    out = analyst.generate_fallback_analysis(macro, _sectors([1.0, 2.0]))
    assert "improved" in _read_line(out)


def test_the_why_line_quotes_the_actual_daily_numbers():
    macro = _macro(vix=5.0, ten=-0.05, hy=0.10)
    out = analyst.generate_fallback_analysis(macro, _sectors([1.0, -1.0]))
    why = next(l for l in out.splitlines() if l.startswith("Why"))
    assert "5.00%" in why and "0.10pts" in why
    assert "1 of 2 tracked ETFs" in why


def test_conflicting_vol_and_credit_refuses_a_regime_call():
    macro = _macro(vix=-4.0, ten=0.01, hy=0.09)
    out = analyst.generate_fallback_analysis(macro, _sectors([0.5]))
    assert "disagreed" in out


def test_every_claim_is_labelled_day_over_day():
    macro = _macro(vix=-4.0, ten=0.03, hy=-0.08)
    out = analyst.generate_fallback_analysis(macro, _sectors([1.0]))
    assert "day-over-day" in out.lower()
    assert "on the day" in out


def test_empty_input_says_insufficient_rather_than_guessing():
    out = analyst.generate_fallback_analysis({}, {})
    assert "Insufficient data" in out
    for phrase in ("improved", "under pressure", "dispersion"):
        assert phrase not in out


def test_missing_macro_series_are_disclosed():
    out = analyst.generate_fallback_analysis({"VIX": "N/A"}, _sectors([1.0, -1.0, 0.5]))
    assert "Data gaps" in out


def test_breadth_counts_all_three_groups():
    snapshot = {
        "macro": ["A (A): ▲1.00% D/D"],
        "broad_industry": ["B (B): ▼1.00% D/D"],
        "theme": ["C (C): ▲1.00% D/D"],
    }
    assert analyst._sector_breadth(snapshot) == (2, 1)
