# DASHBOARD — Complete Interface Specification

> Full specification for the React control panel dashboard.
> Every page, every control, every API route documented here.
> Combined features from AI-trader (Next.js) and OpenAlgo (React 19).

---

## Overview

Two web interfaces run simultaneously:

| Interface | Port | Purpose |
|---|---|---|
| **OpenAlgo** | 3000 | Broker execution, order routing, options analytics, Sandbox mode, Telegram |
| **Our Dashboard** | 5173 (React) + 8000 (FastAPI) | Signal control, ML models, backtest runner, custom PnL analytics, algo control |

They share the same SQLite (WAL) database — WAL lets the API and the runner read/write it from separate processes at once (LIVE-06) — and communicate via OpenAlgo's REST API.

---

## Tech Stack

### Frontend
```
React 19 + TypeScript 5 + Vite 6
TailwindCSS 4.0
shadcn/ui
Recharts 2 (analytics charts)
TradingView Lightweight Charts 4 (equity curve, candles)
TanStack Query 5 (server state, auto-refetch)
Zustand 5 (global state)
Socket.IO client 4 (live position/order updates)
Server-Sent Events (live log stream)
xyflow/React Flow 12 (visual strategy builder)
CodeMirror 6 (Python/JSON editor)
Lucide React (icons)
React Router DOM 6 (routing)
date-fns 3
```

### Backend API (FastAPI, port 8000)
```
fastapi
uvicorn
python-socketio
sqlite3 (stdlib — operational store, WAL mode)
httpx (async OpenAlgo client)
python-dotenv
```

---

## Page Map

```
localhost:5173/
├── /                    → Dashboard.tsx       (Command centre overview)
├── /live                → Live.tsx            (Live trading monitor)
├── /signals             → Signals.tsx         (Signal control panel)
├── /positions           → Positions.tsx       (Positions, orders, holdings)
├── /trades              → Trades.tsx          (Trade history + PnL analytics)
├── /analytics           → Analytics.tsx       (Edge vs costs · R-multiples · what-if sim · data health) ✅ built 2026-06-07
├── /backtest            → Backtest.tsx        (Run backtests + view results)
├── /models              → Models.tsx          (ML model manager)
├── /options             → Options.tsx         (Options analytics suite)
├── /flow                → Flow.tsx            (Visual strategy builder)
├── /settings            → Settings.tsx        (All configuration)
└── /security            → Security.tsx        (API keys, audit log, IP monitor)
```

---

## Global Layout (all pages)

### Top Navigation Bar
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ [Logo] Dashboard  Live  Signals  Positions  Trades  Backtest  Models  Settings  │
│                            [🟢 RUNNING] [SANDBOX] [⚡ KILL ALL] [🌙 Dark/Light] │
└─────────────────────────────────────────────────────────────────────────────────┘
```
- System status badge (🟢 RUNNING / 🟡 PAUSED / 🔴 KILLED / ⚫ MARKET_CLOSED) always visible
- **⚡ KILL ALL** button — bright red, always in top-right — triggers `POST /api/system/kill`
- Theme toggle (Dark / Light, 8 accent colors)
- Market countdown: "Market closes in 2h 15m" or "Market opens in 6h 30m"
- Latency indicator: shows last order round-trip time (from OpenAlgo latency monitor)

### Right Sidebar — Live Log (collapsible)
- SSE stream from `GET /api/system/log/stream`
- Color coding:
  - `[INFO]` — grey
  - `[SIGNAL]` — blue — e.g., "VWAP breakout RELIANCE score: 0.71"
  - `[TRADE]` — green (entry) / red (loss exit) / green (profitable exit)
  - `[WARNING]` — yellow — e.g., "Score near threshold for INFY 0.63"
  - `[ERROR]` — red — execution failures, data gaps, API errors
- Filter bar: ALL / INFO / SIGNAL / TRADE / WARNING / ERROR
- Symbol search/filter
- Pause scroll button
- Export log to file button

### Notification Toasts (bottom-right, auto-dismiss 5s)
- Trade entered: green — "BUY RELIANCE 2 lots @ ₹1,482 (score: 0.71)"
- Trade exited profit: green — "EXIT RELIANCE +₹1,240 (+0.84%)"
- Trade exited loss: red — "SL HIT INFY -₹640 (-0.43%)"
- Circuit breaker: orange — "⚠ Daily loss limit reached. Trading halted."
- Error: red — "ERROR: OpenAlgo connection failed"

---

## Page 1: Dashboard (`/`) — Command Centre

**Purpose:** Single-glance health check of the entire system.

### Layout
```
┌──────────────────────────────────────────────────────────────────────────┐
│  SYSTEM: 🟢 RUNNING  |  Market: OPEN  |  Session: 2h 14m elapsed        │
│  ⚡ KILL ALL  [⏸ Pause]  [Mode: SANDBOX ▼]                              │
├──────────────────────┬───────────────────────────────────────────────────┤
│                      │  TODAY'S STATS                                    │
│   EQUITY CURVE       │  Net PnL:  +₹4,820    Gross: +₹6,100            │
│   (TradingView       │  Win Rate: 68%         Trades: 12                │
│    Lightweight       │  Max DD:   -₹1,200    Fees: ₹1,280              │
│    Chart)            ├───────────────────────────────────────────────────┤
│                      │  OPEN POSITIONS  (live 1s refresh)               │
│   [All time] [Today] │  RELIANCE  BUY  2L  Entry:1482  LTP:1494  +₹1,240│
│   [Benchmark Nifty]  │  INFY      BUY  1L  Entry:1823  LTP:1819  -₹400 │
│                      │  [Exit RELIANCE] [Exit INFY] [Exit All]          │
├──────────────────────┴───────────────────────────────────────────────────┤
│  QUICK STATS                                                              │
│  7-day PnL: +₹18,400  |  30-day PnL: +₹62,000  |  All-time: +₹1,84,000 │
│  All-time WR: 61%  |  Avg trade: +₹820  |  Profit factor: 2.1           │
├──────────────────────────────────────────────────────────────────────────┤
│  CURRENT REGIME: 🟦 TRENDING_UP (87% confidence)                        │
│  VIX: 14.2  |  NIFTY: +0.4%  |  PCR: 1.12  |  Signal queue: 2 waiting  │
└──────────────────────────────────────────────────────────────────────────┘
```

### Kill Switch Modal (on click)
```
⚠️ EMERGENCY STOP

