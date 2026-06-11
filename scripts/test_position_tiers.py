"""
SIZE-02 regression: the position sizer's score→lots bands must match the
documented table in docs/SIGNALS.md (the single source of truth):

    0.55–0.65 → signal only (NO trade)
    0.65–0.70 → 1 lot   (reduced to 0 in CHOPPY)
    0.70–0.75 → 2 lots
    ≥0.75     → 3 lots  (all capped by the active risk profile's lot_size_cap)

Before the fix the sizer keyed off SCORE_THRESHOLD_STRONG + a (ENTRY+STRONG)/2
midpoint and floored at 1 lot, so it traded the 0.55–0.65 "signal only" band and
its tiers didn't line up with the docs.

    .venv/bin/python scripts/test_position_tiers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ensemble.position_sizing import PositionSizer
from config.risk_profiles import ACTIVE as RISK
from signals.base import Direction, Regime

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def main() -> int:
    print("=" * 60); print("SIZE-02 — score-tiered lots match docs/SIGNALS.md"); print("=" * 60)

    # ── Band mapping (profile-independent: this is the desired lots pre-cap) ──
    tl = PositionSizer.score_tier_lots
    cases = [
        (0.55, 0), (0.60, 0), (0.6499, 0),     # signal only — no trade
        (0.65, 1), (0.66, 1), (0.6999, 1),     # 1-lot band
        (0.70, 2), (0.72, 2), (0.7499, 2),     # 2-lot band
        (0.75, 3), (0.90, 3), (1.00, 3),       # 3-lot band
    ]
    for score, want in cases:
        got = tl(score)[0]
        check(got == want, f"score {score:.4f} → {want} lot(s) (got {got})")

    # Symmetric for shorts (uses |score|).
    check(tl(-0.72)[0] == 2, "short score -0.72 → 2 lots (uses |score|)")
    check(tl(-0.60)[0] == 0, "short score -0.60 → no trade")

    # Boundaries are inclusive on the lower edge (>=).
    check(tl(0.65)[0] == 1 and tl(0.70)[0] == 2 and tl(0.75)[0] == 3,
          "band edges 0.65 / 0.70 / 0.75 are inclusive")

    # ── size() integration — cash equity is now RISK-BASED (shares scale with the
    #    per-trade risk budget × conviction tier ÷ stop distance), NOT 1–3 shares.
    #    Band logic (no-trade < 0.65, CHOPPY tier-1 stand-down) is unchanged. ──
    sizer = PositionSizer(capital=10_000_000)   # lot_size defaults to 1 → cash equity
    entry, atr = 2950.0, 28.5
    sl_dist = atr * RISK.sl_atr_multiplier
    per_trade = (RISK.max_daily_loss_pct / 100) * 10_000_000 / RISK.max_trades_per_day

    def qty(score, regime=Regime.TRENDING_UP):
        r = sizer.size("T", Direction.LONG, score, entry, atr, [], regime=regime)
        return None if r is None else r.qty

    check(qty(0.60) is None, "0.55–0.65 band stands down (signal only, no trade)")
    q1, q2, q3 = qty(0.66), qty(0.72), qty(0.80)
    check(q1 and q2 and q3 and q3 > q2 > q1, f"qty scales with conviction tier ({q1} < {q2} < {q3})")
    # tier-3 risks ~the full per-trade budget; sizing deploys real capital (not 1–3 shares).
    expected_t3 = int(per_trade / sl_dist)
    check(abs(q3 - expected_t3) <= 1, f"tier-3 qty sized to the full risk budget (~{expected_t3}, got {q3})")
    check(q3 * entry > 0.05 * 10_000_000, "tier-3 deploys a meaningful fraction of capital (not ~1 share)")

    # CHOPPY override: only the marginal tier-1 (0.65–0.70) stands down.
    check(qty(0.66, Regime.CHOPPY) is None, "0.66 in CHOPPY → no trade (tier-1 stands down)")
    check(qty(0.72, Regime.CHOPPY) and qty(0.72, Regime.CHOPPY) > 0, "0.72 in CHOPPY → still trades")
    check(qty(0.80, Regime.CHOPPY) and qty(0.80, Regime.CHOPPY) > 0, "0.80 in CHOPPY → still trades")

    # The sizing note still records the band.
    r = sizer.size("T", Direction.LONG, 0.80, entry, atr, [], regime=Regime.TRENDING_UP)
    check(r is not None and "3LOT" in r.sizing_note, f"note records the band ({r.sizing_note if r else None})")

    # F&O mode (lot_size > 1) keeps the lot-count model.
    fno = PositionSizer(capital=10_000_000, lot_size=50)
    rf = fno.size("NIFTYFUT", Direction.LONG, 0.80, entry, atr, [], regime=Regime.TRENDING_UP)
    check(rf is not None and rf.qty == min(3, RISK.lot_size_cap) * 50,
          f"F&O still sizes by lots × lot_size (got {rf.qty if rf else None})")

    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
