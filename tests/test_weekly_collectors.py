"""
Weekly collectors (massive.py, cboe.py) and the assembled weekly snapshot.

A fake Massive client answers by path with synthetic data (made-up numbers,
the shape the live probe saw on 2026-09-24), so nothing reaches the network
and no Massive data lives in this public repo.
"""
from datetime import date, datetime, timezone

import pytest

import cboe
import macro
import massive
import weekly_snapshot
from massive_client import MassiveBudgetExceeded
from sectors import ETF_GROUPS

FRIDAY = date(2026, 9, 18)
NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)   # Saturday after the week


class FakeMassive:
    """Stands in for MassiveClient: routes each path to a handler and counts."""

    def __init__(self, **handlers):
        self.handlers = handlers
        self.calls = []
        self.calls_made = 0
        self.calls_by_class = {}
        self.cache_hits = 0

    def get(self, path, params=None, asset_class="stocks", cache=False):
        params = dict(params or {})
        self.calls.append((path, params, asset_class, cache))
        self.calls_made += 1
        self.calls_by_class[asset_class] = self.calls_by_class.get(asset_class, 0) + 1
        for prefix, handler in self.handlers.items():
            if path.startswith("/" + prefix.replace("__", "/")):
                return handler(path, params)
        raise AssertionError(f"unexpected Massive path {path}")


# --- synthetic market ------------------------------------------------------------

# SPY's closes on the dates the weekly changes need. 2026-06-19 (Juneteenth)
# was a Friday holiday, so 13 weeks back resolves to Thursday 06-18.
SPY = {"2026-09-18": 110.0, "2026-09-11": 100.0, "2026-08-21": 95.0, "2026-06-18": 80.0}


def grouped(path, params):
    day = path.rsplit("/", 1)[1]
    if day not in SPY:
        return {"status": "OK", "resultsCount": 0}          # holiday: no results key
    rows = [{"T": "SPY", "c": SPY[day]}, {"T": "NOTOURS", "c": 1.0}]
    rows += [{"T": t, "c": 50.0} for g in ETF_GROUPS.values() for t in g if t not in ("SPY", "AIHY")]
    return {"status": "OK", "resultsCount": len(rows), "results": rows}


def yields(path, params):
    rows = [{"date": "2026-09-17", "yield_2_year": 3.60, "yield_10_year": 4.20},
            {"date": "2026-09-11", "yield_2_year": 3.50, "yield_10_year": 4.00},
            {"date": "2026-06-18", "yield_2_year": 3.90, "yield_10_year": 4.40}]
    return {"status": "OK", "results": rows}


def contracts_for(code):
    return [
        {"ticker": f"{code}U6", "last_trade_date": "2026-09-28"},   # expiring: skipped
        {"ticker": f"{code}V6", "last_trade_date": "2026-10-28"},
        {"ticker": f"{code}V6", "last_trade_date": "2026-10-28"},   # listed twice
        {"ticker": f"{code}:BF F7-G7-H7", "last_trade_date": "2026-11-01"},  # spread
        {"ticker": f"{code}X6", "last_trade_date": "2026-11-25"},
        {"ticker": f"{code}Z6", "last_trade_date": "2026-12-29"},
        {"ticker": f"{code}F7", "last_trade_date": "2027-01-27"},   # 4th: not a candidate
    ]


PRICES = {"CL": 70.0, "GC": 2000.0, "HG": 4.0}
BUSIEST = {"CL": "V6", "GC": "Z6", "HG": "Z6"}


def contracts(path, params):
    code = params["ticker.any_of"][:2]
    return {"status": "OK", "results": contracts_for(code)}


def bars(path, params):
    ticker = path.rsplit("/", 1)[1]
    code, month = ticker[:2], ticker[2:]
    volume = 1000 if month == BUSIEST[code] else 10
    base = PRICES[code]
    rows = [  # newest first, as Massive returns them
        {"session_end_date": "2026-09-21", "settlement_price": None, "volume": 99999},  # still trading
        {"session_end_date": "2026-09-18", "settlement_price": base * 1.1, "volume": volume},
        {"session_end_date": "2026-09-11", "settlement_price": base, "volume": volume},
    ]
    return {"status": "OK", "results": rows}


def full_fake(**overrides):
    handlers = dict(v2__aggs__grouped=grouped, fed__v1__treasury=yields,
                    futures__v1__contracts=contracts, futures__v1__aggs=bars)
    handlers.update(overrides)
    return FakeMassive(**handlers)


