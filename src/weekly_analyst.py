"""
Claude's weekly note (message 2 of 2), with a deterministic fallback.

Same persona and safety rails as the daily analyst, reframed for a Mon-Fri
week: 3M and 1M set the trend, 1W says whether this week continued or broke
it. The model is its own setting (WEEKLY_ANTHROPIC_MODEL / _EFFORT), so the
weekly report can move to a larger model without touching the daily one;
the request shape is the same on every current model, so that is a settings
change only.
"""
import os
import re
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(__file__))

from analyst import call_claude, check_analysis_quality
from sectors import GROUP_TITLES, SECTOR_GROUP_KEYS, all_metrics
from weekly_dashboard import weekly_data_notes, weekly_movers

DEFAULT_WEEKLY_MODEL = "claude-sonnet-5"
# One call a week over three horizons: worth more thinking than the daily's
# medium. low / medium / high / xhigh / max.
DEFAULT_WEEKLY_EFFORT = "high"

WEEKLY_SECTIONS = ("Regime Read", "Market Read", "Leadership", "Trend View",
                   "What Doesn't Fit", "Next Week Watch")
WEEKLY_WORD_BUDGET = 700
MIN_WEEKLY_WORDS = 150
MAX_WEEKLY_WORDS = 1000

HORIZON_NAMES = ("1W", "1M", "3M")


def weekly_model():
    return (os.getenv("WEEKLY_ANTHROPIC_MODEL") or DEFAULT_WEEKLY_MODEL).strip()


def weekly_effort():
    return (os.getenv("WEEKLY_ANTHROPIC_EFFORT") or DEFAULT_WEEKLY_EFFORT).strip().lower()


WEEKLY_SYSTEM_PROMPT = f"""You are a senior macro strategist with 15+ years across rates, FX, and cross-asset strategy. Write a weekly note for a small circle of investors who want your actual view, not a hedged sell-side summary.

Standing lens:
- Credit leads equities — check HY OAS before drawing conclusions from stock moves.
- Rates set the regime — treat yield levels and the 2s10s spread as the gravity everything else moves within.
- The 3M and 1M changes carry the trend. The 1W change tells you whether this week continued that trend or broke from it — never build the trend call on one week alone.
- Require cross-asset confirmation — a sector move without a matching signal elsewhere is noise until proven otherwise.

Voice: decisive, direct, and slightly skeptical. Do not be timid about being wrong. If the data does not support a strong call, say so plainly and use 'this doesn't add up yet' rather than forcing a polished story.

Analytical sequence — work strictly top-down and let each layer set the frame for the next:
1. Regime: bond yields (2Y, 10Y, 2s10s), credit (HY OAS against IG OAS — HY widening while IG holds is a different signal from both widening), commodities (WTI, gold, copper, the gold/copper ratio), the Dollar Index, and VIX.
2. Broad market: the US indices (Dow, S&P 500, Nasdaq 100, Russell 2000) and the regions (Korea, Japan, broad emerging markets). Do they confirm or contradict the regime?
3. Leadership: which sector and theme clusters led or lagged, and whether breadth supports the headline move.

How to read the data:
- Every change is measured on week-end closes: 1W is against the previous Friday's close, 1M against four weeks earlier, 3M against thirteen weeks earlier. "The week" means Monday to Friday.
- ETF changes are price-only (no dividends). HYG's price change leaves out its sizeable coupon, so do not read a small HYG price dip as credit stress unless HY OAS confirms it.
- WTI, gold and copper are the official settlement of the most-traded nearby futures contract.
- EWY is a US-listed, USD-denominated Korea ETF: a rough proxy that embeds the won's move. Never call it the KOSPI.
- Every row carries an "as of" date. A value dated before Friday is from an earlier day than the rest; say so when it matters for a comparison.
- Anything shown as N/A is unavailable: draw no inference from it, and note it if it weakens a step above.
- All inputs are daily closes. Never describe intraday behaviour.
- Only use data in the user message. Never cite outside news, events, or catalysts.

Length discipline: about {WEEKLY_WORD_BUDGET} words. Group tickers into clusters rather than walking through each one. Finishing every section below matters more than detail in any single one — an unfinished note is a failure.

The note is sent as a plain-text Telegram message: no Markdown (no #, ** or _ markers), no title line. Start each section with its name and a colon on a new line, e.g. "Regime Read: ...".

Format — use these section names exactly, in this order:
1. Regime Read: 2-3 sentences on what rates, credit, commodities, the dollar and VIX say together about the regime, and whether this week changed it
2. Market Read: 2-3 sentences on whether the indices and regions confirm or contradict the regime
3. Leadership: 2-3 sentences on which clusters led and lagged, and what breadth says about the quality of the move
4. Trend View: 2-3 sentences on the 1M/3M picture — your actual directional view — and whether this week continued or broke it
5. What Doesn't Fit: the contradictions or data caveats that keep you from being more confident
6. Next Week Watch: 2-3 specific tripwires that would change this view"""


