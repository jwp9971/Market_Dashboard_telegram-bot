# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working with this user — read first

- The user is **new to coding** and is learning project management through AI-assisted development. Explain in plain terms. Give Windows PowerShell commands they can copy and paste.
- **Do not execute decisions automatically.** For every step: give a short overview of what will change and why, lay out the options with a recommendation, and **wait for the user to decide**. Routine mechanics inside an approved step are fine; choices about scope, design or data sources are not.
- Keep everything except the core answer short and direct. On the core answer, be thorough and double-check the logic.
- When you find a problem, say so plainly with the evidence (log line, failing test, number). If an earlier explanation turns out wrong, correct it explicitly.

## Two sessions, two roles

- **Local VS Code session** — builds the `weekly-commentary` branch, runs code and live API calls on the user's laptop.
- **Web session (claude.ai/code)** — GitHub integration only: reviewing and refining PRs, merging when the user says so.
- Never have both editing the same branch at once. `git pull` before starting work.

## Commands

Local environment is Windows + VS Code + PowerShell. CI runs Ubuntu / Python 3.12.

```powershell
.\venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements.txt       # 59-line pinned lock (what CI and the scheduled run install)
pip install -r requirements-dev.txt   # pytest only

python -m pytest -q                                   # full suite — no network, no keys, ~0.3s
python -m pytest tests/test_session_lag.py -q         # one file
python -m pytest tests/test_session_lag.py::test_current_data_is_zero_behind -q   # one test
python -m pytest -q -k staleness                      # by name match
python -m compileall -q src                           # syntax check, as CI does

$env:DRY_RUN=1; python src/main.py    # full live pipeline, prints Telegram messages instead of sending (costs one Claude call)
python src/macro.py                   # print just the macro snapshot
python src/sectors.py                 # print just the ETF snapshot
```

`requirements-direct.txt` records the packages actually imported; `requirements.txt` is the full lock.

## Architecture (current daily bot, on `main`)

Scheduled by `.github/workflows/daily-dashboard.yml` at `0 23 * * 0-4` UTC = **08:00 KST Mon–Fri**. GitHub only runs scheduled workflows from the default branch, so a workflow on another branch cannot fire on a schedule. `tests.yml` runs `compileall` + `pytest` on every push and pull request.

Data flow:

```
main.py → analyst.analyze_market()
            ├─ macro.get_macro_snapshot()    → {key: Metric}         (FRED + Yahoo)
            └─ sectors.get_sector_snapshot() → {group: [Metric], price_source, price_source_note}
          → dashboard.format_dashboard()  +  Claude note (analyst)
          → telegram_bot.send_analysis_report()
          → main.decide_exit_code()  → 0 OK / 1 FAILED / 2 DEGRADED
```

Key invariants — these span several files:

- **`metrics.Metric` is the only data currency.** Collectors return `Metric` records (value, day/week/month change, unit, `change_kind`, `as_of`, source, error). Nothing downstream parses display text; only `Metric.render()` produces strings. `status` is derived (`error`/`missing`/`stale`/`partial`/`ok`), never set by hand. A new data source means a new collector returning `Metric`s — not changes to dashboard or analyst logic.
- **`sectors.SECTOR_GROUP_KEYS` is the snapshot contract.** `analyst.py` and `dashboard.py` import it rather than hardcoding group names; `tests/test_sector_contract.py` enforces this. (A rename that broke the fallback silently for days is why.)
- **Freshness is evaluated once.** `metrics.mark_staleness()` sets `stale` against per-source calendar-day tolerances (`MAX_AGE_*`). Separately, `metrics.sessions_behind()` / `dashboard.etf_session_lag()` count how many **weekdays** the ETF data trails the last completed US session (close taken as 21:00 UTC). 1 session behind → footer note only (indistinguishable from a holiday — there is no holiday calendar, on purpose); 2+ → degraded.
- **Degraded (exit 2)** = fallback analysis, a Claude note failing the quality gates (truncated / too short / too long / missing sections → `source="claude_incomplete"`), a stale series, a missing required series (`dashboard.REQUIRED_MACRO_KEYS` = VIX, HY OAS, 10Y), ETFs 2+ sessions behind, or a total ETF outage. Degraded reports are still delivered, with ⚠️ banners; the Actions run shows red.
- **Time zones:** report date is KST (fixed +9, no tzdata needed); session boundaries are UTC. Functions taking `now` convert at each use.
- **Telegram splitting** (`telegram_bot.build_message_parts`) reserves room for the `(i/n)` marker so no outgoing part exceeds 4096 characters.

