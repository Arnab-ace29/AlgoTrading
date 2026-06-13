# Backtest Output Formats

> Exactly what a backtest run produces, so results are readable and comparable. Defined **before**
> the engine is built (the engine is written to emit these). Implemented in Phase 2 of BUILD_PLAN.
> Every run is keyed by a short `run_id` (e.g. `a1b2c3d4`) and lands in `backtest/results/<run_id>/`.
> Last updated: 2026-06-14

A single run emits **four artifacts**:

```
backtest/results/<run_id>/
  trades.csv        # Format 1 — one row per executed trade (the detailed log you asked for)
  summary.md        # Format 2 — human-readable run summary
  summary.json      # Format 2 — same numbers, machine-readable (for comparing runs)
  tearsheet.html    # Format 3a — visual: equity curve, drawdown, distributions
  journal/<date>.md # Format 3b — per-day decision journal (taken + skipped + why)
```
Plus one row in the `backtest_runs` table so the run is discoverable later.

---

## Format 1 — `trades.csv`  (detailed per-trade log)

One row **per executed trade**, per stock, per date. Columns (in order):

| Column | Meaning |
|---|---|
| `run_id` | which run this trade belongs to |
| `date` | trade date (IST) |
| `symbol` | stock |
| `sector` / `tier` | sector index + Universe Tier (A/B) |
| `strategy` | strategy/overlay that fired (e.g. `S1_momentum`, `S1+H1_xsec`) |
| `direction` | LONG / SHORT |
| `score` | signed composite score at entry |
| `conviction` | risk multiplier used (0.5 / 1.0 / 1.5) |
| `dim_trend` `dim_momentum` `dim_volume` `dim_structure` `dim_context` | the 5-dimension breakdown (why it scored) |
| `entry_time` / `entry_price` | fill time + price (after slippage) |
| `stop_price` | initial stop |
| `target_price` | initial target (or `TRAIL` if trailing-only) |
| `exit_time` / `exit_price` | exit fill |
| `exit_reason` | TARGET / STOP / TRAIL / TIME / REVERSAL |
| `qty` / `exposure` | shares + ₹ notional |
| `risk` | ₹ put at risk at entry (= R) |
| `gross_pnl` | (exit − entry) × qty × side |
| `cost` | round-trip transaction cost (analytics.costs) |
| `net_pnl` | gross − cost |
| `pnl_pct` | net return on exposure |
| `R_multiple` | net_pnl ÷ risk (the key number — expectancy is mean of this) |
| **`mfe_pct` / `mfe_R`** | **potential UPSIDE** — best unrealised gain reached during the trade (how much it *could* have made) |
| **`mae_pct` / `mae_R`** | **potential DOWNSIDE** — worst unrealised drawdown during the trade (how close it came to the stop) |
| `hold_minutes` | time in trade |
| `nifty_ret` / `vix` | market context that day (regime tagging) |

**Why MFE/MAE matter:** they tell you whether your stops/targets are well-placed. High `mfe_R`
on trades you exited early → you're leaving money on the table (loosen the trail). Low `mae_R` on
winners → your stop is wider than it needs to be (tighten it). This is how the exits get tuned
(EDGE_RESEARCH §5).

Example row (illustrative):
```
run_id,date,symbol,sector,tier,strategy,direction,score,conviction,...,entry_price,stop_price,exit_price,exit_reason,qty,risk,net_pnl,R_multiple,mfe_R,mae_R,hold_minutes
a1b2c3d4,2025-03-14,TATAELXSI,NIFTYIT,B,S1_momentum,LONG,11,1.5,...,6420.0,6360.0,6585.0,TRAIL,5,300,792,2.64,3.1,-0.4,38
```

---

## Format 2 — `summary.md` (+ `summary.json`)

The run at a glance, then the breakdowns that actually drive decisions.

**Header**
- run_id, run time, date range, universe + tier, strategy + overlays, key params
- assumptions: fill model, slippage, cost model, starting capital, base_risk_pct

**Headline metrics**
- trades, win rate, avg win / avg loss, **expectancy (R)**, profit factor
- net PnL, return %, **annualised return**, **Sharpe**, **Sortino**, **max drawdown**, exposure
- **vs Buy-and-Hold Nifty** over the same window (must beat it after costs)

**Breakdowns** (each as a small table)
- by **direction** (long vs short)
- by **tier** (A vs B) and by **sector**
- by **month** and by **day-of-week** (tests the "Friday outperforms" claim)
- by **score bucket** (win rate + expectancy per conviction tier → feeds fractional Kelly later)
- by **exit reason** (how much PnL comes from targets vs trails vs reversals)

**Validation block** (Phase 3)
- in-sample vs **out-of-sample** metrics side by side
- negative-control comparison (random / shuffled-label) — edge must beat both
- parameter-sensitivity note

**Best / worst** — top 5 and bottom 5 trades by R.

`summary.json` carries the same numbers as a flat dict so runs can be diffed and ranked
programmatically (e.g. during the Phase 3 sweep).

---

## Format 3 — additional views (my proposals)

You asked for one more; I'm giving **two**, because they answer different questions. Recommend both.

### 3a. `tearsheet.html` — the visual summary  *(primary recommendation)*
A single self-contained HTML page:
- **Equity curve** (strategy vs Nifty benchmark)
- **Underwater / drawdown** plot (how deep, how long — the survival view)
- **Monthly-returns heatmap** (seasonality, lumpiness — momentum is never smooth)
- **R-multiple histogram** (shape of the edge; fat right tail = healthy momentum)
- **MFE vs MAE scatter** (are stops/targets placed right?)
- header KPIs (Sharpe, win rate, expectancy, max DD)

One glance tells you if a config is worth pursuing — far faster than reading tables.

### 3b. `journal/<date>.md` — the daily decision journal  *(highest diagnostic value)*
For each trading day, **what the scanner did**:
- the day's **ranked candidates** (top N by score) with their dimension breakdown
- which were **TAKEN** (→ link to the trade) and which were **SKIPPED** and the exact reason
  (which filter/disqualifier blocked it)
- **regret analysis**: how the skipped high-scorers *would* have done

This directly answers "for each stock I picked to trade that date" **and** its mirror — the ones
you *didn't* pick and should have (or dodged correctly). Since your edge lives in *selecting the
right 1–3 of 756* (EDGE_RESEARCH H1), this journal is where you'll actually debug and improve the
scanner. It's the most useful artifact for iterating the strategy.

---

## Conventions
- Money in ₹; returns in %; risk/PnL also in **R-multiples** (the comparable unit).
- All times IST. All trades **net of costs** — a gross-positive, cost-negative trade is a loss.
- Every run is reproducible: `summary.json` records the exact params + git commit, so any
  result can be regenerated.
