# ROADMAP — Phased Build Plan

> Phase-by-phase tasks with week-by-week breakdown.
> Mark tasks with ✅ when done, 🔄 when in progress, ❌ if abandoned with reason.
> IDs in (brackets) reference `docs/KNOWN_ISSUES.md`.

---

## Phase 0 — Make It Profitable + Reliable  ⬅ CURRENT PRIORITY (added 2026-06-07)

**Why this exists:** the second audit + first real backtest proved the infrastructure
is sound but the **Phase-1 ensemble has no cost-beating edge** — ~1 bp gross vs ~16 bps
round-trip costs → net −2.4% on a 3-month real sample (`KNOWN_ISSUES` → BT-EDGE). All
the safety/correctness bugs are fixed (incl. the P0 RL-veto and risk-based sizing,
SIZE-04). **Do not paper-for-record or go live until the backtest is net-positive after
costs.** Phase 0 is the work to get there.

**Exit gate (to resume Phase 1 paper/live):** walk-forward backtest **net of costs**
shows positive expectancy with **gross edge > round-trip costs** (target Sharpe > 0.8,
net win-rate ≥ 50%), validated out-of-sample on ≥ 150 days.

### 0.0 — Prerequisites (do these before/while building 0.A)
- [ ] **(COST-01)** Verify `analytics/costs.py` rates vs the actual Upstox plan + 2026 SEBI/STT/stamp/GST + realistic slippage
- [ ] **(DEC-01)** Resolve open questions: starting capital · MIS vs NRML · primary timeframe · SEBI RA timing
- [ ] **(DOC-01)** Spec the new dashboard pages in `DASHBOARD.md` (routes + payloads) before building
- [ ] **(ENV-01)** Pin a reproducible env (Python version, libomp, statsmodels, one-command setup + run)
- [ ] **(CONV-01)** Document the UTC-store / IST-session convention; segregate/clear demo data
- [ ] **(SHORT-01)** Confirm intraday shortability/borrow on the equity universe

### 0.A — Validation harness first (you can't tune what you can't measure)
- [ ] **(DATA-01)** Real data pipeline: nsepython index constituents + a daily/EOD candle source + scheduled backfill (DB currently holds only demo data)
- [~] **(BT-07)** Walk-forward auto-windowing — **engine built** (runs on short history); still needs ≥150 days of real data for trustworthy folds (depends on DATA-01)
- [x] **(BT-06)** Per-day EOD square-off in the backtest — **built** (no overnight holds; matches the live runner)
- [ ] **(BT-08)** Portfolio-realism backtest: shared capital + max-concurrent + heat cap across symbols on one timeline
- [ ] **(TEST-LEAK)** CI assertion that every feature at bar `t` uses only data ≤ `t`

### 0.B — Find the edge (iterate against the harness; validate OUT-OF-SAMPLE)
- [ ] **(EDGE-01)** Cost-aware trade selection: recalibrate score threshold to the real distribution, cap trades/symbol/day, tighten `is_cost_effective` (target move ≫ costs)
- [ ] **(EDGE-02)** Tune exit structure to 5-min (wider SL / faster trailing / partial TP / time-stop) — 71% of exits were stops
- [x] **(EDGE-03)** Correlation/sector guard (`risk/correlation_guard.py`) — **built** (sector cap + correlation cap, wired into the runner)
- [ ] **(EDGE-04)** Regime filter on entries (skip momentum in ranging names)
- [ ] **(EDGE-05)** Real session-anchored ORB signal (current `orb` feature is mislabeled)
- [ ] **(EDGE-06)** Index / sector-breadth confirmation gate — trade with the sector, not a lone correlated name (data-free breadth now; trade Bank Nifty off breadth is a later F&O step)
- [ ] **(ML-08)** Train + probability-calibrate the ML gates once DATA-01 exists (`CalibratedClassifierCV`)

### 0.C — Reliability before any real money
- [ ] **(OCO-01)** Broker-side OCO / bracket orders so stops survive a runner crash
- [ ] **(WATCH-01)** Feed/loop watchdog + heartbeat
- [ ] **(TOKEN-01)** Server-side OAuth code→token exchange

### 0.D — Dashboard to support the above
- [x] **(DASH-02)** Gross-vs-net-vs-cost headline tiles (bps) + EDGE/NO-EDGE verdict — **built** (Analytics page)
- [x] **(DASH-03)** R-multiple distribution histogram — **built**
- [x] **(DASH-04)** "What-if" simulator (cost-mult / min-score / target-only) — **built**
- [x] **(DASH-05)** Data-health / coverage panel (bars, freshness, real-vs-demo) — **built**
- [x] **(DASH-08)** PAPER/LIVE/ALL mode toggle — **built**
- [ ] **(DASH-01)** Backtest Lab page (run + per-fold/symbol/regime/exit-reason/time-of-day breakdowns)
- [ ] **(DASH-06)** Model-edge panel (per gate: trained?, OOS AUC, base rate, reliable-vs-advisory)
- [ ] **(DASH-07)** Live risk gauges (session net vs daily limit, heat vs cap, positions vs max, kill/pause state)

> Recommended order: **0.A → 0.B (loop) → 0.D in parallel for visibility → 0.C before live.**
> 0.B is a research loop, not a fixed task list — keep what survives out-of-sample, discard the rest.

### 0.E — Data Backfill + Model Training ⬅ START HERE (Jun 2026)

> **This is the single gate to everything.** ML/RL models are coded but untrained. Backtests have only run on synthetic data. Until real candle data exists at scale, nothing else in Phase 0 can be validated. Do this before any other Phase 0 work.

