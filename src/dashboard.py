import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from macro import get_macro_snapshot
from metrics import Metric, as_of_range, stale_metrics
from sectors import GROUP_TITLES, SECTOR_GROUP_KEYS, all_metrics, get_sector_snapshot
from telegram_bot import send_long_message

# Korea has had no daylight saving since 1988, so a fixed +9 offset is exact
# and needs no tzdata on the machine. The report is read in Seoul; labelling
# it with the runner's UTC date would show the previous day every morning.
KST = timezone(timedelta(hours=9), "KST")

RULE = "\u2501" * 20

# Without these the report is not a market read, it is a list of gaps.
REQUIRED_MACRO_KEYS = ("VIX", "HY OAS", "10Y")

SECTION_ICONS = {
    "macro": "\U0001f30d",
    "broad_industry": "\U0001f3ed",
    "theme": "\U0001f3af",
}


def report_date(now=None):
    return (now or datetime.now(KST)).strftime("%A, %B %d, %Y")


def show_date(iso):
    return Metric(key="", label="", as_of=iso).format_as_of() if iso else ""


def format_as_of_label(metrics):
    """'as of Sep 12', or 'as of Sep 10-Sep 12' when inputs disagree."""
    earliest, latest = as_of_range(metrics)
    if not latest:
        return ""
    if earliest and earliest != latest:
        return "as of {}\u2013{}".format(show_date(earliest), show_date(latest))
    return "as of {}".format(show_date(latest))


def _section(icon, title, metrics, baseline=None):
    """The as-of label prints only when this section disagrees with the
    report-wide date, so a normal report stays clean and a skewed one is loud."""
    earliest, latest = as_of_range(metrics)
    label = ""
    if latest and (latest != baseline or (earliest and earliest != latest)):
        label = format_as_of_label(metrics)
    heading = "{} {}".format(icon, title) + ("  \u00b7 " + label if label else "")
    body = "\n".join("\u2022 " + m.render_line() for m in metrics)
    return "{}\n{}\n{}\n{}".format(RULE, heading, RULE, body)


def _pick(macro, *keys):
    return [macro[k] for k in keys if k in macro]


def _all_metrics(macro, sectors):
    return [m for m in macro.values() if hasattr(m, "status")] + all_metrics(sectors)


def _name_list(metrics, limit=6):
    names = ", ".join(m.symbol or m.label for m in metrics[:limit])
    more = " +{} more".format(len(metrics) - limit) if len(metrics) > limit else ""
    return names + more


def is_data_degraded(macro, sectors):
    """True when the report went out on data that should not be trusted as a
    normal reading: a core input missing, or anything past its staleness
    tolerance. main.py turns this into a non-zero exit."""
    everything = _all_metrics(macro, sectors)
    if any(m.status == "stale" for m in everything):
        return True
    for key in REQUIRED_MACRO_KEYS:
        metric = macro.get(key)
        if metric is None or not metric.is_usable:
            return True
    etfs = all_metrics(sectors)
    return bool(etfs) and not any(m.is_usable for m in etfs)


def build_data_notes(macro, sectors):
    """A short, honest footer: what is missing or stale, which tape served the
    ETF closes, and whether credit is from a different session than equities."""
    notes = []

    everything = _all_metrics(macro, sectors)
    stale = stale_metrics(everything)
    broken = [m for m in everything if m.status in ("missing", "error")]

    if broken:
        notes.append("{} of {} series unavailable ({})".format(
            len(broken), len(everything), _name_list(broken)))

    if stale:
        notes.append("{} series past their freshness window ({})".format(
            len(stale), _name_list(stale)))

    feed_note = sectors.get("feed_note")
    if feed_note:
        notes.append(feed_note)
    elif sectors.get("feed") == "iex":
        notes.append("ETF closes are IEX-only (one exchange); thinly traded "
                     "funds may be unreliable")

    # The prompt tells the analyst that credit leads equities. If the credit
    # data is a session behind, that instruction is being applied across a
    # date gap, so say so rather than leaving it implicit.
    _, credit_date = as_of_range(_pick(macro, "10Y", "2Y", "HY OAS", "IG OAS"))
    _, equity_date = as_of_range(all_metrics(sectors))
    if credit_date and equity_date and credit_date < equity_date:
        notes.append(
            "rates/credit data is from {}, equities from {} "
            "\u2014 not the same session".format(credit_date, equity_date))

    return notes


def format_dashboard(macro, sectors, now=None):
    macro = macro or {}
    sectors = sectors or {}

    everything = list(macro.values()) + all_metrics(sectors)
    _, baseline = as_of_range(everything)

    header = "\U0001f4ca Daily Market Dashboard\n\U0001f5d3 {} (KST)".format(report_date(now))
    if baseline:
        header += "\n\U0001f4cd Market data as of {}".format(show_date(baseline))

    blocks = [
        header,
        _section("\U0001f321", "VOLATILITY & COMMODITIES",
                 _pick(macro, "VIX", "WTI", "Gold", "Copper", "Gold/Copper"), baseline),
        _section("\U0001f4c8", "RATES & CREDIT",
                 _pick(macro, "10Y", "2Y", "2s10s", "HY OAS", "IG OAS"), baseline),
        _section("\U0001f4b5", "FX & DOLLAR",
                 _pick(macro, "USDKRW", "DXY"), baseline),
    ]

    for key in SECTOR_GROUP_KEYS:
        group = sectors.get(key) or []
        if group:
            blocks.append(_section(SECTION_ICONS.get(key, "\u2022"),
                                   GROUP_TITLES[key].upper(), group, baseline))

    notes = build_data_notes(macro, sectors)
    if notes:
        blocks.append("\u26a0\ufe0f Data notes: " + "; ".join(notes) + ".")

    return "\n\n".join(b for b in blocks if b).strip()


def build_dashboard():
    return format_dashboard(get_macro_snapshot(), get_sector_snapshot())


def send_dashboard():
    """Standalone dashboard send. Routed through send_long_message so it gets
    the same length handling as the scheduled report."""
    print("Sending daily dashboard...")
    sent = send_long_message(build_dashboard())
    print("Dashboard sent." if sent else "Dashboard delivery FAILED.")
    return sent


if __name__ == "__main__":
    sys.exit(0 if send_dashboard() else 1)
