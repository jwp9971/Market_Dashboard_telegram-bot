"""
What actually lands in Telegram.

Covers the Stage 2 content fixes: metrics that were fetched and sent to
Claude but never shown, FX and the curve getting real change lines, the
report date being Korean rather than the runner's UTC date, and an honest
footer about what was missing or out of sync.
"""
from datetime import datetime, timedelta, timezone

import dashboard
import sectors
from metrics import (CHANGE_LEVEL, CHANGE_PCT, UNIT_KRW, UNIT_PERCENT,
                     UNIT_RATIO, UNIT_USD, Metric)


def _macro(**overrides):
    base = {
        "VIX": Metric(key="VIX", label="VIX", value=18.42, day_change=5.0,
                      week_change=-10.0, month_change=-12.0, as_of="2026-09-12"),
        "WTI": Metric(key="WTI", label="WTI Crude", value=68.2, day_change=-1.1,
                      unit=UNIT_USD, as_of="2026-09-12"),
        "Gold": Metric(key="Gold", label="Gold", value=2510.4, day_change=0.4,
                       unit=UNIT_USD, as_of="2026-09-12"),
        "Copper": Metric(key="Copper", label="Copper", value=4.32, day_change=-0.2,
                         unit=UNIT_USD, as_of="2026-09-12"),
        "Gold/Copper": Metric(key="Gold/Copper", label="Gold/Copper Ratio",
                              value=581.1, unit=UNIT_RATIO, tracks_changes=False,
                              as_of="2026-09-12"),
        "10Y": Metric(key="10Y", label="10Y Treasury", value=4.10, day_change=0.05,
                      unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL, as_of="2026-09-12"),
        "2Y": Metric(key="2Y", label="2Y Treasury", value=3.72, day_change=0.02,
                     unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL, as_of="2026-09-12"),
        "2s10s": Metric(key="2s10s", label="2s10s Spread", value=0.38, day_change=0.03,
                        unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL, as_of="2026-09-12"),
        "HY OAS": Metric(key="HY OAS", label="HY OAS", value=3.20, day_change=0.10,
                         unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL, as_of="2026-09-12"),
        "IG OAS": Metric(key="IG OAS", label="IG OAS", value=0.92, day_change=0.01,
                         unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL, as_of="2026-09-12"),
        "DXY": Metric(key="DXY", label="Dollar Index", value=101.25, day_change=0.22,
                      as_of="2026-09-12"),
        "USDKRW": Metric(key="USDKRW", label="USD/KRW", value=1380.5, day_change=0.30,
                         week_change=-0.80, month_change=1.20, unit=UNIT_KRW,
                         as_of="2026-09-12"),
    }
    base.update(overrides)
    return base


def _sectors(as_of="2026-09-12"):
    snap = {
        key: [Metric(key=symbol, label=label, symbol=symbol, value=100.0,
                     day_change=0.5, unit=UNIT_USD, as_of=as_of)
              for symbol, label in sectors.ETF_GROUPS[key].items()]
        for key in sectors.SECTOR_GROUP_KEYS
    }
    snap["price_source"] = "yahoo"
    snap["price_source_note"] = None
    return snap


def test_ig_oas_and_dollar_index_are_shown():
    """Both were fetched and sent to Claude but never displayed, so the
    commentary could cite a number the reader could not see."""
    out = dashboard.format_dashboard(_macro(), _sectors())
    assert "IG OAS: 0.92" in out
    assert "Dollar Index: 101.25" in out


def test_usd_krw_has_a_real_change_line():
    """It used to render as a bare arrow with no magnitude and no 1W/1M."""
    out = dashboard.format_dashboard(_macro(), _sectors())
    assert "USD/KRW: ₩1,380.5 (▲0.30% D/D | ▼0.80% 1W | ▲1.20% 1M)" in out


def test_the_curve_has_a_change_line():
    out = dashboard.format_dashboard(_macro(), _sectors())
    assert "2s10s Spread: 0.38% (▲0.03pts D/D)" in out


def test_every_tracked_etf_appears():
    out = dashboard.format_dashboard(_macro(), _sectors())
    for key in sectors.SECTOR_GROUP_KEYS:
        for symbol in sectors.ETF_GROUPS[key]:
            assert f"({symbol})" in out


def test_report_date_is_korean_not_utc():
    """23:00 UTC Sunday is 08:00 Monday in Seoul. Labelling the report with
    the runner's UTC date showed the previous day every morning."""
    utc_sunday_night = datetime(2026, 9, 13, 23, 30, tzinfo=timezone.utc)
    kst = utc_sunday_night.astimezone(dashboard.KST)
    out = dashboard.format_dashboard(_macro(), _sectors(), now=kst)
    assert "Monday, September 14, 2026 (KST)" in out