#### Step 1 — Analytics Token (30 min)
- [ ] Generate Analytics Token in Upstox Developer Console (1-year lifetime, no daily re-auth)
- [ ] Add `ANALYTICS_TOKEN` to `.env` and `.env.example`
- [ ] Add `ANALYTICS_TOKEN = os.getenv("ANALYTICS_TOKEN", "")` to `config/settings.py`
- [ ] Update all backfill/screener scripts to prefer `ANALYTICS_TOKEN` over `LIVE_ACCESS_TOKEN`

**Why:** The live OAuth token expires daily — unattended backfill jobs fail at midnight. The Analytics token eliminates this. It is read-only (historical + market data only, no orders).

#### Step 2 — 5-min Historical Backfill: 750 symbols × 2 years (write once, run overnight)
- [ ] Write `scripts/backfill_history.py` (or update existing) — fetches 2-year 5-min candles for all Nifty Total Market (~750) symbols via `HistoryV3Api`
- [ ] Use Analytics Token; handle rate limits with exponential backoff
- [ ] Store in SQLite `candles_5min` table (existing schema in `data/schema.sql`)
- [ ] Add progress logging: symbols done / total, bars written, estimated time remaining
- [ ] Run overnight: estimated ~2–4 hours for 750 symbols × 2 years × ~75 bars/day

**Why 2 years specifically:**
- Upstox V3 historical API maximum lookback for 5-min: 2 years
- RL training needs ≥ 500 replay episodes (= 500 trading days = ~2 years) per community benchmark in `IDEAS_ADVANCED.md §10`
- ML models (macro/micro XGBoost): 1 year is sufficient, 2 years gives better generalization
- Walk-forward needs ≥ 150 OOS days — comfortably achieved with 2 years

#### Step 3 — ML Model Training (after Step 2 completes)
- [ ] Run `python scripts/train_macro.py` — XGBoost directional gate on real 5-min features
- [ ] Run `python scripts/train_micro.py` — microstructure entry confirmation model
- [ ] Run `python scripts/train_outcomes.py` — strategy outcome models (needs ≥15 labeled trades per strategy from replay runs)
- [ ] Verify each model: `OOS AUC ≥ 0.53` (= `ML_GATE_MIN_AUC`); log AUC to `models/saved/`
- [ ] Add probability calibration: wrap trained model in `CalibratedClassifierCV(method="isotonic")` before saving (see `IDEAS_ADVANCED.md §11.2`)

#### Step 4 — RL Agent Training (after Steps 2 + 3)
- [ ] Run Action Replay on 60+ historical dates to generate `trade_log` episodes with real fills
- [ ] Run `python scripts/train_rl_exit.py` — RL exit agent on replay trade journeys
- [ ] Run `python scripts/train_rl_entry.py` — RL entry agent (needs ≥ 50 entry decisions)
- [ ] Activation threshold: do NOT enable RL in live until ≥ 500 training episodes (per `IDEAS_ADVANCED.md §10`)
- [ ] Use Trade P&L API (`GET /v2/trade/profit-loss/data` with Analytics Token) to supplement replay trade history with actual broker trade outcomes

#### Step 5 — Walk-Forward Validation (exit gate for Phase 0)
- [ ] Run `python scripts/run_backtest.py --days 500 --walk-forward` on real data
- [ ] **Gate:** net-positive after costs, Sharpe > 0.8, win-rate ≥ 50% on ≥ 150 OOS days
- [ ] Compare with/without ML gates to confirm they add edge (not reduce it)
- [ ] If gate passes → proceed to Phase 1 paper trading

**Estimated total time:** 1–2 weeks (mostly waiting for overnight backfill + training runs)

---

## Phase 1 — Rule-Based Core

**Goal:** Working intraday momentum system on NSE, backtested on 1 year of data, paper-traded for 1 week, then live with real capital.
**Duration:** Weeks 1–4
**Gate to Phase 2:** Must be profitable in live trading for at least 3 weeks OR Sharpe > 0.8 in walk-forward backtest AND ≥ 50% win rate in paper trading.
**Prerequisite (Phase 0):** the walk-forward backtest must first be **net-positive after costs** — gross edge > round-trip costs (BT-EDGE). As of 2026-06-07 it is not (1 bp gross vs 16 bps costs), so Phase 0 precedes any Phase-1 paper/live run.

---

### Week 1 — Foundation: Repo, Config, Data Layer

#### 1.1 Repo & Config Setup
- [ ] Create folder structure (see `ARCHITECTURE.md`)
- [ ] `requirements.txt` with pinned versions
- [ ] `.env.example` — template for API keys (never commit `.env`)
- [ ] `config/settings.py` — all constants, thresholds, weights, instrument list
- [ ] `config/risk_profiles.py` — LOW / MEDIUM / HIGH dataclasses

**`config/settings.py` must contain:**
```python
INSTRUMENTS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"]
TIMEFRAME_PRIMARY = "5min"
TIMEFRAMES_STORE = ["1min", "5min", "15min"]
SCORE_THRESHOLD_ENTRY = 0.65
SCORE_THRESHOLD_SIGNAL = 0.55
MAX_CONCURRENT_POSITIONS = 5
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"
BLACKOUT_OPEN_MINUTES = 15   # no trades 9:15–9:30
BLACKOUT_CLOSE_MINUTES = 30  # no trades 15:00–15:30
SIGNAL_WEIGHTS = {
    "vwap_breakout": 0.40,
    "rsi_momentum": 0.35,
    "mean_reversion": 0.25,
}
```

**`config/risk_profiles.py` must contain:**
```python
@dataclass
class RiskProfile:
    name: str
    max_daily_loss_pct: float   # % of capital
    max_trades_per_day: int
    lot_size_cap: int           # max lots per trade
    sl_atr_multiplier: float    # SL = entry ± ATR × this
    target_atr_multiplier: float
    trailing_sl_activation: float  # activate trailing after +X × ATR
    trailing_sl_lock: float        # lock in X × ATR profit

LOW    = RiskProfile("LOW",    1.0, 5,  1, 1.5, 2.5, 1.2, 0.8)
MEDIUM = RiskProfile("MEDIUM", 1.5, 8,  2, 1.5, 2.0, 1.0, 0.7)
HIGH   = RiskProfile("HIGH",   2.0, 12, 3, 1.2, 1.8, 0.8, 0.5)
```

