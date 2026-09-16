# Daily Market Intelligence Bot

An automated macro and market briefing. Each weekday morning (Korea time) it
pulls macro, rates, credit, FX and ETF data, has Claude write a strategist
note grounded only in that data, and delivers both the raw snapshot and the
commentary to Telegram. It runs on a GitHub Actions schedule with no server
and no database.

Built as a self-directed learning project with no prior programming
background, through iterative AI-assisted development.

---

## What it sends

Two Telegram messages each run: a data snapshot, then the analyst note.

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
not calendar intervals** — 1, 5 and 21 preceding daily observations.

---

## Data sources

| Source | Data | Notes |
|---|---|---|
| **FRED** | 2Y/10Y Treasury yields, HY OAS, IG OAS | Yields from H.15 (same business day); ICE BofA OAS series routinely lag one business day |
| **Yahoo Finance** | VIX, WTI, gold, copper, Dollar Index, USD/KRW | via `yfinance`, which is unofficial and can break without notice |
| **Alpaca Markets** | Daily bars for **22** ETFs across 3 tiers | Default. Free plans serve IEX only — see below |
| **Yahoo Finance** | The same 22 ETFs, opt-in via `ETF_SOURCE=yahoo` | One batched request, consolidated closes, but lags a session |
| **Anthropic Claude** | The strategist commentary | Model set by `ANTHROPIC_MODEL`, default `claude-sonnet-5` |

### ETF price policy

ETF closes come from **Alpaca** by default. It prefers the **SIP**
(consolidated) feed with split adjustment, probes it once per run, and falls
back to **IEX** with a note in the report footer if the account is not
entitled.

**Yahoo** is available with `ETF_SOURCE=yahoo`: all 22 symbols in one batched
request, returning consolidated closes with the printed price being the real
market close and the changes computed from split- and dividend-adjusted closes
(so an ex-dividend date is not rendered as a decline — those are total
returns).

Neither source is strictly better, and both failure modes were observed:

- **Alpaca / IEX** is a single exchange at a low single-digit share of
  consolidated volume, so a thinly traded fund's close can be built from very
  few prints. On 2026-09-15 it reported `AIHY` unchanged to the cent over both
  a day and a week.
- **Yahoo (batched)** lagged a full session at the hour this report runs. On
  2026-09-16 at 01:08 UTC — five hours after the Sep 15 close — it returned
  Sep 14 bars for all 22 ETFs.

Alpaca is the default because a stale `D/D` is wrong on every row while a
frozen ticker is wrong on one. The lag itself is now measured and reported
either way; see **Session freshness** below. `alpaca-py` is required only on
this path.

### The 22 ETFs

- **Macro (9)** — DIA, SPY, QQQ, IWM, HYG, IBIT, EWY, EWJ, IEMG
- **Broad Industry (5)** — XLE, XLF, XLV, XLI, XLY
- **Theme (8)** — SOXX, IGV, PAVE, ITA, DRAM, AIHY, BUG, NCLD

Korea is represented by **EWY**, a US-listed, USD-denominated ETF. Its moves
embed USD/KRW and US trading hours, so it is a rough proxy and not a KOSPI
reading.

---

## Setup

### Environment variables

All six are required for a full run. Locally, put them in a `.env` file (it is
git-ignored); in GitHub Actions, add them as repository secrets.

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Destination chat |
| `ANTHROPIC_API_KEY` | Claude commentary |
| `FRED_API_KEY` | Treasury yields and credit spreads |
| `ALPACA_API_KEY` | ETF daily bars (default source) |
| `ALPACA_SECRET_KEY` | ETF daily bars (default source) |

The `ALPACA_*` pair is not needed with `ETF_SOURCE=yahoo`.

Optional: `ETF_SOURCE` (`alpaca` default, or `yahoo`), `ANTHROPIC_MODEL`
(default `claude-sonnet-5`), `ANTHROPIC_MAX_TOKENS` (default `16000`),
`ANTHROPIC_EFFORT` (default `medium`), `ALPACA_FEED` (`sip` default, or
`iex`), `DRY_RUN` (see below).

### Install and run

```bash
pip install -r requirements.txt
python src/main.py
```

`run.bat` does the same on Windows, resolving paths from its own location.

### Testing without sending anything

```bash
DRY_RUN=1 python src/main.py     # prints the messages instead of sending them
```

Still calls the data APIs and Claude, so it costs a Claude request but will
not touch your chat.

