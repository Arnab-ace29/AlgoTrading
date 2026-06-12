# AlgoTrading System — Master Plan

> **Purpose of this file:** Central index and executive summary of the entire system.
> Edit this file to track decisions, mark things done, and note what changed.
> Last updated: June 2026

---

## What We Are Building

A **modular, ensemble-ready intraday algorithmic trading system** for Indian markets (NSE equities, F&O, currency) using Upstox as the broker. The system starts with a rule-based momentum core in Phase 1 and incrementally adds ML, news sentiment, and LLM agents in later phases — without rewriting the core.

**Target:** Profitable intraday trading on NSE with backtested + walk-forward validated strategies, live execution, and a full React control panel dashboard.

### What We Build From Scratch vs What We Use Off-the-Shelf

> **Everything intelligent is built by us.** We only use external tools for two narrow purposes:

| Component | Built by us? | Notes |
|---|---|---|
| All signal logic (VWAP, RSI, mean rev) | ✅ 100% ours | `signals/technical/` |
| Feature engineering (80 features) | ✅ 100% ours | `features/indicators.py` |
| Ensemble aggregator | ✅ 100% ours | `ensemble/aggregator.py` |
| ML models (XGBoost, regime, RL) | ✅ 100% ours | `models/` + `signals/ml/` |
| RL agents (exit + entry) | ✅ 100% ours | `models/rl_*.py` |
| Backtesting engine | ✅ 100% ours (custom event-driven sim) | `backtest/engine.py` — vectorbt removed (June 2026) |
| Dashboard (React + FastAPI) | ✅ 100% ours | `dashboard/` |
| **Order routing to Upstox** | ❌ OpenAlgo middleware | SEBI requires Algo ID on every order — OpenAlgo handles this tagging + broker auth token refresh |
| **Candle/tick data feed** | ❌ Upstox Python SDK | Official free feed, no paid subscription needed |

**OpenAlgo is purely a compliance + execution pipe.** Think of it like a payment gateway — it sits between our code and the exchange, handles auth and regulatory tags, and we never touch it for any logic.

---

## Document Index

| File | What it covers |
|---|---|
| `MASTER_PLAN.md` | This file — index, decisions, status |
| `docs/ROADMAP.md` | Phase-by-phase build plan, week-by-week tasks, milestones |
| `docs/ARCHITECTURE.md` | Full system design, component map, repo file structure |
| `docs/DASHBOARD.md` | Complete dashboard spec — all pages, controls, API routes |
| `docs/DATA.md` | Data sources, SQLite schema, data pipeline, backfill |
| `docs/SIGNALS.md` | Every signal: formula, parameters, feature list, phase |
| `docs/SEBI_COMPLIANCE.md` | Regulatory requirements, compliance checklist, action items |
| `docs/IDEAS_ADVANCED.md` | Ideas bank: RL improvements, alpha signals, risk upgrades, research papers, Reddit/Twitter insights |
| `docs/KNOWN_ISSUES.md` | **Code audit & fix tracker** — every real bug/logic error/gap found, prioritized P0/P1/P2 with `file:line` |

---

## Core Architecture Decisions

> These are locked decisions. Change only with reason noted.

