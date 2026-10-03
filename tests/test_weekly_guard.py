"""
The guard in front of each scheduled weekly slot (weekly_guard.py): skip only
when an earlier run already delivered the week that closed last Friday.

No network: the GitHub API is a fake passed in as `get`.
"""
from datetime import datetime, timezone

import pytest

import weekly_guard
from weekly_guard import DELIVERY_STEP, already_delivered, should_skip, week_closed_at

UTC = timezone.utc
PRIMARY = datetime(2026, 10, 4, 23, 17, tzinfo=UTC)         # Monday 08:17 KST
CLOSED = datetime(2026, 10, 2, 21, 0, tzinfo=UTC)            # Friday's US close
ENV = {"GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "token", "GITHUB_RUN_ID": "99"}


def run(run_id, created, delivery="success", flag=None):
    """A run as fetch_runs returns it; delivery=None means the step never existed."""
    steps = [{"name": "Check whether this week's report already went out", "conclusion": "success"}]
    if delivery is not None:
        steps.append({"name": DELIVERY_STEP, "conclusion": delivery})
    if flag is not None:
        steps.append({"name": "Flag degraded report", "conclusion": flag})
    return {"id": run_id, "created_at": created, "steps": steps}


# --- which week ---------------------------------------------------------------------

@pytest.mark.parametrize("now", [
    PRIMARY,                                                 # Monday primary (Sun UTC)
    datetime(2026, 10, 5, 3, 17, tzinfo=UTC),                # Monday 12:17 KST backup
    datetime(2026, 10, 5, 9, 17, tzinfo=UTC),                # Monday 18:17 KST backup
    datetime(2026, 10, 3, 5, 56, tzinfo=UTC),                # a Saturday manual run
    datetime(2026, 10, 4, 3, 17, tzinfo=UTC),                # a Sunday manual run
    datetime(2026, 10, 2, 21, 30, tzinfo=UTC),               # Friday, just after the close
])
def test_the_week_counts_from_last_fridays_close(now):
    assert week_closed_at(now) == CLOSED


def test_before_fridays_close_it_is_still_the_previous_week():
    assert week_closed_at(datetime(2026, 10, 2, 20, 0, tzinfo=UTC)) == datetime(
        2026, 9, 25, 21, 0, tzinfo=UTC)


# --- what counts as delivered ---------------------------------------------------------

def test_an_ok_run_this_week_counts():
    assert already_delivered([run(1, "2026-10-03T07:10:00Z")], "99", CLOSED)


def test_a_degraded_run_counts_so_the_week_is_not_sent_twice():
    """Exit 2: the delivery step is green, the flag step is red."""
    assert already_delivered([run(1, "2026-10-03T07:10:00Z", flag="failure")], "99", CLOSED)


def test_a_failed_run_does_not_count_so_the_next_slot_retries():
    assert not already_delivered([run(1, "2026-10-03T07:10:00Z", delivery="failure")], "99", CLOSED)


def test_a_skipped_slot_does_not_count():
    assert not already_delivered([run(1, "2026-10-03T11:20:00Z", delivery="skipped")], "99", CLOSED)


def test_a_run_that_died_before_delivery_does_not_count():
    assert not already_delivered([run(1, "2026-10-03T07:10:00Z", delivery=None)], "99", CLOSED)


def test_last_weeks_run_does_not_count():
    assert not already_delivered([run(1, "2026-09-27T08:58:14Z")], "99", CLOSED)


def test_the_current_run_does_not_count_itself():
    assert not already_delivered([run(99, "2026-10-03T07:10:00Z")], "99", CLOSED)


def test_a_manual_run_after_fridays_close_counts():
    assert already_delivered([run(1, "2026-10-02T22:00:00Z")], "99", CLOSED)


# --- talking to the API ---------------------------------------------------------------

class FakeAPI:
    def __init__(self, runs):
        self.runs, self.urls = runs, []

    def __call__(self, url, token):
        self.urls.append(url)
        if "/jobs" in url:
            run_id = int(url.rsplit("/runs/", 1)[1].split("/")[0])
            steps = next(r["steps"] for r in self.runs if r["id"] == run_id)
            return {"jobs": [{"steps": steps}]}
        return {"workflow_runs": [{"id": r["id"], "created_at": r["created_at"]} for r in self.runs]}


def test_it_skips_when_an_earlier_run_delivered(capsys):
    api = FakeAPI([run(1, "2026-10-03T07:10:00Z"), run(99, "2026-10-03T11:17:30Z", delivery=None)])
    assert should_skip(PRIMARY, ENV, api)
    # Asks only for runs since Friday's close, and never for its own jobs.
    assert "created=%3E%3D2026-10-02T21%3A00%3A00Z" in api.urls[0]
    assert "/workflows/weekly-commentary.yml/runs" in api.urls[0]
    assert not any("/runs/99/jobs" in url for url in api.urls)
    assert "1 earlier run(s)" in capsys.readouterr().out


def test_it_runs_when_nothing_was_delivered_yet():
    assert not should_skip(PRIMARY, ENV, FakeAPI([]))


def test_an_unreadable_api_means_run_anyway(capsys):
    def broken(url, token):
        raise OSError("network down")
    assert not should_skip(PRIMARY, ENV, broken)
    out = capsys.readouterr().out
    assert "OSError" in out and "network down" not in out


def test_no_token_means_run_anyway():
    assert not should_skip(PRIMARY, {"GITHUB_REPOSITORY": "owner/repo"}, FakeAPI([]))


def test_main_writes_the_verdict_for_the_next_steps(monkeypatch, tmp_path):
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(weekly_guard, "should_skip", lambda: True)
    assert weekly_guard.main() == 0
    assert output.read_text() == "skip=true\n"
