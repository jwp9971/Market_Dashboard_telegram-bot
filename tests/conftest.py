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
_stub("alpaca.data.enums", DataFeed=object)

# Never let a stray real credential reach a test run.
for var in (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY", "FRED_API_KEY", "ANTHROPIC_API_KEY",
):
    os.environ.pop(var, None)
