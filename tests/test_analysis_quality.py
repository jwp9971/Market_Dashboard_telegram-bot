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
