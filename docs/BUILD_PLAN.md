# Build Plan — Strategy Analysis + Code & Test Roadmap

> Companion to `docs/STRATEGY_RESEARCH.md` (the spec) and `docs/CODEBASE_MAP.md` (what exists).
> This doc: (1) critiques the strategy and says what to **add / subtract**, (2) defines the
> target architecture, (3) lays out a phased roadmap **to code and to test**.
> Last updated: 2026-06-13

---

## Part 1 — Strategy Analysis: Add / Subtract

The 5-dimension framework is sound. The improvements below make it cheaper to compute,
harder to over-fit, and more honest under backtest. Each is tagged **[KEEP] / [SUBTRACT] /
[ADD] / [CHANGE]**.

### Subtract (reduce redundancy — the spec's own "don't triple-count" rule)

- **[SUBTRACT] ROC from Dimension 2 (Momentum).** RSI, MACD-histogram, and ROC all measure
  momentum. Keep **RSI** (level + the 78 ceiling) and **MACD-hist** (acceleration/direction).
  ROC adds a third correlated reading of the same dimension. Drop it.
- **[CHANGE] First-candle-volume in Dimension 3.** It's highly correlated with RVOL (both =
  "unusual volume"). Demote from a scored +1 to a **tiebreaker** between equal-score
  candidates, not an independent point.
- **[SUBTRACT — defer to v2] Free-float >30% and MIS-leverage ≥4× hard filters.** Hard to
  source reliably and rarely binding for Nifty 100. Market-cap + turnover filters already
  exclude the manipulation-prone names. Revisit once the core edge is proven.

### Add (documented momentum edges currently missing)

- **[ADD] Relative Strength vs Nifty — the single highest-value addition.** A stock that is
  *outperforming the index* (today intraday, and over the trailing 5–20 days) is the essence
  of momentum. Add `RS = stock_return / nifty_return` as both a **filter** (RS > 1) and a
  **ranking factor**. This is the best-supported momentum signal and we have the data for it.
- **[ADD] ATR-normalized stops & targets.** The spec uses fixed 2% SL / 1.5% trail. Replace
  with volatility-scaled levels (e.g. stop = entry − 1.5×ATR, target = entry + 3×ATR) so a
  calm stock and a wild one are risked consistently. ATR% is already computed in the Excel.
- **[ADD] Risk-based position sizing (not just allocation %).** Sizing by 20/30/50% of capital
  ignores stop distance. With 5× MIS, a 2% stop on 50% allocation ≈ **5% account risk per
  trade** — too high. Instead: fix **risk per trade = R% of capital** (e.g. 1%), then
  `qty = (R% × capital) / (entry − stop)`. Conviction score scales R (e.g. 0.5R / 1R / 1.5R),
  not raw exposure. Caps blow-up risk and makes the equity curve interpretable.
- **[ADD] Daily go/no-go regime gate (computed once at ~9:20).** Formalize the scattered VIX /
  Nifty checks into one daily switch: trade only if `VIX < threshold` and `Nifty not gapping
  down hard`. One decision, logged, instead of re-checking per stock.
- **[ADD] Benchmark comparison in every backtest.** Report strategy vs buy-and-hold Nifty over
  the same window. Momentum must beat the index **after costs** to justify the effort and risk.

### Change (make assumptions into parameters, decided by data)

- **[CHANGE] Scoring weights → parameters.** The +1/+2 point values are guesses (the spec
  admits this). Make them config, fit on the **train fold only**, validate out-of-sample.
- **[CHANGE] ORB window, RVOL threshold, VIX cutoff → parameters** swept in walk-forward.
  These are literally the spec's 8 open questions; the harness should answer them, not
  hardcode them.

### Keep (don't touch — these are the edge)

- 5-dimension confluence philosophy; VWAP as institutional anchor; OBV-divergence false-breakout
  filter; ORB entry trigger; 10:30 time-stop; the cost-aware "target 3–7% not 0.5–1%" thesis.

### Decisions this forces (need answers before/while coding)

1. **Risk per trade R%** — start at 1% of capital? (drives sizing math)
2. **ATR multiples** — 1.5×ATR stop / 3×ATR target as defaults to optimize around?
3. **Fill model for 5-min backtest** — conservative default: a stop/limit fills only if the
   **next** bar trades through it; entries fill at next-bar open with slippage. Agree?
4. **Split-adjustment** — must verify Upstox OHLCV is adjusted (see Phase 0). Blocking.

---

## Part 2 — Target Architecture

Principle: **one scoring function, shared by backtest and live**, so a validated edge can't
drift between research and production. `features/` and `strategy/` are pure (no I/O);
`backtest/` and `live/` are just two drivers feeding bars into the same scorer.

