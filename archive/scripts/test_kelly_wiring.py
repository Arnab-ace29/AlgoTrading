"""
SIZE-03 regression: prove the Kelly layer is actually wired now.

Before: PositionSizer.update_kelly_stats() was never called, so the Kelly layer
never activated (it gates on >=20 trades and _trade_count stayed 0). This test
seeds closed trades, derives Kelly inputs from them via PnLTracker.kelly_stats(),
feeds them to the sizer the way live/runner.py now does, and checks the sizer's
Kelly fraction engages and changes sizing.

    .venv/bin/python scripts/test_kelly_wiring.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import data.db as db

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def _seed_closed_trade(symbol, entry, exit_price, qty=10):
    tid = db.log_trade_open(symbol, "s", "BUY", "INTRADAY", qty, entry,
                            entry - 5, entry + 10, 0.7, mode="PAPER")
    db.log_trade_close(tid, exit_price, "TARGET_HIT" if exit_price > entry else "SL_HIT")


def main() -> int:
    print("=" * 60); print("SIZE-03 — Kelly layer wiring"); print("=" * 60)
    tmp = tempfile.mkdtemp()
    db.close_conn()
    db.DB_PATH = Path(tmp) / "kelly.sqlite"
    db.init_db()

    # 15 winners of +100 (100->110, qty 10) and 10 losers of -50 (100->95, qty 10).
    # win_rate = 15/25 = 0.60 ; n = 25. reward:risk is NET of costs (PnL-NET), so it
    # sits a touch below the gross 2.0 (avg_win/avg_loss both shrink by ~equal cost).
    for i in range(15):
        _seed_closed_trade(f"W{i}", 100.0, 110.0)
    for i in range(10):
        _seed_closed_trade(f"L{i}", 100.0, 95.0)

    from analytics.pnl_tracker import PnLTracker
    tracker = PnLTracker()
    wr, rr, n = tracker.kelly_stats()
    check(abs(wr - 0.60) < 1e-6, f"kelly_stats win_rate = 0.60 (got {wr})")
    check(1.8 <= rr < 2.0, f"kelly_stats reward:risk is net-of-cost, just under gross 2.0 (got {rr})")
    check(n == 25, f"kelly_stats total closed-trade count = 25 (got {n})")

    # Feed the sizer exactly as live/runner.py::_refresh_kelly_stats now does.
    from ensemble.position_sizing import PositionSizer
    from signals.base import Direction

    fresh = PositionSizer(capital=100_000)
    check(fresh._trade_count == 0, "a fresh sizer starts with Kelly inert (n=0)")

    sizer = PositionSizer(capital=100_000)
    sizer.update_kelly_stats(wr, rr, n)            # <-- the wiring
    check(sizer._trade_count == 25, "sizer now sees 25 trades (Kelly past its 20-trade gate)")

    # quarter-Kelly fraction for the realized (net) edge: ((b*p - q)/b) * 0.25.
    expected_frac = ((rr * wr - (1 - wr)) / rr) * 0.25
    frac = sizer._compute_kelly_fraction()
    check(abs(frac - expected_frac) < 1e-9,
          f"quarter-Kelly fraction matches the net edge ({frac:.4f} ≈ {expected_frac:.4f})")

    # ── The normalization fix (the second-order SIZE-03 bug) ──────────────────
    # The multiplier is edge ÷ baseline, centered on 1.0 at the assumed baseline edge.
    base = PositionSizer(capital=100_000)
    base.update_kelly_stats(0.55, 1.5, 25)         # the baseline edge
    check(abs(base._kelly_multiplier() - 1.0) < 1e-9,
          f"baseline edge → 1.0× multiplier (got {base._kelly_multiplier():.3f})")
    baseline_frac = base._compute_kelly_fraction()
    expected_mult = expected_frac / baseline_frac
    check(abs(sizer._kelly_multiplier() - expected_mult) < 1e-9,
          f"better-than-baseline edge scales up (got {sizer._kelly_multiplier():.3f} ≈ {expected_mult:.3f})")

    args = ("TEST", Direction.LONG, 0.72, 2950.0, 28.5, [])

    # Regression: a healthy edge must NOT round to 0 lots. (Before the fix the raw
    # quarter-Kelly fraction 0.10 gave round(base*0.10)=0 → no trade.)
    r_cal = sizer.size(*args)
    check(r_cal is not None and r_cal.qty >= 1,
          f"healthy edge still trades — not zeroed by Kelly (qty={r_cal.qty if r_cal else 0})")
    check(r_cal is not None and "KELLY" in r_cal.sizing_note,
          f"sizing note records the Kelly layer ({r_cal.sizing_note if r_cal else 'None'})")

    # At the baseline edge the Kelly layer is a no-op → sizes like the inert sizer.
    check(base.size(*args).qty == fresh.size(*args).qty,
          "baseline-edge Kelly sizes identically to an inert sizer (1.0× no-op)")

    # A poor / negative edge stands down (Kelly → 0).
    poor = PositionSizer(capital=100_000)
    poor.update_kelly_stats(0.40, 1.0, 30)         # below breakeven → Kelly fraction 0
    check(poor._kelly_multiplier() == 0.0, "negative edge → 0× multiplier")
    check(poor.size(*args) is None, "negative edge stands down (no trade)")

    # The runner wiring exists and is the glue that feeds tracker → sizer.
    from live.runner import LiveRunner
    check(hasattr(LiveRunner, "_refresh_kelly_stats"),
          "LiveRunner._refresh_kelly_stats exists (the wiring point)")

    db.close_conn()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
