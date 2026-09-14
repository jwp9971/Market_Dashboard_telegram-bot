# Daily Market Intelligence Bot

An automated, AI-assisted macro and market analysis pipeline that delivers a
structured daily briefing — spanning macro indicators, rates and credit,
broad market ETFs, and AI-generated strategist commentary — directly to
Telegram, on a fully serverless cloud schedule.

---

## Overview

This project pulls data from multiple financial APIs each trading day,
synthesizes it into a structured report, generates AI-written market
commentary grounded strictly in that data, and delivers the result
automatically via Telegram — with no server, database, or manual execution
required.

It was built as a self-directed learning project with no prior
programming background, developed through iterative, AI-assisted
("vibe coding") development.

---

## What It Does

Each weekday morning, the bot automatically:

1. Fetches macro indicators (VIX, WTI crude, gold/copper, Treasury yields,
   high-yield credit spreads) from FRED and Yahoo Finance
2. Fetches a curated set of ETFs across three tiers — **Macro** (major
   indices, bonds, Bitcoin, geographic exposure), **Broad Industry**
   (GICS-style sector ETFs), and **Theme** (semiconductors, AI
   infrastructure, cybersecurity, and other thesis-driven baskets) — via
   the Alpaca Markets API
3. Sends this structured dataset to an LLM (Claude, with optional OpenAI
   support) operating under a defined "senior macro strategist" persona
   with an explicit analytical sequence and strict sourcing rules
4. Delivers both the raw data snapshot and the AI commentary to Telegram
   as separate, auto-splitting messages

---

## Architecture

┌─────────────┐ ┌──────────────┐ ┌───────────────┐
│ Data Layer │ ──▶ │ Analyst LLM │ ──▶ │ Telegram Bot │
│ FRED, Alpaca│ │ (Claude/GPT) │ │ Delivery │
│ yfinance │ │ │ │ │
└─────────────┘ └──────────────┘ └───────────────┘
▲
│
GitHub Actions
(scheduled, cloud)


**Tech stack:** Python 3.12 · GitHub Actions (cron scheduling) · FRED API ·
Alpaca Markets API (`alpaca-py`) · Yahoo Finance (`yfinance`) · Anthropic
Claude API · Telegram Bot API

---

## Data Sources

| Source | Data |
|---|---|
| **FRED** | 2Y/10Y Treasury yields, high-yield credit spread (OAS) |
| **Yahoo Finance** | VIX, WTI crude, gold, copper, USD/KRW exchange rate |
| **Alpaca Markets** | Daily price bars for 21 tracked ETFs across 3 tiers |
| **Anthropic Claude** | AI-generated strategist commentary |

---

## Project Structure
├── .github/workflows/
│ └── daily-dashboard.yml # Scheduled cloud automation (GitHub Actions)
├── src/
│ ├── main.py # Entry point — orchestrates the full run
│ ├── analyst.py # LLM prompt construction, guardrails, fallback logic
│ ├── macro.py # FRED + yfinance macro data fetching
│ ├── sectors.py # Alpaca ETF data fetching, 3-tier grouping
│ ├── dashboard.py # Formats fetched data into the Telegram message
│ └── telegram_bot.py # Message delivery, auto-splitting for length limits
├── requirements.txt
└── run.bat # Optional local execution shortcut

---

## Automation

The pipeline runs automatically on weekday mornings via a scheduled GitHub
Actions workflow. All credentials are managed through GitHub's encrypted 
repository secrets and injected as environment variables at runtime; 
nothing sensitive is ever committed to the repository.

To run manually instead of waiting for the schedule, the workflow also
supports on-demand triggering from the Actions tab.

---

## Sample Output (structure)

📊 Daily Market Dashboard
🗓 [Date]

🌡 MACRO SNAPSHOT

VIX, WTI, Gold/Copper, Treasury yields, HY OAS, USD/KRW

🌍 INDICES / BONDS / BITCOIN / GEOGRAPHY

DIA, SPY, QQQ, IWM, HYG, IBIT, EWY, EWJ, IEMG
(each with day/week/month % change)

🏭 BROAD INDUSTRY

XLE, XLF, XLV, XLI, XLY

🎯 THEME

SOXX, IGV, PAVE, ITA, DRAM, AIHY, BUG, NCLD

🧠 Analyst Comment
[AI-generated strategist note — macro read → index read → sector
composition → intraday flag (if relevant) → trend view → watch items]

---

## Notable Engineering Decisions

A few problems surfaced during development that required real
diagnosis rather than simple fixes — documenting them here since the
debugging process was as instructive as the build itself:

- **Data source migration under a discovered constraint.** Korean sector
  data was originally sourced from a Korean brokerage's Open API, which
  turned out to enforce IP-address whitelisting for security. GitHub
  Actions' ephemeral cloud runners use a different, non-fixed IP on every
  run, making that architecture fundamentally incompatible with serverless
  automation. Rather than reintroducing a persistent server, the Korean
  sector data was reworked to use a broad-market ETF proxy instead, keeping
  the automation fully serverless and free.

- **Dependency resolution under a hidden version conflict.** A legacy
  Alpaca SDK package worked fine in local ad-hoc testing but failed during
  a strict, from-scratch dependency install — surfacing a real conflict
  between two libraries' pinned `websockets` requirements. Resolved by
  migrating to Alpaca's actively maintained current SDK rather than
  patching around the outdated one.

- **LLM output grounded to provided data only.** The analyst's system
  prompt explicitly restricts it to reasoning over the data it's given,
  with an enforced analytical sequence (macro → index → sector composition
  → trend) and instructions to state uncertainty plainly rather than
  produce a confident but unsupported narrative.

- **Resilience over silent failure.** If the LLM call fails for any reason
  (rate limits, network issues, credential problems), the pipeline
  automatically falls back to a rule-based summary rather than failing the
  entire run — and the delivered message explicitly flags when this
  fallback was used, so degraded output is never mistaken for the full
  analysis.

- **Message-length handling.** Telegram enforces a 4096-character limit per
  message. Output is automatically split at clean paragraph or sentence
  boundaries when needed, so analysis is never silently truncated
  mid-thought.

---

## Disclaimer

This project is for personal informational and educational purposes. It
does not constitute investment advice, and the AI-generated commentary
should not be relied upon for actual trading or investment decisions.

---

## Background

Built entirely through iterative AI-assisted development, starting from no
prior programming experience — as a practice and test of how quickly a
production-grade (if small-scale) technical system could be designed,
debugged, and deployed by directing AI tools effectively rather than
writing code independently from scratch.
