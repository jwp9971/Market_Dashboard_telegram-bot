import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or None
CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip() or None

TELEGRAM_MAX_LENGTH = 4096


async def send_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials are not configured.")
        return False

    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text=text)
        return True
    except Exception as e:
        print(f"Telegram send failed: {e}")
        return False


def send_alert(text):
    return asyncio.run(send_message(text))


def split_into_chunks(text, max_length=TELEGRAM_MAX_LENGTH):
    """
    Splits text into chunks that each fit within Telegram's message
    limit, breaking at paragraph or sentence boundaries where possible
    so no content is ever cut off mid-thought. Returns a list of
    complete chunks — nothing is discarded.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > max_length:
        # Prefer breaking at a paragraph break within the limit
        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at == -1:
            # Fall back to the last sentence-ending period within the limit
            split_at = remaining.rfind(". ", 0, max_length)
        if split_at == -1:
            # Last resort: break at the last space to avoid cutting a word
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at == -1:
            # No good break point at all — hard split (should be rare)
            split_at = max_length

        chunk = remaining[:split_at + 1].strip()
        chunks.append(chunk)
        remaining = remaining[split_at + 1:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def send_long_message(text):
    """
    Sends text as one or more Telegram messages, splitting only if
    necessary. Multi-part messages are numbered so it's clear nothing
    is missing. Returns True only if every part sent successfully.
    """
    chunks = split_into_chunks(text)
    all_sent = True

    for i, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            chunk = f"({i}/{len(chunks)})\n\n{chunk}"
        sent = send_alert(chunk)
        all_sent = all_sent and sent

    return all_sent


def send_analysis_report(analysis_text, dashboard_text, source="claude"):
    """
    Sends the dashboard snapshot and analyst commentary as separate
    Telegram messages, and further splits either one into numbered
    parts if it exceeds Telegram's 4096-character limit — so the full
    analysis is always delivered, never silently cut off.
    """
    source_note = "\n⚠️ Fallback analysis (Claude call failed today)" if source != "claude" else ""

    dashboard_message = f"📊 Data Snapshot\n\n{dashboard_text}"
    analysis_message = f"🧠 Analyst Comment{source_note}\n\n{analysis_text}"

    sent_dashboard = send_long_message(dashboard_message)
    sent_analysis = send_long_message(analysis_message)

    return sent_dashboard and sent_analysis


if __name__ == "__main__":
    send_alert("✅ Stock Signal Bot is connected and running!")
