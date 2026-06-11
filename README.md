# AlgoTrading — Indian Markets (NSE/BSE/F&O/Currency)

Modular ensemble algorithmic trading system for Indian markets using Upstox + OpenAlgo.

---

## Quick Navigation

| Document | Description |
|---|---|
| **[MASTER_PLAN.md](MASTER_PLAN.md)** | Start here — architecture decisions, status tracker, open questions |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Phase-by-phase build plan, week-by-week tasks, milestones |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | System design, component map, full repo file structure |
| **[docs/DASHBOARD.md](docs/DASHBOARD.md)** | Complete dashboard spec — all 11 pages, every control, all API routes |
| **[docs/DATA.md](docs/DATA.md)** | Data sources, SQLite schema, data pipeline |
| **[docs/SIGNALS.md](docs/SIGNALS.md)** | Every signal: formula, parameters, 80-feature list, ensemble formulas |
| **[docs/SEBI_COMPLIANCE.md](docs/SEBI_COMPLIANCE.md)** | Regulatory checklist, white-box vs black-box, RA registration guide |
| **[docs/IDEAS_ADVANCED.md](docs/IDEAS_ADVANCED.md)** | Ideas bank — RL agents, alpha signals, risk upgrades, research papers, Reddit/Twitter insights |

---

## System at a Glance

```
9:00 IST  Screener (Nifty 500) → ranks all stocks → top 10–15 per strategy → daily_watchlist.json
                                                                           ↓
9:15 IST  Upstox WebSocket (live ticks, top 15 only)  →  SQLite  →  80 Features
                                                                           ↓
          Signals (VWAP / RSI / ML / FinBERT / RL)  →  Ensemble Score
                                                                           ↓
          Position Sizer (score tier × Kelly × portfolio heat × RL sizing)
                                                                           ↓
OpenAlgo (order router only, SEBI Algo ID) → Upstox → NSE Exchange
                                                                           ↓
          trade_log (SQLite)  →  FastAPI (port 8000)  →  React Dashboard (port 5173)
```

The live loop is **event-driven**: signals fire when a bar closes (the feed force-closes bars
on a wall clock so quiet/EOD bars aren't lost), the position monitor acts only on fresh prices
(alerts instead of silently disabling stops on a stale feed), and dashboard controls reach the
runner via a control plane. See `docs/ARCHITECTURE.md` → Data Flow, and `docs/KNOWN_ISSUES.md`
for the fix tracker. Next reliability step: broker-side OCO stops.

**4 build phases:**
- **Phase 1 (Weeks 1–4):** Rule-based momentum — VWAP, RSI, Mean Reversion
- **Phase 2 (Weeks 5–10):** ML signals — XGBoost + Regime Detection + RL Exit + RL Entry + RL Sizing
- **Phase 3 (Weeks 11–16):** News/sentiment — FinBERT + NSE Announcements + Options Flow
- **Phase 4 (Weeks 17+):** LLM agents + Auto alpha discovery

---

## Prerequisites

- Python 3.11+
- Node.js 20+ (for React dashboard)
- Upstox account with API access
- OpenAlgo running locally (https://github.com/marketcalls/openalgo)

## Setup

```bash
# 1. Clone and create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and fill in API keys
copy .env.example .env
# Edit .env with your Upstox API key/secret and OpenAlgo key

# 4. Initialize database
python -c "from data.db import init_db; init_db()"

# 5. Backfill historical data
python data/upstox_history.py

# 6. Start dashboard API
uvicorn dashboard.api.main:app --port 8000 --reload

# 7. Start React frontend (separate terminal)
cd dashboard/frontend && npm install && npm run dev

# 8. Start the runner (market hours only)
python live/runner.py --paper     # PAPER: virtual money on the LIVE feed (forward test)
python live/runner.py             # LIVE / paper per PAPER_TRADE in .env
```

---

## Backtest vs paper (forward) testing

Two different ways to validate, both supported:

- **Backtest** — replays *historical* candles already in SQLite through the full strategy
  (walk-forward, intrabar SL/target fills, real sizing + Indian costs). Trigger from the
  dashboard Backtest page or `backtest/engine.py`. Answers *"would this have worked?"*
- **Paper / forward test** — runs the **real strategy on the LIVE feed in real time with
  virtual money**: identical signals, sizing and risk, fake fills, P&L computed from the live
  ticks, all day, EOD square-off. `python live/runner.py --paper` during market hours.
  Answers *"does it work right now, before risking capital?"*

Paper and live trades are tagged (`trade_log.mode` = `PAPER` | `LIVE`), so a virtual day's P&L
is isolated from real results — filter via `/api/trades/daily-stats?mode=PAPER`. Switch
real↔virtual with the `PAPER_TRADE` flag (or the dashboard mode toggle); the logic is identical,
only the order fills are simulated. You can't "backtest the live stream" (backtest is historical
by definition) — paper trading is the live-feed equivalent.

---

## Current Status

See `MASTER_PLAN.md` for full status tracker.