# --- ETFs ------------------------------------------------------------------------

def test_etfs_use_one_grouped_call_per_needed_week_plus_holiday_step_back():
    client = full_fake()
    snapshot = massive.get_etf_snapshot(client, FRIDAY, NOW)
    days = [call[0].rsplit("/", 1)[1] for call in client.calls]
    assert days == ["2026-09-18", "2026-09-11", "2026-08-21", "2026-06-19", "2026-06-18"]

    spy = next(m for m in snapshot["macro"] if m.symbol == "SPY")
    assert (spy.value, spy.week_change, spy.month_change, spy.quarter_change) == (110.0, 10.0, 15.79, 37.5)
    assert spy.as_of == "2026-09-18" and spy.source == "massive"


def test_only_settled_days_are_cached():
    client = full_fake()
    massive.get_etf_snapshot(client, FRIDAY, NOW)
    cached = {call[0].rsplit("/", 1)[1]: call[3] for call in client.calls}
    assert cached["2026-09-18"] is False        # the latest session: could still be filling in
    assert cached["2026-09-11"] is True


def test_an_etf_absent_from_grouped_daily_is_missing_not_dropped():
    snapshot = massive.get_etf_snapshot(full_fake(), FRIDAY, NOW)
    aihy = next(m for m in snapshot["theme"] if m.symbol == "AIHY")
    assert aihy.value is None and "no data" in aihy.error
    assert sum(len(v) for v in snapshot.values()) == 22


# --- yields ----------------------------------------------------------------------

def test_yields_and_the_curve_from_one_call():
    client = full_fake()
    rows = massive.get_yield_metrics(client, FRIDAY)
    assert len(client.calls) == 1 and client.calls[0][2] == "economy"
    assert rows["10Y"].value == 4.20 and rows["10Y"].as_of == "2026-09-17"
    assert rows["10Y"].week_change == 0.2 and rows["10Y"].quarter_change == -0.2
    assert rows["2s10s"].value == pytest.approx(0.6)
    assert rows["2s10s"].week_change == 0.1


# --- futures ---------------------------------------------------------------------

def test_candidate_tickers_roll_over_the_year():
    assert massive.candidate_tickers("GC", date(2026, 11, 5), months=4) == ["GCX6", "GCZ6", "GCF7", "GCG7"]


@pytest.mark.parametrize("ticker,expected", [
    ("GCZ6", True), ("CLF27", True), ("CL:BF F7-G7-H7", False),
    ("HG:SA 03M F7", False), ("GCZ", False), ("HGZ6", False),
])
def test_only_outright_contracts_count(ticker, expected):
    assert massive.is_outright(ticker, "GC" if ticker.startswith("G") else "CL") is expected


def test_candidates_skip_expiring_spreads_and_duplicates():
    picked = massive.pick_candidates(contracts_for("GC"), "GC", FRIDAY)
    assert [c["ticker"] for c in picked] == ["GCV6", "GCX6", "GCZ6"]


def test_the_most_traded_contract_wins_and_unsettled_bars_are_ignored():
    ticker, series = massive.get_futures_series(full_fake(), "GC", FRIDAY)
    assert ticker == "GCZ6"
    assert [day for day, _ in series] == ["2026-09-18", "2026-09-11"]


def test_futures_metrics_and_ratio():
    rows = massive.get_futures_metrics(full_fake(), FRIDAY)
    assert rows["WTI"].symbol == "CLV6" and rows["Gold"].symbol == "GCZ6"
    assert rows["Gold"].week_change == 10.0
    assert rows["Gold/Copper"].value == 500.0
    assert rows["Gold/Copper"].render() == "500.0"


def test_an_empty_contract_snapshot_retries_the_day_before():
    seen = []

    def sometimes_empty(path, params):
        seen.append(params["date"])
        return contracts(path, params) if params["date"] != "2026-09-18" else {"results": []}

    ticker, _ = massive.get_futures_series(full_fake(futures__v1__contracts=sometimes_empty), "GC", FRIDAY)
    assert seen == ["2026-09-18", "2026-09-17"] and ticker == "GCZ6"


# --- Cboe ------------------------------------------------------------------------

