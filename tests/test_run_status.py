"""
A run that failed to deliver, or delivered something degraded, must not exit 0.
Every historical failure in this project was green in the Actions list.
"""
import main
import telegram_bot as tb


def test_clean_run_exits_zero():
    assert main.decide_exit_code("claude", True) == main.EXIT_OK


def test_delivery_failure_exits_nonzero():
    assert main.decide_exit_code("claude", False) == main.EXIT_FAILED


def test_fallback_is_degraded_not_ok():
    assert main.decide_exit_code("fallback", True) == main.EXIT_DEGRADED


def test_incomplete_analysis_is_degraded_not_ok():
    assert main.decide_exit_code("claude_incomplete", True) == main.EXIT_DEGRADED


def test_failed_delivery_beats_degraded_source():
    assert main.decide_exit_code("fallback", False) == main.EXIT_FAILED


def test_unknown_source_is_not_ok():
    assert main.decide_exit_code("unknown", True) == main.EXIT_DEGRADED


def test_fallback_is_visibly_labelled_in_the_message():
    note = tb.build_source_note("fallback")
    assert "Fallback" in note


def test_incomplete_is_visibly_labelled_in_the_message():
    note = tb.build_source_note("claude_incomplete", ["Model output was cut off by the token limit"])
    assert "INCOMPLETE" in note
    assert "cut off" in note


def test_clean_run_adds_no_warning_banner():
    assert tb.build_source_note("claude") == ""
