"""
Macro XGBoost model — correctness test (TEST-01).

Rewritten from a smoke-print script into real assertions: trains on synthetic
multi-symbol data (with a temp model path so the live model isn't clobbered),
and checks that training returns a valid AUC/accuracy, predictions are valid
probabilities that VARY across inputs, and the model round-trips through disk.

We assert AUC ∈ [0,1] (not AUC > 0.5): the synthetic data has no real edge, so
demanding > 0.5 would be a flaky test. "Predictions vary" is the meaningful
discrimination check on random data.

Run (needs xgboost + libomp):
    DYLD_FALLBACK_LIBRARY_PATH=.venv/lib/python3.9/site-packages/sklearn/.dylibs \
        .venv/bin/python scripts/test_macro_model.py
Also pytest-collectable: `pytest scripts/test_macro_model.py`.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

try:                          # pytest is optional — only used to mark skips under collection
    import pytest
except ImportError:
    pytest = None


def _skip(reason: str):
    """Skip under pytest; a no-op for standalone runs (main() guards separately)."""
    if pytest is not None:
        pytest.skip(reason)


def _has_xgboost() -> bool:
    try:
        import xgboost  # noqa: F401
        return True
    except Exception:
        return False


def _stacked(symbols, n: int = 320, seed: int = 11) -> pd.DataFrame:
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


def _train_model(tmp: Path):
    from signals.ml.macro_model import MacroXGBoostModel
    df = _stacked(["AAA", "BBB", "CCC", "DDD", "EEE"], n=320)
    m = MacroXGBoostModel(model_path=tmp / "macro.pkl")
    m.min_samples = 200
    metrics = m.train(df)
    return m, df, metrics


def test_macro_trains_with_valid_metrics():
    if not _has_xgboost():
        _skip("xgboost unavailable"); return
    with tempfile.TemporaryDirectory() as t:
        m, _, metrics = _train_model(Path(t))
        assert m.is_trained, "model should be trained"
        assert "auc" in metrics and 0.0 <= metrics["auc"] <= 1.0, f"AUC not a valid prob: {metrics.get('auc')}"
        assert 0.0 <= metrics["accuracy"] <= 1.0, f"accuracy out of range: {metrics.get('accuracy')}"
        assert metrics["train_samples"] > 0 and metrics["val_samples"] > 0, "empty train/val split"
        assert len(m.feature_columns) > 10, f"too few feature columns: {len(m.feature_columns)}"


def test_macro_predictions_valid_and_vary():
    if not _has_xgboost():
        _skip("xgboost unavailable"); return
    with tempfile.TemporaryDirectory() as t:
        m, df, _ = _train_model(Path(t))
        sym = df[df["symbol"] == "AAA"]
        preds = []
        # Predict on many distinct trailing windows → distinct feature rows.
        for end in range(60, len(sym), 7):
            r = m.predict(sym.iloc[:end])
            assert 0.0 <= r.prediction <= 1.0, f"prediction not a probability: {r.prediction}"
            assert 0.5 <= r.confidence <= 1.0, f"confidence = max(p,1-p) must be ≥0.5: {r.confidence}"
            assert isinstance(r.is_reliable, bool)
            preds.append(round(r.prediction, 3))
        assert len(preds) >= 5, "not enough prediction samples"
        assert len(set(preds)) >= 2, f"predictions are constant ({set(preds)}) — model doesn't discriminate"


def test_macro_persistence_roundtrip():
    if not _has_xgboost():
        _skip("xgboost unavailable"); return
    from signals.ml.macro_model import MacroXGBoostModel
    with tempfile.TemporaryDirectory() as t:
        m, df, _ = _train_model(Path(t))
        m.save_model()
        assert (Path(t) / "macro.pkl").exists(), "model file not written"
        sym = df[df["symbol"] == "AAA"].iloc[:120]
        before = m.predict(sym).prediction

        reloaded = MacroXGBoostModel(model_path=Path(t) / "macro.pkl")
        assert reloaded.is_trained, "reloaded model should report trained"
        after = reloaded.predict(sym).prediction
        assert abs(before - after) < 1e-9, f"reloaded prediction differs: {before} vs {after}"


def main() -> int:
    print("=" * 60); print("TEST-01 — Macro XGBoost model correctness"); print("=" * 60)
    if not _has_xgboost():
        print("  ~ SKIP (xgboost unavailable)"); return 0
    tests = [test_macro_trains_with_valid_metrics,
             test_macro_predictions_valid_and_vary,
             test_macro_persistence_roundtrip]
    p = f = 0
    for fn in tests:
        try:
            fn(); p += 1; print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            f += 1; print(f"  ✗ {fn.__name__}: {e}")
    print("=" * 60); print(f"PASS={p}  FAIL={f}"); print("=" * 60)
    return 1 if f else 0


if __name__ == "__main__":
    raise SystemExit(main())