# --- prompt ----------------------------------------------------------------------

def _row(metric):
    as_of = getattr(metric, "as_of", None)
    return f"- {metric.render_line()}" + (f"  [as of {as_of}]" if as_of else "")


def breadth(etfs, horizon):
    """(up, total) across every ETF with a change over that horizon."""
    changes = [m.change(horizon) for m in all_metrics(etfs) if m.is_usable]
    changes = [c for c in changes if c is not None]
    return sum(1 for c in changes if c >= 0), len(changes)


def _breadth_line(etfs):
    parts = []
    for horizon in HORIZON_NAMES:
        up, total = breadth(etfs, horizon)
        if total:
            parts.append(f"{up} of {total} up over {horizon}")
    return "; ".join(parts) or "not available"


def build_weekly_prompt(snapshot):
    macro, etfs = snapshot["macro"], snapshot["etfs"]
    leaders, laggards = weekly_movers(etfs)

    def movers(metrics):
        return ", ".join(f"{m.symbol} {m.format_change('1W')}" for m in metrics) or "n/a"

    groups = []
    for key in SECTOR_GROUP_KEYS:
        rows = etfs.get(key) or []
        if rows:
            groups.append(f"{GROUP_TITLES[key]}:\n" + "\n".join(_row(m) for m in rows))
    notes = "\n".join(f"- {n}" for n in weekly_data_notes(snapshot))

    return f"""Write the weekly note using the persona and format above.

Week covered: {snapshot['label']}, {snapshot['week'][1].year} (Monday to Friday).
Changes: 1W vs the previous Friday's close · 1M = 4 weeks · 3M = 13 weeks, all on week-end closes.

Macro data:
{chr(10).join(_row(m) for m in macro.values()) or "No data available"}

ETF data (US-listed ETFs, price-only changes):
{chr(10).join(groups) or "No data available"}

Breadth (ETFs up or flat): {_breadth_line(etfs)}
Week's leaders (1W): {movers(leaders)}
Week's laggards (1W): {movers(laggards)}

Data notes:
{notes or "- none"}
"""


# --- fallback --------------------------------------------------------------------

def _macro_change(snapshot, key, horizon):
    metric = snapshot["macro"].get(key)
    return metric.change(horizon) if metric is not None and metric.is_usable else None


def _etf_change(snapshot, symbol, horizon):
    for metric in all_metrics(snapshot["etfs"]):
        if metric.symbol == symbol and metric.is_usable:
            return metric.change(horizon)
    return None


def _moved(value, unit, rising="rose", falling="fell"):
    return f"{rising if value >= 0 else falling} {abs(value):.2f}{unit}"


