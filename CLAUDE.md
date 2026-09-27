# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working with this user — read first

- The user is **new to coding** and is learning project management through AI-assisted development. Explain in plain terms. Give Windows PowerShell commands they can copy and paste.
- **Do not execute decisions automatically.** For every step: give a short overview of what will change and why, lay out the options with a recommendation, and **wait for the user to decide**. Routine mechanics inside an approved step are fine; choices about scope, design or data sources are not.
- Keep everything except the core answer short and direct. On the core answer, be thorough and double-check the logic.
- When you find a problem, say so plainly with the evidence (log line, failing test, number). If an earlier explanation turns out wrong, correct it explicitly.

## Two sessions, two roles

- **Local VS Code session** — builds each change on its own branch off `main`, runs code and live API calls on the user's laptop.
- **Web session (claude.ai/code)** — GitHub integration only: reviewing and refining PRs, merging when the user says so.
- Never have both editing the same branch at once. `git pull` before starting work.

## Commands

Local environment is Windows + VS Code + PowerShell, **Python 3.14** in the project's own `venv\` (the pinned lock installs and the full suite passes on it). CI runs Ubuntu / **Python 3.12** — write code that works on both.

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
python scripts/massive_probe.py       # weekly branch: live Massive check (~8 free calls; by hand only, never in Actions)
```

`requirements-direct.txt` records the packages actually imported; `requirements.txt` is the full lock.

## Architecture (daily bot)

**Since Stage G the scheduled bot is the weekly one** (`src/weekly_main.py`, `.github/workflows/weekly-commentary.yml`, primary `17 5 * * 6` UTC = Saturday 14:17 KST plus two guarded backup slots; see "Weekly Commentary" below). The daily bot described here is **manual only**: `daily-dashboard.yml` keeps its Run button, and its old cron `0 23 * * 0-4` is noted in a comment there. GitHub only runs scheduled workflows from the default branch, so a workflow on another branch cannot fire on a schedule. `tests.yml` runs `compileall` + `pytest` on every push and pull request.

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

- `tests/conftest.py` **blocks the network** (`yfinance.download`, `yfinance.Ticker`, `requests.get`, `anthropic.Anthropic` and `telegram_bot.Bot` raise), **blanks every key** (env and module constants — `load_dotenv()` would otherwise bring the laptop's real keys back) and **freezes the clock** at 2026-09-16 01:00 UTC in `metrics` and `dashboard`. Patch fetchers (`sectors.fetch_yahoo_frame`, `macro.get_yfinance_series`, …) in tests; never rely on the real date. Pass explicit `now=` / `today=` when a test is about time.
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

**Goal:** a weekly macro/market commentary built on **Massive API (free Basic tier)** plus a small set of supplementary sources, delivered by the same Telegram bot. Built on the branch **`weekly-commentary`** (2026-09-24, stages A–G) and merged to `main` the same day (PR #14); new work now branches off `main` (see Git workflow). The user will add more data and content ideas later — build the foundation, don't pre-build speculative features.

**Status:** Stages A–G are done and **live on `main`** (PR #14, 2026-09-24). The repo is private. The weekly report is the scheduled bot; the daily one is manual only.
- `python src/weekly_snapshot.py` collects every weekly number live: 18 Massive calls, ~2 min. The values were cross-checked against Cboe and Yahoo on 2026-09-24.
- `python src/weekly_dashboard.py` previews the real Telegram text locally: ~3,000 characters, one message.
- `python src/weekly_analyst.py` writes Claude's note locally, costing one Claude call. The live test on 2026-09-24 used Sonnet 5: 3.6k input and 3.4k output tokens (≈ $0.04), 683 words, `end_turn`, and every number checked matched the snapshot.
- `python src/weekly_main.py` runs the whole weekly job. On 2026-09-24:
  - A `DRY_RUN` gave exit 0; message 1 was 2,999 characters and message 2 was 3,833 (one part each); no Markdown.
  - The **first real send reached the user's Telegram chat**: exit 0, `claude-sonnet-5`, 3.7k input and 3.7k output tokens.
- `MASSIVE_API_KEY` is in the local `.env` and in GitHub Secrets.
- **First GitHub run** (manual, 2026-09-24, run #1): exit 0, 18 Massive calls (two 60 s rate-limit waits, ~3 min), `claude-sonnet-5` `end_turn`, both messages sent. The log showed statuses and counts only. Whether Yahoo (DXY) answered from the runner isn't visible in the log, only in the message.
- **First scheduled slot** (`0 3 * * 6`, 2026-09-26) was **dropped**: no run was ever created (checked 29 h later), although the workflow was `active` on `main`. The daily cron on this repo had fired 7/7 times (09-07…09-15), each 1 h 47 m – 2 h 12 m late. GitHub community discussion #185355 reports schedules silently stopping in mid-2026.
- **Run #2** (manual, 2026-09-27): exit 0, 17 Massive calls (Friday 09-25 grouped daily returned 200 at 09:01 UTC Sunday), `claude-opus-5-5` (the user set the repository variable `WEEKLY_ANTHROPIC_MODEL`; effort left empty = `high`), `end_turn`, both messages sent. Log lines now appear as they happen.
- **Schedule since 2026-09-27 (PR after #15):** primary `17 5 * * 6` (Sat 14:17 KST, after New York midnight all year) and backups `17 11 * * 6` (Sat 20:17 KST) and `17 3 * * 0` (Sun 12:17 KST), each guarded by `src/weekly_guard.py`. **First live check: Sat 10-03** — expect one delivering run and two ~20 s "slot skipped" runs.

- **Robustness (PR after the backup slots, 2026-09-27):** a run degrades instead of dying.
  - Claude client `timeout=360`, `max_retries=1` (`analyst.CLAUDE_TIMEOUT_SECONDS` / `CLAUDE_MAX_RETRIES`); SDK defaults (600 s × 3) could outlast the job. Claude and Telegram errors are logged as type (+ HTTP status) only.
  - A missing `MASSIVE_API_KEY` costs only the Massive rows (`weekly_snapshot.via_massive`). ETFs are fetched before futures.
  - A failed earlier-week grouped-daily call only drops that horizon for all ETFs (`snapshot["etf_gaps"]`, footer note); only this week's failure blanks the ETFs. One failed futures product loses only its row (the ratio carries the failing leg's reason).
  - FRED retries once after 5 s on no response / 429 / 5xx; Yahoo logs `-> N rows, last <date>`.

Next: new data and content ideas from the user, one branch and PR per change.

### Massive data terms — hard rules

Massive's market-data terms limit use to **personal, non-commercial** use. They forbid publishing, displaying or transferring the data to third parties, and derived indices need a licence. The repo was public until Stage G and is private now; its Actions logs are still visible to anyone it is shared with. So:

- **Never commit Massive data.** Test fixtures in `tests/fixtures/massive/` are **synthetic**: the documented shape with made-up numbers. Real responses live only in the gitignored `cache/`.
- **Never print Massive values in Actions.** Log only the endpoint, status, counts and dates. No `DRY_RUN` in Actions. Don't put Massive data in artifacts or the Actions cache: the weekly job fetches fresh on each run (Stage F).
- The Telegram chat is the user alone, which counts as personal use.

**Terms review (2026-09-24, from the full terms page) — the user accepted the residual risk and chose not to email Massive for now:**
- **Fine:**
  - Code in the repo isn't Market Data. A search of every file and the full git history found no real Massive values.
  - Running on GitHub's runners is not "transmitting … for publication or distribution" (§2).
  - The user is the only end user (§1).
- **Open ambiguity 1:** sending Massive numbers to Claude. §5(c) forbids transferring the data or "analytics, research … derived from" it to any third party. §5(d) forbids "non-display use" unless licensed, and §2 says "strictly for display use only". This applies wherever the bot runs, laptop included.
- **Open ambiguity 2:** CME "Non-Professional" status (§4.3). CME's definition includes "has an active futures trading account". This affects the WTI / gold / copper data.
- **If Massive ever objects:** the fix is to keep Massive values out of the Claude prompt, or drop Massive futures. Deleting all Market Data on termination (§8) means clearing the local `cache/`.
- **Other sources:** FRED (ICE BofA OAS), Yahoo and Cboe have similar personal-use terms; the same no-values-in-logs rule covers them.
- **Don't compute DXY (or any index) from Massive FX pairs.** The terms treat that as a derived index.

### Massive Basic tier — confirmed (docs + live probe, 2026-09-24)

- Base URL `https://api.massive.com`. Auth is via the header `Authorization: Bearer <key>` (a `?apiKey=` parameter also works, but it would leak into URLs). The client only uses the header.
- **5 REST requests/minute per asset class**, each class counted separately. Reference endpoints have their own bucket. Economy isn't named, so the client gives it its own 5/min bucket. Over the limit → **429** with no `Retry-After`. Not entitled → **403** `NOT_AUTHORIZED`. Extra API keys don't add capacity.
- EOD data, ~2 years history (indices 1+ year). No snapshots, trades, quotes, WebSockets or flat files.
- **Grouped daily** `/v2/aggs/grouped/locale/us/market/stocks/{date}` returns the whole US market (~12,600 rows) **in one call**. **All 22 ETFs were present.** Fields: `T,o,h,l,c,v,vw,n,t`.
  - Closes are split-adjusted, but **never dividend-adjusted**, so returns are price-only. The daily bot uses total return; this difference must be disclosed.
  - A **weekend date returns 200 `OK`, `resultsCount: 0`, and no `results` key at all**. Treat a missing or empty `results` as "no session" (this also covers holidays).