```bash
pip install -r requirements-dev.txt
python -m pytest -q              # no network, no API keys, no messages
```

---

## Schedule

`0 23 * * 0-4` UTC — **08:00 Korea time, Monday to Friday**, covering the
previous US session.

GitHub's scheduled workflows are best-effort and are frequently delayed;
observed runs have started 1–2 hours late. Schedules on public repositories
are also disabled after 60 days without repository activity. There is no
delivery-time guarantee.

---

## Reading the result

The workflow's exit code says what happened, so the Actions list is
meaningful at a glance:

| Exit | Meaning | Actions |
|---|---|---|
| `0` | Clean — complete Claude note on healthy data | green |
| `1` | Failed — nothing delivered | red |
| `2` | Degraded — delivered, but read the warnings | red |

A run is **degraded** when any of these is true:

- Claude was unavailable, so the deterministic fallback was used
- Claude's note was cut off, too short, too long, or missing sections
  (`claude-sonnet-5` runs adaptive thinking by default and those tokens come
  out of `ANTHROPIC_MAX_TOKENS`, so lowering it can reintroduce truncation)
- A required macro series (VIX, HY OAS, 10Y) was unavailable
- Any series was past its freshness window
- The ETF section is two or more sessions behind the expected close
- Every ETF fetch failed

Degraded reports are still delivered, with a ⚠️ banner on the analyst message
naming the specific reason, and a data-notes footer on the snapshot.

### Freshness windows

Observations are checked against a per-source tolerance in **calendar** days:
4 for equities and the Yahoo macro series, 5 for both FRED families. The FRED
tolerance was raised from 4 after the 2026-09-15 run held Friday's yields on a
Tuesday — exactly 4 days, so the next Monday holiday would have false-alarmed.

There is deliberately **no market-holiday calendar** — that would need another
dependency or a hardcoded list that goes out of date. Calendar-day tolerances
absorb weekends and holidays instead. The trade-off is that a genuinely stale
series can go unflagged for an extra day or two.

### Session freshness

Calendar-day tolerances cannot catch a source that is consistently one session
late: Sep 14 data read on Sep 16 is only two calendar days, well inside the
window. So the ETF section is separately checked against the most recent
weekday whose US close has certainly passed, and the gap is reported in
**weekdays**:

- **1 session behind** — stated in the data-notes footer, but the run still
  passes. A single market holiday is indistinguishable from a real one-session
  lag without a holiday calendar, and failing on it would turn every holiday
  red.
- **2 or more** — fails the run. Scheduled holidays do not close the market on
  two consecutive weekdays; only exceptional events do, and that is the
  accepted false-positive.

---

## Project structure

```
.github/workflows/
  daily-dashboard.yml   Scheduled run
  tests.yml             Tests on every push and pull request
src/
  main.py               Entry point; owns the exit status
  metrics.py            The Metric record — numbers, units, dates, quality
  macro.py              FRED + Yahoo collection
  sectors.py            Alpaca ETF collection, feed resolution
  analyst.py            Prompt, Claude call, quality gates, fallback
  dashboard.py          Renders the snapshot
  telegram_bot.py       Delivery and message splitting
tests/                  Network-free test suite
```

Collectors return `Metric` records carrying value, changes, unit, observation
date, source and quality. Nothing downstream parses formatted text; only
`Metric.render()` produces display strings.

---

## Known limitations

- **`yfinance` is unofficial.** The macro series depend on it and it can break
  without warning.
- **Neither ETF source is clean.** IEX misreports thinly traded funds; batched
  Yahoo lags a session. The lag is reported; the thin-fund distortion is not
  detectable from the data alone.
- **No market-holiday calendar**, as described above.
- **ETF returns depend on the source.** Alpaca is split-adjusted only (price
  returns); Yahoo is split- and dividend-adjusted (total returns) with the raw
  close printed.
- **`D/D`, `1W`, `1M` are observation counts**, not calendar intervals.
- **Credit and equity data can be from different sessions.** The report says so
  when it happens, but does not reconcile them.
- **No delivery guarantee** — GitHub cron is best-effort.
- **The analyst note is not verified for accuracy.** The prompt constrains it
  to the supplied data and the code checks length and section completeness,
  but nothing validates the claims themselves.
- **Costs are not zero.** GitHub Actions and the data APIs are free at this
  volume; Claude requests are billed.

---

## Disclaimer

For personal informational and educational purposes. Not investment advice.
The AI-generated commentary should not be relied upon for trading or
investment decisions.