| Layer | Choice | Reason | Status |
|---|---|---|---|
| Broker | **Upstox** | Already have account, 0 brokerage on API trades | ✅ Locked |
| Order router | **OpenAlgo** (thin middleware only) | SEBI requires Algo ID on every API order — OpenAlgo handles this tagging, broker OAuth, and sandbox. We call its REST API from `live/openalgo_client.py`. We do NOT use its dashboard or logic. | ✅ Locked |
| Live + historical data | **Upstox Python SDK** | Free, WebSocket, official, no paid data feed | ✅ Locked |
| Data storage | **SQLite (WAL)** operational; DuckDB optional for analytics | SQLite-WAL supports concurrent cross-process readers + a single writer (runner writes while dashboard reads — LIVE-06), zero setup, file-based, no server. DuckDB kept for heavy ad-hoc OLAP only. | ✅ Migrated Jun 2026 (LIVE-06) |
| Backtesting | **Custom event-driven simulator** (was vectorbt) | vectorbt was misused (concatenated symbols/folds into one series) and fragile on Py3.13; replaced with a transparent bar-by-bar sim with intrabar fills, real sizing + costs, per-fold metrics | ✅ Rewritten Jun 2026 (BT-01..04) |
| Signal framework | **Custom BaseSignal** | Modular, extensible to ML/news/LLM without rewriting core | ✅ Locked |
| ML models | **XGBoost → PyTorch** | Industry standard for tabular data, proven in AI-trader | ✅ Locked |
| News NLP | **FinBERT** | Financial-domain BERT, free via HuggingFace | 📋 Phase 3 |
| LLM agents | **TradingAgents pattern** | Best multi-agent architecture, supports local Ollama | 📋 Phase 4 |
| Dashboard frontend | **React 19 + Vite + TypeScript + TailwindCSS + shadcn/ui** | Same stack as OpenAlgo, proven in production | ✅ Locked |
| Dashboard backend | **FastAPI** | Fast, async, Python, native SSE/WebSocket support | ✅ Locked |

---

## Phase Status Tracker

> **Honest status (June 2026 audit):** "Coded" means the file exists and imports — it does **not** mean wired, validated, or leak-free. See `docs/KNOWN_ISSUES.md` for the gap between what the docs describe and what actually runs. Several P0 items below must be fixed before any paper/live run is trustworthy.

| Phase | Name | Status | Target Start | Notes |
|---|---|---|---|---|
| **Phase 1** | Rule-Based Core | ⚠️ Logic validated; needs paper week | Week 1 | 3 technical signals + ensemble + sizer; all signal-correctness bugs fixed + tested — sizer (SIZE-01), regime bonus (AGG-01), mean reversion (SIG-01), NaN-safe features (FEAT-02), **session-anchored VWAP (FEAT-01)**, **UTC→IST session features (FEAT-03)** — and the walk-forward backtest engine rebuilt (BT-01..04) and extended to **SHORTs + next-bar-open fills (BT-05)**. PnL is now **net of Indian costs everywhere** with a **cost-aware entry filter** (PnL-02). Remaining before live: a paper-traded week on record (the execution P0s + the RL-entry P0 are now fixed). |
| **Phase 2** | ML + Multi-Strategy Portfolio | ⚠️ Logic fixed; live multi-leg exec pending | Week 5 | Regime detector wired into aggregator. Macro/Micro/Outcome gates in the runner; **ML leakage (ML-01..03), safe promotion (RETRAIN-01..02 + ML-05 refit-on-full), RL agents (RL-01..04 + RL-05 permissive-veto P0), and pairs/theta books incl. THETA-01 — all fixed + tested.** ML gates now only veto above a min OOS AUC (ML-04); micro train/serve timeframe aligned (ML-06); `evaluate()` made pure (ML-07). Pairs + Theta run as risk-gated parallel books (`ThetaBook`/`PairsBook`) with the cointegration-health false-halt fixed (PAIRS-01) and `statsmodels` installed (DEP-01). **Remaining: live multi-leg execution; full probability calibration; backtest portfolio realism.** |
| **Phase 3** | News & Options Flow | 🔲 Not started | Week 11 | FinBERT, NSE Announcements, PCR. `signals/news/`, `signals/options_flow/`, `data/nse_data.py` do not exist yet. |
| **Phase 4** | LLM + Auto Alpha | 🔲 Not started | Week 17 | TradingAgents, alphagen. `signals/llm/`, `signals/research/` do not exist yet. |
| **Pre-market screener** | Universe selection / watchlist | ✅ Built (June 2026) | — | `screener/` produces `config/daily_watchlist.json` via `scripts/run_screener.py`; runner reads it at startup. Cross-sectional ranking + catalysts, no look-ahead, unit-tested. Still needs nsepython constituents + a daily candle source + 09:00 scheduling (GAP-01). |
| **Dashboard** | React + FastAPI control panel | ✅ Functional + auth (June 2026) | — | Controls reach the runner via the `config/control.py` control plane (kill switch, auto-trade pause, weights). Live & AI Models pages rewired to real endpoints. **Roadmap** page tracks features. Mutating routes are token-authenticated (SEC-01, `DASHBOARD_TOKEN`). Still open: token OAuth exchange (TOKEN-01). |

