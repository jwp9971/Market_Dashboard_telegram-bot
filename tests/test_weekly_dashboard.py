"""
The weekly snapshot text (weekly_dashboard.py) and the two-line row format.

Built from a hand-made snapshot -- synthetic numbers, no fetching -- shaped
like weekly_snapshot.get_weekly_snapshot()'s return value.
"""
from datetime import date, datetime, timezone

import pytest

from metrics import (CHANGE_LEVEL, CHANGE_PCT, UNIT_INDEX, UNIT_PERCENT, UNIT_RATIO,
                     UNIT_USD, WEEKLY_HORIZONS, Metric, missing)
from sectors import ETF_GROUPS, GROUP_TITLES, SECTOR_GROUP_KEYS
from telegram_bot import build_message_parts
from weekly_dashboard import (format_weekly_dashboard, is_weekly_degraded,
                              weekly_data_notes, weekly_movers)
from weeks import weekly_metric

FRIDAY = date(2026, 9, 18)
NOW = datetime(2026, 9, 19, 3, tzinfo=timezone.utc)       # Saturday noon KST


def series(now_value, week_ago, month_ago=None, quarter_ago=None, last_day="2026-09-18"):
    rows = [(last_day, now_value), ("2026-09-11", week_ago)]
    if month_ago is not None:
        rows.append(("2026-08-21", month_ago))
    if quarter_ago is not None:
        rows.append(("2026-06-18", quarter_ago))
    return rows


def weekly(key, label, rows, unit=UNIT_USD, kind=CHANGE_PCT, symbol=""):
    return weekly_metric(key, label, rows, FRIDAY, unit, kind, source="test", symbol=symbol)


def make_snapshot():
    macro = {
        "VIX": weekly("VIX", "VIX", series(18.0, 20.0, 19.0, 21.0), UNIT_INDEX),
        "WTI": weekly("WTI", "WTI Crude", series(70.0, 69.0, 65.0, 60.0), symbol="CLX6"),
        "Gold": weekly("Gold", "Gold", series(2200.0, 2000.0, 2100.0, 1900.0), symbol="GCZ6"),
        "Copper": weekly("Copper", "Copper", series(4.4, 4.3, 4.2, 4.1), symbol="HGZ6"),
        "Gold/Copper": Metric(key="Gold/Copper", label="Gold/Copper Ratio", value=500.0,
                              unit=UNIT_RATIO, tracks_changes=False, horizons=WEEKLY_HORIZONS,
                              as_of="2026-09-18"),
    }
    # FRED and the Economy API run a day behind: Thursday values.
    for key, label, level in (("10Y", "10Y Treasury", 4.2), ("2Y", "2Y Treasury", 3.6),
                              ("2s10s", "2s10s Spread", 0.6), ("HY OAS", "HY OAS", 2.7),
                              ("IG OAS", "IG OAS", 0.8)):
        macro[key] = weekly(key, label, series(level, level - 0.1, level - 0.2, level + 0.1,
                                               last_day="2026-09-17"), UNIT_PERCENT, CHANGE_LEVEL)
    macro["DXY"] = weekly("DXY", "Dollar Index", series(100.2, 99.1, 98.8, 100.8), UNIT_INDEX)

    etfs, n = {}, 0
    for group in SECTOR_GROUP_KEYS:
        etfs[group] = []
        for symbol, label in ETF_GROUPS[group].items():
            n += 1
            if symbol == "NCLD":
                etfs[group].append(missing(symbol, label, source="test", symbol=symbol,
                                           error="no data in the week of 2026-09-14",
                                           horizons=WEEKLY_HORIZONS))
                continue
            quarter = None if symbol == "AIHY" else 90.0
            # 1W change grows with n, so the ranking is known: n=1 lowest.
            etfs[group].append(weekly(symbol, label, series(100.0 + n, 100.0, 98.0, quarter),
                                      symbol=symbol))
    notes = ["Commodities: official settlement of the most-traded nearby contract (CLX6, GCZ6, HGZ6)"]
    return {"week": (date(2026, 9, 14), FRIDAY), "label": "Week of Sep 14–18",
            "macro": macro, "etfs": etfs, "notes": notes, "massive_calls": 18}


@pytest.fixture
def snap():
    return make_snapshot()


@pytest.fixture
def text(snap):
    return format_weekly_dashboard(snap, now=NOW)


# --- layout ----------------------------------------------------------------------

def test_the_header_names_the_week_and_the_definitions(text):
    lines = text.splitlines()
    assert lines[0] == "📊 Weekly Market Dashboard"
    assert lines[1] == "🗓 Week of Sep 14–18, 2026 (KST report: Saturday, September 19, 2026)"
    assert lines[2] == "📏 Week-end closes: 1W vs previous Friday · 1M = 4 weeks · 3M = 13 weeks"


def test_sections_come_in_order_without_krw_or_daily_changes(text):
    order = ["VOLATILITY & COMMODITIES", "RATES & CREDIT", "DOLLAR"]
    order += [GROUP_TITLES[g].upper() for g in SECTOR_GROUP_KEYS] + ["Data notes"]
    positions = [text.index(title) for title in order]
    assert positions == sorted(positions)
    assert "USD/KRW" not in text and "D/D" not in text


