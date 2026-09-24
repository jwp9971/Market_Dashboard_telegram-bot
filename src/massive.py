"""
Massive collectors for the weekly commentary: ETFs, Treasury yields, futures.

Each collector fetches dated daily series and hands them to
weeks.weekly_metric(), so the Mon-Fri week rules live in one place. Every
request goes through massive_client.MassiveClient (rate limit, retries,
budget); nothing here prints a data value.
"""
import os
import re
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(__file__))

from metrics import (CHANGE_LEVEL, CHANGE_PCT, UNIT_PERCENT, UNIT_RATIO,
                     UNIT_USD, WEEKLY_HORIZONS, Metric, last_expected_session)
from sectors import ETF_GROUPS, SECTOR_GROUP_KEYS
from weeks import MAX_WEEKS_BACK, WEEKS_BACK, normalise, week_of, weekly_metric

SOURCE = "massive"

# --- ETFs: grouped daily -----------------------------------------------------


def grouped_daily_closes(client, day, now=None):
    """
    {ticker: close} for one US session, or {} when there was none.

    A weekend or holiday comes back as status OK with no `results` key at all
    (probe, 2026-09-24). Only a day before the latest completed session is
    cached, so an answer fetched before Massive has the day can't be frozen.
    """
    settled = day < last_expected_session(now)
    body = client.get(f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}",
                      {"adjusted": "true"}, "stocks", cache=settled)
    return {row["T"]: row["c"] for row in body.get("results") or []
            if row.get("T") and row.get("c") is not None}


def etf_week_end_series(client, friday, now=None):
    """
    {ticker: [(date, close), ...]} holding each needed week's last close.

    Only the weeks the changes use are fetched -- this week, 1, 4 and 13 back
    -- one grouped-daily call each, stepping back a day when a date had no
    session (a holiday Friday costs one more call).
    """
    series = {}
    for weeks_back in sorted({0, *WEEKS_BACK.values()}):
        monday, day = week_of(friday, weeks_back)
        while day >= monday:
            closes = grouped_daily_closes(client, day, now)
            if closes:
                for ticker, close in closes.items():
                    series.setdefault(ticker, []).append((day, close))
                break
            day -= timedelta(days=1)
    return series


def get_etf_snapshot(client, friday, now=None):
    """{group: [Metric]} in SECTOR_GROUP_KEYS order, like sectors.get_sector_snapshot."""
    series = etf_week_end_series(client, friday, now)
    return {
        group: [weekly_metric(symbol, label, series.get(symbol, []), friday,
                              UNIT_USD, CHANGE_PCT, source=SOURCE, symbol=symbol)
                for symbol, label in ETF_GROUPS[group].items()]
        for group in SECTOR_GROUP_KEYS
    }


# --- Treasury yields: Economy API ----------------------------------------------

YIELD_FIELDS = {"10Y": ("10Y Treasury", "yield_10_year"),
                "2Y": ("2Y Treasury", "yield_2_year")}


def get_yield_metrics(client, friday):
    """10Y, 2Y and 2s10s from one call; changes are level changes in points."""
    since, _ = week_of(friday, MAX_WEEKS_BACK)
    body = client.get("/fed/v1/treasury-yields", {
        "date.gte": since.isoformat(), "date.lte": friday.isoformat(),
        "sort": "date.desc", "limit": 200,
    }, "economy")
    rows = body.get("results") or []
    series = {key: [(row.get("date"), row.get(field)) for row in rows]
              for key, (_, field) in YIELD_FIELDS.items()}

    metrics = {key: weekly_metric(key, label, series[key], friday, UNIT_PERCENT,
                                  CHANGE_LEVEL, source=SOURCE)
               for key, (label, _) in YIELD_FIELDS.items()}

    ten, two = dict(normalise(series["10Y"])), dict(normalise(series["2Y"]))
    spread = [(day, ten[day] - two[day]) for day in ten if day in two]
    metrics["2s10s"] = weekly_metric("2s10s", "2s10s Spread", spread, friday,
                                     UNIT_PERCENT, CHANGE_LEVEL, source=SOURCE)
    return metrics


# --- Futures: most-traded nearby contract ----------------------------------------

FUTURES = {"WTI": ("CL", "WTI Crude"), "Gold": ("GC", "Gold"), "Copper": ("HG", "Copper")}

