# AlgoTrading — Component Inventory

*Use this doc to track what exists, what phase it belongs to, and how to retrieve/activate it when needed.*
*Last updated: June 2026.*

---

## How to Read This Doc

- **Status column**: `active` = running in live/backtest now | `coded` = exists but dormant | `stub` = placeholder only | `missing` = not built
- **Retrieve when**: what condition triggers bringing this component back
- **Archive path**: where the file was moved if archived from the working tree

---

## Phase 0 — Active Now (Keep in Working Tree)

These are the components needed to run the current backtest and (once edge is proven) paper trading.

### Data Layer

| Component | File | What It Does | Status |
|---|---|---|---|
| SQLite data store | `data/db.py` | Thread-safe WAL store for candles, ticks, trades | active |
| Upstox live feed | `data/upstox_feed.py` | WebSocket ticks + wall-clock bar aggregation | active |
| Upstox historical | `data/upstox_history.py` | REST API backfill (1min–1day OHLCV) | active |
| Instrument metadata | `data/instruments.py` | ISIN / token mapping for Upstox | active |
| NSE equity keys | `data/nse_eq_keys.json` | Upstox instrument keys for NSE equities | active |
| DB schema | `data/schema.sql` | SQLite DDL (candles, ticks, trades, option_chain) | active |

### Features

| Component | File | What It Does | Status |
|---|---|---|---|
| 80-feature engine | `features/indicators.py` | All indicators: momentum, trend, volatility, volume, session | active |

### Phase 1 Signals

| Component | File | What It Does | Weight | Status |
|---|---|---|---|---|
| VWAP breakout | `signals/technical/vwap_breakout.py` | VWAP cross + EMA + volume + ADX | 0.40 | active |
| RSI momentum | `signals/technical/rsi_momentum.py` | RSI extremes + EMA trend + volume | 0.35 | active |
| Mean reversion | `signals/technical/mean_reversion.py` | BB %B + RSI z-score at genuine extremes | 0.25 | active |
| Signal base class | `signals/base.py` | Abstract base + enums (Direction, Regime) | — | active |

### Ensemble & Sizing

| Component | File | What It Does | Status |
|---|---|---|---|
| Signal aggregator | `ensemble/aggregator.py` | Weighted sum + regime bonus → composite score | active |
| Position sizer | `ensemble/position_sizing.py` | Score tier → lot size; Kelly; heat/regime de-risking | active |

### Risk Controls

| Component | File | What It Does | Status |
|---|---|---|---|
| Circuit breaker | `risk/circuit_breaker.py` | Daily loss halt, blackout windows, kill switch, pause | active |
| Correlation guard | `risk/correlation_guard.py` | Sector cap + return-correlation cap on open positions | active |

### Live Execution

| Component | File | What It Does | Status |
|---|---|---|---|
| Live runner | `live/runner.py` | Main loop: bar events → signals → ensemble → orders | active |
| OpenAlgo client | `live/openalgo_client.py` | REST wrapper: place, poll, close orders via OpenAlgo | active |
| Entry decision logic | `live/decision.py` | Pure entry logic shared by live + replay | active |

### Backtest

| Component | File | What It Does | Status |
|---|---|---|---|
| Backtest engine | `backtest/engine.py` | Walk-forward event-driven simulator | active |
| Run backtest script | `scripts/run_backtest.py` | CLI trigger for backtest | active |

### Analytics & Costs

| Component | File | What It Does | Status |
|---|---|---|---|
| Cost model | `analytics/costs.py` | Indian intraday cost model; entry cost filter | active |
| PnL tracker | `analytics/pnl_tracker.py` | Daily P&L, win-rate, expectancy, Sharpe, Kelly inputs | active |

### Screener (Pre-Market)

| Component | File | What It Does | Status |
|---|---|---|---|
| Daily screener | `screener/daily_screener.py` | Ranks universes, outputs `daily_watchlist.json` | coded (not scheduled) |
| Ranking features | `screener/ranking_features.py` | Pure-numpy ranking metrics, composite score formula | active |
| Universe fetcher | `screener/universe_fetcher.py` | NSE index constituents (currently curated static list) | coded |
| Universe definitions | `screener/universe.py` | Named universes: Nifty 50/100/500/F&O eligible | active |
| Run screener script | `scripts/run_screener.py` | CLI trigger (run manually at 9:00 IST for now) | active |

