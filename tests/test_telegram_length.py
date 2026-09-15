"""
Telegram rejects any message over 4096 characters after entity parsing.
These tests assert on the FINAL outgoing strings, part markers included --
the old splitter was correct about chunk sizes but added "(1/2)\n\n" to each
chunk afterwards, pushing the real payload over the limit.
"""
import pytest

import telegram_bot as tb

LIMIT = tb.TELEGRAM_MAX_LENGTH


def _all_parts_ok(text):
    parts = tb.build_message_parts(text)
    assert parts, "splitter returned nothing"
    for part in parts:
        assert part != "", "splitter produced an empty part (Telegram rejects these)"
        assert len(part) <= LIMIT, f"part is {len(part)} chars, limit is {LIMIT}"
    return parts


@pytest.mark.parametrize("size", [1, 100, LIMIT - 1, LIMIT])
def test_messages_at_or_under_the_limit_are_sent_whole(size):
    text = "y" * size
    assert tb.build_message_parts(text) == [text]


@pytest.mark.parametrize("size", [LIMIT + 1, LIMIT + 2, LIMIT * 2, 5000, 20000])
def test_oversized_messages_split_within_the_limit(size):
    parts = _all_parts_ok("z" * size)
    assert len(parts) > 1


def test_limit_plus_one_actually_splits():
    """The old code returned this as one unsplit 4097-character message."""
    parts = tb.build_message_parts("z" * (LIMIT + 1))
    assert len(parts) == 2


def test_unbroken_text_with_no_spaces():
    _all_parts_ok("x" * 5000)


def test_space_separated_text():
    _all_parts_ok(("word " * 1000)[:5000])


def test_paragraph_separated_text():
    _all_parts_ok("\n\n".join("paragraph %d body text" % i for i in range(500)))


def test_text_starting_with_a_paragraph_break_makes_no_empty_part():
    _all_parts_ok("\n\n" + "q" * 5000)


def test_no_content_is_lost_when_splitting():
    text = " ".join(f"sentence number {i}." for i in range(1200))
    parts = tb.build_message_parts(text)
    rebuilt = "".join(p.split("\n\n", 1)[1] if p.startswith("(") else p for p in parts)
    assert "".join(rebuilt.split()) == "".join(text.split())


def test_realistic_long_analysis_message():
    body = ("The macro read is unchanged. " * 400).strip()
    _all_parts_ok(f"\U0001f9e0 Analyst Comment\n\n{body}")