This will:
  1. Cancel ALL open orders
  2. Market-exit ALL open positions
  3. Stop the trading loop
  4. Log reason to audit trail

Reason (optional): [________________]

[Cancel]  [CONFIRM KILL ALL — red button]
```

---

## Page 2: Live Trading Monitor (`/live`)

**Purpose:** Real-time view of signals, positions, and the algo's decision-making.

### Section 1: Market Pulse Strip (top)
```
NIFTY  24,820  +0.42%  VWAP dist: +0.12%  |  BankNIFTY  52,140  +0.61%
VIX  14.20  |  IV%ile  34%  |  PCR  1.12  |  Advances: 1,284  Declines: 468
```

### Section 2: Signal Scanner (left panel, refreshes every 30s)

Table columns:
- Symbol
- **Score** (color bar: red < 0.55, yellow 0.55–0.65, green > 0.65)
- Top signal (which signal is driving the score most)
- Regime
- RSI
- VWAP dist %
- Volume ratio
- Open position? (badge)
- [Force Enter] button (requires score ≥ 0.55, shows confirmation modal)

### Section 3: Active Trade Monitor (right panel, 1s refresh)

For each open position, a card showing:
- Symbol, side, lots
- Mini chart: premium/price journey since entry (TradingView Lightweight)
- Current PnL (₹ and %)
- Time in trade: "42 min"
- SL: ₹1,462 (distance: -₹20 / -1.35%)
- Target: ₹1,510 (distance: +₹16 / +1.08%)
- RL Agent recommendation badge: HOLD / TIGHTEN / EXIT
- [Manual Exit] button
- [Move SL to Entry] button (lock in breakeven)

### Section 4: Execution Mode Toggle
```
[🤖 AUTO]  [👆 SEMI-AUTO]  [👁 MONITOR ONLY]
```
- **AUTO**: signals auto-enter when score ≥ threshold
- **SEMI-AUTO**: signals queue up in "Approval Queue" section, require one-click approve
- **MONITOR ONLY**: no entries, only shows what would have been entered

### Section 5: Approval Queue (semi-auto only)
```
RELIANCE  BUY  Score: 0.73  2 lots  VWAP Breakout  [✓ Approve]  [✗ Reject]
TCS       BUY  Score: 0.68  1 lot   RSI Momentum   [✓ Approve]  [✗ Reject]
```

---

## Page 3: Signal Control Panel (`/signals`)

**Purpose:** Full control over the ensemble engine — tune weights, enable/disable signals, see per-signal performance.

### Signal Registry

Each signal shown as a card:
```
┌─────────────────────────────────────────────────────────────────┐
│  VWAP Momentum Breakout                        [● ENABLED ▪▫▫]  │
│  Type: Technical  |  Phase: 1  |  Default weight: 0.40          │
│                                                                  │
│  Weight:  ──────────●────────  0.40                             │
│  Score threshold for entry: ──────●──────  0.65                 │
│                                                                  │
│  Performance (last 30 trades using this signal):                │
│  Win Rate: 65%  |  Avg PnL: +₹820  |  Contribution: +0.28      │
│                                                                  │
│  Current scores: RELIANCE: 0.75  TCS: 0.50  INFY: 0.60         │
│                                                                  │
│  [Backtest This Signal Alone]  [Reset to Default]  [Disable]    │
└─────────────────────────────────────────────────────────────────┘
```

Signal cards shown in order:
**Phase 1 (always visible):**
1. VWAP Momentum Breakout
2. RSI Momentum
3. Mean Reversion

**Phase 2 (shown when ML is activated):**
4. Macro XGBoost
5. Micro XGBoost (gate)
6. Regime Detector (not a score signal — shows current regime)
7. Strategy Outcome Models (gate)

**Phase 3 (shown when news is activated):**
8. NSE Announcement Filter (suppression)
9. FinBERT News Sentiment
10. Options Flow

**Phase 4 (shown when LLM is activated):**
11. Technical Analyst Agent
12. News Analyst Agent
13. Risk Agent (multiplier)

### Global Controls
```
┌─────────────────────────────────────────────────────────────┐
│  MASTER CONTROLS                                             │
│                                                              │
│  Entry score threshold:    ───────────●──  0.65             │
│  Signal score threshold:   ──────●────────  0.55            │
│                                                              │
│  [Re-normalize weights to sum to 1.0]                       │
│  [Reset ALL to defaults]                                     │
│  [Save configuration]  ← writes to config/settings.py      │
└─────────────────────────────────────────────────────────────┘
```

### Live Score Formula Display
```
Current ensemble formula:
  score = 0.40 × VWAP_breakout
        + 0.35 × RSI_momentum
        + 0.25 × mean_reversion
        + regime_bonus

