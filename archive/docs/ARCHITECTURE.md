# ARCHITECTURE — System Design & File Structure

> Full system component map, data flow, and complete repository file structure.

---

## System Component Map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL SOURCES                                    │
│   Upstox WebSocket (live ticks)    Upstox REST API (historical OHLCV)      │
│   nsepython (option chain, PCR)    NSE website (announcements)             │
│   Google News RSS / MoneyControl   HuggingFace (FinBERT model)             │
│   OpenAI / Ollama API (LLM)                                                 │
└───────────┬─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────────┐
│      DATA LAYER           │
│  data/upstox_feed.py      │  ← WebSocket → writes ticks to SQLite
│  data/upstox_history.py   │  ← REST API → writes candles to SQLite
│  data/nse_data.py         │  ← nsepython → writes option chain to SQLite
│  data/db.py               │  ← SQLite (WAL) helpers, thread-local conns
│                           │
│  ┌─────────────────────┐  │
│  │  SQLite WAL (single │  │
│  │  file, on disk) —   │  │
│  │  concurrent readers │  │
│  │  + 1 writer across  │  │
│  │  processes          │  │
│  │  algo_trading.sqlite│  │
│  └─────────────────────┘  │
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────────────────────────────────────────┐
│                    FEATURE ENGINE                             │
│   features/indicators.py → compute_all_features(df)          │
│   Returns: DataFrame with 80 columns (one row per bar)        │
│   features/micro_features.py → tick-level 5 features         │
└───────────┬───────────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                         SIGNAL LAYER                                      │
│                                                                           │
│  Phase 1 — Technical          Phase 2 — ML            Phase 3 — News     │
│  ┌─────────────────────┐     ┌───────────────────┐   ┌────────────────┐  │
│  │ vwap_breakout.py    │     │ macro_model.py    │   │ nse_events.py  │  │
│  │ rsi_momentum.py     │     │ micro_model.py    │   │ finbert.py     │  │
│  │ mean_reversion.py   │     │ regime_detect.py  │   │ options_flow.py│  │
│  └─────────┬───────────┘     │ strategy_outcomes │   └───────┬────────┘  │
│            │                 └─────────┬─────────┘           │           │
│            └──────────────────────┬────┘────────────────────┘           │
│                                   │                                       │
│                    Each signal: BaseSignal.compute() → float [-1, +1]    │
└───────────────────────────────────┬───────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────┐
│                   ENSEMBLE AGGREGATOR                     │
│   ensemble/aggregator.py                                  │
│   Weighted sum + regime bonus → final_score ∈ [-1, +1]   │
│   Threshold check → LONG / SHORT / NO_TRADE               │
│                                                           │
│   ensemble/position_sizing.py                             │
│   Score tier → lot size, ATR-based SL, target, trailing  │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────┐
│                    RISK LAYER                             │
│   risk/circuit_breaker.py → halt on daily loss / blackout │
│   risk/correlation_guard.py → limit correlated positions  │
└───────────────────────┬───────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                         EXECUTION LAYER                                   │
│                                                                           │
│   live/openalgo_client.py   →   OpenAlgo (localhost:3000)                │
│                                 Flask + React 19 platform                 │
│                                 ↓                                         │
│                             Upstox Broker API                             │
│                             NSE Exchange                                  │
└───────────────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                      LOGGING & ANALYTICS                                  │
│                                                                           │
│   SQLite: trade_log, daily_performance, equity_curve                     │
│   analytics/pnl_tracker.py → compute daily stats                        │
└───────────────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                       DASHBOARD                                           │
│                                                                           │
│   dashboard/api/main.py   (FastAPI, port 8000)                           │
│   dashboard/frontend/     (React 19 + Vite, port 5173)                  │
│                                                                           │
│   See DASHBOARD.md for complete spec                                      │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow — Live Trading

The live loop is **event-driven** (June 2026): signals fire when a bar closes, not on a fixed timer.

