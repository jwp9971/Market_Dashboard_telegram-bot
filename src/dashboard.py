import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from macro import get_macro_snapshot
from sectors import get_sector_snapshot
from telegram_bot import send_long_message

def format_market_time(ts, label):
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts)
        return f"📍 {label}: {dt.strftime('%b %d, %Y')}"
    except:
        return f"📍 {label}: {ts}"

def format_dashboard(macro, sectors):
    today = datetime.now().strftime("%B %d, %Y")

    macro_lines = "\n".join(f"• {line}" for line in sectors.get("macro", []))
    industry_lines = "\n".join(f"• {line}" for line in sectors.get("broad_industry", []))
    theme_lines = "\n".join(f"• {line}" for line in sectors.get("theme", []))
    market_time_label = format_market_time(sectors.get("market_time"), "Market Data")

    message = f"""
📊 Daily Market Dashboard
🗓 {today}

━━━━━━━━━━━━━━━
🌡 MACRO SNAPSHOT
━━━━━━━━━━━━━━━
- VIX: {macro.get('VIX', 'N/A')}
- WTI Crude: {macro.get('WTI', 'N/A')}
- Gold: {macro.get('Gold', 'N/A')} | Copper: {macro.get('Copper', 'N/A')}
- Gold/Copper Ratio: {macro.get('Gold/Copper Ratio', 'N/A')}

📈 RATES & CREDIT
- 10Y Treasury: {macro.get('10Y Treasury', 'N/A')}
- 2Y Treasury: {macro.get('2Y Treasury', 'N/A')}
- 2s10s Spread: {macro.get('2s10s Spread', 'N/A')}
- HY OAS: {macro.get('HY OAS', 'N/A')}
- USD/KRW: {sectors.get('fx', 'N/A')}

━━━━━━━━━━━━━━━
🌍 INDICES / BONDS / BITCOIN / GEOGRAPHY
{market_time_label}
━━━━━━━━━━━━━━━
{macro_lines}

━━━━━━━━━━━━━━━
🏭 BROAD INDUSTRY
━━━━━━━━━━━━━━━
{industry_lines}

━━━━━━━━━━━━━━━
🎯 THEME
━━━━━━━━━━━━━━━
{theme_lines}
"""
    return message.strip()

def build_dashboard():
    macro = get_macro_snapshot()
    sectors = get_sector_snapshot()
    return format_dashboard(macro, sectors)

def send_dashboard():
    """Standalone dashboard send. Routed through send_long_message so it gets
    the same length handling as the scheduled report."""
    print("Sending daily dashboard...")
    message = build_dashboard()
    sent = send_long_message(message)
    print("Dashboard sent." if sent else "Dashboard delivery FAILED.")
    return sent

if __name__ == "__main__":
    sys.exit(0 if send_dashboard() else 1)