def test_rows_are_two_lines(text):
    assert "• S&P 500 (SPY)  $102.00\n   1W ▲2.00% · 1M ▲4.08% · 3M ▲13.33%" in text
    assert "• 10Y Treasury  4.20%\n   1W ▲0.10pts · 1M ▲0.20pts · 3M ▼0.10pts" in text


def test_a_row_without_changes_is_one_line(text):
    after = text.split("• Gold/Copper Ratio  500.0\n", 1)[1]
    assert after.startswith("\n━")        # blank line, then the next section


def test_a_missing_row_says_why(text):
    assert "• Neoclouds (NCLD)  N/A (no data in the week of 2026-09-14)" in text


def test_only_a_section_off_friday_carries_an_as_of_label(text):
    assert "📈 RATES & CREDIT  · as of Sep 17\n" in text
    assert "🌡 VOLATILITY & COMMODITIES\n" in text


def test_a_full_week_fits_one_telegram_message(text):
    assert len(text) < 4096
    assert len(build_message_parts("📊 Data Snapshot\n\n" + text)) == 1


# --- movers ----------------------------------------------------------------------

def test_movers_are_the_best_and_worst_weeks(snap, text):
    leaders, laggards = weekly_movers(snap["etfs"])
    assert [m.symbol for m in leaders] == ["BUG", "AIHY", "DRAM"]     # NCLD is missing
    assert [m.symbol for m in laggards] == ["DIA", "SPY", "QQQ"]
    assert "🏆 Leaders 1W: BUG ▲21.00% · AIHY ▲20.00% · DRAM ▲19.00%" in text
    assert "📉 Laggards 1W: DIA ▲1.00% · SPY ▲2.00% · QQQ ▲3.00%" in text


def test_movers_need_at_least_two_usable_etfs(snap):
    for group in snap["etfs"].values():
        for m in group:
            m.error = "gone"
    assert weekly_movers(snap["etfs"]) == ([], [])
    assert "Leaders" not in format_weekly_dashboard(snap, now=NOW)


# --- notes -----------------------------------------------------------------------

def test_notes_state_sources_price_only_early_short_and_missing(snap):
    notes = weekly_data_notes(snap)
    assert notes[0].startswith("Commodities: official settlement")
    assert "ETF changes are price-only: Massive closes are split- but not dividend-adjusted" in notes
    assert ("Last value before Friday (a holiday, or the source runs a day behind): "
            "10Y, 2Y, 2s10s, HY OAS, IG OAS") in notes
    assert "3M unavailable (under 13 weeks of history): AIHY" in notes
    assert "Missing this week: NCLD" in notes


def test_a_clean_week_only_explains_the_numbers(snap):
    for m in snap["macro"].values():
        m.as_of = "2026-09-18"
    snap["etfs"] = {g: [m for m in rows if m.symbol not in ("NCLD", "AIHY")]
                    for g, rows in snap["etfs"].items()}
    assert weekly_data_notes(snap) == [snap["notes"][0],
                                       "ETF changes are price-only: Massive closes are "
                                       "split- but not dividend-adjusted"]


# --- degraded --------------------------------------------------------------------

def test_a_normal_week_is_not_degraded(snap):
    assert is_weekly_degraded(snap) is False


@pytest.mark.parametrize("key", ["VIX", "HY OAS", "10Y"])
def test_losing_a_core_series_degrades_the_week(snap, key):
    snap["macro"][key].error = "gone"
    assert is_weekly_degraded(snap) is True


def test_losing_every_etf_degrades_the_week(snap):
    for group in snap["etfs"].values():
        for m in group:
            m.value = None
    assert is_weekly_degraded(snap) is True


def test_single_gaps_are_notes_not_degradation(snap):
    snap["macro"]["WTI"].error = "gone"
    snap["macro"]["DXY"].value = None
    assert is_weekly_degraded(snap) is False


# --- the two-line row itself -------------------------------------------------------

def test_render_block_variants():
    m = weekly("SPY", "S&P 500", series(101.0, 100.0), symbol="SPY")
    assert m.render_block() == "S&P 500 (SPY)  $101.00\n   1W ▲1.00%"
    flat = weekly("X", "X", series(100.0, 100.0))
    assert flat.render_block() == "X  $100.00\n   1W 0.00%"
    alone = weekly("X", "X", [("2026-09-18", 5.0)])
    assert alone.render_block() == "X  $5.00\n   1W N/A"
    m.stale = True
    assert "⚠ STALE, as of Sep 18" in m.render_block().splitlines()[0]


def test_format_change_and_the_daily_line_agree():
    m = Metric(key="10Y", label="10Y", value=4.1, day_change=0.05, week_change=-0.2,
               unit=UNIT_PERCENT, change_kind=CHANGE_LEVEL)
    assert m.format_change("D/D") == "▲0.05pts"
    assert m.format_change("1M") is None
    assert m.render() == "4.10% (▲0.05pts D/D | ▼0.20pts 1W)"