#### 1.2 Data Layer
- [ ] `data/upstox_history.py` — fetch OHLCV for 1min/5min/15min candles via Upstox REST, last 365 days
- [ ] `data/upstox_feed.py` — WebSocket live feed (MarketDataStreamerV3), writes ticks to SQLite
- [ ] `data/nse_data.py` — nsepython: option chain, PCR, OI, index data
- [ ] `data/db.py` — SQLite helpers: `init_db()`, `write_candles()`, `read_candles()`, `upsert_ticks()`
- [ ] `data/schema.sql` — all table definitions (see `DATA.md` for full schema)
- [ ] Test: pull 1 year of 5-min candles for NIFTY + 5 Nifty 50 stocks, verify row counts

**Upstox historical candles endpoint:**
```python
# upstox-python-sdk v2.x
from upstox_client import HistoryApi
api = HistoryApi(api_client)
resp = api.get_historical_candle_data1(
    instrument_key="NSE_EQ|INE002A01018",  # RELIANCE
    interval="5minute",
    to_date="2026-06-04",
    from_date="2025-06-04",
    api_version="2.0"
)
```

**Upstox WebSocket live feed:**
```python
from upstox_client import MarketDataStreamerV3
streamer = MarketDataStreamerV3(api_client, instrument_keys, "full")
streamer.on("message", on_message_handler)
streamer.connect()
```

---

### Week 2 — Feature Engineering & Signal Framework

#### 2.1 Feature Engine (80 features, steal from AI-trader)
- [ ] `features/indicators.py` — `compute_all_features(df: pd.DataFrame) -> pd.DataFrame`

**Full 80-feature list is in `SIGNALS.md`.** Summary of categories:
- Momentum (8): RSI14, MACD, MACD signal, MACD hist, StochRSI, Williams%R, ROC10, ROC20
- Trend (9): EMA9, EMA20, EMA50, SMA200, VWAP, VWAP_dist_pct, ADX, DI_plus, DI_minus
- Volatility (6): ATR14, BB_upper, BB_lower, BB_pct_b, realized_vol_20, realized_vol_60
- Volume (5): OBV_slope, MFI14, volume_ratio (vs 20-day avg), volume_delta, volume_spike_flag
- Multi-timeframe (8): RSI14_5m, RSI14_15m, EMA20_5m, EMA20_15m, MACD_5m, VWAP_5m, VWAP_15m, ATR_15m
- Options (8): PCR, OI_change_pct, IV_atm, delta_atm, theta_pressure, gamma_atm, days_to_expiry, OI_ratio
- Session (6): mins_since_open, session_progress, is_first_hour, is_last_hour, is_power_hour, day_of_week
- Microstructure (5): bid_ask_spread, order_imbalance, trade_size_spike, volume_burst, tick_momentum
- Derived (25+): RSI divergence, MACD hist slope, VWAP std dev, price/SMA ratios, rolling correlations

**Library:** Use `ta` library for standard indicators. Custom code for VWAP, tick features, options features.

#### 2.2 BaseSignal Interface
- [ ] `signals/base.py`

```python
from abc import ABC, abstractmethod
import pandas as pd

class BaseSignal(ABC):
    name: str = ""
    weight: float = 0.0
    phase: int = 1

    @abstractmethod
    def compute(self, df: pd.DataFrame, symbol: str) -> float:
        """Returns score in [-1.0, +1.0].
        -1.0 = strong short signal
         0.0 = neutral / no signal
        +1.0 = strong long signal
        """
        pass

    def is_ready(self, df: pd.DataFrame) -> bool:
        """Returns False if insufficient data to compute reliably."""
        return len(df) >= 50
```

#### 2.3 Three Technical Signals
- [ ] `signals/technical/vwap_breakout.py` — bullish VWAP breakout signal
- [ ] `signals/technical/rsi_momentum.py` — RSI momentum continuation signal
- [ ] `signals/technical/mean_reversion.py` — Bollinger Band mean reversion signal

**VWAP Breakout logic (from AI-trader, proven 60–100% WR in backtests):**
```
LONG conditions (need ≥3 of 4):
  close > VWAP
  RSI(14) > 55
  EMA20 > EMA50
  volume_spike OR volume_ratio > 1.5

score = conditions_met / 4.0

SHORT conditions (need ≥3 of 4):
  close < VWAP
  RSI(14) < 45
  EMA20 < EMA50
  volume_spike OR volume_ratio > 1.5
```

**RSI Momentum logic:**
```
LONG: RSI crossed above 50 (last 3 bars) AND MACD_hist > 0 AND ROC10 > 0
SHORT: RSI crossed below 50 AND MACD_hist < 0 AND ROC10 < 0
score = weighted sum of met conditions, normalized [-1, 1]
```

**Mean Reversion logic (from AI-trader — rare but high avg gain):**
```
LONG (oversold): RSI14 < 30 AND close ≤ BB_lower AND VWAP_dist_pct < -0.3%
SHORT (overbought): RSI14 > 70 AND close ≥ BB_upper AND VWAP_dist_pct > +0.3%
Only active in SIDEWAYS / LOW_VOL regime
score = 1.0 if all conditions met, 0.6 if 2/3 met
```

---

### Week 3 — Ensemble, Position Sizing, Backtest

#### 3.1 Ensemble Aggregator
- [ ] `ensemble/aggregator.py`

