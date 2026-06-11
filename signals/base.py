"""
BaseSignal — abstract interface that every signal must implement.

All signals return a score in [-1.0, +1.0]:
  +1.0 = maximum long conviction
  -1.0 = maximum short conviction
   0.0 = no opinion / neutral

Signals also report:
  - direction: LONG / SHORT / NEUTRAL
  - confidence: 0.0–1.0 (abs value of score)
  - regime_affinity: which regimes this signal works best in
  - components: dict of sub-scores for dashboard transparency
"""

from __future__ import annotations
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import pandas as pd


def feat(row, key: str, default: float = 0.0) -> float:
    """
    NaN-safe numeric feature read.

    Use this instead of `float(row.get(key, default) or default)`. The `or`
    idiom is unsafe for numeric features because a legitimate 0.0 is falsy and
    gets silently replaced by the default (issue FEAT-02). This returns the
    default only when the value is genuinely missing or NaN.
    """
    val = row.get(key, default)
    try:
        val = float(val)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(val):
        return float(default)
    return val


class Direction(str, Enum):
    LONG    = "LONG"
    SHORT   = "SHORT"
    NEUTRAL = "NEUTRAL"


class Regime(str, Enum):
    TRENDING_UP    = "TRENDING_UP"
    TRENDING_DOWN  = "TRENDING_DOWN"
    MEAN_REVERTING = "MEAN_REVERTING"
    CHOPPY         = "CHOPPY"
    UNKNOWN        = "UNKNOWN"


@dataclass
class SignalResult:
    """Output of BaseSignal.compute()"""
    signal_name:   str
    symbol:        str
    score:         float                    # [-1.0, +1.0]
    direction:     Direction
    confidence:    float                    # [0.0, 1.0]
    regime:        Regime = Regime.UNKNOWN
    components:    dict   = field(default_factory=dict)  # sub-scores for transparency
    notes:         str    = ""

    def __post_init__(self) -> None:
        self.score      = float(max(-1.0, min(1.0, self.score)))
        self.confidence = float(max(0.0,  min(1.0, abs(self.score))))
        if self.score > 0.05:
            self.direction = Direction.LONG
        elif self.score < -0.05:
            self.direction = Direction.SHORT
        else:
            self.direction = Direction.NEUTRAL

    @property
    def is_actionable(self) -> bool:
        """True if score crosses minimum threshold to be shown in scanner."""
        return abs(self.score) >= 0.40

    def to_dict(self) -> dict:
        return {
            "signal":     self.signal_name,
            "symbol":     self.symbol,
            "score":      round(self.score, 4),
            "direction":  self.direction.value,
            "confidence": round(self.confidence, 4),
            "regime":     self.regime.value,
            "components": self.components,
            "notes":      self.notes,
        }


class BaseSignal(ABC):
    """
    Abstract base class for all signals.
    Subclass this and implement `compute()`.
    """

    name: str = "base_signal"
    regime_affinity: list[Regime] = []   # regimes where this signal excels
    shadow_mode: bool = False            # if True, compute but don't affect ensemble

    def compute(self, df: pd.DataFrame, symbol: str = "") -> SignalResult:
        """
        Compute signal score from feature-enriched OHLCV DataFrame.
        df must already have features computed by features/indicators.py.
        Returns SignalResult with score in [-1.0, +1.0].
        """
        if df is None or df.empty:
            return self._neutral(symbol, notes="empty dataframe")
        if len(df) < 20:
            return self._neutral(symbol, notes=f"insufficient bars ({len(df)})")
        return self._compute(df, symbol)

    @abstractmethod
    def _compute(self, df: pd.DataFrame, symbol: str) -> SignalResult:
        """Implement signal logic here. df is guaranteed non-empty with ≥20 bars."""

    def _neutral(self, symbol: str, notes: str = "") -> SignalResult:
        return SignalResult(
            signal_name=self.name,
            symbol=symbol,
            score=0.0,
            direction=Direction.NEUTRAL,
            confidence=0.0,
            notes=notes,
        )

    def _result(
        self,
        symbol: str,
        score: float,
        components: Optional[dict] = None,
        regime: Regime = Regime.UNKNOWN,
        notes: str = "",
    ) -> SignalResult:
        return SignalResult(
            signal_name=self.name,
            symbol=symbol,
            score=score,
            direction=Direction.NEUTRAL,  # set in __post_init__
            confidence=abs(score),
            regime=regime,
            components=components or {},
            notes=notes,
        )
