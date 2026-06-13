# Codebase Map — What Actually Exists

> Snapshot of the **real, git-tracked source** on `main` after the June 2026 clean-up.
> The old multi-module codebase (ML/RL signals, ensemble, screener, dashboard, live runner)
> lives entirely in `archive/` and is **not** part of the working tree any more.
> Last updated: 2026-06-13

---

## TL;DR

The repo today is a **data layer + download/reporting scripts + strategy docs**. There is
**no strategy implementation yet** — no indicators, no scorer, no backtest engine, no live
runner in the working tree. The next phase builds those from scratch (see `docs/BUILD_PLAN.md`).

```
config/    → settings + universe lists
data/      → SQLite layer, Upstox history backfill, instrument-key resolver, schema
scripts/   → data download, Excel inventory, DB inspection, universe fixer
docs/      → strategy spec + this map + build plan + references
archive/   → ALL old code (reference only; fetch from here when needed)
logs/      → runtime logs
```

---

## Working tree — git-tracked source

### `config/`

| File | Purpose | Status |
|---|---|---|
| `settings.py` | Central config: paths, capital, session times, Upstox dual-credential (sandbox/live + ANALYTICS_TOKEN), instrument keys for ~10 seed symbols. | ⚠️ **Stale** — still contains dead config from the old system (`MODELS_DIR`, `BACKTEST_RESULTS_DIR`, ML gates, `REGIME_WEIGHT_MAP`, old `SIGNAL_WEIGHTS` for vwap_breakout/rsi_momentum/mean_reversion, ensemble/screener/correlation/OpenAlgo/dashboard/Discord). Needs a slim-down pass. Live values still used by data scripts: `DB_PATH`, `ANALYTICS_TOKEN`, `UPSTOX_ACCESS_TOKEN`, `INSTRUMENT_KEYS`, `ROOT_DIR`. |
| `universes.json` | The tradable universe. Keys: `nifty50` (50), `nifty100` (101), `nifty_total` (746), `fo_eligible` (209). | ✅ Clean & current |

### `data/`

| File | Purpose | Status |
|---|---|---|
| `db.py` | **The only DB access layer** (rule: never `import sqlite3` elsewhere). SQLite WAL. Helpers: `init_db`, `write_candles`/`read_candles`, `get_latest_candle_time`, `upsert_ticks`, `log_trade_open`/`log_trade_close`, `get_open_trades`, `get_trade_log`, `upsert_daily_performance`, `get_equity_curve`, `record_backtest_run`, `execute_query`. | ⚠️ `log_trade_close()` imports `analytics.costs.round_trip_cost` — **that module does not exist** (only in `archive/analytics/costs.py`). Will crash on first trade close. |
| `upstox_history.py` | Historical OHLCV backfill via Upstox V3. API: `get_api_client`, `fetch_candles_for_range`, `backfill_symbol` (incremental vs full), `backfill_all`, `backfill_with_yfinance`, `UPSTOX_V3_TIMEFRAME_MAP`. | ✅ Working |
| `instruments.py` | Resolve `symbol → NSE_EQ|ISIN` instrument key from Upstox master (cached weekly). Handles `EQ` + `BE`. Also extracts F&O-eligible underlyings. API: `resolve_instrument_key`, `get_fo_eligible_symbols`, `get_all_equity_symbols`. | ✅ Working |
| `schema.sql` | Canonical DDL. **5 tables:** `ticks`, `minute_candles`, `trade_log`, `daily_performance`, `backtest_runs`. | ✅ Clean & current |
| `nse_eq_keys.json` | Cache: 2,667 `symbol → instrument_key` entries. Regenerated weekly. | ✅ (gitignored: large variant) |
| `nse_fo_symbols.json` | 209–216 F&O-eligible underlying symbols. | ✅ |
| `algo_trading.sqlite` | The live DB (~5.5 GB). 5-min + 1-day OHLCV for 747 symbols + indices/macro. | ✅ (gitignored) |

### `scripts/`