---

## Target Markets — Strategy-Specific Universes

> **Decision (Jun 2026):** Separate universes per strategy. Each strategy trades only the stocks it's designed for. A daily pre-market screener ranks candidates within each universe and picks the top N for that day.

| Strategy Book | Universe | Size | Why |
|---|---|---|---|
| **Momentum / VWAP Breakout** | Nifty 50 only | 50 stocks | Liquidity is critical — tight spreads, instant fills, high volume for reliable VWAP |
| **RSI Momentum** | Nifty 50 + Nifty Next 50 | 100 stocks | Slightly broader, still liquid |
| **Mean Reversion** | Nifty 500 (F&O eligible subset) | ~200 stocks | More oversold/overbought extremes in mid-caps; must be F&O eligible for hedging |
| **Options Flow signals** | F&O eligible stocks only | ~200 stocks | Needs live option chain data — only available for F&O stocks |
| **ML macro model** | Nifty 200 | 200 stocks | Enough data per stock to train a reliable model |
| **News / FinBERT** | Any NSE stock with news | ~500 stocks | News can hit any stock; score only if news exists |
| **Pairs / Stat Arb** (Phase 3+) | Nifty 50 sector peers | ~15 pairs | Only co-integrated pairs tested in backtest |

### Daily Pre-Market Screener (runs at 9:00 IST)

Before market open, the screener ranks all stocks within each universe and selects the **top 10–15 highest-opportunity candidates** for the day. Only these are tracked live during the session.

**Ranking criteria (computed from previous day EOD + overnight data):**
```python
screener_score = (
    0.30 × technical_setup_score    # breakout proximity, volume surge, VWAP positioning
  + 0.25 × momentum_rank            # 5-day and 20-day return rank within universe
  + 0.20 × volume_surge_score       # yesterday's volume vs 20-day avg
  + 0.15 × volatility_opportunity   # ATR percentile: not too low, not too high
  + 0.10 × news_event_score         # any catalyst: earnings coming, bulk deal, FII buy
)
```

**Output:** A ranked watchlist written to `config/daily_watchlist.json` before market open.

**Why this matters:** A stock with a 0.70 signal score on a dull day with average volume is not the same as a 0.70 score on a stock with 3× volume and a catalyst. The screener surfaces the ones that actually have a reason to move.

### Position Sizing — How It Auto-Adjusts

Four layers stack together to determine final lot size for every trade:

| Layer | What it does | When active |
|---|---|---|
| **Score tier** | 1 lot (score 0.65–0.70), 2 lots (0.70–0.75), 3 lots (≥0.75) | Always (Phase 1+) |
| **Portfolio heat check** | Reduces size if total open risk already > X% of capital | Always (Phase 1+) |
| **Kelly multiplier** | Scales up/down based on rolling 20-trade win rate | After 20 trades |
| **RL Position Sizing Agent** | Learns context: VIX + regime + session PnL → optimal size | After 500 episodes (Phase 2+) |

Result: in a strong trending session with a hot win streak, it may enter 3 lots. After 3 consecutive losses in a choppy market, it may enter 0.5 lots (half position) automatically.

---

## Non-Negotiables (Anti-Patterns to Avoid)

- [ ] **No look-ahead bias** — features computed only from data available at bar close
- [ ] **No backtest overfitting** — walk-forward validation only, never optimize on test set
- [ ] **No skipping transaction costs** — model 0.05% slippage + STT + brokerage always
- [ ] **No jumping phases** — each phase must be profitable in live before starting the next
- [ ] **No black-box in live without SEBI RA registration** — white-box Phase 1 first
- [ ] **Kill switch always present** — `circuit_breaker.py` + OpenAlgo kill switch

---

## Critical Gaps Before Any Live (or Trustworthy Paper) Trading

