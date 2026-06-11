"""
Macro XGBoost Model - Phase 2
Directional prediction model for 15-minute price movement.

Label: y = 1 if close[t+15min] / close[t] >= 1.001 (≥0.1% rise in 15 min), else 0
Features: All 80 technical features + regime info
Usage: Predicts bullish/bearish bias for ensemble scoring
"""

from __future__ import annotations
import os
import pickle
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
import xgboost as xgb
from sklearn.metrics import roc_auc_score, accuracy_score
from loguru import logger

from models.validation import purged_split
from config.settings import ML_GATE_MIN_AUC


@dataclass
class MacroModelResult:
    prediction: float          # Probability of bullish move (0.0 to 1.0)
    confidence: float          # Model confidence (max(prob, 1-prob))
    feature_importance: Dict[str, float]  # Top 10 features
    is_reliable: bool          # True only if model cleared the OOS AUC edge bar
    base_rate: float = 0.5     # training positive-class rate = the neutral decision point


class MacroXGBoostModel:
    """
    XGBoost model for predicting 15-minute directional price movement.
    Trained on all technical features with walk-forward validation.
    """
    
    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = model_path or Path("models/saved/macro_xgb.pkl")
        self.model: Optional[xgb.XGBClassifier] = None
        self.feature_columns: list[str] = []
        self.is_trained = False
        self.min_samples = 1000  # Minimum samples needed for reliable prediction
        self.lookahead_bars = 3  # 15-min horizon on 5-min bars; also the embargo gap
        self.val_auc: Optional[float] = None   # OOS AUC — gates the right to veto
        self.base_rate: float = 0.5            # training P(bull) — neutral decision point
        
        # Load existing model if available
        if self.model_path.exists():
            self.load_model()
    
    def create_labels(self, df: pd.DataFrame, lookahead_bars: int = 3) -> pd.Series:
        """
        Create binary labels for 15-minute directional prediction.
        3 bars of 5-minute data = 15 minutes
        
        Args:
            df: DataFrame with OHLCV data
            lookahead_bars: Number of bars to look ahead (3 for 15min)
            
        Returns:
            Series of binary labels (1 = bullish, 0 = bearish/neutral)
        """
        future_returns = df['close'].shift(-lookahead_bars) / df['close'] - 1
        labels = (future_returns >= 0.001).astype(int)  # 0.1% threshold
        
        # Remove last few rows where we can't compute future returns
        labels = labels.iloc[:-lookahead_bars]
        
        return labels
    
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare feature matrix for training/prediction.
        
        Args:
            df: DataFrame with all technical features computed
            
        Returns:
            DataFrame of features ready for XGBoost
        """
        from features.indicators import FEATURE_COLUMNS
        
        # Use the canonical feature set (already includes momentum, trend,
        # volatility, volume, multi-timeframe, session, microstructure and
        # derived features). De-duplicate while preserving order.
        seen: set[str] = set()
        feature_cols: list[str] = []
        for col in FEATURE_COLUMNS:
            if col in df.columns and col not in seen:
                feature_cols.append(col)
                seen.add(col)
        
        # Create feature matrix
        features = df[feature_cols].copy()
        
        # Remove columns that are entirely NaN (no usable data)
        valid_cols = []
        for col in feature_cols:
            if col in features.columns and features[col].notna().any():
                valid_cols.append(col)
        features = features[valid_cols]

        # Handle NaN values — forward-fill only, then zero-fill. NEVER bfill:
        # backward-filling pulls FUTURE values into earlier rows (look-ahead, ML-03).
        features = features.ffill().fillna(0.0)

        self.feature_columns = valid_cols
        return features

    def _features_for_inference(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Build a single-row feature matrix using the trained feature set.

        Rolling/derived features need history, so the full df is passed in and
        only the last row is returned. Missing columns are zero-filled so the
        matrix always matches the columns the model was trained on.
        """
        if not self.feature_columns:
            return None
        # Reindex to the exact trained columns (missing -> NaN), then fill.
        # ffill only (no bfill) — the last row has no future to borrow from anyway.
        features = df.reindex(columns=self.feature_columns)
        features = features.ffill().fillna(0.0)
        if features.empty:
            return None
        return features.tail(1)
    
    def _build_frames(self, df: pd.DataFrame) -> list:
        """
        Build per-symbol (X, y) frames with a unified feature-column set.
        Features/labels are computed within each instrument (no cross-symbol
        shift/rolling leakage) and aligned; the last `lookahead_bars` unlabelable
        rows are dropped. Sets self.feature_columns to the union across symbols.
        """
        groups = [g for _, g in df.groupby("symbol")] if "symbol" in df.columns else [df]
        raw: list = []
        for group in groups:
            if len(group) < 50:
                continue
            X = self.prepare_features(group)
            y = self.create_labels(group, self.lookahead_bars)
            n = min(len(X), len(y))
            if n < 30:
                continue
            raw.append((X.iloc[:n].reset_index(drop=True), y.iloc[:n].reset_index(drop=True)))
        if not raw:
            raise ValueError("No usable per-symbol data after feature computation")

        cols: list[str] = []
        seen: set[str] = set()
        for X, _ in raw:
            for c in X.columns:
                if c not in seen:
                    seen.add(c); cols.append(c)
        self.feature_columns = cols
        return [(X.reindex(columns=cols).fillna(0.0), y) for X, y in raw]

    def evaluate(self, df: pd.DataFrame) -> Optional[float]:
        """
        AUC of the CURRENT model on `df` (out-of-sample if df was never trained on).
        PURE: _build_frames mutates self.feature_columns, which would corrupt the
        live champion mid-evaluation, so we snapshot and restore the trained columns
        and score strictly against them.
        """
        if not self.is_trained or self.model is None or not self.feature_columns:
            return None
        trained_cols = list(self.feature_columns)
        try:
            frames = self._build_frames(df)
        except ValueError:
            return None
        finally:
            self.feature_columns = trained_cols   # never let evaluate() mutate the model
        X = pd.concat([Xi.reindex(columns=trained_cols).fillna(0.0) for Xi, _ in frames],
                      ignore_index=True)
        y = pd.concat([yi for _, yi in frames], ignore_index=True)
        if y.nunique() < 2 or X.empty:
            return None
        try:
            proba = self.model.predict_proba(X)[:, 1]
            return float(roc_auc_score(y, proba))
        except Exception:
            return None

    def train(self, df: pd.DataFrame, validation_split: float = 0.2) -> Dict[str, Any]:
        """
        Train the XGBoost model on historical data.
        
        Args:
            df: DataFrame with OHLCV and all features
            validation_split: Fraction of data for validation
            
        Returns:
            Dictionary with training metrics
        """
        logger.info("Training Macro XGBoost model...")

        # Per-symbol (X, y) frames with a unified column set (no cross-symbol leak).
        frames = self._build_frames(df)
        total = sum(len(X) for X, _ in frames)
        if total < self.min_samples:
            raise ValueError(f"Insufficient training data: {total} < {self.min_samples}")

        # Chronological per-symbol split with an embargo equal to the label horizon,
        # so validation is the latest bars and no train label peeks into validation.
        X_train, y_train, X_val, y_val = purged_split(
            frames, test_frac=validation_split, embargo=self.lookahead_bars
        )

        # Train XGBoost model (device="cuda" uses RTX GPU if available, falls back to cpu)
        self.model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            device="cuda",
            eval_metric='logloss'
        )
        
        self.model.fit(X_train, y_train, 
                      eval_set=[(X_val, y_val)],
                      verbose=False)
        
        # Evaluate
        y_pred_proba = self.model.predict_proba(X_val)[:, 1]
        y_pred = (y_pred_proba >= 0.5).astype(int)
        
        auc = roc_auc_score(y_val, y_pred_proba)
        accuracy = accuracy_score(y_val, y_pred)
        # Persist the OOS AUC (gates the veto) and the training base rate (the
        # class-imbalanced neutral point the directional gate centres on, instead
        # of a hard 0.50 that structurally blocks LONGs — see runner._passes_ml_gates).
        self.val_auc = float(auc)
        self.base_rate = float(pd.concat([y_train, y_val]).mean())

        # Feature importance
        feature_importance = dict(zip(
            self.feature_columns,
            self.model.feature_importances_
        ))
        top_features = dict(sorted(feature_importance.items(),
                                 key=lambda x: x[1], reverse=True)[:10])

        self.is_trained = True
        
        metrics = {
            'auc': auc,
            'accuracy': accuracy,
            'base_rate': self.base_rate,
            'train_samples': len(X_train),
            'val_samples': len(X_val),
            'top_features': top_features
        }

        logger.info(f"Model trained. AUC: {auc:.3f}, Accuracy: {accuracy:.3f}, "
                    f"base_rate: {self.base_rate:.3f}"
                    f"{'' if auc >= ML_GATE_MIN_AUC else ' (below gate AUC — stays advisory)'}")
        return metrics
    
    def predict(self, df: pd.DataFrame) -> MacroModelResult:
        """
        Predict directional bias for current market conditions.
        
        Args:
            df: DataFrame with latest market data and features
            
        Returns:
            MacroModelResult with prediction and metadata
        """
        # A model is only allowed to VETO once it has cleared the OOS AUC edge bar;
        # otherwise it stays advisory and the rule-based system trades unimpeded.
        reliable = (self.is_trained and self.model is not None
                    and self.val_auc is not None and self.val_auc >= ML_GATE_MIN_AUC)
        if not self.is_trained or self.model is None:
            return MacroModelResult(
                prediction=0.5,
                confidence=0.0,
                feature_importance={},
                is_reliable=False,
                base_rate=self.base_rate,
            )

        # Build inference features over full history, take the last row
        features = self._features_for_inference(df)

        if features is None or features.empty:
            return MacroModelResult(
                prediction=0.5,
                confidence=0.0,
                feature_importance={},
                is_reliable=False,
                base_rate=self.base_rate,
            )
        
        # Predict
        prediction_proba = self.model.predict_proba(features)[0, 1]  # Probability of class 1 (bullish)
        confidence = max(prediction_proba, 1 - prediction_proba)
        
        # Feature importance for this prediction
        feature_importance = dict(zip(
            self.feature_columns,
            self.model.feature_importances_
        ))
        top_features = dict(sorted(feature_importance.items(), 
                                 key=lambda x: x[1], reverse=True)[:10])
        
        return MacroModelResult(
            prediction=float(prediction_proba),
            confidence=float(confidence),
            feature_importance=top_features,
            is_reliable=reliable,
            base_rate=self.base_rate,
        )
    
    def save_model(self) -> None:
        """Save the trained model to disk."""
        if self.is_trained and self.model is not None:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.model_path.with_suffix(self.model_path.suffix + ".tmp")
            with open(tmp, 'wb') as f:
                pickle.dump({
                    'model': self.model,
                    'feature_columns': self.feature_columns,
                    'is_trained': self.is_trained,
                    'val_auc': self.val_auc,
                    'base_rate': self.base_rate,
                }, f)
            os.replace(tmp, self.model_path)   # atomic swap (safe champion promotion)
            logger.info(f"Model saved to {self.model_path}")
    
    def load_model(self) -> None:
        """Load a trained model from disk."""
        if self.model_path.exists():
            with open(self.model_path, 'rb') as f:
                data = pickle.load(f)
                self.model = data['model']
                self.feature_columns = data['feature_columns']
                self.is_trained = data['is_trained']
                self.val_auc = data.get('val_auc')
                self.base_rate = data.get('base_rate', 0.5)
            logger.info(f"Model loaded from {self.model_path} (val_auc={self.val_auc}, "
                        f"base_rate={self.base_rate:.3f})")
        else:
            logger.warning(f"No model found at {self.model_path}")


# Global model instance (singleton pattern)
_macro_model: Optional[MacroXGBoostModel] = None


def get_macro_model() -> MacroXGBoostModel:
    """Get or create the global macro model instance."""
    global _macro_model
    if _macro_model is None:
        _macro_model = MacroXGBoostModel()
    return _macro_model
