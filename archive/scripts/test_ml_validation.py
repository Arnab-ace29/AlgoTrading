"""
Tests for the ML leakage fixes (ML-01/02) and safe promotion (RETRAIN-01/02).

Covers the pure logic — split utilities + champion/challenger decision — with
stub models, so it runs without xgboost (which needs libomp on macOS):

    .venv/bin/python scripts/test_ml_validation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from models.validation import purged_split, time_holdout_split
from models.promotion import champion_challenger

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def test_purged_split():
    print("purged_split (ML-01/02):")
    # single symbol, 100 rows, 'pos' marks chronological order
    X = pd.DataFrame({"pos": range(100), "f": range(100)})
    y = pd.Series([i % 2 for i in range(100)])
    Xtr, ytr, Xva, yva = purged_split([(X, y)], test_frac=0.2, embargo=3)
    check(len(Xtr) == 77 and len(Xva) == 20, "80/20 split with 3-row embargo → 77 train, 20 val")
    check(Xtr["pos"].max() == 76, "train ends at row 76")
    check(Xva["pos"].min() == 80, "validation starts at row 80 (latest rows)")
    check(Xva["pos"].min() - Xtr["pos"].max() == 4, "embargo gap of 3 rows between train and val")

    # two symbols → pooled, val is latest-per-symbol
    X2 = pd.DataFrame({"pos": range(100), "f": range(100, 200)})
    Xtr2, _, Xva2, _ = purged_split([(X, y), (X2, y)], test_frac=0.2, embargo=0)
    check(len(Xtr2) == 160 and len(Xva2) == 40, "two symbols pool to 160 train / 40 val")


def test_time_holdout_split():
    print("time_holdout_split (RETRAIN-02):")
    idx = pd.date_range("2024-01-01", periods=60, freq="D")
    df = pd.DataFrame({"x": range(60)}, index=idx)
    fit, hold = time_holdout_split(df, holdout_days=10)
    check(len(fit) > 0 and len(hold) > 0, "splits into non-empty fit + holdout")
    check(fit.index.max() < hold.index.min(), "fit is strictly older than holdout")
    check(hold.index.min() >= idx.max() - pd.Timedelta(days=10), "holdout is the most recent ~10 days")


class _Stub:
    """Duck-typed stand-in for an ML model."""
    def __init__(self, eval_auc, is_trained=True, train_auc=0.6, model_path="live.pkl"):
        self.eval_auc = eval_auc
        self.is_trained = is_trained
        self.train_auc = train_auc
        self.model_path = model_path
        self.saved = False
        self.loaded = False

    def evaluate(self, df):
        return self.eval_auc

    def train(self, df):
        self.is_trained = True
        return {"auc": self.train_auc, "train_samples": len(df)}

    def save_model(self):
        self.saved = True

    def load_model(self):
        self.loaded = True


def _df():
    idx = pd.date_range("2024-01-01", periods=60, freq="D")
    return pd.DataFrame({"x": range(60)}, index=idx)


def test_promotion_logic():
    print("champion/challenger promotion (RETRAIN-01):")
    df = _df()

    # A) challenger better → promote
    champ = _Stub(eval_auc=0.55, is_trained=True, model_path="live.pkl")
    chal = _Stub(eval_auc=0.62, model_path="chal.pkl")
    r = champion_challenger("m", champ, lambda: chal, df, holdout_days=10)
    check(r["promoted"] is True, "challenger > champion → promoted")
    check(chal.saved and champ.loaded, "promoted: challenger saved + live reloaded")
    check(chal.model_path == champ.model_path, "challenger saved to the live model path")

    # B) challenger worse → keep champion
    champ = _Stub(eval_auc=0.60, is_trained=True, model_path="live.pkl")
    chal = _Stub(eval_auc=0.55, model_path="chal.pkl")
    r = champion_challenger("m", champ, lambda: chal, df, holdout_days=10)
    check(r["promoted"] is False, "challenger < champion → kept champion")
    check(not chal.saved and not champ.loaded, "kept: nothing saved/reloaded")

    # C) no champion yet → promote
    champ = _Stub(eval_auc=None, is_trained=False, model_path="live.pkl")
    chal = _Stub(eval_auc=0.40, model_path="chal.pkl")
    r = champion_challenger("m", champ, lambda: chal, df, holdout_days=10)
    check(r["promoted"] is True, "no champion → promote challenger")

    # D) challenger AUC unmeasurable + champion exists → keep
    champ = _Stub(eval_auc=0.58, is_trained=True, model_path="live.pkl")
    chal = _Stub(eval_auc=None, model_path="chal.pkl")
    r = champion_challenger("m", champ, lambda: chal, df, holdout_days=10)
    check(r["promoted"] is False, "unmeasurable challenger → keep champion")

    # E) challenger trains only on the FIT slice (never the holdout)
    champ = _Stub(eval_auc=0.50, is_trained=True, model_path="live.pkl")
    chal = _Stub(eval_auc=0.70, model_path="chal.pkl")
    r = champion_challenger("m", champ, lambda: chal, df, holdout_days=10)
    check(r["training_samples"] < len(df), "challenger fit on < full window (holdout excluded)")


def main() -> int:
    print("=" * 60); print("ML LEAKAGE + PROMOTION TESTS"); print("=" * 60)
    test_purged_split()
    test_time_holdout_split()
    test_promotion_logic()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