> From the June 2026 code audit. Full detail with `file:line` in `docs/KNOWN_ISSUES.md`. These are the P0s — none of the "non-negotiables" above actually hold until these are fixed.
>
> **Update (2026-06-05 fix batch):** items 1–3, 5, 6, 7, and **8 (screener — now built)** are addressed — a `config/control.py` control plane wires the dashboard kill switch / pause / weights to the runner; the kill switch flattens + halts; exit-order failures are retried/escalated instead of dropping a live position; daily-loss is enforced proactively in the monitor; positions are reconciled from the DB on restart; the operational store was migrated **DuckDB→SQLite (WAL)** so the runner + dashboard can share the DB across processes (item 6); and the `screener/` module produces the daily watchlist. **Still open P0: 4 (fill reconciliation is best-effort only).** Live status of every fix is on the dashboard **Roadmap** page.

1. **Exit orders are fire-and-forget** (LIVE-01) — the book is marked flat even when the exit order fails, leaving live unmonitored exposure.
2. **Kill switch doesn't flatten or stop the loops** (LIVE-02) — it only blocks new entries; the "non-negotiable kill switch" is failing-open.
3. **No fill confirmation** (LIVE-03) — PnL is booked at signal price, not actual fill; `get_order_status` is never called.
4. **No reconciliation on restart** (LIVE-04) — positions open at crash time are orphaned forever.
5. **Daily-loss limit only checked at entry** (LIVE-05) — open-position losses can blow past the limit with nothing halting.
6. ~~**DuckDB connection shared across 3 threads, no lock** (LIVE-06)~~ — **DONE (2026-06-05):** operational store migrated to **SQLite (WAL)** with thread-local connections; supports concurrent cross-process readers + a writer (runner + dashboard share the DB). DuckDB now analytics-only.
7. **Dashboard controls don't reach the runner** (CTRL-01) — kill switch / weights mutate a different process. A control plane is the prerequisite for the kill switch to mean anything.
8. ~~**Screener doesn't exist** (GAP-01)~~ — **DONE (2026-06-05):** `screener/` builds the daily watchlist via `scripts/run_screener.py`; runner consumes it.

**Rule:** Do not paper-trade-for-record or go live until items 1–7 are `[FIXED]` in `KNOWN_ISSUES.md`. **All signal / backtest / ML / RL / strategy-logic issues from the June 2026 audit are now fixed + tested** — incl. session-anchored VWAP (FEAT-01), the backtest engine (BT-01..04), ML leakage + safe promotion (ML-01..03, RETRAIN-01..02), the RL agents (RL-01..04), and the pairs/theta books (THETA-01). Feed robustness is done (FEED-01/02), the live loop is event-driven (signals fire on bar close; kill switch reacts in ~1s), the operational store is SQLite-WAL so runner + dashboard share the DB across processes (LIVE-06), and dashboard mutations are authenticated (SEC-01). **What remains is mostly broker-dependent execution + infra:** broker-side OCO (the big one — stops at the exchange that survive a crash), full fill reconciliation (LIVE-03), live multi-leg execution for pairs/theta, and the OAuth code exchange (TOKEN-01).

---

## Key Reference Repositories

| Repo | URL | What we steal from it |
|---|---|---|
| AI-trader | https://github.com/aaryansinha16/AI-trader | 80-feature set, score formula, RL exit, tick backtest design |
| OpenAlgo | https://github.com/marketcalls/openalgo | Execution layer, broker integration, options tools, dashboard patterns |
| TradingAgents | https://github.com/TauricResearch/TradingAgents | Multi-agent LLM architecture (Phase 4) |
| alphagen | https://github.com/RL-MLDM/alphagen | RL-based auto alpha factor discovery (Phase 4) |
| vectorbt | https://github.com/polakowo/vectorbt | Backtesting engine |
| nsepython | https://github.com/aeron7/nsepython | Free NSE data (option chains, PCR, OI) |

---

## Decision Log

> Record every significant decision here with date and reason.