MONTH_CODES = "FGHJKMNQUVXZ"
CANDIDATE_MONTHS = 8
CANDIDATES = 3
# In its last two weeks a contract's volume has already moved to the next
# one; without this the expiring month crowds December gold out of the top 3.
SKIP_WITHIN_DAYS = 14
VOLUME_SESSIONS = 5


def candidate_tickers(code, reference, months=CANDIDATE_MONTHS):
    """This month's outright contract and the next few: GCV6, GCX6, GCZ6, ..."""
    tickers, year, month = [], reference.year, reference.month
    for _ in range(months):
        tickers.append(f"{code}{MONTH_CODES[month - 1]}{year % 10}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return tickers


def is_outright(ticker, code):
    """
    GCZ6 yes; CL:BF F7-G7-H7 or HG:SA 03M F7 no. Massive labels those spreads
    type="single" too, so the ticker's shape is the reliable test.
    """
    return bool(re.fullmatch(rf"{code}[{MONTH_CODES}]\d{{1,2}}", str(ticker or "")))


def pick_candidates(contracts, code, friday):
    """The next CANDIDATES outright contracts not about to expire, nearest first."""
    cutoff = (friday + timedelta(days=SKIP_WITHIN_DAYS)).isoformat()
    usable = {c["ticker"]: c for c in contracts
              if is_outright(c.get("ticker"), code)
              and str(c.get("last_trade_date") or "") >= cutoff}
    return sorted(usable.values(), key=lambda c: str(c.get("last_trade_date")))[:CANDIDATES]


def settled_bars(bars, through):
    """
    Finished sessions only, dated by session_end_date (window_start is the
    previous calendar day). A bar with no settlement price is a session still
    trading, so it is left out.
    """
    return [bar for bar in bars
            if bar.get("settlement_price") is not None
            and str(bar.get("session_end_date") or "") <= through.isoformat()]


def recent_volume(bars, sessions=VOLUME_SESSIONS):
    latest = sorted(bars, key=lambda b: str(b.get("session_end_date")), reverse=True)
    return sum(bar.get("volume") or 0 for bar in latest[:sessions])


def get_futures_series(client, code, friday):
    """
    (contract ticker, [(session date, settlement price), ...]) for the most
    traded of the next few contracts, or (None, []) if none has data.

    All three horizons come from that one contract, so a roll between
    contracts can never show up as a price jump.
    """
    contracts = []
    # Without date= the endpoint lists every contract once per day back to
    # 2025; one day's snapshot lists each contract once. The snapshot for the
    # current day can still be empty (gold was, on 2026-09-24), so step back
    # a day once if needed.
    for snapshot in (friday, friday - timedelta(days=1)):
        contracts = client.get("/futures/v1/contracts", {
            "ticker.any_of": ",".join(candidate_tickers(code, friday)),
            "date": snapshot.isoformat(), "limit": 100,
        }, "futures").get("results") or []
        if contracts:
            break

    since, _ = week_of(friday, MAX_WEEKS_BACK)
    best = None
    for contract in pick_candidates(contracts, code, friday):
        ticker = contract["ticker"]
        bars = client.get(f"/futures/v1/aggs/{ticker}", {
            "resolution": "1session",
            "window_start.gte": (since - timedelta(days=1)).isoformat(),
            "limit": 200,
        }, "futures").get("results") or []
        bars = settled_bars(bars, friday)
        if bars and (best is None or recent_volume(bars) > best[0]):
            best = (recent_volume(bars), ticker, bars)

    if best is None:
        return None, []
    _, ticker, bars = best
    return ticker, [(bar["session_end_date"], bar["settlement_price"]) for bar in bars]


def get_futures_metrics(client, friday):
    """WTI, Gold, Copper and the Gold/Copper ratio, each from its chosen contract."""
    metrics = {}
    for key, (code, label) in FUTURES.items():
        ticker, series = get_futures_series(client, code, friday)
        metrics[key] = weekly_metric(key, label, series, friday, UNIT_USD, CHANGE_PCT,
                                     source=SOURCE, symbol=ticker or code)

    gold, copper = metrics["Gold"], metrics["Copper"]
    metrics["Gold/Copper"] = Metric(
        key="Gold/Copper", label="Gold/Copper Ratio",
        value=(round(gold.value / copper.value, 2)
               if gold.value is not None and copper.value else None),
        unit=UNIT_RATIO, tracks_changes=False, horizons=WEEKLY_HORIZONS,
        as_of=gold.as_of or copper.as_of, source=SOURCE,
    )
    return metrics
