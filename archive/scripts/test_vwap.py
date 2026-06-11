"""
Tests for session-anchored VWAP (FEAT-01).

    .venv/bin/python scripts/test_vwap.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from features.indicators import _session_vwap, compute_all_features

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def test_session_reset():
    print("session reset + cumulative average:")
    idx = pd.to_datetime([
        "2025-01-01 09:15", "2025-01-01 09:20", "2025-01-01 09:25",
        "2025-01-02 09:15", "2025-01-02 09:20",
    ])
    price = pd.Series([10, 20, 30, 100, 200], index=idx, dtype=float)
    vol = pd.Series([1, 1, 1, 1, 1], index=idx, dtype=float)
    vw = _session_vwap(price, vol, idx).values
    # day1: 10, (10+20)/2=15, (10+20+30)/3=20 ; day2 RESETS: 100, (100+200)/2=150
    check(np.allclose(vw, [10, 15, 20, 100, 150]), f"cumulative within day, resets next day → {list(vw)}")
    check(abs(vw[3] - 100) < 1e-9, "first bar of day 2 = its own typical price (no carry-over from day 1)")


def test_volume_weighted():
    print("volume weighting:")
    idx = pd.to_datetime(["2025-01-01 09:15", "2025-01-01 09:20",
                          "2025-01-02 09:15", "2025-01-02 09:20"])
    price = pd.Series([10, 20, 100, 200], index=idx, dtype=float)
    vol = pd.Series([1, 3, 1, 1], index=idx, dtype=float)
    vw = _session_vwap(price, vol, idx).values
    # day1 bar1 = (10*1 + 20*3)/(1+3) = 17.5
    check(abs(vw[1] - 17.5) < 1e-9, f"weights by volume within the session ({vw[1]})")


def test_no_lookahead():
    print("no look-ahead:")
    idx = pd.to_datetime([
        "2025-01-01 09:15", "2025-01-01 09:20", "2025-01-01 09:25",
        "2025-01-02 09:15", "2025-01-02 09:20",
    ])
    price = pd.Series([10, 20, 30, 100, 200], index=idx, dtype=float)
    vol = pd.Series([1, 1, 1, 1, 1], index=idx, dtype=float)
    full = _session_vwap(price, vol, idx).values
    day1 = _session_vwap(price.iloc[:3], vol.iloc[:3], idx[:3]).values
    check(np.allclose(full[:3], day1), "day-1 VWAP is identical with or without day-2 bars present")


def test_fallback_no_timestamps():
    print("fallback without timestamps:")
    n = 100
    price = pd.Series(np.linspace(100, 110, n))
    vol = pd.Series(np.ones(n))
    vw = _session_vwap(price, vol, price.index)   # RangeIndex → rolling fallback
    check(len(vw) == n, "returns a full-length series (rolling fallback, no crash)")


def test_integration():
    print("integration via compute_all_features:")
    rng = np.random.default_rng(5)
    rows = []
    start = datetime(2025, 1, 1, 9, 15)
    for d in range(2):
        base = start + timedelta(days=d)
        px = 1000 + rng.normal(0, 2, 75).cumsum()
        for i in range(75):
            ts = base + timedelta(minutes=5 * i)
            c = px[i]
            rows.append((ts, c, c + 1, c - 1, c, 1000.0 + i))
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"]).set_index("timestamp")
    out = compute_all_features(df)
    check("vwap_session" in out.columns and "vwap_dist_pct" in out.columns, "session VWAP + distance produced")

    dates = out.index.normalize()
    day2_first = int(np.argmax(dates == dates.unique()[1]))   # first row of day 2
    typ = (out["high"] + out["low"] + out["close"]) / 3
    check(abs(out["vwap_session"].iloc[day2_first] - typ.iloc[day2_first]) < 1e-6,
          "VWAP resets on the first bar of day 2 (== its typical price)")
    check(not out["vwap_dist_pct"].iloc[day2_first:].isna().all(), "vwap_dist_pct is finite intraday")


def main() -> int:
    print("=" * 60); print("SESSION-ANCHORED VWAP TESTS (FEAT-01)"); print("=" * 60)
    test_session_reset()
    test_volume_weighted()
    test_no_lookahead()
    test_fallback_no_timestamps()
    test_integration()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
