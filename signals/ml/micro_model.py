"""
Micro XGBoost Model - Phase 2
Entry confirmation model using tick-level microstructure features.

Label: Net buying pressure in next 30 ticks (sum of signed trade volumes)
Features: 5 tick-level microstructure features
Usage: Binary gate - if micro model score < 0.45, skip entry even if macro score is high
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
class MicroModelResult:
    prediction: float          # Probability of positive buying pressure (0.0 to 1.0)
    confidence: float          # Model confidence (max(prob, 1-prob))
    should_enter: bool         # Entry gate: True if prediction >= 0.45
    is_reliable: bool          # True if model has enough data


class MicroXGBoostModel:
    """
    XGBoost model for predicting short-term buying pressure using microstructure features.
    Acts as a binary gate to prevent entries during unfavorable micro conditions.
    """
    
    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = model_path or Path("models/saved/micro_xgb.pkl")
        self.model: Optional[xgb.XGBClassifier] = None
        self.feature_columns: list[str] = []
        self.is_trained = False
        self.min_samples = 500  # Minimum samples needed for reliable prediction
        self.entry_threshold = 0.45  # Below this, skip entry
        # Label/embargo horizon in BARS. The model now trains AND serves on the
        # primary 5-min timeframe (train/serve skew fix), so this is 6 bars = 30 min
        # of forward buying pressure — an intraday horizon, not the old 30-bar
        # (=150 min) window that also leaked across the EOD boundary.
        self.lookahead_ticks = 6
        self.val_auc: Optional[float] = None   # OOS AUC — gates the right to veto
        self.train_timeframe: str = "5min"     # tf the model was trained on (serve must match)
        
        # Load existing model if available
        if self.model_path.exists():
            self.load_model()
    
    def create_microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create tick-level microstructure features from OHLCV data.
        
        Args:
            df: DataFrame with OHLCV data (can be tick-level or 1-minute)
            
        Returns:
            DataFrame with microstructure features
        """
        features = pd.DataFrame(index=df.index)
        
        # 1. Bid-ask spread estimation (using high-low as proxy)
        features['bid_ask_spread'] = (df['high'] - df['low']) / df['close']
        
        # 2. Order imbalance proxy (volume-weighted price movement)
        features['order_imbalance'] = (df['close'] - df['open']) / (df['high'] - df['low'] + 1e-8)
        
        # 3. Trade size spike (current volume vs rolling average)
        features['volume_ma20'] = df['volume'].rolling(20, min_periods=1).mean()
        features['trade_size_spike'] = df['volume'] / features['volume_ma20']
        
        # 4. Volume burst (volume acceleration)
        features['volume_burst'] = df['volume'].diff().fillna(0) / (df['volume'].rolling(5, min_periods=1).mean() + 1e-8)
        
        # 5. Tick momentum (price change acceleration)
        features['tick_momentum'] = df['close'].diff().fillna(0)
        features['tick_momentum'] = features['tick_momentum'].rolling(3, min_periods=1).mean()
        
        return features
    
    def create_labels(self, df: pd.DataFrame, lookahead_ticks: int = 30) -> pd.Series:
        """
        Create labels based on net buying pressure in next N ticks.
        
        Args:
            df: DataFrame with OHLCV data
            lookahead_ticks: Number of ticks to look ahead
            
        Returns:
            Series of binary labels (1 = positive buying pressure, 0 = negative/neutral)
        """
        # Use volume * price change as proxy for buying pressure
        price_change = df['close'].diff().fillna(0)
        buying_pressure = price_change * df['volume']
        
        # Sum over lookahead window
        future_pressure = buying_pressure.rolling(lookahead_ticks).sum().shift(-lookahead_ticks)
        
        # Binary label: 1 if positive pressure, 0 otherwise
        labels = (future_pressure > 0).astype(int)
        
        # Remove last few rows where we can't compute future pressure
        labels = labels.iloc[:-lookahead_ticks]
        
        return labels
    
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare feature matrix for training/prediction.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame of microstructure features ready for XGBoost
        """
        # Create microstructure features
        features = self.create_microstructure_features(df)

        # ffill only, then zero-fill — never bfill (pulls future values back, ML-03).
        features = features.ffill().fillna(0.0)

        self.feature_columns = list(features.columns)
        return features

    def _features_for_inference(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Single-row microstructure features over full history (last row)."""
        features = self.create_microstructure_features(df)
        features = features.ffill().fillna(0.0)
        if features.empty:
            return None
        if self.feature_columns:
            features = features.reindex(columns=self.feature_columns).fillna(0.0)
        return features.tail(1)
    
    def _build_frames(self, df: pd.DataFrame) -> list:
        """Per-symbol (X, y) microstructure frames, aligned and column-unified."""
        groups = [g for _, g in df.groupby("symbol")] if "symbol" in df.columns else [df]
        raw: list = []
        for group in groups:
            if len(group) < 50:
                continue
            X = self.prepare_features(group)
            y = self.create_labels(group, self.lookahead_ticks)
            n = min(len(X), len(y))
            if n < 30:
                continue
            raw.append((X.iloc[:n].reset_index(drop=True), y.iloc[:n].reset_index(drop=True)))
        if not raw:
            raise ValueError("No usable per-symbol data after feature computation")
        cols = list(raw[0][0].columns)
        self.feature_columns = cols
        return [(X.reindex(columns=cols).fillna(0.0), y) for X, y in raw]

    def evaluate(self, df: pd.DataFrame) -> Optional[float]:
        """AUC of the CURRENT model on `df` (out-of-sample if unseen). PURE — restores
        self.feature_columns so evaluating the champion can't corrupt it."""
        if not self.is_trained or self.model is None or not self.feature_columns:
            return None
        trained_cols = list(self.feature_columns)
        try:
            frames = self._build_frames(df)
        except ValueError:
            return None
        finally:
            self.feature_columns = trained_cols
        X = pd.concat([Xi.reindex(columns=trained_cols).fillna(0.0) for Xi, _ in frames],
                      ignore_index=True)
        y = pd.concat([yi for _, yi in frames], ignore_index=True)
        if y.nunique() < 2 or X.empty:
            return None
        try:
            return float(roc_auc_score(y, self.model.predict_proba(X)[:, 1]))
        except Exception:
            return None

    def train(self, df: pd.DataFrame, validation_split: float = 0.2) -> Dict[str, Any]:
        """
        Train the micro XGBoost model on historical data.
        
        Args:
            df: DataFrame with OHLCV data
            validation_split: Fraction of data for validation
            
        Returns:
            Dictionary with training metrics
        """
        logger.info("Training Micro XGBoost model...")

        frames = self._build_frames(df)
        total = sum(len(X) for X, _ in frames)
        if total < self.min_samples:
            raise ValueError(f"Insufficient training data: {total} < {self.min_samples}")

        # Chronological per-symbol split with embargo = label horizon (no leakage).
        X_train, y_train, X_val, y_val = purged_split(
            frames, test_frac=validation_split, embargo=self.lookahead_ticks
        )

        # Train XGBoost model (device="cuda" uses RTX GPU if available, falls back to cpu)
        self.model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=4,
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
        self.val_auc = float(auc)   # gates the right to veto (ML_GATE_MIN_AUC)

        # Feature importance
        feature_importance = dict(zip(
            self.feature_columns,
            self.model.feature_importances_
        ))

        self.is_trained = True
        
        metrics = {
            'auc': auc,
            'accuracy': accuracy,
            'train_samples': len(X_train),
            'val_samples': len(X_val),
            'feature_importance': feature_importance
        }
        
        logger.info(f"Micro model trained. AUC: {auc:.3f}, Accuracy: {accuracy:.3f}")
        return metrics
    
    def predict(self, df: pd.DataFrame) -> MicroModelResult:
        """
        Predict short-term buying pressure for entry confirmation.
        
        Args:
            df: DataFrame with latest market data
            
        Returns:
            MicroModelResult with prediction and entry gate decision
        """
        if not self.is_trained or self.model is None:
            return MicroModelResult(
                prediction=0.5,
                confidence=0.0,
                should_enter=False,
                is_reliable=False
            )
        
        # Build inference features over full history, take the last row
        features = self._features_for_inference(df)
        
        if features is None or features.empty:
            return MicroModelResult(
                prediction=0.5,
                confidence=0.0,
                should_enter=False,
                is_reliable=False
            )
        
        # Predict
        prediction_proba = self.model.predict_proba(features)[0, 1]  # Probability of positive pressure
        confidence = max(prediction_proba, 1 - prediction_proba)
        # Cast to a Python bool — `np_float >= float` yields numpy.bool_, which
        # breaks the dataclass's `bool` contract and json.dumps downstream.
        should_enter = bool(prediction_proba >= self.entry_threshold)
        # Only veto once the model has cleared the OOS AUC edge bar.
        reliable = self.val_auc is not None and self.val_auc >= ML_GATE_MIN_AUC

        return MicroModelResult(
            prediction=float(prediction_proba),
            confidence=float(confidence),
            should_enter=should_enter,
            is_reliable=reliable,
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
                    'entry_threshold': self.entry_threshold,
                    'val_auc': self.val_auc,
                    'train_timeframe': self.train_timeframe,
                }, f)
            os.replace(tmp, self.model_path)   # atomic swap
            logger.info(f"Micro model saved to {self.model_path}")
    
    def load_model(self) -> None:
        """Load a trained model from disk."""
        if self.model_path.exists():
            with open(self.model_path, 'rb') as f:
                data = pickle.load(f)
                self.model = data['model']
                self.feature_columns = data['feature_columns']
                self.is_trained = data['is_trained']
                self.entry_threshold = data.get('entry_threshold', 0.45)
                self.val_auc = data.get('val_auc')
                self.train_timeframe = data.get('train_timeframe', '5min')
            logger.info(f"Micro model loaded from {self.model_path} "
                        f"(val_auc={self.val_auc}, tf={self.train_timeframe})")
        else:
            logger.warning(f"No micro model found at {self.model_path}")


# Global model instance (singleton pattern)
_micro_model: Optional[MicroXGBoostModel] = None


def get_micro_model() -> MicroXGBoostModel:
    """Get or create the global micro model instance."""
    global _micro_model
    if _micro_model is None:
        _micro_model = MicroXGBoostModel()
    return _micro_model
