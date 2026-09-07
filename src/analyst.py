import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))

from macro import get_macro_snapshot
from sectors import get_sector_snapshot

load_dotenv()

ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You are a senior macro strategist with 15+ years across rates, FX, and cross-asset strategy. Write a daily note for a small circle of investors who want your actual view, not a hedged sell-side summary.

Standing lens:
- Credit leads equities — check HY OAS before drawing conclusions from stock moves.
- Distrust single-day moves until they align with the multi-day trend.
- Rates set the regime — treat yield levels and the 2s10s spread as the gravity everything else moves within.
- Require cross-asset confirmation — a sector move without a matching signal elsewhere is noise until proven otherwise.

Voice: decisive, direct, and slightly skeptical. Do not be timid about being wrong. If the data does not support a strong call, say so plainly and use 'this doesn't add up yet' rather than forcing a polished story.

Analytical sequence — work strictly top-down, in this order, and let each layer set the frame for the next:

1. Macro first. Start with bond yields (2Y, 10Y, 2s10s), credit (HY OAS), commodities (gold, copper, WTI, gold/copper ratio), and FX (USD/KRW). This is the regime layer — establish whether the backdrop is risk-on, risk-off, or unclear before looking at a single equity number.

2. Broad market next. Move to the headline indices (US: Dow, S&P 500, Nasdaq 100; plus KOSPI/KODEX 200 and any other broad index provided). Ask whether index-level direction is confirming or contradicting the macro read from step 1. Note if the answer differs meaningfully between US and Korea.

3. Sector composition last. Only after the macro and index-level read is established, dissect what's driving it — which sector clusters are leading or lagging the index move, and whether that composition supports or undercuts the headline number (e.g. an index up only on narrow breadth is a different story than one up broadly).

Timeframe weighting: Day-over-day moves are the least important input for any directional or trend call — weekly and monthly changes carry far more weight for what you actually believe about the trend. Do not build your core read or trend view primarily on D/D numbers. The one exception: flag any single-day move that is unusually violent (roughly high-single-digit percent or greater on an index/sector, or a similarly outsized move in a macro series) as its own callout — state what moved, what it could imply, and what would confirm or deny it — but keep this separate from and subordinate to your weekly/monthly trend view.

Length discipline: You have a firm 600-word budget. Do not address every individual ticker — group into 2-3 sector clusters and speak to cluster behavior. Prioritize finishing every section below completely over exhaustive detail in any one section. An unfinished note is a failure regardless of how good the partial analysis is.

Only use data explicitly provided in the user message. Never reference outside news, events, or catalysts not given to you.

Format:
1. Macro Read: 1-2 sentences on the regime — what rates, credit, commodities, and FX are collectively signaling
2. Index Read: 1-2 sentences on whether headline indices (US and Korea) confirm or contradict the macro regime
3. Sector Composition: 2-3 sentences on which sector clusters are driving the index-level move, and whether that composition strengthens or weakens the headline story
4. Intraday Flag: (only if a genuinely violent single-day move occurred) what moved, the implication, and what would confirm it — otherwise state plainly that no single-day move rises to flag-worthy
5. Trend View: 1-2 sentences on the weekly/monthly picture — this is your actual directional view, weighted toward multi-day data, not today's tape
6. Watch: 1-2 tripwires — specific things that would change this view if they happen next

Max 600 words total."""


def _extract_change_direction(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    if "▲" in text:
        return "up"
    if "▼" in text:
        return "down"
    return None


def _format_snapshot(snapshot: Dict[str, Any]) -> str:
    if not snapshot:
        return "No data available"
    lines = []
    for key, value in snapshot.items():
        if isinstance(value, list):
            lines.append(f"- {key}: {', '.join(value)}")
        else:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def build_analysis_prompt(macro_snapshot: Dict[str, Any], sector_snapshot: Dict[str, Any]) -> str:
    return f"""Write the daily note using the persona and format above.

Be explicit about how the macro signals and sector signals agree or disagree.
If one side is leading the other, say so.
If the data is inconsistent, say that plainly.

