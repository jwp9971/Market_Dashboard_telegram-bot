"""
Has this week's report already gone out? The check in front of every scheduled
slot of the weekly workflow.

GitHub's scheduler can drop a slot outright -- 2026-09-26 03:00 UTC produced no
run at all -- so the workflow has a primary Monday slot and later backups.
Each scheduled run first asks the GitHub API whether an earlier run of this
workflow already delivered the week that closed last Friday, and skips
everything else if so. Manual runs never ask.

"Delivered" means that run's delivery step succeeded. The workflow fails that
step only when nothing reached Telegram (exit 1), so a degraded week (exit 2,
still a red run) counts as delivered and is not sent twice, while a failed
week is retried by the next slot.

If the API can't be read, the run goes ahead: a duplicate report is better
than a missed week. Standard library only -- it runs before pip install -- and
it prints counts, never a value.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, time, timezone

sys.path.insert(0, os.path.dirname(__file__))

from metrics import US_SESSION_CLOSE_UTC_HOUR
from weeks import last_completed_week

WORKFLOW_FILE = "weekly-commentary.yml"
# Must match the step name in the workflow file; a test holds them together.
DELIVERY_STEP = "Run weekly commentary"
API = "https://api.github.com"


def week_closed_at(now=None):
    """The US close of the last completed week's Friday, as a UTC datetime."""
    _, friday = last_completed_week(now)
    return datetime.combine(friday, time(US_SESSION_CLOSE_UTC_HOUR), tzinfo=timezone.utc)


def _parse_time(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def already_delivered(runs, current_run_id, since):
    """
    True if a run other than this one, created after `since`, has its delivery
    step at "success". `runs` is [{"id", "created_at", "steps": [{"name",
    "conclusion"}]}].
    """
    for run in runs:
        if str(run.get("id")) == str(current_run_id):
            continue
        created = run.get("created_at")
        if not created or _parse_time(created) < since:
            continue
        for step in run.get("steps") or []:
            if step.get("name") == DELIVERY_STEP and step.get("conclusion") == "success":
                return True
    return False


def _get_json(url, token):
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def fetch_runs(repo, since, token, current_run_id=None, get=_get_json):
    """This workflow's runs created since `since`, each with its job steps."""
    query = urllib.parse.urlencode({
        "created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "per_page": 50,
    })
    listing = get(f"{API}/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?{query}", token)
    runs = []
    for run in listing.get("workflow_runs") or []:
        if str(run.get("id")) == str(current_run_id):
            continue
        jobs = get(f"{API}/repos/{repo}/actions/runs/{run['id']}/jobs", token).get("jobs") or []
        runs.append({"id": run["id"], "created_at": run.get("created_at"),
                     "steps": [step for job in jobs for step in job.get("steps") or []]})
    return runs


def should_skip(now=None, env=None, get=_get_json):
    """True when this scheduled run should skip because the week already went out."""
    env = os.environ if env is None else env
    repo = env.get("GITHUB_REPOSITORY")
    token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")
    run_id = env.get("GITHUB_RUN_ID")
    since = week_closed_at(now)
    if not (repo and token):
        print("Guard: no GitHub repository or token; running the report")
        return False
    try:
        runs = fetch_runs(repo, since, token, run_id, get)
    except Exception as e:
        print(f"Guard: could not read earlier runs ({type(e).__name__}); running the report")
        return False
    delivered = already_delivered(runs, run_id, since)
    verdict = ("already delivered, skipping this slot" if delivered
               else "none delivered, running the report")
    print(f"Guard: {len(runs)} earlier run(s) since {since:%Y-%m-%d %H:%M} UTC; {verdict}")
    return delivered


def main():
    skip = should_skip()
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"skip={'true' if skip else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
