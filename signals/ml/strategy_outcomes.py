"""
Strategy Outcome Models - Phase 2

One XGBClassifier per strategy that predicts P(WIN) from the market features
present at the moment of entry. Acts as a final gate: only enter if the
outcome model gives >= win_threshold probability of a winning trade.

Needs at least MIN_TRADES_PER_STRATEGY labelled trades for a strategy before
it becomes active. Until then, the gate is open (returns should_enter=True).
"""

from __future__ import annotations
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score, accuracy_score
from loguru import logger

from config.settings import ML_GATE_MIN_AUC


@dataclass
class OutcomeResult:
    strategy: str
    win_probability: float
    should_enter: bool
    is_reliable: bool


class StrategyOutcomeModels:
    """
    Holds one XGBoost win/loss classifier per strategy name.

    Models are keyed by strategy (e.g. "vwap_breakout"). Each is trained on the
    feature vector at entry with a binary WIN label from the trade_log.
    """

    MIN_TRADES_PER_STRATEGY = 15

    def __init__(self,
                 model_path: Optional[Path] = None,
                 win_threshold: float = 0.55):
        self.model_path = model_path or Path("models/saved/strategy_outcomes.pkl")
        self.win_threshold = win_threshold
        # strategy -> {"model": XGBClassifier, "features": list[str]}
        self.models: Dict[str, Dict[str, Any]] = {}
        if self.model_path.exists():
            self.load_model()

    def _prepare_xy(self, df: pd.DataFrame, feature_cols: list[str]):
        """Build (X, y) from a per-strategy trade feature frame.

        df must contain the feature columns plus a 'win' column (1/0).
        """
        cols = [c for c in feature_cols if c in df.columns]
        # Each row is an independent entry snapshot — impute missing with 0, never
        # ffill/bfill across unrelated trades (that would borrow other trades' values).
        X = df[cols].fillna(0.0)
        y = df["win"].astype(int)
        return X, y, cols

    def train_strategy(self,
                       strategy: str,
                       trades_features: pd.DataFrame,
                       feature_cols: list[str]) -> Optional[Dict[str, Any]]:
        """
        Train the outcome model for one strategy.

        trades_features: one row per closed trade, with feature columns and a
                         'win' column. Returns metrics dict, or None if there
                         is not enough data.
        """
        if len(trades_features) < self.MIN_TRADES_PER_STRATEGY:
            logger.info(
                f"{strategy}: only {len(trades_features)} trades "
                f"(<{self.MIN_TRADES_PER_STRATEGY}) — skipping outcome model"
            )
            return None

        # Trades are temporally ordered events — sort by entry time so the holdout
        # is the MOST RECENT trades, never a random shuffle that leaks the future (ML-02).
        df = trades_features
        if "entry_time" in df.columns:
            df = df.sort_values("entry_time")

        X, y, cols = self._prepare_xy(df, feature_cols)

        # Need both classes present to train a classifier.
        if y.nunique() < 2:
            logger.warning(f"{strategy}: only one outcome class present — skipping")
            return None

        # Chronological holdout (no shuffle): train on older trades, validate on recent.
        cut = min(max(int(len(X) * 0.75), 1), len(X) - 1)
        X_train, X_val = X.iloc[:cut], X.iloc[cut:]
        y_train, y_val = y.iloc[:cut], y.iloc[cut:]
        if y_train.nunique() < 2:
            logger.warning(f"{strategy}: train split is single-class after time-ordering — skipping")
            return None

        model = xgb.XGBClassifier(
            n_estimators=120, max_depth=4, learning_rate=0.08,
            subsample=0.9, colsample_bytree=0.9, random_state=42,
            n_jobs=-1, eval_metric="logloss",
        )
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        proba = model.predict_proba(X_val)[:, 1]
        try:
            auc = roc_auc_score(y_val, proba)
        except ValueError:
            auc = float("nan")
        acc = accuracy_score(y_val, (proba >= 0.5).astype(int))

        self.models[strategy] = {"model": model, "features": cols, "auc": float(auc)}
        logger.info(f"{strategy}: outcome model trained (AUC={auc:.3f}, acc={acc:.3f}, n={len(X)})"
                    f"{'' if (auc == auc and auc >= ML_GATE_MIN_AUC) else ' — below gate AUC, advisory only'}")
        return {"strategy": strategy, "auc": auc, "accuracy": acc, "n_trades": len(X)}

    def predict(self, strategy: str, feature_row: pd.DataFrame) -> OutcomeResult:
        """
        Predict P(WIN) for a strategy given the latest feature row.

        If no model exists for the strategy yet, the gate is open (enter).
        """
        entry = self.models.get(strategy)
        if entry is None:
            return OutcomeResult(strategy, 0.5, True, is_reliable=False)

        model, cols = entry["model"], entry["features"]
        X = feature_row.reindex(columns=cols).fillna(0.0).tail(1)
        if X.empty:
            return OutcomeResult(strategy, 0.5, True, is_reliable=False)

        # Only veto once this strategy's model cleared the OOS AUC edge bar.
        auc = entry.get("auc")
        reliable = auc is not None and auc == auc and auc >= ML_GATE_MIN_AUC  # auc==auc rejects NaN

        win_prob = float(model.predict_proba(X)[0, 1])
        return OutcomeResult(
            strategy=strategy,
            win_probability=win_prob,
            should_enter=win_prob >= self.win_threshold,
            is_reliable=reliable,
        )

    # ── Persistence ───────────────────────────────────────────────────────
    def save_model(self) -> None:
        if self.models:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.model_path, "wb") as f:
                pickle.dump({"models": self.models, "win_threshold": self.win_threshold}, f)
            logger.info(f"Strategy outcome models saved to {self.model_path}")

    def load_model(self) -> None:
        if self.model_path.exists():
            with open(self.model_path, "rb") as f:
                data = pickle.load(f)
            self.models = data["models"]
            self.win_threshold = data.get("win_threshold", self.win_threshold)
            logger.info(f"Strategy outcome models loaded from {self.model_path}")


_outcome_models: Optional[StrategyOutcomeModels] = None


def get_outcome_models() -> StrategyOutcomeModels:
    global _outcome_models
    if _outcome_models is None:
        _outcome_models = StrategyOutcomeModels()
    return _outcome_models
