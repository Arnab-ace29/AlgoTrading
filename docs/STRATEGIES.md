# Strategies — What the Bot Trades (Logic Reference)

> The canonical, readable description of every strategy the system runs, with exact logic.
> **Status: SPEC.** No strategy is coded yet — this is the contract for Phase 1 of
> `docs/BUILD_PLAN.md`. This doc is updated as each strategy is implemented and validated;
> a strategy only graduates from "spec" → "live-candidate" after it passes the Phase 3 gate
> in `docs/EDGE_RESEARCH.md` (OOS edge, stable sign, beats negative controls).

Legend: 🔵 spec (not coded) · 🟡 coded, in backtest · 🟢 validated (OOS-passed) · ⚪ retired

---

## S1 — Volume Momentum Breakout (Gap-and-Go)   🔵

The core strategy. One **signed scorer** produces both long and short signals.

### Thesis
Under semi-strong efficiency, edge comes from *gradual incorporation*: a catalyst-driven move
continues over 30–60 min because institutions work large orders over time. We detect the move
early (volume + structure) and ride the continuation, exiting before it exhausts.

### Universe & regime gate (run once, ~9:20 AM)
- Universe: `config/universes.json` → Tier A (Nifty 100) + Tier B (liquid mid/large that pass
  the filter). Hard filter: market cap ≥ ₹1,000 Cr **and** turnover ≥ ₹50 Cr/day.
- Daily go/no-go: trade only if VIX regime is not "panic" and Nifty isn't gapping down hard.
  (Phase 3 H3 decides the exact VIX rule — momentum in low-VIX, stand down / reversion in high.)

### The signed score (computed per symbol at the entry bar)
Five dimensions, each measuring something different; the **sum is signed** (+ = long, − = short).
Long uses the bullish side of each test, short the mirror image.

| Dim | Signal | Long condition (short = mirror) | Pts |
|---|---|---|---|
| **Trend** | Session VWAP | price > VWAP (institutions in profit, tailwind) | +1 |
| | EMA 9/21 (5-min) | 9 > 21, both sloping up | +1 |
| | Prior-day high | price > PDH (no overhead supply) | +1 |
| | Gap | gap-up > 2% | +1 |
| **Momentum** | RSI(14) | 55–70 (+1), 70–75 (+1 more); **> 78 → disqualify** | +1/+2 |
| | MACD histogram | positive **and rising** (acceleration) | +1 |
| **Volume** | RVOL (same-time-window) | > 3× (+1), > 5× (+1 more) | +1/+2 |
| | OBV | making new intraday highs with price (no divergence) | +1 |
| | Gap quality | clean 0.5–3% gap | +1 |
| **Structure** | ORB | breaks the opening-range high with volume (the trigger) | +1 |
| | First-candle quality | close in top 30% of range, small wick | tiebreak |
| **Context** | Nifty | positive and above its own VWAP | +1 |
| | Sector index | the stock's sector up > 0.5% (needs `sector_map.json`) | +1 |
| | VIX | < regime threshold | +1 |

**Direction:** `score ≥ +entry_threshold → LONG`; `score ≤ −entry_threshold → SHORT`; else FLAT.
**Must-haves (else skip):** RVOL > 2× and price on the correct side of VWAP.
**Negative disqualifiers (override score):** RSI > 78, gap > 5%, OBV diverging, volume fading
after the first candle, Nifty against you > 0.5%, VIX spike > 10% d/d, recent upper circuit,
results/corporate action today/tomorrow, RVOL driven by a single bulk deal.

### Entry
- Trigger: price breaks the ORB level (high for long, low for short) with a volume surge.
- Order: limit, 0.1–0.2% beyond the ORB level. If unfilled in the bar, skip (don't chase).
- Backtest fill model: fill only if the next bar trades through the limit; assume worst-case
  in-bar fill + slippage (0.5%+ on fast names).

### Exit (whichever first)
- **Stop:** ATR-based (≈ 75th-pct of winners' MAE from data — see EDGE_RESEARCH §5), padded for
  gap-through. No fixed %.
- **Target:** none fixed — **trail** by ATR/structure (momentum payoff is fat-tailed; a fixed
  target caps the winners that carry the edge).
- **Time stop:** hard exit ~10:30 AM (validated by `E[return | held t]` in Phase 3).
- **Reversal:** first opposite-color bar on above-average volume; or momentum fade
  (RSI back through 60 / MACD-hist shrinking 2 bars).

### Sizing (risk engine — see BUILD_PLAN Part 2A)
Conviction (from |score|) sets risk, stop distance sets share count, budget caps downside:
`risk_budget = capital × base_risk_pct × conviction` (e.g. ₹20k × 1% × {0.5/1.0/1.5});
`qty = risk_budget / (entry − stop − slippage_pad)`; capped by exposure & the daily-loss rail.

---

## Edge-feature overlays (added to S1 as they pass validation)

These come from `docs/EDGE_RESEARCH.md`. Each is a *feature/condition* layered onto S1's score,
turned on only after it earns its place out-of-sample.

| ID | Overlay | Effect on S1 | Status |
|---|---|---|---|
| **H1** | Cross-sectional extreme ranking | Trade only the top/bottom percentile of the 756-name rank, not absolute thresholds | 🔵 |
| **H2** | Intraday momentum anomaly | Condition entry on the 9:15–9:45 signed VWAP return predicting rest-of-day | 🔵 |
| **H3** | VIX regime switch | Selects S1 (low VIX) vs S2 reversion (high VIX); also scales size inversely to VIX | 🔵 |
| **H4** | Beta-decomposed gap | Rank on the *idiosyncratic* gap (strip out market-beta gap) | 🔵 |
| **H5** | Sector relative strength | Long leaders / short laggards; lifts the rank | 🔵 |

---

## S2 — Mean-Reversion (high-VIX regime)   🔵 (planned, after S1 validates)

Symmetric counterpart for choppy / high-volatility days, when momentum crashes and panic
overshoots revert. **Not built until S1 is proven** — one validated engine at a time
(BUILD_PLAN sequencing). Logic TBD from H3 results.

---

## How a strategy graduates

```
🔵 spec  →  code in Phase 1  →  🟡 backtest (Phase 3)  →  pass gate?  →  🟢 validated  →  paper  →  live
                                                         │
                                                         └─ fail → document why, retire ⚪ or iterate
```
A strategy is never sized with real money before 🟢 (OOS Sharpe > 1.0, beats Nifty after costs,
stable across folds) **and** 60+ paper days matching backtest expectancy.