### Config & Control

| Component | File | What It Does | Status |
|---|---|---|---|
| Settings | `config/settings.py` | Central config: instruments, thresholds, weights, paths | active |
| Risk profiles | `config/risk_profiles.py` | LOW/MEDIUM/HIGH sizing caps, leverage, stop tiers | active |
| Control plane | `config/control.py` | JSON-based IPC: kill/pause/weights from API to runner | active |
| Universes map | `config/universes.json` | Strategy → universe mapping | active |

### Dashboard

| Component | File | What It Does | Status |
|---|---|---|---|
| FastAPI backend | `dashboard/api/main.py` | API server (port 8000, async) | active |
| Feature store | `dashboard/api/feature_store.py` | Shared feature cache for dashboard requests | active |
| System routes | `dashboard/api/routes/system.py` | /status, /scan, /control | active |
| Signal routes | `dashboard/api/routes/signals.py` | /signals, /ensemble, /regime | active |
| Position routes | `dashboard/api/routes/positions.py` | /positions | active |
| Trade routes | `dashboard/api/routes/trades.py` | /trades, /daily-stats, /equity-curve | active |
| Backtest routes | `dashboard/api/routes/backtest.py` | /backtest/run, /backtest/results | active |
| Analytics routes | `dashboard/api/routes/analytics.py` | /analytics/summary, /whatif, /data-health, /r-multiples | active |
| Feature routes | `dashboard/api/routes/features.py` | /features, /feature/{name} | active |
| Models routes | `dashboard/api/routes/models.py` | /models/status | active |
| React UI | `dashboard/ui/` | Full React 19 + Vite frontend | active |

### Utility Scripts

| Component | File | What It Does | Status |
|---|---|---|---|
| Seed demo data | `scripts/seed_demo_data.py` | Populate SQLite with synthetic data for dev | active |
| Env diagnostic | `scripts/diag_env.py` | Check dependencies, API keys, DB | active |
| Setup verify | `scripts/verify_setup.py` | Full system setup check | active |
| Token refresh | `scripts/refresh_token.py` | Refresh Upstox OAuth2 daily token (manual) | active |
| Universe refresh | `scripts/refresh_universe.py` | Update NSE index constituent lists | active |
| Clean candles | `scripts/clean_non_upstox_candles.py` | Remove non-Upstox data from DB | active |

---

## Phase 2 — Coded, Not Active (Archived)

These exist but are not needed until Phase-1 signals show a cost-beating edge.

### ML Gate Signals

| Component | Archive Path | What It Does | Retrieve When |
|---|---|---|---|
| Macro model | `archive/signals/ml/macro_model.py` | XGBoost long-term trend/regime signal | Phase-1 backtest shows +EV; train on real data |
| Micro model | `archive/signals/ml/micro_model.py` | XGBoost intrabar microstructure entry confirmation | Same as macro |
| Regime detector | `archive/signals/ml/regime_detector.py` | HMM-like classifier: TRENDING/MEAN_REVERTING/CHOPPY | Needed for regime-gated entry |
| Strategy outcomes | `archive/signals/ml/strategy_outcomes.py` | Per-strategy Win/Loss labels from trade log | After ≥200 real paper trades |

### ML Training Scripts

| Component | Archive Path | What It Does | Retrieve When |
|---|---|---|---|
| Train macro | `archive/models/train_macro.py` | Train macro XGBoost on 180d daily candles | After DATA-01 (real candles) |
| Train micro | `archive/models/train_micro.py` | Train micro XGBoost on 5-min bars | Same |
| Train outcomes | `archive/models/train_outcomes.py` | Train per-strategy outcome models from trade log | After 200+ paper trades |
| Daily retrain script | `archive/scripts/retrain_daily.py` | Post-market: retrain all models + promote | After ML gates are activated |
| Model validation | `archive/models/validation.py` | Purged splits, embargo periods | Needed for any ML training |
| Model promotion | `archive/models/promotion.py` | Champion/challenger OOS gate + atomic swap | Needed for any ML training |
| Data loader | `archive/models/_data_loader.py` | Load candles + features for model training | Needed for any ML training |

### RL Agents