```python
def aggregate(signals: list[BaseSignal], df: pd.DataFrame, symbol: str,
              regime: str, weights_override: dict = None) -> float:
    weights = weights_override or settings.SIGNAL_WEIGHTS
    score = sum(weights[s.name] * s.compute(df, symbol)
                for s in signals if s.is_ready(df))
    regime_bonus = REGIME_BONUS_MAP.get(regime, 0.0)
    return score + regime_bonus
```

**Regime bonus map (Phase 1 — simple):**
```python
REGIME_BONUS_MAP = {
    "TRENDING_UP": +0.05,
    "TRENDING_DOWN": +0.03,
    "MEAN_REVERTING": 0.0,
    "CHOPPY": -0.05,  # penalize in choppy markets
}
```

#### 3.2 Position Sizer
- [ ] `ensemble/position_sizing.py`

**Score-tiered lot sizing (from AI-trader):**
```python
def get_lot_size(score: float, risk_profile: RiskProfile) -> int:
    abs_score = abs(score)
    if abs_score >= 0.75: return min(3, risk_profile.lot_size_cap)
    if abs_score >= 0.65: return min(2, risk_profile.lot_size_cap)
    return 1

def get_sl_target(entry: float, side: str, atr: float,
                  risk_profile: RiskProfile) -> tuple[float, float]:
    sl_dist = atr * risk_profile.sl_atr_multiplier
    tgt_dist = atr * risk_profile.target_atr_multiplier
    if side == "BUY":
        return entry - sl_dist, entry + tgt_dist
    return entry + sl_dist, entry - tgt_dist
```

**Trailing SL logic:**
- Activates when unrealized profit ≥ `activation × ATR`
- Locks in `lock × ATR` profit by moving SL up
- Re-evaluated every bar
- From AI-trader's backtest: trailing SL is 57% of exits, 96% profitable

#### 3.3 Risk Controls
- [ ] `risk/circuit_breaker.py`

```python
class CircuitBreaker:
    def should_halt(self, daily_pnl: float, capital: float,
                    open_positions: int) -> tuple[bool, str]:
        if daily_pnl < -(capital * risk_profile.max_daily_loss_pct / 100):
            return True, "DAILY_LOSS_LIMIT"
        if open_positions >= settings.MAX_CONCURRENT_POSITIONS:
            return True, "MAX_POSITIONS"
        if self._is_blackout_time():
            return True, "BLACKOUT_WINDOW"
        return False, ""
```

#### 3.4 vectorbt Backtest
- [ ] `backtest/engine.py` — vectorbt wrapper
- [ ] `notebooks/03_backtest_phase1.ipynb` — full backtest notebook

**Backtest requirements:**
- Load 1 year of 5-min OHLCV from SQLite
- Transaction costs: 0.05% slippage + STT (0.01% intraday equity) + brokerage (₹20/order flat for Upstox)
- Walk-forward: 4-month train / 2-month test, slide by 1 month (6 folds minimum)
- Output metrics: Total return, Annualized return, Sharpe ratio, Sortino ratio, Max drawdown, Win rate, Avg trade PnL, Profit factor, Expectancy
- Compare 3 signals individually vs combined ensemble

---

### Week 4 — OpenAlgo Setup + Live Runner + Dashboard

#### 4.1 OpenAlgo Setup
- [ ] Clone OpenAlgo: `git clone https://github.com/marketcalls/openalgo`
- [ ] Follow Upstox guide: https://docs.openalgo.in/connect-brokers/brokers/upstox
- [ ] Start Flask backend + React dashboard
- [ ] Test sandbox: place dummy orders, verify fills
- [ ] Configure Telegram bot (optional but recommended)

#### 4.2 OpenAlgo Client
- [ ] `live/openalgo_client.py` — thin wrapper around OpenAlgo REST API

```python
class OpenAlgoClient:
    def place_order(self, symbol, exchange, side, qty, product, order_type, price=None) -> str
    def modify_order(self, order_id, qty, price) -> bool
    def cancel_order(self, order_id) -> bool
    def get_positions(self) -> list[dict]
    def get_orderbook(self) -> list[dict]
    def get_funds(self) -> dict
    def get_quotes(self, symbols: list[str]) -> dict
    def square_off_all(self) -> bool
```

#### 4.3 Live Runner
- [ ] `live/runner.py` — main trading loop

**Loop logic (market hours 9:15–15:30 IST):**
```
Every 30 seconds:
  1. Fetch latest candles from SQLite (written by WebSocket feed)
  2. For each watched symbol:
     a. Compute all 80 features on candle DataFrame
     b. Run each enabled signal → get score
     c. Aggregate score
     d. If score ≥ ENTRY_THRESHOLD:
        - Check circuit breaker
        - Check no existing position for this symbol
        - Calculate lot size + SL + target
        - Place order via OpenAlgo
        - Log to trade_log
  3. For each open position:
     a. Check SL hit (LTP ≤ SL for long)
     b. Check target hit (LTP ≥ target for long)
     c. Check trailing SL update
     d. Exit via OpenAlgo if needed

Every 1 second:
  - Update position LTP from WebSocket feed
  - Check trailing SL conditions

End of day (15:25 IST):
  - Square off all open positions
  - Compute daily_performance
  - Save to SQLite
  - Send Telegram daily summary
```

#### 4.4 Dashboard (React + FastAPI)
- [ ] `dashboard/api/main.py` — FastAPI skeleton
- [ ] `dashboard/frontend/` — React app (Vite + TypeScript + Tailwind + shadcn/ui)
- [ ] See `DASHBOARD.md` for full page-by-page specification

**Phase 1 dashboard priority pages (in order):**
1. `/trades` — data exists from week 1, build this first to verify data layer
2. `/` Dashboard — equity curve + positions + live log
3. `/signals` — signal toggles + weight sliders
4. `/positions` — proxy OpenAlgo
5. `/backtest` — run backtests from UI
6. `/settings` — risk profile + watchlist

