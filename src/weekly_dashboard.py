"""
The weekly snapshot as Telegram text (message 1 of 2; the Claude note is 2).

Takes what weekly_snapshot.get_weekly_snapshot() returns and never fetches
anything itself, so the text always matches the data the note reasons about.
Rows are two lines each -- name and value, then 1W / 1M / 3M -- which reads
better on a phone than the daily one-liners.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from dashboard import (REQUIRED_MACRO_KEYS, RULE, SECTION_ICONS, format_as_of_label,
                       report_date, show_date)
from metrics import as_of_range
from sectors import GROUP_TITLES, SECTOR_GROUP_KEYS, all_metrics

MOVERS_PER_SIDE = 3

MACRO_SECTIONS = (
    ("🌡", "VOLATILITY & COMMODITIES", ("VIX", "WTI", "Gold", "Copper", "Gold/Copper")),
    ("📈", "RATES & CREDIT", ("10Y", "2Y", "2s10s", "HY OAS", "IG OAS")),
    ("💵", "DOLLAR", ("DXY",)),
)


def _section(icon, title, metrics, friday_iso):
    """Rows as two-line blocks. The as-of label appears only when the section's
    dates are not simply the week's Friday, so a normal week stays clean."""
    earliest, latest = as_of_range(metrics)
    label = ""
    if latest and (latest != friday_iso or earliest != latest):
        label = format_as_of_label(metrics)
    heading = f"{icon} {title}" + (f"  · {label}" if label else "")
    body = "\n".join("• " + m.render_block() for m in metrics)
    return f"{RULE}\n{heading}\n{RULE}\n{body}"


def weekly_movers(etfs, per_side=MOVERS_PER_SIDE):
    """(leaders, laggards) by 1W among ETFs that have one, best and worst first."""
    ranked = sorted((m for m in all_metrics(etfs) if m.is_usable and m.week_change is not None),
                    key=lambda m: m.week_change, reverse=True)
    per_side = min(per_side, len(ranked) // 2)
    if per_side == 0:
        return [], []
    return ranked[:per_side], ranked[::-1][:per_side]


def _movers_block(etfs):
    leaders, laggards = weekly_movers(etfs)
    if not leaders:
        return ""

    def line(metrics):
        return " · ".join(f"{m.symbol} {m.format_change('1W')}" for m in metrics)

    return f"🏆 Leaders 1W: {line(leaders)}\n📉 Laggards 1W: {line(laggards)}"


def _names(metrics):
    return ", ".join(m.symbol or m.key for m in metrics)


def weekly_data_notes(snapshot):
    """
    The footer: how to read the numbers and every gap, stated plainly.
    Source facts (contracts used, a VIX fallback) come from the snapshot.
    """
    _, friday = snapshot["week"]
    rows = list(snapshot["macro"].values()) + all_metrics(snapshot["etfs"])
    notes = list(snapshot.get("notes") or [])
    notes.append("ETF changes are price-only: Massive closes are split- but not dividend-adjusted")

    early = [m for m in rows if m.value is not None and m.as_of and m.as_of < friday.isoformat()]
    if early:
        notes.append("Last value before Friday (a holiday, or the source runs a day behind): "
                     + _names(early))
    short = [m for m in rows if m.value is not None and m.tracks_changes
             and m.week_change is not None and m.quarter_change is None]
    if short:
        notes.append("3M unavailable (under 13 weeks of history): " + _names(short))
    absent = [m for m in rows if m.value is None]
    if absent:
        notes.append("Missing this week: " + _names(absent))
    return notes


def is_weekly_degraded(snapshot):
    """
    True when the week should not be read as a normal report: a core series
    (VIX, HY OAS, 10Y) is unusable or every ETF is. Single gaps, early-dated
    values and the VIX fallback are footer notes only, as in the daily bot.
    """
    macro = snapshot["macro"]
    for key in REQUIRED_MACRO_KEYS:
        metric = macro.get(key)
        if metric is None or not metric.is_usable:
            return True
    etfs = all_metrics(snapshot["etfs"])
    return not any(m.is_usable for m in etfs)


def format_weekly_dashboard(snapshot, now=None):
    now = now or datetime.now(timezone.utc)
    _, friday = snapshot["week"]
    friday_iso = friday.isoformat()
    macro, etfs = snapshot["macro"], snapshot["etfs"]

    header = (f"📊 Weekly Market Dashboard\n"
              f"🗓 {snapshot['label']}, {friday.year} (KST report: {report_date(now)})\n"
              f"📏 Week-end closes: 1W vs previous Friday · 1M = 4 weeks · 3M = 13 weeks")
    blocks = [header, _movers_block(etfs)]

    for icon, title, keys in MACRO_SECTIONS:
        metrics = [macro[k] for k in keys if k in macro]
        if metrics:
            blocks.append(_section(icon, title, metrics, friday_iso))
    for key in SECTOR_GROUP_KEYS:
        group = etfs.get(key) or []
        if group:
            blocks.append(_section(SECTION_ICONS.get(key, "•"), GROUP_TITLES[key].upper(),
                                   group, friday_iso))

    notes = weekly_data_notes(snapshot)
    if notes:
        blocks.append("⚠️ Data notes:\n" + "\n".join("• " + n for n in notes))
    return "\n\n".join(b for b in blocks if b).strip()


if __name__ == "__main__":
    from weekly_snapshot import get_weekly_snapshot

    snapshot = get_weekly_snapshot()
    if os.getenv("GITHUB_ACTIONS") == "true":
        # Actions logs are public and Massive data may not be published.
        print("Values not printed in Actions.")
        sys.exit(0)
    text = format_weekly_dashboard(snapshot)
    print("\n" + text + "\n")
    print(f"[{len(text)} characters; degraded: {is_weekly_degraded(snapshot)}; "
          f"week of {show_date(snapshot['week'][0].isoformat())}]")
