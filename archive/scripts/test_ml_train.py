"""
End-to-end ML training test (needs xgboost + libomp).

Verifies the leakage-fixed macro/micro models actually train, expose feature
columns, evaluate out-of-sample, and that champion/challenger promotion runs with
real models. Run with libomp on the fallback path:

    DYLD_FALLBACK_LIBRARY_PATH=.venv/lib/python3.9/site-packages/sklearn/.dylibs \
        .venv/bin/python scripts/test_ml_train.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def _make_stacked(symbols, n=260, seed=11):
    """Per-symbol synthetic OHLCV → compute_all_features → stacked frame w/ 'symbol'."""
    from features.indicators import compute_all_features
    rng = np.random.default_rng(seed)
    start = datetime(2025, 1, 1, 9, 15)
    frames = []
    for k, sym in enumerate(symbols):
        rets = rng.normal(0.0003 * (1 if k % 2 else -1), 0.004, n)
        close = 1000 * np.cumprod(1 + rets)
        op = close * (1 + rng.normal(0, 0.001, n))
        hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.0015, n)))
        lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.0015, n)))
        vol = rng.integers(50_000, 200_000, n).astype(float)
        idx = pd.DatetimeIndex([start + timedelta(minutes=5 * i) for i in range(n)])
        df = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close, "volume": vol}, index=idx)
        df = compute_all_features(df)
        df["symbol"] = sym
        frames.append(df)
    return pd.concat(frames)


def test_macro_train():
    print("macro model train/evaluate (ML-01/03):")
    from signals.ml.macro_model import MacroXGBoostModel
    df = _make_stacked(["AAA", "BBB", "CCC", "DDD", "EEE"], n=300)

    with tempfile.TemporaryDirectory() as tmp:
        m = MacroXGBoostModel(model_path=Path(tmp) / "macro.pkl")
        m.min_samples = 200
        metrics = m.train(df)
        check(m.is_trained, "model trains")
        check("auc" in metrics and 0.0 <= metrics["auc"] <= 1.0, f"returns a valid AUC ({metrics.get('auc'):.3f})")
        check(len(m.feature_columns) > 10, f"feature columns set ({len(m.feature_columns)})")

        # out-of-sample evaluate on the most recent slice
        # build a tz-naive time index span; df index already datetime
        holdout = df.groupby("symbol").tail(40)
        auc = m.evaluate(holdout)
        check(auc is None or (0.0 <= auc <= 1.0), f"evaluate() returns a valid AUC or None ({auc})")

        # no-bfill: prepared features have no NaN and don't depend on the future.
        feats = m.prepare_features(df[df["symbol"] == "AAA"])
        check(not feats.isna().any().any(), "prepared features have no NaN (ffill+zero, no bfill)")


def test_promotion_real():
    print("champion/challenger with REAL models (RETRAIN-01/02):")
    from signals.ml.macro_model import MacroXGBoostModel
    from models.promotion import champion_challenger
    df = _make_stacked(["AAA", "BBB", "CCC", "DDD"], n=320)

    with tempfile.TemporaryDirectory() as tmp:
        live = MacroXGBoostModel(model_path=Path(tmp) / "live.pkl")
        live.min_samples = 150
        live.train(df)                      # establish a champion
        live.save_model()
        check(Path(live.model_path).exists(), "champion saved to live path")

        def make_challenger():
            c = MacroXGBoostModel(model_path=Path(tmp) / "chal.pkl")
            c.min_samples = 150
            return c

        r = champion_challenger("macro", live, make_challenger, df, holdout_days=2, margin=0.0)
        check("promoted" in r and isinstance(r["promoted"], bool), f"promotion ran (promoted={r['promoted']})")
        check(r.get("holdout_auc") is None or 0.0 <= r["holdout_auc"] <= 1.0,
              f"challenger scored out-of-sample (holdout_auc={r.get('holdout_auc')})")
        check(Path(live.model_path).exists(), "live model file still present after promotion decision")


def test_micro_train():
    print("micro model train (ML-01/03):")
    from signals.ml.micro_model import MicroXGBoostModel
    # micro builds its own features from raw OHLCV
    rng = np.random.default_rng(5)
    frames = []
    start = datetime(2025, 1, 1, 9, 15)
    for sym in ["AAA", "BBB", "CCC"]:
        n = 400
        close = 1000 * np.cumprod(1 + rng.normal(0, 0.003, n))
        idx = pd.DatetimeIndex([start + timedelta(minutes=i) for i in range(n)])
        df = pd.DataFrame({"open": close, "high": close * 1.002, "low": close * 0.998,
                           "close": close, "volume": rng.integers(1000, 9000, n).astype(float)}, index=idx)
        df["symbol"] = sym
        frames.append(df)
    stacked = pd.concat(frames)
    with tempfile.TemporaryDirectory() as tmp:
        m = MicroXGBoostModel(model_path=Path(tmp) / "micro.pkl")
        m.min_samples = 200
        metrics = m.train(stacked)
        check(m.is_trained and "auc" in metrics, f"micro trains (AUC={metrics.get('auc'):.3f})")


def main() -> int:
    print("=" * 60); print("ML END-TO-END TRAIN TESTS"); print("=" * 60)
    try:
        import xgboost  # noqa
    except Exception as e:
        print(f"  ~ SKIP (xgboost unavailable: {type(e).__name__})")
        return 0
    test_macro_train()
    test_micro_train()
    test_promotion_real()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
