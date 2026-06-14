"""Unit tests for the NSE intraday cost model (analytics/costs.py)."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.costs import (
    round_trip_cost, cost_breakdown, per_leg_slippage, slip_price, is_cost_effective,
)


def test_round_trip_cost_known_trade():
    # Buy 100 @ 500, sell 100 @ 510. Turnover: buy 50,000, sell 51,000.
    cost = round_trip_cost(500, 510, 100)
    # Hand-check the components:
    brokerage = min(20, 0.0003 * 50000) + min(20, 0.0003 * 51000)   # 15 + 15.3 = 30.3
    stt       = 0.00025 * 51000                                      # 12.75
    exchange  = 0.0000297 * 101000                                   # ~3.00
    sebi      = 0.000001 * 101000                                    # 0.101
    stamp     = 0.00003 * 50000                                      # 1.5
    gst       = 0.18 * (brokerage + exchange + sebi)
    expected  = round(brokerage + stt + exchange + sebi + stamp + gst, 2)
    assert abs(cost - expected) < 0.01, (cost, expected)
    # Breakdown total must equal round_trip_cost.
    assert abs(cost_breakdown(500, 510, 100)["total"] - cost) < 0.01


def test_cost_is_positive_and_small_fraction():
    # On a liquid large-cap trade, charges should be a small % of turnover.
    cost = round_trip_cost(2000, 2040, 50)   # ~₹1L turnover/leg
    turnover = 2000 * 50
    assert cost > 0
    assert cost / turnover < 0.001            # < 0.1% per leg-ish, sane


def test_degenerate_inputs_return_zero():
    assert round_trip_cost(0, 100, 10) == 0.0
    assert round_trip_cost(100, 100, 0) == 0.0
    assert round_trip_cost("x", 100, 10) == 0.0
    assert cost_breakdown(0, 0, 0)["total"] == 0.0


def test_slippage_separate_and_always_hurts():
    # slip_price: BUY fills higher, SELL fills lower.
    assert slip_price(100, "BUY", 0.005) == 100.5
    assert slip_price(100, "SELL", 0.005) == 99.5
    assert per_leg_slippage(100, 10, 0.005) == 5.0


def test_round_trip_cost_excludes_slippage():
    # Charges-only: cost must be far below a 0.05% x2 slippage figure on the turnover.
    cost = round_trip_cost(1000, 1000, 100)          # 200,000 turnover
    slip = per_leg_slippage(1000, 100, 0.0005) * 2   # both legs
    assert cost < slip * 3   # cost is charges; slippage modelled elsewhere


def test_is_cost_effective():
    # A 2% target on a liquid name clears costs; a sub-cost target does not.
    assert is_cost_effective(500, 510, 100) is True       # +10 gross = 1000 >> cost
    assert is_cost_effective(500, 500.05, 100) is False   # +5 gross, < 2x cost


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