**Paper trade for 1 full week via OpenAlgo sandbox before going live with real capital.**

---

## Phase 2 — ML Signal Layer + Multi-Strategy Portfolio

**Goal:** Add XGBoost models, RL agents, pairs trading (stat arb), and theta/options selling. By end of Phase 2 we have 4 uncorrelated strategies running simultaneously — targeting Sharpe ≥ 1.8 combined.
**Duration:** Weeks 5–12
**Gate to Phase 3:** Combined portfolio Sharpe > 1.5 in live trading over 2 months. Each strategy individually profitable.

**Why we add pairs + theta here:** These are mathematically independent from momentum/mean-reversion (low correlation). Adding them in Phase 2 dramatically improves risk-adjusted returns without requiring news data or LLMs. Research shows combined Sharpe of uncorrelated strategies can be 50–80% higher than the best individual strategy.

### Week 5–6: Regime Detection

#### 5.1 Regime Classifier
- [x] `signals/ml/regime_detector.py`

**Features for regime classification:**
- EMA9/EMA20/EMA50 spread ratios
- ATR percentile (0–100) over 60-day window
- RSI14 rolling 20-day average
- ADX value (> 25 = trending, < 20 = ranging)
- Realized volatility 5-day vs 20-day ratio

**Regime classes:**
- `TRENDING_UP` — ADX > 25, EMA slope positive, price above all EMAs
- `TRENDING_DOWN` — ADX > 25, EMA slope negative, price below all EMAs
- `MEAN_REVERTING` — ADX < 20, RSI oscillating 30–70, low ATR percentile
- `CHOPPY` — High ATR percentile but no trend, whipsawing EMAs

**Implementation options (in order of complexity):**
1. Rule-based decision tree (fastest, most interpretable) ← start here
2. Hidden Markov Model (hmmlearn) ← better regime boundaries
3. ML classifier on labeled data ← Phase 3

#### 5.2 Regime-Adjusted Aggregator
- [x] Update `ensemble/aggregator.py` to use regime-specific weights

```python
REGIME_WEIGHT_MAP = {
    "TRENDING_UP":    {"vwap_breakout": 0.50, "rsi_momentum": 0.40, "mean_reversion": 0.10},
    "TRENDING_DOWN":  {"vwap_breakout": 0.50, "rsi_momentum": 0.40, "mean_reversion": 0.10},
    "MEAN_REVERTING": {"vwap_breakout": 0.10, "rsi_momentum": 0.20, "mean_reversion": 0.70},
    "CHOPPY":         {"vwap_breakout": 0.33, "rsi_momentum": 0.33, "mean_reversion": 0.34},
    # In CHOPPY: reduce all weights → score rarely crosses threshold → fewer trades
}
```

### Week 7–8: XGBoost Models

#### 6.1 Macro XGBoost (Directional Gate)
- [x] `signals/ml/macro_model.py`
- [x] `models/train_macro.py`

**Label:** `y = 1` if `close[t+15min] / close[t] >= 1.001` (≥0.1% rise in 15 min), else `0`

**Training data requirements:**
- Minimum 6 months of 1-min OHLCV before trusting model
- Walk-forward: 5 folds, 120-day train / 30-day test

**Feature selection:**
- Start with all 80 features
- Drop features with Pearson correlation > 0.85 (remove redundancy)
- Use XGBoost feature importance to keep top 50

**Score integration:**
```python
# Phase 2 ensemble formula (AI-trader proven):
final_score = (0.50 × macro_model.predict_proba(features)[1]  # P(bullish)
             + 0.30 × flow_score                               # PCR + OI change
             + 0.20 × technical_strength                       # rule-based score
             + regime_bonus)
```

#### 6.2 Micro XGBoost (Entry Confirmation)
- [x] `signals/ml/micro_model.py`
- [x] `models/train_micro.py`

**Label:** Net buying pressure in next 30 ticks (sum of signed trade volumes)

**Features:** 5 tick-level microstructure features (bid_ask_spread, order_imbalance, trade_size_spike, volume_burst, tick_momentum)

**Role:** Acts as a binary gate — if micro model score < 0.45, skip entry even if macro score is high. Prevents "catching a falling knife" entries.

### Week 9–10: Strategy Outcome Models + RL Exit Agent

#### 7.1 Strategy Outcome Models
- [x] `signals/ml/strategy_outcomes.py`
- [x] `models/train_outcomes.py`

**One XGBClassifier per strategy (3 models):**
- Input: 50 market features at moment of entry
- Label: WIN (PnL > 0) or LOSS from actual `trade_log`
- Acts as final gate: only enter if outcome model gives ≥ 0.55 probability of WIN
- **Needs ≥ 15 labeled trades per strategy before becoming useful.** Until then, skip this gate.

#### 7.2 RL Exit Agent (Q-learning)
- [x] `models/rl_exit_agent.py`
- [x] `models/train_rl_on_journeys.py`

**State space (8 features, all trade-relative):**
```python
state = [
    time_in_trade_normalized,      # 0.0 = just entered, 1.0 = EOD
    pnl_pct,                       # current unrealized PnL as %
    sl_distance_pct,               # distance to SL as % of entry
    target_distance_pct,           # distance to target as % of entry
    momentum_score,                # current composite momentum score
    volume_trend,                  # volume rising/falling
    regime_encoded,                # 0-3 for 4 regimes
    score_at_entry,                # original entry score
]
```

**Actions:** `HOLD` (0), `EXIT_NOW` (1), `TIGHTEN_SL` (2)

**Reward:** Realized PnL at episode end (when position closes)

**Training:** On all historical trade journeys saved in `trade_log`

**From AI-trader data:** RL exit contributes ~15% of exits at ~90%+ profitability rate