| File | Purpose |
|---|---|
| `download_data.py` | Download 5-min + 1-day OHLCV (Upstox), India VIX + global indices (yfinance), sector indices (Upstox). Uses `ANALYTICS_TOKEN`. Flags: `--tf`, `--vix-only`, `--days`, `--force`. |
| `build_data_excel.py` | Build `data/stock_master.xlsx` — 3 sheets (Stock Master, Summary, Indices & Macro) with market cap (yfinance), turnover/ATR (DB), coverage, source columns, strategy-filter flag. |
| `inspect_db.py` | DB coverage diagnostic across the universe (5-min/1-day bars, missing symbols). |
| `fix_universe_symbols.py` | Check universe symbols against Upstox master; print rename/delist corrections. |

### `docs/`

| File | Purpose | Status |
|---|---|---|
| `STRATEGY_RESEARCH.md` | The strategy spec — Volume Momentum Breakout (Gap-and-Go), 5-dimension framework, scoring, workflow, open questions. | ✅ Current (spec only, not built) |
| `STRATEGIES.md` | Canonical readable reference of every strategy + logic, with a 🔵/🟡/🟢 status per strategy. | ✅ (all 🔵 spec) |
| `EDGE_RESEARCH.md` | Falsifiable alpha hypotheses (H1–H6) + how to test each. | ✅ |
| `BACKTEST_OUTPUT.md` | The 4 result artifacts a run emits (trades.csv, summary, tearsheet, decision journal). | ✅ (spec) |
| `SCRIPTS.md` | Every script: purpose/inputs/outputs/flags + run sequences. | ✅ |
| `CODEBASE_MAP.md` | This file. | ✅ |
| `BUILD_PLAN.md` | Strategy analysis + contracts + code & test roadmap. | ✅ |
| `DATA.md` | Data sources/schema/pipeline. | ❌ **Out of sync** — documents 5 deleted tables, an old `trade_log` shape, and dead modules (`upstox_feed.py`, `nse_data.py`, `signals/news`, `signals/llm`). Needs rewrite to match `schema.sql`. |
| `UPSTOX_API_REFERENCE.md` | Upstox V3 API notes. | ✅ Reference |
| `CODE_AUDIT.md` | Post-mortem of the old codebase — what worked / what failed. | ✅ Reference |
| `COMPONENT_INVENTORY.md` | Inventory of archived components. | ✅ Reference |

---

## The `archive/` directory — reference only

Contains the **complete old codebase** (git-tracked, also preserved on branch
`snapshot/full-codebase`). When the rebuild needs a proven piece, **fetch it from here**
rather than reinventing it. Highest-value items to mine:

| Path in archive | What it is | Reuse value |
|---|---|---|
| `archive/analytics/costs.py` | Indian intraday round-trip cost stack (STT, brokerage, GST, stamp, exchange, SEBI). | **HIGH** — needed by `db.py` now; the strategy thesis depends on it. |
| `archive/features/indicators.py` | Technical indicators (VWAP, EMA, RSI, MACD, ATR, OBV, etc.). | **HIGH** — basis for the new `features/indicators.py`. |
| `archive/backtest/engine.py` | Event-loop backtest engine. | MEDIUM — reference for the new engine. |
| `archive/risk/` `archive/live/` `archive/ensemble/` | Circuit breaker, position sizing, live runner, OpenAlgo client. | MEDIUM — patterns to adapt later. |
| `archive/dashboard/` | FastAPI + React dashboard. | LOW for now (post-validation). |

---

## Known issues to fix (tracked in `docs/BUILD_PLAN.md`)

1. `data/db.py` → missing `analytics.costs` import (latent crash).
2. `config/settings.py` → dead config referencing deleted dirs/old system.
3. `docs/DATA.md` → describes an architecture that no longer exists.
4. No `scripts/validate_data.py` (referenced in DATA.md, never existed).
5. Split-adjustment of Upstox OHLCV unverified (critical for gap-based strategy).
6. Survivorship bias: universe = today's index membership.
