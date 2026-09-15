"""
ETF feed selection.

IEX is one exchange at a low single-digit share of consolidated volume, so a
thinly traded ETF's daily close can be built from a handful of prints. SIP is
the consolidated tape. Prefer it, and when the account is not entitled, fall
back -- but never silently.
"""
import dashboard
import sectors


class _FakeClient:
    """Records which feed each request asked for; refuses SIP when told to."""
    def __init__(self, allow_sip=True):
        self.allow_sip = allow_sip
        self.feeds_requested = []

    def get_stock_bars(self, request):
        self.feeds_requested.append(request["feed"])
        if request["feed"] == sectors.DataFeed.SIP and not self.allow_sip:
            raise PermissionError("subscription does not permit querying recent SIP data")
        raise RuntimeError("bars not needed for these tests")


def _patch_request(monkeypatch):
    """StockBarsRequest is stubbed as `object` in conftest; capture kwargs."""
    monkeypatch.setattr(sectors, "StockBarsRequest", lambda **kw: kw)


def test_split_adjustment_is_requested(monkeypatch):
    """Raw prices show a split as a real move."""
    assert sectors.ADJUSTMENT == sectors.Adjustment.SPLIT


def test_sip_is_preferred_when_alpaca_is_used():
    assert sectors.PREFERRED_FEED == "sip"


def test_alpaca_is_no_longer_the_default_source():
    """A live run showed Alpaca refusing SIP and IEX returning a week of
    unchanged closes for AIHY, so Yahoo is the default."""
    assert sectors.ETF_SOURCE == "yahoo"


def test_sip_is_used_when_entitled(monkeypatch):
    _patch_request(monkeypatch)
    monkeypatch.setattr(sectors, "PREFERRED_FEED", "sip")
    client = _FakeClient(allow_sip=True)
    # The probe raises RuntimeError only after the feed check, so SIP "works".
    monkeypatch.setattr(sectors, "_fetch_bars", lambda c, s, feed: None)

    feed, note = sectors.resolve_feed(client)
    assert feed == "sip"
    assert note is None


def test_entitlement_failure_falls_back_to_iex_with_a_note(monkeypatch):
    monkeypatch.setattr(sectors, "PREFERRED_FEED", "sip")

    def refuse(client, symbol, feed):
        raise PermissionError("subscription does not permit querying recent SIP data")

    monkeypatch.setattr(sectors, "_fetch_bars", refuse)

    feed, note = sectors.resolve_feed(_FakeClient(allow_sip=False))
    assert feed == "iex"
    assert note and "IEX" in note
    assert "unavailable" in note


def test_feed_can_be_pinned_to_iex(monkeypatch):
    monkeypatch.setattr(sectors, "PREFERRED_FEED", "iex")
    feed, note = sectors.resolve_feed(_FakeClient())
    assert feed == "iex"
    assert note is None


def test_an_unknown_feed_setting_is_reported_not_obeyed(monkeypatch):
    monkeypatch.setattr(sectors, "PREFERRED_FEED", "nonsense")
    feed, note = sectors.resolve_feed(_FakeClient())
    assert feed == "iex"
    assert "unknown" in note


def test_the_probe_costs_one_request_not_twenty_two(monkeypatch):
    calls = []
    monkeypatch.setattr(sectors, "PREFERRED_FEED", "sip")
    monkeypatch.setattr(sectors, "_fetch_bars",
                        lambda c, s, feed: calls.append(s))
    sectors.resolve_feed(_FakeClient())
    assert len(calls) == 1


# --- how the choice reaches the reader -------------------------------------

def _snapshot(price_source, note=None):
    snap = {key: [] for key in sectors.SECTOR_GROUP_KEYS}
    snap["price_source"] = price_source
    snap["price_source_note"] = note
    return snap


def test_fallback_is_disclosed_in_the_report():
    out = dashboard.format_dashboard({}, _snapshot(
        "alpaca:iex", "SIP feed unavailable (PermissionError); using IEX"))
    assert "SIP feed unavailable" in out


def test_plain_iex_carries_its_own_warning():
    out = dashboard.format_dashboard({}, _snapshot("alpaca:iex"))
    assert "IEX-only" in out


def test_sip_needs_no_warning():
    out = dashboard.format_dashboard({}, _snapshot("alpaca:sip"))
    assert "IEX-only" not in out


def test_yahoo_needs_no_warning():
    """Yahoo returns consolidated closes, so the IEX caveat does not apply."""
    out = dashboard.format_dashboard({}, _snapshot("yahoo"))
    assert "IEX-only" not in out


def test_source_keys_are_not_mistaken_for_etf_groups():
    """all_metrics must not try to iterate the source strings."""
    assert sectors.all_metrics(_snapshot("yahoo")) == []