| Component | Archive Path | What It Does | Retrieve When |
|---|---|---|---|
| RL entry agent | `archive/models/rl_entry_agent.py` | Q-learning: veto vs allow entry based on VIX/regime/win-rate | ≥500 paper trading entry decisions |
| RL exit agent | `archive/models/rl_exit_agent.py` | Q-learning: HOLD/EXIT/TIGHTEN_SL on open position | ≥500 completed trades |
| Train RL entry | `archive/models/train_rl_entry.py` | Train entry agent from replay decisions | Same as above |
| Train RL exits | `archive/models/train_rl_on_journeys.py` | Train exit agent on trade journeys | Same as above |

### Replay Engine (for RL Training)

| Component | Archive Path | What It Does | Retrieve When |
|---|---|---|---|
| Replay engine | `archive/replay/engine.py` | Full-fidelity historical sim; generates trade log for RL | When starting RL agent training |

### Pairs / Stat-Arb Strategies

| Component | Archive Path | What It Does | Retrieve When |
|---|---|---|---|
| Cointegration scanner | `archive/signals/pairs/cointegration_scanner.py` | Johansen test, hedge ratio, spread dynamics | Phase 2: after multi-leg order routing built |
| Pairs signal | `archive/signals/pairs/pairs_signal.py` | Z-score on spread; entry/exit on extremes | Same |
| Pairs book | `archive/signals/pairs/pairs_book.py` | Health-gated parallel strategy manager | Same |
| Pairs risk | `archive/risk/pairs_risk.py` | Cointegration drift monitor, halt on persistent break | Same |

### Theta / Options Strategies

| Component | Archive Path | What It Does | Retrieve When |
|---|---|---|---|
| Weekly straddle | `archive/signals/theta/weekly_straddle.py` | ATM short straddle entry/exit/sizing | Phase 2: after option chain data + multi-leg routing |
| Theta book | `archive/signals/theta/theta_book.py` | Risk-gated straddle manager | Same |
| Hedge manager | `archive/signals/theta/hedge_manager.py` | Delta/gamma hedging for short option book | Same |
| Theta risk | `archive/risk/theta_risk.py` | Gamma/vega exposure caps | Same |

### Margin Data (needed for MIS leverage)

| Component | Archive Path | What It Does | Retrieve When |
|---|---|---|---|
| Margin module | `archive/data/margin.py` | MIS margin multiplier cache per stock | When USE_MARGIN=true |
| Margin data | `archive/data/margin_multipliers.json` | Cached per-stock intraday leverage from Upstox | Same |
| Fetch margin script | `archive/scripts/fetch_margin_multipliers.py` | Fetch and cache MIS limits from Upstox | Same |

### Analytics

| Component | Archive Path | What It Does | Retrieve When |
|---|---|---|---|
| Discord/Telegram notify | `archive/analytics/discord_notify.py` | EOD P&L summary notifications | When alert integration needed |

### Dashboard Routes (Phase 2)

| Component | Archive Path | What It Does | Retrieve When |
|---|---|---|---|
| Replay route | `archive/dashboard/api/routes/replay.py` | /replay/run — run action replay from UI | When RL training activated |

### Phase 2 Test Scripts

| Component | Archive Path | What It Does |
|---|---|---|
| test_books.py | `archive/scripts/test_books.py` | Pairs/theta book logic |
| test_phase2_strategies.py | `archive/scripts/test_phase2_strategies.py` | Pairs + theta integration |
| test_rl_agents.py | `archive/scripts/test_rl_agents.py` | RL entry/exit agent |
| test_rl_exit_agent.py | `archive/scripts/test_rl_exit_agent.py` | Exit agent Q-learning |
| test_runner_ml_gates.py | `archive/scripts/test_runner_ml_gates.py` | Runner ML gate integration |
| test_ml_gate_edge.py | `archive/scripts/test_ml_gate_edge.py` | ML gate veto logic |
| test_ml_train.py | `archive/scripts/test_ml_train.py` | Training pipeline leakage check |
| test_ml_validation.py | `archive/scripts/test_ml_validation.py` | Purged splits, embargo |
| test_macro_model.py | `archive/scripts/test_macro_model.py` | Macro model smoke test |
| test_micro_model.py | `archive/scripts/test_micro_model.py` | Micro model smoke test |
| test_theta_sizing.py | `archive/scripts/test_theta_sizing.py` | Theta delta-hedge sizing |
| test_pairs_fixes.py | `archive/scripts/test_pairs_fixes.py` | Cointegration scanner |

