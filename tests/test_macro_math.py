"""Sign conventions, missing-data handling, and snapshot shape in macro.py."""
import macro
from metrics import CHANGE_LEVEL, CHANGE_PCT, UNIT_KRW, UNIT_PERCENT


class _FakeSeries:
    """Minimal stand-in for a pandas Series so these tests need no pandas."""
    def __init__(self, values):
        self._values = list(values)
        self.iloc = self

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


def test_fred_level_change_uses_newest_minus_older():
    # FRED is fetched sort_order=desc, so values[0] is the newest.
    values = [4.10, 4.05, 4.00, 3.95, 3.90, 3.80]
    assert macro._level_change(values, 1) == 0.05
    assert macro._level_change(values, 5) == 0.30


def test_fred_level_change_is_none_without_enough_history():
    assert macro._level_change([4.10], 1) is None
    assert macro._level_change([4.10, 4.05], 5) is None


def test_pct_change_uses_oldest_as_the_base():
    closes = _FakeSeries([100.0, 105.0, 110.0])  # oldest -> newest
    assert macro._pct_change_from_series(closes, 1) == 4.76
    assert macro._pct_change_from_series(closes, 2) == 10.0


def test_pct_change_is_none_without_enough_history():
    assert macro._pct_change_from_series(_FakeSeries([100.0]), 1) is None


def test_pct_change_guards_against_a_zero_base():
    assert macro._pct_change_from_series(_FakeSeries([0.0, 5.0]), 1) is None


def test_non_finite_values_are_treated_as_missing():
    assert macro._coerce_numeric(float("nan")) is None
    assert macro._coerce_numeric(float("inf")) is None
    assert macro._coerce_numeric("nan") is None
    assert macro._coerce_numeric(".") is None
    assert macro._coerce_numeric("4.10") == 4.10


def test_spread_subtraction_propagates_missing_legs():
    assert macro._subtract(4.10, 3.72) == 0.38
    assert macro._subtract(None, 3.72) is None
    assert macro._subtract(4.10, None) is None


def test_snapshot_shape_without_credentials(monkeypatch):
    """No keys and no network: every metric still appears, marked missing."""
    monkeypatch.setattr(macro, "FRED_API_KEY", None)
    monkeypatch.setattr(macro, "get_yfinance_series",
                        lambda ticker: (None, None, None, None, None))

    snapshot = macro.get_macro_snapshot()
    expected = {"VIX", "WTI", "Gold", "Copper", "Gold/Copper", "10Y", "2Y",
                "2s10s", "HY OAS", "IG OAS", "DXY", "USDKRW"}
    assert expected <= set(snapshot)
    for metric in snapshot.values():
        assert metric.render() == "N/A"


def test_units_and_change_kinds_are_right(monkeypatch):
    monkeypatch.setattr(macro, "FRED_API_KEY", None)
    monkeypatch.setattr(macro, "get_yfinance_series",
                        lambda ticker: (1.0, 0.1, 0.2, 0.3, "2026-09-12"))
    snapshot = macro.get_macro_snapshot()

    # Yields and spreads move in percentage points, prices in percent.
    assert snapshot["10Y"].change_kind == CHANGE_LEVEL
    assert snapshot["2s10s"].change_kind == CHANGE_LEVEL
    assert snapshot["VIX"].change_kind == CHANGE_PCT
    assert snapshot["USDKRW"].unit == UNIT_KRW
    assert snapshot["10Y"].unit == UNIT_PERCENT


def test_spread_change_is_the_difference_of_its_legs(monkeypatch):
    def fake_fred(series_id, limit=40):
        return {"DGS10": (4.10, 0.05, 0.20, None, "2026-09-12"),
                "DGS2": (3.72, 0.02, 0.30, None, "2026-09-12")}.get(
                    series_id, (None, None, None, None, None))

    monkeypatch.setattr(macro, "get_fred_series", fake_fred)
    monkeypatch.setattr(macro, "get_yfinance_series",
                        lambda ticker: (None, None, None, None, None))

    spread = macro.get_macro_snapshot()["2s10s"]
    assert spread.value == 0.38
    assert spread.day_change == 0.03      # 0.05 - 0.02
    assert spread.week_change == -0.10    # 0.20 - 0.30
    assert spread.month_change is None    # one leg missing


def test_gold_survives_a_failed_copper_fetch(monkeypatch):
    monkeypatch.setattr(macro, "FRED_API_KEY", None)

    def fake_yahoo(ticker):
        if ticker == "GC=F":
            return 2510.4, 0.5, 1.0, 2.0, "2026-09-12"
        return None, None, None, None, None

    monkeypatch.setattr(macro, "get_yfinance_series", fake_yahoo)
    snapshot = macro.get_macro_snapshot()

    assert snapshot["Gold"].value == 2510.4
    assert snapshot["Copper"].value is None
    assert snapshot["Gold/Copper"].value is None   # ratio needs both


def test_fred_errors_do_not_leak_the_api_key(monkeypatch, capsys):
    """requests puts the request URL in its exception text, and the URL
    carries api_key=... -- only the status and series id may be logged."""
    def exploding_get(url, params=None, timeout=None):
        raise macro.requests.RequestException(
            f"500 Server Error for url: {url}?api_key=SECRET123")

    monkeypatch.setattr(macro, "FRED_API_KEY", "SECRET123")
    monkeypatch.setattr(macro.requests, "get", exploding_get, raising=False)

    macro.get_fred_series("DGS10")
    assert "SECRET123" not in capsys.readouterr().out
