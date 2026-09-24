"""
Entry point for the weekly commentary: fetch, format, analyse, send, exit code.

    $env:DRY_RUN=1; python src/weekly_main.py   # prints both messages (local only)
    python src/weekly_main.py                   # sends them to Telegram

Exit codes are main.py's: 0 OK, 1 FAILED (nothing delivered), 2 DEGRADED
(delivered, but a fallback/incomplete note or data that should not be read as
a normal week). Nothing here prints a data value: the Actions log is public
and Massive's terms forbid publishing its data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import telegram_bot
import weekly_analyst
import weekly_dashboard
import weekly_snapshot
from main import EXIT_DEGRADED, EXIT_FAILED, EXIT_OK, decide_exit_code

DEGRADED_WARNING = ("Underlying weekly data is incomplete — see the data notes "
                    "at the end of the snapshot")


def run_weekly_report(now=None):
    """Runs one weekly report. Returns (exit_code, result_or_None)."""
    if telegram_bot.DRY_RUN and os.getenv("GITHUB_ACTIONS") == "true":
        # A dry run prints both messages, i.e. every number, into a public log.
        print("Refusing DRY_RUN in GitHub Actions: it would publish Massive data in the log.")
        return EXIT_FAILED, None

    try:
        snapshot = weekly_snapshot.get_weekly_snapshot(now)
    except Exception as e:
        print(f"Weekly snapshot failed: {type(e).__name__}")
        return EXIT_FAILED, None

    # The note reasons about exactly the snapshot shown -- never a second fetch.
    dashboard_text = weekly_dashboard.format_weekly_dashboard(snapshot, now)
    result = weekly_analyst.analyze_week(snapshot)
    source = result["source"]
    warnings = list(result["warnings"])

    data_degraded = weekly_dashboard.is_weekly_degraded(snapshot)
    if data_degraded:
        warnings.append(DEGRADED_WARNING)

    try:
        delivered = telegram_bot.send_analysis_report(
            result["analysis"], dashboard_text, source=source, warnings=warnings)
    except Exception as e:
        print(f"Telegram delivery raised: {type(e).__name__}")
        delivered = False

    print("Weekly report sent to Telegram:", delivered)
    print(f"Analysis source: {source} ({result['model']})")
    for warning in warnings:
        print(f"Warning: {warning}")

    return decide_exit_code(source, delivered, data_degraded), result


def main():
    try:
        exit_code, _ = run_weekly_report()
    except Exception as e:
        # Anything unexpected: print the type only. An exception's message or
        # a traceback can quote a value, and the Actions log is public to
        # anyone the repository is shared with.
        print(f"Weekly report crashed: {type(e).__name__}")
        exit_code = EXIT_FAILED
    label = {EXIT_OK: "OK", EXIT_FAILED: "FAILED", EXIT_DEGRADED: "DEGRADED"}.get(exit_code, "UNKNOWN")
    print(f"Run status: {label} (exit {exit_code})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
