import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or None
CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip() or None

# Set DRY_RUN=1 to print messages instead of sending them. Lets the full
# pipeline be exercised locally without spamming the chat.
DRY_RUN = (os.getenv("DRY_RUN") or "").strip().lower() in ("1", "true", "yes", "on")

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
    if DRY_RUN:
        print(f"--- DRY RUN: would send {len(text)} chars ---")
        print(text)
        print("--- end of message ---")
        return True
    return asyncio.run(send_message(text))


def _part_prefix(index, total):
    return f"({index}/{total})\n\n"


def _split_raw(text, limit):
    """
    Splits text into pieces of at most `limit` characters, preferring
    paragraph, then sentence, then word boundaries. Never returns an
    empty piece and never exceeds `limit`.
    """
    pieces = []
    remaining = text.strip()

    while len(remaining) > limit:
        window = remaining[:limit]

        # Prefer a paragraph break; the break itself is dropped.
        split_at = window.rfind("\n\n")
        if split_at > 0:
            chunk, consumed = remaining[:split_at], split_at + 2
        else:
            # Then the last sentence-ending period; keep the period.
            split_at = window.rfind(". ")
            if split_at > 0:
                chunk, consumed = remaining[:split_at + 1], split_at + 1
            else:
                # Then the last space; the space itself is dropped.
                split_at = window.rfind(" ")
                if split_at > 0:
                    chunk, consumed = remaining[:split_at], split_at + 1
                else:
                    # No break point at all (e.g. one long unbroken token):
                    # hard split at exactly the limit, never limit + 1.
                    chunk, consumed = remaining[:limit], limit

        chunk = chunk.strip()
        if chunk:
            pieces.append(chunk)
        remaining = remaining[consumed:].strip()

    if remaining:
        pieces.append(remaining)

    return pieces or [text.strip()]


def split_into_chunks(text, max_length=TELEGRAM_MAX_LENGTH):
    """
    Splits text so that each chunk still fits Telegram's limit *after*
    the "(i/n)" part marker is prepended. The marker length depends on
    how many chunks there are, so the budget is resolved by re-splitting
    until it stops growing (converges in one or two passes).
    """
    text = text.strip()
    if len(text) <= max_length:
        return [text]

    reserve = 0
    chunks = _split_raw(text, max_length)
    for _ in range(5):
        needed = len(_part_prefix(len(chunks), len(chunks)))
        if needed <= reserve:
            break
        reserve = needed
        chunks = _split_raw(text, max_length - reserve)

    return chunks


def build_message_parts(text, max_length=TELEGRAM_MAX_LENGTH):
    """
    Returns the exact strings that will be handed to Telegram, part
    markers included. Every returned part is non-empty and within the
    limit — this is the function the tests assert against.
    """
    chunks = split_into_chunks(text, max_length)
    if len(chunks) <= 1:
        parts = list(chunks)
    else:
        total = len(chunks)
        parts = [f"{_part_prefix(i, total)}{c}" for i, c in enumerate(chunks, start=1)]

    # Safety net: nothing leaves this function over the limit, even if the
    # budget logic above is ever wrong.
    safe = []
    for part in parts:
        while len(part) > max_length:
            safe.append(part[:max_length])
            part = part[max_length:]
        if part:
            safe.append(part)
    return safe


def send_long_message(text):
    """
    Sends text as one or more Telegram messages, splitting only if
    necessary. Multi-part messages are numbered so it's clear nothing
    is missing. Returns True only if every part sent successfully.
    """
    parts = build_message_parts(text)
    all_sent = True

    for part in parts:
        sent = send_alert(part)
        if not sent:
            print(f"Telegram part failed ({len(part)} chars)")
        all_sent = all_sent and sent

    return all_sent


def build_source_note(source="claude", warnings=None):
    """Header line that makes a degraded report impossible to mistake for a
    normal one."""
    lines = []
    if source == "fallback":
        lines.append("⚠️ Fallback analysis (Claude call failed today)")
    elif source == "claude_incomplete":
        lines.append("⚠️ INCOMPLETE analysis — delivered as-is, do not read as a finished note")
    elif source != "claude":
        lines.append(f"⚠️ Unverified analysis source: {source}")

    for warning in warnings or []:
        lines.append(f"⚠️ {warning}")

    return ("\n" + "\n".join(lines)) if lines else ""


def send_analysis_report(analysis_text, dashboard_text, source="claude", warnings=None):
    """
    Sends the dashboard snapshot and analyst commentary as separate
    Telegram messages, splitting either one into numbered parts if it
    exceeds Telegram's 4096-character limit. Returns True only if every
    part of both messages was accepted.
    """
    source_note = build_source_note(source, warnings)

    dashboard_message = f"\U0001f4ca Data Snapshot\n\n{dashboard_text}"
    analysis_message = f"\U0001f9e0 Analyst Comment{source_note}\n\n{analysis_text}"

    sent_dashboard = send_long_message(dashboard_message)
    sent_analysis = send_long_message(analysis_message)

    return sent_dashboard and sent_analysis


if __name__ == "__main__":
    send_alert("✅ Stock Signal Bot is connected and running!")
