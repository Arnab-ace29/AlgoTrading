"""Unit tests for features/indicators.py — golden values + no-look-ahead."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from features.indicators import (
    session_vwap, atr, rvol_same_window, intraday_return_from_open,
    zscore, relative_strength,
)


def _intraday_df(days=25, bars_per_day=3, base_vol=1000):
    """Build a small multi-day 5-min-ish frame at fixed time-of-day slots (UTC)."""
    rows = []
    for d in range(days):
        day = pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(days=d)
        for b in range(bars_per_day):
            ts = day + pd.Timedelta(hours=4, minutes=5 * b)   # 09:35.. IST-ish
            price = 100 + b
            rows.append((ts, price, price + 1, price - 1, price + 0.5,
                         base_vol * (b + 1)))
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    return df.set_index("ts")


def test_atr_constant_range():
    # high-low is always 2, prev-close gaps small → ATR converges near 2.
    df = _intraday_df()
    a = atr(df, period=14)
    assert a.dropna().iloc[-1] > 0
    assert 1.0 < a.dropna().iloc[-1] < 4.0


def test_session_vwap_resets_daily():
    df = _intraday_df(days=2, bars_per_day=3)
    v = session_vwap(df)
    # First bar of each day: VWAP == that bar's typical price (only one bar so far).
    day = df.index.tz_convert("Asia/Kolkata").normalize()
    firsts = v.groupby(day).first()
    tp = ((df["high"] + df["low"] + df["close"]) / 3).groupby(day).first()
    assert np.allclose(firsts.values, tp.values)


def test_rvol_same_window_no_lookahead_and_value():
    # Same volume every day at each slot → rvol should be ~1.0 once baseline exists,
    # and the FIRST occurrence of each slot must be NaN (no prior day = no baseline).
    df = _intraday_df(days=25, bars_per_day=3, base_vol=1000)
    r = rvol_same_window(df, lookback_days=20)
    ist = df.index.tz_convert("Asia/Kolkata")
    slot = pd.Series(ist.strftime("%H:%M"), index=df.index)
    # first row of each slot -> NaN (needs >=3 priors actually, so first 2 NaN)
    for s, grp in r.groupby(slot):
        assert np.isnan(grp.iloc[0]), s
    # late rows: volume constant per slot → ratio ~1.0
    assert abs(r.dropna().iloc[-1] - 1.0) < 1e-6


def test_rvol_detects_a_spike():
    df = _intraday_df(days=25, bars_per_day=1, base_vol=1000)
    df.iloc[-1, df.columns.get_loc("volume")] = 5000   # 5x spike on the last bar
    r = rvol_same_window(df, lookback_days=20)
    assert abs(r.iloc[-1] - 5.0) < 1e-6


def test_zscore_basic():
    z = zscore(pd.Series([1, 2, 3, 4, 5]))
    assert abs(z.mean()) < 1e-9
    assert z.iloc[-1] > 0 and z.iloc[0] < 0
    # zero-variance -> all zeros (no divide-by-zero)
    assert (zscore(pd.Series([7, 7, 7])) == 0).all()


def test_relative_strength_sign():
    stock = pd.Series([100, 102, 104])   # +2%, +1.96%
    index = pd.Series([100, 101, 102])   # +1%, +0.99%
    rs = relative_strength(stock, index, periods=1)
    assert rs.iloc[1] > 0   # stock outperformed


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
