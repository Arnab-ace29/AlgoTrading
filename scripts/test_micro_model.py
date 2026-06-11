"""
Micro XGBoost model — correctness test (TEST-01).

Rewritten from a smoke-print script into real assertions: trains the micro
entry-gate model on synthetic multi-symbol 1-min data (temp model path so the
live model isn't clobbered), and checks valid AUC/accuracy, NaN-free prepared
features, valid + varying gate predictions, and a disk round-trip.

AUC is asserted ∈ [0,1] (not > 0.5) — synthetic data has no real edge.

Run (needs xgboost + libomp):
    DYLD_FALLBACK_LIBRARY_PATH=.venv/lib/python3.9/site-packages/sklearn/.dylibs \
        .venv/bin/python scripts/test_micro_model.py
Also pytest-collectable: `pytest scripts/test_micro_model.py`.
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


def _stacked(symbols, n: int = 500, seed: int = 5) -> pd.DataFrame:
    """Per-symbol synthetic 1-min OHLCV stacked with a 'symbol' column."""
    rng = np.random.default_rng(seed)
    start = datetime(2025, 1, 1, 9, 15)
    frames = []
    for sym in symbols:
        close = 1000 * np.cumprod(1 + rng.normal(0, 0.003, n))
        idx = pd.DatetimeIndex([start + timedelta(minutes=i) for i in range(n)])
        df = pd.DataFrame({
            "open": close, "high": close * 1.002, "low": close * 0.998,
            "close": close, "volume": rng.integers(1_000, 9_000, n).astype(float),
        }, index=idx)
        df["symbol"] = sym
        frames.append(df)
    return pd.concat(frames)


def _train_model(tmp: Path):
    from signals.ml.micro_model import MicroXGBoostModel
    df = _stacked(["AAA", "BBB", "CCC"], n=500)
    m = MicroXGBoostModel(model_path=tmp / "micro.pkl")
    m.min_samples = 200
    metrics = m.train(df)
    return m, df, metrics


def test_micro_prepare_features_no_nan():
    if not _has_xgboost():
        _skip("xgboost unavailable"); return
    from signals.ml.micro_model import MicroXGBoostModel
    df = _stacked(["AAA"], n=400)
    feats = MicroXGBoostModel().prepare_features(df)
    assert len(feats) > 0 and len(feats.columns) >= 3, "no micro features produced"
    assert not feats.isna().any().any(), "prepared features contain NaN (ffill+zero expected, no bfill)"


def test_micro_trains_with_valid_metrics():
    if not _has_xgboost():
        _skip("xgboost unavailable"); return
    with tempfile.TemporaryDirectory() as t:
        m, _, metrics = _train_model(Path(t))
        assert m.is_trained, "model should be trained"
        assert "auc" in metrics and 0.0 <= metrics["auc"] <= 1.0, f"AUC not a valid prob: {metrics.get('auc')}"
        assert 0.0 <= metrics["accuracy"] <= 1.0, f"accuracy out of range: {metrics.get('accuracy')}"


def test_micro_gate_predictions_valid_and_vary():
    if not _has_xgboost():
        _skip("xgboost unavailable"); return
    with tempfile.TemporaryDirectory() as t:
        m, df, _ = _train_model(Path(t))
        sym = df[df["symbol"] == "AAA"]
        preds = []
        for end in range(120, len(sym), 11):
            r = m.predict(sym.iloc[:end])
            assert 0.0 <= r.prediction <= 1.0, f"prediction not a probability: {r.prediction}"
            assert 0.5 <= r.confidence <= 1.0, f"confidence must be ≥0.5: {r.confidence}"
            assert isinstance(r.should_enter, bool), "gate decision must be a bool"
            # gate must agree with its own threshold/probability
            assert r.should_enter == (r.prediction >= m.entry_threshold), "gate inconsistent with prediction"
            preds.append(round(r.prediction, 3))
        assert len(set(preds)) >= 2, f"predictions are constant ({set(preds)}) — model doesn't discriminate"


def test_micro_persistence_roundtrip():
    if not _has_xgboost():
        _skip("xgboost unavailable"); return
    from signals.ml.micro_model import MicroXGBoostModel
    with tempfile.TemporaryDirectory() as t:
        m, df, _ = _train_model(Path(t))
        m.save_model()
        assert (Path(t) / "micro.pkl").exists(), "model file not written"
        sym = df[df["symbol"] == "AAA"].iloc[:200]
        before = m.predict(sym).prediction
        reloaded = MicroXGBoostModel(model_path=Path(t) / "micro.pkl")
        assert reloaded.is_trained, "reloaded model should report trained"
        after = reloaded.predict(sym).prediction
        assert abs(before - after) < 1e-9, f"reloaded prediction differs: {before} vs {after}"


def main() -> int:
    print("=" * 60); print("TEST-01 — Micro XGBoost model correctness"); print("=" * 60)
    if not _has_xgboost():
        print("  ~ SKIP (xgboost unavailable)"); return 0
    tests = [test_micro_prepare_features_no_nan,
             test_micro_trains_with_valid_metrics,
             test_micro_gate_predictions_valid_and_vary,
             test_micro_persistence_roundtrip]
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
