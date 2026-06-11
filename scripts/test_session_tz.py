"""
FEAT-TZ regression: candle timestamps are stored in UTC but session-relative
features are defined in IST (NSE 09:15–15:30). Before the fix, time_norm spanned
only ~0–0.12 over a session and session_open was detected at 14:45 IST. This builds
a real UTC-indexed session and asserts the IST-correct behaviour.

    .venv/bin/python scripts/test_session_tz.py
    pytest scripts/test_session_tz.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from features.indicators import compute_all_features, _ist_index

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def _utc_session_df(n=75, tz_aware=True):
    """A single NSE session: 75 5-min bars from 03:45 UTC (= 09:15 IST)."""
    start = pd.Timestamp("2024-06-03 03:45:00", tz="UTC")   # Mon 09:15 IST
    idx = pd.date_range(start, periods=n, freq="5min")      # UTC
    if not tz_aware:
        idx = idx.tz_localize(None)                          # naive UTC (backtest style)
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0, 0.2, n))
    df = pd.DataFrame({
        "open": close, "high": close + 0.3, "low": close - 0.3,
        "close": close, "volume": rng.uniform(1e5, 2e5, n),
    }, index=idx)
    return df


def test_time_norm_spans_session():
    print("FEAT-TZ — time_norm spans 0→1 across an IST session (not 0→0.12):")
    df = compute_all_features(_utc_session_df())
    tn = df["time_norm"]
    check(abs(tn.iloc[0] - 0.0) < 1e-6, f"first bar (09:15 IST) → time_norm≈0 (got {tn.iloc[0]:.3f})")
    # 75 bars → last is 09:15 + 74*5min = 15:25 IST → 370/375 ≈ 0.987.
    check(tn.iloc[-1] > 0.95, f"last bar (15:25 IST) → time_norm≈0.99 (got {tn.iloc[-1]:.3f})")
    check(tn.max() <= 1.0 and tn.min() >= 0.0, "time_norm stays within [0,1]")


def test_session_open_detected():
    print("FEAT-TZ — session_open is the 09:15 IST bar (not 14:45):")
    df = _utc_session_df()
    feat = compute_all_features(df.copy())
    expected_open = float(df["open"].iloc[0])     # 09:15 IST bar open
    check(abs(float(feat["session_open"].iloc[-1]) - expected_open) < 1e-6,
          "session_open ffills from the real 09:15 IST open")
    check(feat["session_return"].notna().any(), "session_return is computable (session_open found)")


def test_naive_utc_also_ist():
    print("FEAT-TZ — tz-naive (backtest) UTC index is also treated as UTC→IST:")
    df = compute_all_features(_utc_session_df(tz_aware=False))
    check(df["time_norm"].iloc[0] < 0.05 and df["time_norm"].iloc[-1] > 0.95,
          "naive-UTC session still spans 0→1 in IST")


def test_ist_helper():
    print("FEAT-TZ — _ist_index converts both tz-aware and naive:")
    aware = pd.date_range(pd.Timestamp("2024-06-03 03:45", tz="UTC"), periods=3, freq="5min")
    check(_ist_index(aware)[0].hour == 9 and _ist_index(aware)[0].minute == 15,
          "03:45 UTC → 09:15 IST")
    naive = aware.tz_localize(None)
    check(_ist_index(naive)[0].hour == 9, "naive 03:45 (assumed UTC) → 09:15 IST")


def main() -> int:
    print("=" * 60); print("SESSION TIMEZONE TESTS (FEAT-TZ)"); print("=" * 60)
    test_time_norm_spans_session()
    test_session_open_detected()
    test_naive_utc_also_ist()
    test_ist_helper()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
