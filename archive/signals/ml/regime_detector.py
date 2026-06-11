"""
Regime Detector - Phase 2
Identifies market regimes to adjust signal weights dynamically.

Regimes:
- TRENDING_UP: ADX > 25, EMA slope positive, price above all EMAs
- TRENDING_DOWN: ADX > 25, EMA slope negative, price below all EMAs  
- MEAN_REVERTING: ADX < 20, RSI oscillating 30-70, low ATR percentile
- CHOPPY: High ATR percentile but no trend, whipsawing EMAs

Implementation: Rule-based decision tree (fastest, most interpretable)
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Literal
from dataclasses import dataclass


RegimeType = Literal["TRENDING_UP", "TRENDING_DOWN", "MEAN_REVERTING", "CHOPPY"]


def _safe_float(value, default: float) -> float:
    """Return float(value) unless it is None/NaN, in which case return default."""
    try:
        if value is None:
            return default
        f = float(value)
        if np.isnan(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


@dataclass
class RegimeState:
    regime: RegimeType
    confidence: float  # 0.0 to 1.0
    adx: float
    atr_percentile: float  # 0.0 to 1.0 (matches features.indicators 'atr_percentile')
    rsi_avg: float
    ema_spread: float


class RegimeDetector:
    """Rule-based regime classifier using technical indicators.

    Expects a feature-enriched DataFrame from features.indicators.compute_all_features.
    Note: 'atr_percentile' is on a 0.0-1.0 scale (rolling rank), NOT 0-100.
    """
    
    def __init__(self, 
                 adx_threshold: float = 25.0,
                 adx_low_threshold: float = 20.0,
                 atr_percentile_high: float = 0.80,
                 atr_percentile_low: float = 0.30,
                 rsi_mean_rev_min: float = 30.0,
                 rsi_mean_rev_max: float = 70.0):
        self.adx_threshold = adx_threshold
        self.adx_low_threshold = adx_low_threshold
        self.atr_percentile_high = atr_percentile_high
        self.atr_percentile_low = atr_percentile_low
        self.rsi_mean_rev_min = rsi_mean_rev_min
        self.rsi_mean_rev_max = rsi_mean_rev_max
    
    def detect_regime(self, df: pd.DataFrame, symbol: str) -> RegimeState:
        """
        Detect current market regime for a symbol.
        
        Args:
            df: DataFrame with price data and computed features
            symbol: Symbol name for logging
            
        Returns:
            RegimeState with detected regime and confidence
        """
        if len(df) < 60:
            return RegimeState(
                regime="CHOPPY",
                confidence=0.0,
                adx=0.0,
                atr_percentile=0.5,
                rsi_avg=50.0,
                ema_spread=0.0
            )
        
        # Get latest values (handle NaN with sensible neutral defaults)
        latest = df.iloc[-1]
        adx = _safe_float(latest.get('adx_14'), 20.0)
        atr_percentile = _safe_float(latest.get('atr_percentile'), 0.5)
        rsi = _safe_float(latest.get('rsi_14'), 50.0)
        rsi_avg = _safe_float(df['rsi_14'].rolling(20).mean().iloc[-1], rsi) if 'rsi_14' in df.columns else 50.0
        
        # EMA spread analysis (NaN-safe; fall back to close during warm-up)
        close = _safe_float(latest.get('close'), 0.0)
        ema9 = _safe_float(latest.get('ema_9'), close)
        ema20 = _safe_float(latest.get('ema_20'), close)
        ema50 = _safe_float(latest.get('ema_50'), close)
        
        # EMA slope (3-period slope)
        if len(df) >= 3 and 'ema_20' in df.columns:
            ema20_slope = (ema20 - _safe_float(df['ema_20'].iloc[-3], ema20)) / 3
            ema50_slope = (ema50 - _safe_float(df['ema_50'].iloc[-3], ema50)) / 3
        else:
            ema20_slope = 0.0
            ema50_slope = 0.0
        
        # Price vs EMAs
        above_ema9 = close > ema9
        above_ema20 = close > ema20
        above_ema50 = close > ema50
        
        # EMA spread (how aligned are EMAs) — percentage spread, guard div-by-zero
        ema_spread = ((ema9 - ema50) / ema50 * 100) if ema50 else 0.0
        
        # Rule-based decision tree
        regime = "CHOPPY"
        confidence = 0.5
        
        # Strong trending conditions
        if adx > self.adx_threshold:
            if above_ema9 and above_ema20 and above_ema50 and ema20_slope > 0 and ema50_slope > 0:
                regime = "TRENDING_UP"
                confidence = min(0.9, 0.6 + (adx - self.adx_threshold) / 20.0)
            elif not above_ema9 and not above_ema20 and not above_ema50 and ema20_slope < 0 and ema50_slope < 0:
                regime = "TRENDING_DOWN"
                confidence = min(0.9, 0.6 + (adx - self.adx_threshold) / 20.0)
        
        # Mean reversion conditions
        elif adx < self.adx_low_threshold:
            if (atr_percentile < self.atr_percentile_low and 
                self.rsi_mean_rev_min <= rsi_avg <= self.rsi_mean_rev_max):
                regime = "MEAN_REVERTING"
                confidence = min(0.8, 0.5 + (self.adx_low_threshold - adx) / 10.0)
        
        # Choppy conditions (high volatility but no trend)
        elif atr_percentile > self.atr_percentile_high:
            regime = "CHOPPY"
            confidence = min(0.8, 0.5 + (atr_percentile - self.atr_percentile_high) / 20.0)
        
        return RegimeState(
            regime=regime,
            confidence=confidence,
            adx=adx,
            atr_percentile=atr_percentile,
            rsi_avg=rsi_avg,
            ema_spread=ema_spread
        )
    
    def get_regime_weights(self, regime: RegimeType) -> dict[str, float]:
        """
        Get regime-specific signal weights.
        
        Args:
            regime: Current market regime
            
        Returns:
            Dictionary of signal weights for the regime
        """
        # From roadmap: REGIME_WEIGHT_MAP
        regime_weights = {
            "TRENDING_UP": {
                "vwap_breakout": 0.50,
                "rsi_momentum": 0.40,
                "mean_reversion": 0.10,
            },
            "TRENDING_DOWN": {
                "vwap_breakout": 0.50,
                "rsi_momentum": 0.40,
                "mean_reversion": 0.10,
            },
            "MEAN_REVERTING": {
                "vwap_breakout": 0.10,
                "rsi_momentum": 0.20,
                "mean_reversion": 0.70,
            },
            "CHOPPY": {
                "vwap_breakout": 0.33,
                "rsi_momentum": 0.33,
                "mean_reversion": 0.34,
            }
        }
        
        return regime_weights.get(regime, regime_weights["CHOPPY"])
    
    def get_regime_bonus(self, regime: RegimeType) -> float:
        """
        Get regime bonus for ensemble score.
        
        Args:
            regime: Current market regime
            
        Returns:
            Bonus score to add to ensemble
        """
        # From roadmap: REGIME_BONUS_MAP
        regime_bonuses = {
            "TRENDING_UP": 0.05,
            "TRENDING_DOWN": 0.03,
            "MEAN_REVERTING": 0.0,
            "CHOPPY": -0.05,  # penalize in choppy markets
        }
        
        return regime_bonuses.get(regime, 0.0)
