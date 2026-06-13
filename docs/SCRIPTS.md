# Scripts Reference & Run Sequences

> Every script in `scripts/`: what it does, inputs, outputs, key flags, and the **order to run
> them** for common workflows (fresh setup, daily update, adding stocks, monthly maintenance).
> Last updated: 2026-06-14

---

## The data flow at a glance

```
Upstox NSE master ──► data/nse_eq_keys.json ──┐
                      data/nse_fo_symbols.json │
                                               ▼
config/universes.json ──► download_data.py ──► data/algo_trading.sqlite ──► build_data_excel.py ──► data/stock_master.xlsx
   (the universe)            (OHLCV + VIX)        (the 5-table DB)              (+ yfinance caps)        (tracking workbook)
```

**Source of truth:** `config/universes.json` defines the universe. **All backtesting and live
trading draw their symbols from here.** The SQLite DB holds the price data; the Excel is a
human-readable inventory/health dashboard built from DB + yfinance.

---

## Scripts

### `download_data.py` — fetch / update OHLCV + VIX + indices

| | |
|---|---|
| **Purpose** | Populate/refresh `minute_candles` with 5-min + 1-day OHLCV (Upstox), India VIX + global indices (yfinance), and NSE sector indices (Upstox). |
| **Reads** | `config/universes.json`, `data/nse_eq_keys.json`, `ANALYTICS_TOKEN` from `.env` |
| **Writes** | `data/algo_trading.sqlite` (`minute_candles`) |
| **Token** | `ANALYTICS_TOKEN` (1-yr read-only — safe for unattended runs) |
| **Runtime** | Full backfill: **hours** (5-min × 756). Daily `--update`: ~10–15 min. |

**Modes / flags**
- *(no flag)* — **backfill**: fetch only symbols below threshold (5-min < 500 bars, 1-day < 450)
  + auto-detected partial 5-min history. Use after **adding** symbols.
- `--update` — **daily top-up**: incrementally bring **ALL** symbols up to the latest trading
  day. Use for routine refresh.
- `--force` — re-fetch **full** history for everything (rarely needed; slow).
- `--tf {5min,1day,both}` — limit to one timeframe (default `both`).
- `--vix-only` — only VIX + indices (fast).
- `--days N` — lookback window for full backfills (default 730).

### `build_data_excel.py` — build the tracking workbook

| | |
|---|---|
| **Purpose** | Build `data/stock_master.xlsx` — per-symbol inventory: market cap, turnover, ATR%, tier, index membership, data coverage, **freshness/staleness**, strategy-filter flag. 3 sheets: Stock Master, Summary, Indices & Macro. |
| **Reads** | `data/algo_trading.sqlite`, `config/universes.json`, `data/yfinance_info_cache.json` (auto), yfinance (only for symbols not in cache) |
| **Writes** | `data/stock_master.xlsx`, `data/yfinance_info_cache.json` |
| **Runtime** | ~6 min (the turnover/ATR SQL over ~24M rows). yfinance is cached, so adding a few names is near-instant. |

**Flags**
- *(no flag)* — uses the yfinance cache (7-day TTL); fetches only new symbols.
- `--refresh-yf` — force a full yfinance re-fetch (market caps move; do monthly-ish).
- `--no-yfinance` — skip caps entirely (fast, but market cap = 0 → strategy filter collapses).
- `--output PATH` — write somewhere other than `data/stock_master.xlsx`.

### `inspect_db.py` — coverage diagnostic

| | |
|---|---|
| **Purpose** | Print DB coverage across the universe: 5-min/1-day bar counts, date ranges, missing symbols, Nifty-100 bar distribution, index/macro presence. Read-only sanity check. |
| **Reads** | `data/algo_trading.sqlite`, `config/universes.json` |
| **Writes** | nothing (stdout) |

### `fix_universe_symbols.py` — catch renames / delistings

| | |
|---|---|
| **Purpose** | Check every universe symbol against the live Upstox NSE master; report renamed/delisted tickers and a suggested correction map (e.g. LTIM→LTM, ZOMATO→ETERNAL). |
| **Reads** | `config/universes.json`, Upstox NSE master |
| **Writes** | prints corrections (apply by editing `universes.json`) |

### `find_missing_caps.py` — find large/mid caps absent from the universe

| | |
|---|---|
| **Purpose** | Fetch market cap (yfinance) for every NSE symbol **not** in the universe; report anything ≥ ₹5,000 Cr so liquid omissions (incl. recent IPOs) can be added. |
| **Reads** | `config/universes.json`, `data/nse_eq_keys.json`, yfinance |
| **Writes** | `data/missing_caps.csv` |
| **Runtime** | ~13 min (sweeps ~1,900 names) |

> Note: high market cap ≠ tradable. Always re-check **turnover ≥ ₹50 Cr/day** before adding —
> most big-cap omissions are illiquid (low free float) and correctly excluded.

---

## Run sequences

### A. From scratch (empty DB / new machine)

```bash
# 0. Ensure .env has ANALYTICS_TOKEN (+ Upstox creds)
# 1. Full historical backfill — 5min + 1day + VIX + sector indices  (HOURS)
python scripts/download_data.py
# 2. Build the tracking Excel (fetches + caches yfinance market caps)
python scripts/build_data_excel.py
# 3. Verify coverage
python scripts/inspect_db.py
```

### B. Daily / periodic data refresh  ◄ the common one

```bash
# 1. Top up ALL symbols to the latest trading day (incremental, ~10-15 min)
python scripts/download_data.py --update
# 2. Rebuild the Excel (yfinance cached → fast; refreshes freshness flags)
python scripts/build_data_excel.py
```

### C. Adding new stocks to the universe

```bash
# 1. (optional) find liquid omissions
python scripts/find_missing_caps.py
# 2. Edit config/universes.json — add the new symbols to "nifty_total"
# 3. Backfill ONLY the new names (auto-detected as below-threshold)
python scripts/download_data.py
# 4. Rebuild Excel (only the new symbols hit yfinance)
python scripts/build_data_excel.py
```

### D. Monthly universe maintenance

```bash
# 1. Catch renamed/delisted tickers
python scripts/fix_universe_symbols.py
# 2. Catch new large/mid-cap listings (then turnover-check before adding)
python scripts/find_missing_caps.py
# 3. Edit universes.json as needed, then:
python scripts/download_data.py            # backfill any additions
python scripts/build_data_excel.py --refresh-yf   # refresh market caps too
```

---

## Notes

- **Outputs are gitignored**: `algo_trading.sqlite`, `stock_master.xlsx`, `yfinance_info_cache.json`,
  `missing_caps*.csv`. Only code + `universes.json` are versioned.
- **Token:** use `ANALYTICS_TOKEN` for all data jobs — it's read-only and lasts a year, so
  unattended runs never hit the daily-expiry of the trading token.
- **Excel freshness flags** (`Data Current?`, `Days Stale`) tell you when to run sequence B.
  Red `Data Current? = N` means that symbol's 1-day data is > 1 day behind the latest in the DB.
