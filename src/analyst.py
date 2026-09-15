import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))

from macro import get_macro_snapshot
from sectors import SECTOR_GROUP_KEYS, get_sector_snapshot

load_dotenv()

ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

# Quality gates applied to Claude's output before it is presented as a
# finished note. The prompt asks for a 600-word note in six sections; these
# bounds are deliberately loose so only genuinely broken output is flagged.
MIN_ANALYSIS_WORDS = 120
MAX_ANALYSIS_WORDS = 900
REQUIRED_SECTIONS = ("Macro Read", "Index Read", "Trend View", "Watch")

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


# Matches the change segments the formatters produce, e.g.
#   "▲1.23% D/D"  "▼0.05pts 1W"  "▲2.00% 1M"
_CHANGE_PATTERN = re.compile(
    r"([▲▼])\s*([0-9]+(?:\.[0-9]+)?)\s*(?:%|pts)?\s*(D/D|1W|1M)"
)


def parse_changes(text: Any) -> Dict[str, float]:
    """
    Pulls signed numeric changes out of a formatted metric string, keyed by
    horizon: {"D/D": -1.2, "1W": 0.4}.

    This exists because collectors currently hand downstream code display
    strings rather than numbers. It replaces the old behaviour of searching a
    whole string for an arrow, which could not tell a daily move from a
    monthly one and produced sign-inverted reads. Stage 2 (structured metric
    records) removes the need for it entirely.
    """
    changes: Dict[str, float] = {}
    for arrow, number, horizon in _CHANGE_PATTERN.findall(str(text or "")):
        value = float(number)
        changes[horizon] = value if arrow == "▲" else -value
    return changes


def _horizon(snapshot: Dict[str, Any], key: str, horizon: str = "D/D") -> Optional[float]:
    return parse_changes(snapshot.get(key)).get(horizon)


def _sector_breadth(sector_snapshot: Dict[str, Any], horizon: str = "D/D") -> Tuple[int, int]:
    """Counts ETFs up and down over one named horizon, across every group."""
    up = down = 0
    for group_key in SECTOR_GROUP_KEYS:
        for line in sector_snapshot.get(group_key, []) or []:
            change = parse_changes(line).get(horizon)
            if change is None:
                continue
            if change >= 0:
                up += 1
            else:
                down += 1
    return up, down


def check_analysis_quality(text: Optional[str], truncated: bool = False) -> List[str]:
    """Returns a list of problems with a model-written note. Empty == clean."""
    problems: List[str] = []
    if not text or not text.strip():
        return ["Analysis text was empty"]

    if truncated:
        problems.append("Model output was cut off by the token limit")

    word_count = len(text.split())
    if word_count < MIN_ANALYSIS_WORDS:
        problems.append(f"Analysis is unusually short ({word_count} words)")
    elif word_count > MAX_ANALYSIS_WORDS:
        problems.append(
            f"Analysis ran to {word_count} words against a 600-word budget"
        )

    lowered = text.lower()
    missing = [s for s in REQUIRED_SECTIONS if s.lower() not in lowered]
    if missing:
        problems.append("Missing section(s): " + ", ".join(missing))

    return problems


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


def call_claude(prompt: str) -> Dict[str, Any]:
    """
    Returns {"text": str|None, "truncated": bool, "error": str|None}.
    The truncation flag is part of the return value rather than a printed
    warning so callers cannot accidentally present a cut-off note as
    a finished one.
    """
    result: Dict[str, Any] = {"text": None, "truncated": False, "error": None}

    if not ANTHROPIC_API_KEY:
        result["error"] = "ANTHROPIC_API_KEY is not set"
        print("Claude call skipped: ANTHROPIC_API_KEY is not set in .env")
        return result

    try:
        import anthropic
    except ImportError:
        result["error"] = "anthropic package is not installed"
        print("Claude call skipped: 'anthropic' package is not installed in this environment")
        return result

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        if getattr(response, "stop_reason", None) == "max_tokens":
            result["truncated"] = True
            print("WARNING: Claude response was cut off by max_tokens")

        pieces = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                pieces.append(text)
        result["text"] = "\n".join(pieces).strip() or None
        return result
    except Exception as exc:
        result["error"] = str(exc)
        print(f"Claude call failed: {exc}")
        return result