```
1. Market opens 9:15 IST
2. upstox_feed.py connects WebSocket → receives ticks; caches each symbol's latest
   price in memory (with a monotonic age) for fresh/stale checks (FEED-02)
3. Ticks written to SQLite (ticks) + aggregated into minute_candles. A 1s wall-clock
   timer force-closes a bar when its interval elapses even with no new tick, so the
   last bar of a quiet period / pre-EOD is never lost (FEED-01). Each bar close is an event.
4. live/runner.py signal loop is EVENT-DRIVEN:
   - on each primary-tf bar close the feed enqueues the symbol; the loop processes it
   - a 60s full-rescan is the fallback if the feed goes quiet
   - control state + EOD are checked every ~1s (kill switch / pause react in ~1s)
   Per symbol: read candles → 80 features → signals → ensemble → ML gates (each only
   vetoes above a min OOS AUC; macro centred on the training base rate, ML-04) →
   circuit breaker → sizing → cost-aware filter (PnL-02) → order via OpenAlgo
   (polled to a terminal fill, real filled-qty booked, LIVE-07) → trade_log (net of
   costs). Order placement stays on this single thread.
5. Position monitor (1s): for each open position, use a FRESH live price only —
   if missing/stale it skips the stop and raises a throttled stale-feed alert
   (never substitutes entry price, FEED-02); else checks SL/target/trailing SL and
   exits via OpenAlgo. Exit orders are confirmed before the book is updated (LIVE-01);
   a daily-loss breach flattens + halts (LIVE-05).
6. Dashboard polls /api/* every 1–30s; controls reach the runner via the
   config/control.py control plane (kill switch / pause / weights), not a shared process.
7. 15:25 IST: EOD square-off (exits at best-known price), daily_performance computed.
```

> Next reliability step (broker-dependent, not yet built): place SL/target as broker-side
> OCO/GTT orders so stops live at the exchange and survive a runner crash (LIVE-01/02/04).

---

## Data Flow — Backtesting

```
1. Load 1 year of 5-min OHLCV from SQLite → pandas DataFrame
2. compute_all_features(df) → features DataFrame (no look-ahead; session features in IST)
3. For each out-of-sample bar: run signals → aggregate → ensemble result
4. Custom event-driven simulator (backtest/engine.py — vectorbt removed):
   - LONG and SHORT trades (BT-05); entry fills at the NEXT bar's OPEN (no same-bar look-ahead)
   - Cost-aware filter skips setups that can't clear round-trip costs (mirrors live)
   - Intrabar SL/target on the bar's high/low, filled AT the stop/target price (SL first if both)
   - Full Indian intraday cost model charged per trade; PnL reported net (BT-03)
5. Per-fold + aggregate metrics: Sharpe, drawdown, win rate, profit factor, expectancy (BT-04)
6. Result JSON + trades CSV saved to backtest/results/; run row persisted to backtest_runs
7. Dashboard /backtest page fetches results
```
> **Known modelling limit:** each (symbol, fold) is simulated independently with full
> capital and no shared portfolio-heat/concurrency cap, so the aggregate equity/Sharpe
> are optimistic vs the live caps. Per-trade stats are valid. (KNOWN_ISSUES §11.)

---

## Complete Repository File Structure

