"""
A cut-off or malformed model note must never be labelled `source="claude"`.
The Sept 9 run logged a max_tokens truncation and still delivered the partial
text as a normal completed analysis.
"""
import sys

import analyst

GOOD_NOTE = (
    "Macro Read: rates and credit are pointing the same way. " * 10
    + "Index Read: the headline indices confirm it. " * 10
    + "Sector Composition: breadth is narrow. " * 10
    + "Trend View: the weekly picture still dominates. " * 10
    + "Watch: a credit reversal would change this. " * 10
)


class _Block:
    def __init__(self, text):
        self.text = text


class _Response:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Block(text)]
        self.stop_reason = stop_reason


def _fake_anthropic(monkeypatch, text, stop_reason="end_turn"):
    class _Messages:
        def create(self, **kwargs):
            return _Response(text, stop_reason)

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    monkeypatch.setattr(sys.modules["anthropic"], "Anthropic", _Client, raising=False)
    monkeypatch.setattr(analyst, "ANTHROPIC_API_KEY", "test-key")


def test_complete_note_is_labelled_claude(monkeypatch):
    _fake_anthropic(monkeypatch, GOOD_NOTE)
    result = analyst.analyze_market({"VIX": "18.0"}, {"macro": [], "broad_industry": [], "theme": []})
    assert result["source"] == "claude"
    assert result["warnings"] == []


def test_truncated_note_is_not_labelled_claude(monkeypatch):
    _fake_anthropic(monkeypatch, GOOD_NOTE, stop_reason="max_tokens")
    result = analyst.analyze_market({"VIX": "18.0"}, {"macro": [], "broad_industry": [], "theme": []})
    assert result["source"] == "claude_incomplete"
    assert any("cut off" in w for w in result["warnings"])


def test_note_missing_sections_is_flagged(monkeypatch):
    _fake_anthropic(monkeypatch, "Macro Read: something happened. " * 60)
    result = analyst.analyze_market({}, {})
    assert result["source"] == "claude_incomplete"
    assert any("Missing section" in w for w in result["warnings"])


def test_runaway_length_is_flagged(monkeypatch):
    _fake_anthropic(monkeypatch, GOOD_NOTE + ("filler word here. " * 700))
    result = analyst.analyze_market({}, {})
    assert result["source"] == "claude_incomplete"
    assert any("600-word budget" in w for w in result["warnings"])


def test_no_api_key_falls_back(monkeypatch):
    monkeypatch.setattr(analyst, "ANTHROPIC_API_KEY", None)
    result = analyst.analyze_market({}, {})
    assert result["source"] == "fallback"
    assert any("Claude unavailable" in w for w in result["warnings"])


def test_api_exception_falls_back(monkeypatch):
    class _Client:
        def __init__(self, api_key=None):
            raise RuntimeError("rate limited")

    monkeypatch.setattr(sys.modules["anthropic"], "Anthropic", _Client, raising=False)
    monkeypatch.setattr(analyst, "ANTHROPIC_API_KEY", "test-key")
    result = analyst.analyze_market({}, {})
    assert result["source"] == "fallback"
    assert any("rate limited" in w for w in result["warnings"])


# --- Stage 4: the truncation root cause -----------------------------------

def test_thinking_and_budget_are_declared_explicitly(monkeypatch):
    """
    claude-sonnet-5 runs adaptive thinking whether or not you ask for it, and
    thinking tokens come out of max_tokens. At 4096 the reasoning consumed the
    budget and the note was cut off mid-section while looking far shorter than
    the limit -- twice in production, on 2026-09-09 and 2026-09-15.
    """
    captured = {}

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Response(GOOD_NOTE)

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    monkeypatch.setattr(sys.modules["anthropic"], "Anthropic", _Client, raising=False)
    monkeypatch.setattr(analyst, "ANTHROPIC_API_KEY", "test-key")

    analyst.call_claude("prompt")

    assert captured["thinking"] == {"type": "adaptive"}
    assert captured["output_config"]["effort"] in (
        "low", "medium", "high", "xhigh", "max")
    assert captured["max_tokens"] >= 16000, (
        "max_tokens must leave room for thinking plus a ~600 word note")


def test_the_budget_is_far_above_the_note_length():
    """A 600-word note is ~800 tokens; the rest of the budget is headroom for
    adaptive thinking."""
    assert analyst.ANTHROPIC_MAX_TOKENS >= 16000


def test_effort_defaults_to_medium():
    """A daily note over a fixed table of numbers is not a hard reasoning
    problem, so the thinking depth should be proportionate."""
    assert analyst.ANTHROPIC_EFFORT == "medium"


def test_truncation_is_still_caught_if_it_somehow_happens(monkeypatch):
    _fake_anthropic(monkeypatch, GOOD_NOTE, stop_reason="max_tokens")
    result = analyst.analyze_market({}, {})
    assert result["source"] == "claude_incomplete"