#### 7.3 RL Entry Agent (Q-learning)
- [x] `models/rl_entry_agent.py`
- [x] `models/train_rl_entry.py`

**State space (10 features, extended from exit agent):**
```python
state = [
    composite_score,           # ensemble score at signal fire
    regime_encoded,            # current regime
    time_of_day_normalized,    # 0.0=9:15, 1.0=15:30
    vix_normalized,            # India VIX / 52-week high
    session_pnl_normalized,    # today PnL / daily loss limit
    open_positions_count,      # how many positions already open
    volume_ratio,              # current vol vs 20-day avg
    score_momentum,            # score now - score 5 bars ago
    macro_model_prob,          # P(bullish) from XGBoost
    recent_win_rate,           # last 10 trades win rate
]
```

**Actions:** `SKIP` (0), `ENTER` (1)
**Activation:** Only after ≥ 50 entry decisions logged. Before that, all threshold-crossing signals auto-enter.

#### 7.4 Daily Retraining Pipeline
- [x] `scripts/retrain_daily.py` — run post-market (after 15:30 IST)

```
1. Load last 180-day rolling window of candles
2. Retrain macro model (incremental_train.py)
3. Retrain micro model
4. Retrain strategy outcome models (only if ≥15 new trades)
5. Retrain RL exit agent (train_rl_on_journeys.py, 50 epochs)
6. Backup old models to models/saved/backups/YYYYMMDD/
7. Log: new vs old AUC, training duration, sample count
8. Send Telegram summary
```

### Week 11–12: Pairs Trading (Statistical Arbitrage)

**Goal:** Market-neutral strategy — profits whether market goes up or down. Historical Sharpe on NSE: 1.5–3.0.

#### 8.1 Cointegration Scanner
- [x] `signals/pairs/cointegration_scanner.py`
- [ ] `notebooks/pairs_discovery.ipynb` — run once to find pairs, then monthly refresh

**Pairs to test first (strong historical cointegration on NSE):**
```python
CANDIDATE_PAIRS = [
    ("HDFCBANK", "ICICIBANK"),    # banking peers — strongest pair
    ("TCS", "INFY"),             # IT sector
    ("HINDUNILVR", "DABUR"),     # FMCG
    ("RELIANCE", "ONGC"),        # oil & gas
    ("AXISBANK", "KOTAKBANK"),   # mid-size banks
    ("WIPRO", "HCLTECH"),        # IT tier-2
]
```

**Cointegration test (Engle-Granger):**
```python
from statsmodels.tsa.stattools import coint
score, pvalue, _ = coint(price_A, price_B)
# Keep pair if pvalue < 0.05 → statistically cointegrated
```

**Output:** `config/validated_pairs.json` — list of pairs that pass the test with hedge ratio stored.

#### 8.2 Pairs Signal
- [x] `signals/pairs/pairs_signal.py`

**Signal logic:**
```python
def compute_pairs_score(pair: tuple, df: pd.DataFrame) -> float:
    A, B = pair
    hedge_ratio = get_hedge_ratio(A, B)   # OLS regression coefficient
    spread = price_A - hedge_ratio * price_B
    
    # Rolling Z-score of spread:
    mu = spread.rolling(window=20).mean()
    sigma = spread.rolling(window=20).std()
    z_score = (spread.iloc[-1] - mu.iloc[-1]) / sigma.iloc[-1]
    
    # Signal:
    # z > +2.0 → spread too wide → short A, long B (score = -1.0 for A, +1.0 for B)
    # z < -2.0 → spread too narrow → long A, short B
    # |z| < 0.5 → no signal → exit if in position
    return z_score  # passed to ensemble as a directional score
```

**Entry rule:** |z_score| > 2.0 → enter pair trade (simultaneous long + short)
**Exit rule:** |z_score| < 0.5 → spread has normalized → close both legs
**Stop loss:** |z_score| > 3.5 → spread diverging badly → cut loss (cointegration may have broken)

**Key properties:**
- Market neutral: long one stock, short the other → net market exposure ≈ 0
- F&O required: need short selling → use futures for the short leg
- Max 3 pairs simultaneously (capital requirement)
- Expected win rate: 60–70%, avg hold: 1–5 days (not purely intraday)

#### 8.3 Pairs Risk Management
- [x] `risk/pairs_risk.py`

```python
# Cointegration health check (run daily):
# If pvalue drifts > 0.10 for 5 consecutive days → pair has broken → halt it
# Common reason: major corporate event (merger, scandal) breaks historical relationship

def check_pair_health(pair: tuple, rolling_window: int = 30) -> bool:
    _, pvalue, _ = coint(recent_price_A, recent_price_B)
    return pvalue < 0.10   # still cointegrated?
```

---

### Week 12–13: Theta / Options Selling Strategy

**Goal:** Sell weekly NIFTY/BankNIFTY option premium algorithmically. Highest Sharpe of any NSE retail strategy (1.5–2.5). Profits from time decay when market is range-bound.

#### 9.1 Theta Strategy Engine
- [x] `signals/theta/weekly_straddle.py`
- [x] `signals/theta/hedge_manager.py`
- [x] `risk/theta_risk.py`

**Core strategy — ATM Short Straddle on NIFTY weekly:**
```python
# Entry conditions (checked at 9:30 IST Monday or Tuesday):
def should_enter_straddle() -> bool:
    return (
        india_vix < 18              # avoid selling when fear is high
        and india_vix > 11          # avoid selling when premium is too thin
        and not is_event_week()     # RBI policy, budget, F&O expiry week → skip
        and days_to_expiry >= 3     # min 3 days of theta left
    )

# Entry:
atm_strike = round(nifty_spot / 50) * 50   # nearest 50-point strike
sell_call = Place(symbol="NIFTY", strike=atm_strike, opt="CE", action="SELL", qty=1lot)
sell_put  = Place(symbol="NIFTY", strike=atm_strike, opt="PE", action="SELL", qty=1lot)
```