```
D:\Python_Codes\AlgoTrading\
│
├── MASTER_PLAN.md                    ← Central index (READ FIRST)
├── README.md                         ← Quick start guide
├── requirements.txt                  ← Pinned Python dependencies
├── .env.example                      ← API keys template (NEVER commit .env)
├── .gitignore                        ← Excludes .env, *.pkl, *.db, __pycache__
│
├── docs/                             ← All documentation
│   ├── ROADMAP.md                    ← Phased build plan + week-by-week tasks
│   ├── ARCHITECTURE.md               ← This file
│   ├── DASHBOARD.md                  ← Dashboard spec (all pages, API routes)
│   ├── DATA.md                       ← Data sources, schema, pipeline
│   ├── SIGNALS.md                    ← Every signal: formula, parameters, features
│   └── SEBI_COMPLIANCE.md            ← Regulatory checklist
│
├── config/
│   ├── settings.py                   ← All constants, thresholds, weights, instruments
│   └── risk_profiles.py              ← LOW / MEDIUM / HIGH dataclasses
│
├── data/
│   ├── upstox_feed.py                ← WebSocket live data (MarketDataStreamerV3)
│   ├── upstox_history.py             ← Historical OHLCV via Upstox REST API
│   ├── nse_data.py                   ← nsepython: option chain, PCR, OI
│   ├── db.py                         ← SQLite (WAL) helpers (init, read, write, upsert), thread-local conns
│   ├── instruments.py                ← Downloads Upstox NSE.json.gz master; caches symbol→instrument_key map to data/nse_eq_keys.json (weekly refresh)
│   ├── margin.py                     ← Upstox ChargeApi.post_margin wrapper; fetch/cache/load MIS margin multipliers (data/margin_multipliers.json)
│   ├── margin_multipliers.json       ← Cache: {date, symbols:{SYMBOL:{multiplier, margin_pct, ...}}} (needs live token to populate)
│   └── schema.sql                    ← All SQLite table definitions
│
├── features/
│   ├── indicators.py                 ← compute_all_features(df) → 80-column DataFrame
│   └── micro_features.py             ← 5 tick-level features
│
├── signals/
│   ├── base.py                       ← BaseSignal abstract class
│   ├── technical/
│   │   ├── __init__.py
│   │   ├── vwap_breakout.py          ← VWAP + RSI + EMA momentum breakout
│   │   ├── rsi_momentum.py           ← RSI cross + MACD continuation
│   │   └── mean_reversion.py         ← BB lower/upper + RSI extreme + VWAP distance
│   ├── ml/
│   │   ├── __init__.py
│   │   ├── macro_model.py            ← XGBoost: P(price +0.1% in 15min)
│   │   ├── micro_model.py            ← XGBoost: tick buying pressure
│   │   ├── regime_detector.py        ← Classify: TRENDING/MEAN_REVERTING/CHOPPY
│   │   └── strategy_outcomes.py      ← Per-strategy WIN/LOSS gate model
│   ├── news/
│   │   ├── __init__.py
│   │   ├── nse_announcements.py      ← Event calendar + PEAD signal
│   │   └── finbert_sentiment.py      ← FinBERT news sentiment score
│   ├── options_flow/
│   │   ├── __init__.py
│   │   └── flow_signals.py           ← PCR, OI change, IV skew, max pain
│   ├── llm/                          ← Phase 4
│   │   ├── __init__.py
│   │   ├── technical_agent.py        ← LLM technical analyst agent
│   │   ├── news_agent.py             ← LLM news analyst agent
│   │   └── risk_agent.py             ← LLM risk assessment agent
│   └── research/                     ← Research paper implementations
│       ├── cross_sectional_momentum.py
│       ├── momentum_crash.py
│       ├── order_flow_imbalance.py
│       └── pead.py
│
├── ensemble/
│   ├── aggregator.py                 ← Weighted score combiner with regime adjustment
│   └── position_sizing.py            ← Score-tiered lots, ATR SL/target, trailing SL, MIS margin leverage
│
├── risk/
│   ├── circuit_breaker.py            ← Halt on daily loss / max positions / blackout
│   └── correlation_guard.py          ← Reduce when correlated positions accumulate
│
├── backtest/
│   ├── engine.py                     ← custom event-driven simulator + walk-forward (long+short, next-bar-open fills, intrabar SL/target, net costs)
│   ├── tick_replay.py                ← Tick-level backtest (Phase 2+ — NOT yet built)
│   └── results/                      ← Saved backtest CSVs + HTML tearsheets
│       └── .gitkeep
│
├── replay/
│   ├── engine.py                     ← Full-fidelity single-day Action Replay (steps 5min bars; reuses DailyScreener, EnsembleAggregator, CircuitBreaker, PositionSizer; fill = next bar open; intrabar SL/target; EOD squareoff; emits timestamped events; auto-fetches from Upstox if bars missing)
│   └── results/                      ← Saved replay JSON files (one per run)
│
├── models/
│   ├── train_macro.py                ← Train XGBoost macro model
│   ├── train_micro.py                ← Train XGBoost micro model
│   ├── train_outcomes.py             ← Train strategy outcome models
│   ├── train_rl_on_journeys.py       ← Train RL exit agent
│   ├── rl_exit_agent.py              ← Q-learning exit agent class
│   └── saved/                        ← Trained model files
│       ├── macro_model.pkl
│       ├── micro_model.pkl
│       ├── regime_model.pkl
│       ├── outcome_vwap.pkl
│       ├── outcome_rsi.pkl
│       ├── outcome_mean_rev.pkl
│       ├── rl_exit_agent.pkl
│       └── backups/                  ← Date-stamped backups
│           └── YYYYMMDD/
│
├── live/
│   ├── runner.py                     ← Main live trading loop
│   └── openalgo_client.py            ← OpenAlgo REST API wrapper
│
├── analytics/
│   └── pnl_tracker.py                ← Daily P&L, equity curve, stats
│
├── dashboard/
│   ├── api/                          ← FastAPI backend
│   │   ├── main.py                   ← FastAPI app (port 8000)
│   │   ├── routes/
│   │   │   ├── system.py             ← start/stop/kill switch; OAuth token exchange
│   │   │   ├── signals.py            ← weights, enable flags, scores
│   │   │   ├── trades.py             ← trade log, equity curve, analytics
│   │   │   ├── positions.py          ← proxy OpenAlgo positions/orders
│   │   │   ├── backtest.py           ← trigger + stream backtest
│   │   │   ├── replay.py             ← Action Replay: POST /run, GET /status, /result, /history
│   │   │   └── models.py             ← model status, retrain trigger
│   │   └── websocket.py              ← SSE log stream + Socket.IO
│   └── frontend/                     ← React 19 + Vite app
│       ├── package.json
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── tailwind.config.ts
│       ├── index.html
│       └── src/
│           ├── main.tsx
│           ├── App.tsx
│           ├── pages/
│           │   ├── Dashboard.tsx     ← / (overview + kill switch)
│           │   ├── Live.tsx          ← /live (signal scanner + trade monitor)
│           │   ├── Signals.tsx       ← /signals (control panel)
│           │   ├── Positions.tsx     ← /positions (orders + holdings)
│           │   ├── Trades.tsx        ← /trades (history + PnL analytics)
│           │   ├── Backtest.tsx      ← /backtest (run + results)
│           │   ├── Models.tsx        ← /models (ML manager)
│           │   ├── Options.tsx       ← /options (12 analytics tools)
│           │   ├── Flow.tsx          ← /flow (visual strategy builder)
│           │   ├── Settings.tsx      ← /settings
│           │   └── Security.tsx      ← /security
│           ├── components/
│           │   ├── layout/
│           │   │   ├── Navbar.tsx
│           │   │   ├── Sidebar.tsx
│           │   │   └── LiveLog.tsx   ← SSE log stream sidebar
│           │   ├── charts/
│           │   │   ├── EquityCurve.tsx
│           │   │   ├── PnLHeatmap.tsx
│           │   │   ├── DrawdownChart.tsx
│           │   │   └── SignalGauge.tsx
│           │   ├── controls/
│           │   │   ├── KillSwitch.tsx
│           │   │   ├── SignalCard.tsx
│           │   │   ├── SignalSlider.tsx
│           │   │   └── RiskProfileSelector.tsx
│           │   └── tables/
│           │       ├── TradeTable.tsx
│           │       ├── PositionTable.tsx
│           │       └── OrderTable.tsx
│           ├── hooks/
│           │   ├── useSystemStatus.ts
│           │   ├── useSignals.ts
│           │   ├── useTrades.ts
│           │   └── usePositions.ts
│           ├── store/
│           │   └── appStore.ts       ← Zustand global state
│           ├── api/
│           │   └── client.ts         ← TanStack Query API client
│           └── types/
│               └── index.ts          ← TypeScript type definitions
│
├── screener/
│   ├── universe.py                   ← Defines per-strategy stock universes (Nifty 50/100/200/500)
│   ├── daily_screener.py             ← Pre-market run: ranks all stocks, outputs daily_watchlist.json
│   ├── ranking_features.py           ← EOD features used for ranking (momentum, volume surge, ATR%ile)
│   └── catalyst_detector.py          ← Detects upcoming catalysts: earnings, bulk deals, FII flow
│
├── scripts/
│   ├── retrain_daily.py              ← Post-market model retraining
│   ├── backfill_history.py           ← Backfill missing historical data
│   ├── run_screener.py               ← Entry point: runs daily_screener.py at 9:00 IST
│   ├── fetch_option_chain.py         ← Snapshot option chain to SQLite
│   └── fetch_margin_multipliers.py   ← Fetch MIS margin multipliers from Upstox → data/margin_multipliers.json (needs live token; run weekly)
│
├── notebooks/
│   ├── 01_data_exploration.ipynb     ← Explore raw data quality
│   ├── 02_feature_analysis.ipynb     ← Feature importance, correlations
│   ├── 03_backtest_phase1.ipynb      ← Phase 1 walk-forward backtest
│   └── 04_ml_training.ipynb          ← XGBoost training experiments
│
└── tests/
    ├── test_signals.py               ← Unit tests for each signal
    ├── test_backtest.py              ← Backtest engine sanity checks
    ├── test_data.py                  ← Data layer tests
    └── test_ensemble.py              ← Aggregator + position sizer tests
```

