"""
ML gate edge-bar regression: a model may VETO live entries only once it has
demonstrated a minimum out-of-sample AUC (config.ML_GATE_MIN_AUC). A trained-but-
no-edge model must stay advisory (is_reliable=False) so the rule-based system
keeps trading. Also checks the macro gate centres on the training base rate.

Uses a stub estimator (predict_proba) — no xgboost / heavy training needed.

    .venv/bin/python scripts/test_ml_gate_edge.py
    pytest scripts/test_ml_gate_edge.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from config.settings import ML_GATE_MIN_AUC
from signals.ml.macro_model import MacroXGBoostModel

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


class _Stub:
    """Minimal estimator: always predicts P(class1)=p."""
    def __init__(self, p):
        self.p = p
        self.feature_importances_ = np.array([1.0])
    def predict_proba(self, X):
        n = len(X)
        return np.column_stack([np.full(n, 1 - self.p), np.full(n, self.p)])


def _macro_with(val_auc, base_rate=0.5, p=0.6):
    m = MacroXGBoostModel(model_path=Path("/tmp/nonexistent_macro.pkl"))
    m.model = _Stub(p)
    m.feature_columns = ["rsi_14"]
    m.is_trained = True
    m.val_auc = val_auc
    m.base_rate = base_rate
    return m


def test_edge_bar():
    print("ML-GATE — no-edge model stays advisory, real-edge model can veto:")
    df = pd.DataFrame({"rsi_14": np.linspace(40, 60, 80)})

    weak = _macro_with(val_auc=0.50)        # coin flip
    check(not weak.predict(df).is_reliable, f"AUC 0.50 (<{ML_GATE_MIN_AUC}) → advisory (no veto)")

    strong = _macro_with(val_auc=0.61)
    check(strong.predict(df).is_reliable, f"AUC 0.61 (>={ML_GATE_MIN_AUC}) → reliable (may veto)")

    untrained = MacroXGBoostModel(model_path=Path("/tmp/nonexistent_macro2.pkl"))
    check(not untrained.predict(df).is_reliable, "untrained model is never reliable")


def test_base_rate_exposed():
    print("ML-GATE — macro result carries the training base rate (gate neutral point):")
    m = _macro_with(val_auc=0.60, base_rate=0.42, p=0.45)
    res = m.predict(df=pd.DataFrame({"rsi_14": np.linspace(40, 60, 80)}))
    check(abs(res.base_rate - 0.42) < 1e-9, f"base_rate surfaced ({res.base_rate})")
    # With base_rate 0.42, a P(bull)=0.45 is ABOVE neutral → would NOT block a LONG,
    # whereas a hard-0.50 cut would have wrongly blocked it.
    check(res.prediction > res.base_rate, "P(bull) above base rate → LONG not structurally blocked")


def main() -> int:
    print("=" * 60); print("ML GATE EDGE-BAR TESTS"); print("=" * 60)
    test_edge_bar()
    test_base_rate_exposed()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