def test_cboe_csv_parses_and_skips_bad_rows():
    text = "DATE,OPEN,HIGH,LOW,CLOSE\n09/17/2026,1,2,0.5,1.5\nbad,1,1,1,1\n09/18/2026,1,2,1,1.75\n"
    assert cboe.parse_vix_history(text) == [("2026-09-17", 1.5), ("2026-09-18", 1.75)]


def test_cboe_http_failure_is_an_empty_series(capsys):
    class Response:
        status_code = 503
        text = ""
    assert cboe.get_vix_series(http_get=lambda url, timeout: Response()) == []
    assert "HTTP 503" in capsys.readouterr().out


# --- the assembled snapshot ------------------------------------------------------

@pytest.fixture
def offline_sources(monkeypatch):
    """Cboe current through Friday; FRED and Yahoo answer with small series."""
    calls = {"yahoo": []}
    monkeypatch.setattr(cboe, "get_vix_series",
                        lambda: [("2026-09-11", 15.0), ("2026-09-18", 18.0)])
    monkeypatch.setattr(macro, "get_fred_observations",
                        lambda series_id, limit: [("2026-09-17", 3.0), ("2026-09-10", 2.9)])

    def yahoo(ticker, period):
        calls["yahoo"].append(ticker)
        return [("2026-09-11", 100.0), ("2026-09-18", 101.0)]
    monkeypatch.setattr(macro, "get_yfinance_closes", yahoo)
    return calls


def test_the_snapshot_has_every_row_and_stays_within_budget(offline_sources):
    client = full_fake()
    snap = weekly_snapshot.get_weekly_snapshot(now=NOW, client=client)
    assert snap["week"] == (date(2026, 9, 14), FRIDAY)
    assert snap["label"] == "Week of Sep 14–18"
    assert list(snap["macro"]) == list(weekly_snapshot.MACRO_ORDER)
    assert all(m.value is not None for m in snap["macro"].values())
    assert "USDKRW" not in snap["macro"]
    assert client.calls_made <= weekly_snapshot.WEEKLY_CALL_BUDGET
    assert offline_sources["yahoo"] == ["DX-Y.NYB"]          # no VIX fallback needed


def test_notes_name_contracts_price_only_and_early_values(offline_sources):
    notes = weekly_snapshot.get_weekly_snapshot(now=NOW, client=full_fake())["notes"]
    joined = "\n".join(notes)
    assert "CLV6, GCZ6, HGZ6" in joined
    assert "price-only" in joined
    assert "HY OAS" in joined and "10Y" in joined          # dated Thursday
    assert "Missing this week: AIHY" in joined


def test_vix_falls_back_to_yahoo_when_cboe_is_behind(offline_sources, monkeypatch):
    monkeypatch.setattr(cboe, "get_vix_series", lambda: [("2026-09-17", 17.0)])
    snap = weekly_snapshot.get_weekly_snapshot(now=NOW, client=full_fake())
    assert snap["macro"]["VIX"].source == "yahoo"
    assert snap["macro"]["VIX"].as_of == "2026-09-18"
    assert any("Cboe file ends 2026-09-17" in n for n in snap["notes"])


def test_vix_stays_on_cboe_when_yahoo_is_no_newer(offline_sources, monkeypatch):
    monkeypatch.setattr(cboe, "get_vix_series", lambda: [("2026-09-17", 17.0)])
    monkeypatch.setattr(macro, "get_yfinance_closes", lambda t, p: [("2026-09-17", 1.0)])
    snap = weekly_snapshot.get_weekly_snapshot(now=NOW, client=full_fake())
    assert snap["macro"]["VIX"].source == "cboe"


def test_one_failing_source_leaves_the_rest_standing(offline_sources):
    def broken(path, params):
        raise MassiveBudgetExceeded("budget")
    snap = weekly_snapshot.get_weekly_snapshot(
        now=NOW, client=full_fake(futures__v1__contracts=broken))
    for key in ("WTI", "Gold", "Copper", "Gold/Copper"):
        assert snap["macro"][key].error == "massive failed: MassiveBudgetExceeded"
    assert snap["macro"]["10Y"].value is not None
    assert snap["macro"]["VIX"].value is not None


def test_the_snapshot_log_shows_counts_not_values(offline_sources, capsys):
    weekly_snapshot.get_weekly_snapshot(now=NOW, client=full_fake())
    out = capsys.readouterr().out
    assert "live Massive calls" in out
    assert "110" not in out and "2200" not in out