---

## Universe & Screener Architecture

### Strategy-Specific Universes

Each strategy only operates on stocks it's designed for. This is enforced in `screener/universe.py`:

```python
UNIVERSES = {
    "momentum_vwap":    "nifty50",          # 50 stocks — liquidity critical
    "rsi_momentum":     "nifty100",         # 100 stocks
    "mean_reversion":   "nifty500_fo",      # ~200 F&O-eligible Nifty 500 stocks
    "options_flow":     "fo_eligible",      # ~200 stocks with live option chains
    "ml_macro":         "nifty200",         # 200 stocks — enough data for model training
    "finbert_news":     "any_with_news",    # dynamic — scored only if news exists today
    "pairs_arb":        "cointegrated_pairs", # ~15 pre-validated pairs
}

# Index constituents fetched from nsepython and cached in SQLite:
# nifty50, nifty100, nifty200, nifty500, fo_eligible_list
# Refreshed monthly (constituents change on rebalance dates)
```

### Daily Pre-Market Screener Flow

```
8:45 IST   Token refresh (Upstox OAuth)
9:00 IST   run_screener.py starts
           ↓
           For each universe:
             1. Load all stocks in universe from SQLite
             2. Compute ranking_features on EOD data from yesterday
             3. Check catalyst_detector (earnings today?, bulk deal?, FII buy?)
             4. Compute screener_score per stock
             5. Rank and select top 10–15
           ↓
           Write config/daily_watchlist.json:
           {
             "momentum_vwap":  ["RELIANCE", "TCS", "HDFCBANK", ...],  (top 10)
             "mean_reversion": ["LTIM", "PERSISTENT", "COFORGE", ...],  (top 8)
             "options_flow":   ["NIFTY", "BANKNIFTY", "RELIANCE", ...]  (top 10)
           }
           ↓
9:10 IST   live/runner.py reads daily_watchlist.json
           Subscribes Upstox WebSocket ONLY to these symbols
           (saves bandwidth — not watching all 500 stocks live)
9:15 IST   Market opens, trading begins on watchlist only
```

