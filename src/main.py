import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from analyst import analyze_market
from dashboard import format_dashboard
from telegram_bot import send_analysis_report


def run_daily_analysis():
    try:
        result = analyze_market()
    except Exception as e:
        print(f"Analysis generation failed: {e}")
        return None

    macro_snapshot = result["macro_snapshot"]
    sector_snapshot = result["sector_snapshot"]
    analysis_text = result["analysis"]
    source = result.get("source", "unknown")

    # Same data the analyst reasoned about — not a fresh fetch —
    # so the Telegram snapshot always matches the commentary.
    dashboard_text = format_dashboard(macro_snapshot, sector_snapshot)

    sent = send_analysis_report(analysis_text, dashboard_text, source=source)
    print("Analysis sent to Telegram:", sent)
    print("Analysis source:", source)
    return result


if __name__ == "__main__":
    run_daily_analysis()