"""
The batched Yahoo ETF path (Stage 4 default).

A live run on 2026-09-15 showed Alpaca refusing SIP and the IEX fallback
returning AIHY unchanged to the cent over both a day and a week. Yahoo returns
consolidated closes for all 22 symbols in one request.
"""
import pytest
from conftest import FakeSeries, fake_yahoo_frame

import dashboard
import sectors


@pytest.fixture(autouse=True)
def _use_yahoo(monkeypatch):
    """Alpaca is the default source again (freshness); these tests are about
    the Yahoo path, which stays available via ETF_SOURCE=yahoo."""
    monkeypatch.setattr(sectors, "ETF_SOURCE", "yahoo")


def _patch_fetch(monkeypatch, frame, record=None):
    def fetch(symbols, period="3mo"):
        if record is not None:
            record.append((list(symbols), period))
        return frame
    monkeypatch.setattr(sectors, "fetch_yahoo_frame", fetch)


def test_all_symbols_covers_every_group():
    assert len(sectors.all_symbols()) == 22
    assert set(sectors.all_symbols()) == {
        s for key in sectors.SECTOR_GROUP_KEYS for s in sectors.ETF_GROUPS[key]}


def test_every_etf_is_fetched_in_one_request(monkeypatch):
    """22 sequential Alpaca calls become a single batched download."""
    calls = []
    _patch_fetch(monkeypatch, fake_yahoo_frame(sectors.all_symbols()), calls)

    sectors.get_sector_snapshot()
    assert len(calls) == 1
    assert sorted(calls[0][0]) == sorted(sectors.all_symbols())


def test_snapshot_shape_and_source(monkeypatch):
    _patch_fetch(monkeypatch, fake_yahoo_frame(sectors.all_symbols()))
    snapshot = sectors.get_sector_snapshot()

    for key in sectors.SECTOR_GROUP_KEYS:
        assert len(snapshot[key]) == len(sectors.ETF_GROUPS[key])
    assert snapshot["price_source"] == "yahoo"
    assert snapshot["price_source_note"] is None


def test_values_and_dates_come_through(monkeypatch):
    _patch_fetch(monkeypatch, fake_yahoo_frame(["SPY"], closes={"SPY": 100.0},
                                               as_of="2026-09-14"))
    metric = sectors.build_yahoo_metric(
        fake_yahoo_frame(["SPY"], closes={"SPY": 100.0}, as_of="2026-09-14"),
        "SPY", "S&P 500")
    assert metric.as_of == "2026-09-14"
    assert metric.value == pytest.approx(102.4, abs=0.1)
    assert metric.day_change is not None
    assert metric.status == "ok"


def test_a_symbol_missing_from_the_batch_is_an_error_not_a_crash(monkeypatch):
    frame = fake_yahoo_frame([s for s in sectors.all_symbols() if s != "AIHY"])
    _patch_fetch(monkeypatch, frame)

    snapshot = sectors.get_sector_snapshot()
    aihy = next(m for m in sectors.all_metrics(snapshot) if m.symbol == "AIHY")
    assert aihy.status == "error"
    assert "N/A" in aihy.render()
    # Every other symbol still made it.
    assert sum(1 for m in sectors.all_metrics(snapshot) if m.is_usable) == 21


def test_a_total_fetch_failure_still_lists_every_etf(monkeypatch):
    def boom(symbols, period="3mo"):
        raise RuntimeError("yahoo is down")
    monkeypatch.setattr(sectors, "fetch_yahoo_frame", boom)

    snapshot = sectors.get_sector_snapshot()
    assert len(sectors.all_metrics(snapshot)) == 22
    assert all(m.status == "error" for m in sectors.all_metrics(snapshot))
    assert "Yahoo ETF fetch failed" in snapshot["price_source_note"]


def test_the_failure_is_disclosed_in_the_report(monkeypatch):
    monkeypatch.setattr(sectors, "fetch_yahoo_frame",
                        lambda symbols, period="3mo": (_ for _ in ()).throw(OSError()))
    out = dashboard.format_dashboard({}, sectors.get_sector_snapshot())
    assert "Yahoo ETF fetch failed" in out


