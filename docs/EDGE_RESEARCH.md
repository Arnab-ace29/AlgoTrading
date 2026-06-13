# Edge Research — Falsifiable Hypotheses & How to Test Them

> Where the alpha actually comes from, written as **experiments you can run**, not opinions.
> Companion to `docs/STRATEGY_RESEARCH.md` (the strategy) and `docs/BUILD_PLAN.md` (the build).
> Last updated: 2026-06-13

---

## 0. The governing principle

We assume **semi-strong efficiency**: all *public information* is already in the price.
That single assumption tells us where edge **cannot** live and where it **can**:

- ❌ **Cannot** live in: predicting news, "undervalued" stocks, forecasting events.
- ✅ **Can** live in three EMH-surviving sources:
  1. **Gradual incorporation** — big orders execute over minutes-to-hours, so price *continues*
     after a catalyst (the intraday-momentum anomaly).
  2. **Non-informational flow** — index rebalancing, options-hedging, ETF create/redeem,
     margin liquidation, expiry pinning. Forced participants move price away from fair value.
  3. **Risk premia** — getting *paid* to provide liquidity / bear risk others won't.

> **Definition of edge:** a conditional expectation `E[ forward_return | features ]` that stays
> **non-zero after costs**, with a **stable sign out-of-sample**. We *measure* it; we don't
> *invent* it. Running this measurement systematically across 750 names **is** the edge.

---

## 1. The measurement protocol (identical for every hypothesis)

Every hypothesis below is tested the same way, so results are comparable and honest:

1. **Define the event** precisely (e.g. "9:45 AM, RVOL>2, price>VWAP").
2. **Define the forward return** — the thing we're predicting (e.g. 9:45→close, or next 30 min),
   measured **net of a pessimistic cost+slippage model**.
3. **Split time, not trades.** Train fold = older 60–70%; test (OOS) fold = most recent 30–40%.
   Walk-forward in rolling windows. **Never fit and report on the same data.**
4. **Compute the conditional distribution** of forward return given the feature(s) — not just the
   mean. We care about mean, hit-rate, *and* the tails.
5. **Score with the right metric** (see §2) on the **OOS** fold.
6. **Pass criterion:** edge is non-zero after costs, **same sign in every fold**, and survives the
   negative controls in §6. If it only works in-sample, it is over-fit — discard it.

---

## 2. Metrics glossary (so "it works" means something)

| Metric | What it measures | Use for |
|---|---|---|
| **Rank-IC** (Spearman) | Correlation between a *ranking signal today* and *forward return*, across the cross-section, each day. | Cross-sectional ranking edges (H1, H5). A daily mean IC of even **0.03–0.05 that is stable** is a real, tradable edge. |
| **Expectancy (R)** | `mean(return) / risk_per_trade`, in R-multiples. | Any entry signal. Must be **> costs** and **> 0** OOS. |
| **Hit rate + payoff** | Win % and avg-win/avg-loss. | Sanity; feeds Kelly later. |
| **MAE / MFE** | Max Adverse / Favorable Excursion per trade. | **Deriving stops and targets** (§5). |
| **Sharpe / Sortino (daily)** | Risk-adjusted return of the *strategy equity curve*. | Portfolio-level go/no-go (gate: OOS Sharpe > 1.0). |
| **Sign stability** | Does the edge keep the same sign across every walk-forward fold? | The anti-overfit test. More important than the magnitude. |

---

## 3. The edge hypotheses (ranked by EV ÷ effort)

### TIER 1 — backtestable on current data (5-min OHLCV, 2yr, 750 names), high EV

---

#### H1 — Cross-sectional extreme ranking *(highest leverage, lowest effort)*

**Thesis.** On any day, the *tail* of a 750-wide cross-section continues hardest. Instead of
absolute thresholds ("RVOL>3"), **rank all 750 names every bar** by a signed momentum-volume
score and trade only the top/bottom percentile.

**Why it survives EMH.** Gradual incorporation is *strongest* for the names with the most
abnormal flow — and "most abnormal" is a *relative* statement, best captured by cross-sectional
rank, which is also self-normalizing across volatility regimes.

