# Backtest Findings — Research Log

> Run-by-run record of what each backtest taught us. Append-only; newest first.
> Each entry: hypothesis → result → interpretation → next. Keeps the research honest
> (no quietly forgetting failed ideas) and prevents re-running dead ends.
> See `docs/EDGE_RESEARCH.md` for the hypotheses and `docs/BACKTEST_OUTPUT.md` for formats.

---

## Investigation 1 — H1 cross-sectional ranking (2026-06-14)

**Setup:** universe = all ~742 liquid equities, 2025-06-01 → 2026-06-01 (224 trading days),
₹20k capital, 1% risk/trade, entry 09:45 IST, 10:30 time-stop, ATR(1.5) stop / ATR(2.0) trail.
Signal = `log1p(rvol_same_window) × return_from_open`, trade top/bottom 1% of the cross-section.

| run | direction | slippage/leg | trades | win% | expectancy | MFE/MAE | verdict |
|---|---|---|---|---|---|---|---|
| `173137b3` | follow momentum | 0.5% | 415 | 18.3% | −0.204R | 0.12 / −0.29 | ❌ no edge |
| `faf97fa0` | **fade (revert)** | 0.5% | 415 | 29.2% | −0.136R | 0.16 / −0.24 | ➖ right sign, cost-killed |
| `7e4154c5` | fade | 0.2% | 415 | 42.4% | −0.044R | 0.20 / −0.20 | ➖ near breakeven |

### What we learned
1. **Following the morning move loses.** The stocks most extended by 09:45 do **not** continue —
   adverse excursion beats favorable on **73.5%** of trades. The move is largely done by 09:45.
   (Confirms the strategy doc's own "don't buy the extended move" warning.)
2. **The extremes mean-REVERT.** Fading (short the top movers / long the bottom) flips win rate
   18%→29%→42% as slippage falls, and at 0.2%/leg the MFE/MAE become symmetric — the fingerprint
   of a real, balanced edge being eaten by costs.
3. **The edge is THIN and execution-bound.** Extrapolated gross expectancy ≈ 0 to +0.05R. This is
   not a money-printer; profitability hinges on execution quality and exit capture, not the signal.
4. **We give the move back.** Avg MFE +0.20R but realised −0.04R: trailing to the 10:30 time-stop
   surrenders the reversion gain instead of banking it. The exit, not the entry, is now the lever.

### Caveats / honesty
- "Return % / max DD = −100%" in early runs is a **metric artifact** (cumulative PnL vs fixed
  capital, no compounding, no ruin-halt). The clean measure is **per-trade expectancy (R)**. TODO:
  track running equity properly in `metrics.py`.
- 0.2%/leg is optimistic-but-plausible for *limit* orders on liquid names (a reversion entry
  *provides* liquidity, often improving the fill). 0.5%/leg is the pessimistic bound. Truth is in
  between and must be validated against real fills before trusting any positive result.
- All results are **in-sample** so far. Nothing here is validated out-of-sample yet.

### Next experiments (in priority order — pick deliberately, don't fit noise)
1. **Exit capture** (highest-value, directly motivated by MFE): replace trail-to-time-stop with a
   profit target near the reversion's typical size + a tighter time window. Banking +0.2R instead
   of giving it back likely flips the edge positive at realistic cost. *Risk: in-sample exit tuning
   — must confirm out-of-sample.*
2. **Signal conditioning:** fade only the MOST stretched (high RVOL **and** large distance from
   VWAP) — the names that revert hardest — to raise edge-per-trade.
3. **If still marginal:** this horizon is a cost trap; move to **H2** (longer, to-close hold) or
   earlier entry, per the EDGE_RESEARCH queue.

**Status:** H1 = 🟡 in backtest. Reversion sign confirmed; edge thin; not yet tradable. Do **not**
proceed toward paper/live until a variant clears costs **out-of-sample** and beats the negative
controls (EDGE_RESEARCH §6).