**Exit conditions (any of these → close both legs):**
```python
def should_exit_straddle(position) -> bool:
    return (
        position.pnl_pct >= 0.50    # target: 50% of premium collected
        or position.pnl_pct <= -1.0 # stop loss: lose 2× the premium collected
        or days_to_expiry <= 0      # expiry day → close by 3:00 PM
        or india_vix > 20           # VIX spike → close immediately (biggest risk)
        or abs(delta) > 0.35        # position has gone too directional → adjust
    )
```

**VIX-based position sizing:**
```python
# The higher the VIX, the more premium we collect BUT also higher risk:
vix_to_lots = {
    (11, 14): 1,   # low VIX → small position (thin premium)
    (14, 18): 2,   # moderate VIX → standard position  
    (18, 20): 1,   # high VIX → reduce size (danger zone)
    # > 20: don't enter
}
```

**Delta hedging (optional, Phase 2b):**
```python
# If net delta > 0.20 (position has become too directional):
# Buy/sell NIFTY futures to neutralize delta
# Check delta every 15 minutes
# Only hedge if delta > 0.15 (don't over-hedge small moves)
```

**Why this works on NSE (documented edge):**
- NSE weekly options are the most liquid in the world by volume
- Implied volatility (IV) consistently trades 15–25% above realized volatility (the "vol risk premium")
- Selling IV = selling overpriced insurance = structural edge
- Win rate: 65–70% of weeks when VIX < 16 (documented by multiple Indian quants)

**The risk (must be respected):**
- Black swan events: Liberation Day tariffs (Apr 2025), COVID (Mar 2020), Demonetisation (Nov 2016)
- In these events: short straddle can lose 5–10× the weekly premium in a single day
- Mitigation: strict VIX stop (close at VIX > 20), never oversize, keep theta book ≤ 20% of total capital

#### 9.2 Theta Metrics in Dashboard
Add to `/positions` page and `/performance` page:
- Weekly straddle entry premium collected
- Current delta exposure
- Days to expiry
- Theta decay per day (₹ value)
- VIX alert threshold

---

### Phase 2 Combined Portfolio

By end of Week 13, the system runs 4 strategies simultaneously:

| Strategy | Type | Market exposure | Expected Sharpe |
|---|---|---|---|
| VWAP + RSI Momentum | Directional | Long/short Nifty 50 equity | 0.9–1.2 |
| Mean Reversion | Mean-reverting | Long/short Nifty 500 equity | 0.8–1.1 |
| Pairs Trading | Market neutral | Long A, Short B (pairs) | 1.5–2.5 |
| Theta Selling | Short volatility | Short NIFTY options | 1.5–2.0 |
| **Combined** | **Uncorrelated mix** | **Diversified** | **~2.0–2.5** |

The combined Sharpe is significantly higher because:
- When momentum fails (choppy market) → theta selling thrives (choppy = range-bound = good for straddles)
- When theta selling gets hurt (VIX spike) → momentum thrives (directional moves = breakouts)
- Pairs trading is always market-neutral and doesn't care about direction

---

## Phase 3 — News & Alternative Data

**Goal:** Add fundamental and sentiment layers to complement technical + ML signals.
**Duration:** Weeks 11–16
**Gate to Phase 4:** Phase 3 Sharpe > Phase 2 Sharpe, FinBERT signal has positive IC, system profitable in live for 2 months.

### Task 8.1: NSE Announcements Filter
- [ ] `signals/news/nse_announcements.py`

**What to track:**
- Board meeting dates (earnings results)
- Dividend record dates
- Stock splits / bonus issues
- Promoter pledge increase/decrease
- Bulk deals / block deals

**Rules:**
- Suppress ALL signals for a symbol 30 min before and 60 min after a scheduled announcement
- PEAD signal: if actual earnings surprise > 5% vs estimate, go with momentum in surprise direction for 20 trading days
- Promoter pledging increase > 5%: add bearish bias to that symbol

### Task 8.2: FinBERT News Sentiment
- [ ] `signals/news/finbert_sentiment.py`

**Model:** `ProsusAI/finbert` from HuggingFace (3 classes: positive/negative/neutral)

**Sources:**
- NSE announcements text (BoardMeeting PDFs → OCR → sentiment)
- MoneyControl headlines RSS feed
- Google News RSS (`f"site:moneycontrol.com {symbol}"`)
- Economic Times headlines