**Signal.** `rank_score = zscore(RVOL_same_window) × sign(close − VWAP) × (return_from_open)`.
Rank across the universe each 5-min bar.

**Test.** Daily **Rank-IC** between `rank_score` at 9:45 and the 9:45→close return, on the OOS fold.
Also: decile portfolios — does the top decile's forward return monotonically beat the bottom
decile, net of cost?

**Pass.** OOS mean Rank-IC ≥ ~0.03 with the **same sign every fold**; top-minus-bottom decile
spread positive after costs.

**Data.** Have it. **Effort:** Low.

---

#### H2 — The intraday momentum anomaly, made explicit

**Thesis.** The signed, volume-weighted return of the **first 30 minutes** predicts the
**rest-of-day** return (Gao, Han, Li & Zhou 2018 — robust across decades and markets). Your
gap-and-go is implicitly this; make it the explicit thesis and condition it.

**Why it survives EMH.** Institutional execution is *scheduled* (VWAP/TWAP algos run all day), so
morning order-flow mechanically predicts afternoon order-flow. Not information — execution structure.

**Signal.** `morning_signal = VWAP-weighted return over 9:15–9:45`, conditioned on gap size, RVOL,
and VIX regime.

**Test.** Regress `(9:45→close return)` on `morning_signal` OOS; report slope, t-stat, and
expectancy of a long-if-positive / short-if-negative rule **net of cost**. Condition: does the
effect strengthen with RVOL? weaken at high VIX?

**Pass.** Positive, significant slope OOS; cost-adjusted expectancy > 0 with stable sign.

**Data.** Have it. **Effort:** Low.

---

#### H3 — VIX as a regime *switch*, not a filter

**Thesis.** Momentum **crashes** in high volatility; mean-reversion **pays** in high volatility
(panic overshoots revert). So VIX should *select the strategy*, not just gate it.

**Why it survives EMH.** Volatility proxies the ratio of forced/liquidity-driven flow to
informed flow. High vol = more panic/forced selling = overshoot = reversion premium.

**Signal.** `VIX_percentile` vs trailing 1yr → low decile = momentum mode; high decile = reversion
mode. Also size **inversely** to VIX.

**Test.** Split all H1/H2 results by VIX percentile bucket. Compute expectancy of *momentum* and of
*reversion* in each bucket, OOS. Confirm the crossover (momentum wins low-VIX, reversion wins high-VIX).

**Pass.** Clear, monotonic regime dependence that holds OOS; a VIX-switched blend beats either
strategy alone on Sharpe.

**Data.** Have it (INDIAVIX daily, 2yr). **Effort:** Medium.

---

### TIER 2 — backtestable now, medium EV

---

#### H4 — Beta-decomposed gaps (idiosyncratic vs market)

**Thesis.** A +3% gap on a flat-market day (idiosyncratic) continues; a +3% gap when the whole
market gapped +2.5% (beta) does not. Trade the **idiosyncratic** residual.

**Why it survives EMH.** Idiosyncratic gaps reflect *single-stock* forced flow still being worked;
market-beta gaps are already arbitraged across the index.

**Signal.** `idio_gap = stock_gap − beta × market_gap`, where `market_gap` from Nifty / SP500 /
NASDAQ overnight and `beta` from trailing daily returns.

**Test.** Compare forward-return expectancy of high-`idio_gap` vs high-raw-gap names OOS.

**Pass.** Idiosyncratic component has higher, more stable cost-adjusted expectancy than raw gap.

**Data.** Have it (indices + 1-day history for beta). **Effort:** Medium.

---

#### H5 — Sector relative strength

**Thesis.** Long stocks in the day's **leading** sector, short the **lagging** — sector tailwind
sustains single-stock moves.

**Why it survives EMH.** Sector rotation is a slow institutional flow (funds rebalance sector
weights over days); riding it is harvesting that flow.

**Signal.** Rank the 8 sector indices by intraday + trailing-5d return; tag each stock with its
sector's rank (needs `config/sector_map.json`).

**Test.** Add `sector_rank` as a conditioning variable to H1; does it lift Rank-IC? Decile spread?

**Pass.** Conditioning on sector strength improves OOS expectancy vs the unconditioned signal.