⚠ Weights do not sum to 1.0  [Re-normalize]
```
Updates live as sliders move. Red warning if weights don't sum to 1.0.

### Signal History Chart (bottom)
- Select symbol from dropdown
- Line chart: each signal's score contribution over last 50 bars
- Shows divergence/convergence of signals
- Useful for seeing which signal is driving vs lagging

---

## Page 4: Positions & Orders (`/positions`)

**Purpose:** Full position and order management (proxied from OpenAlgo).

### Tabs

**Open Positions**
- Symbol, Exchange, Product (MIS/NRML/CNC), Side, Qty, Avg Price, LTP, P&L, P&L%
- Color: green row = profit, red row = loss
- Per row: [Modify SL] [Close Position] buttons
- Bottom: [Square Off ALL] button (with big confirmation modal)

**Order Book** (live, Socket.IO)
- Time, Symbol, Type (MKT/LMT/SL), Side, Qty, Price, Status (OPEN/COMPLETE/REJECTED/CANCELLED)
- Filters: status, symbol, strategy
- [Cancel] per open order
- [Modify] for limit orders (inline edit)

**Trade Book**
- All executed trades today
- Time, Symbol, Side, Qty, Trade Price, Exchange Order ID
- [Export CSV]

**Holdings** (delivery / CNC positions)
- Symbol, Qty, Avg Price, Current Price, Day P&L, Total P&L
- Sector breakdown pie chart (below table)

**Funds**
- Available cash, Used margin, Collateral, Total
- Segment breakdown bar (Equity / F&O / Currency)
- Real-time margin utilization % gauge

---

## Page 5: Trade History & PnL Analytics (`/trades`)

**Purpose:** Deep analysis of all historical trades.

### Filter Bar (sticky top)
- Date range: [Today] [This Week] [This Month] [3M] [6M] [1Y] [Custom ▼]
- Strategy: multi-select dropdown
- Symbol: multi-select
- Regime: multi-select
- Win/Loss/All toggle

### Trade Log Table (paginated, 50 rows/page)
Columns:
| Column | Notes |
|---|---|
| Entry Time | IST, sortable |
| Exit Time | IST |
| Symbol | Clickable → filters to that symbol |
| Side | BUY/SELL badge |
| Qty | Number of shares |
| Entry Price | |
| Exit Price | |
| Gross PnL | ₹ |
| Fees | STT + brokerage combined |
| Net PnL | Color: green/red |
| PnL % | |
| Score | Score at entry |
| Strategy | Clickable → filter |
| Exit Reason | Badge (SL_HIT / TARGET / TRAILING / RL_EXIT / MANUAL / EOD) |
| Regime | Badge |
| Duration | "42 min" |
| ML Confidence | Macro model P(bullish) at entry |

Row click → expand to show: full signal_scores JSON, entry chart snippet, notes field

**[Export CSV]** and **[Export Excel]** buttons

### Analytics Charts (below table)

**Row 1 — PnL Overview**
- Cumulative equity curve (all-time, drawdown shading in red below zero)
- Monthly PnL bar chart (green/red by month)
- Rolling 20-trade win rate line

**Row 2 — Strategy Performance**
- PnL by strategy: grouped bars (wins vs losses)
- Win rate by strategy: horizontal bar chart
- Average trade PnL by strategy: bar chart

**Row 3 — Time Analytics**
- **PnL heatmap** by hour × day-of-week (9:15–15:30 rows, Mon–Fri columns)
  - Color: green = best average PnL, red = worst
  - Find your personal edge hours
- Trade distribution histogram by hour
- Average trade duration by strategy

**Row 4 — Signal Analytics**
- Score distribution histogram (winning trades green, losing trades red)
- Average score for wins vs losses (scatter plot)
- Which signal contributed most to win/loss (stacked bar)

**Row 5 — Risk Metrics**
| Metric | Value | Description |
|---|---|---|
| Sharpe Ratio | 1.24 | Risk-adjusted return |
| Sortino Ratio | 1.87 | Downside risk adjusted |
| Profit Factor | 2.1 | Gross profit / Gross loss |
| Expectancy | +₹680 | Expected PnL per trade |
| Max Drawdown | -4.2% | Largest peak-to-trough |
| Calmar Ratio | 3.1 | Return / Max drawdown |
| Avg Win / Avg Loss | 2.3× | Win/loss ratio |

---

## Page 5b: Analytics & Simulation (`/analytics`) — ✅ built 2026-06-07

**Purpose:** answer "is there an edge, net of costs?" and let you re-price the trade
log without re-running the engine. All endpoints are GET (read-only) under
`/api/analytics/*`. Window (1W/1M/3M/ALL) + mode (ALL/PAPER/LIVE) controls in the header.

### Panels
- **Edge vs Costs (DASH-02)** — `GET /analytics/summary?days=&mode=`. Headline tiles:
  gross edge (bps of notional) vs cost drag (bps), net P&L, expectancy (₹ and R). A
  green/red verdict badge fires when gross edge ≤ cost drag ("NO EDGE — COSTS DOMINATE").
- **Secondary KPIs** — trades, net win-rate, profit factor, avg R.
- **R-Multiple Distribution (DASH-03)** — `GET /analytics/r-multiples`. Histogram of
  net P&L ÷ risk (|entry−SL|×qty) per trade; green/red by sign.
- **What-If Simulator (DASH-04)** — `GET /analytics/whatif?cost_mult=&min_score=&only_target_exits=`.
  Sliders re-price closed trades under different cost multipliers / selectivity /
  exit-discipline; shows baseline vs scenario net, win-rate, expectancy side by side.
- **By Exit Reason** — `GET /analytics/by-exit-reason`. Net performance per
  SL_HIT / TARGET_HIT / REVERSAL / EOD.
- **Data Health & Coverage (DASH-05)** — `GET /analytics/data-health`. Bars per
  (symbol, timeframe, source), last-bar age, and a DEMO flag so you never backtest on
  seed data by mistake.

### Still to build
- **Backtest Lab (DASH-01)** — run the engine from the UI with sliders + per-fold /
  per-regime / time-of-day breakdowns (extends the Backtest page below).
- **Model-edge panel (DASH-06)** and **live risk gauges (DASH-07)**.

---

## Page 5c: Action Replay (`/action-replay`) — ✅ built

**Purpose:** Re-run any past trading day with full strategy fidelity — same DailyScreener,
EnsembleAggregator, ML gates, risk controls, and position sizing as the live runner. No
real orders are placed (pure simulation), even when `UPSTOX_MODE=live`.

### Setup Form

```
┌─────────────────────────────────────────────────────────────────────┐
│  DATE         [2026-06-05 ▼]   RISK     [LOW ▼]                     │
│  CAPITAL      [₹20,000    ]    ML GATES [ON (live-faithful) ▼]      │
│  MIS MARGIN   [⚡ MIS ON  ]    [▶ Run Replay]                        │
└─────────────────────────────────────────────────────────────────────┘
```

- **Date** — IST session date to replay (any past trading day with data in DB).
- **Capital** — starting capital; defaults to `TRADING_CAPITAL` from `.env`.
- **Risk Profile** — LOW / MEDIUM / HIGH (same ATR multiples as live).
- **ML Gates** — toggle ML gate models ON/OFF. OFF = pure rule-based, useful for comparing with/without ML.
- **MIS Margin** — `⚡ MIS ON` / `CASH ONLY` toggle. When ON, position sizes are scaled using the MIS margin multiplier from the broker cache. Requires `data/margin_multipliers.json` (run `scripts/fetch_margin_multipliers.py` with a live token first).

### Progress Bar
Live progress from the backend (0–100%) with status message, polled every 800ms.

### KPI Strip
```
Net P&L  |  Win Rate  |  Trades  |  Gross  |  Costs  |  Margin/Exposure
```

### Watchlist Table — Universe & Position Scan
Columns: Symbol · Strategies · Screener Score · Live Score · Regime · **MIS Mult.** · Status

- **MIS Mult.** — broker MIS leverage for this stock (green ≥4×, yellow ≥2×, red <2×, `—` = cache empty). Hover shows margin % of notional.
- **Status** badges: `SCANNING` / `SIGNAL` / `ARMED` / `GATED` / `IN_POSITION` / `TRADED`

### Trades Table
Columns: Symbol · Direction · Qty · Entry · Exit · Notional · Net P&L · Exit Reason

Clicking a row expands a detail panel:
```
Side: LONG (LONG) · Notional: ₹4,750 = 0.24× capital (within cash) · Held: 3 bars
MIS Margin blocked: ₹950 at 5.0× MIS leverage (20.0% of notional)
Entry score: 0.712 · Regime: TRENDING_UP · Gross: +₹142 · Cost: ₹9.5
Signals: vwap_breakout: 0.78 · rsi_momentum: 0.65 · mean_reversion: 0.21
Sizing: Tier:3LOT(>=0.75) | 19 sh (risk ₹200 @5.0×MIS)+RISK_SCALED | qty:19
```

### Gate Rejection Panel
Bar chart of why signals were blocked (ML gate / cost filter / circuit breaker / CHOPPY stand-down / sizing/heat).

### Timeline (playable event log)
- Play / Pause / speed selector (1× 2× 5× 10×)
- Scrub slider
- Per-event rows: timestamp · event type · symbol · detail
  - ENTRY events show `[4.5× MIS]` when margin is active
- Events: `UNIVERSE_SET` / `ENTRY` / `EXIT` / `GATE_BLOCK` / `ARMED` / `TRAIL_SL` / `BREAKER_HALT` / `SESSION_CLOSE`

### NO_DATA Banner
If Upstox backfill failed (token missing / holiday / weekend), a banner instructs the
user to run `scripts/refresh_token.py` and retry.

---

## Page 6: Backtest Runner (`/backtest`)

**Purpose:** Run backtests from the UI, view results, compare runs.

### Run New Backtest (form)

```
┌──────────────────────────────────────────────────────────────┐
│  NEW BACKTEST                                                │
│                                                              │
│  Instruments:  [Nifty 50 ▼]  [+ Add symbols]              │
│  Date range:   [2025-06-01]  to  [2026-06-04]               │
│  Timeframe:    [5min ▼]                                      │
│  Signals:      [✓ VWAP] [✓ RSI] [✓ Mean Rev] [☐ ML]        │
│  Risk profile: [○ LOW  ● MEDIUM  ○ HIGH]                    │
│  Walk-forward: [✓ ON]  Train: [4M]  Test: [2M]             │
│  Slippage:     [○ 0.03%  ● 0.05%  ○ 0.10%]                 │
│                                                              │
│  [▶ RUN BACKTEST]              Estimated time: ~45s          │
└──────────────────────────────────────────────────────────────┘
```

### Progress Display
```
Running backtest...  ████████████░░░░░  73%
Processing 2025-12-14... (fold 3/6)
[Cancel]
```
Progress streamed via SSE from `GET /api/backtest/progress?run_id=XYZ`

### Results Panel

**Summary Card**
```
┌───────────────────────────────────────────────────────────────────┐
│  Backtest: Nifty 50 | 5min | Jun 2025 – Jun 2026 | MEDIUM risk   │
│                                                                   │
│  Total Return:    +22.4%     Sharpe Ratio:   1.34               │
│  Ann. Return:     +22.4%     Sortino Ratio:  1.92               │
│  Max Drawdown:    -4.8%      Profit Factor:  2.3                │
│  Win Rate:        62%        Expectancy:     +₹720              │
│  Total Trades:    387        Avg Trade:      +₹720              │
└───────────────────────────────────────────────────────────────────┘
```

**Charts:**
- Equity curve with drawdown shading (TradingView Lightweight Charts)
- Monthly returns heatmap (calendar grid)
- Exit reason pie chart (SL / TARGET / TRAILING / RL / TIMEOUT)

**Walk-Forward Table:**
| Fold | Train Period | Test Period | Sharpe | Return | Drawdown | Trades |
|---|---|---|---|---|---|---|
| 1 | Jun–Sep 25 | Oct–Nov 25 | 1.21 | +4.2% | -3.1% | 64 |
| 2 | Jul–Oct 25 | Nov–Dec 25 | 1.45 | +5.1% | -2.8% | 58 |
| ... | ... | ... | ... | ... | ... | ... |
| Avg | | | 1.34 | +3.8% | -3.4% | 64.5 |

### Compare Runs (side-by-side)
- Select 2–4 runs from history
- Overlay equity curves on single chart
- Side-by-side metrics table
- Highlight winner in each metric

### Backtest History
- All past runs table: date run, instruments, Sharpe, return, win rate
- [Load Results] per row
- [Delete] per row
- [Export HTML Tearsheet] per row

---

## Page 7: ML Model Manager (`/models`)

**Purpose:** Track, retrain, and evaluate every ML model.

### Model Cards

```
┌──────────────────────────────────────────────────────────────┐
│  Macro XGBoost (Directional Gate)              [● ACTIVE]    │
│  Last trained: 2026-06-03 18:45 IST                          │
│  Training window: 2026-01-01 → 2026-06-01                    │
│  Training samples: 48,320 bars                               │
│                                                              │
│  Performance (walk-forward):                                 │
│  AUC: 0.612    Accuracy: 58.4%    Precision: 0.61           │
│  Recall: 0.58  F1: 0.595                                     │
│                                                              │
│  Feature drift: 🟢 LOW (last check: 2h ago)                 │
│                                                              │
│  [▶ Retrain Now]  [📊 Feature Importance]  [📈 AUC History] │
└──────────────────────────────────────────────────────────────┘
```

Model cards for:
1. **Macro XGBoost** — directional gate
2. **Micro XGBoost** — entry confirmation gate
3. **Regime Detector** — regime classification
4. **Strategy Outcome: VWAP** — WIN/LOSS gate
5. **Strategy Outcome: RSI** — WIN/LOSS gate
6. **Strategy Outcome: Mean Rev** — WIN/LOSS gate
7. **RL Exit Agent** — HOLD/EXIT/TIGHTEN actions

### Retrain Flow
1. Click [Retrain Now] on any model card
2. Confirmation modal: shows training window dates, estimated time
3. Progress: live log stream of training output (SSE)
4. Completion: modal shows old AUC vs new AUC
   - Green: improved
   - Red: degraded (option to keep old model)
5. Previous model auto-backed up to `models/saved/backups/YYYYMMDD/`

### Feature Importance Chart
- Top 20 features for Macro model (horizontal bar chart)
- Recharts BarChart, color by feature category (momentum/trend/volatility/etc.)
- Refreshes after every retrain

### AUC History Chart
- Line chart: AUC score over each retrain
- Horizontal reference line at 0.50 (random) and 0.58 (target)
- Shows if model is drifting or improving

### RL Exit Agent Details
- Current Q-value table (state × action heatmap)
- Exit breakdown: % HOLD / EXIT / TIGHTEN per session
- Reward curve from last training run

---

## Page 8: Options Analytics (`/options`)

**Purpose:** All 12 OpenAlgo options tools in our dashboard.

All tools stream live from Upstox via OpenAlgo's unified WebSocket.

### Tools
1. **Strategy Builder** — multi-leg construction, live Greeks, payoff diagram, one-click basket
2. **Strategy Portfolio** — saved strategies watchlist + simulation
3. **Option Chain** — live Greeks per strike, inline click-to-trade
4. **Option Greeks History** — historical IV, Delta, Theta, Vega, Gamma (ATM)
5. **OI Tracker** — CE/PE OI bars, PCR overlay, ATM strike marker
6. **Max Pain** — live max pain strike, pain distribution chart
7. **Straddle Chart** — dynamic ATM straddle + synthetic futures overlay
8. **Straddle PnL** — intraday straddle simulation, auto N-point adjustments
9. **Vol Surface** — 3D implied vol surface across strikes & expiries
10. **GEX Dashboard** — OI walls, net GEX per strike, top gamma strikes
11. **IV Smile** — Call + Put IV curves with skew analysis
12. **OI Profile** — futures candles with OI butterfly overlay

**Our custom additions (not in OpenAlgo):**
- **IV Rank Tracker** — current IV vs 52-week range (0–100 scale) per instrument
- **Theta Decay Monitor** — daily theta collected for open short positions
- **PCR History** — PCR over the last 30 days chart

---

## Page 9: Visual Strategy Builder (`/flow`)

**Purpose:** Drag-and-drop no-code strategy builder (OpenAlgo Flow pattern).

### Node Types
**Data nodes:** OHLCV feed, tick feed, option chain data, news feed

**Indicator nodes:** RSI, MACD, VWAP, EMA, ATR, Bollinger Bands, OBV, ADX, Volume Ratio

**Condition nodes:** `>`, `<`, `=`, AND, OR, NOT, crossover, crossunder
- Condition nodes have TRUE/FALSE output edges

**Signal nodes:** Link to our `BaseSignal` modules (VWAP Breakout, RSI Momentum, etc.)

**Score node:** Ensemble aggregator with configurable weight inputs per connected signal

**Action nodes:** Place order, Modify SL, Cancel order, Alert (Telegram), Log event

**Risk nodes:** Circuit breaker check, position size calculator

**Notification nodes:** Telegram message, dashboard log event

### Features
- JSON import/export (share strategies between traders)
- [▶ Test in Sandbox] — runs against current sandbox with real market data
- Visual execution trace: highlights which nodes fired on last bar
- Save multiple named strategies
- Schedule: select specific days of week / time windows

---

## Page 10: Settings (`/settings`)

**Purpose:** All configuration in one place.

### Sections

**Broker & Connection**
- Upstox API Key: [masked] [Show] [Regenerate]
- Upstox API Secret: [masked] [Show]
- OpenAlgo Host: http://localhost:3000 [Test Connection]
- OpenAlgo API Key: [masked] [Show]
- Connection status: 🟢 Connected / 🔴 Disconnected
- **Trading mode**: [🔵 SANDBOX] [🔴 LIVE — big warning modal on toggle]

**Risk Profile**
- Quick select: [LOW] [MEDIUM] [HIGH]
- Or custom mode (toggle) — shows all parameters individually:
  - Max daily loss: ₹[____]
  - Max concurrent positions: [1–20 slider]
  - Max trades per day: [1–50 slider]
  - Lot size cap: [1–5 slider]
  - Score threshold for entry: [0.50–0.80 slider]
  - SL ATR multiplier: [0.5–3.0 slider]
  - Target ATR multiplier: [0.5–5.0 slider]
  - Trailing SL activation: [0.5–2.0 slider]
  - Trailing SL lock-in: [0.3–1.5 slider]

**Instrument Watchlist**
- Table: symbol, exchange, enabled toggle, lot size override, score threshold override
- [+ Add symbol] (search box with live lookup)
- [Import CSV] button (format: symbol, exchange, enabled)
- Quick presets: [Nifty 50] [BankNifty F&O] [All F&O underlyings]

**Trading Schedule**
- Market open: 09:15 IST (editable)
- Market close: 15:30 IST (editable)
- No-trade window at open: [15 minutes] slider
- No-trade window at close: [30 minutes] slider
- Custom blackout dates: date picker + add
- NSE holidays 2026: [pre-populated list, editable]

**Data Settings**
- Historical data range to maintain: [1 year ▼]
- Candle timeframes: [✓ 1min] [✓ 5min] [✓ 15min] [☐ 1hr]
- Auto-backfill on startup: [✓]
- SQLite DB file path: data/algo_trading.sqlite [Browse]
- [Run Data Quality Check] button

**Notifications**
- Telegram bot token: [masked] [Test]
- Telegram chat ID: [____]
- Notify on: [✓ Trade entry] [✓ Trade exit] [✓ Circuit breaker] [✓ Retrain complete] [✓ Errors] [☐ Signals (verbose)]
- Daily summary time: [16:00 IST ▼]

**LLM Settings (Phase 4)**
- LLM provider: [None ▼] / OpenAI / Anthropic / Local Ollama
- API key: [masked]
- Model: [gpt-4o-mini ▼]
- Max LLM spend per day: ₹[____]
- Ollama host (if local): http://localhost:11434

**Appearance**
- Theme: [🌙 Dark] [☀ Light]
- Accent color: 8 color swatches
- Dashboard refresh rate: [1s] [5s] [30s]
- Log sidebar: [Docked right] [Floating] [Hidden]

---

## Page 11: Security (`/security`)

**Purpose:** API key management, session monitoring, audit log.

### Sections

**API Keys**
- Dashboard API key: [masked] [Reveal] [Regenerate]
- Upstox API key status: 🟢 Valid (expires daily — shows time to expiry)
- OpenAlgo API key: [masked] [Reveal]

**Two-Factor Authentication**
- Current status: Enabled / Disabled
- [Enable 2FA] → QR code for authenticator app
- [Disable 2FA] → requires current TOTP code

**Active Sessions**
- Table: Session ID, IP address, Started, Last active, Browser
- [Revoke] per session
- [Revoke All Other Sessions] button

**IP Monitor**
- Live table: Timestamp, IP, Endpoint, Status (200/401/429)
- [Ban IP] button per row
- Banned IPs list with [Unban] option

**Rate Limits (current settings)**
- Login attempts: 5 per 10 minutes
- API calls: 1000 per minute
- Order placement: 50 per minute

**Audit Log** (all system actions, forever retained)
| Timestamp | User | Action | Details |
|---|---|---|---|
| 2026-06-04 10:23:14 | localhost | TRADE_ENTERED | RELIANCE BUY 2L @1482 score:0.71 |
| 2026-06-04 10:15:02 | localhost | SETTINGS_CHANGED | risk_profile: MEDIUM→HIGH |
| 2026-06-04 09:45:11 | localhost | MODEL_RETRAINED | macro_model AUC 0.601→0.612 |
| 2026-06-04 09:14:55 | localhost | SYSTEM_STARTED | runner.py started, 7 instruments |
| 2026-06-03 15:28:33 | localhost | KILL_SWITCH | reason: "testing", positions: 2 closed |

---

## FastAPI Backend — All Routes

```
=== SYSTEM ===
GET  /api/system/status               → {state, uptime, market_open, last_signal}
POST /api/system/start                → start live runner
POST /api/system/pause                → pause new entries, hold positions
POST /api/system/resume               → resume from pause
POST /api/system/kill                 → emergency: cancel all, exit all, stop loop
GET  /api/system/log/stream           → SSE stream of live log events
GET  /api/system/health               → {db_ok, openalgo_ok, upstox_ok}
POST /api/system/risk                 → {profile: LOW|MEDIUM|HIGH} — set risk profile (live via control plane + .env)
POST /api/system/capital              → {capital: number} — set trading capital used for sizing/risk (live + .env)
GET  /api/system/funds                → actual Upstox funds via OpenAlgo {ok, available, used, total}; ok:false in paper/sandbox

=== SIGNALS ===
GET  /api/signals/                    → all signals with weights, enabled, stats
GET  /api/signals/{name}              → single signal details
PUT  /api/signals/{name}/weight       → update weight (body: {weight: float})
PUT  /api/signals/{name}/enable       → toggle enable (body: {enabled: bool})
GET  /api/signals/{symbol}/scores     → current scores for a symbol from all signals
PUT  /api/signals/threshold           → update entry threshold (body: {threshold: float})
POST /api/signals/save                → persist current weights/thresholds to settings.py
POST /api/signals/normalize           → auto-scale weights to sum to 1.0

=== TRADES ===
GET  /api/trades/                     → paginated trade log (filters: date, strategy, symbol, regime, win)
GET  /api/trades/equity-curve         → [{timestamp, cumulative_pnl}]
GET  /api/trades/daily                → daily_performance table
GET  /api/trades/analytics/heatmap    → {hour_day_matrix: [[avg_pnl]]}
GET  /api/trades/analytics/by-strategy → [{strategy, win_rate, avg_pnl, total_trades}]
GET  /api/trades/analytics/signals    → signal contribution to wins vs losses
GET  /api/trades/analytics/risk       → {sharpe, sortino, max_dd, profit_factor, expectancy}
GET  /api/trades/export               → CSV file download

=== POSITIONS (proxy OpenAlgo) ===
GET  /api/positions/open              → open positions from OpenAlgo
GET  /api/positions/orders            → order book
GET  /api/positions/trades-today      → today's executed trades
GET  /api/positions/holdings          → delivery holdings
GET  /api/positions/funds             → funds + margin
POST /api/positions/{id}/exit         → exit a specific position
POST /api/positions/exit-all          → square off all positions
POST /api/positions/{id}/modify-sl    → modify stop-loss (body: {sl_price: float})

=== ACTION REPLAY ===
POST /api/replay/run                  → {date, capital?, risk_profile?, use_ml_gates, use_margin} → start replay in background
GET  /api/replay/status               → {state, progress, message, run_id, date}
GET  /api/replay/result               → full result dict (events, trades, universe, summary, gate_counts)
GET  /api/replay/history              → last N saved replay runs (from replay/results/*.json)

=== BACKTEST ===
POST /api/backtest/run                → start backtest job (returns run_id)
GET  /api/backtest/progress           → SSE stream for run_id
GET  /api/backtest/results/{run_id}   → full results
GET  /api/backtest/history            → all past runs summary
DELETE /api/backtest/{run_id}         → delete run + results file

=== MODELS ===
GET  /api/models/                     → all model cards (status, AUC, last trained)
GET  /api/models/{name}               → single model details
POST /api/models/{name}/retrain       → trigger retrain (async)
GET  /api/models/{name}/progress      → SSE stream of training log
GET  /api/models/{name}/features      → feature importance [{feature, importance}]
GET  /api/models/{name}/auc-history   → [{trained_at, auc, accuracy}]

=== MARKET DATA (proxy via OpenAlgo) ===
GET  /api/market/quote/{symbol}       → {ltp, ohlc, volume, bid, ask, depth}
GET  /api/market/candles              → historical candles (params: symbol, tf, from, to)
GET  /api/market/option-chain/{sym}   → option chain snapshot
GET  /api/market/regime/{symbol}      → current regime classification

=== SETTINGS ===
GET  /api/settings/                   → full config (safe subset, no secrets)
PUT  /api/settings/                   → update config
GET  /api/settings/risk-profiles      → LOW/MEDIUM/HIGH definitions
PUT  /api/settings/risk-profile       → switch profile (body: {profile: "MEDIUM"})
GET  /api/settings/watchlist          → instrument watchlist
POST /api/settings/watchlist          → add symbol
DELETE /api/settings/watchlist/{sym}  → remove symbol
POST /api/settings/test-broker        → test Upstox + OpenAlgo connection
POST /api/settings/validate-env       → check all .env variables are set

=== SECURITY ===
GET  /api/security/sessions           → active sessions
DELETE /api/security/sessions/{id}    → revoke session
GET  /api/security/ip-log             → recent IP access log
POST /api/security/ip-ban             → ban an IP
GET  /api/security/audit-log          → paginated audit log
```

---

## Socket.IO Events (real-time updates)

```
Server → Client events:
  'position_update'    → {symbol, ltp, unrealized_pnl, ...}
  'order_update'       → {order_id, status, ...}
  'trade_executed'     → {trade_id, symbol, side, qty, price, pnl}
  'circuit_breaker'    → {reason, timestamp}
  'regime_change'      → {symbol, old_regime, new_regime, confidence}
  'system_state'       → {state: "RUNNING"|"PAUSED"|"KILLED"}

Client → Server events:
  'subscribe_symbol'   → subscribe to real-time position updates for a symbol
  'unsubscribe_symbol' → unsubscribe
```

---

## Build Order (Phase 1, Week 4)

**Backend first (day 1–2):**
1. `dashboard/api/main.py` — FastAPI skeleton, all routes stubbed with 200 returns
2. `dashboard/api/routes/trades.py` — trade log + equity curve (SQLite reads)
3. `dashboard/api/routes/system.py` — start/stop/kill, system status
4. `dashboard/api/websocket.py` — SSE log stream

**Frontend (day 2–5):**
5. React scaffold: `npm create vite@latest frontend -- --template react-ts`
6. Install: tailwindcss, shadcn/ui, recharts, lightweight-charts, tanstack-query, zustand, socket.io-client
7. Navbar + Sidebar layout components
8. `/trades` page — first page (pure data, no live dependency) ← verify data layer
9. `/` Dashboard — equity curve + open positions + kill switch
10. `/signals` page — signal cards + weight sliders
11. `/live` page — signal scanner + position monitor
12. `/positions` page — proxy OpenAlgo data
13. `/backtest` page
14. `/models` page
15. `/settings` page
16. `/options` + `/flow` pages (OpenAlgo integration)
17. `/security` page
