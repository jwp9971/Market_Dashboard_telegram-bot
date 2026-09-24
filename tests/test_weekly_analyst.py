"""
The weekly note (weekly_analyst.py): prompt, quality gates, model settings and
the deterministic fallback. call_claude is stubbed -- no network, no spend.
"""
import pytest

import weekly_analyst
from test_weekly_dashboard import make_snapshot
from weekly_analyst import (WEEKLY_SECTIONS, WEEKLY_SYSTEM_PROMPT, analyze_week,
                            build_weekly_prompt, generate_weekly_fallback)


def note(sections=WEEKLY_SECTIONS, sentence="The data points one way this week. ", repeat=10):
    return "\n".join(f"{name}: " + sentence * repeat for name in sections)


GOOD_NOTE = note()           # six sections, ~430 words


@pytest.fixture
def snap():
    return make_snapshot()


@pytest.fixture
def claude(monkeypatch):
    """Stubs call_claude; set .reply to what it should return."""
    class Stub:
        reply = {"text": GOOD_NOTE, "truncated": False, "error": None}
        calls = []

        def __call__(self, prompt, **kwargs):
            self.calls.append({"prompt": prompt, **kwargs})
            return dict(self.reply)

    stub = Stub()
    stub.calls = []
    monkeypatch.setattr(weekly_analyst, "call_claude", stub)
    monkeypatch.delenv("WEEKLY_ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("WEEKLY_ANTHROPIC_EFFORT", raising=False)
    return stub


# --- prompt ----------------------------------------------------------------------

def test_the_prompt_carries_the_week_rows_breadth_movers_and_notes(snap):
    prompt = build_weekly_prompt(snap)
    assert "Week covered: Week of Sep 14–18, 2026 (Monday to Friday)." in prompt
    assert "1W vs the previous Friday's close · 1M = 4 weeks · 3M = 13 weeks" in prompt
    for metric in snap["macro"].values():
        assert metric.render_line() in prompt
    assert "- S&P 500 (SPY): $102.00 (▲2.00% 1W | ▲4.08% 1M | ▲13.33% 3M)  [as of 2026-09-18]" in prompt
    assert "Breadth (ETFs up or flat): 21 of 21 up over 1W; 21 of 21 up over 1M; 20 of 20 up over 3M" in prompt
    assert "Week's leaders (1W): BUG ▲21.00%, AIHY ▲20.00%, DRAM ▲19.00%" in prompt
    assert "- 3M unavailable (under 13 weeks of history): AIHY" in prompt
    assert "Neoclouds (NCLD): N/A (no data in the week of 2026-09-14)" in prompt
    assert "D/D" not in prompt and "USD/KRW" not in prompt


def test_the_system_prompt_names_every_section_in_order():
    format_block = WEEKLY_SYSTEM_PROMPT.split("Format", 1)[1]
    positions = [format_block.index(f"{i}. {name}:")
                 for i, name in enumerate(WEEKLY_SECTIONS, start=1)]
    assert positions == sorted(positions)
    assert "about 700 words" in WEEKLY_SYSTEM_PROMPT
    assert "price-only" in WEEKLY_SYSTEM_PROMPT and "KOSPI" in WEEKLY_SYSTEM_PROMPT
    assert "D/D" not in WEEKLY_SYSTEM_PROMPT and "USD/KRW" not in WEEKLY_SYSTEM_PROMPT


# --- settings --------------------------------------------------------------------

def test_the_weekly_note_uses_its_own_model_settings(snap, claude):
    analyze_week(snap)
    call = claude.calls[0]
    assert call["system"] == WEEKLY_SYSTEM_PROMPT
    assert (call["model"], call["effort"]) == ("claude-sonnet-5", "high")


def test_switching_model_is_an_env_change_only(snap, claude, monkeypatch):
    monkeypatch.setenv("WEEKLY_ANTHROPIC_MODEL", "claude-opus-5")
    monkeypatch.setenv("WEEKLY_ANTHROPIC_EFFORT", "XHigh ")
    result = analyze_week(snap)
    assert (claude.calls[0]["model"], claude.calls[0]["effort"]) == ("claude-opus-5", "xhigh")
    assert result["model"] == "claude-opus-5"
    assert result["analysis"].endswith("— claude-opus-5 · effort xhigh")


# --- outcomes --------------------------------------------------------------------

def test_a_complete_note_is_claude_and_signed(snap, claude):
    result = analyze_week(snap)
    assert result["source"] == "claude" and result["warnings"] == []
    assert result["analysis"].startswith("Regime Read:")
    assert result["analysis"].endswith("\n\n— claude-sonnet-5 · effort high")


def test_a_curly_apostrophe_still_counts_as_the_section(snap, claude):
    claude.reply = {"text": GOOD_NOTE.replace("What Doesn't Fit", "What Doesn’t Fit"),
                    "truncated": False, "error": None}
    assert analyze_week(snap)["source"] == "claude"


@pytest.mark.parametrize("text,truncated,expected", [
    (note(WEEKLY_SECTIONS[:-1]), False, "Missing section(s): Next Week Watch"),
    (note(repeat=1), False, "unusually short"),
    (note(repeat=30), False, "against a 700-word budget"),
    (GOOD_NOTE, True, "cut off by the token limit"),
])
def test_a_note_failing_a_gate_is_incomplete(snap, claude, text, truncated, expected):
    claude.reply = {"text": text, "truncated": truncated, "error": None}
    result = analyze_week(snap)
    assert result["source"] == "claude_incomplete"
    assert any(expected in w for w in result["warnings"])


def test_no_note_falls_back_with_the_reason(snap, claude):
    claude.reply = {"text": None, "truncated": False, "error": "Claude declined (cyber)"}
    result = analyze_week(snap)
    assert result["source"] == "fallback"
    assert result["warnings"] == ["Claude unavailable: Claude declined (cyber)"]
    assert result["analysis"].startswith("Regime Read:")
    assert "— claude" not in result["analysis"]


# --- fallback --------------------------------------------------------------------

def test_fallback_calls_risk_on_only_when_vix_and_credit_agree(snap):
    snap["macro"]["HY OAS"].week_change = -0.05          # VIX already fell 6.50%
    text = generate_weekly_fallback(snap)
    assert "Regime Read: Risk appetite improved over the week" in text
    assert "VIX fell 6.50%" in text and "HY OAS tightened 0.05pts" in text


def test_fallback_calls_risk_off_when_both_rise(snap):
    snap["macro"]["VIX"].week_change = 12.0
    text = generate_weekly_fallback(snap)
    assert "Risk was under pressure over the week" in text     # HY OAS widened 0.10


def test_fallback_says_no_clean_read_when_they_disagree(snap):
    text = generate_weekly_fallback(snap)
    assert "Volatility and credit disagreed over the week" in text


def test_fallback_trend_and_what_doesnt_fit(snap):
    text = generate_weekly_fallback(snap)
    assert ("Trend View: Over 13 weeks the S&P 500 (SPY) rose 13.33% while HY OAS "
            "tightened 0.10pts; credit and equities agree on the trend.") in text
    assert ("What Doesn't Fit: This week's HY OAS move (+0.10pts) runs against its "
            "3M trend (-0.10pts).") in text
    assert "21 of 21 tracked ETFs finished the week higher or flat" in text


def test_fallback_admits_when_there_is_nothing_to_read(snap):
    for metric in snap["macro"].values():
        metric.error = "gone"
    for group in snap["etfs"].values():
        for metric in group:
            metric.error = "gone"
    assert generate_weekly_fallback(snap).startswith("Regime Read: Insufficient data")


# --- plain text for Telegram -------------------------------------------------------

def test_markdown_is_stripped_before_sending(snap, claude):
    """The 2026-09-24 live run came back with '# title' and '## Section'
    headings, which a plain-text Telegram message would show literally."""
    markdown = "# Weekly Macro Note\n\n" + "\n\n".join(
        f"## {name}\nThe **data** points one way this week. " * 1 + "More text here. " * 12
        for name in WEEKLY_SECTIONS)
    claude.reply = {"text": markdown, "truncated": False, "error": None}
    result = analyze_week(snap)
    assert result["source"] == "claude"
    assert "#" not in result["analysis"] and "**" not in result["analysis"]
    assert "\nRegime Read\nThe data points one way" in "\n" + result["analysis"].split("\n\n", 1)[1]


def test_the_prompt_asks_for_plain_text():
    assert "no Markdown" in WEEKLY_SYSTEM_PROMPT
