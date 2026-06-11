"""
Setup Verification Script
Run this first to confirm everything is installed and wired up correctly.

Usage:
    python scripts/verify_setup.py

Checks:
  1. All required packages importable
  2. SQLite (WAL) DB can be created and schema can be initialised
  3. Features compute without error on synthetic data
  4. All 3 signals produce valid scores
  5. Ensemble aggregator combines scores correctly
  6. Position sizer returns valid sizing
  7. Circuit breaker logic works
  8. yfinance can fetch sample data (optional)
"""

from __future__ import annotations
import sys
from pathlib import Path

# Ensure project root is on sys.path when run from scripts/ or project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

PASS = "  ✓"
FAIL = "  ✗"


def run_check(name: str, fn) -> bool:
    try:
        fn()
        print(f"{PASS} {name}")
        return True
    except Exception as e:
        print(f"{FAIL} {name}")
        print(f"      Error: {e}")
        return False


def check_imports():
    # These imports are the check itself — they verify each dependency is installed.
    import sqlite3   # noqa: F401  — operational store (stdlib)
    import upstox_client  # noqa: F401
    import ta  # noqa: F401
    import fastapi  # noqa: F401
    import loguru  # noqa: F401
    # vectorbt is NOT required (custom backtest engine) and DuckDB is now OPTIONAL
    # (SQLite is the operational store; DuckDB only for heavy analytics). See
    # docs/KNOWN_ISSUES.md (BT-01..04, LIVE-06).


def check_db():
    import tempfile
    from pathlib import Path
    from data import db as dbmod

    with tempfile.TemporaryDirectory() as tmp:
        dbmod.close_conn()
        dbmod.DB_PATH = Path(tmp) / "test.sqlite"
        dbmod.init_db()
        tid = dbmod.log_trade_open("TEST", "s", "BUY", "INTRADAY", 1,
                                   100.0, 99.0, 101.0, 0.6, mode="PAPER")
        dbmod.log_trade_close(tid, 102.0, "TARGET_HIT")
        assert len(dbmod.get_trade_log()) >= 1, "trade round-trip failed"
        dbmod.close_conn()


def make_synthetic_df(n: int = 200) -> pd.DataFrame:
    np.random.seed(42)
    idx = pd.date_range("2024-01-02 09:15", periods=n, freq="5min", tz="Asia/Kolkata")
    close = 2900 + np.cumsum(np.random.randn(n) * 5)
    return pd.DataFrame({
        "open":   close - np.abs(np.random.randn(n) * 2),
        "high":   close + np.abs(np.random.randn(n) * 4),
        "low":    close - np.abs(np.random.randn(n) * 4),
        "close":  close,
        "volume": np.random.randint(10_000, 500_000, n).astype(float),
    }, index=idx)


def check_features():
    from features.indicators import compute_all_features, FEATURE_COLUMNS
    df = make_synthetic_df(200)
    df_feat = compute_all_features(df)
    non_null_cols = [c for c in FEATURE_COLUMNS if c in df_feat.columns and df_feat[c].notna().any()]
    assert len(non_null_cols) >= 50, f"Only {len(non_null_cols)} feature columns have data"


def check_signals():
    from features.indicators import compute_all_features
    from signals.technical.vwap_breakout  import VWAPBreakoutSignal
    from signals.technical.rsi_momentum   import RSIMomentumSignal
    from signals.technical.mean_reversion import MeanReversionSignal

    df = compute_all_features(make_synthetic_df(200))
    for Signal in [VWAPBreakoutSignal, RSIMomentumSignal, MeanReversionSignal]:
        result = Signal().compute(df, "TEST")
        assert -1.0 <= result.score <= 1.0, f"Score out of range: {result.score}"
        assert result.direction in ["LONG", "SHORT", "NEUTRAL"]


def check_ensemble():
    from features.indicators import compute_all_features
    from ensemble.aggregator import EnsembleAggregator

    df = compute_all_features(make_synthetic_df(200))
    agg = EnsembleAggregator()
    result = agg.compute(df, "TEST")
    assert -1.0 <= result.composite_score <= 1.0


def check_position_sizer():
    from ensemble.position_sizing import PositionSizer
    from signals.base import Direction

    sizer  = PositionSizer()
    result = sizer.size("TEST", Direction.LONG, 0.72, 2950.0, 28.5, [])
    assert result is not None
    assert result.qty >= 1
    assert result.sl_price < 2950.0
    assert result.target_price > 2950.0


def check_circuit_breaker():
    from risk.circuit_breaker import CircuitBreaker
    from datetime import datetime
    import pytz

    cb = CircuitBreaker(capital=100_000)
    IST = pytz.timezone("Asia/Kolkata")
    mid_day = datetime(2024, 6, 3, 11, 0, tzinfo=IST)
    allowed, reason = cb.allow_entry("TEST", session_pnl=0, open_position_count=0, now=mid_day)
    assert allowed, f"Should be allowed: {reason}"

    allowed, reason = cb.allow_entry("TEST", session_pnl=-2000, open_position_count=0, now=mid_day)
    assert not allowed, "Should be blocked by daily loss limit"


def check_yfinance():
    import yfinance as yf
    df = yf.download("TCS.NS", period="5d", interval="1d", progress=False, auto_adjust=True)
    assert not df.empty, "yfinance returned no data"


if __name__ == "__main__":
    print("\nAlgoTrading — Setup Verification\n" + "=" * 40)

    checks = [
        ("Package imports",         check_imports),
        ("SQLite schema init",       check_db),
        ("Feature engine (80 cols)", check_features),
        ("Signal scores [-1, +1]",   check_signals),
        ("Ensemble aggregator",      check_ensemble),
        ("Position sizer",           check_position_sizer),
        ("Circuit breaker",          check_circuit_breaker),
        ("yfinance data fetch",       check_yfinance),
    ]

    passed = 0
    for name, fn in checks:
        if run_check(name, fn):
            passed += 1

    print(f"\n{'=' * 40}")
    print(f"Passed: {passed}/{len(checks)}")

    if passed == len(checks):
        print("All checks passed. System ready.\n")
    else:
        print("Some checks failed. Fix errors above before running live.\n")
        sys.exit(1)
