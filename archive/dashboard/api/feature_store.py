"""
Feature tracker store — backs the dashboard Roadmap page.

Tracks what has been built (with dates), what is in progress, and what is still
pending, across the whole system. Stored as a JSON file so it is easy to edit by
hand and version in git. Seeded on first use from the list below (derived from
docs/KNOWN_ISSUES.md + docs/ROADMAP.md).

Statuses: "done" | "in_progress" | "pending"
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from config.settings import ROOT_DIR

STORE_PATH = ROOT_DIR / "config" / "feature_tracker.json"
_lock = threading.Lock()

# Date the initial audit + first fix batch landed.
_T0 = "2026-06-05"


def _slug(title: str) -> str:
    s = "".join(c.lower() if c.isalnum() else "-" for c in title)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")[:60]


def _f(title, category, status, priority="", phase="", ref="", notes="",
       added=_T0, completed=None) -> dict:
    return {
        "id":           _slug(title),
        "title":        title,
        "category":     category,
        "status":       status,
        "priority":     priority,
        "phase":        phase,
        "issue_ref":    ref,
        "notes":        notes,
        "added_at":     added,
        "completed_at": completed if completed else (_T0 if status == "done" else None),
        "updated_at":   _T0,
    }


# ── Seed board ────────────────────────────────────────────────────────────────
_SEED: list[dict] = [
    # ---- Done (June 2026 fix batch) ----
    _f("Control plane (dashboard ↔ runner)", "Execution", "done", "P0", "1", "CTRL-01",
       "JSON control file the runner polls each loop; kill switch / pause / weights now reach live trading."),
    _f("Kill switch flattens positions and halts entries", "Execution", "done", "P0", "1", "LIVE-02",
       "Kill switch now flattens all open positions and blocks new entries, reversible from the dashboard."),
    _f("Exit-order failure handling with retry + escalation", "Execution", "done", "P0", "1", "LIVE-01",
       "Position is kept open on a failed exit and retried with backoff; escalates to broker close-all after 3 tries."),
    _f("Proactive daily-loss halt", "Risk", "done", "P0", "1", "LIVE-05",
       "Monitor thread halts + flattens the moment session PnL breaches the daily loss limit, independent of entries."),
    _f("Position reconciliation on restart", "Execution", "done", "P0", "1", "LIVE-04",
       "On startup the runner adopts open trades from the DB so positions are never orphaned after a crash."),
    _f("Best-effort fill-price confirmation", "Execution", "done", "P0", "1", "LIVE-03",
       "Polls order status once and books PnL at the actual fill price when available (full reconciliation still pending)."),
    _f("Consistent SEBI strategy tag on all orders", "Execution", "done", "P2", "1", "TAG-01",
       "Entry and exit orders both tag with the canonical strategy id used in the trade log."),
    _f("Position sizer can stand down (0 lots)", "Risk", "done", "P1", "1", "SIZE-01",
       "Kelly / heat / regime layers can now reduce to no-trade instead of being floored at 1 lot."),
    _f("Regime bonus no longer flips signal sign", "Signals", "done", "P1", "1", "AGG-01",
       "Regime bonus adjusts magnitude in the direction of the composite; can no longer invert long/short near zero."),
    _f("Mean reversion fires only at extremes", "Signals", "done", "P1", "1", "SIG-01",
       "Gated on genuine oversold/overbought extremes instead of any bb_pct_b != 0.5."),
    _f("NaN-safe feature reads", "Signals", "done", "P1", "1", "FEAT-02",
       "Replaced the `value or default` idiom that turned legitimate 0.0 readings into fallbacks."),
    _f("Transaction-cost model (STT / brokerage / GST / slippage)", "Risk", "done", "P1", "1", "PnL-01",
       "Net PnL now subtracts a realistic Indian intraday cost model; daily stats report gross, costs and net."),
    _f("Blackout-window time arithmetic fix", "Risk", "done", "P2", "1", "",
       "Open-blackout end time computed with timedelta math so it can't raise on minute overflow."),
    _f("Kill-switch API accepts a body", "Dashboard", "done", "P1", "1", "CTRL-02",
       "Fixed the 422 — kill switch endpoint now takes {active} and writes to the control plane."),
    _f("Equity-curve field aligned", "Dashboard", "done", "P2", "1", "UI-03",
       "API returns `equity` in chronological order so the Overview area chart renders."),
    _f("Auto-trade / pause toggle", "Dashboard", "done", "P1", "1", "",
       "Control-backed master switch to pause new entries without flattening, from the Live page."),
    _f("Feature Tracker / Roadmap page", "Dashboard", "done", "", "1", "",
       "This board — track what's added (with dates), in progress, and pending."),
    _f("Live page rewired to real endpoints", "Dashboard", "done", "P1", "1", "UI-01",
       "Live ops console now polls real status / scan / positions / control endpoints instead of missing SSE routes."),
    _f("AI Models page rewired to real endpoint", "Dashboard", "done", "P1", "1", "UI-01",
       "Reads /api/models/status (file presence + training log) instead of a non-existent /api/rl/status."),
    _f("Models status API endpoint", "Dashboard", "done", "", "2", "",
       "Reports saved-model presence and last training metrics for the AI Models page."),
    _f("Backtest run persistence", "Dashboard", "done", "P2", "1", "UI-02",
       "Completed backtests are written to backtest_runs so the history panel populates."),

    # ---- Backtest engine rebuild (done) ----
    _f("Walk-forward backtest correctness", "Backtest", "done", "P1", "1", "BT-01..04",
       "Per-(symbol,fold) portfolios, intrabar SL/target fills, real sizing, per-fold metrics."),
    _f("Session-anchored VWAP", "Signals", "done", "P1", "1", "FEAT-01",
       "Replaced the rolling 78-bar VWAP with a true session-reset VWAP."),

    _f("Operational store migrated DuckDB→SQLite (WAL)", "Execution", "done", "P0", "1", "LIVE-06",
       "SQLite WAL with thread-local connections: concurrent cross-process readers + a writer, so the runner and dashboard share one DB. DuckDB now analytics-only. Proven by scripts/test_concurrency.py."),
    _f("Kelly position-sizing layer wired + normalized", "Risk", "done", "P1", "2", "SIZE-03",
       "Kelly was inert (update_kelly_stats never called) and, once wired, the raw quarter-Kelly fraction zeroed every trade. Runner now feeds realized win-rate/reward:risk from PnLTracker; multiplier normalized to scale around 1.0 instead of rounding to 0. Tested by scripts/test_kelly_wiring.py."),
    _f("Score→lots bands match the documented spec", "Risk", "done", "P1", "1", "SIZE-02",
       "Sizer now uses the documented 0.65/0.70/0.75 tiers (0.55–0.65 = no trade, CHOPPY zeroes the 1-lot tier) via config.SCORE_TIER_*, capped by the risk profile — replacing the old STRONG+midpoint logic. Tested by scripts/test_position_tiers.py."),
    _f("OpenAlgo API key not duplicated / not persisted", "Execution", "done", "P2", "1", "SEC-02",
       "Key sent once in the JSON body (OpenAlgo's auth); removed the duplicate x-api-key header and redacted it from OrderResult.raw_response (paper + live). Tested by scripts/test_openalgo_security.py."),
    _f("Model tests assert correctness (not smoke prints)", "Testing", "done", "P2", "1", "TEST-01",
       "macro/micro/RL-exit tests rewritten with real assertions (valid AUC, predictions vary, persistence round-trip), pytest-collectable, temp model paths. Caught + fixed a numpy.bool_ leak in MicroModelResult.should_enter."),
    _f("Theta straddle sizing driven by config", "Risk", "done", "P2", "2", "THETA-02",
       "vix_to_lots now derives bands from vix_floor/full_size/ceiling/panic (added configurable vix_full_size) instead of hardcoded 11/14/18/20; defaults reproduce the old bands. Tested by scripts/test_theta_sizing.py."),
    _f("Header UX: hover tooltips + editable risk/capital + broker funds", "Dashboard", "done", "P2", "1", "",
       "Reusable Tip component explains every header control + nav item on hover. RISK is now an editable dropdown and CAPITAL is click-to-edit (POST /system/risk, /system/capital — applied live via the control plane + saved to .env). New BROKER tile shows actual Upstox funds via GET /system/funds (OpenAlgo /api/v1/funds; '—' in paper). Sizer/breaker take an injected risk profile so changes apply without restart."),

    # ---- Pending: execution / data / risk ----
    _f("Broker-side bracket / OCO orders", "Execution", "pending", "P1", "2", "",
       "Place SL/target at the exchange so positions survive a runner crash."),
    _f("Forced bar-close timer in feed", "Data", "pending", "P1", "1", "FEED-01",
       "Flush the in-progress candle on a wall clock even when no new tick arrives."),
    _f("Stale-LTP alert (no entry-price fallback)", "Data", "pending", "P1", "1", "FEED-02",
       "Treat a missing LTP as an alert instead of using entry price (which disables stops)."),
    _f("Volatility targeting for position size", "Risk", "pending", "P2", "2", "",
       "Scale size to a target portfolio vol; stacks with Kelly."),
    _f("Discord webhook rate limiting", "Data", "pending", "P2", "1", "",
       "Bounded worker/queue instead of one thread per message."),

    # ---- Pending: ML / RL ----
    _f("Time-ordered split + purged CV for XGBoost", "ML/RL", "pending", "P1", "2", "ML-01..03",
       "Chronological per-symbol split with purge + embargo; stop bfill leakage."),
    _f("RL exit agent: real next_state + action coverage", "ML/RL", "pending", "P1", "2", "RL-01..02",
       "Fix the self-loop next_state and train EXIT-early / TIGHTEN actions."),
    _f("RL entry agent: real context in state", "ML/RL", "pending", "P1", "2", "RL-03",
       "Populate the hardcoded-constant state dimensions or drop them."),
    _f("Champion / challenger model promotion", "ML/RL", "pending", "P1", "2", "RETRAIN-01",
       "Promote a retrained model only if it beats the live one on held-out data; atomic swap + rollback."),
    _f("Out-of-sample retrain evaluation", "ML/RL", "pending", "P1", "2", "RETRAIN-02",
       "Evaluate retrains on a forward slice the model never saw."),
    _f("Probability calibration of model outputs", "ML/RL", "pending", "P1", "2", "",
       "Isotonic/Platt calibration so 0.45/0.55 gate thresholds mean what they say."),

    # ---- Pending: backtest / compliance ----
    _f("Leakage / causality test harness", "Backtest", "pending", "P1", "1", "",
       "Assert every feature at bar t uses only data <= t; run in CI."),
    _f("Backtest ↔ live parity monitoring", "Backtest", "pending", "P2", "2", "",
       "Log what the backtest would have done per live trade; alert on divergence."),
    _f("Auth on dashboard mutating routes", "Dashboard", "pending", "P1", "1", "SEC-01",
       "Token/session on kill-switch, mode, token, close-all, backtest run."),
    _f("Dashboard token OAuth exchange", "Dashboard", "pending", "P1", "1", "TOKEN-01",
       "Exchange the pasted auth code for a real access token server-side."),

    # ---- Pending: roadmap phases ----
    _f("Pre-market screener module", "Screener", "done", "P0", "1", "GAP-01",
       "screener/ built: universes + cross-sectional ranking + catalysts → config/daily_watchlist.json "
       "(run via scripts/run_screener.py). Runner reads it at startup. Pure scoring core is unit-tested, no look-ahead."),
    _f("Wire pairs + theta into ensemble / backtest", "Signals", "pending", "P1", "2", "",
       "Files exist but are not in the live or backtest path."),
    _f("FinBERT news sentiment signal", "Signals", "pending", "", "3", "",
       "ProsusAI/finbert on NSE/MoneyControl headlines."),
    _f("NSE announcements / event blackout", "Signals", "pending", "", "3", "",
       "Suppress signals around earnings/events; PEAD bias."),
    _f("Options flow (PCR / OI / IV) signals", "Signals", "pending", "", "3", "",
       "Contrarian PCR, OI momentum, IV skew via nsepython."),
    _f("LLM analyst agents", "ML/RL", "pending", "", "4", "",
       "Technical / news / risk analyst agents (TradingAgents pattern)."),

    # ════════════════════════════════════════════════════════════════════════
    # Second audit + fix batch (2026-06-07) — multi-agent re-read
    # ════════════════════════════════════════════════════════════════════════
    # ---- Done (P0 + correctness) ----
    _f("RL entry agent no longer vetoes ~100% of entries", "ML/RL", "done", "P0", "2", "RL-05",
       "Activated agent was SKIPping every unseen Q-cell (silently halting trading). should_enter is now permissive on unseen/unlearned cells (falls back to rules) and only vetoes learned losers; activation counts real ENTER decisions.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Net-of-cost PnL everywhere + cost-aware entry filter", "Risk", "done", "P1", "1", "PnL-02",
       "Win/loss, Kelly, win-rate and the live daily-loss rail now use NET pnl (trade_log.net_pnl+cost stored); a cost-aware filter skips setups whose target can't clear round-trip costs.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Poll-to-terminal fill confirmation + partial-fill handling", "Execution", "done", "P1", "2", "LIVE-07",
       "place_order polls until terminal (catches post-accept rejection); OrderResult carries filled_qty/avg_price; runner books real fills and retries partial exits.",
       added="2026-06-07", completed="2026-06-07"),
    _f("ML gates only veto above a min OOS AUC + base-rate centering", "ML/RL", "done", "P1", "2", "ML-04",
       "A model is advisory until it clears ML_GATE_MIN_AUC out-of-sample; the macro gate centres on the training base rate, not a hard 0.50 (removes the anti-LONG bias on the imbalanced label).",
       added="2026-06-07", completed="2026-06-07"),
    _f("Promotion refits on full data + no in-sample fallback", "ML/RL", "done", "P1", "2", "ML-05",
       "Challenger refit on the full window after the OOS gate passes (no freshest-data starvation); a too-short holdout keeps the champion instead of an in-sample comparison.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Micro model train/serve timeframe aligned (5-min)", "ML/RL", "done", "P1", "2", "ML-06",
       "Was trained on 1-min but served on 5-min (skew). Now trains + serves on 5-min with a 6-bar horizon.",
       added="2026-06-07", completed="2026-06-07"),
    _f("evaluate() made pure (no champion corruption)", "ML/RL", "done", "P2", "2", "ML-07",
       "evaluate() no longer mutates the live model's feature_columns; snapshots + scores on trained columns.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Backtest short-side + next-bar-open fills", "Backtest", "done", "P1", "1", "BT-05",
       "Engine now simulates SHORTs (the runner trades them) and fills entries at the next bar's open (removes same-bar look-ahead) + applies the cost filter.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Backtest per-day EOD square-off", "Backtest", "done", "P1", "1", "BT-06",
       "Positions force-close at the IST session end and never fill/hold across a session boundary — matches the strictly-intraday live runner.",
       added="2026-06-07", completed="2026-06-07"),
    _f("UTC→IST session features", "Signals", "done", "P1", "1", "FEAT-03",
       "time_norm / session_open / day_of_week / expiry + RL time_of_day assumed IST but candles are stored UTC; now converted. (Fixed time_norm spanning only 0–0.12.)",
       added="2026-06-07", completed="2026-06-07"),
    _f("Risk-based equity position sizing", "Risk", "done", "P1", "1", "SIZE-04",
       "Cash equity traded 1–3 shares (F&O lot model w/ lot_size=1). Now risk-based: shares = per-trade risk budget × conviction ÷ stop distance. F&O keeps the lot model.",
       added="2026-06-07", completed="2026-06-07"),
    _f("read_candles tolerates mixed tz timestamp formats", "Data", "done", "P2", "1", "DB-TZ",
       "Parsing crashed when the timestamp column mixed tz-aware (real backfill) and naive (demo seed) ISO; now parsed as UTC.",
       added="2026-06-07", completed="2026-06-07"),
    _f("statsmodels installed (cointegration dep)", "Execution", "done", "P1", "2", "DEP-01",
       "Was declared but not installed → all pairs math crashed at runtime; installed into the venv.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Pairs health check tri-state (no false halt)", "Risk", "done", "P1", "2", "PAIRS-01",
       "An un-testable day (data gap/holidays) no longer counts toward the halt streak; window widened to 150d.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Pairs z-score excludes the current bar", "Signals", "done", "P2", "2", "PAIRS-02",
       "Z-score measured against the prior window so a true divergence crosses entry/stop instead of self-damping.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Screener correctness (volume surge / catalyst / inf / CSV)", "Screener", "done", "P2", "1", "SCR-01..04",
       "Volume-surge baseline excludes the current bar; event-risk catalyst actually penalises; zero interior close rejected (no +inf rank); --strategies CSV stripped + unknown-strategy warns.",
       added="2026-06-07", completed="2026-06-07"),
    _f("RL exit agent documented as trained-but-inactive", "ML/RL", "done", "P1", "2", "RL-06",
       "Exit agent is trained daily but never wired into live exits (purely rule-based today). Documented with the guards required before activation, so operators don't assume RL manages exits.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Analytics & Simulation dashboard page", "Dashboard", "done", "P1", "1", "DASH-02/03/04/05/08",
       "New /analytics page + /api/analytics/* route: gross-vs-net-vs-cost (bps) edge verdict, R-multiple distribution, what-if simulator, by-exit-reason, data-health, PAPER/LIVE toggle.",
       added="2026-06-07", completed="2026-06-07"),

    # ---- In progress ----
    _f("Backtest walk-forward auto-windowing", "Backtest", "in_progress", "P1", "0", "BT-07",
       "Engine auto-fits train/test to the available span so walk-forward runs on short histories. Needs ≥150 days of real data (DATA-01) for trustworthy folds.",
       added="2026-06-07"),

    # ---- Phase 0: make it profitable (the gate) ----
    _f("Find a cost-beating edge (BT-EDGE gate)", "Backtest", "pending", "P0", "0", "BT-EDGE",
       "Empirical: Phase-1 ensemble shows ~1 bp gross edge vs ~16 bps costs → net negative. Profitability gate before any paper/live.",
       added="2026-06-07"),
    _f("Cost-aware trade selection", "Signals", "done", "P1", "0", "EDGE-01",
       "SCORE_TIER_TRADE raised 0.65\u21920.68; MAX_TRADES_PER_SYMBOL_DAY=3 added; per-day counter in backtest + live runner. Cost filter tightened.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Tune exit structure to the 5-min timeframe", "Risk", "done", "P1", "0", "EDGE-02",
       "LOW: sl_atr 1.5→2.0, target 2.5→3.0, trail_act 1.2→1.5, trail_lock 0.8→1.0. "
       "MEDIUM: sl_atr 1.5→2.0, target 2.0→2.8, trail_act 1.0→1.2, trail_lock 0.7→0.8.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Correlation / sector exposure guard", "Risk", "done", "P1", "0", "EDGE-03",
       "risk/correlation_guard.py — sector cap (max 2/sector) + optional return-correlation cap, wired into the runner entry path. No 3-banks-at-once.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Regime filter on entries", "Signals", "done", "P2", "0", "EDGE-04",
       "_MOMENTUM_BLOCK_REGIMES = {Regime.CHOPPY} wired into backtest engine + live runner. All entries blocked when regime is CHOPPY.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Real session-anchored ORB signal", "Signals", "pending", "P2", "0", "EDGE-05",
       "The orb/first_30m feature is mislabeled (rolling 6-bars-ago window). Build a true opening-range breakout.",
       added="2026-06-07"),
    _f("Index / sector-breadth confirmation gate", "Signals", "pending", "P1", "0", "EDGE-06",
       "Each stock is traded in isolation today (no index/constituent context). Compute banking-sector breadth "
       "from the banks already tracked (fraction above VWAP / positive momentum) and gate entries on sector "
       "alignment; optionally subscribe to NIFTY BANK for its trend. Composes with EDGE-03 + EDGE-04. "
       "Trading Bank Nifty itself off breadth is a later F&O step.",
       added="2026-06-07"),
    _f("Train + probability-calibrate the ML gates", "ML/RL", "pending", "P1", "0", "ML-08",
       "Needs a real training-data pipeline (DATA-01) + CalibratedClassifierCV so 0.45/0.55 cutoffs map to real precision.",
       added="2026-06-07"),
    _f("Portfolio-realism backtest", "Backtest", "pending", "P2", "0", "BT-08",
       "Shared capital + max-concurrent + heat cap across symbols on one timeline (today each symbol is isolated).",
       added="2026-06-07"),
    _f("Leakage / causality CI assertion", "Backtest", "pending", "P2", "0", "TEST-LEAK",
       "Assert every feature at bar t uses only data ≤ t.",
       added="2026-06-07"),
    _f("Feed / loop watchdog + heartbeat", "Data", "pending", "P2", "0", "WATCH-01",
       "Detect a dead websocket, stalled main loop, or crashed monitor thread.",
       added="2026-06-07"),
    _f("Real data pipeline (constituents + daily/EOD + backfill)", "Data", "pending", "P1", "0", "DATA-01",
       "nsepython index constituents + a daily/EOD candle source + scheduled backfill. DB holds only demo data today. Prerequisite for ML-08, BT-07, the screener.",
       added="2026-06-07"),
    _f("Backtest Lab dashboard page", "Dashboard", "pending", "P1", "0", "DASH-01",
       "Run the engine from the UI (date range / symbols / risk profile / threshold sliders) with per-fold / regime / time-of-day breakdowns.",
       added="2026-06-07"),
    _f("Model-edge dashboard panel", "Dashboard", "pending", "P2", "0", "DASH-06",
       "Per ML gate: trained?, OOS AUC, base rate, reliable-vs-advisory (cleared ML_GATE_MIN_AUC?).",
       added="2026-06-07"),
    _f("Live risk gauges dashboard panel", "Dashboard", "pending", "P2", "0", "DASH-07",
       "Session net vs daily limit, portfolio heat vs cap, open positions vs max, kill/pause state.",
       added="2026-06-07"),

    # ---- Phase 0 prerequisites ----
    _f("Verify the transaction-cost model", "Risk", "pending", "P1", "0", "COST-01",
       "Confirm costs.py rates vs the actual Upstox plan + 2026 SEBI/STT/stamp/GST + realistic slippage. The edge verdict hinges on this ~16 bps figure.",
       added="2026-06-07"),
    _f("Resolve open trading questions", "Risk", "pending", "P1", "0", "DEC-01",
       "Starting capital · MIS vs NRML · primary timeframe · SEBI RA timing — drive risk-based sizing.",
       added="2026-06-07"),
    _f("Spec new dashboard pages in DASHBOARD.md", "Dashboard", "done", "P2", "0", "DOC-01",
       "Analytics page spec added; Backtest Lab / model-edge / risk-gauges still to spec when built.",
       added="2026-06-07", completed="2026-06-07"),
    _f("Pin a reproducible environment", "Testing", "pending", "P2", "0", "ENV-01",
       "pyproject says Python ≥3.11 but the venv is 3.9.6; xgboost needs libomp. Rebuild on a declared interpreter, add statsmodels, document one-command setup.",
       added="2026-06-07"),
    _f("Document UTC-store / IST-session data convention", "Data", "pending", "P2", "0", "CONV-01",
       "So the DATA-01 pipeline follows it; segregate/clear demo data so it never mixes with real.",
       added="2026-06-07"),
    _f("Confirm intraday shortability / borrow", "Risk", "pending", "P2", "0", "SHORT-01",
       "The backtest now trades shorts and assumes any name is shortable (MIS).",
       added="2026-06-07"),

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # Phase 0.E \u2014 Data backfill + model training track (Jun 2026)
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    _f("Analytics Token wired into settings + backfill scripts", "Data", "done", "P0", "0",
       notes="ANALYTICS_TOKEN in .env.example, config/settings.py, data/upstox_history.py. "
             "get_api_client() prefers it over LIVE_ACCESS_TOKEN. CLI adds --universe flag for 750-symbol backfill.",
       added="2026-06-08", completed="2026-06-08"),
    _f("Generate Analytics Token + 2-year 5-min backfill (750 symbols)", "Data", "in_progress", "P0", "0",
       notes="Generate at developer.upstox.com \u2192 Analytics tab. "
             "Run: python data/upstox_history.py --universe --days 730 --tf 5min. Est: 2\u20134 hrs overnight.",
       added="2026-06-08"),
    _f("Train ML models on real data (macro + micro XGBoost)", "ML/RL", "pending", "P0", "0", "ML-08",
       "Run scripts/train_macro.py + train_micro.py after backfill. Gate: OOS AUC \u2265 0.53. Add CalibratedClassifierCV (isotonic) before saving.",
       added="2026-06-08"),
    _f("Train RL entry + exit agents on replay episodes", "ML/RL", "pending", "P0", "0",
       "Run Action Replay on 60+ dates \u2192 build trade_log \u2192 train_rl_exit.py + train_rl_entry.py. "
       "Do NOT activate RL in live until \u2265 500 training episodes.",
       added="2026-06-08"),
    _f("Walk-forward validation on real data (Phase 0 exit gate)", "Backtest", "pending", "P0", "0", "BT-07",
       "Run scripts/run_backtest.py --days 500 --walk-forward on real candles. "
       "Gate: Sharpe > 0.8, net win-rate \u2265 50% on \u2265 150 OOS days. Unlocks Phase 1 paper trading.",
       added="2026-06-08"),

    # ---- Backburner: newly discovered API capabilities (IDEAS_ADVANCED \u00a712) ----
    _f("Exit All Positions API in circuit breaker", "Risk", "pending", "P1", "1",
       notes="POST /v2/order/positions/exit \u2014 single call flattens all open positions. "
             "Wire into risk/circuit_breaker.py on DAILY_LOSS_LIMIT breach. Only works during market hours.",
       added="2026-06-08"),
    _f("Corporate Actions calendar \u2014 suppress signals on ex-date", "Risk", "pending", "P2", "2",
       "GET /v2/fundamentals/{isin}/corporate-actions \u2192 skip all signals on ex-dividend/split date (mechanical price drop = false short signal).",
       added="2026-06-08"),
    _f("PCR as intraday regime modifier", "Signals", "pending", "P2", "3",
       "GET /v2/market/pcr \u2192 PCR > 1.3 = contrarian long bias, < 0.7 = contrarian short. "
       "Session-level modifier in ensemble/aggregator.py.",
       added="2026-06-08"),
    _f("Market Holidays + Exchange Status gating", "Data", "pending", "P2", "1",
       "GET /v2/market/status + /v2/market/holidays \u2014 gate live runner on actual status; "
       "auto-skip holidays in backfill loop instead of hitting empty API responses.",
       added="2026-06-08"),
    _f("FII/DII data via Upstox API (replace NSE scraper)", "Data", "pending", "P2", "3",
       "GET /v2/market/fii + /v2/market/dii \u2192 pre-market session bias modifier. "
       "Replaces NSE website scraping with a clean first-party API call in screener/daily_screener.py.",
       added="2026-06-08"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict]:
    with _lock:
        if not STORE_PATH.exists():
            STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STORE_PATH.write_text(json.dumps(_SEED, indent=2), encoding="utf-8")
            return list(_SEED)
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8")) or []
        except Exception:
            return list(_SEED)


def _save(items: list[dict]) -> None:
    with _lock:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
        import os
        os.replace(tmp, STORE_PATH)


def sync_seed() -> list[dict]:
    """
    Reconcile the on-disk tracker with the (code-of-record) `_SEED` so the dashboard
    Roadmap reflects newly-added/fixed items WITHOUT clobbering manual edits:
      • seed items missing by id are appended (new work shows up),
      • seed items still untouched since the original seed date (`updated_at <= _T0`)
        are refreshed to the seed's current status/notes (stale items flip to done),
      • anything the user edited via the UI (a later `updated_at`) is left alone.
    Idempotent — only writes when something actually changed.
    """
    items = _load()
    by_id = {it["id"]: it for it in items}
    changed = False
    for s in _SEED:
        cur = by_id.get(s["id"])
        if cur is None:
            items.append(dict(s))
            changed = True
            continue
        if str(cur.get("updated_at", ""))[:10] <= _T0:
            for k in ("status", "category", "priority", "phase", "notes", "issue_ref", "completed_at"):
                if cur.get(k) != s.get(k):
                    cur[k] = s.get(k)
                    changed = True
    if changed:
        _save(items)
    return items


# ── Public API ────────────────────────────────────────────────────────────────

def list_features() -> list[dict]:
    return sync_seed()


def stats() -> dict:
    items = sync_seed()
    by_status: dict[str, int] = {"done": 0, "in_progress": 0, "pending": 0}
    by_category: dict[str, dict] = {}
    for it in items:
        st = it.get("status", "pending")
        by_status[st] = by_status.get(st, 0) + 1
        cat = it.get("category", "Other")
        c = by_category.setdefault(cat, {"done": 0, "in_progress": 0, "pending": 0, "total": 0})
        c[st] = c.get(st, 0) + 1
        c["total"] += 1
    total = len(items)
    done = by_status.get("done", 0)
    return {
        "total":        total,
        "by_status":    by_status,
        "by_category":  by_category,
        "pct_complete": round(100.0 * done / total, 1) if total else 0.0,
    }


def add_feature(title: str, category: str = "Other", status: str = "pending",
                priority: str = "", phase: str = "", notes: str = "",
                issue_ref: str = "") -> dict:
    items = _load()
    fid = _slug(title) or f"feat-{int(datetime.now().timestamp())}"
    base = fid
    n = 1
    existing = {it["id"] for it in items}
    while fid in existing:
        n += 1
        fid = f"{base}-{n}"
    today = datetime.now(timezone.utc).date().isoformat()
    item = {
        "id": fid, "title": title, "category": category, "status": status,
        "priority": priority, "phase": phase, "issue_ref": issue_ref, "notes": notes,
        "added_at": today,
        "completed_at": today if status == "done" else None,
        "updated_at": _now(),
    }
    items.append(item)
    _save(items)
    return item


def update_feature(fid: str, **changes) -> dict | None:
    items = _load()
    today = datetime.now(timezone.utc).date().isoformat()
    found = None
    for it in items:
        if it["id"] == fid:
            for k in ("title", "category", "status", "priority", "phase", "notes", "issue_ref"):
                if k in changes and changes[k] is not None:
                    it[k] = changes[k]
            if changes.get("status") == "done" and not it.get("completed_at"):
                it["completed_at"] = today
            if changes.get("status") and changes.get("status") != "done":
                it["completed_at"] = None
            it["updated_at"] = _now()
            found = it
            break
    if found:
        _save(items)
    return found


def delete_feature(fid: str) -> bool:
    items = _load()
    new_items = [it for it in items if it["id"] != fid]
    if len(new_items) != len(items):
        _save(new_items)
        return True
    return False
