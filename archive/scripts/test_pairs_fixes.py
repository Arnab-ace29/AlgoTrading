"""
Regression tests for the pairs fixes:
  • PairsHealthTracker must NOT count an un-testable day (data gap / holidays)
    toward the halt streak — that conflation false-halts healthy pairs.
  • The pairs z-score must exclude the current bar from its own mean/std, so a true
    divergence crosses the entry/stop thresholds instead of self-damping toward 0.

    .venv/bin/python scripts/test_pairs_fixes.py
    pytest scripts/test_pairs_fixes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

import risk.pairs_risk as pr
from risk.pairs_risk import PairsHealthTracker
from signals.pairs.pairs_signal import PairsSignal

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def test_health_tristate_no_false_halt():
    print("PAIRS — un-testable days don't halt a healthy pair:")
    orig = pr.check_pair_health
    try:
        pr.check_pair_health = lambda a, b, **k: (None, 1.0)   # never testable
        t = PairsHealthTracker(consecutive_days_to_halt=5)
        for _ in range(20):
            st = t.record_daily_check("A", "B")
        check(not t.is_halted("A", "B"), "20 un-testable days → NOT halted")
        check(st["streak"] == 0, "halt streak stays 0 on un-testable days")

        # A genuinely broken pair still halts after the configured streak.
        pr.check_pair_health = lambda a, b, **k: (False, 0.5)   # broken
        for _ in range(5):
            st = t.record_daily_check("C", "D")
        check(t.is_halted("C", "D"), "5 genuinely-unhealthy days DO halt")
    finally:
        pr.check_pair_health = orig


def test_zscore_excludes_current_bar():
    print("PAIRS — z-score excludes the current bar (true divergence crosses stop):")
    sig = PairsSignal(pair=("A", "B"), hedge_ratio=1.0, window=20, entry_z=2.0, stop_z=3.5)
    rng = np.random.default_rng(3)
    n = 60
    # B flat; A = B + stationary noise, then a 4-sigma blow-out on the last bar.
    base = 100 + np.cumsum(rng.normal(0, 0.05, n))
    a = base + rng.normal(0, 1.0, n)
    a[-1] = base[-1] + 4.0          # ~4σ divergence on the latest bar
    pa = pd.Series(a); pb = pd.Series(base)
    z = sig.compute_zscore(pa, pb)
    check(z is not None and abs(z) > 3.0, f"a ~4σ blow-out registers |z|>3 (got {z:.2f})")


def main() -> int:
    print("=" * 60); print("PAIRS FIXES TESTS"); print("=" * 60)
    test_health_tristate_no_false_halt()
    test_zscore_excludes_current_bar()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
