"""
Regression guard for the Sept 9 bug.

Commit 32e6bbc renamed the sector group keys in sectors.py from us/kr to
macro/broad_industry/theme and touched no other file. analyst.py kept reading
"us" and "kr", so the fallback silently stopped seeing any ETF data. Nothing
caught it. This does.
"""
import analyst
import dashboard
import sectors


def test_analyst_and_sectors_agree_on_group_keys():
    assert analyst.SECTOR_GROUP_KEYS is sectors.SECTOR_GROUP_KEYS


def test_every_group_key_has_etfs_and_a_title():
    for key in sectors.SECTOR_GROUP_KEYS:
        assert sectors.ETF_GROUPS.get(key), f"no ETF list for group '{key}'"
        assert sectors.GROUP_TITLES.get(key), f"no display title for group '{key}'"


def test_snapshot_contains_every_group_the_analyst_reads(monkeypatch):
    monkeypatch.setattr(sectors, "ALPACA_API_KEY", None)
    monkeypatch.setattr(sectors, "ALPACA_SECRET_KEY", None)

    snapshot = sectors.get_sector_snapshot()
    for key in analyst.SECTOR_GROUP_KEYS:
        assert key in snapshot, f"analyst reads '{key}' but the snapshot has no such key"


def test_auth_failure_still_lists_every_etf(monkeypatch):
    """A blank section hides the outage; a section of errors shows it."""
    monkeypatch.setattr(sectors, "ALPACA_API_KEY", None)
    snapshot = sectors.get_sector_snapshot()

    for key in sectors.SECTOR_GROUP_KEYS:
        assert len(snapshot[key]) == len(sectors.ETF_GROUPS[key])
        for metric in snapshot[key]:
            assert metric.status == "error"
            assert "N/A" in metric.render()


def test_dashboard_renders_every_group(monkeypatch):
    monkeypatch.setattr(sectors, "ALPACA_API_KEY", None)
    snapshot = sectors.get_sector_snapshot()

    rendered = dashboard.format_dashboard({}, snapshot)
    for key in sectors.SECTOR_GROUP_KEYS:
        assert sectors.GROUP_TITLES[key].upper() in rendered
        for symbol in sectors.ETF_GROUPS[key]:
            assert symbol in rendered, f"dashboard drops {symbol}"


def test_all_metrics_flattens_in_group_order(monkeypatch):
    monkeypatch.setattr(sectors, "ALPACA_API_KEY", None)
    snapshot = sectors.get_sector_snapshot()
    flat = sectors.all_metrics(snapshot)
    expected = sum(len(sectors.ETF_GROUPS[k]) for k in sectors.SECTOR_GROUP_KEYS)
    assert len(flat) == expected
    assert flat[0].symbol == next(iter(sectors.ETF_GROUPS["macro"]))


def test_sectors_no_longer_depends_on_alpaca_auth_for_fx():
    """USD/KRW moved to macro.py; a failed Alpaca auth cannot reach it."""
    import macro
    source = open(sectors.__file__).read()
    assert "USDKRW" not in source
    assert "yfinance" not in source
    assert "USDKRW" in open(macro.__file__).read()