def test_a_single_bar_is_not_enough_for_a_change():
    frame = {"SPY": {"Close": FakeSeries([100.0], ["2026-09-14"])}}
    metric = sectors.build_yahoo_metric(frame, "SPY", "S&P 500")
    assert metric.status == "error"


# --- the adjustment policy ------------------------------------------------

def test_changes_use_adjusted_closes_but_the_price_shown_is_the_real_close():
    """Across an ex-dividend date the raw close drops without the holder
    losing anything. The printed price must still be the real close, or it
    will not match any quote the reader looks up."""
    dates = ["2026-09-10", "2026-09-11", "2026-09-12"]
    frame = {"XLF": {
        # Raw close falls 2% on the distribution.
        "Close": FakeSeries([100.0, 100.0, 98.0], dates),
        # Total return is flat.
        "Adj Close": FakeSeries([98.0, 98.0, 98.0], dates),
    }}
    metric = sectors.build_yahoo_metric(frame, "XLF", "Financials")
    assert metric.value == 98.0          # the real market close
    assert metric.day_change == 0.0      # not -2.00%


def test_adjusted_close_is_optional():
    """Older or partial responses may omit Adj Close; fall back to Close."""
    dates = ["2026-09-11", "2026-09-12"]
    frame = {"SPY": {"Close": FakeSeries([100.0, 101.0], dates)}}
    metric = sectors.build_yahoo_metric(frame, "SPY", "S&P 500")
    assert metric.value == 101.0
    assert metric.day_change == 1.0


def test_a_flat_week_is_reported_as_flat_not_up():
    """The AIHY symptom: identical closes must not render as an up move."""
    dates = [f"2026-09-{d:02d}" for d in range(1, 8)]
    frame = {"AIHY": {"Close": FakeSeries([20.80] * 7, dates)}}
    metric = sectors.build_yahoo_metric(frame, "AIHY", "AI Hyperscale")
    rendered = metric.render()
    assert "▲0.00" not in rendered
    assert "0.00% D/D" in rendered


# --- per-symbol fallback --------------------------------------------------

def test_an_unparseable_batch_falls_back_to_per_symbol(monkeypatch):
    """Insurance: the batched response shape could not be verified against the
    live API from the build environment, so an empty parse retries through the
    per-ticker call macro.py already uses in production."""
    monkeypatch.setattr(sectors, "fetch_yahoo_frame",
                        lambda symbols, period="3mo": {"unexpected": "shape"})

    singles = []

    def single(symbol, period="3mo"):
        singles.append(symbol)
        return fake_yahoo_frame([symbol])[symbol]

    monkeypatch.setattr(sectors, "fetch_yahoo_single", single)

    snapshot = sectors.get_sector_snapshot()
    assert sorted(singles) == sorted(sectors.all_symbols())
    assert all(m.is_usable for m in sectors.all_metrics(snapshot))
    assert "fell back to per-symbol" in snapshot["price_source_note"]


def test_the_fallback_is_disclosed_in_the_report(monkeypatch):
    monkeypatch.setattr(sectors, "fetch_yahoo_frame",
                        lambda symbols, period="3mo": {})
    monkeypatch.setattr(sectors, "fetch_yahoo_single",
                        lambda symbol, period="3mo": fake_yahoo_frame([symbol])[symbol])
    out = dashboard.format_dashboard({}, sectors.get_sector_snapshot())
    assert "fell back to per-symbol" in out


def test_no_fallback_when_the_batch_parses(monkeypatch):
    calls = []
    monkeypatch.setattr(sectors, "fetch_yahoo_frame",
                        lambda symbols, period="3mo": fake_yahoo_frame(symbols))
    monkeypatch.setattr(sectors, "fetch_yahoo_single",
                        lambda symbol, period="3mo": calls.append(symbol))

    snapshot = sectors.get_sector_snapshot()
    assert calls == []
    assert snapshot["price_source_note"] is None


def test_a_raised_fetch_does_not_trigger_the_per_symbol_retry(monkeypatch):
    """A hard outage should not turn into 22 more failing requests."""
    calls = []
    monkeypatch.setattr(sectors, "fetch_yahoo_frame",
                        lambda symbols, period="3mo": (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(sectors, "fetch_yahoo_single",
                        lambda symbol, period="3mo": calls.append(symbol))
    sectors.get_sector_snapshot()
    assert calls == []
