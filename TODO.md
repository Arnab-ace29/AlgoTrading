# AlgoTrading — Task Tracker

> **Key:** `[U]` = User request · `[A]` = Assistant recommendation · `✅` = Done · `🔄` = In progress · `⏳` = Pending

---

## Session: June 2026

### Codebase Audit & Archive

| # | Task | Who | Status | Notes |
|---|---|---|---|---|
| 1 | Audit old codebase — what worked / what didn't | U | ✅ | `docs/CODE_AUDIT.md` |
| 2 | Create component inventory for archived code | U | ✅ | `docs/COMPONENT_INVENTORY.md` |
| 3 | Move ALL old code to `archive/`, clean slate `main` branch | U | ✅ | Entire old codebase in `archive/`, branch `snapshot/full-codebase` preserved |
| 4 | Move old architecture docs (ARCHITECTURE, DASHBOARD, SIGNALS, ROADMAP, etc.) to `archive/docs/` | U | ✅ | Keeping: STRATEGY_RESEARCH, DATA, UPSTOX_API_REFERENCE, CODE_AUDIT, COMPONENT_INVENTORY |
| 5 | Push to GitHub with separate branch for old code | U | ✅ | `main` = clean slate, `snapshot/full-codebase` = full old code |

### Strategy Research

| # | Task | Who | Status | Notes |
|---|---|---|---|---|
| 6 | Research Options vs Futures vs Intraday profitability | U | ✅ | Conclusion: options selling > futures > low-freq equity intraday > options buying |
| 7 | Determine viable strategy for ₹20k capital | A | ✅ | Only equity intraday cash segment viable at ₹20k due to SEBI 2025-26 F&O minimums |
| 8 | Define instrument universe (Nifty 50 too slow → bigger universe) | U | ✅ | Nifty 100 primary + liquid Midcap 150; filters: ≥₹1000cr mkt cap, ≥₹50cr daily vol |
| 9 | Design strategy: volume momentum breakout (Gap-and-Go) | U | ✅ | Full 5-dimension framework + scoring in `docs/STRATEGY_RESEARCH.md` |
| 10 | Document strategy spec | U | ✅ | `docs/STRATEGY_RESEARCH.md` — 413 lines, complete |

### Data Infrastructure

| # | Task | Who | Status | Notes |
|---|---|---|---|---|
| 11 | Data audit — what exists, what's needed, how much to scrape | U | ✅ | 23.5M rows of real 5-min OHLCV for 740 symbols (2 years, source: Upstox). Missing: daily candles, VIX |
| 12 | Restore data infrastructure from archive (`db.py`, `upstox_history.py`, `instruments.py`, `settings.py`) | A | ✅ | Restored to `data/` and `config/` |
| 13 | Verify Upstox ANALYTICS_TOKEN validity | A | ✅ | Valid until ~June 2027. Used for all historical data downloads |
| 14 | Verify India VIX from yfinance (`^INDIAVIX`) | A | ✅ | Works. Returns daily data. 722 rows (2 years) in DB |
| 15 | Fix universe symbols: LTIM→LTM, ZOMATO→ETERNAL, TATAMOTORS→TMCV/TMPV | A | ✅ | `fix_universe_symbols.py`; `config/universes.json` patched; all new symbols already have full 2yr data |
| 16 | Fix `instruments.py` to resolve BE-type (trade-for-trade) stocks | A | ✅ | Line 70: added `BE` to type filter; cache regenerated with 2,667 symbols |
| 17 | Remove DUMMYALCAR placeholder from universe | A | ✅ | Removed from `config/universes.json`; universe now 747 symbols |
| 18 | Download 1-day OHLCV for all ~750 symbols | A | ✅ | 752 symbols, 332,815 rows; ~495 daily candles each (2 years) |
| 19 | Download India VIX daily (2 years) and store in DB | A | ✅ | INDIAVIX: 722 rows, 2023-06-30 → 2026-06-12 |
| 20 | Download sector indices (Nifty Bank, IT, FMCG, Pharma, Auto, Metal) | A | ✅ | Done via `download_data.py` Step 4 (NIFTYINFRA key invalid — all others OK) |
| 21 | Download 5-min + 1-day data for 8 missing BE-type symbols | A | ✅ | ATLANTAELE (11k bars), DBREALTY, JAIBALAJI, KRN, PFOCUS, QPOWER, STLTECH (~34k bars each), UTLSOLAR (137 days). All 747 symbols now have 5min data |
| 22 | Build master stock data inventory Excel | U | ✅ | `data/stock_master.xlsx` — 747 symbols, real market caps via yfinance, 413 strategy filter candidates |

### Backtest & Validation (Upcoming)

| # | Task | Who | Status | Notes |
|---|---|---|---|---|
| 23 | Backtest the 5-dimension momentum breakout strategy on 2 years of real data | U | ⏳ | Needs data download to complete first |
| 24 | Validate: optimal ORB window (9:15-9:30 vs 9:15-9:45) | A | ⏳ | Listed in STRATEGY_RESEARCH.md open questions |
| 25 | Validate: best RVOL threshold (2× vs 2.5× vs 3× avg) | A | ⏳ | |
| 26 | Validate: VIX hard-pass filter net effect on win rate | A | ⏳ | |
| 27 | Paper trade for 60+ days once backtest shows Sharpe > 1.0 | U | ⏳ | |
| 28 | Go live at ₹20k after paper trading validates strategy | U | ⏳ | |

---

## Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| June 2026 | Target 3-7% momentum moves, not 0.5-1% scalps | Round-trip costs ~16-18 bps eat 18%+ of a 1% move but only 3-6% of a 5% move |
| June 2026 | Nifty 100 + liquid Midcap 150 as universe (not Nifty 50) | Nifty 50 moves < 1-2% intraday; need stocks that can move 3-7% in 60 min |
| June 2026 | ≥₹1,000 cr market cap + ≥₹50 cr daily turnover filters | Prevents illiquid small caps with wide bid-ask spreads |
| June 2026 | ANALYTICS_TOKEN for all data backfill jobs | 1-year lifetime, no daily re-auth needed; LIVE_ACCESS_TOKEN expires each midnight IST |
| June 2026 | India VIX via yfinance (`^INDIAVIX`) not Upstox | Simpler, no instrument key needed, works for daily data |
| June 2026 | SQLite WAL mode as primary data store | Supports concurrent readers + writer without locking (live runner + dashboard) |
| June 2026 | Include BE (trade-for-trade) stocks in universe | They have valid OHLCV from Upstox; strategy filter (≥₹50cr turnover) will exclude illiquid ones |

---

## How to Run (Quick Reference)

```bash
# Download all missing data (5min + 1day + VIX + sector indices)
python scripts/download_data.py

# Only daily candles (fast, ~10 min)
python scripts/download_data.py --tf 1day

# Only VIX + global indices
python scripts/download_data.py --vix-only

# Build master Excel (needs data + yfinance, ~10 min for mkt cap fetch)
python scripts/build_data_excel.py

# Build Excel fast (no yfinance market cap, uses DB data only)
python scripts/build_data_excel.py --no-yfinance

# Inspect DB contents
python scripts/inspect_db.py
```