**Data.** Have it (sector indices in DB + Excel). **Effort:** Medium.

---

### TIER 3 — highest ceiling, but NOT yet (data gap)

---

#### H6 — Order-flow imbalance (OFI)

**Thesis.** Net aggressive-buy vs aggressive-sell volume (who crosses the spread) is among the
most robust short-horizon predictors in microstructure — and is pure EMH-consistent *flow*.

**Blocker.** Our historical store is **5-min OHLCV; no archived ticks.** OFI needs trade-level
data. **Action now:** start the live tick collector writing to the `ticks` table so we accumulate
history; revisit OFI once we have months of ticks. Do **not** block Tier 1–2 on this.

**Effort:** High + requires forward data collection.

---

## 4. Execution-level edges (not signals — but they ARE edge)

These are why disciplined retail beats the 70% who lose. They compound with H1–H5:

- **Cost minimization** — limit-order entries, cap order size to a fraction of bar volume, model
  slippage honestly (0.5%+ on fast names). Every bp saved is a bp of pure alpha.
- **Risk-based sizing** — fixed fractional risk per trade (see BUILD_PLAN Risk Engine). Survival
  *is* edge: you can't compound an edge if a drawdown ends you.
- **Daily loss cap** — turns a 6-loser streak from −15% into −3%. Pure expectancy protection.
- **Empirical exits** (§5) — most traders cap winners with round-number targets and bleed the
  fat tail momentum lives on.

---

## 5. Deriving target & stop from data (MAE / MFE) — not picking them

Round-number stops/targets are what the losing crowd uses. Derive them:

1. For every historical signal, record **MAE** (worst drawdown before exit) and **MFE** (best
   gain before exit), in ATR units.
2. **Stop** = just beyond the **75th percentile of *winners'* MAE.** Tight enough to cut losers,
   loose enough not to shake out trades that would have won. (Often ~1.2–1.8×ATR — let data decide.)
3. **Target** — plot the **MFE distribution.** Momentum payoff is fat-tailed; a fixed target caps
   the right tail that *is* the edge. Expect the data to say: **trail, don't fix a target.** Use
   ATR/structure trail + a hard **time-stop**.
4. **Time-stop** — compute `E[return | held t minutes]`; exit where it flattens/rolls over. This
   *tests* the 10:30 assumption (open question #8) instead of assuming it.
5. Express everything in **R-multiples** (stop = 1R). At ~45% hit rate you need winners ≥ ~1.5–2R
   for positive expectancy; the MFE data tells you whether the trade can structurally deliver that.

---

## 6. Anti-overfitting rules (mandatory — this is how strategies lie)

- **Negative controls:** run the same test on (a) random entries, (b) a shuffled-label version.
  Your edge must beat both decisively. If random scores similarly, you found noise.
- **Sign stability > magnitude:** a small edge with the same sign in all 6 folds beats a huge edge
  in 2 folds and flat in 4.
- **Parameter sensitivity:** nudge each threshold ±20%. If the edge collapses, it's curve-fit.
- **Multiple-testing discipline:** every extra parameter/feature you try raises the odds of a
  false positive. Pre-register the hypothesis and the pass criterion *before* looking at OOS.
- **Cost stress:** re-run the winner at 1.5× your slippage assumption. If it dies, it wasn't real.
- **Capacity check:** does the signal still work if you only trade names where your order is
  < X% of bar volume? (An edge you can't get filled on isn't an edge.)

---

## 7. Research queue (the order to actually run them)

```
1. H1  Cross-sectional ranking      ← start here (highest EV/effort)
2. H2  Intraday momentum anomaly     ← validates the core thesis
3. H5  Sector RS  (needs sector_map) ← cheap conditioner on H1
4. H4  Beta-decomposed gaps          ← refines selection
5. H3  VIX regime switch             ← unlocks the short/MR side
6. H6  Order-flow imbalance          ← only after live ticks accumulate
```

Each runs through the §1 protocol, scored by §2 metrics, gated by §6 controls. A hypothesis that
passes becomes a feature in `strategy/score.py`; one that fails is documented as dead and dropped.