| Date | Decision | Reason |
|---|---|---|
| Jun 2026 | Start with Phase 1 rule-based, not full ML from day 1 | Easier to debug, faster to first live trade, solid foundation |
| Jun 2026 | Use OpenAlgo as execution layer, not raw Upstox SDK | SEBI compliance handled, Upstox already integrated, sandbox available |
| Jun 2026 | DuckDB over TimescaleDB | TimescaleDB requires PostgreSQL server, painful on Windows; DuckDB is a file. *(Superseded Jun 2026 for the operational store — see SQLite-WAL entry below; DuckDB stays optional for analytics.)* |
| Jun 2026 | Custom dashboard over Streamlit | Need full control: kill switch, signal sliders, live log, ML management |
| Jun 2026 | React 19 + FastAPI over Next.js | Aligns with OpenAlgo's proven stack; FastAPI for Python-native backend |
| Jun 2026 | Separate universes per strategy (not one fixed watchlist) | Each strategy type has different liquidity/data needs. Momentum needs Nifty 50 liquidity; mean reversion benefits from Nifty 500 extremes; options flow needs F&O-eligible stocks only |
| Jun 2026 | Daily pre-market screener to select top 10–15 candidates per universe | Focuses compute and capital on highest-opportunity stocks each day, not a static list |
| Jun 2026 | Full code audit; created `docs/KNOWN_ISSUES.md` and made the status tracker honest | A read-through found the docs describe an aspirational system that diverges from the running code: 8 P0 safety/execution bugs, signal/backtest/ML correctness errors, a missing screener, and controls that don't reach the runner. Tracking before fixing so nothing is lost. |
| Jun 2026 | Replaced vectorbt with a custom event-driven backtest simulator | vectorbt was being misused (all symbols/folds concatenated into one 1-D series → meaningless Sharpe) and is fragile on Python 3.13. The custom sim does intrabar SL/target fills at the stop price, real ATR sizing + Indian costs, and per-fold metrics — and is fully unit-tested. (BT-01..04) |
| Jun 2026 | Fixed ML training leakage + made model promotion safe | macro/micro/outcome models used a non-time-ordered split on symbol-concatenated frames + `bfill` (future leakage); retrain overwrote the live model with no held-out gate (and never even saved macro/micro). Added `models/validation.purged_split` (per-symbol chronological + embargo), removed all `bfill`, and `models/promotion.champion_challenger` (out-of-sample holdout, atomic promote-only-if-better). Verified with real xgboost. (ML-01..03, RETRAIN-01..02) |
| Jun 2026 | Fixed the RL exit/entry agents | Exit-agent journeys self-looped `next_state` (terminal reward never propagated) and only trained HOLD/final-EXIT; entry-agent state had 6/10 constant dims that mismatched live → unusable Q-table. Rebuilt journeys with proper TD backup + counterfactual EXIT/TIGHTEN rewards, reduced the entry state to dims reconstructable in both train and live, and stopped synthetic data from tripping the activation gate. (RL-01..04) |
| Jun 2026 | Pairs + theta integrated as parallel strategy books (not the ensemble) | A 2-leg market-neutral spread and a short straddle don't fit the single-symbol `[-1,1]` ensemble, so they run as their own books. `ThetaBook`/`PairsBook` finally consult `theta_risk`/`pairs_risk` (previously dead code) on every decision, and the THETA-01 delta-hedge sizing bug is fixed. Live multi-leg execution (option chain + futures hedge + 2-leg routing) is the remaining piece. |
| Jun 2026 | Session-anchored VWAP (FEAT-01) | VWAP was a rolling 78-bar window that bled across days; replaced with a per-trading-day cumulative VWAP (`_session_vwap`) feeding `vwap_dist_pct` + the VWAP bands, so the VWAP-breakout and mean-reversion signals match the spec. This was the last signal-correctness bug from the audit. |
| Jun 2026 | Feed robustness + event-driven signal loop (FEED-01/02) | Bars now force-close on a wall-clock timer (no lost quiet/EOD bars); the feed keeps an in-memory price cache with age so the monitor uses only fresh prices and alerts on stale feed instead of silently substituting entry price. The runner moved from a blind 30s sweep to processing symbols on bar-close events (60s fallback), so the kill switch reacts in ~1s. This is the foundation for scaling out and intraday re-screening. `upstox_client` import made lazy. |
| Jun 2026 | Paper / forward-testing is first-class | Clarified that "run the strategy on the LIVE feed with virtual money for the day" is paper/forward testing (distinct from the historical backtest), and it already exists via `PAPER_TRADE` (identical logic, fake fills, live-feed P&L, all-day, EOD square-off). Added a `mode` (PAPER/LIVE) tag on every trade so virtual results are isolated from real ones in the trade log + daily stats + API. Deferred: a dashboard button that spawns/stops the engine process (ops; run the runner via CLI, control pause/kill from the dashboard). |
| Jun 2026 | Dashboard auth (SEC-01) | Mutating routes (kill switch, mode/token writes, close-all, backtest run, weights/toggles, feature edits) now require `X-API-Key == DASHBOARD_TOKEN` via middleware; GETs stay open. Auth is off when the env var is unset (localhost dev) and the API warns. UI sends the key from localStorage. |
| 2026-06-07 | **Second independent audit + fix batch (profitability + reliability)** | A multi-agent re-read (7 module readers → adversarial verification) found issues the first audit missed, incl. a **P0**: the RL entry agent vetoed ~100% of entries once active (unseen Q-cell → SKIP). Fixed P0 + 15 more: net-of-cost PnL/Kelly/win-rate + a cost-aware entry filter (PnL-02); poll-to-terminal fill confirmation + partial-fill handling (LIVE-07); ML gates only veto above a min OOS AUC and centre on the training base rate (ML-04); promotion refits on full data after the gate (ML-05); micro train/serve timeframe aligned (ML-06); backtest now covers SHORTs + next-bar-open fills (BT-05); UTC→IST session features (FEAT-03); screener + pairs correctness; `statsmodels` installed. All unit-tested; full suite 87 passing (only the 2 broker-credential sandbox tests fail, env-only). See `docs/KNOWN_ISSUES.md` → "Second audit batch". |
| Jun 2026 | **Operational store migrated DuckDB→SQLite (WAL)** (LIVE-06) | DuckDB allows only one read-write process, so the runner and dashboard couldn't both hold the DB open — seeding required stopping the API, and the shared in-process connection had even segfaulted the dashboard under concurrent polling. Chose the scalable path (option 2): move the operational store to **SQLite in WAL mode** — concurrent cross-process readers alongside one writer, thread-local connections (`journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`). `data/db.py`'s public interface is unchanged (still DataFrames), so no caller changed; `data/schema.sql` retyped for SQLite. DuckDB is now optional, analytics-only. Proven by `scripts/test_concurrency.py` (writer process + concurrent reader, 0 lock errors, all cross-process writes visible) and by seeding demo data while the backend ran. |