def generate_weekly_fallback(snapshot):
    """
    Deterministic stand-in when Claude is unavailable. It states only what the
    numbers show, and claims a regime only when volatility and credit agree
    over the week -- the same restraint as the daily fallback.
    """
    vix_w = _macro_change(snapshot, "VIX", "1W")
    hy_w = _macro_change(snapshot, "HY OAS", "1W")
    up, total = breadth(snapshot["etfs"], "1W")

    if vix_w is None and hy_w is None and total == 0:
        return ("Regime Read: Insufficient data for a regime call.\n"
                "Why: Neither the core macro series (VIX, HY OAS) nor any ETF changes "
                "were available this week, so no directional statement is supportable.\n"
                "Next Week Watch: Restore the data feed before reading anything into this week.\n")

    facts = []
    for key, label, unit, words in (
            ("VIX", "VIX", "%", ("rose", "fell")),
            ("HY OAS", "HY OAS", "pts", ("widened", "tightened")),
            ("IG OAS", "IG OAS", "pts", ("widened", "tightened")),
            ("10Y", "the 10Y", "pts", ("rose", "fell")),
            ("2s10s", "2s10s", "pts", ("steepened", "flattened")),
            ("DXY", "the Dollar Index", "%", ("rose", "fell"))):
        change = _macro_change(snapshot, key, "1W")
        if change is not None:
            facts.append(f"{label} {_moved(change, unit, *words)}")
    if total:
        facts.append(f"{up} of {total} tracked ETFs finished the week higher or flat")
    leaders, laggards = weekly_movers(snapshot["etfs"])
    if leaders:
        facts.append("leaders " + ", ".join(f"{m.symbol} {m.format_change('1W')}" for m in leaders)
                     + "; laggards " + ", ".join(f"{m.symbol} {m.format_change('1W')}" for m in laggards))

    if vix_w is not None and hy_w is not None and vix_w < 0 and hy_w < 0:
        regime = "Risk appetite improved over the week, with volatility and credit agreeing."
    elif vix_w is not None and hy_w is not None and vix_w > 0 and hy_w > 0:
        regime = "Risk was under pressure over the week, with volatility and credit agreeing."
    elif vix_w is not None and hy_w is not None:
        regime = "Volatility and credit disagreed over the week, so there is no clean regime read."
    else:
        regime = "The available data does not support a regime call this week."

    spy_q = _etf_change(snapshot, "SPY", "3M")
    hy_q = _macro_change(snapshot, "HY OAS", "3M")
    if spy_q is not None and hy_q is not None:
        trend = (f"Over 13 weeks the S&P 500 (SPY) {_moved(spy_q, '%')} while HY OAS "
                 f"{_moved(hy_q, 'pts', 'widened', 'tightened')}"
                 + ("; credit and equities agree on the trend." if (spy_q >= 0) == (hy_q <= 0)
                    else "; credit is not confirming the equity trend."))
    else:
        trend = "The 3M trend cannot be assessed from the available data."

    doesnt_fit = "Nothing obvious stands out from the numbers alone."
    spy_w = _etf_change(snapshot, "SPY", "1W")
    ig_w = _macro_change(snapshot, "IG OAS", "1W")
    if spy_w is not None and spy_q is not None and (spy_w >= 0) != (spy_q >= 0):
        doesnt_fit = f"This week's SPY move ({spy_w:+.2f}%) runs against its 3M trend ({spy_q:+.2f}%)."
    elif hy_w is not None and hy_q is not None and (hy_w >= 0) != (hy_q >= 0):
        doesnt_fit = f"This week's HY OAS move ({hy_w:+.2f}pts) runs against its 3M trend ({hy_q:+.2f}pts)."
    elif hy_w is not None and ig_w is not None and (hy_w >= 0) != (ig_w >= 0):
        doesnt_fit = "High yield and investment grade credit moved in opposite directions this week."

    return (f"Regime Read: {regime}\n"
            f"Why (week-end closes): {'; '.join(facts) + '.' if facts else 'No usable weekly changes.'}\n"
            f"Trend View: {trend}\n"
            f"What Doesn't Fit: {doesnt_fit}\n"
            "Next Week Watch: A move in VIX and HY OAS in the same direction would set the "
            "next regime read; watch whether breadth follows the leaders.\n")


# --- the note --------------------------------------------------------------------

def plain_text(text):
    """
    Strips Markdown the prompt asks the model not to use. Telegram gets this
    as plain text, so a '## Regime Read' or '**bold**' would show literally,
    and models differ in how firmly they follow a formatting instruction.
    """
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        lines.append(line.replace("**", "").replace("__", ""))
    return "\n".join(lines).strip()


def analyze_week(snapshot):
    """
    {"analysis", "source", "warnings", "model"}, with the same `source`
    contract as analyst.analyze_market:
      "claude"            - a complete model note
      "claude_incomplete" - a model note that failed a quality gate
      "fallback"          - the deterministic note
    """
    model, effort = weekly_model(), weekly_effort()
    claude = call_claude(build_weekly_prompt(snapshot), system=WEEKLY_SYSTEM_PROMPT,
                         model=model, effort=effort)

    warnings: List[str] = []
    if claude.get("text"):
        warnings = check_analysis_quality(
            claude["text"], truncated=claude.get("truncated", False),
            sections=WEEKLY_SECTIONS, min_words=MIN_WEEKLY_WORDS,
            max_words=MAX_WEEKLY_WORDS, budget_words=WEEKLY_WORD_BUDGET)
        source = "claude_incomplete" if warnings else "claude"
        # Signed, so the chat always shows which model wrote the note.
        analysis = f"{plain_text(claude['text'])}\n\n— {model} · effort {effort}"
    else:
        analysis = generate_weekly_fallback(snapshot)
        source = "fallback"
        if claude.get("error"):
            warnings = [f"Claude unavailable: {claude['error']}"]

    return {"analysis": analysis, "source": source, "warnings": warnings, "model": model}


if __name__ == "__main__":
    from weekly_snapshot import get_weekly_snapshot

    result = analyze_week(get_weekly_snapshot())
    if os.getenv("GITHUB_ACTIONS") == "true":
        # Actions logs are visible to others, and the note quotes Massive data.
        print(f"source={result['source']} (note not printed in Actions)")
        sys.exit(0)
    print("\n" + result["analysis"])
    print(f"\n[source={result['source']} model={result['model']} "
          f"words={len(result['analysis'].split())}]")
    for warning in result["warnings"]:
        print(f"[warning] {warning}")