- **Treasury yields** `/fed/v1/treasury-yields` (`date.gte`, `sort=date.desc`, `limit`):
  - Fields actually returned: `date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year`. The docs also list 6M/3Y/7Y/20Y, but those were absent.
  - Latest row is **one business day behind** (09-22 on 2026-09-24 KST), the same lag as FRED.
- **Futures** (`/futures/v1/contracts`, `/futures/v1/aggs/{contract}?resolution=1session`). The docs were wrong in places. Solved in Stage C (`massive.get_futures_series`):
  - Codes: **CL** (NYMEX `XNYM`), **GC** and **HG** (COMEX `XCEC`). There is no continuous ticker, and no `days_to_maturity` field.
  - **Without `date=`, contracts come back once per contract per day back to 2025**, so a page covers almost nothing. `sort` accepts only `date`, `product_code` and `ticker`. The `type` label is unreliable: spreads like `CL:BF F7-G7-H7` are labelled `"single"`.
  - The working query: build the next 8 monthly tickers (`GCV6, GCX6, …`) and request them with `ticker.any_of`, plus `date=<week's Friday>`. If that returns empty, retry the day before: the current day's snapshot can be empty, as it was for gold on 09-24.
  - Keep only outrights (regex `^CODE[FGHJKMNQUVXZ]\d{1,2}$`) and skip contracts within 14 days of `last_trade_date`. The expiring month otherwise pushes December gold out of the top 3. Then take the **most traded (last 5 sessions) of the next 3**.
  - On 2026-09-24 this picked CLX6, GCZ6 and HGZ6, the benchmark months.
  - Bars come **newest first**. `window_start` is the previous calendar day, so **date by `session_end_date`**. A bar with `settlement_price: null` is a session still trading and must be dropped. Values use `settlement_price`.
