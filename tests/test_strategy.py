"""Tests for strategy/ranking.py (H1) and strategy/sizing.py (risk engine)."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from strategy.ranking import compute_signal, select, RankParams
from strategy.sizing import position_size, SizingParams


# ── Ranking (H1) ──────────────────────────────────────────────────────────────
def _snap():
    # 6 symbols: A strong-up+high-vol (long), F strong-down+high-vol (short),
    # the rest noise / low-vol.
    return pd.DataFrame({
        "rvol":     [6.0, 1.2, 0.8, 3.5, 1.0, 5.0],
        "ret_open": [0.04, 0.001, -0.002, 0.03, 0.0, -0.05],
    }, index=["A", "B", "C", "D", "E", "F"])


def test_signal_is_signed():
    sig = compute_signal(_snap())
    assert sig["A"] > 0 and sig["F"] < 0
    assert abs(sig["E"]) < 1e-9   # zero move -> zero signal


def test_select_picks_extremes_and_direction():
    res = select(_snap(), RankParams(top_pct=0.5, min_rvol=2.0, min_abs_ret=0.005, max_per_side=3))
    assert res.loc["A", "direction"] == "LONG"
    assert res.loc["F", "direction"] == "SHORT"
    # B, C, E fail the min_rvol/min_abs_ret gates → excluded
    assert "B" not in res.index and "C" not in res.index and "E" not in res.index


def test_select_respects_max_per_side():
    snap = pd.DataFrame({
        "rvol":     [3, 4, 5, 6],
        "ret_open": [0.02, 0.03, 0.04, 0.05],
    }, index=["A", "B", "C", "D"])
    res = select(snap, RankParams(top_pct=1.0, min_rvol=2.0, min_abs_ret=0.005, max_per_side=2))
    assert (res["direction"] == "LONG").sum() <= 2


def test_select_empty_when_nothing_eligible():
    snap = pd.DataFrame({"rvol": [1.0, 1.1], "ret_open": [0.0, 0.001]}, index=["A", "B"])
    assert select(snap).empty


# ── Sizing (risk engine) ──────────────────────────────────────────────────────
def test_position_size_risk_is_one_percent():
    # ₹20k capital, conviction 1.0, 1% => ₹200 risk. Entry 500, stop 488, atr 8.
    p = SizingParams(base_risk_pct=0.01, slippage_pad_atr=0.0)
    r = position_size(20_000, 1.0, entry=500, stop=488, atr=8, params=p)
    # risk/share = |500-488| = 12 ; qty = floor(200/12)=16 ; risk=192
    assert r.qty == 16
    assert abs(r.risk - 192) < 1e-6
    assert r.reason == "ok"


def test_conviction_scales_risk():
    p = SizingParams(base_risk_pct=0.01, slippage_pad_atr=0.0)
    lo = position_size(20_000, 0.5, 500, 488, 8, p)
    hi = position_size(20_000, 1.5, 500, 488, 8, p)
    assert hi.qty > lo.qty   # more conviction -> more size


def test_daily_risk_cap_blocks():
    p = SizingParams(base_risk_pct=0.01, daily_risk_cap_pct=0.03, slippage_pad_atr=0.0)
    # already 2.9% risked; a 1% trade would exceed 3% -> blocked
    r = position_size(20_000, 1.0, 500, 488, 8, p, open_risk=0.029 * 20_000)
    assert r.qty == 0 and r.reason == "daily_risk_cap"


def test_exposure_cap_limits_qty():
    p = SizingParams(base_risk_pct=1.0, max_exposure=10_000, slippage_pad_atr=0.0)  # huge budget
    r = position_size(20_000, 1.0, entry=500, stop=499, atr=1, params=p)
    assert r.qty == 20   # 10,000 / 500, capped by exposure not risk


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