**Frequency:** Compute every 30 minutes during market hours (news doesn't change per-minute)

**Score calculation:**
```python
sentiment_score = finbert_positive_prob - finbert_negative_prob
# Range: -1.0 to +1.0
# Cache in SQLite to avoid re-inference
```

**Phase 3 ensemble formula:**
```python
final_score = (0.35 × macro_model_score
             + 0.25 × flow_score
             + 0.15 × technical_strength
             + 0.15 × news_sentiment
             + 0.10 × options_flow_score
             + regime_bonus)
```

### Task 8.3: Options Flow Signals
- [ ] `signals/news/options_flow.py`

**Signals from option chain (via nsepython):**
- PCR > 1.5 = oversold → contrarian bullish signal
- PCR < 0.5 = overbought → contrarian bearish signal
- OI build speed (fast OI increase = conviction signal)
- IV skew (call IV > put IV = bullish, put IV > call IV = bearish)
- Max pain level acts as gravitational price target

---

## Phase 4 — LLM + Auto Alpha Discovery

**Goal:** Add LLM-powered analysis agents and automated alpha factor discovery.
**Duration:** Weeks 17+
**Gate:** Phase 3 profitable in live for 2+ months. SEBI RA registration complete (required for black-box algos).

### Task 9.1: Multi-Agent LLM Framework
- [ ] `signals/llm/technical_agent.py`
- [ ] `signals/llm/news_agent.py`
- [ ] `signals/llm/risk_agent.py`

**Architecture (adapted from TradingAgents for NSE):**
```
Technical Analyst Agent  →
News Analyst Agent       →  Researcher Debate (Bull vs Bear)  →  Trader Agent  →  Score
Risk Assessment Agent    →
```

**LLM provider options (in order of cost):**
1. `gpt-4o-mini` — cheapest, good quality (~$0.01–0.05 per trade decision)
2. Local Ollama (LLaMA 3.1 8B or Mistral 7B) — free, less capable
3. `gpt-4o` or `claude-3-5-sonnet` — best quality, more expensive

**Cost guard:** Cap LLM API spend at $X/day (configurable). If exceeded, disable LLM signals and fall back to Phase 3.

### Task 9.2: Auto Alpha Discovery (alphagen pattern)
- [ ] `signals/research/alphagen_wrapper.py`

**What it does:**
- RL agent explores a tree of mathematical expressions (e.g., `RSI / MACD_hist * volume_ratio`)
- Reward = IC (information coefficient) improvement when the new factor is added to existing factor set
- Discovered factors auto-wrapped as `BaseSignal` subclasses

**Usage:** Run weekly offline. Discover 1–2 candidate factors. Backtest each. A/B test in paper trading for 2 weeks before adding to live ensemble.

---

## Research Papers to Implement

| Paper | Signal | Phase | Status |
|---|---|---|---|
| Jegadeesh & Titman 1993 — Momentum | `signals/research/cross_sectional_momentum.py` — rank Nifty 50 by 12-1 month return | 2 | 🔲 |
| Daniel & Moskowitz 2016 — Momentum Crashes | `signals/research/momentum_crash.py` — reduce momentum weight in high-vol regimes | 2 | 🔲 |
| Cont, Kukanov, Stoikov 2014 — Order Flow Imbalance | `signals/research/order_flow.py` — bid-ask imbalance → price impact | 2 | 🔲 |
| Bernard & Thomas 1989 — PEAD | `signals/research/pead.py` — post-earnings drift signal | 3 | 🔲 |
| QuantEvolve 2025 — LLM Alpha Generation | Auto-generate signal candidates | 4 | 🔲 |

---

## Milestones

| # | Milestone | Definition of Done | Status |
|---|---|---|---|
| **M0** | **Edge proven (Phase 0 gate)** | **Walk-forward backtest NET of costs is positive — gross edge > round-trip costs, Sharpe > 0.8, net win-rate ≥ 50% on ≥150 days OOS (BT-EDGE)** | 🔲 |
| **M0.E** | **Backfill + models trained** | **Analytics Token live; 2-year 5-min candles for 750 symbols in SQLite; macro/micro models AUC ≥ 0.53 OOS; RL trained on ≥ 500 episodes; walk-forward Sharpe > 0.8** | 🔲 |
| M1 | Data pipeline live | Real Upstox/daily backfill + WebSocket writing to SQLite, 1 week clean data, no gaps (DATA-01) | 🔲 |
| M2 | First backtest | Custom event-driven engine on 1 year Nifty 50, walk-forward, net-of-costs (vectorbt removed) | 🔲 |
| M3 | Dashboard running | React dashboard showing trade log + equity curve + signal sliders | 🔲 |
| M4 | Paper trading | 1 week OpenAlgo sandbox, win rate ≥ 50%, no bugs | 🔲 |
| M5 | Live Phase 1 | 1 month real capital, tracking vs backtest | 🔲 |
| M6 | ML models trained | Macro model AUC ≥ 0.58 on walk-forward | 🔲 |
| M7 | Pairs trading live | ≥1 pair profitable in paper trading over 20 spread cycles | 🔲 |
| M8 | Theta strategy live | Theta straddle profitable in paper trading for 4 consecutive weeks | 🔲 |
| M9 | Multi-strategy portfolio | All 4 strategies live, combined Sharpe ≥ 1.5 over 2 months | 🔲 |
| M10 | News signal active | FinBERT signal has positive IC over 1 month | 🔲 |
| M11 | LLM agents tested | LLM agents in paper trading, measuring contribution | 🔲 |

---

## Week-by-Week Summary

| Week | Focus | Key deliverable |
|---|---|---|
| **0** | **Make it profitable (CURRENT)** | **Validation harness + edge search until walk-forward is net-positive after costs (Phase 0 / M0)** |
| **0.E** | **Data backfill + train models** | **Analytics Token → 2yr 5-min backfill (750 symbols) → train ML/RL → walk-forward validates Sharpe > 0.8 (M0.E)** |
| 1 | Repo + Data layer | Upstox data in SQLite, 1 year historical pulled |
| 2 | Features + Signals | 80 features computed, 3 signals returning scores |
| 3 | Ensemble + Backtest | Walk-forward backtest passing, position sizer working |
| 4 | Live + Dashboard | OpenAlgo connected, paper trading, dashboard live |
| 5-6 | Regime detection | Regime classifier, weight adjustment in aggregator |
| 7-8 | XGBoost models | Macro + micro models trained, AUC tracked |
| 9-10 | RL exit + entry + retraining | Both RL agents + daily retrain pipeline |
| 11-12 | Pairs trading | Cointegration scan, pairs signal, market-neutral live |
| 12-13 | Theta / options selling | ATM short straddle on NIFTY weekly, VIX guards |
| 13-14 | Multi-strategy live | All 4 strategies running, portfolio heat, combined metrics |
| 15-16 | NSE announcements + FinBERT | Event filter, PEAD signal, sentiment score |
| 17-18 | Options flow | PCR, OI, IV skew signals |
| 17+ | LLM agents | Technical + News + Risk agents |
| 20+ | Auto alpha | alphagen weekly runs, A/B testing new factors |