```
config/
  settings.py            # SLIMMED: paths, capital, session, tokens, strategy params
  universes.json         # (exists)
  sector_map.json        # NEW: stock → sector index (NIFTYBANK, NIFTYIT, ...)

features/
  indicators.py          # PURE funcs: session_vwap, ema, rsi, macd_hist, atr, obv,
                         #   rvol_same_window, relative_strength. In: DataFrame. Out: Series.

strategy/
  filters.py             # hard universe filters + negative disqualifiers (RSI>78, gap>5%, ...)
  score.py               # THE scorer: 5 dims → (score, direction, reasons). Params, not magic #s.
  sizing.py              # risk-based qty from (capital, R%, entry, stop)
  regime.py              # daily go/no-go gate (VIX, Nifty)

analytics/
  costs.py               # RESTORED from archive: Indian intraday round-trip cost stack

backtest/
  engine.py              # bar replay, fill model, applies score.py + sizing + costs
  metrics.py             # sharpe, sortino, max-dd, profit factor, expectancy, vs-benchmark
  walkforward.py         # train/test splits; param sweep on train, score on OOS

live/                    # (Phase 4+) paper then live; imports the SAME score.py
scripts/
  validate_data.py       # NEW: OHLC integrity, gaps, dups, split detection
  run_backtest.py        # NEW: CLI entry to run a backtest / sweep
  (existing data scripts)
```

---

## Part 3 — Roadmap (Code) with Test Gates

Each phase ends at a **gate** that must pass before the next begins. Nothing here trades real
money until Phase 5, and only after Phase 3's statistical bar is cleared.

### Phase 0 — Foundation fixes (unblock everything) ▸ ~1–2 sessions

**Code**
- [ ] Restore `analytics/costs.py` from `archive/analytics/costs.py`; verify the cost formula
      against current SEBI/NSE rates (STT, GST, brokerage, stamp, exchange txn, SEBI fee).
- [ ] Fix `data/db.py` import so `log_trade_close()` resolves `round_trip_cost` (and add a
      direct unit test so this can never silently break again).
- [ ] Slim `config/settings.py`: delete dead config (`MODELS_DIR`, `BACKTEST_RESULTS_DIR`,
      ML gates, `REGIME_WEIGHT_MAP`, old `SIGNAL_WEIGHTS`, ensemble/screener/correlation,
      OpenAlgo, dashboard, Discord-if-unused). Add a `STRATEGY` params block (R%, ATR mults,
      ORB window, RVOL/VIX thresholds, score weights).
- [ ] Rewrite `docs/DATA.md` to match the real 5-table `schema.sql`.
- [ ] Write `scripts/validate_data.py`: OHLC integrity (low ≤ open/close ≤ high), no dup
      `(symbol, tf, timestamp)`, intraday gap detection, volume>0 on liquid names, bar-to-bar
      jump > X% flag (catches unadjusted splits).
- [ ] Build `config/sector_map.json` (stock → sector index).

**Investigate (blocking decisions)**
- [ ] **Split-adjustment:** pick 3–5 stocks with known 2024–25 splits/bonuses, compare DB
      OHLCV to the corporate action. Confirm adjusted, or add an adjustment step.
- [ ] **Survivorship bias:** document the exposure; decide whether to reconstruct point-in-time
      index membership now or accept-and-annotate for v1.

**Test gate 0:** `pytest` green on cost model + db round-trip; `validate_data.py` runs clean
(or surfaces a documented, accepted list of exceptions) on the full DB.

### Phase 1 — Shared signal layer ▸ ~2–3 sessions

