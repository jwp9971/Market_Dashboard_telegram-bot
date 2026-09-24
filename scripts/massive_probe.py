"""
The only script that calls Massive live. Run it by hand, never in Actions.

    python scripts/massive_probe.py

It checks what the docs leave open -- ETF coverage in grouped daily, what a
weekend date returns, treasury-yield fields and lag, futures contract codes
and bar dating, whether DXY exists -- and saves every raw answer under the
gitignored cache/massive/ for inspection. It prints structure (counts, field
names, dates, ticker symbols), never prices or yields: Massive's terms forbid
publishing its data and this repo is public.

About 10 calls; the sixth futures call waits for the rate limit, so it takes
a little over a minute.
"""
import os
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


def _front_month(contracts):
    """Nearest-expiry contract by days_to_maturity, if the field exists."""
    dated = [c for c in contracts if isinstance(c.get("days_to_maturity"), (int, float))
             and c["days_to_maturity"] >= 0]
    return min(dated, key=lambda c: c["days_to_maturity"]) if dated else None


def probe_futures(client, today):
    since = (today - timedelta(days=10)).isoformat()
    for code, name in FUTURES_PRODUCTS.items():
        section(f"Futures: {name} ({code})")
        try:
            body = client.get("/futures/v1/contracts",
                              {"product_code": code, "date": today.isoformat(), "limit": 50},
                              "futures", cache=True)
        except MassiveError as exc:
            print(f"contracts lookup raised {type(exc).__name__}: {exc}")
            continue
        contracts = body.get("results") or []
        print(f"contracts listed: {len(contracts)}")
        if not contracts:
            print(f"top-level keys: {fields(body)}")
            continue
        print(f"contract fields: {fields(contracts[0])}")
        front = _front_month(contracts)
        if front is None:
            print("no days_to_maturity field -- cannot pick a front month automatically")
            continue
        ticker = front.get("ticker")
        print(f"front month: {ticker} ({front.get('days_to_maturity')} days to maturity; "
              f"listed at position {contracts.index(front) + 1})")
        if not ticker:
            continue
        try:
            bars = client.get(f"/futures/v1/aggs/{ticker}",
                              {"resolution": "1session", "window_start.gte": since, "limit": 20},
                              "futures", cache=True)
        except MassiveError as exc:
            print(f"bars raised {type(exc).__name__}: {exc}")
            continue
        rows = bars.get("results") or []
        print(f"session bars: {len(rows)}")
        if rows:
            print(f"bar fields: {fields(rows[0])}")
            for row in rows[-3:]:
                start = row.get("window_start")
                start_text = (datetime.fromtimestamp(start / 1e9, timezone.utc).date().isoformat()
                              if isinstance(start, (int, float)) else start)
                print(f"  window_start={start_text}  session_end_date={row.get('session_end_date')}")


def probe_dxy(client):
    section("Reference: does DXY exist?")
    body = client.get("/v3/reference/tickers", {"search": "DXY", "limit": 20},
                      "reference", cache=False)
    results = body.get("results") or []
    print(f"matches: {len(results)}")
    for row in results:
        print(f"  {row.get('ticker')}  market={row.get('market')}  name={row.get('name')}")


def main():
    now = datetime.now(timezone.utc)
    today = now.date()
    session = last_expected_session(now)
    saturday = session - timedelta(days=(session.weekday() - 5) % 7 or 7)
    client = MassiveClient(max_calls=15)

    steps = (
        lambda: probe_stocks(client, session.isoformat(), saturday.isoformat()),
        lambda: probe_economy(client, today),
        lambda: probe_futures(client, today),
        lambda: probe_dxy(client),
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