### Screener Ranking Formula

```python
# screener/daily_screener.py
def compute_screener_score(symbol: str, eod_data: pd.DataFrame) -> float:
    return (
        0.30 * technical_setup_score(symbol, eod_data)
        # breakout_proximity: how close to 20-day high or ORB level
        # volume_surge: yesterday volume / 20-day avg volume
        # vwap_position: close vs estimated next-day VWAP

      + 0.25 * momentum_rank(symbol, eod_data)
        # 5-day return rank within universe (percentile 0-1)
        # 20-day return rank within universe
        # cross-sectional momentum score

      + 0.20 * volume_surge_score(symbol, eod_data)
        # yesterday_volume / adv_20 (average daily volume 20-day)
        # unusual volume flag (> 2× ADV)

      + 0.15 * volatility_opportunity_score(symbol, eod_data)
        # ATR percentile (want 40th–80th: enough movement, not too wild)
        # Bollinger Band squeeze flag (compression before expansion)

      + 0.10 * catalyst_score(symbol)
        # +0.3 if earnings in next 3 days (PEAD opportunity)
        # +0.2 if bulk deal (institutional buying)
        # +0.2 if FII net buy > ₹500 Cr yesterday
        # -0.3 if board meeting today (suppress — avoid event risk)
    )
```

### What This Means for Data Requirements

| Universe | Symbols | Data needed | Source | Storage/day |
|---|---|---|---|---|
| Nifty 50 | 50 | Live ticks + 1min candles + option chain | Upstox WebSocket | ~200 MB |
| Nifty 100 | 100 | 5min candles only during market hours | Upstox WebSocket | ~100 MB |
| Nifty 500 screening | 500 | **EOD only** (no live ticks) | Upstox REST API (post-market) | ~50 MB |
| All F&O eligible | ~200 | Option chain snapshots every 30min | nsepython | ~40 MB |

**Key insight:** Only the top 10–15 selected stocks get full live tick data. The rest of the 500-stock universe is only fetched as EOD data for next-morning screening. This keeps bandwidth and compute manageable.

---

## Technology Stack

