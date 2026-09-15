"""
Regression guard for the Sept 9 bug.

Commit 32e6bbc renamed the sector group keys in sectors.py from us/kr to
macro/broad_industry/theme and touched no other file. analyst.py kept reading
"us" and "kr", so the fallback silently stopped seeing any ETF data at all.
Nothing caught it. This does.
"""
import analyst
import sectors


def test_analyst_and_sectors_agree_on_group_keys():
    assert analyst.SECTOR_GROUP_KEYS is sectors.SECTOR_GROUP_KEYS


def test_snapshot_contains_every_group_the_analyst_reads(monkeypatch):
    monkeypatch.setattr(sectors, "ALPACA_API_KEY", None)
    monkeypatch.setattr(sectors, "ALPACA_SECRET_KEY", None)
    monkeypatch.setattr(sectors, "get_exchange_rate", lambda: (None, None))

    snapshot = sectors.get_sector_snapshot()
    for key in analyst.SECTOR_GROUP_KEYS:
        assert key in snapshot, f"analyst reads '{key}' but the snapshot has no such key"
    assert "fx" in snapshot and "market_time" in snapshot


def test_dashboard_reads_every_group(monkeypatch):
    import dashboard
    sector_snapshot = {k: [f"{k} line"] for k in sectors.SECTOR_GROUP_KEYS}
    sector_snapshot.update({"fx": "N/A", "market_time": None})
    rendered = dashboard.format_dashboard({}, sector_snapshot)
    for key in sectors.SECTOR_GROUP_KEYS:
        assert f"{key} line" in rendered, f"dashboard drops the '{key}' group"


def test_fx_survives_missing_alpaca_credentials(monkeypatch):
    """USD/KRW comes from Yahoo and must not be lost to an Alpaca auth failure."""
    monkeypatch.setattr(sectors, "ALPACA_API_KEY", None)
    monkeypatch.setattr(sectors, "get_exchange_rate", lambda: (1380.5, "▲"))
    snapshot = sectors.get_sector_snapshot()
    assert "1380.5" in snapshot["fx"]
