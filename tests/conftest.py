"""
Makes the project importable in a bare environment.

The real SDKs (telegram, alpaca, yfinance, ...) are only stubbed when they
are genuinely missing, so these tests behave identically in CI (no
dependencies installed) and on your laptop (full venv). No test in this
suite touches the network, spends API credit, or sends a message.
"""
import os
import sys
import types

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _stub(name, **attrs):
    try:
        __import__(name)
        return sys.modules[name]
    except ImportError:
        pass

    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module

    if "." in name:
        parent_name, _, child = name.rpartition(".")
        parent = _stub(parent_name)
        setattr(parent, child, module)
    return module


_stub("telegram", Bot=object)
_stub("dotenv", load_dotenv=lambda *a, **k: None)
_stub("anthropic")
_stub("requests", RequestException=Exception, get=None)
_stub("yfinance", Ticker=object)
_stub("alpaca")
_stub("alpaca.data")
_stub("alpaca.data.historical", StockHistoricalDataClient=object)
_stub("alpaca.data.requests", StockBarsRequest=object)
_stub("alpaca.data.timeframe", TimeFrame=object)
class _DataFeed:
    IEX = "iex"
    SIP = "sip"


class _Adjustment:
    RAW = "raw"
    SPLIT = "split"
    ALL = "all"


_stub("alpaca.data.enums", DataFeed=_DataFeed, Adjustment=_Adjustment)

# Never let a stray real credential reach a test run.
for var in (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY", "FRED_API_KEY", "ANTHROPIC_API_KEY",
):
    os.environ.pop(var, None)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """
    Hard guard: this suite must never reach the network.

    Stage 4 moved the ETF fetch to yfinance, which is installed in a full local
    venv but stubbed in CI -- so a test that forgot to patch its fetcher passed
    locally by silently downloading real market data, and the suite went from
    0.2s to 48s without failing. Patch sectors.fetch_yahoo_frame or
    macro.get_yfinance_series in the test instead.
    """
    def blocked(*args, **kwargs):
        raise AssertionError(
            "test tried to reach the network -- patch the fetcher "
            "(sectors.fetch_yahoo_frame / macro.get_yfinance_series) instead"
        )

    import requests
    import yfinance
    monkeypatch.setattr(yfinance, "download", blocked, raising=False)
    monkeypatch.setattr(yfinance, "Ticker", blocked, raising=False)
    monkeypatch.setattr(requests, "get", blocked, raising=False)


class FakeSeries:
    """Minimal pandas-Series stand-in for the fetch fakes below."""
    def __init__(self, values, dates):
        self._values = list(values)
        self.index = list(dates)
        self.iloc = self

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]

    def dropna(self):
        return self


def fake_yahoo_frame(symbols, closes=None, as_of="2026-09-14", bars=25):
    """Builds what fetch_yahoo_frame returns: {symbol: {field: Series}}."""
    dates = [f"2026-08-{d:02d}" for d in range(1, bars)] + [as_of]
    frame = {}
    for i, symbol in enumerate(symbols):
        base = (closes or {}).get(symbol, 100.0 + i)
        series = [base * (1 + 0.001 * n) for n in range(len(dates))]
        frame[symbol] = {
            "Close": FakeSeries(series, dates),
            "Adj Close": FakeSeries(series, dates),
        }
    return frame