def generate_fallback_analysis(macro_snapshot: Dict[str, Any], sector_snapshot: Dict[str, Any]) -> str:
    """
    Deterministic stand-in used when Claude is unavailable.

    Every rule below reads a named numeric horizon. It never infers a regime
    from an arrow appearing somewhere in a string, because a single metric
    line carries daily, weekly and monthly moves that routinely disagree.
    When the inputs it needs are missing it says so instead of asserting a
    regime.
    """
    macro_snapshot = macro_snapshot or {}
    sector_snapshot = sector_snapshot or {}

    vix_d = _horizon(macro_snapshot, "VIX")
    hy_d = _horizon(macro_snapshot, "HY OAS")
    ten_d = _horizon(macro_snapshot, "10Y Treasury")
    vix_w = _horizon(macro_snapshot, "VIX", "1W")
    hy_w = _horizon(macro_snapshot, "HY OAS", "1W")

    up, down = _sector_breadth(sector_snapshot, "D/D")
    total = up + down

    have_core = vix_d is not None and hy_d is not None
    if not have_core and total == 0:
        return (
            "Read: Insufficient data for a regime call.\n"
            "Why: Neither the core macro series (VIX, HY OAS) nor any sector "
            "changes were available for this run, so no directional statement "
            "is supportable.\n"
            "What doesn't fit: Not assessable without data.\n"
            "Watch: Restore the data feed before reading anything into today's tape.\n"
        )

    def _dir(value, rising="rose", falling="fell"):
        return rising if value >= 0 else falling

    facts = []
    if vix_d is not None:
        facts.append(f"VIX {_dir(vix_d)} {abs(vix_d):.2f}% on the day")
    if hy_d is not None:
        facts.append(
            f"HY OAS {_dir(hy_d, 'widened', 'tightened')} {abs(hy_d):.2f}pts on the day"
        )
    if ten_d is not None:
        facts.append(f"the 10Y {_dir(ten_d)} {abs(ten_d):.2f}pts on the day")
    if total:
        facts.append(f"{up} of {total} tracked ETFs closed higher")

    # Credit and volatility set the regime; both must agree before this
    # claims one. Everything is stated as a same-day observation.
    if have_core and vix_d < 0 and hy_d < 0:
        read = "Risk appetite improved on the day, but one session is not a trend."
        watch = "Confirmation would be credit continuing to tighten alongside broader sector participation."
    elif have_core and vix_d > 0 and hy_d > 0:
        read = "Risk was under pressure on the day, with volatility and credit agreeing."
        watch = "A reversal in credit spreads would be the first sign this is easing."
    elif have_core:
        read = "Volatility and credit disagreed on the day, so there is no clean regime read."
        watch = "Watch for VIX and HY OAS to move in the same direction before drawing a conclusion."
    elif total and min(up, down) >= max(1, total // 4):
        read = "The tape showed dispersion rather than conviction on the day."
        watch = "A sustained move in the same direction across most sectors would change this."
    else:
        read = "The available data does not support a regime call today."
        watch = "A clearer alignment between rates, credit, and sector leadership would change this view."

    why = ("; ".join(facts) + ".") if facts else "No usable same-day changes were available."

    # A daily move that contradicts the week is the most useful thing a
    # deterministic summary can surface.
    doesnt_fit = "Nothing obvious stands out yet."
    if vix_d is not None and vix_w is not None and (vix_d >= 0) != (vix_w >= 0):
        doesnt_fit = (
            f"Today's VIX move ({vix_d:+.2f}%) runs against the week "
            f"({vix_w:+.2f}%)."
        )
    elif hy_d is not None and hy_w is not None and (hy_d >= 0) != (hy_w >= 0):
        doesnt_fit = (
            f"Today's HY OAS move ({hy_d:+.2f}pts) runs against the week "
            f"({hy_w:+.2f}pts)."
        )
    elif have_core and (vix_d >= 0) != (hy_d >= 0):
        doesnt_fit = "Volatility and credit are pointing in opposite directions today."

    missing = [k for k in ("VIX", "HY OAS", "10Y Treasury")
               if _horizon(macro_snapshot, k) is None]
    coverage = ""
    if missing:
        coverage = f"\nData gaps: no same-day change for {', '.join(missing)}."

    return f"""Read: {read}
Why (day-over-day only): {why}
What doesn't fit: {doesnt_fit}
Watch: {watch}{coverage}
"""


def analyze_market(macro_snapshot: Optional[Dict[str, Any]] = None, sector_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Returns the snapshots plus the analysis and an honest `source`:
      "claude"            - a complete model note
      "claude_incomplete" - a model note that failed a quality gate
      "fallback"          - the deterministic summary
    `warnings` carries the specific problems so delivery can label them.
    """
    if macro_snapshot is None:
        macro_snapshot = get_macro_snapshot()
    if sector_snapshot is None:
        sector_snapshot = get_sector_snapshot()

    prompt = build_analysis_prompt(macro_snapshot, sector_snapshot)
    claude = call_claude(prompt)

    warnings: List[str] = []
    if claude.get("text"):
        problems = check_analysis_quality(claude["text"], truncated=claude.get("truncated", False))
        analysis_text = claude["text"]
        source = "claude_incomplete" if problems else "claude"
        warnings = problems
    else:
        analysis_text = generate_fallback_analysis(macro_snapshot, sector_snapshot)
        source = "fallback"
        if claude.get("error"):
            warnings = [f"Claude unavailable: {claude['error']}"]

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "macro_snapshot": macro_snapshot,
        "sector_snapshot": sector_snapshot,
        "analysis": analysis_text,
        "source": source,
        "warnings": warnings,
    }


if __name__ == "__main__":
    result = analyze_market()
    print(result["analysis"])
    print(f"\n[source={result['source']}]")
    for warning in result["warnings"]:
        print(f"[warning] {warning}")
