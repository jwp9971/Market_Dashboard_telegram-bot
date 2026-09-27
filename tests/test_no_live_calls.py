"""
The suite's own guard (conftest.py): no test may spend a Claude call, post to
the chat or use a real key -- on a laptop too, where .env reloads the keys.
"""
import os
import sys

import pytest

import analyst
import macro
import telegram_bot
from conftest import CREDENTIALS


def test_no_real_key_is_visible_to_a_test():
    assert not any(os.environ.get(var) for var in CREDENTIALS)
    assert analyst.ANTHROPIC_API_KEY is None and macro.FRED_API_KEY is None
    assert telegram_bot.BOT_TOKEN is None and telegram_bot.CHAT_ID is None


def test_the_claude_and_telegram_clients_refuse_to_start():
    with pytest.raises(AssertionError, match="reach the network"):
        sys.modules["anthropic"].Anthropic(api_key="real-looking-key")
    with pytest.raises(AssertionError, match="reach the network"):
        telegram_bot.Bot(token="real-looking-token")


def test_a_forgotten_stub_falls_back_instead_of_calling_claude(monkeypatch):
    """With a key set but no fake client, the call fails safely, never live."""
    monkeypatch.setattr(analyst, "ANTHROPIC_API_KEY", "set-by-this-test")
    assert analyst.call_claude("prompt")["error"] == "AssertionError"