### Python Backend
```
upstox-python-sdk    ← Broker data + order execution
sqlite3 (stdlib)     ← Operational store, WAL mode (concurrent readers + 1 writer, cross-process) — LIVE-06
duckdb (optional)    ← Embedded analytical (OLAP) database — heavy ad-hoc analysis only, off the operational path
(custom engine)      ← Backtesting — event-driven simulator in backtest/engine.py (vectorbt removed, BT-01..04)
pandas               ← Data manipulation
numpy                ← Numerical operations
ta                   ← Technical indicators library
xgboost              ← ML models
scikit-learn         ← Feature selection, metrics
hmmlearn             ← Hidden Markov Model for regime detection
fastapi              ← Dashboard API server
uvicorn              ← ASGI server for FastAPI
python-socketio      ← WebSocket/Socket.IO for live updates
httpx                ← Async HTTP client (OpenAlgo calls)
python-dotenv        ← .env file loading
nsepython            ← NSE data scraper
quantstats           ← Backtest performance metrics
transformers         ← HuggingFace (FinBERT, Phase 3)
torch                ← PyTorch (Phase 2-3)
langchain            ← LLM orchestration (Phase 4)
```

### React Frontend
```
react@19             ← UI framework
typescript@5         ← Type safety
vite@6               ← Build tool
tailwindcss@4        ← Styling
@shadcn/ui           ← Component library
recharts@2           ← Analytics charts
lightweight-charts@4 ← TradingView charts (equity curve, candles)
@tanstack/react-query@5  ← Server state management
zustand@5            ← Client state management
socket.io-client@4   ← Live updates
@xyflow/react@12     ← Visual Flow builder
codemirror@6         ← Code editor
lucide-react         ← Icons
react-router-dom@6   ← Routing
date-fns@3           ← Date utilities
```

---

## Port Map

| Service | Port | URL |
|---|---|---|
| OpenAlgo Flask backend | 3000 | http://localhost:3000 |
| OpenAlgo WebSocket proxy | 8765 | ws://localhost:8765 |
| Our FastAPI dashboard API | 8000 | http://localhost:8000 |
| Our React frontend (dev) | 5173 | http://localhost:5173 |

---

## Environment Variables (`.env` — never commit this file)

```bash
# Upstox API
UPSTOX_API_KEY=your_key_here
UPSTOX_API_SECRET=your_secret_here
UPSTOX_REDIRECT_URI=http://localhost:3000/callback
UPSTOX_ACCESS_TOKEN=generated_at_runtime

# OpenAlgo
OPENALGO_API_KEY=your_openalgo_key
OPENALGO_HOST=http://localhost:3000

# Dashboard
DASHBOARD_API_SECRET=random_secret_key
DASHBOARD_PORT=8000

# LLM (Phase 4)
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here

# Telegram
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

# Paths
DB_PATH=data/algo_trading.sqlite
MODELS_PATH=models/saved/
```

---

## Key Design Principles

### 1. BaseSignal Interface — The Core of Extensibility
Every signal (technical, ML, news, LLM) implements the same interface. Adding a new signal = creating one new file with a class that extends `BaseSignal`. The ensemble aggregator, dashboard, and backtest engine all work with any `BaseSignal` automatically.

### 2. Config-Driven Weights
All signal weights and thresholds live in `config/settings.py`. The dashboard's signal sliders write back to this file. No code changes needed to tune the ensemble.

### 3. SQLite (WAL) as the Single Source of Truth
All operational data (raw ticks, candles, features, trades, model metadata) lives in one SQLite file in **WAL mode**. WAL is the key choice: it allows **concurrent readers across processes alongside a single writer**, so every component shares one file with no synchronization layer:
- The live runner writes trades (the single writer)
- The dashboard reads trades **at the same time, from a different process** (this is what DuckDB could not do — LIVE-06)
- The backtest engine reads historical candles
- The retrain script reads trade journeys

Connections are thread-local (`data/db.py`), each opened with `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`. The public helpers still return pandas DataFrames, so callers are storage-agnostic. **DuckDB remains available but optional** — reserved for heavy ad-hoc analytical (OLAP) queries, never on the operational read/write path.

### 4. OpenAlgo as Execution Abstraction
Our code never calls Upstox directly for order execution. It always goes through OpenAlgo. This means:
- Switching to Zerodha/Dhan = change one config line
- SEBI compliance handled by OpenAlgo's empanelled status
- Sandbox testing always available
- Order approval workflow (semi-auto mode) built in

### 5. Phase Gates — No Skipping
Each phase must demonstrate profitability in live trading before the next phase starts. This prevents:
- Debugging ML + execution + LLM simultaneously (impossible to diagnose)
- Deploying a complex system that loses money for unclear reasons
- Over-engineering before the basics work
