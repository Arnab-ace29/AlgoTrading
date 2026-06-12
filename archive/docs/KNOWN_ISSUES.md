# KNOWN ISSUES — Code Audit & Fix Tracker

> Consolidated tracker of real bugs, logic errors, and gaps found in the codebase.
> Created from a full read-through of every Python module (June 2026).
> This is the "what needs fixing" companion to `MASTER_PLAN.md`.
>
> **Status legend:** `[OPEN]` not started · `[WIP]` in progress · `[FIXED]` resolved · `[WONTFIX]` accepted
> **Priority:** **P0** = dangerous / blocks any live or reliable paper trading · **P1** = corrupts signals, backtest, PnL, or models · **P2** = robustness / hygiene
>
> Every item lists `file:line`, what's wrong, why it matters, and the fix direction. Line numbers are as of the audit and may drift — search the symbol if they don't match.

---

## Empirical backtest finding (2026-06-07) — the strategy has no cost-beating edge yet

After the second-audit fixes, real 5-min data (6 Nifty-50 names, ~57 trading days, Mar–Jun 2026, pulled via Yahoo) was run through the engine. **The infrastructure is correct, but the Phase-1 ensemble is not yet profitable:**

| Metric | 1-share sizing (old) | Risk-based sizing (SIZE-04) |
|---|---|---|
| Net PnL | +₹43 | **−₹2,425** |
| Sharpe | 0.46 | **−6.1** |
| Profit factor | 1.14 | **0.49** |
| Gross edge | — | **1.15 bps of notional** |
| Costs | — | **16.3 bps of notional** |

The "+₹43" under 1-share sizing was an artifact of trading ~1% of capital (costs negligible). Sized to risk (as live must be to make money), **costs are ~14× the gross edge** — the strategy generates ~1 bp of gross alpha per round trip and pays ~16 bps in costs. Trades also concentrate in correlated ranging names (ICICIBANK 33 trades / SBIN 17 → both net-negative; "death by stops + costs"). 71% of exits were SL hits, 26% targets — the 1.5×ATR SL / 2.5×ATR target structure is too tight for 5-min noise.

**This is the gating issue for profitability** (BT-EDGE). Caveats: small sample (58 trades), one regime, no walk-forward (needs ≥150 days of history), ML gates not applied in the backtest, yfinance data quality. But the direction is unambiguous and matches priors: simple VWAP/RSI/mean-reversion on liquid large-caps does not clear ~0.17% round-trip Indian intraday costs without a real selection edge. Fix the edge before any paper-for-record / live. Levers: cost-aware trade selection (fewer/higher-conviction), exit-structure tuning to the timeframe, correlation/sector guard, regime filter, and training+calibrating the ML gates (whose entire purpose is to filter for win-probability).

---

## Backlog — to build next (profitability · validation · reliability · dashboard)

Tracked work items, opened 2026-06-07. These are the path from "infrastructure ready"
to "profitable + reliable". Priority is **edge first** (EDGE-/ML-/BT-) — nothing else
matters until the backtest is net-positive after costs (BT-EDGE). IDs are referenced
as checkpoints in `docs/ROADMAP.md` → "Phase 0 — Make It Profitable".

### Pre-work / prerequisites (do before the Phase-0 build)

| ID | Pri | One-line |
|---|---|---|
| COST-01 | P1 | **Verify the cost model.** The whole profitability verdict rests on ~16 bps round-trip (`analytics/costs.py`). Confirm brokerage/STT/exchange/SEBI/stamp/GST against the actual Upstox plan + current 2026 rates, and set realistic slippage for the traded names. Lower real costs → lower edge bar. |
| DEC-01 | P1 | **Resolve the open questions** (MASTER_PLAN): starting capital, MIS vs NRML, primary timeframe, SEBI RA timing. These now drive risk-based sizing directly. |
| DOC-01 | P2 | **Spec the new dashboard pages in DASHBOARD.md** (DASH-01/02/04/05) — fix the API routes + payloads before building. |
| ENV-01 | P2 | **Pin a reproducible env.** `pyproject` says Python ≥3.11 but the venv is 3.9.6; xgboost needs `libomp` (no brew). Rebuild on a declared interpreter, add `statsmodels`, document the one-command setup + run command. |
| CONV-01 | P2 | **Document the UTC-store / IST-session convention** (FEAT-03, DB-TZ) so the DATA-01 pipeline follows it; segregate or clear demo data so it never mixes with real. |
| SHORT-01 | P2 | **Confirm intraday shortability / borrow** on the equity universe — the backtest now trades shorts and assumes any name is shortable (MIS). |

### Edge / profitability (the gate: BT-EDGE)

| ID | Pri | One-line |
|---|---|---|
| EDGE-01 | P1 | **Cost-aware trade selection.** At ~16 bps round-trip the conviction bar must clear costs: raise/recalibrate the score threshold, cap trades-per-symbol-per-day, and tighten `is_cost_effective` (require target move ≫ costs). Stop the ICICIBANK/SBIN overtrading. |
| EDGE-02 | P1 | **Exit structure tuned to the 5-min timeframe.** 71% of exits were stop-hits (1.5×ATR SL too tight for 5-min noise). Test wider SL / faster trailing / partial profit-taking / time-stop — validate OUT-OF-SAMPLE, do not curve-fit this quarter. |
| EDGE-03 | P1 | [BUILT] **Correlation / sector guard** — `risk/correlation_guard.py`: sector cap (max 2/sector, configurable) + optional return-correlation cap, wired into the runner entry path so the book can't stack into one sector/cluster. (`test_correlation_guard.py`) |
| EDGE-04 | P2 | **Regime filter for entries.** Don't run momentum signals in a ranging/choppy name; gate entries on the regime detector (it already exists) rather than only re-weighting. |
| EDGE-05 | P2 | **Real opening-range-breakout signal.** The `orb`/`first_30m` feature is mislabeled (rolling 6-bars-ago window, not the session open range — see FEAT note). Build a session-anchored ORB; it's one of the few intraday edges that historically clears costs. |
| ML-08 | P1 | **Train + calibrate the ML gates.** Their purpose is to filter for win-probability, but they need a real training-data pipeline (only demo data exists today) and `CalibratedClassifierCV` (isotonic/Platt) so the 0.45/0.55 cutoffs map to real precision. Extends cross-cutting §10. |
| EDGE-06 | P1 | **Index / sector-breadth confirmation.** Today each stock is traded in isolation — no index or cross-constituent context. (a) *Now (data-free):* compute banking-sector breadth (fraction of banks above VWAP / with positive momentum) from the banks already tracked, and gate bank entries on sector alignment — "trade with the sector, not a lone correlated name". Optionally subscribe to NIFTY BANK (the index key already exists in `INSTRUMENT_KEYS`) for its trend directly. Composes with EDGE-03 (sector guard) + EDGE-04 (regime filter). (b) *Later (F&O):* trade Bank Nifty itself off constituent breadth/lead-lag — needs the pending multi-leg execution. |

### Validation harness

| ID | Pri | One-line |
|---|---|---|
| BT-06 | P1 | [BUILT] **Per-day EOD square-off in the backtest** — positions force-close at the IST session end and never fill/hold across a session boundary, matching the strictly-intraday live runner (`engine._simulate`, `test_backtest`). |
| BT-07 | P1 | [PARTIAL] **Walk-forward auto-windowing** — `run(walk_forward=True)` now auto-fits train/test to the available span so it runs on short histories (engine done). **Still needs** a daily/EOD source + ≥150 days for trustworthy folds (depends on DATA-01). |
| BT-08 | P2 | **Portfolio-realism backtest** — shared capital + `max_concurrent_positions` + `portfolio_heat_limit` across symbols on a unified timeline (today each symbol is isolated with full capital). Extends cross-cutting §11. |
| TEST-LEAK | P2 | **Automated leakage assertion in CI** — assert every feature at bar `t` uses only data ≤ `t`. Extends cross-cutting §7. |