**Code**
- [ ] `features/indicators.py` — port proven funcs from `archive/features/indicators.py`; add
      `rvol_same_window` (today's 9:15–9:20 vs 20-day avg for that exact slot), session-anchored
      `vwap` (daily 9:15 reset), `relative_strength` vs Nifty.
- [ ] `strategy/filters.py` — hard filters + the negative-disqualifier list.
- [ ] `strategy/score.py` — the one scorer: input a per-symbol bar window + market context,
      output `ScoreResult(score, direction, dimension_breakdown, reasons)`. Weights from config.
- [ ] `strategy/sizing.py` — risk-based qty.
- [ ] `strategy/regime.py` — daily go/no-go.

**Test gate 1:**
- Unit tests per indicator vs **hand-computed golden values** (and/or `pandas-ta`/TA-Lib
  cross-check) on a tiny fixed DataFrame.
- **No-look-ahead test:** scorer fed bars up to time *t* must produce identical output whether
  or not future bars exist in the frame.
- Filter tests on synthetic rows (each disqualifier triggers exactly when expected).
- Scorer determinism: same input → same `ScoreResult`.

### Phase 2 — Backtest engine ▸ ~3–4 sessions

**Code**
- [ ] `backtest/engine.py` — chronological 5-min bar replay over the universe; at each ORB
      time, screen → score → size → simulate entry (next-bar-open + slippage), manage ATR stop
      / trail / time-stop, book net PnL via `analytics.costs`. **Reuses `strategy/score.py`
      verbatim.**
- [ ] `backtest/metrics.py` — Sharpe, Sortino, max drawdown, profit factor, expectancy, win
      rate, avg win/loss, exposure, and **vs-Nifty benchmark**.
- [ ] `backtest/walkforward.py` — rolling train/test; optimize params on train, record OOS.
- [ ] `scripts/run_backtest.py` — CLI; writes a row to `backtest_runs` + a trades CSV/tearsheet.

**Test gate 2:**
- **Golden-path integration test:** a hand-built 2-day, 2-stock fixture where the correct
  trades/PnL are known by hand → engine reproduces them exactly.
- **Look-ahead guard:** assert the engine never reads a bar with `timestamp > now`.
- **Determinism:** identical inputs → byte-identical trade log.
- **Cost reconciliation:** sum of per-trade costs == independent recompute.

### Phase 3 — Validation: answer the 8 open questions ▸ ~2–3 sessions

**Run**
- [ ] Walk-forward sweep over: ORB window {15,30,45m}, RVOL {2,2.5,3×}, VIX filter {on/off},
      score-weight sets, R% {0.5,1,1.5}.
- [ ] Produce a comparison report + tearsheet per config.
- [ ] **Monte Carlo** on trade-sequence ordering → distribution of max-drawdown.
- [ ] **Sensitivity** check: does a small param nudge collapse the edge? (over-fit smell test).

**Test gate 3 (the real go/no-go):**
- Out-of-sample **Sharpe > 1.0**, **beats buy-and-hold Nifty after costs**, max-DD tolerable,
  and edge is **stable across folds** (not one lucky window). If it fails → iterate the spec,
  do **not** proceed to live.

### Phase 4 — Paper trading ▸ 60+ trading days

**Code**
- [ ] `live/` paper harness: live/last data → same `strategy/score.py` → simulated orders →
      `trade_log` (mode=PAPER) → Discord notify → EOD `daily_performance`.
- [ ] Daily **paper-vs-backtest reconciliation**: feed the same day to both; trades must match.

**Test gate 4:** 60+ paper days; live results track backtest expectancy within tolerance.

### Phase 5 — Go live at ₹20k ▸ after Phase 4 passes

**Code**
- [ ] Broker order integration (real MIS orders), circuit breaker (daily loss cap, max
      positions, per-sector cap), guaranteed EOD square-off, kill switch.
- [ ] Start `PAPER_TRADE=true` → flip only after a final live-shadow check.

**Test gate 5:** circuit breaker + square-off proven in a forced-failure drill before real
capital; start tiny, scale only on sustained Sharpe > 1.0 live.

---

## Part 4 — Test Strategy (how we test, across all phases)

| Layer | What | How |
|---|---|---|
| **Unit** | indicators, cost model, filters, sizing | Golden values on tiny fixtures; cross-check vs `pandas-ta`/TA-Lib; known-trade → known-cost. |
| **Invariant / property** | no look-ahead, determinism, OHLC integrity | Assert scorer/engine at bar *t* ignore *>t*; same input → same output; `validate_data.py` rules. |
| **Integration** | full engine on known slice | Hand-built fixture with known trades; checkpoint the equity curve. |
| **Statistical** | does the edge survive? | Walk-forward OOS Sharpe, Monte Carlo DD, param sensitivity, benchmark beat. |
| **Reconciliation** | backtest == live | Same day → both paths → trades/PnL match within tolerance. |

**Conventions:** `pytest` under `tests/` mirroring the package layout; fixtures = small CSVs of
real candles checked into `tests/fixtures/`; deterministic seeds; CI-friendly (no network in
unit tests — mock Upstox/yfinance). Target: every `strategy/` and `analytics/` function has a test.

---

## Immediate next actions (Phase 0 kickoff)

1. Restore + verify `analytics/costs.py`; fix `db.py`; add cost unit test.
2. Slim `settings.py`; add the `STRATEGY` params block.
3. Write `scripts/validate_data.py`; run it on the DB.
4. Investigate split-adjustment (blocking) + document survivorship bias.
5. Rewrite `docs/DATA.md`.
