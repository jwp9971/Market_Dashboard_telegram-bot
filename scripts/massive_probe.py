"""
The only script that calls Massive live. Run it by hand, never in Actions.

    python scripts/massive_probe.py

It checks what the docs leave open -- ETF coverage in grouped daily, what a
weekend date returns, treasury-yield fields and lag, futures contract codes
and which contract is most traded -- and saves every raw answer under the
gitignored cache/massive/ for inspection. It prints structure (counts, field
names, dates, ticker symbols), never prices or yields: Massive's terms forbid
publishing its data and this repo is public.

Up to about 15 futures calls, so the rate limiter makes it take roughly three
minutes. Answers already cached today are reused for free.
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from massive_client import MassiveClient, MassiveError  # noqa: E402
from metrics import last_expected_session  # noqa: E402
from sectors import ETF_GROUPS  # noqa: E402

FUTURES_PRODUCTS = {"CL": "WTI crude", "GC": "Gold", "HG": "Copper"}


def section(title):
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def fields(record):
    return ", ".join(sorted(record)) if isinstance(record, dict) else type(record).__name__


def probe_stocks(client, session, saturday):
    section(f"Stocks: grouped daily {session}")
    body = client.get(f"/v2/aggs/grouped/locale/us/market/stocks/{session}",
                      {"adjusted": "true"}, "stocks", cache=True)
    results = body.get("results") or []
    print(f"status={body.get('status')} adjusted={body.get('adjusted')} resultsCount={body.get('resultsCount')}")
    if results:
        print(f"result fields: {fields(results[0])}")
    wanted = [symbol for group in ETF_GROUPS.values() for symbol in group]
    present = {row.get("T") for row in results}
    missing = [symbol for symbol in wanted if symbol not in present]
    print(f"our ETFs present: {len(wanted) - len(missing)}/{len(wanted)}"
          + (f"  MISSING: {', '.join(missing)}" if missing else ""))

    section(f"Stocks: grouped daily on a Saturday ({saturday})")
    try:
        body = client.get(f"/v2/aggs/grouped/locale/us/market/stocks/{saturday}",
                          {"adjusted": "true"}, "stocks", cache=True)
        print(f"status={body.get('status')} resultsCount={body.get('resultsCount')} "
              f"results={'absent' if 'results' not in body else len(body['results'] or [])} "
              f"keys: {fields(body)}")
    except MassiveError as exc:
        print(f"raised {type(exc).__name__}: {exc}")


def probe_economy(client, today):
    since = (today - timedelta(days=14)).isoformat()
    section(f"Economy: treasury yields since {since}")
    body = client.get("/fed/v1/treasury-yields",
                      {"date.gte": since, "sort": "date.desc", "limit": 10},
                      "economy", cache=True)
    results = body.get("results") or []
    print(f"status={body.get('status')} rows={len(results)}")
    if results:
        print(f"fields: {fields(results[0])}")
        dates = [row.get("date") for row in results]
        print(f"dates (newest first): {', '.join(str(d) for d in dates)}")
        for name in ("yield_2_year", "yield_10_year"):
            filled = sum(1 for row in results if row.get(name) is not None)
            print(f"{name}: filled on {filled}/{len(results)} rows")


def probe_products(client):
    """Futures product codes on COMEX (XCEC) and NYMEX (XNYM): names and codes only."""
    for venue in ("XCEC", "XNYM"):
        section(f"Futures products on {venue}")
        body = client.get("/futures/v1/products",
                          {"trading_venue": venue, "limit": 1000}, "futures", cache=True)
        results = body.get("results") or []
        print(f"products: {len(results)}")
        for row in results:
            name = str(row.get("name") or "")
            if any(word in name.lower() for word in ("gold", "copper", "crude", "wti")):
                print(f"  {row.get('product_code'):<6} type={row.get('type')}  {name}")


def _recent_volume(rows, sessions=5):
    """Volume over the latest few sessions; bars arrive newest first."""
    ordered = sorted(rows, key=lambda r: str(r.get("session_end_date")), reverse=True)
    return sum(r.get("volume") or 0 for r in ordered[:sessions])


# A plain outright contract: product code, month letter, year digit(s), e.g.
# GCZ6. Spreads and combos (CL:BF F7-G7-H7, HG:SA 03M F7) are labelled
# type="single" too, so the ticker shape is the reliable test.
MONTH_CODES = "FGHJKMNQUVXZ"


def is_outright(ticker, code):
    return bool(re.fullmatch(rf"{code}[{MONTH_CODES}]\d{{1,2}}", str(ticker)))


def candidate_tickers(code, today, months=8):
    """This month's contract and the next few: GCV6, GCX6, GCZ6, GCF7, ..."""
    tickers = []
    year, month = today.year, today.month
    for _ in range(months):
        tickers.append(f"{code}{MONTH_CODES[month - 1]}{year % 10}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return tickers


def probe_futures(client, today, session):
    since = (today - timedelta(weeks=14)).isoformat()
    for code, name in FUTURES_PRODUCTS.items():
        section(f"Futures: {name} ({code}) -- next 3 single contracts")
        try:
            # The endpoint only sorts by date/product_code/ticker, so fetch the
            # contracts expiring in the next ~7 months and order them here.
            body = client.get("/futures/v1/contracts", {
                # Without date= the endpoint returns one row per contract per
                # day back to 2025; one day's snapshot lists each contract once.
                # Paging through every listed spread is wasteful, so ask for
                # the outright tickers we can name ourselves.
                "ticker.any_of": ",".join(candidate_tickers(code, today)),
                "date": session, "limit": 100,
            }, "futures", cache=True)
        except MassiveError as exc:
            print(f"contracts lookup raised {type(exc).__name__}: {exc}")
            continue
        listed = body.get("results") or []
        outrights = [c for c in listed if is_outright(c.get("ticker"), code)
                     # In its last two weeks a contract's volume has already
                     # moved to the next one, so it is never a candidate.
                     and str(c.get("last_trade_date")) >= (today + timedelta(days=14)).isoformat()]
        contracts = sorted(outrights, key=lambda c: str(c.get("last_trade_date")))[:3]
        print(f"contracts returned: {len(listed)}, outrights: {len(outrights)}; nearest three: "
              + ", ".join(str(c.get("ticker")) for c in contracts))
        candidates = []
        for contract in contracts:
            ticker = contract.get("ticker")
            try:
                bars = client.get(f"/futures/v1/aggs/{ticker}", {
                    "resolution": "1session", "window_start.gte": since, "limit": 200,
                }, "futures", cache=True)
            except MassiveError as exc:
                print(f"  {ticker}: bars raised {type(exc).__name__}: {exc}")
                continue
            rows = bars.get("results") or []
            dates = sorted(str(r.get("session_end_date")) for r in rows)
            settled = sum(1 for r in rows if r.get("settlement_price") is not None)
            print(f"  {ticker:<6} last_trade={contract.get('last_trade_date')}  bars={len(rows)}  "
                  f"with settlement={settled}  "
                  f"span={dates[0] if dates else '-'}..{dates[-1] if dates else '-'}")
            candidates.append((_recent_volume(rows), ticker))
        if candidates:
            print(f"  most traded over the last 5 sessions: {max(candidates)[1]}")


def main():
    now = datetime.now(timezone.utc)
    today = now.date()
    session = last_expected_session(now)
    saturday = session - timedelta(days=(session.weekday() - 5) % 7 or 7)
    client = MassiveClient(max_calls=30)

    steps = (
        lambda: probe_stocks(client, session.isoformat(), saturday.isoformat()),
        lambda: probe_economy(client, today),
        lambda: probe_futures(client, today, session.isoformat()),
    )
    for step in steps:
        try:
            step()
        except MassiveError as exc:
            print(f"step failed: {type(exc).__name__}: {exc}")

    section("Summary")
    print(f"live calls: {client.calls_made} {client.calls_by_class}; cache hits: {client.cache_hits}")
    print(f"raw answers saved under {client.cache_dir} (gitignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
