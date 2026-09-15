"""
Keeps the README honest.

The original README claimed 21 ETFs (there are 22) and optional OpenAI support
(no such code exists). Documentation drifts silently; these assertions make it
fail loudly instead.
"""
import pathlib
import re

import dashboard
import sectors

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
SRC = list((ROOT / "src").glob("*.py"))


def test_etf_count_matches_the_code():
    total = sum(len(g) for g in sectors.ETF_GROUPS.values())
    assert total == 22
    assert f"**{total}** ETFs" in README


def test_every_group_count_matches():
    for key, title in (("macro", "Macro"), ("broad_industry", "Broad Industry"),
                       ("theme", "Theme")):
        assert f"**{title} ({len(sectors.ETF_GROUPS[key])})**" in README


def test_every_ticker_is_listed():
    for key in sectors.SECTOR_GROUP_KEYS:
        for symbol in sectors.ETF_GROUPS[key]:
            assert symbol in README, f"{symbol} is tracked but undocumented"


def test_no_openai_claim_without_openai_code():
    code = "\n".join(p.read_text(encoding="utf-8") for p in SRC).lower()
    if "openai" not in code:
        assert "openai" not in README.lower(), "README claims OpenAI support that does not exist"


def test_removed_overclaims_stay_removed():
    for phrase in ("production-grade", "never silently truncated",
                   "strictly grounded", "fully free"):
        assert phrase.lower() not in README.lower(), f"unsupported claim: {phrase}"


def test_every_required_env_var_is_documented():
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY",
                "FRED_API_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                "ANTHROPIC_MODEL", "ALPACA_FEED", "DRY_RUN"):
        assert var in README, f"{var} is read by the code but undocumented"


def test_the_schedule_matches_the_workflow():
    workflow = (ROOT / ".github/workflows/daily-dashboard.yml").read_text()
    cron = re.search(r"cron:\s*'([^']+)'", workflow).group(1)
    assert cron == "0 23 * * 0-4"
    assert cron in README


def test_exit_codes_are_documented():
    import main
    for code in (main.EXIT_OK, main.EXIT_FAILED, main.EXIT_DEGRADED):
        assert f"`{code}`" in README


def test_required_macro_keys_are_documented():
    for key in dashboard.REQUIRED_MACRO_KEYS:
        assert key in README


def test_limitations_section_exists():
    assert "## Known limitations" in README


def test_etf_source_options_are_documented():
    import sectors
    assert "ETF_SOURCE" in README
    assert sectors.ETF_SOURCE in README


def test_the_total_return_policy_is_stated():
    """The printed price and the percentage come from different series; that
    has to be written down or it looks like a bug."""
    assert "total return" in README.lower()


def test_freshness_windows_match_the_code():
    from metrics import MAX_AGE_FRED_OAS, MAX_AGE_FRED_RATES, MAX_AGE_MARKET_DAYS
    assert MAX_AGE_FRED_RATES == MAX_AGE_FRED_OAS
    assert f"{MAX_AGE_MARKET_DAYS} for equities" in README
    assert f"{MAX_AGE_FRED_RATES} for both FRED families" in README
