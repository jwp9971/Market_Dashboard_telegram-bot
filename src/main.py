import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from analyst import analyze_market
from dashboard import format_dashboard
from telegram_bot import send_analysis_report

# Exit codes. GitHub Actions marks the run red for anything non-zero, which
# is the point: a report that failed or was degraded should be visible in the
# Actions list without opening the logs.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_DEGRADED = 2


def decide_exit_code(source, delivered):
    """Maps a run outcome to a process exit status."""
    if not delivered:
        return EXIT_FAILED
    if source != "claude":
        return EXIT_DEGRADED
    return EXIT_OK


def run_daily_analysis():
    """Runs one report. Returns (exit_code, result_or_None)."""
    try:
        result = analyze_market()
    except Exception as e:
        print(f"Analysis generation failed: {e}")
        return EXIT_FAILED, None

    macro_snapshot = result["macro_snapshot"]
    sector_snapshot = result["sector_snapshot"]
    analysis_text = result["analysis"]
    source = result.get("source", "unknown")
    warnings = result.get("warnings", [])

    # Same data the analyst reasoned about — not a fresh fetch —
    # so the Telegram snapshot always matches the commentary.
    dashboard_text = format_dashboard(macro_snapshot, sector_snapshot)

    try:
        delivered = send_analysis_report(
            analysis_text, dashboard_text, source=source, warnings=warnings
        )
    except Exception as e:
        print(f"Telegram delivery raised: {e}")
        delivered = False

    print("Analysis sent to Telegram:", delivered)
    print("Analysis source:", source)
    for warning in warnings:
        print(f"Warning: {warning}")

    return decide_exit_code(source, delivered), result


def main():
    exit_code, _ = run_daily_analysis()
    label = {
        EXIT_OK: "OK",
        EXIT_FAILED: "FAILED",
        EXIT_DEGRADED: "DEGRADED",
    }.get(exit_code, "UNKNOWN")
    print(f"Run status: {label} (exit {exit_code})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