- **The rate limit is counted server-side across processes.** Two probe runs less than a minute apart got a 429. The client's retry handled it.
- **DXY is not on Massive.** A reference search for "DXY" found only unrelated stocks.
- **Not available on Basic:** SPX, DJI, RUT and **VIX** index values; HY/IG credit spreads; financial statements.
- The `vX` endpoints are less stable than `v1`–`v3`.

### Source map (agreed 2026-09-24)

Same instruments as the daily bot, **minus USD/KRW**. New data (inflation, funding, more ETFs…) comes only after the foundation works — the user will add it.

| Data | Weekly source | To verify |
|---|---|---|
| 22 ETFs | Massive Stocks grouped daily — replaces Alpaca; fixes the IEX thin-ETF problem | ✅ all 22 present; price-only (not dividend-adjusted) |
| 10Y / 2Y (→ 2s10s) | Massive Economy `/fed/v1/treasury-yields` | ✅ works; one business day behind, like FRED |
| WTI / gold / copper | Massive Futures: settlement of the most-traded nearby contract; all horizons from that one contract (no roll jumps) | ✅ |
| DXY | **Yahoo `DX-Y.NYB`** (decided 2026-09-24; not on Massive, and computing it from Massive FX is ruled out by the terms) | ✅ |
| HY / IG OAS | **FRED, unchanged** (Massive gap; one-day lag known and disclosed) | IG kept by assumption — user may drop it |
| VIX | **Cboe public CSV** `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` (no key; `DATE,OPEN,HIGH,LOW,CLOSE`, MM/DD/YYYY; from 1990). **Falls back to Yahoo `^VIX`** when Cboe lacks the week's last session | At 05:00 UTC on 2026-09-24 it still ended at 09-22 (updated 01:51 GMT 09-23), so it runs **more than a session behind** |
| USD/KRW | **dropped** from the weekly report (daily bot unchanged) | — |