---

## Open Questions / TODO

> Items that need a decision before or during implementation.

- [ ] What capital to start Phase 1 live trading with?
- [ ] Which Nifty 50 stocks to focus on for Phase 1? (High-liquidity candidates: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, AXISBANK, WIPRO, HINDUNILVR, BAJFINANCE)
- [ ] Intraday MIS or NRML product type for F&O positions?
- [ ] Target timeframe for backtesting: 1-min or 5-min candles as primary?
- [ ] SEBI RA registration — start process during Phase 2 or wait for Phase 3?

---

## Success Metrics

| Metric | Phase 1 Target | Phase 2 Target | Status (2026-06-07 backtest) |
|---|---|---|---|
| Walk-forward Sharpe | > 0.8 | > 1.2 | **−6.1** (non-WF, 3mo, risk-sized) — no edge yet (BT-EDGE) |
| Live win rate (NET) | ≥ 50% | ≥ 55% | 43% net |
| Max daily drawdown | < 2% capital | < 1.5% capital | 2.5% (small sample) |
| Model AUC (macro) | N/A | ≥ 0.58 | untrained (no real data pipeline yet) |
| Strategy coverage | 3 strategies | 5+ strategies | 3 (rule-based) |
| **Gross edge vs costs** | **must exceed ~16 bps/round-trip** | — | **1.15 bps gross — fails** |

> **Gate:** the system is infrastructurally ready but **not yet profitable** — the
> Phase-1 ensemble's gross edge (~1 bp of notional) does not clear Indian intraday
> costs (~16 bps round-trip). Finding/validating a cost-beating edge is the blocker
> before paper-for-record. See `docs/KNOWN_ISSUES.md` → "Empirical backtest finding".
