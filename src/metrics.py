"""
One structured record per measurement.

Collectors used to turn numbers into display strings immediately, and every
downstream consumer then had to read those strings back -- which is how the
fallback ended up searching for arrow glyphs and inverting the day's signal.
Numbers, units, dates and quality now stay structured all the way to the
presentation boundary; only render() turns them into text.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

# How to render the value itself.
UNIT_USD = "usd"
UNIT_KRW = "krw"
UNIT_PERCENT = "percent"
UNIT_INDEX = "index"
UNIT_RATIO = "ratio"

# How to interpret the changes: a percentage return, or a move in the level
# itself (percentage points, for yields and spreads already quoted in %).
CHANGE_PCT = "pct"
CHANGE_LEVEL = "level"

# How many calendar days an observation may lag before it counts as stale.
# Calendar days, not business days, on purpose: a business-day rule needs a
# market-holiday calendar (a new dependency, or a hardcoded list that rots).
# These tolerances absorb a weekend plus a holiday instead. The cost is that a
# genuinely stale series can slip through for an extra day or two.
MAX_AGE_MARKET_DAYS = 4    # equities and daily Yahoo series
MAX_AGE_FRED_RATES = 5     # H.15 reaches FRED about a business day later
MAX_AGE_FRED_OAS = 5       # ICE BofA OAS routinely lags one business day
# Both FRED tolerances were raised from 4 after a live run on 2026-09-15 held
# Friday's yields on a Tuesday -- 4 days, exactly at the old limit, so the
# next Monday holiday would have produced a false alarm.

UP = "▲"
DOWN = "▼"

HORIZONS = (("D/D", "day_change"), ("1W", "week_change"), ("1M", "month_change"))


def to_iso_date(value: Any) -> Optional[str]:
    """Normalises whatever a data source hands back into 'YYYY-MM-DD'."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return (value.date() if isinstance(value, datetime) else value).isoformat()
    text = str(value).strip()
    if not text:
        return None
    # Timestamps arrive as '2026-09-12T00:00:00-04:00' or '2026-09-12 00:00:00'.
    for separator in ("T", " "):
        if separator in text:
            text = text.split(separator, 1)[0]
            break
    return text or None


@dataclass
class Metric:
    key: str
    label: str
    value: Optional[float] = None
    day_change: Optional[float] = None
    week_change: Optional[float] = None
    month_change: Optional[float] = None
    unit: str = UNIT_INDEX
    change_kind: str = CHANGE_PCT
    as_of: Optional[str] = None
    source: str = ""
    symbol: str = ""
    error: Optional[str] = None
    # False for derived values (a ratio, say) that legitimately have no change
    # series, so they render bare instead of claiming a missing D/D.
    tracks_changes: bool = True
    # Tolerance for this metric's source; None means never judged stale.
    max_age_days: Optional[int] = None
    # Set by mark_staleness() so status stays a pure function of the record
    # rather than silently depending on when it happens to be read.
    stale: bool = False

    @property
    def status(self) -> str:
        """Derived, never set by hand, so it cannot drift from the data."""
        if self.error:
            return "error"
        if self.value is None:
            return "missing"
        if self.stale:
            return "stale"
        if self.day_change is None and self.tracks_changes:
            return "partial"
        return "ok"

    @property
    def is_usable(self) -> bool:
        """Stale data is still shown -- a dated number beats a hidden one --
        but it is not treated as a healthy input."""
        return self.status in ("ok", "partial")

    def age_days(self, today: Optional[date] = None) -> Optional[int]:
        if not self.as_of:
            return None
        try:
            observed = datetime.strptime(self.as_of, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
        return ((today or datetime.now(timezone.utc).date()) - observed).days

    def is_stale_at(self, today: Optional[date] = None) -> bool:
        if self.max_age_days is None or self.value is None:
            return False
        age = self.age_days(today)
        return age is not None and age > self.max_age_days

    def change(self, horizon: str) -> Optional[float]:
        """Numeric change over one named horizon: 'D/D', '1W' or '1M'."""
        for name, attribute in HORIZONS:
            if name == horizon:
                return getattr(self, attribute)
        return None

    # --- presentation boundary ------------------------------------------

    def format_value(self) -> str:
        if self.value is None:
            return "N/A"
        if self.unit == UNIT_USD:
            return f"${self.value:,.2f}"
        if self.unit == UNIT_KRW:
            return f"₩{self.value:,.1f}"
        if self.unit == UNIT_PERCENT:
            return f"{self.value:.2f}%"
        if self.unit == UNIT_RATIO:
            return f"{self.value:,.1f}"
        return f"{self.value:,.2f}"

    def format_changes(self) -> str:
        if not self.tracks_changes:
            return ""
        suffix = "%" if self.change_kind == CHANGE_PCT else "pts"
        parts = []
        for name, attribute in HORIZONS:
            change = getattr(self, attribute)
            if change is None:
                if name == "D/D":
                    parts.append("D/D N/A")
                continue
            # Judge direction on the value actually displayed: a change that
            # rounds to 0.00 is flat, and "up zero" reads as a mistake.
            shown = round(change, 2)
            if shown == 0:
                parts.append(f"{abs(shown):.2f}{suffix} {name}")
            else:
                arrow = UP if shown > 0 else DOWN
                parts.append(f"{arrow}{abs(shown):.2f}{suffix} {name}")
        return " | ".join(parts)

    def format_as_of(self) -> str:
        if not self.as_of:
            return ""
        try:
            return datetime.strptime(self.as_of, "%Y-%m-%d").strftime("%b %d")
        except (ValueError, TypeError):
            return str(self.as_of)

    def render(self) -> str:
        """'4.10% (▲0.05pts D/D | ▼0.20pts 1W)'"""
        if self.error:
            return f"N/A ({self.error})"
        if self.value is None:
            return "N/A"
        changes = self.format_changes()
        text = f"{self.format_value()} ({changes})" if changes else self.format_value()
        if self.stale:
            text += f"  \u26a0 STALE, as of {self.format_as_of()}"
        return text

    def render_line(self) -> str:
        """'S&P 500 (SPY): $612.40 (▲0.42% D/D)'"""
        name = f"{self.label} ({self.symbol})" if self.symbol else self.label
        return f"{name}: {self.render()}"


def missing(key, label, source="", symbol="", error=None, **kwargs) -> Metric:
    """A metric a collector could not produce, kept in place so the report
    shows the gap rather than silently dropping the row."""
    return Metric(key=key, label=label, source=source, symbol=symbol,
                  error=error, **kwargs)


def latest_as_of(metrics) -> Optional[str]:
    dates = [m.as_of for m in metrics if getattr(m, "as_of", None)]
    return max(dates) if dates else None


def as_of_range(metrics):
    """(earliest, latest) observation dates across a set of metrics, so a
    report can disclose when its inputs are not from the same session."""
    dates = sorted({m.as_of for m in metrics if getattr(m, "as_of", None)})
    if not dates:
        return None, None
    return dates[0], dates[-1]


def mark_staleness(metrics, today: Optional[date] = None):
    """
    Evaluates staleness once, at a known point, so `today` is injectable and
    Metric.status never depends on when it is read. Returns the metrics.
    """
    today = today or datetime.now(timezone.utc).date()
    for metric in metrics:
        metric.stale = metric.is_stale_at(today)
    return metrics


def stale_metrics(metrics):
    return [m for m in metrics if m.status == "stale"]
