"""
Ensemble Aggregator
Combines scores from all active signals into a single composite score.

Phase 1 formula:
  composite = Σ (signal_score × weight) × regime_multiplier
  direction = LONG if composite >= threshold, SHORT if <= -threshold, else NEUTRAL

Regime adjustment: weights shift based on detected market regime.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from loguru import logger

from signals.base import BaseSignal, SignalResult, Direction, Regime
from signals.ml.regime_detector import RegimeDetector
from config.settings import (
    SIGNAL_WEIGHTS, REGIME_WEIGHT_MAP,
    SCORE_THRESHOLD_ENTRY,
)


@dataclass
class EnsembleResult:
    symbol:          str
    composite_score: float          # [-1.0, +1.0]
    direction:       Direction
    regime:          Regime
    signal_scores:   dict[str, float]   # per-signal scores for transparency
    weights_used:    dict[str, float]   # effective weights after regime adjustment
    actionable:      bool               # composite_score >= SCORE_THRESHOLD_ENTRY
    notes:           str = ""

    def to_dict(self) -> dict:
        return {
            "symbol":          self.symbol,
            "composite_score": round(self.composite_score, 4),
            "direction":       self.direction.value,
            "regime":          self.regime.value,
            "signal_scores":   {k: round(v, 4) for k, v in self.signal_scores.items()},
            "weights_used":    {k: round(v, 4) for k, v in self.weights_used.items()},
            "actionable":      self.actionable,
            "notes":           self.notes,
        }


class EnsembleAggregator:
    """
    Weighted ensemble of signals with regime-based weight adjustment.
    Instantiate once, call .compute() on each bar for each symbol.
    """

    def __init__(
        self,
        signals:      Optional[list[BaseSignal]] = None,
        weights:      Optional[dict[str, float]] = None,
        regime_map:   Optional[dict[str, dict[str, float]]] = None,
        entry_threshold: float = SCORE_THRESHOLD_ENTRY,
        regime_detector: Optional[RegimeDetector] = None,
    ):
        self.signals          = signals or _build_default_signals()
        self.base_weights     = weights or dict(SIGNAL_WEIGHTS)
        self.regime_map       = regime_map or dict(REGIME_WEIGHT_MAP)
        self.entry_threshold  = entry_threshold
        self.regime_detector  = regime_detector or RegimeDetector()

        # Validate weights sum to ~1.0
        total = sum(self.base_weights.values())
        if not 0.95 <= total <= 1.05:
            logger.warning(f"Signal weights sum to {total:.2f} (expected ~1.0)")

        # Map signal name → signal object for fast lookup
        self._signal_map: dict[str, BaseSignal] = {s.name: s for s in self.signals}

    def _detect_regime(self, df: pd.DataFrame, symbol: str) -> Regime:
        """
        Classify market regime using the enhanced RegimeDetector.
        """
        regime_state = self.regime_detector.detect_regime(df, symbol)
        
        # Convert RegimeType to Regime enum
        regime_mapping = {
            "TRENDING_UP": Regime.TRENDING_UP,
            "TRENDING_DOWN": Regime.TRENDING_DOWN,
            "MEAN_REVERTING": Regime.MEAN_REVERTING,
            "CHOPPY": Regime.CHOPPY,
        }
        
        return regime_mapping.get(regime_state.regime, Regime.CHOPPY)

    def compute(
        self,
        df: pd.DataFrame,
        symbol: str,
        regime: Regime = Regime.UNKNOWN,
    ) -> EnsembleResult:
        """
        Compute composite score for a symbol using the current bar's features.
        df: feature-enriched OHLCV DataFrame (from features/indicators.py)
        regime: current regime classification. If UNKNOWN, auto-detected from df.
        """
        # Auto-detect regime if not provided
        if regime == Regime.UNKNOWN:
            regime = self._detect_regime(df, symbol)

        signal_scores: dict[str, float] = {}
        weights_used:  dict[str, float] = {}

        # Get regime-adjusted weights
        if regime != Regime.UNKNOWN and regime.value in self.regime_map:
            active_weights = self.regime_map[regime.value]
        else:
            active_weights = self.base_weights

        composite = 0.0
        total_weight = 0.0

        for signal in self.signals:
            if signal.shadow_mode:
                # Shadow mode: compute but don't contribute to ensemble
                try:
                    signal.compute(df, symbol)
                except Exception:
                    pass
                continue

            weight = active_weights.get(signal.name, self.base_weights.get(signal.name, 0.0))
            if weight == 0.0:
                continue

            try:
                result: SignalResult = signal.compute(df, symbol)
                signal_scores[signal.name] = result.score
                weights_used[signal.name]  = weight
                composite += result.score * weight
                total_weight += weight
            except Exception as e:
                logger.warning(f"Signal {signal.name} failed for {symbol}: {e}")
                signal_scores[signal.name] = 0.0

        # Normalize over the weights of signals that actually contributed, so a
        # failed/disabled signal doesn't silently re-weight the ensemble (AGG-02).
        if total_weight > 0:
            composite /= total_weight

        # Apply the regime bonus to the MAGNITUDE in the direction of the
        # composite — never as a raw additive offset, which could flip the sign
        # of a weak signal near zero (AGG-01). A penalty (negative bonus) shrinks
        # magnitude but is floored at 0, so it can reduce conviction to neutral
        # but never invert long↔short.
        regime_bonus = self.regime_detector.get_regime_bonus(regime.value)
        sign = 1.0 if composite > 0 else (-1.0 if composite < 0 else 0.0)
        if sign != 0.0:
            magnitude = max(0.0, abs(composite) + regime_bonus)
            composite = sign * magnitude

        composite = float(max(-1.0, min(1.0, composite)))

        if composite >= self.entry_threshold:
            direction = Direction.LONG
        elif composite <= -self.entry_threshold:
            direction = Direction.SHORT
        else:
            direction = Direction.NEUTRAL

        return EnsembleResult(
            symbol=symbol,
            composite_score=composite,
            direction=direction,
            regime=regime,
            signal_scores=signal_scores,
            weights_used=weights_used,
            actionable=(abs(composite) >= self.entry_threshold),
        )

    def update_weights(self, new_weights: dict[str, float]) -> None:
        """Update signal weights at runtime (e.g., from dashboard slider)."""
        self.base_weights.update(new_weights)

    def set_signal_enabled(self, signal_name: str, enabled: bool) -> None:
        """Enable or disable a signal via dashboard toggle."""
        if signal_name in self._signal_map:
            self._signal_map[signal_name].shadow_mode = not enabled


def _build_default_signals() -> list[BaseSignal]:
    """Import and instantiate all Phase 1 signals."""
    from signals.technical.vwap_breakout  import VWAPBreakoutSignal
    from signals.technical.rsi_momentum   import RSIMomentumSignal
    from signals.technical.mean_reversion import MeanReversionSignal
    return [
        VWAPBreakoutSignal(),
        RSIMomentumSignal(),
        MeanReversionSignal(),
    ]
