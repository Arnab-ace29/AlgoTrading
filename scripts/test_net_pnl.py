"""
Tests for net-of-cost PnL accounting (PnL-NET) and the cost-aware entry filter.

    .venv/bin/python scripts/test_net_pnl.py
    pytest scripts/test_net_pnl.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from analytics.costs import round_trip_cost, is_cost_effective
from analytics.pnl_tracker import PnLTracker

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def test_net_series_classifies_on_net():
    print("PnL-NET — win/loss classified on NET, not gross:")
    tr = PnLTracker()
    # A trade with a TINY gross gain that round-trip costs flip negative.
    entry, exit_, qty = 3000.0, 3000.5, 1   # +0.5 gross on 1 share
    cost = round_trip_cost(entry, exit_, qty)
    check(cost > 0.5, f"round-trip cost ({cost:.2f}) exceeds the 0.50 gross gain")
    df = pd.DataFrame([{
        "pnl": 0.5, "cost": cost, "net_pnl": 0.5 - cost,
        "entry_price": entry, "exit_price": exit_, "qty": qty,
    }])
    net = tr._net_series(df)
    check(float(net.iloc[0]) < 0, "stored net_pnl is negative")
    check((net > 0).sum() == 0, "the cost-eaten trade is NOT counted as a win")


def test_net_series_legacy_fallback():
    print("PnL-NET — legacy rows (no net_pnl column) recompute cost:")
    tr = PnLTracker()
    df = pd.DataFrame([{"pnl": 0.5, "entry_price": 3000.0, "exit_price": 3000.5, "qty": 1}])
    net = tr._net_series(df)
    check(float(net.iloc[0]) < 0, "legacy gross-positive cost-eaten trade nets negative")


def test_kelly_uses_net():
    print("PnL-NET — Kelly win-rate excludes cost-eaten 'wins':")
    tr = PnLTracker()
    # 10 marginal gross-wins that all net negative -> net win_rate should be 0.
    rows = [{"pnl": 0.5, "cost": 5.0, "net_pnl": -4.5,
             "entry_price": 3000.0, "exit_price": 3000.5, "qty": 1} for _ in range(10)]
    df = pd.DataFrame(rows)
    net = tr._net_series(df)
    check((net > 0).mean() == 0.0, "net win-rate of cost-eaten trades is 0% (gross would be 100%)")


def test_cost_filter():
    print("PnL-NET — is_cost_effective blocks cost-traps, passes real edges:")
    # Tiny edge: target only 0.5 above entry on 1 share -> blocked.
    check(not is_cost_effective(3000.0, 3000.5, 1), "tiny 0.5-rupee target is blocked")
    # Real edge: 2.5*ATR target ~ 1.25% move -> easily passes.
    check(is_cost_effective(3000.0, 3037.5, 1), "a ~1.25% target move passes")
    # Symmetric for shorts (target below entry).
    check(is_cost_effective(3000.0, 2962.5, 1), "a short target (below entry) passes")
    check(not is_cost_effective(0.0, 10.0, 1), "non-positive entry is skipped")


def main() -> int:
    print("=" * 60); print("NET-PnL ACCOUNTING TESTS"); print("=" * 60)
    test_net_series_classifies_on_net()
    test_net_series_legacy_fallback()
    test_kelly_uses_net()
    test_cost_filter()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
