"""
The weekly entry point (weekly_main.py) and its workflow file.

Everything outward-facing is stubbed: no fetch, no Claude call, no message.
"""
import pathlib

import pytest

import telegram_bot
import weekly_analyst
import weekly_dashboard
import weekly_main
import weekly_snapshot
from main import EXIT_DEGRADED, EXIT_FAILED, EXIT_OK
from test_weekly_dashboard import NOW, make_snapshot

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "weekly-commentary.yml"


@pytest.fixture
def run(monkeypatch):
    """Stubs the three stages; returns a dict the test can tune and inspect."""
    state = {"snapshot": make_snapshot(), "sent": [], "delivered": True,
             "analysis": {"analysis": "Regime Read: ...", "source": "claude",
                          "warnings": [], "model": "claude-sonnet-5"}}

    def snapshot(now=None):
        if isinstance(state["snapshot"], Exception):
            raise state["snapshot"]
        return state["snapshot"]

    def send(analysis, dashboard, source="claude", warnings=None):
        state["sent"].append({"analysis": analysis, "dashboard": dashboard,
                              "source": source, "warnings": list(warnings or [])})
        return state["delivered"]

    monkeypatch.setattr(weekly_snapshot, "get_weekly_snapshot", snapshot)
    monkeypatch.setattr(weekly_analyst, "analyze_week", lambda snap: dict(state["analysis"]))
    monkeypatch.setattr(telegram_bot, "send_analysis_report", send)
    monkeypatch.setattr(telegram_bot, "DRY_RUN", False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return state


def test_a_clean_week_sends_both_messages_and_exits_ok(run):
    code, _ = weekly_main.run_weekly_report(now=NOW)
    assert code == EXIT_OK
    sent = run["sent"][0]
    assert sent["dashboard"] == weekly_dashboard.format_weekly_dashboard(run["snapshot"], NOW)
    assert sent["analysis"] == "Regime Read: ..."
    assert sent["source"] == "claude" and sent["warnings"] == []


def test_a_fallback_note_is_degraded(run):
    run["analysis"].update(source="fallback", warnings=["Claude unavailable: boom"])
    code, _ = weekly_main.run_weekly_report(now=NOW)
    assert code == EXIT_DEGRADED
    assert run["sent"][0]["warnings"] == ["Claude unavailable: boom"]


def test_degraded_data_is_labelled_and_exits_2(run):
    run["snapshot"]["macro"]["VIX"].error = "gone"
    code, _ = weekly_main.run_weekly_report(now=NOW)
    assert code == EXIT_DEGRADED
    assert run["sent"][0]["warnings"] == [weekly_main.DEGRADED_WARNING]


def test_a_failed_send_is_a_failure(run):
    run["delivered"] = False
    code, _ = weekly_main.run_weekly_report(now=NOW)
    assert code == EXIT_FAILED


def test_a_failed_snapshot_sends_nothing(run, capsys):
    run["snapshot"] = RuntimeError("secret-looking detail")
    code, result = weekly_main.run_weekly_report(now=NOW)
    assert (code, result, run["sent"]) == (EXIT_FAILED, None, [])
    assert "secret-looking detail" not in capsys.readouterr().out


def test_dry_run_is_refused_inside_actions(run, monkeypatch):
    monkeypatch.setattr(telegram_bot, "DRY_RUN", True)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    calls = []
    monkeypatch.setattr(weekly_snapshot, "get_weekly_snapshot", lambda now=None: calls.append(1))
    code, _ = weekly_main.run_weekly_report(now=NOW)
    assert code == EXIT_FAILED and calls == [] and run["sent"] == []


def test_the_log_carries_statuses_not_values(run, capsys):
    weekly_main.run_weekly_report(now=NOW)
    out = capsys.readouterr().out
    assert "Weekly report sent to Telegram: True" in out
    assert "$102.00" not in out and "18.00" not in out


# --- the workflow file ------------------------------------------------------------

def _workflow_lines():
    """Workflow lines without comments, so the explanations don't count."""
    return [line.split("#", 1)[0] for line in WORKFLOW.read_text(encoding="utf-8").splitlines()]


def test_an_unexpected_crash_prints_only_its_type(run, monkeypatch, capsys):
    """An exception message can quote a number; the Actions log must not."""
    def explode(snapshot, now=None):
        raise ValueError("could not convert string to float: '761.69'")
    monkeypatch.setattr(weekly_dashboard, "format_weekly_dashboard", explode)
    assert weekly_main.main() == EXIT_FAILED
    out = capsys.readouterr().out
    assert "Weekly report crashed: ValueError" in out
    assert "761.69" not in out and run["sent"] == []


def _step(name):
    """The workflow lines of one step, from its '- name:' to the next one."""
    lines = _workflow_lines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {name}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("- name:")),
               len(lines))
    return "\n".join(lines[start:end])