---

## Phase 3 — Not Started (Ideas Only)

Nothing coded yet. Listed here so it can be built when ready.

| Feature | Where It Would Go | What It Needs |
|---|---|---|
| FinBERT news sentiment | `signals/news/finbert_signal.py` | HuggingFace `ProsusAI/finbert`; RSS/newsapi feed |
| NSE events (earnings, FII, bulk deals) | `screener/catalyst_detector.py` (stub exists) | NSE event data source (nsepython or manual) |
| Options flow signals (PCR, OI, IV skew) | `signals/options_flow/` | Live NSE option chain data |
| Sector breadth confirmation | `signals/technical/sector_breadth.py` | Nifty sector indices from Upstox |

`screener/catalyst_detector.py` is a stub that exists in the working tree — it reads event flags but doesn't fetch real events yet.

---

## Phase 4 — Not Started

| Feature | Where It Would Go | What It Needs |
|---|---|---|
| LLM trading agents | `agents/` | Anthropic Claude or similar; tool-use wiring |
| Auto alpha discovery | `research/` | Feature generation + evaluation pipeline |

---

## Documentation Inventory

All docs kept in `docs/`. None archived — they are reference material regardless of phase.

| Doc | What It Covers | Keep? |
|---|---|---|
| `docs/ARCHITECTURE.md` | System design, component map, data flows | Yes |
| `docs/SIGNALS.md` | All signal formulas, 80-feature list, thresholds | Yes |
| `docs/DATA.md` | Data sources, SQLite schema, backfill pipeline | Yes — **key reference** |
| `docs/UPSTOX_API_REFERENCE.md` | Upstox SDK + OpenAlgo integration notes | Yes — **key reference** |
| `docs/KNOWN_ISSUES.md` | P0/P1/P2 bug tracker with fix directions | Yes |
| `docs/ROADMAP.md` | Phase 0–4 build plan, weekly milestones | Yes |
| `docs/DASHBOARD.md` | All 11 dashboard pages, routes, payloads | Yes |
| `docs/SEBI_COMPLIANCE.md` | Regulatory requirements | Yes |
| `docs/IDEAS_ADVANCED.md` | Ideas bank: RL, alpha research, Reddit/Twitter | Yes — archive candidate if space is tight |
| `docs/CODE_AUDIT.md` | What worked / what didn't (this audit) | Yes — this file |
| `docs/COMPONENT_INVENTORY.md` | Component tracker (this file) | Yes — this file |
| `MASTER_PLAN.md` | Executive summary, decision log, status | Yes |
| `README.md` | Quick-start guide | Yes |

---

## How to Activate an Archived Component

1. Copy the file from `archive/` back to its original path in the working tree.
2. Check [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for any open issues tagged to that component.
3. Run the corresponding test script from `scripts/` (or restore it from `archive/scripts/`).
4. If it's a signal: add it to `ensemble/aggregator.py` with its weight.
5. If it's an ML model: run the training script and verify AUC > 0.53 OOS before activating the gate.
6. If it's a strategy book (pairs/theta): wire the execution path in `live/runner.py` and test with paper mode first.

---

## Quick Reference: What to Restore for Common Goals

| Goal | Restore These |
|---|---|
| **Train ML gate models** | `archive/signals/ml/`, `archive/models/validation.py`, `archive/models/promotion.py`, `archive/models/_data_loader.py`, `archive/models/train_macro.py`, `archive/models/train_micro.py` |
| **Activate RL agents** | `archive/models/rl_entry_agent.py`, `archive/models/rl_exit_agent.py`, `archive/replay/engine.py`, `archive/models/train_rl_entry.py`, `archive/models/train_rl_on_journeys.py` |
| **Add pairs trading** | `archive/signals/pairs/`, `archive/risk/pairs_risk.py` + build multi-leg order routing |
| **Add theta/options** | `archive/signals/theta/`, `archive/risk/theta_risk.py`, option chain data source |
| **Enable margin leverage** | `archive/data/margin.py`, `archive/data/margin_multipliers.json`, `archive/scripts/fetch_margin_multipliers.py` |
| **Add EOD alerts** | `archive/analytics/discord_notify.py` |
| **Daily model retraining** | All ML components above + `archive/scripts/retrain_daily.py` |