### Design decisions already agreed

- **`src/massive_client.py` (built in Stage B)** is the only way code reaches Massive. It uses plain `requests` (no official SDK).
  - A **rolling-window limiter per asset class** (`stocks, economy, futures, currencies, reference`, 5 per 60 s + 1 s margin): the first 5 calls go at once, and the 6th waits. The clock and sleep are injectable.
  - Retries: **429** waits 60 s (2 retries); **5xx or a dropped connection** waits 5 s then 15 s; **401/403** raises `MassiveAuthError` at once.
  - A **per-run budget** (`max_calls`, default 40) raises `MassiveBudgetExceeded` *before* sending a request. Retries count against it; cache hits don't.
  - The **cache is opt-in per call** (`cache=True`). Use it only for settled past dates, so an early empty answer never gets frozen. Files go to `cache/massive/<class>/<path>__<hash>.json`.
  - The log shows counts, never values, and never the key. `next_url` paging isn't built; a response that has more pages logs a warning.
- **Only one script calls live Massive: `scripts/massive_probe.py`** (renamed from `record_fixtures.py`, since fixtures are synthetic). Run it by hand only. It prints structure, not values, and saves the raw answers to `cache/`.
- **Weekly cadence:** drop day-over-day emphasis, reframe around 1W/1M/3M, curve shape and realised volatility.
- **A week is a Monday–Friday calendar week, measured on week-end closes** (built in Stages C/D):
  - 1W = this week's last close vs the previous week's last close.
  - 1M = vs 4 weeks earlier; 3M = vs 13 weeks earlier.
  - "Last close" = the week's final trading day — usually Friday, Thursday if Friday is a holiday. Take the last available bar inside the Mon–Fri window rather than using a holiday calendar.
  - Not "the last 5 observations". **Built in `src/weeks.py`**: every collector hands in a dated daily series and `weekly_metric()` makes the `Metric`. Weekly metrics carry `horizons=WEEKLY_HORIZONS` (1W/1M/3M, with 3M in the new `quarter_change`); daily ones keep the default and render byte-identically.
  - **The report always covers the last completed week** (Friday's 21:00 UTC close has passed), even when it runs midweek.
  - No observation inside the target week means the value is **missing** ("no data in the week of …"), never last week's number.
  - A 1M/3M with no prior close is simply left out. AIHY (listed 07-21) and NCLD (listed 08-06) have no 3M yet.
- **Weekly workflow (`.github/workflows/weekly-commentary.yml`, Stage F):**
  - Stage F: `workflow_dispatch` only; Stage G added the Saturday cron; 2026-09-27 added the backups and the guard. It uses the secrets `TELEGRAM_*`, `ANTHROPIC_API_KEY`, `FRED_API_KEY` and `MASSIVE_API_KEY`, and takes `WEEKLY_ANTHROPIC_MODEL` / `_EFFORT` from repository **variables** (`vars.*`; empty means the code defaults).
  - It has no `DRY_RUN`, no artifacts and no `actions/cache`. `tests/test_weekly_main.py` enforces all of this.
  - `PYTHONUNBUFFERED=1`, so log lines appear as they happen (run #1's lines were all stamped at exit).
  - **Guard (`src/weekly_guard.py`, stdlib only, runs before `pip install`):** on `schedule` events only, it lists this workflow's runs created since the last completed week's Friday 21:00 UTC (`weeks.last_completed_week` + `metrics.US_SESSION_CLOSE_UTC_HOUR`) and skips the slot if one has its **"Run weekly commentary"** step at `success`. That step fails only on exit 1; exit 2 fails the separate "Flag degraded report" step, so degraded weeks count as sent and stay red. API unreadable → run anyway. Needs `permissions: actions: read`; `continue-on-error: true` so a broken guard still sends. The step name is `weekly_guard.DELIVERY_STEP`; a test keeps them equal.
  - The job runs only on `refs/heads/main`, so a Run button on another branch can't post to the chat. `timeout-minutes: 30`.
  - Don't modify `daily-dashboard.yml`.
- **Telegram: the real chat**, no test chat (the daily bot is inactive, so no clash). `DRY_RUN=1` is the safety switch while developing. So `telegram_bot.py` needs no chat-override change.

### Layout (agreed): flat, no separate folder

The branch is the separation; new files sit beside the existing ones and are named by purpose. Existing modules import each other by bare name (`from metrics import Metric`), so a subfolder would need extra import plumbing.

```
src/massive_client.py      HTTP + per-class rate limiter + cache + budget guard   (B)
src/massive.py             Massive collectors → Metric records                    (C)
src/weekly_dashboard.py    weekly snapshot layout                                  (D)
src/weekly_analyst.py      weekly prompt, required sections, fallback              (E)
src/weekly_main.py         weekly entry point + exit code                          (F)
src/weekly_guard.py        skip a scheduled slot once the week was delivered      (after G)
scripts/massive_probe.py   the only live-Massive caller, run by hand               (B)
tests/fixtures/massive/    synthetic JSON samples (committed; never real data)
cache/                     runtime response cache (gitignored)
```

Reuse as-is: `metrics.Metric` + freshness helpers, `macro.get_fred_series` / `_fred_metric` (OAS), `sectors.ETF_GROUPS` / `SECTOR_GROUP_KEYS` / `GROUP_TITLES`, `telegram_bot` splitting/sending, `dashboard.report_date` / `_section` / `format_as_of_label`, `main.decide_exit_code`.
Small edits to shared files (keep the daily output identical — the existing suite proves it): `metrics.py` gains a 3M horizon; `analyst.call_claude` / `check_analysis_quality` accept a prompt and section list, with the daily ones as defaults.

### Stages

Each stage gets an overview and a user decision before any code.

| Stage | Work |
|---|---|
| A ✅ | Local `venv` (Python 3.14); `weekly-commentary` from `main`; `cache/` gitignored; decisions recorded; user confirms `MASSIVE_API_KEY` in GitHub Secrets |
| B ✅ | Massive client foundation: per-class limiter (injectable clock), retry/backoff, raw cache, budget guard, probe script, fake-clock tests, live probe |
| C ✅ | `weeks.py`, `massive.py`, `cboe.py`, `weekly_snapshot.py`; `macro.get_fred_observations` / `get_yfinance_closes` (the daily `get_fred_series` now wraps the first, same output); `Metric.quarter_change` + `horizons` |
| D ✅ | `weekly_dashboard.py`: two-line rows (`Metric.render_block`), a movers block, footer notes, `is_weekly_degraded` |
| E ✅ | `weekly_analyst.py`: weekly prompt (6 sections, ~700 words), gates 150–1,000, deterministic fallback, own model settings, Markdown stripped; `analyst.call_claude` / `check_analysis_quality` take per-call settings and report refusals |
| F ✅ | `weekly_main.py` (fetch, format, analyse, send, exit code; reuses `send_analysis_report` / `decide_exit_code`; refuses `DRY_RUN` inside Actions); inert manual workflow; local dry run + first real send |
| G ✅ | Weekly replaces daily: weekly cron `0 3 * * 6`, daily manual only; the repo goes private; terms review recorded; crash-safe logging; then `weekly-commentary` → `main` by PR |

### Stage D decisions (2026-09-24)

- **Delivery: two messages, like the daily bot.** Message 1 is the snapshot (`format_weekly_dashboard`), message 2 is Claude's note. Reuse `telegram_bot.send_analysis_report` in Stage F.
- **Rows take two lines:** `• Name (SYM)  value`, then `   1W ▲x · 1M ▼y · 3M ▲z`, built by `Metric.render_block()` / `format_changes_compact()`. A row with no changes (the Gold/Copper ratio) takes one line.
- **Movers block:** the top 3 and bottom 3 ETFs by 1W, from usable rows only.
- **Footer:**
  - source facts from the snapshot: contracts used, VIX fallback
  - ETFs are price-only
  - values dated before Friday
  - 3M unavailable (under 13 weeks of history)
  - missing rows
  - The derived notes live in `weekly_dashboard.weekly_data_notes`; `weekly_snapshot.source_notes` supplies only the source facts.
- **Degraded** (`is_weekly_degraded`) when VIX, HY OAS or 10Y is unusable, or every ETF is. Everything else is a note only.

### Stage E decisions (2026-09-24)

- **Sections:** Regime Read, Market Read, Leadership, Trend View, What Doesn't Fit, Next Week Watch. About 700 words; gates at 150 / 1,000. The check accepts a curly apostrophe (Doesn’t).
- **Model:** `WEEKLY_ANTHROPIC_MODEL` (default `claude-sonnet-5`) and `WEEKLY_ANTHROPIC_EFFORT` (default `high`), separate from the daily settings.
  - The user plans to move to a larger model later. The request shape (adaptive thinking + `output_config.effort`, `max_tokens` 16000, no prefill) is valid on Sonnet 5, Opus 5, Opus 5.5 and Fable 5.1, so that's an env change only.
  - When they switch to Opus 5 / Fable 5.1, **offer Anthropic's server-side refusal `fallbacks`** (beta; see the claude-api skill). They weren't enabled for Sonnet 5.
  - A refusal currently becomes the deterministic fallback with the warning "Claude declined (<category>)".
- The note is **signed** `— <model> · effort <effort>`.
- **Markdown handling:** the live run returned Markdown headings, so the prompt now asks for plain text and `weekly_analyst.plain_text()` strips `#` headings and `**` / `__` markers before sending.
  - The fixed prompt has **not yet been seen live**; check it in Stage F's `DRY_RUN`.
- The prompt gets breadth ("X of N up over 1W / 1M / 3M") computed in code, the movers and the footer notes. The HYG price-only caveat is spelled out.

### Stage G decisions (2026-09-24)

- **Weekly replaces daily.**
  - `weekly-commentary.yml` ran on `cron: '0 3 * * 6'` (Saturday 12:00 KST); it is now three guarded slots (see Status) and keeps its Run button.
  - `daily-dashboard.yml` lost only its `schedule:`. It is manual-only now, and a comment there shows the old cron for restoring it. Tests enforce both (`test_weekly_main.py`, `test_readme_claims.py`).
- **Why that hour (revised 2026-09-27):** after New York midnight, so Massive's end-of-day Friday bar is final — Massive/Polygon Basic can refuse "today's data before end of day" with a 403, which `massive_client` treats as `MassiveAuthError` and which would blank all 22 ETFs (not observed; the only timing evidence is "had the previous session by 05:00 UTC"). Cboe updated its VIX file at 01:51 GMT the day after a session. Rates and credit still show Thursday; the footer says so. GitHub may start runs 1–2 h late.
- **The repository goes private** (the user does this in Settings, *before* the merge to `main`), so Actions logs are no longer public. The no-values-in-logs rules still apply.
- **`weekly_main.main()` catches any unexpected exception and prints only its type.** An exception message or traceback can quote a value.
- The test fixtures' real Cboe VIX numbers were replaced with invented ones.
- **After merge:** the first GitHub run passed on 2026-09-24 (see Status).
- **Model:** the user may later set the repository variable `WEEKLY_ANTHROPIC_MODEL` to a larger model. Offer the server-side refusal `fallbacks` then.

## Git workflow

One local folder; switch branches in place (VS Code shows the current branch bottom-left).

- `main` mirrors the live bot. **Never commit to it directly** — it changes only through merged PRs, then `git pull`.
- **Agreed (2026-09-26):** one short-lived branch per change off `main` → PR into `main` → wait for the green **Tests** check on the PR (nothing enforces this: `main` has no branch protection, and GitHub Free doesn't offer it for private repos) → the user merges → delete the branch → `git checkout main; git pull`.
- `weekly-commentary` and `weekly/stage-*` were the Stage A–G branches; all are merged and can be deleted.
- Commit or stash before switching branches. The shared `.env` and `venv` stay put across switches; after switching, `pip install -r requirements.txt` if dependencies differ.
- Switching branches locally cannot affect production — the live bot runs from GitHub `main` via Actions.

## Starting a new session

Read this file, summarise the plan and current status back to the user in a few lines, confirm which stage is next, then give the overview for that stage and wait for a decision.
