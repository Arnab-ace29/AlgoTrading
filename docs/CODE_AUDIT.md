# AlgoTrading — Code Audit: What Worked and What Didn't

*Last updated: June 2026. Based on full codebase review post Phase 0 cleanup.*

---

## The One-Line Summary

The **infrastructure is solid and all safety bugs are fixed**, but the Phase-1 strategy has no cost-beating edge: 1.15 bps gross signal vs 16.3 bps round-trip costs. The system works; the *strategy* doesn't pay.

---

## What Worked Well

### Infrastructure

| Component | Why It Works |
|---|---|
| **SQLite WAL data layer** (`data/db.py`) | Thread-local connections, concurrent readers + single writer, no segfaults. Migrated from DuckDB which crashed under threads. |
| **Event-driven live loop** (`live/runner.py`) | Signals fire on bar-close events, not fixed 60s timers. Kill switch reacts in ~1 second. |
| **Control plane** (`config/control.py`) | Runner polls a JSON file each loop. Dashboard writes to the same file. No shared process state, no race conditions. |
| **Cost model** (`analytics/costs.py`) | Complete Indian intraday costs: brokerage, STT, stamp, exchange, SEBI, GST, slippage. Entry filter skips trades that can't clear round-trip costs. |
| **Walk-forward backtest engine** (`backtest/engine.py`) | Per-symbol independent simulations (no cross-symbol contamination). Intrabar SL/target fills at stop/target price, not bar close. Real risk-based position sizing. |
| **Purged ML splits** (`models/validation.py`) | Per-symbol, chronological, with embargo periods. No time-leakage. No `bfill`. |
| **Champion/challenger promotion** (`models/promotion.py`) | Models only promoted when OOS holdout AUC improves. Atomic file swap. No in-sample overfitting path. |
| **Session-anchored VWAP** (`signals/technical/vwap_breakout.py`) | Resets at 9:15 IST daily. Earlier version rolled across days → meaningless signal. |
| **Net-of-cost PnL everywhere** (`analytics/pnl_tracker.py`) | Kelly multiplier, win-rate, session halt all use net PnL. Earlier version used gross PnL → Kelly sizes were lying. |
| **Risk-based position sizing** (`ensemble/position_sizing.py`) | `shares = risk_budget × conviction ÷ stop_distance`. Earlier version placed flat 1-share; that's not sizing, it's noise. |
| **Risk controls** (`risk/circuit_breaker.py`, `risk/correlation_guard.py`) | Daily loss halt, kill switch (flattens all + halts entries), sector cap, return-correlation cap. All wired correctly. |
| **80-feature engine** (`features/indicators.py`) | NaN-safe. UTC→IST session conversion. All 80 features producing valid values. |
| **Test suite** (`scripts/test_*.py`) | 87 tests passing. Covers backtest correctness, ML leakage, feed aggregation, fill confirmation, concurrency, risk controls. |

### Bugs That Were Found and Fixed

All bugs below were discovered during the June 2026 audit and fixed.

#### P0 (Dangerous — would have caused live losses or crashes)

| Bug ID | What Was Wrong | How It Was Fixed |
|---|---|---|
| LIVE-01 | Exit order failure silently left live position open | Only mark position closed after confirmed fill; retry + escalate on failure |
| LIVE-02 | Kill switch logged intent but didn't flatten positions or halt the loop | Kill switch now calls `_flatten_all()` and halts entry loop immediately |
| LIVE-03 | PnL booked on order *accept*, not *fill* — all PnL numbers were fictional | Poll order status to terminal fill state; book real filled qty + avg price |
| LIVE-04 | Crash/restart left orphaned positions with no record | Reconcile from DB on startup; re-register open positions |
| LIVE-05 | Daily loss limit only checked at entry, not during position monitor | Monitor checks limit every second; halts + flattens the moment limit is breached |
| LIVE-06 | DuckDB connection shared across threads → segfault under load | Migrated entire operational store to SQLite with WAL mode + thread-local connections |
| CTRL-01 | Dashboard kill/pause/weights controls never reached the runner | Control plane: runner polls JSON file each loop; API writes to same file |
| RL-05 | RL entry agent vetoed ~100% of live entries (all unseen state cells) | Agent is now permissive on unseen cells; falls back to rule-based decision |
| GAP-01 | No pre-market screener existed at all | Built `screener/` module + `scripts/run_screener.py` |

#### P1 (Correctness — wrong results, silent wrong behaviour)