Environment variables: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`, `FRED_API_KEY`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` (required); optional `ETF_SOURCE` (`alpaca` default | `yahoo`), `ALPACA_FEED` (`sip` default | `iex`), `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS` (16000), `ANTHROPIC_EFFORT` (`medium`), `DRY_RUN`. Local values live in the gitignored `.env`; CI uses GitHub Secrets. `MASSIVE_API_KEY` is also in the local `.env` for the weekly work.

## Test conventions

- `tests/conftest.py` **blocks the network** (`yfinance.download`, `yfinance.Ticker`, `requests.get` raise) and **freezes the clock** at 2026-09-16 01:00 UTC in `metrics` and `dashboard`. Patch fetchers (`sectors.fetch_yahoo_frame`, `macro.get_yfinance_series`, …) in tests; never rely on the real date. Pass explicit `now=` / `today=` when a test is about time.
- Use `monkeypatch`, never direct assignment to module attributes — direct assignment leaks into later tests.
- External SDKs are stubbed only when not installed, so the suite behaves the same in CI and in a full local venv.
- `tests/test_readme_claims.py` checks README facts (ETF count, tickers, cron, exit codes, env vars, freshness windows) against the code. Change the README when behaviour changes, or CI fails.

## Lessons learned the hard way

- The default model in `analyst.py` runs **adaptive thinking even when not requested**, and thinking tokens come out of `max_tokens`. At 4096 the note was cut off while looking short. Keep the budget at 16000 and read the logged `Claude usage: … stop_reason=` line.
- **Alpaca free plan refuses SIP → IEX only.** IEX is one exchange; thinly traded ETFs (e.g. `AIHY`) come back frozen at `0.00%`. Known, labelled, accepted.
- **Batched `yf.download` lagged a full session** at run time, while per-ticker `yf.Ticker().history()` was current. That is why ETFs went back to Alpaca.
- **FRED yields and OAS reach FRED about one business day late.** Rates/credit dated earlier than equities is normal and is disclosed in the footer.
- **Calendar-day tolerances cannot see a consistent one-session lag** — that is why `sessions_behind` exists.
- **Tests can rot with the calendar.** Four fixtures passed when written and failed a week later. The frozen clock in `conftest.py` prevents this.

## Weekly Commentary — the active project

**Goal:** a weekly macro/market commentary built on **Massive API (free Basic tier)** plus a small set of supplementary sources, delivered by the same Telegram bot. Developed on a long-lived experimental branch **`weekly-commentary`** (not created yet) so `main` and the live daily bot stay untouched. The user will add more data and content ideas later — build the foundation, don't pre-build speculative features.

**Status:** Massive API key obtained, stored in the local `.env` as `MASSIVE_API_KEY`, connection confirmed. Confirm whether it is also in GitHub Secrets before any workflow needs it.

### Massive Basic tier — constraints that shape the design

From the user's research note (2026-09-22); verify against Massive docs when implementing.

- **5 REST requests/minute per asset class** (Stocks, Options, Indices, Currencies, Futures). Extra API keys do not add capacity.
- EOD data, ~2 years history (indices 1+ year). No snapshots, trades, quotes, WebSockets or flat files.
- **Grouped daily** `/v2/aggs/grouped/locale/us/market/stocks/{date}` returns the whole US equity market's daily OHLCV **in one call** — use it for all ETFs instead of one call per ticker.
- **Economy API** (`/fed/v1/treasury-yields`, `/fed/v1/inflation`, `/fed/v1/inflation-expectations`, `/fed/v1/labor-market`, `/fed/v1/funding-conditions`) covers the full Treasury curve, inflation and funding conditions.
- **Not available on Basic:** SPX, DJI, RUT and **VIX** index values; HY/IG credit spreads; financial statements.
- `vX` endpoints (SEC filings, float, etc.) are less stable than `v1`–`v3`.

### Planned source map

