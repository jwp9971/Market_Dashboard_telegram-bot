# Market Intelligence Bot

A personal macro and market briefing delivered to Telegram. Each report
collects rates, credit, commodities, the dollar, volatility and a fixed set of
ETFs. Claude then writes a strategist note that uses only that data, and the
bot sends two messages: the data snapshot and the note. Everything runs on
GitHub Actions, with no server and no database.

Built as a self-directed learning project with no prior programming
background, through iterative AI-assisted development.

---

## Current status

*As of 2026-09-26*

| Report | State | Entry point | When it runs |
|---|---|---|---|
| **Weekly commentary** | **Live**, the scheduled report since 2026-09-24 | `src/weekly_main.py` | Every Saturday at 12:17 Korea time, or by hand |
| Daily dashboard | Paused: still in the code, runs by hand only | `src/main.py` | Run workflow button only |

- The weekly report was built in seven reviewed stages (PRs #7–#13) and
  merged to `main` on 2026-09-24 (PR #14). Its first GitHub Actions run the
  same day delivered both messages cleanly (exit 0).
- The repository is private. Most weekly data comes from Massive, whose terms
  allow personal use only (see [Data-use rules](#data-use-rules)).
- **Next:** new data and content for the weekly report, one reviewed change
  at a time.

---

## The weekly report

### What it sends

**Message 1, the snapshot.** The numbers below are made up and the message is
shortened:

```
📊 Weekly Market Dashboard
🗓 Week of Sep 14–18, 2026 (KST report: Saturday, September 19, 2026)
📏 Week-end closes: 1W vs previous Friday · 1M = 4 weeks · 3M = 13 weeks

🏆 Leaders 1W: SOXX ▲4.10% · DRAM ▲3.85% · IGV ▲2.60%
📉 Laggards 1W: XLE ▼2.35% · IBIT ▼1.90% · XLV ▼0.75%

━━━━━━━━━━━━━━━━━━━━
🌡 VOLATILITY & COMMODITIES
━━━━━━━━━━━━━━━━━━━━
• VIX  16.40
   1W ▼6.29% · 1M ▼9.39% · 3M ▲3.80%
• WTI Crude (CLX6)  $63.10
   1W ▼1.87% · 1M ▼4.10% · 3M ▼8.25%
…

━━━━━━━━━━━━━━━━━━━━
📈 RATES & CREDIT  · as of Sep 17
━━━━━━━━━━━━━━━━━━━━
• 10Y Treasury  4.12%
   1W ▲0.06pts · 1M ▼0.09pts · 3M ▼0.21pts
…

… Dollar, then the three ETF sections …

⚠️ Data notes:
• ETF changes are price-only: Massive closes are split- but not dividend-adjusted
• Last value before Friday (a holiday, or the source runs a day behind): 10Y, 2Y, 2s10s, HY OAS, IG OAS
```

**Message 2, Claude's note.** It runs to about 700 words of plain text in six
sections: Regime Read, Market Read, Leadership, Trend View, What Doesn't Fit
and Next Week Watch. The note ends with a line naming the model and effort
that wrote it. A note under 150 or over 1,000 words, cut off, or missing a
section is flagged. If Claude declines, fails or is unavailable, the bot sends
a fixed fallback note instead, with a ⚠️ warning explaining why.

### How a week is measured

- The report covers the **last completed Monday–Friday week**, even when it
  runs midweek.
- A week's close is its last trading day inside Monday–Friday: usually
  Friday, or Thursday when Friday is a holiday.
- **1W** compares with the previous week's close, **1M** with four weeks
  back and **3M** with thirteen weeks back.
- A source with nothing inside the week shows the row as missing. It never
  repeats last week's number.
- 3M is left out until a fund has 13 weeks of history.

### Weekly data sources

| Data | Source | Notes |
|---|---|---|
| **22** ETFs | Massive, grouped daily bars | Price-only: split-adjusted but not dividend-adjusted |
| 10Y, 2Y, 2s10s | Massive, Treasury yields | One business day behind |
| WTI, gold, copper | Massive, futures | Official settlement of the most-traded of the next three contracts. That one contract gives every horizon, so a contract roll never shows up as a jump |
| HY OAS, IG OAS | FRED (ICE BofA) | One business day behind |
| VIX | Cboe's public history file | Falls back to Yahoo `^VIX` when Cboe hasn't published the week's last session |
| Dollar Index | Yahoo `DX-Y.NYB` | Not available on Massive |
| The note | Anthropic Claude | `WEEKLY_ANTHROPIC_MODEL`, default `claude-sonnet-5` |

USD/KRW is not part of the weekly report.

### The 22 ETFs (both reports)

- **Macro (9)**: DIA, SPY, QQQ, IWM, HYG, IBIT, EWY, EWJ, IEMG
- **Broad Industry (5)**: XLE, XLF, XLV, XLI, XLY
- **Theme (8)**: SOXX, IGV, PAVE, ITA, DRAM, AIHY, BUG, NCLD

Korea is represented by **EWY**, a US-listed, USD-denominated ETF. Its moves
include USD/KRW and follow US trading hours, so it is only a rough stand-in,
not a KOSPI reading.

### When a weekly report is degraded

The run exits `2` (see [Reading the result](#reading-the-result)) when:

- the note is the fallback, or fails the checks above
- VIX, HY OAS or the 10Y is unusable
- every ETF is unusable

A single missing row, values dated before Friday, or the VIX fallback only
adds a line to the data notes.

### Data-use rules

Massive's market-data terms allow **personal, non-commercial use only**. They
forbid publishing its data or passing it to others. So:

- Real Massive responses are never committed. Test fixtures use invented
  numbers, and the local response cache (`cache/`) is gitignored.
- The Actions job logs only endpoints, statuses and counts, never values. It
  refuses `DRY_RUN`, uploads no artifacts and uses no Actions cache.
- The Telegram chat has one reader: the owner.
- One question is still open: sending Massive numbers to Claude may count as
  passing the data on under the terms. The owner reviewed this on 2026-09-24
  and accepted the risk. If Massive objects, the fix is to keep Massive
  values out of the prompt.
- Nothing computes an index (for example DXY) from Massive data, because the
  terms treat that as a derived index that needs a licence.

---

## Schedule

**Weekly report:** `17 3 * * 6` UTC, which is **12:17 Korea time every
Saturday**. It runs about six hours after Friday's close, once Friday's ETF,
futures and VIX data have been published. Rates and credit still show
Thursday, because those sources run one business day behind, and the footer
says so. The minute is 17 rather than 0 because GitHub's scheduler is busiest
on the hour: the first scheduled run, set for `0 3` on 2026-09-26, had not
started three hours later.

**Daily report:** manual only (the Run workflow button). Its old schedule was
`0 23 * * 0-4` UTC (08:00 Korea time, Monday to Friday) and can be restored
in `.github/workflows/daily-dashboard.yml`.

GitHub's scheduled workflows are best-effort. They often start late and can
occasionally be skipped. If no report has arrived by mid-afternoon Korea time,
start one with **Actions → Weekly Commentary → Run workflow**. A late
scheduled run can still start afterwards, which would send a second copy.

---

## Setup

### Environment variables

Locally, put these in a `.env` file (it is gitignored). In GitHub Actions,
add them as repository secrets.

| Variable | Used by | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | both | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | both | Destination chat |
| `ANTHROPIC_API_KEY` | both | Claude commentary |
| `FRED_API_KEY` | both | Credit spreads (and the daily report's Treasury yields) |
| `MASSIVE_API_KEY` | weekly | Massive market data (free Basic plan) |
| `ALPACA_API_KEY` | daily | ETF daily bars (daily default source) |
| `ALPACA_SECRET_KEY` | daily | ETF daily bars (daily default source) |

Optional settings:

- **Weekly:** `WEEKLY_ANTHROPIC_MODEL` (default `claude-sonnet-5`) and
  `WEEKLY_ANTHROPIC_EFFORT` (default `high`). In Actions, set these as
  repository **variables** (Settings → Secrets and variables → Actions →
  Variables). Moving to a larger model only means changing that variable.
- **Daily:** `ETF_SOURCE` (`alpaca` default, or `yahoo`; the `ALPACA_*` pair
  isn't needed with `yahoo`), `ANTHROPIC_MODEL` (default `claude-sonnet-5`),
  `ANTHROPIC_MAX_TOKENS` (default `16000`), `ANTHROPIC_EFFORT` (default
  `medium`), `ALPACA_FEED` (`sip` default, or `iex`).
- **Both:** `DRY_RUN=1` prints the messages instead of sending them.

### Install and run (Windows PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1            # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements.txt        # the pinned lock that CI installs

$env:DRY_RUN=1; python src/weekly_main.py            # weekly: print both messages, send nothing
Remove-Item Env:DRY_RUN; python src/weekly_main.py   # weekly: send both messages to Telegram
$env:DRY_RUN=1; python src/main.py                   # daily: print, send nothing
```

A dry run still calls the data APIs and Claude, so it costs one Claude
request, but nothing reaches your chat. Some commands preview single parts of
the weekly report locally:

- `python src/weekly_snapshot.py` prints the collected numbers.
- `python src/weekly_dashboard.py` prints message 1.
- `python src/weekly_analyst.py` writes the note, at the cost of one Claude
  call.

`run.bat` runs the daily report on Windows.

### Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest -q                    # no network, no API keys, no messages
```

The same suite runs in GitHub Actions on every push and pull request, on
Python 3.12. `tests/test_readme_claims.py` checks facts in this README against
the code.

---

## Reading the result

Both reports end with an exit code, so the Actions list shows at a glance what
happened:

| Exit | Meaning | Actions |
|---|---|---|
| `0` | Clean: a complete Claude note on healthy data | green |
| `1` | Failed: nothing delivered | red |
| `2` | Degraded: delivered, but read the warnings | red |

Degraded reports are still delivered, with a ⚠️ banner on the note naming the
reason and a data-notes footer on the snapshot. The run summary in Actions
says "delivered (OK)", "delivered but DEGRADED" or "FAILED".

---

## The daily dashboard (paused)

The original report ran every weekday morning until the weekly report
replaced it on 2026-09-24. It is kept working and can be run by hand.

<details>
<summary>What it sends, data sources and freshness rules</summary>

### What it sends

```
📊 Daily Market Dashboard
🗓 Tuesday, September 15, 2026 (KST)
📍 Market data as of Sep 12

━━━━━━━━━━━━━━━━━━━━
🌡 VOLATILITY & COMMODITIES
━━━━━━━━━━━━━━━━━━━━
• VIX: 19.84 (▲8.42% D/D | ▼4.10% 1W | ▼11.30% 1M)
• WTI Crude: $62.18 (▼1.44% D/D | ▼2.90% 1W | ▼6.15% 1M)
• Gold: $3,742.60 (▲0.62% D/D | ▲1.85% 1W | ▲4.40% 1M)
• Copper: $4.58 (▼0.91% D/D | ▼1.20% 1W | ▲2.75% 1M)
• Gold/Copper Ratio: 817.2

━━━━━━━━━━━━━━━━━━━━
📈 RATES & CREDIT
━━━━━━━━━━━━━━━━━━━━
• 10Y Treasury: 4.08% (▼0.04pts D/D | ▲0.11pts 1W | ▼0.18pts 1M)
• 2s10s Spread: 0.53% (▲0.02pts D/D | ▲0.08pts 1W | ▲0.13pts 1M)
• HY OAS: 2.91% (▲0.07pts D/D | ▲0.14pts 1W | ▼0.09pts 1M)
• IG OAS: 0.78% (▲0.01pts D/D | ▲0.02pts 1W | ▼0.03pts 1M)

… FX & Dollar, then three ETF sections …

⚠️ Data notes: 1 of 34 series unavailable (AIHY).
```

Changes are labelled `D/D`, `1W` and `1M`. These are **observation counts,
not calendar intervals**: 1, 5 and 21 preceding daily observations.

### Daily data sources

| Source | Data | Notes |
|---|---|---|
| **FRED** | 2Y/10Y Treasury yields, HY OAS, IG OAS | Yields from H.15 (same business day); ICE BofA OAS series routinely lag one business day |
| **Yahoo Finance** | VIX, WTI, gold, copper, Dollar Index, USD/KRW | via `yfinance`, which is unofficial and can break without notice |
| **Alpaca Markets** | Daily bars for the 22 ETFs | Default. Free plans serve IEX only (see below) |
| **Yahoo Finance** | The same 22 ETFs, opt-in via `ETF_SOURCE=yahoo` | One batched request, consolidated closes, but lags a session |
| **Anthropic Claude** | The strategist commentary | Model set by `ANTHROPIC_MODEL`, default `claude-sonnet-5` |

### ETF price policy

ETF closes come from **Alpaca** by default. It tries the **SIP**
(consolidated) feed with split adjustment once per run. If the account isn't
entitled to SIP, it falls back to **IEX** and says so in the report footer.

**Yahoo** is available with `ETF_SOURCE=yahoo`. It fetches all 22 symbols in
one batched request. The printed price is the real market close, and the
changes are computed from split- and dividend-adjusted closes, so they are
total returns and an ex-dividend date doesn't look like a decline.

Neither source is strictly better, and both failure modes were observed:

- **Alpaca / IEX** is a single exchange with a low single-digit share of
  consolidated volume, so a thinly traded fund's close can come from very few
  trades. On 2026-09-15 it reported `AIHY` unchanged to the cent over both a
  day and a week.
- **Yahoo (batched)** lagged a full session at the hour this report runs. On
  2026-09-16 at 01:08 UTC, five hours after the Sep 15 close, it returned
  Sep 14 bars for all 22 ETFs.

Alpaca is the default because a stale `D/D` is wrong on every row, while a
frozen ticker is wrong on only one. Either way the lag is now measured and
reported (see **Session freshness** below). `alpaca-py` is needed only for
the Alpaca source.

### When a daily report is degraded

- Claude was unavailable, so the fixed fallback note was used
- Claude's note was cut off, too short, too long, or missing sections
  (`claude-sonnet-5` uses adaptive thinking by default, and those tokens come
  out of `ANTHROPIC_MAX_TOKENS`, so lowering it can bring truncation back)
- A required macro series (VIX, HY OAS, 10Y) was unavailable
- Any series was past its freshness window
- The ETF section is two or more sessions behind the expected close
- Every ETF fetch failed

### Freshness windows

Each observation is checked against a per-source limit in **calendar** days:
4 for equities and the Yahoo macro series, 5 for both FRED families. The FRED
limit was raised from 4 after the 2026-09-15 run still held Friday's yields on
the Tuesday. That was exactly 4 days, so the next Monday holiday would have
raised a false alarm.

There is deliberately **no market-holiday calendar**. It would need another
dependency or a hardcoded list that goes out of date. Calendar-day limits
absorb weekends and holidays instead. The trade-off is that a genuinely stale
series can go unflagged for an extra day or two.

### Session freshness

Calendar-day limits can't catch a source that is always one session late: Sep
14 data read on Sep 16 is only two calendar days old, well inside the limit.
So the ETF section is also checked against the most recent weekday whose US
close has certainly passed, and the gap is counted in **weekdays**:

- **1 session behind:** stated in the data-notes footer, but the run still
  passes. Without a holiday calendar, a single market holiday looks exactly
  like a real one-session lag, and failing on it would turn every holiday red.
- **2 or more:** the run is degraded. Scheduled holidays never close the
  market on two weekdays in a row; only exceptional events do, and that is
  the accepted false alarm.

</details>

---

## Project structure

```
.github/workflows/
  weekly-commentary.yml Weekly report: Saturday schedule + Run button
  daily-dashboard.yml   Daily report: Run button only
  tests.yml             Tests on every push and pull request
src/
  weekly_main.py        Weekly entry point; owns the exit status
  weekly_snapshot.py    Weekly: assembles every weekly number
  weeks.py              Weekly: Mon-Fri week-end closes and 1W / 1M / 3M changes
  massive_client.py     Massive API access: rate limit, retries, cache, call budget
  massive.py            Weekly: ETFs, Treasury yields, futures from Massive
  cboe.py               Weekly: VIX from Cboe's public history file
  weekly_dashboard.py   Weekly: snapshot text, movers, footer notes, degraded rule
  weekly_analyst.py     Weekly: Claude prompt, quality checks, fallback note
  main.py               Daily entry point; exit codes shared with the weekly report
  metrics.py            The Metric record: numbers, units, dates, quality
  macro.py              FRED + Yahoo collection (both reports)
  sectors.py            ETF list; Alpaca / Yahoo ETF collection (daily)
  analyst.py            Claude call and quality checks (shared); daily prompt and fallback
  dashboard.py          Daily snapshot text
  telegram_bot.py       Delivery and message splitting (both reports)
scripts/
  massive_probe.py      Manual live check of the Massive API (never run in Actions)
tests/                  Network-free test suite (synthetic data only)
```

Every data source returns `Metric` records carrying the value, changes, unit,
observation date, source and quality. Nothing downstream parses formatted
text; only `Metric` produces display strings.

---

## How changes are made

- `main` is what the bot runs. It changes only through pull requests.
- Each change gets its own short-lived branch from `main`, then a PR into
  `main`. Merge only after the **Tests** check on the PR is green, then delete
  the branch.
- Code and live API runs happen on the owner's laptop. PR review and merging
  happen on GitHub.

---

## Known limitations

- **No delivery guarantee.** GitHub's schedule is best-effort, so a run can
  start late or be skipped.
- **Weekly ETF changes are price-only.** Massive doesn't adjust for
  dividends, so high-yield funds such as HYG look weaker than their total
  return. The daily report's changes depend on its source: Alpaca's are
  price returns, Yahoo's are total returns.
- **Rates and credit run a business day behind.** The weekly report shows
  Thursday's values for them, and the footer says so. Equity and credit data
  can therefore come from different sessions.
- **VIX from Cboe can lag more than a session.** The Yahoo fallback covers
  that, and the footer notes it.
- **`yfinance` is unofficial.** The Dollar Index, the VIX fallback and the
  daily macro series depend on it, and it can break without warning.
- **The daily ETF sources are imperfect.** IEX misreports thinly traded
  funds, and batched Yahoo lags a session.
- **No market-holiday calendar**, on purpose (see the daily section).
- **The analyst note is not checked for accuracy.** The prompt limits it to
  the supplied data and the code checks length and sections, but nothing
  validates the claims themselves.
- **Massive's terms are only partly settled.** See
  [Data-use rules](#data-use-rules).
- **Costs are not zero.** GitHub Actions and the data APIs are free at this
  volume, but Claude requests are billed (a few cents per weekly note on the
  default model).

---

## Disclaimer

For personal informational and educational purposes. Not investment advice.
The AI-generated commentary should not be relied upon for trading or
investment decisions.
