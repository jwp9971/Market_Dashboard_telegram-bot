"""Sign conventions and missing-data handling in the number crunching."""
import macro


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


def test_missing_change_renders_as_na_not_nan():
    line = macro.format_pct_change_line(None, None, None)
    assert line == "D/D N/A"
    assert "nan" not in line.lower()


def test_arrows_match_the_sign():
    assert macro.format_pct_change_line(1.5).startswith("▲")
    assert macro.format_pct_change_line(-1.5).startswith("▼")


def test_metric_value_with_no_reading_is_na():
    assert macro.format_metric_value(None, "▲1.00% D/D") == "N/A"