| Data | Weekly source |
|---|---|
| 22 ETFs | Massive grouped daily (Stocks) — replaces Alpaca; fixes the IEX thin-ETF problem |
| Treasury curve, inflation, funding | Massive Economy |
| WTI / gold / copper | Massive Futures (or keep Yahoo — user decision) |
| DXY / USD-KRW | Massive Currencies (or keep Yahoo — user decision) |
| HY / IG OAS | **stays FRED** (Massive gap) |
| VIX | **stays Yahoo `^VIX`** (Massive Basic excludes it; CBOE later) |

### Design decisions already agreed

- **Request queue → per-asset-class rate limiter → REST → cache.** Each class spaces calls ~12 s apart (configurable). Retry with backoff on HTTP 429. A per-run budget guard asserts calls stay under quota.
- **The rate limiter takes an injectable clock/sleep** so tests run instantly.
- **Cache aggressively:** EOD data doesn't change within a week. Raw responses cached as JSON on disk (`cache/`, gitignored). The same saved responses double as test fixtures.
- **Only one script calls live Massive** (`scripts/record_fixtures.py`); everything else replays saved data.
- **The repo is public:** commit only small, hand-trimmed fixtures (the tickers actually used), not full grouped-daily dumps — both for size and because redistributing Massive data may breach their terms.
- **Weekly cadence:** drop day-over-day emphasis, reframe around 1W/1M/3M, curve shape, inflation trend, funding conditions and realised volatility. "1W" means 5 observations, not a calendar week — say so in the report.
- The weekly job gets its **own workflow file, `workflow_dispatch` only** until the user decides to schedule it. Don't modify `daily-dashboard.yml` on the branch.
- Experimental sends go to a **test Telegram chat** (`TELEGRAM_BOT_TOKEN_TEST` / `TELEGRAM_CHAT_ID_TEST`), never the real one.

Proposed layout (confirm with the user before creating):

```
src/massive_client.py      HTTP + per-class rate limiter + cache + budget guard
src/massive.py             Massive collectors → Metric records
scripts/record_fixtures.py the only live-Massive caller
tests/fixtures/massive/    small trimmed JSON samples (committed)
cache/                     runtime response cache (gitignored)
```

### Stages

Each stage gets an overview and a user decision before any code.

| Stage | Work |
|---|---|
| A | Create `weekly-commentary` from `main`; confirm `MASSIVE_API_KEY` in GitHub Secrets; manual-only weekly workflow skeleton; test-chat env vars |
| B | Massive client foundation: per-class limiter (injectable clock), retry/backoff, raw cache, budget guard, record script, fake-clock tests |
| C | Massive collectors → `Metric` (grouped-daily ETFs, Economy, optionally Futures/FX); keep FRED (OAS) and Yahoo (VIX) |
| D | Weekly snapshot + dashboard sections (curve, inflation, funding), footer notes for supplementary sources |
| E | Weekly prompt and fallback rewritten for the weekly framing |
| F | Integration: `DRY_RUN`, test chat, manual dispatch, tuning |
| G | User decides: replace the daily bot / run both / abandon → merge to `main` or not |

### Open questions to settle before Stage B

1. Does the Economy API have its own 5/min queue, or share one?
2. Auth style (query parameter vs header).
3. Does grouped daily return adjusted closes, and is there an `adjusted` parameter?
4. Futures and FX: Massive or keep Yahoo?
5. Delivery shape: same two Telegram messages, or a different weekly layout?

## Git workflow

One local folder; switch branches in place (VS Code shows the current branch bottom-left).

- `main` mirrors the live bot. **Never commit to it directly** — it changes only through merged PRs, then `git pull`.
- `weekly-commentary` holds the experiment. Suggested default: a short-lived branch per stage off `weekly-commentary` → PR into `weekly-commentary` (CI runs; the web session can review) → the user merges. Propose this at Stage A and let the user choose.
- Commit or stash before switching branches. The shared `.env` and `venv` stay put across switches; after switching, `pip install -r requirements.txt` if dependencies differ.
- Switching branches locally cannot affect production — the live bot runs from GitHub `main` via Actions.

## Starting a new session

Read this file, summarise the plan and current status back to the user in a few lines, confirm which stage is next, then give the overview for that stage and wait for a decision.