Data provided:
Macro data:
{_format_snapshot(macro_snapshot)}

Sector data:
{_format_snapshot(sector_snapshot)}
"""


def call_claude(prompt: str) -> Optional[str]:
    if not ANTHROPIC_API_KEY:
        print("Claude call skipped: ANTHROPIC_API_KEY is not set in .env")
        return None

    try:
        import anthropic
    except ImportError:
        print("Claude call skipped: 'anthropic' package is not installed in this environment")
        return None

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        if response.stop_reason == "max_tokens":
            print("WARNING: Claude response was cut off by max_tokens — consider raising the limit further")

        pieces = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                pieces.append(text)
        return "\n".join(pieces).strip() or None
    except Exception as exc:
        print(f"Claude call failed: {exc}")
        return None


def generate_fallback_analysis(macro_snapshot: Dict[str, Any], sector_snapshot: Dict[str, Any]) -> str:
    macro_text = []
    for key, value in macro_snapshot.items():
        if value is not None:
            macro_text.append(f"{key}: {value}")

    sector_text = []
    for market_name in ("us", "kr"):
        for line in sector_snapshot.get(market_name, []):
            sector_text.append(str(line))

    read = "The data is still too mixed to force a clean read."
    why = "Rates, credit, and sector breadth are not yet telling one consistent story."
    what_doesnt_fit = ""
    watch = "A clean confirmation from rates and credit would change this view."

    vix = macro_snapshot.get("VIX") or ""
    ten_y = macro_snapshot.get("10Y Treasury") or ""
    hy_oas = macro_snapshot.get("HY OAS") or ""
    sector_lines = " | ".join(sector_text)

    if "▼" in str(vix) and "▲" in str(ten_y) and "▼" in str(hy_oas):
        read = "Risk appetite is improving, but the move is still too narrow to trust."
        why = "VIX is easing, long-end yields are rising, and credit spreads are tightening. That combination is constructive, but it needs confirmation from broader sector participation before it becomes durable."
        watch = "A broader sector rally with rates and credit still cooperating would make this more convincing."
    elif "▲" in str(vix) and "▼" in str(ten_y) and "▲" in str(hy_oas):
        read = "The market is still under pressure from a fragile macro setup."
        why = "Volatility is rising, yields are falling, and credit spreads are widening. That is not a clean bullish setup, and the sector data does not yet overcome it."
        watch = "A reversal in credit spreads and a better sector breadth read would change this view."
    elif sector_lines and "▲" in sector_lines and "▼" in sector_lines:
        read = "The tape is showing dispersion rather than conviction."
        why = "The sector proxies are not moving in one direction, so this looks more like rotation than a broad regime shift."
        watch = "A sustained move in the same direction across multiple sectors would change the view."
    else:
        read = "The market is still waiting for a cleaner signal."
        why = "The macro data is not yet giving a clear regime shift, and the sector read is too mixed to force a stronger call."
        watch = "A clearer alignment between rates, credit, and sector leadership would change this view."

    if "▲" in str(hy_oas) and "▼" in str(vix):
        what_doesnt_fit = "Credit is still being cautious even as volatility eases."

    return f"""Read: {read}
Why: {why}
What doesn't fit: {what_doesnt_fit if what_doesnt_fit else 'Nothing obvious stands out yet.'}
Watch: {watch}
"""


def analyze_market(macro_snapshot: Optional[Dict[str, Any]] = None, sector_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if macro_snapshot is None:
        macro_snapshot = get_macro_snapshot()
    if sector_snapshot is None:
        sector_snapshot = get_sector_snapshot()

    prompt = build_analysis_prompt(macro_snapshot, sector_snapshot)
    claude_output = call_claude(prompt)
    analysis_text = claude_output or generate_fallback_analysis(macro_snapshot, sector_snapshot)

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "macro_snapshot": macro_snapshot,
        "sector_snapshot": sector_snapshot,
        "analysis": analysis_text,
        "source": "claude" if claude_output else "fallback",
    }


if __name__ == "__main__":
    result = analyze_market()
    print(result["analysis"])