| Bug ID | What Was Wrong | How It Was Fixed |
|---|---|---|
| ML-01/02/03 | XGBoost training leaked future data (global shuffle, `bfill` across symbols) | Per-symbol purged splits, chronological order, no forward-fill across time |
| BT-01–04 | Used vectorbt incorrectly; concatenated multi-symbol bars; fills at close price; flat 1-share sizing | Rewrote as event-driven custom simulator with per-symbol runs, real fills, real sizing |
| FEAT-01 | VWAP accumulated across days, not session-anchored | Reset VWAP accumulator at 9:15 IST each day |
| FEAT-02 | NaN features silently coerced to 0 (masked missing data as signal) | `feat()` helper preserves NaN vs 0.0 distinction |
| FEAT-03 | Session time features computed in UTC, not IST | Convert bar timestamps to IST before all session math |
| SIZE-01 | Position sizer floored at 1 lot, preventing full de-risking | Sizer can now stand down to 0 lots |
| SIZE-04 | All positions were 1 share regardless of risk or conviction | Risk-based sizing: `shares = risk_budget × conviction ÷ stop_distance` |
| PnL-02 | Win/loss tracking and Kelly formula used gross PnL | Switched to net-of-cost PnL for all performance tracking |
| LIVE-07 | Orders booked on "accept" status; partial fills ignored | Poll to terminal status; book real filled qty; track and handle partial exits |
| BT-05 | Backtest was long-only; filled at bar close (look-ahead) | SHORT direction added; fills at next-bar-open |
| AGG-01 | Regime bonus could flip signal direction | Regime bonus is additive only; cannot change sign of composite score |
| AGG-02 | Composite score normalised over all signals, not just contributing ones | Normalise only over signals that produced a non-zero score this bar |
| SIG-01 | Mean-reversion signal fired on mild extremes, not genuine BB/RSI extremes | Added extremes gate: BB %B < 0.05 or > 0.95 AND RSI < 25 or > 75 |
| THETA-01 | Delta hedge lot calculation used wrong index | Fixed index reference in hedge size formula |
| PAIRS-01/02 | Pairs health check didn't halt on persistent cointegration break | Added persistent-break counter; halts after N consecutive breaks |

---

## What Doesn't Work

### The Core Problem: No Cost-Beating Edge

The Phase-1 ensemble was backtested on 6 Nifty-50 names over ~57 trading days (5-min candles, Mar–Jun 2026). Results:

| Metric | Old (1-share flat) | Current (risk-based sizing) | Target |
|---|---|---|---|
| Net PnL | +₹43 | **−₹2,425** | > 0 |
| Sharpe ratio | 0.46 | **−6.1** | > 0.8 |
| Profit factor | 1.14 | **0.49** | > 1.0 |
| Gross edge | — | **1.15 bps of notional** | — |
| Round-trip costs | — | **16.3 bps of notional** | — |
| **Verdict** | Looked OK | **No edge** | **Edge > costs** |

The old 1-share flat sizing made the numbers look acceptable — but it was meaningless because position size had no relation to risk. With real sizing, the problem is visible: the signals generate about 1 bp of alpha and the market takes 16 bps in costs.

**Root causes (diagnosed, not yet fixed):**
- SL at 1.5×ATR is too tight for 5-min bar noise → 71% of stops hit before target
- No cost-aware trade selection (many small-edge trades that can never clear costs)
- Signals fire too often in choppy regimes where there is no trend

### Blockers Preventing Paper/Live Trading

| Blocker | What's Missing | Effort to Fix |
|---|---|---|
| **No real data** | Only demo synthetic data exists. ML models untrained. Walk-forward not validated. | 2–4 hours to fetch + store via Upstox HistoryV3 |
| **No cost-beating edge** | Phase-1 ensemble is net-negative after costs on available data | 1–3 weeks of backtesting + parameter tuning |
| **No broker-side OCO** | SL/target orders only live in the runner process. Don't survive a crash. | 3–5 days (depends on broker API support) |

### Open P2 Issues (Robustness)

| Issue | Description | Status |
|---|---|---|
| TOKEN-01 | Raw OAuth auth code stored as token instead of exchanging for access token | Open |
| WATCH-01 | No watchdog on the WebSocket feed or main loop; dead feed not alerted | Open |
| OCO-01 | No bracket/OCO orders at exchange level; stops are process-level only | Open |
| COST-01 | Cost model rates from early 2026; may need updating | Not verified |

### Incomplete Features (Code Exists, Doesn't Run End-to-End)

| Feature | Status | What's Missing |
|---|---|---|
| ML gate models (macro, micro) | Code complete; models never trained on real data | Real historical candles → training run |
| RL entry agent | Code complete; permissive on unseen states | ≥500 entry decisions from real replay runs |
| RL exit agent | Code complete, trained on demo; **not wired into live exits** | Activation + wiring into position monitor |
| Pairs trading | Signal + risk code complete; not in live runner | Multi-leg order routing |
| Theta / short straddle | Code complete; not in live runner | Multi-leg order routing + option chain data |
| Daily screener | Code complete; not scheduled | Cron at 9:00 IST |
| NSE index constituents | Curated static list | nsepython integration for live Nifty 50/100/500 |
| OAuth token refresh | Manual `scripts/refresh_token.py` | Automation / server-side token exchange |
| Dashboard Lab page | Backtest results viewable via API; no UI page | Frontend page (DASH-01) |

### Not Started (Phase 3–4)

These were planned but not yet begun. No code exists.

| Feature | Phase | Why Not Started |
|---|---|---|
| FinBERT news sentiment | 3 | Needs HuggingFace model + RSS scrapers |
| NSE events (earnings, FII, bulk deals) | 3 | Needs NSE event data source |
| Options flow signals (PCR, OI, IV) | 3 | Needs live option chain data |
| LLM agents / TradingAgents pattern | 4 | Not started |
| Auto alpha discovery | 4 | Not started |

---

## What to Do Next (Priority Order)

1. **Get real data** — Fetch 2 years of 5-min + daily candles via Upstox HistoryV3 for Nifty 50/100. Store in SQLite. This unblocks everything.
2. **Tune the edge** — Widen SL (try 2.0–3.0×ATR), add time-stop, implement cost-aware score threshold. Validate OOS over ≥150 days.
3. **Broker-side OCO** — Check Upstox bracket order API. Implement before going live.
4. **Train ML gates** — After step 1. Run `scripts/train_macro.py` + `scripts/train_micro.py`. Only activate if AUC > 0.53 OOS.
5. **Paper trade** — Only after step 2 shows net-positive on walk-forward backtest.