def test_the_workflow_has_a_primary_slot_two_backups_and_the_run_button():
    """2026-09-26's only slot was dropped by GitHub; one slot is not enough."""
    text = "\n".join(_workflow_lines())
    assert "workflow_dispatch" in text
    crons = [line.split("cron:", 1)[1].strip() for line in _workflow_lines() if "cron:" in line]
    assert crons == ["'17 5 * * 6'", "'17 11 * * 6'", "'17 3 * * 0'"]
    assert "push:" not in text and "pull_request" not in text


def test_every_scheduled_slot_checks_first_whether_the_week_went_out():
    import weekly_guard
    text = "\n".join(_workflow_lines())
    guard = _step("Check whether this week's report already went out")
    assert "if: github.event_name == 'schedule'" in guard
    assert "continue-on-error: true" in guard          # a broken check still sends
    assert "python src/weekly_guard.py" in guard
    assert "GH_TOKEN: ${{ github.token }}" in guard
    assert "actions: read" in text and "contents: read" in text
    # The guard runs before the install, so a skipped slot costs seconds.
    assert text.index("python src/weekly_guard.py") < text.index("pip install")
    for name in ("Install dependencies", weekly_guard.DELIVERY_STEP):
        assert "if: steps.guard.outputs.skip != 'true'" in _step(name)


def test_only_a_failed_delivery_fails_the_delivery_step():
    """The guard reads the delivery step: degraded (exit 2) must leave it green."""
    import weekly_guard
    delivery = _step(weekly_guard.DELIVERY_STEP)
    assert "python src/weekly_main.py" in delivery
    assert 'echo "degraded=true" >> "$GITHUB_OUTPUT"' in delivery
    exits = [line.strip() for line in delivery.splitlines() if "exit" in line]
    assert exits == ['exit "$code" ;;']                  # only in the FAILED branch
    flag = _step("Flag degraded report")
    assert "if: steps.weekly.outputs.degraded == 'true'" in flag and "exit 2" in flag


def test_only_main_can_post_to_the_chat():
    assert "if: github.ref == 'refs/heads/main'" in "\n".join(_workflow_lines())


def test_the_daily_workflow_is_manual_only_now():
    daily = ROOT / ".github" / "workflows" / "daily-dashboard.yml"
    lines = [line.split("#", 1)[0] for line in daily.read_text(encoding="utf-8").splitlines()]
    text = "\n".join(lines)
    assert "workflow_dispatch" in text
    assert "schedule:" not in text and "cron" not in text


def test_the_workflow_never_publishes_data():
    text = "\n".join(_workflow_lines())
    for forbidden in ("DRY_RUN", "upload-artifact", "actions/cache"):
        assert forbidden not in text


def test_the_workflow_runs_the_weekly_entry_point_with_its_secrets():
    text = "\n".join(_workflow_lines())
    assert "python src/weekly_main.py" in text
    for secret in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY",
                   "FRED_API_KEY", "MASSIVE_API_KEY"):
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in text
    assert "WEEKLY_ANTHROPIC_MODEL: ${{ vars.WEEKLY_ANTHROPIC_MODEL }}" in text