def test_as_of_is_stated_once_in_the_header_when_inputs_agree():
    out = dashboard.format_dashboard(_macro(), _sectors())
    assert "Market data as of Sep 12" in out
    # Not repeated on every section heading.
    assert out.count("as of Sep 12") == 1


def test_a_section_out_of_step_is_labelled_even_though_others_are_not():
    macro = _macro()
    for key in ("10Y", "2Y", "2s10s", "HY OAS", "IG OAS"):
        macro[key].as_of = "2026-09-11"
    out = dashboard.format_dashboard(macro, _sectors())
    rates_heading = next(l for l in out.splitlines() if "RATES & CREDIT" in l)
    fx_heading = next(l for l in out.splitlines() if "FX & DOLLAR" in l)
    assert "as of Sep 11" in rates_heading
    assert "as of" not in fx_heading


def test_mixed_dates_are_shown_as_a_range():
    macro = _macro(**{"HY OAS": Metric(key="HY OAS", label="HY OAS", value=3.2,
                                       day_change=0.1, change_kind=CHANGE_LEVEL,
                                       as_of="2026-09-10")})
    out = dashboard.format_dashboard(macro, _sectors())
    assert "as of Sep 10–Sep 12" in out


def test_missing_series_are_named_in_the_footer():
    macro = _macro(**{"IG OAS": Metric(key="IG OAS", label="IG OAS")})
    out = dashboard.format_dashboard(macro, _sectors())
    assert "Data notes:" in out
    assert "unavailable" in out
    assert "IG OAS" in out.split("Data notes:")[1]


def test_no_footer_when_everything_is_healthy():
    out = dashboard.format_dashboard(_macro(), _sectors())
    assert "Data notes:" not in out


def test_credit_lagging_equities_is_disclosed():
    """The prompt tells the analyst credit leads equities. If credit is a
    session behind, the reader needs to know that instruction spans a gap."""
    stale = {k: v for k, v in _macro().items()}
    for key in ("10Y", "2Y", "HY OAS", "IG OAS"):
        stale[key].as_of = "2026-09-11"
    out = dashboard.format_dashboard(stale, _sectors(as_of="2026-09-12"))
    assert "not the same session" in out


def test_auth_failure_produces_a_readable_report(monkeypatch):
    monkeypatch.setattr(sectors, "ETF_SOURCE", "alpaca")
    monkeypatch.setattr(sectors, "ALPACA_API_KEY", None)
    out = dashboard.format_dashboard(_macro(), sectors.get_sector_snapshot())
    assert "Daily Market Dashboard" in out
    assert "N/A (Alpaca auth failed)" in out
    assert "22 of 34 series unavailable" in out


def test_empty_input_does_not_crash():
    out = dashboard.format_dashboard({}, {})
    assert "Daily Market Dashboard" in out


def test_report_fits_a_single_telegram_message():
    """A healthy report should not need splitting; if it grows past the
    limit the splitter handles it, but one message is the intent."""
    import telegram_bot as tb
    out = dashboard.format_dashboard(_macro(), _sectors())
    parts = tb.build_message_parts(f"\U0001f4ca Data Snapshot\n\n{out}")
    assert len(parts) == 1, f"report is {len(out)} chars and now splits"


def test_derived_ratio_renders_without_a_phantom_change_line():
    """Gold/Copper has no change series, so "(D/D N/A)" would be misleading."""
    out = dashboard.format_dashboard(_macro(), _sectors())
    line = next(l for l in out.splitlines() if "Gold/Copper" in l)
    assert line == "\u2022 Gold/Copper Ratio: 581.1"


def test_credit_spreads_show_their_percent_unit():
    """A bare "2.91" does not say whether it is percent or basis points."""
    out = dashboard.format_dashboard(_macro(), _sectors())
    assert "HY OAS: 3.20%" in out
    assert "IG OAS: 0.92%" in out


def test_macro_rows_do_not_leak_internal_series_ids(monkeypatch):
    import macro as macro_module

    monkeypatch.setattr(macro_module, "get_fred_series",
                        lambda s, limit=40: (4.08, -0.04, None, None, "2026-09-12"))
    monkeypatch.setattr(macro_module, "get_yfinance_series",
                        lambda t: (1.0, 0.1, None, None, "2026-09-12"))

    out = dashboard.format_dashboard(macro_module.get_macro_snapshot(), {})
    for internal in ("BAMLH0A0HYM2", "BAMLC0A0CM", "DGS10", "DGS2",
                     "^VIX", "DX-Y.NYB", "USDKRW=X", "CL=F"):
        assert internal not in out, f"{internal} leaked into the report"


def test_etf_rows_keep_their_ticker():
    """The ticker is reader-facing for ETFs, unlike a FRED series id."""
    out = dashboard.format_dashboard(_macro(), _sectors())
    assert "S&P 500 (SPY):" in out
    assert "Semiconductors (SOXX):" in out