### Reliability / execution

| ID | Pri | One-line |
|---|---|---|
| OCO-01 | P1 | **Broker-side OCO / bracket orders** so SL/target live at the exchange and survive a runner crash (the root reliability win behind LIVE-01/02/04). Extends cross-cutting §2. |
| DATA-01 | P1 | **Real data pipeline** — index constituents (nsepython) for the screener universe, a daily/EOD candle source, and scheduled backfill; today the DB holds only demo data. Prerequisite for ML-08, BT-07, the screener (GAP-01 leftovers). |
| WATCH-01 | P2 | **Feed/loop watchdog + heartbeat** — detect a dead websocket, stalled main loop, or crashed monitor thread. Extends cross-cutting §5. |
| TOKEN-01 | P1 | (already tracked) Exchange the OAuth code for a token server-side instead of storing the raw code. |

### Dashboard (make tracking + simulation easier)

> **Built 2026-06-07:** a new **Analytics** page + `/api/analytics/*` route ship DASH-02/03/04/05 (and DASH-08's mode toggle). Remaining: DASH-01, DASH-06, DASH-07.

| ID | Pri | Status | One-line |
|---|---|---|---|
| DASH-02 | P1 | [BUILT] | **Gross-vs-net-vs-cost decomposition** — "Edge vs Costs" panel shows gross bps vs cost bps with a clear EDGE/NO-EDGE verdict (`Analytics.tsx`, `/analytics/summary`). |
| DASH-03 | P2 | [BUILT] | **Per-trade R-multiple distribution** (histogram) + avg/expectancy R (`/analytics/r-multiples`). |
| DASH-04 | P1 | [BUILT] | **"What-if" simulator** — re-price the trade log under cost-multiplier / min-score / target-only assumptions, no engine re-run (`/analytics/whatif`). |
| DASH-05 | P1 | [BUILT] | **Data-health / coverage panel** — bars per symbol/timeframe/source, freshness, demo-vs-real flag (`/analytics/data-health`). |
| DASH-08 | P2 | [BUILT] | **PAPER/LIVE/ALL mode toggle** on the Analytics page (the `mode` tag in `trade_log`). |
| DASH-01 | P1 | [OPEN] | **Backtest Lab page** — run from the UI (date range / symbols / risk profile / threshold sliders); equity curve + per-fold metrics + breakdowns. (Backend `/backtest/run` already exists.) |
| DASH-06 | P2 | [OPEN] | **Model-edge panel** — per ML gate: trained?, OOS AUC, base rate, reliable-vs-advisory (cleared `ML_GATE_MIN_AUC`?). |
| DASH-07 | P2 | [OPEN] | **Live risk gauges** — session net PnL vs daily limit, portfolio heat vs cap, open positions vs max, kill-switch/pause state. |

---

## Fixed in the second audit batch (2026-06-07)

A fresh independent multi-agent re-read (7 module-cluster readers → adversarial
per-finding verification) surfaced issues the first audit missed — including a **P0**
that would have silently halted live trading. All fixed + unit-tested:

- **RL-05 (P0) — the entry agent vetoed ~100% of entries once active.** A tabular
  Q-table over a ~1.2M-cell state space activates after ~25 trades, so almost every
  live state is an unseen cell; an all-zero cell argmaxes to SKIP, so enabling the
  agent silently stopped nearly all trading. Fix: `should_enter` is now **permissive
  on unseen/unlearned cells** (falls back to the rule-based system) and only vetoes a
  cell it has *learned* is a loser; activation counts real ENTER decisions, not the
  doubled decision-dict count. (`scripts/test_rl_agents.py`)
- **PnL-02 (P1) — PnL was gross everywhere it mattered.** `trade_log.pnl` is gross,
  and win/loss, Kelly inputs, the win-rate metric and the live `_session_pnl`/daily-loss
  rail all keyed off it, so a gross-positive but cost-negative trade counted as a win
  (over-sizing Kelly, halting the day too late). Fix: store `cost`+`net_pnl` per trade;
  classify and size on **net**; accumulate net into `_session_pnl`; plus a **cost-aware
  entry filter** (`is_cost_effective`) that skips setups whose target can't clear
  round-trip costs. (`scripts/test_net_pnl.py`)
- **LIVE-07 (P1) — orders booked on "accepted", not "filled".** `place_order` now
  polls to a terminal state (catching post-accept rejections), returns `filled_qty`/
  `avg_price`, and the runner books the real filled qty and retries partial exits
  instead of popping a position with shares still live. (`scripts/test_fill_confirmation.py`)
- **ML-04/05/06/07 (P1/P2) — ML gates could veto with no edge, ship stale models,
  serve on the wrong timeframe, and corrupt the champion.** A model now only vetoes
  after clearing `ML_GATE_MIN_AUC` (0.53) out-of-sample; the macro gate centres on the
  training base rate (kills the anti-LONG bias of a 0.50 cut on an imbalanced label);
  promotion refits on the full window after the gate and never degrades to an in-sample
  comparison; the micro model trains+serves on 5-min; `evaluate()` is pure.
  (`scripts/test_ml_gate_edge.py`)
- **BT-05 (P1) — the backtest only validated longs and entered at the signal bar's
  close.** It now simulates SHORTs (the runner trades them), fills at the **next bar's
  open**, and applies the same cost filter as live. (`scripts/test_backtest.py`)
- **FEAT-03 (P1) — session features assumed IST but candles are stored UTC**, so
  `time_norm` spanned only ~0–0.12 and "session open" was detected at 14:45 IST. All
  session-relative features + the RL `time_of_day` now convert to IST.
  (`scripts/test_session_tz.py`)
- **SCR-01..04, PAIRS-01/02, DEP-01** — screener volume-surge self-baseline, clamped-away
  event-risk penalty, +inf-return-from-zero-close, CSV parsing; pairs false-halt on
  data gaps and self-included z-score; and the missing `statsmodels` dependency.
  (`scripts/test_screener.py`, `scripts/test_pairs_fixes.py`)

---

## Fixed in the June 2026 batch

These landed on 2026-06-05 (also tracked live on the dashboard **Roadmap** page):

`CTRL-01` control plane (`config/control.py` — dashboard writes intents, runner polls) · `CTRL-02` kill-switch API body · `LIVE-01` exit-order failure handling (retry + escalate, never drop a live position) · `LIVE-02` kill switch flattens + halts · `LIVE-03` best-effort fill-price confirmation · `LIVE-04` position reconciliation on restart · `LIVE-05` proactive daily-loss halt in the monitor · `SIZE-01` sizer can stand down to 0 lots · `AGG-01` regime bonus can't flip sign · `AGG-02` normalize over contributing weights · `SIG-01` mean reversion only at extremes · `FEAT-02` NaN-safe feature reads (`signals/base.feat`) · `PnL-01` Indian transaction-cost model (`analytics/costs.py`) · blackout-window arithmetic · `TAG-01` consistent strategy tag · `UI-01` Live + AI Models pages rewired to real endpoints · `UI-02` backtest run persistence · `UI-03` equity-curve field · plus auto-trade pause, models-status API, and the Roadmap/feature-tracker page.

Also shipped: `GAP-01` (pre-market screener — `screener/` + `scripts/run_screener.py`); `BT-01..04` (backtest engine rewritten as a custom event-driven simulator — `backtest/engine.py`, vectorbt removed); `ML-01..03` (leakage-safe per-symbol purged splits + no bfill — `models/validation.py`); `RETRAIN-01..02` (champion/challenger promotion with out-of-sample holdout — `models/promotion.py`); `LIVE-06` (operational store migrated DuckDB→SQLite WAL — concurrent cross-process readers + writer; `data/db.py`, `data/schema.sql`); runtime fixes found during dashboard fire-up (missing `ta` dep, NaN-in-JSON, lazy backtest import).

Also shipped: `RL-01..04` (exit-agent TD backup + EXIT/TIGHTEN training, entry-agent state consistency + reconstructed context, digitize clamp — `models/train_rl_on_journeys.py`, `rl_*_agent.py`).

Also shipped: `THETA-01` (delta-hedge sizing) + pairs/theta integrated as risk-gated strategy books (`ThetaBook`/`PairsBook`).

Also shipped: `FEAT-01` (session-anchored VWAP — `features/indicators._session_vwap`).

Every signal / backtest / ML / RL / strategy-logic issue from the audit is fixed; the feed is robust + event-driven (FEED-01/02); dashboard mutations are authenticated (SEC-01). What's left is mostly broker-dependent execution + infra: **broker-side OCO** (the big reliability win — LIVE-01/02/04 root cause), `LIVE-03` full fill reconciliation, `TOKEN-01` (OAuth code exchange), live multi-leg execution for pairs/theta, and short-side / next-bar-open fills in the backtest. (`LIVE-06` — the runner+dashboard-on-one-DB blocker — is now resolved: the operational store is SQLite in WAL mode, which supports concurrent cross-process readers + a writer.)

---

## How to use this file

1. Fix **P0** before any further paper or live trading — several of these can lose real money silently.
2. Fix **P1** before trusting any backtest number, model AUC, or live PnL figure.
3. When you fix an item, flip its status to `[FIXED]` and note the commit.
4. New issues go in the right priority section with a new ID.

---

## Issue Index

### Second audit (2026-06-07) — found by an independent multi-agent re-read

| ID | Pri | Status | One-line |
|---|---|---|---|
| SIZE-04 | **P1** | [FIXED] | Cash-equity sizing traded **1–3 shares** (F&O lot model with `lot_size=1`) → ~1% of capital/trade, costs dominate. Now **risk-based**: shares = per-trade risk budget × conviction ÷ stop distance; F&O keeps the lot model (`position_sizing.size`) |
| BT-EDGE | — | [OPEN] | **Empirical:** on 3mo real 5-min data the Phase-1 ensemble shows ~no gross edge (1.15 bps of notional vs 16.3 bps costs) → net −2.4%. Engine is correct/look-ahead-free; the **strategy lacks a cost-beating edge**. See "Empirical backtest" below. |
| DB-TZ | P2 | [FIXED] | `read_candles` crashed on a `timestamp` column mixing tz-aware (real backfill) + naive (demo seed) ISO; now parsed as UTC (`db.read_candles`) |
| RL-05 | **P0** | [FIXED] | Activated entry agent vetoed ~100% of entries (unseen Q-cell → SKIP); now permissive on unseen/unlearned cells + activation counts real ENTERs (`rl_entry_agent.should_enter`) |
| RL-06 | P1 | [FIXED-DOC] | Exit agent trained daily but never wired into live exits; documented as trained-but-inactive with the guards required before activation (`rl_exit_agent` docstring) |
| PnL-02 | P1 | [FIXED] | Win/loss, Kelly, win-rate and live `_session_pnl`/daily-loss halt now use NET (cost-adjusted) pnl; `trade_log.net_pnl`+`cost` stored; cost-aware entry filter added (`db.log_trade_close`, `pnl_tracker._net_series`, `runner._exit_position`, `costs.is_cost_effective`) |
| LIVE-07 | P1 | [FIXED] | `place_order` polled to a terminal state (catches post-accept rejection); `OrderResult` carries `filled_qty`/`avg_price`; runner books real fills + handles partial exits (`openalgo_client`, `runner`) |
| ML-04 | P1 | [FIXED] | A model may VETO only after clearing a min OOS AUC bar (`ML_GATE_MIN_AUC`); macro gate centred on training base rate, not a hard 0.50 (`macro/micro/strategy_outcomes`, `runner._passes_ml_gates`) |
| ML-05 | P1 | [FIXED] | Promotion refits the challenger on the FULL window before shipping (no freshest-data starvation); a too-short holdout keeps the champion instead of an in-sample comparison (`promotion.champion_challenger`) |
| ML-06 | P1 | [FIXED] | Micro model trained on 1-min but served on 5-min (train/serve skew); now trains + serves on 5-min, 6-bar horizon (`micro_model`, `retrain_daily.load_micro_data`) |
| ML-07 | P2 | [FIXED] | `evaluate()` mutated the live model's `feature_columns` (corrupted the champion); now snapshots/restores + scores strictly on trained columns (`macro/micro_model.evaluate`) |
| BT-05 | P1 | [FIXED] | Backtest was long-only and entered at the signal bar's close; now simulates SHORTs too, fills at the NEXT bar's open, and applies the cost filter (`backtest/engine._simulate`) |
| FEAT-03 | P1 | [FIXED] | Session features (time_norm, session_open, day_of_week, expiry) + RL time_of_day assumed IST but candles are stored UTC; now converted to IST (`indicators._ist_index`, `runner._build_entry_state`) |
| SCR-01 | P2 | [FIXED] | `volume_surge` baseline excluded the current bar (was self-damping) (`ranking_features.compute_metrics`) |
| SCR-02 | P2 | [FIXED] | Catalyst event-risk suppression (−0.3) was clamped to 0; now clamps to [−0.3,1] so event-risk names rank below neutral (`ranking_features.screener_score`) |
| SCR-03 | P2 | [FIXED] | A zero interior close gave a +inf return that ranked top; any non-positive close (and non-finite return) now rejects the symbol (`ranking_features.compute_metrics`) |
| SCR-04 | P2 | [FIXED] | `--strategies` CSV is stripped + empties dropped; unknown strategy warns instead of silently defaulting (`run_screener`, `universe.universe_for_strategy`) |
| PAIRS-01 | P1 | [FIXED] | Pairs health check returned tri-state — an un-testable day (data gap/holidays) no longer counts toward the halt streak; window widened to 150d (`pairs_risk`) |
| PAIRS-02 | P2 | [FIXED] | Pairs z-score now measured against the prior window (current bar excluded), so a true divergence crosses entry/stop instead of self-damping (`pairs_signal.compute_zscore`) |
| DEP-01 | P1 | [FIXED] | `statsmodels` (cointegration dep) was declared but not installed → all pairs math crashed at runtime; installed into the venv |

> **Refuted by adversarial verification (NOT bugs):** the champion AUC is genuinely out-of-sample (the promoted artifact only ever carries an older fit slice, not the full window) and the outcome-model entry-feature reconstruction does not look ahead (the in-progress bar is never persisted, and `entry_time` is wall-clock-after-close). Two claims were withdrawn after a verifier read the exact data lineage.

### First audit (2026-06-05/06)

| ID | Pri | Status | One-line |
|---|---|---|---|
| LIVE-01 | P0 | [FIXED] | Exit failure retries w/ backoff + escalates to broker close-all; never pops a live position (`runner._exit_position`) |
| LIVE-02 | P0 | [FIXED] | Kill switch flattens all positions + halts entries via the control plane (`runner._flatten_all`) |
| LIVE-03 | P0 | [FIXED] | Best-effort fill-price confirmation books PnL at the actual fill (`runner._confirm_fill_price`); full partial-fill reconciliation still pending |
| LIVE-04 | P0 | [FIXED] | Open trades adopted from the DB on startup (`runner._reconcile_open_positions`) |
| LIVE-05 | P0 | [FIXED] | Monitor halts + flattens the moment session PnL breaches the daily limit, independent of entries |
| LIVE-06 | P0 | [FIXED] | Operational store migrated DuckDB→SQLite (WAL) — concurrent cross-process readers + writer; DuckDB now analytics-only |
| CTRL-01 | P0 | [FIXED] | JSON control plane the runner polls each loop (`config/control.py`) — kill/pause/weights reach live trading |
| CTRL-02 | P1 | [FIXED] | Kill-switch endpoint accepts `{active}` and writes the control plane (no more 422) |
| SIZE-01 | P1 | [FIXED] | Sizer can stand down to 0 lots — the `max(1,…)` floor removed from the de-risking layers |
| SIZE-02 | P1 | [FIXED] | Score→lots bands now match SIGNALS.md (0.65/0.70/0.75 tiers, 0.55–0.65 no-trade, CHOPPY 1-lot stand-down) via `config.SCORE_TIER_*` |
| SIZE-03 | P1 | [FIXED] | Kelly layer wired into the runner + multiplier normalized so it scales instead of zeroing every trade |
| AGG-01 | P1 | [FIXED] | Regime bonus scales magnitude in the composite's direction — can no longer flip sign |
| AGG-02 | P1 | [FIXED] | Composite normalized over contributing weights — a failed signal can't re-weight the ensemble |
| SIG-01 | P1 | [FIXED] | Mean reversion gated on genuine extremes (BB/RSI/z-score), not any `bb_pct_b != 0.5` |
| FEAT-01 | P1 | [FIXED] | "VWAP" is a rolling 78-bar window, not session-anchored (spec says reset 9:15) |
| FEAT-02 | P1 | [FIXED] | `signals/base.feat()` is NaN-safe — legitimate 0.0 readings preserved, not coerced to default |
| BT-01 | P1 | [FIXED] | Walk-forward folds + symbols concatenated into one series → invalid equity/Sharpe |
| BT-02 | P1 | [FIXED] | SL/target checked on close only; fills at close, not at stop/target price |
| BT-03 | P1 | [FIXED] | Real position sizing discarded; vectorbt uses flat 5% size mislabeled as "risk" |
| BT-04 | P1 | [FIXED] | Per-fold metrics promised but never computed (`fold_results` unused) |
| ML-01 | P1 | [FIXED] | XGBoost split on symbol-concatenated frame → "time-ordered" split isn't time-ordered |
| ML-02 | P1 | [FIXED] | Strategy-outcome model uses shuffled/stratified split on time series (leakage) |
| ML-03 | P1 | [FIXED] | `bfill()` in ML feature prep can pull future values backward |
| RL-01 | P1 | [FIXED] | HOLD transitions back up to the next bar's state (proper TD); terminal reward propagates |
| RL-02 | P1 | [FIXED] | Each bar emits HOLD / EXIT_NOW / TIGHTEN_SL transitions — all three actions learned |
| RL-03 | P1 | [FIXED] | Entry-agent state keyed only on dims reconstructable in train+live; constant dims dropped |
| RL-04 | P2 | [FIXED] | `np.digitize(...) - 1` wraps out-of-range low values to the top bucket |
| THETA-01 | P1 | [FIXED] | Delta-hedge lot sizing is dimensionally wrong (treats per-unit delta as lot count) |
| THETA-02 | P2 | [FIXED] | `vix_to_lots` now sizes from the configured `vix_floor/full_size/ceiling/panic` (added `vix_full_size`); defaults reproduce the old bands |
| PnL-01 | P1 | [FIXED] | Indian intraday cost model applied; daily stats report gross, costs, net (`analytics/costs.py`) |
| RETRAIN-01 | P1 | [FIXED] | Retrain overwrites live model in place with no AUC gate or atomic swap |
| RETRAIN-02 | P1 | [FIXED] | Retrain "old vs new AUC" is in-sample on training rows — optimistic, not held-out |
| FEED-01 | P1 | [FIXED] | Last bar of a quiet period never flushes — no wall-clock bar-close timer |
| FEED-02 | P1 | [FIXED] | Missing LTP falls back to `entry_price` → SL/target silently never trigger |
| SEC-01 | P1 | [FIXED] | No auth on any dashboard route, including kill switch, mode switch, token write |
| SEC-02 | P2 | [FIXED] | API key sent once (JSON body only); dropped the `x-api-key` header and redacted from `raw_response` |
| TOKEN-01 | P1 | [OPEN] | Dashboard `/token` stores the raw OAuth code as if it were an access token |
| UI-01 | P1 | [FIXED] | Live + AI Models pages rewired to real endpoints (status/scan/positions/control, models/status) |
| UI-02 | P2 | [FIXED] | Completed backtests persisted to `backtest_runs`; history panel populates |
| UI-03 | P2 | [FIXED] | Equity-curve API returns `equity` in chronological order; Overview chart renders |
| TAG-01 | P2 | [FIXED] | Entry + exit orders tag with the canonical strategy id used in the trade log |
| GAP-01 | P0 | [FIXED] | `screener/` module (the whole pre-market watchlist flow) does not exist |
| GAP-02 | P2 | [OPEN] | ~11 other documented modules / dirs missing (see Doc↔Code section) |
| TEST-01 | P2 | [FIXED] | The 3 model smoke-tests rewritten with real assertions (valid AUC, predictions vary, persistence round-trip) + pytest-collectable + temp model paths |

---

## P0 — Dangerous / Blocks Trading

### LIVE-01 · Exit order failure is silently ignored — **[FIXED 2026-06-05]**
_Fixed: `runner._exit_position` only books closed on a confirmed order; on failure the position is kept and retried with backoff, escalating to `close_all_positions` after 3 tries._
`live/runner.py:404-422` — `_exit_position()` calls `place_order(...)` then unconditionally `log_trade_close()` and `_open_positions.pop(trade_id)` **regardless of `order.success`**. The order id falls back to `""` on failure but the position is still removed from the book and PnL is recorded.
**Why it matters:** If the exit order times out or is rejected, the system believes it is flat while still holding a live, now-unmonitored position. This is the single most dangerous accounting bug.
**Fix:** Only mark closed after a confirmed fill (see LIVE-03). On exit failure: retry with backoff, escalate to `close_all_positions`, and alert — never pop the position on a failed order.

### LIVE-02 · Kill switch doesn't flatten or stop the loops — **[FIXED 2026-06-05]**
_Fixed: `runner._apply_control_state` calls `_flatten_all("KILL_SWITCH")` and halts entries; the control plane reacts in ~1s._
`risk/circuit_breaker.py:67-71` + `live/runner.py` — `trigger_kill_switch(True)` only makes `allow_entry()` return False. The monitor thread and signal loop keep running and **open positions are never force-closed**; `close_all_positions()` is defined on the client but never called by the kill path.
**Why it matters:** A "kill switch" that leaves live exposure open and loops running is failing-open in the way that matters most.
**Fix:** Kill switch must (1) set the flag, (2) call `close_all_positions()`, (3) cancel pending orders, (4) stop the signal loop. Wire it to the *running* runner instance (see CTRL-01).

### LIVE-03 · No fill confirmation — PnL is fictional — **[FIXED (best-effort) 2026-06-05]**
_Fixed: `runner._confirm_fill_price` polls order status and books PnL at the actual fill when available. **Still pending:** poll-until-terminal + partial-fill reconciliation (the deeper order-lifecycle work)._
`live/runner.py:225,409` + `live/openalgo_client.py:143` — `place_order` returns success as soon as OpenAlgo *accepts* the market order. The runner immediately books the position at the last candle close and books exit PnL at the monitor's LTP. `get_order_status` exists but is **never called**; there is no average-fill-price reconciliation and no partial-fill handling.
**Fix:** After placing, poll `get_order_status` until terminal; record actual fill price/qty; handle partials and post-accept rejections; book PnL on real fills.

### LIVE-04 · No position reconciliation on restart — **[FIXED 2026-06-05]**
_Fixed: `runner._reconcile_open_positions()` adopts open DB trades on startup, before the loop, so a crash-time position is monitored + squared off._
`live/runner.py` — `_open_positions` starts empty on every boot. `get_open_trades()` (DB) and broker `get_positions()` are never used to rehydrate state.
**Why it matters:** Any position open at crash/restart is orphaned — never monitored, never squared off.
**Fix:** On startup, reconcile in-memory book against broker positions + open DB trades before the loop starts; adopt or flatten orphans.

### LIVE-05 · Daily-loss limit only enforced at entry — **[FIXED 2026-06-05]**
_Fixed: the monitor halts + flattens the moment `_session_pnl` breaches the daily limit, independent of any entry attempt (`runner.py:586-592`)._
`live/runner.py:201` + `risk/circuit_breaker.py` — the daily-loss halt is evaluated only on the entry path. Losses accruing purely from open positions hitting stops can push `_session_pnl` well past `-daily_loss_limit` with nothing halting the session.
**Fix:** Add a proactive monitor tick that halts and flattens the moment `_session_pnl` breaches the limit, independent of any entry attempt.

### LIVE-06 · DuckDB shared connection — **[FIXED 2026-06-05 — migrated to SQLite WAL]**
A single module-global DuckDB `_conn` was used concurrently by multiple threads. This was not theoretical — it **segfaulted the dashboard** (exit 139) under normal concurrent React-Query polling, because uvicorn dispatches each sync route to a threadpool worker that hit the one connection at once. The deeper problem was cross-process: DuckDB allows only one read-write process, so the dashboard API and the live runner could not both hold the file open at once (seeding required stopping the API).
**Fix (chosen: operational store off DuckDB — option 2, the scalable path).** The operational store is now **SQLite in WAL mode** (`data/db.py`, `data/schema.sql`). WAL allows **concurrent readers alongside a single writer across processes**, so the runner can write trades/candles while the dashboard reads them live. Connections are **thread-local** (`threading.local`), each opened with `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`. The public `data/db.py` interface is unchanged (still returns DataFrames), so no caller changed. DuckDB is now **optional, analytics-only** (heavy ad-hoc OLAP), not on the operational path.
**Verified:** `scripts/test_concurrency.py` — a separate writer **process** inserts 60 trades while this process reads concurrently: 0 lock errors across 70 reads, all 60 cross-process writes visible (5/5). Demo data was also seeded **while the backend was running** with no lock error — the exact scenario DuckDB could not support.

### CTRL-01 · Dashboard controls don't reach the live runner — **[FIXED 2026-06-05]**
_Fixed: `config/control.py` is a JSON control plane the runner polls each loop; the API writes intents and the runner applies kill/pause/weights/toggles. The runner owns trading state._
`dashboard/api/routes/system.py` + `signals.py` instantiate their **own** `CircuitBreaker()` and `EnsembleAggregator()` at import. `live/runner.py:78-80` creates its own separate instances. There is no shared store or IPC.
**Why it matters:** Toggling the kill switch, editing weights, or enabling/disabling signals from the dashboard changes only the API process's objects and has **zero effect on live trading** — the controls look like they work but don't.
**Fix:** A shared control plane: a DB control table (or file) the runner polls each loop, or a small IPC/queue. The runner is the single owner of trading state; the API writes intents, the runner reads and applies them.

### GAP-01 · The screener module does not exist — **[FIXED 2026-06-05]**
`screener/` is now built: `universe.py` (named universes + strategy map, JSON-overridable), `ranking_features.py` (pure-numpy ranking metrics + the documented 0.30/0.25/0.20/0.15/0.10 score formula, no look-ahead), `catalyst_detector.py` (optional earnings/bulk-deal/FII catalysts), and `daily_screener.py` (loads EOD candles — resampling intraday when no daily series exists — ranks each universe, writes `config/daily_watchlist.json` + `screener_breakdown.json`). Entry point: `scripts/run_screener.py` (run ~09:00 IST). The live runner already reads the watchlist on startup (and now skips the `_meta` key). Unit-tested in `scripts/test_screener.py` (25 assertions incl. look-ahead invariance).
**Still to do:** real index constituents from nsepython (currently a curated Nifty 50/100 default, overridable via `config/universes.json`); a daily/EOD candle source for the full universe; scheduling the 09:00 run.

---

## P1 — Correctness (trust nothing downstream until fixed)

### SIZE-01 · Sizer floors at 1 lot, defeating every de-risking layer — **[FIXED 2026-06-05]**
_Fixed: the heat / Kelly / regime layers can now return 0 lots (stand down); the `max(1,…)` floor was removed from inside them and applied only after a deliberate trade decision._
`ensemble/position_sizing.py:97,110,118,122` — every layer uses `max(1, ...)`. Kelly scaling to 0.25×, heat-budget reduction, and the documented "0 lots in CHOPPY" all round down to 0 and are then forced back to 1.
**Fix:** Allow `0` as a valid output (stand down). Apply the `max(1, ...)` floor only after a deliberate "we are trading" decision, not inside each de-risking layer.

### SIZE-02 · Lot tiers don't match the documented bands — **[FIXED 2026-06-06]**
The sizer keyed off `SCORE_THRESHOLD_STRONG` + a `(ENTRY+STRONG)/2 = 0.625` midpoint and floored at 1 lot, so it traded the 0.55–0.65 "signal only" band and its tiers didn't line up with the `docs/SIGNALS.md` table.
**Fixed:** the documented bands are now the single source of truth, encoded in `config.settings` (`SCORE_TIER_TRADE=0.65`, `SCORE_TIER_2LOT=0.70` = `SCORE_THRESHOLD_STRONG`, `SCORE_TIER_3LOT=0.75`) and applied by `PositionSizer.score_tier_lots()`:
- `0.55–0.65` → **0 lots (signal only, no trade)** — `size()` returns `None`, enforcing the band in the sizer (not just the entry gate).
- `0.65–0.70` → 1 lot, **reduced to 0 in CHOPPY** (`size()` now takes a `regime` arg; the runner + backtest pass `result.regime`).
- `0.70–0.75` → 2 lots · `≥0.75` → 3 lots — all `min(desired, RISK.lot_size_cap)` so the documented count is capped by the active risk profile (LOW=1 / MED=2 / HIGH=3).
**Verified:** `scripts/test_position_tiers.py` (23 assertions — band edges, short symmetry, no-trade band, CHOPPY 1-lot stand-down, profile cap). The Kelly layer (SIZE-03) stacks on top of this and still passes.

### SIZE-03 · Kelly layer never activated + zeroed every trade when forced — **[FIXED 2026-06-06]**
Two coupled bugs, the second masked by the first:
1. **Dead wiring.** `ensemble/position_sizing.py update_kelly_stats(...)` was documented *"Called by live/runner.py"* but the runner never called it, so `kelly_win_rate`/`kelly_rr_ratio` stayed at the constructor defaults and `_trade_count` stayed 0 — and the Kelly layer gates on `_trade_count >= 20`. The Kelly de-risking layer was **silently inert** in live trading.
2. **Broken multiplier (surfaced once wiring was added).** The layer used the raw quarter-Kelly *fraction* (~0.06–0.25 even for a strong edge) directly as a lot multiplier: `round(base_lots × 0.1) = 0`. So the moment Kelly activated it **zeroed out essentially every trade**, regardless of risk profile. The `min(1.5, …)` cap (unreachable by a raw fraction) and the "scale by rolling win rate" docstring showed the multiplier was meant to be a scaler centered on 1.0.

**Fix:**
- `analytics/pnl_tracker.kelly_stats(n=50)` → `(win_rate, reward:risk, total_closed_trades)` from realized results.
- `live/runner.LiveRunner._refresh_kelly_stats()` feeds those into `sizer.update_kelly_stats(...)` — called once at startup (primed from history) and after every confirmed exit. Guarded so a stats refresh can never interfere with an exit.
- `PositionSizer._kelly_multiplier()` now returns *current edge ÷ baseline edge* (baseline `KELLY_BASELINE_WIN=0.55` / `KELLY_BASELINE_RR=1.5`), so the multiplier sits at 1.0× for an average edge, rises toward the 1.5× cap for a strong edge, and falls toward 0 (stand down) for a poor/negative one. A freshly-calibrated sizer with no realized edge is an exact 1.0× no-op.
**Verified:** `scripts/test_kelly_wiring.py` (14 assertions) — kelly_stats math, activation gate, 1.0× at baseline, scale-up for a better edge, **healthy edge no longer rounds to 0 lots**, and negative edge stands down.

### AGG-01 · Regime bonus can flip the signal's sign — **[FIXED 2026-06-06]**
_Fixed: the regime bonus now scales magnitude in the composite's direction (floored at 0), so it can shrink conviction to neutral but never invert long↔short (`aggregator.py`)._
`ensemble/aggregator.py:150` — a fixed `+0.05` (TRENDING_UP) is added to the composite after combining. A net-short composite of `-0.02` plus `+0.05` becomes `+0.03` — long.
**Fix:** Apply the regime bonus in the direction of the composite (scale magnitude), or gate it so it can't change sign.

### AGG-02 · A failed signal silently re-weights the ensemble — **[FIXED 2026-06-06]**
_Fixed: the composite is divided by the summed weights of the signals that actually contributed (`composite /= total_weight`), so a failed/disabled signal can't inconsistently re-weight the rest._
`ensemble/aggregator.py:141-147` — when a signal throws it's scored 0 but its weight is dropped from `total_weight`, and normalization only fires when `total_weight != 1`. Net effect: a broken signal changes the effective weighting inconsistently.
**Fix:** Decide on a policy (renormalize over surviving weights, or treat a failed signal as a hard skip for that bar) and apply it consistently.

### SIG-01 · Mean reversion fires far too often — **[FIXED 2026-06-06]**
_Fixed: gated on genuine extremes — `bb_pct_b<=0.20` / `rsi<=35` / `z<=-2` for longs (mirror for shorts), still requiring the correct side of mid-band — so a near-mid reading no longer emits a score._
`signals/technical/mean_reversion.py:50,74` — branches on `bb_pct_b < 0.5` / `> 0.5`, so a near-mid-band reading (e.g. 0.45) enters the long branch. `SIGNALS.md` requires extremes (`rsi<30 AND close<=bb_lower AND vwap_dist<-0.3%`).
**Fix:** Gate on the documented extreme conditions; only emit a non-zero score at genuine band extremes.

### FEAT-01 · Session-anchored VWAP — **[FIXED 2026-06-06]**
`features/indicators._session_vwap()` computes cumulative(typical·volume)/cumulative(volume) **reset each trading day** (grouped by calendar day, which is session-correct for NSE in both IST and UTC). Both `vwap_dist_pct` and the `vwap_std_*` bands now use it (was a `rolling(78)`/`rolling(20)` window that bled across sessions). `vwap_breakout` and `mean_reversion` therefore key off a spec-compliant VWAP. Verified by `scripts/test_vwap.py` (8 assertions: per-day reset, volume weighting, no look-ahead, integration). Falls back to a rolling window only when the index has no timestamps.

### FEAT-02 · `X or default` masks legitimate zero values — **[FIXED 2026-06-06]**
_Fixed: replaced the `x or default` idiom with `signals/base.feat()`, which returns the default only when the value is genuinely missing or NaN — a real 0.0 is preserved._
`signals/technical/rsi_momentum.py:32-34`, `vwap_breakout.py:31`, others — `row.get("rsi_14", 50) or 50.0` turns a real RSI of exactly 0, or `macd_hist`/`roc`/`vwap_dist` of exactly 0.0, into the fallback because 0.0 is falsy.
**Fix:** Use explicit NaN checks (`val = row.get(...); val = default if pd.isna(val) else val`), never truthiness, for numeric features.

### BT-01..04 · Backtest engine — **[ALL FIXED 2026-06-06]**
`backtest/engine.py` was rewritten as a custom event-driven simulator (vectorbt removed):
- **BT-01** — each `(symbol, fold)` is simulated independently and its trades pooled; nothing concatenates different instruments into one price series. The equity curve / Sharpe / drawdown are computed from a real daily-PnL curve.
- **BT-02** — exits use each bar's **high/low** to detect intrabar SL/target hits and fill **at the stop/target price** (SL assumed first if both hit in one bar), not at close.
- **BT-03** — the real `PositionSizer` sets qty + ATR SL/target, and the Indian transaction-cost model (`analytics/costs.py`) is charged on every trade; no flat-5% size.
- **BT-04** — per-fold metrics (return, Sharpe, win rate, PF, expectancy, max DD, trades) are computed and reported in `summary()["per_fold"]` alongside the aggregate, and persisted to `backtest_runs`.

No look-ahead: features are computed on the full train+test window but signals only fire on the out-of-sample test window. Verified by `scripts/test_backtest.py` (27 assertions incl. intrabar-fill behaviour) and end-to-end via the dashboard `/backtest/run`.
**Still to do:** next-bar-open entry fills (currently fills at the signal bar's close + modelled slippage); short-side trades (engine is long-only); the engine targets intraday timeframes (daily-bar `max_hold` is degenerate).

### ML-01..03 · ML training leakage — **[ALL FIXED 2026-06-06]**
- **ML-01** — `models/validation.purged_split()` does a per-symbol chronological split with an embargo equal to the label horizon, so validation is the latest bars per instrument and no train label peeks into validation. macro + micro `train()` now build per-symbol frames (`_build_frames`) and call it instead of `train_test_split` on a symbol-concatenated frame.
- **ML-02** — `strategy_outcomes.train_strategy()` sorts trades by `entry_time` and uses a chronological holdout (no shuffle/stratify); training rows are now tagged with `entry_time` in `train_outcomes.build_training_frames`. Single-class train splits are skipped.
- **ML-03** — every ML feature path is `ffill().fillna(0.0)` — **no `bfill`** anywhere (macro/micro `prepare_features` + inference, outcome `_prepare_xy`, `train_outcomes.reconstruct_entry_features`). Verified by a real-xgboost test asserting prepared features contain no NaN.

Verified: `scripts/test_ml_validation.py` (16 logic assertions) + `scripts/test_ml_train.py` (10 end-to-end with real xgboost).

### RL-01..04 · RL exit/entry agents — **[ALL FIXED 2026-06-06]**
- **RL-01** — `train_rl_on_journeys._build_journey` now sets a HOLD transition's `next_state` to the **next bar's** state (proper TD backup); only the forced-close at the last bar is terminal. The realized reward propagates back through the journey (verified: a winning trade's early-bar HOLD value is positive).
- **RL-02** — each bar emits three transitions — HOLD (→ next bar), EXIT_NOW (terminal, reward = pnl locked in now), TIGHTEN_SL (terminal, reward = counterfactual tightened-stop rollout over the actual candle path). All three actions now get learned Q-values; the agent genuinely compares hold-vs-exit-vs-tighten (verified: losers are cut early). The synthetic bootstrap was also rebuilt to use a coherent price path with the same structure (no more random-action noise).
- **RL-03** — the entry agent keys its Q-table only on dims reliably populated in BOTH training and live (composite_score, regime, time_of_day, volume_ratio, recent_win_rate, session_pnl, open_positions). `vix`/`macro_prob`/`score_momentum` are excluded (not reconstructable post-hoc → would key train vs live into different cells). `recent_win_rate`, `session_pnl_normalized`, `open_positions_count` are now reconstructed from the trade log so they vary. Synthetic data no longer counts toward the activation gate (`count_for_activation=False`).
- **RL-04** — discretization in both agents clamps `np.digitize(x, bins) - 1` to `[0, len-1]`, so out-of-range values no longer wrap to the top bucket.
- Also: the exit-agent retrain now actually calls `save_model()` (it never did).

Verified by `scripts/test_rl_agents.py` (12 assertions). Note the RL agents target intraday exits; the synthetic bootstrap is for cold-start only — activate on real data.

### THETA-01 · Delta-hedge sizing — **[FIXED 2026-06-06]**
`DeltaHedgeManager.compute_hedge(net_delta, position_lots)` now sizes correctly: the position's share-delta is `net_delta × position_lots × lot_size` and one future carries `lot_size` deltas, so **futures_lots = round(net_delta × position_lots)** (the `lot_size` cancels) — not `round(per-unit delta)`. A sub-lot drift returns 0 (not hedgeable in whole lots) instead of being forced to 1.
**Also wired (pairs + theta books):** `theta_risk`/`pairs_risk` were never consulted by the strategy/signal. New decision layers — `signals/theta/theta_book.ThetaBook` and `signals/pairs/pairs_book.PairsBook` — gate every entry/exit on the risk rails (VIX panic, book-capital cap, concurrency; pair-halt + concurrent-pairs cap). These run as **parallel strategy books**, deliberately not folded into the single-symbol `[-1,1]` ensemble (a 2-leg spread / short straddle doesn't fit it). Verified by `scripts/test_books.py` (19 assertions). **Still pending:** live multi-leg execution (option-chain feed + futures hedge orders + 2-leg/OCO routing).

### PnL-01 · Transaction costs never applied to live PnL — **[FIXED 2026-06-06]**
_Fixed: `analytics/costs.round_trip_cost` (Indian intraday model: STT, brokerage, exchange, SEBI, stamp, GST, slippage) is subtracted per trade; daily stats report gross, costs, and net separately._
`analytics/pnl_tracker.py:65` — `net_pnl = gross_pnl  # add STT/brokerage later`. `BACKTEST_COMMISSION`/`SLIPPAGE` exist in settings but are unused live. Live PnL and the daily summary overstate profitability.
**Fix:** Apply an Indian intraday cost model (sell-side STT 0.025%, exchange txn, SEBI fee, GST on brokerage, stamp duty, brokerage, slippage) to every closed trade; report gross and net separately.

### RETRAIN-01..02 · Unsafe model promotion — **[FIXED 2026-06-06]**
`models/promotion.champion_challenger()` (used by `retrain_daily`): trains a CHALLENGER on the older fit slice only, scores BOTH the live champion and the challenger on a held-out forward slice (`time_holdout_split`, most recent N days) the challenger never saw, and promotes — **atomic swap into the live file + reload** — only if the challenger beats the champion by `margin`. Otherwise the champion is kept untouched. This replaces the old code where `get_*_model()` returned the same singleton, the macro/micro retrain never even called `save_model()`, and "old AUC" was measured in-sample on `tail(1000)`. Model `save_model()` is now atomic (tmp + `os.replace`). Verified by stub-model logic tests + a real-model promotion test.

### FEED-01..02 · Feed robustness — **[FIXED 2026-06-06]** (+ event-driven foundation)
- **FEED-01** — `CandleAggregator.flush_if_due()` plus a 1s timer thread in `UpstoxFeed` **force-close a bar when its interval elapses even with no new tick**, so the last bar of a quiet period (and the final pre-EOD bar) is never lost. `stop()` flushes too. These emit bar-close events.
- **FEED-02** — the feed keeps an in-memory price cache with a monotonic age (`get_quote(symbol) -> (price, age)`). The monitor uses a **fresh** price only; if it's missing or older than `STALE_PRICE_SECONDS`, it **skips the stop check and raises a throttled stale-feed alert** rather than substituting `entry_price` (which silently disabled the stop). Flatten/EOD exits use the best-known price (tick → last candle close), never a fabricated entry-price zero-PnL.
- **Event-driven loop (foundation)** — the runner now processes a symbol when its primary-tf bar closes (the feed enqueues it), with a 60s fallback sweep; control/EOD are checked every ~1s (kill switch reacts in ~1s, not up to 30s). Order placement stays on the single signal-loop thread. `upstox_client` is now imported lazily so the feed is testable without the SDK. Verified by `scripts/test_feed.py` (11 assertions).
**Still pending (the deeper reliability win):** broker-side OCO so stops live at the exchange and survive a runner crash — see LIVE-01/02/04 + `IDEAS_ADVANCED.md` §11.1.

### SEC-01 · Dashboard auth — **[FIXED 2026-06-06]**
An auth middleware (`dashboard/api/main.py`) requires `X-API-Key == DASHBOARD_TOKEN` on every state-changing request (POST/PUT/PATCH/DELETE) — kill switch, mode/token writes, close-all, backtest run, weights/toggles, feature edits. Read-only GETs and CORS preflight stay open so the dashboard renders. When `DASHBOARD_TOKEN` is **unset** the middleware is a no-op (localhost-dev convenience) and the API warns once at startup; **set it before exposing the dashboard on any non-localhost interface.** The UI sends the key from localStorage (lock button to set it) and surfaces `auth_enabled` from `/status`. Verified: 401 without/with-wrong key, 200 with the correct key, GETs open.
**Related still-open:** `TOKEN-01` (dashboard `/system/token` stores the raw OAuth code without exchanging it).

### TOKEN-01 · Dashboard `/token` stores the raw OAuth code — **[OPEN]**
`dashboard/api/routes/system.py:140-185` — it stores whatever the user pastes (typically a `?code=...` callback) into `LIVE_ACCESS_TOKEN` without exchanging the code for a token. That value is not a usable access token.
**Fix:** Reuse `refresh_token.py:exchange_code_for_token` server-side; store the exchanged token only.

### UI-01 · Live & AI Models pages call non-existent endpoints — **[FIXED 2026-06-06]**
_Fixed: both pages were rewired to endpoints that exist — Live polls `/status`,`/scan`,`/positions` + the control plane; AI Models reads `/models/status` (file presence + last training metrics)._
`dashboard/ui/src/pages/Live.tsx` (`/api/stream`, `/api/auto_trade`), `AIModels.tsx` (`/api/rl/status`) — none of these routes exist. Live shows "RECONNECTING" forever; AI Models shows "NOT LOADED".
**Fix:** Implement the SSE producer + auto-trade + model-status endpoints, or replace these pages with the data that does exist.

---

## P2 — Robustness / Hygiene

- **RL-04** **[FIXED]** — both agents now bin via a clamped `_bin()` helper (`np.clip(digitize-1, 0, len-1)`); out-of-range values no longer wrap to the top bucket. See the RL-01..04 entry above.
- **THETA-02** **[FIXED 2026-06-06]** — `vix_to_lots` now derives its bands entirely from `self.vix_floor / vix_full_size / vix_ceiling / vix_panic` (added a configurable `vix_full_size`, default 14, for the 1→2-lot split, clamped into `[floor, ceiling]`). The defaults (11/14/18/20) reproduce the old bands exactly, but tuning the bounds now actually shifts sizing. Verified by `scripts/test_theta_sizing.py` (24 assertions — default bands, shifted custom bands, same-VIX-different-config, clamp, config-driven panic).
- **AGG/SIG hardcodes** `signals/base.py:53-63` — actionable threshold 0.40 and ±0.05 direction deadband are hardcoded, inconsistent with `SCORE_THRESHOLD_SIGNAL`. Move to config.
- **FEAT-PSAR** `features/indicators.py:169` — `psar_bull = 0.5` placeholder on length mismatch feeds the model a constant dummy. Compute or drop the feature.
- **FEAT-warn** `features/indicators.py:28` — global `warnings.filterwarnings("ignore", RuntimeWarning)` hides div-by-zero / NaN generation. Scope or remove.
- **MODELPATH** `signals/ml/*`, `models/rl_*` — model paths are relative (`models/saved/...`) and depend on CWD, unlike `config.MODELS_DIR`. Use the config path everywhere.
- **UI-02** **[FIXED]** — completed backtests are written to `backtest_runs` (see BT-04), so `/backtest/history` populates.
- **UI-03** **[FIXED]** — the equity-curve API returns `equity` in chronological order; the Overview chart renders (`dashboard/api/routes/trades.py`).
- **TAG-01** **[FIXED]** — entry + exit orders both tag with the canonical strategy id used in the trade log (`STRATEGY_TAG`).
- **PnL breakeven** **[FIXED]** — win/loss now split on `pnl > 0` / `pnl < 0`; a breakeven trade is neither (`analytics/pnl_tracker.py`).
- **BLACKOUT** **[FIXED]** — the open-blackout window uses integer-minute math (`risk/circuit_breaker.py`), so `BLACKOUT_OPEN_MINUTES ≥ 60` can't raise `ValueError`.
- **SEC-02** **[FIXED 2026-06-06]** — the key is sent once in the JSON body (OpenAlgo's auth); the duplicate `x-api-key` header was removed and `raw_response` is run through `_redact()` (paper + live), so the secret never lands in a returned object or log. `self.api_key` is still held in memory for body auth only. Verified by `scripts/test_openalgo_security.py` (11 assertions).
- **DISCORD** `analytics/discord_notify.py:60` — one `threading.Thread` per message, no rate limiting (Discord webhook limit ~30/min). Use a bounded queue/worker.
- **Swallowed exceptions** `data/upstox_feed.py:178,234,269,289`, `analytics/pnl_tracker.py:101,114` — bare `except: pass` hides feed parse failures and DB errors. Log with context; don't silently drop ticks.
- **TEST-01** **[FIXED 2026-06-06]** — the three smoke-print scripts (`test_macro_model.py`, `test_micro_model.py`, `test_rl_exit_agent.py`) are now real assertion tests: valid AUC ∈ [0,1] + accuracy, predictions are valid probabilities that **vary** across inputs (the meaningful discrimination check — not the flaky "AUC > 0.5" on random synthetic data), gate consistency, deterministic RL Q-update toward reward, and a save→reload round-trip. They use **temp model paths** (the old scripts saved over the live model) and are **pytest-collectable** (`pytest scripts/test_*_model.py`), with a standalone `main()` that prints a PASS/FAIL summary and SKIPs cleanly when xgboost is absent. Fixed a real type bug the assertions caught: `MicroModelResult.should_enter` was a `numpy.bool_` (broke `isinstance(.,bool)` + json) — now cast to `bool`.

---

## Documentation ↔ Code Mismatches

The docs describe modules and paths that don't exist in the tree. Either build them or mark them clearly as planned.

| Documented in | Path | Status |
|---|---|---|
| MASTER_PLAN, ARCHITECTURE | `screener/` (universe, daily_screener, ranking_features, catalyst_detector) | **Built (GAP-01 fixed)** — `scripts/run_screener.py` writes `daily_watchlist.json` |
| ARCHITECTURE | `data/nse_data.py` (nsepython option chain / PCR / OI) | Missing |
| ARCHITECTURE | `features/micro_features.py` | Missing (micro features live inside `micro_model.py`) |
| ARCHITECTURE | `risk/correlation_guard.py` | **Built (EDGE-03)** — sector cap + correlation cap, wired into the runner |
| ARCHITECTURE | `backtest/tick_replay.py` | Missing |
| ARCHITECTURE, ROADMAP | `signals/news/`, `signals/options_flow/`, `signals/llm/`, `signals/research/` | Missing (Phase 3–4, expected) |
| ARCHITECTURE | `notebooks/`, `tests/` | Missing |
| README step 7 | `dashboard/frontend/` | Wrong — actual dir is `dashboard/ui/` |
| ROADMAP `[x]` marks | macro/micro/outcome/RL/pairs/theta modules | **Partly wired (updated 2026-06-06):** the ensemble composite is still the 3 technical signals, but macro/micro/outcome/RL-entry are now consulted live as **entry gates** in the runner (`live/runner.py` imports + `_evaluate` path). Pairs/theta now run as **risk-gated books** (`ThetaBook`/`PairsBook`, unit-tested) but are **not yet driven by the runner** — live multi-leg execution is pending. |
| SIGNALS.md score formulas | every Phase-1 signal | Code scoring diverges from the documented `sum(conditions)/N`, so documented thresholds (0.55/0.65/0.70) aren't calibrated to actual score distributions |

**Action:** Update `ARCHITECTURE.md`'s file tree to reflect reality (or build the gaps), correct the README frontend path, and add a note in each doc distinguishing "built and wired" from "file exists" from "planned."

---

## Cross-Cutting Missing Capabilities

These aren't single-line bugs; they're whole capabilities the system needs before it can trade real money reliably. Tracked here, with alpha-side ideas in `IDEAS_ADVANCED.md`.

1. **Control plane** between dashboard and runner (CTRL-01) — the prerequisite for the kill switch and weight controls to mean anything.
2. **Broker-side bracket / OCO orders** — so SL/target live at the exchange and survive a runner crash, instead of being polled in-process (relates to LIVE-01/02/04, FEED-02). See `IDEAS_ADVANCED.md` §11.
3. **Order lifecycle**: idempotency keys, retry/backoff, partial-fill handling, status polling (LIVE-03).
4. **Reconciliation loop**: periodic and on-startup sync of in-memory book ↔ broker ↔ DB (LIVE-04).
5. **Watchdog/heartbeat** for the feed and loops: detect a dead websocket, a stalled main loop, a crashed monitor thread.
6. **Realistic Indian cost model** in both backtest and live (PnL-01, BT-03).
7. **Leakage test harness**: an automated assertion that every feature at bar `t` uses only data ≤ `t`, run in CI.
8. **Walk-forward done correctly**: per-fold metrics, purge + embargo, and out-of-sample-only model evaluation (BT-01/04, ML-01/03, RETRAIN-02).
9. **Pairs + theta:** decision + risk layers now integrated as parallel strategy books (`ThetaBook`/`PairsBook`, THETA-01 fixed) and unit-tested. **Remaining:** live multi-leg execution — option-chain feed, futures delta-hedge orders, and 2-leg/OCO order routing — so the books can actually trade.
10. **Probability calibration** of XGBoost outputs — **partially addressed (ML-04):** a model can now only veto after clearing a minimum out-of-sample AUC, and the macro gate centres on the training base rate instead of a hard 0.50 (removing the anti-LONG bias on the imbalanced label). **Still pending:** full isotonic/Platt calibration (`CalibratedClassifierCV`) so the micro `0.45` and outcome `0.55` cutoffs map to real precision, and validation-derived (not hard-coded) thresholds.

11. **Backtest portfolio realism** — each (symbol, fold) is still simulated in isolation with full capital and an empty portfolio-heat list, so the live caps (`max_concurrent_positions`, `portfolio_heat_limit`) never bind in the backtest. Per-trade stats (win rate, expectancy, profit factor) are valid; the aggregate equity/Sharpe are optimistic because they assume no cross-symbol capital contention. A unified-timeline portfolio sim is the remaining work. (BT-05 added short-side + next-bar-open fills + the cost filter; this is the residual.)
