"""
Pairs Trading Signal - Phase 2 (Statistical Arbitrage)

Computes the rolling Z-score of a cointegrated spread and emits a
market-neutral signal:

    z > +entry  -> spread too WIDE  -> SHORT A, LONG B
    z < -entry  -> spread too NARROW -> LONG A, SHORT B
    |z| < exit  -> spread normalised -> close both legs
    |z| > stop  -> spread diverging  -> cut loss (cointegration may have broken)

The signal is market-neutral: it always trades both legs in opposite
directions, so net market exposure is ~0.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from signals.pairs.cointegration_scanner import get_hedge_ratio


@dataclass
class PairsSignalResult:
    pair: tuple[str, str]
    z_score: float
    action: str                 # "ENTER", "EXIT", "STOP", "HOLD"
    leg_a_direction: str        # "LONG" / "SHORT" / "FLAT"
    leg_b_direction: str        # "LONG" / "SHORT" / "FLAT"
    hedge_ratio: float
    spread: float
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "pair": f"{self.pair[0]}-{self.pair[1]}",
            "z_score": round(self.z_score, 4),
            "action": self.action,
            "leg_a": self.leg_a_direction,
            "leg_b": self.leg_b_direction,
            "hedge_ratio": round(self.hedge_ratio, 4),
            "spread": round(self.spread, 4),
            "notes": self.notes,
        }


class PairsSignal:
    """Z-score based pairs trading signal for one cointegrated pair."""

    name = "pairs_stat_arb"

    def __init__(self,
                 pair: tuple[str, str],
                 hedge_ratio: Optional[float] = None,
                 window: int = 20,
                 entry_z: float = 2.0,
                 exit_z: float = 0.5,
                 stop_z: float = 3.5):
        self.pair = pair
        self.window = window
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.stop_z = stop_z
        # Hedge ratio: explicit override or load from validated_pairs.json
        self.hedge_ratio = hedge_ratio if hedge_ratio is not None else (
            get_hedge_ratio(pair[0], pair[1]) or 1.0
        )

    def compute_spread(self, price_a: pd.Series, price_b: pd.Series) -> pd.Series:
        """spread = A - hedge_ratio * B, aligned on the shared index."""
        aligned = pd.concat([price_a, price_b], axis=1, keys=["a", "b"]).dropna()
        return aligned["a"] - self.hedge_ratio * aligned["b"]

    def compute_zscore(self, price_a: pd.Series, price_b: pd.Series) -> Optional[float]:
        """
        Latest Z-score of the spread, measured against the PRIOR `window` bars
        (excluding the current bar). Including the current point in its own mean/std
        biases |z| toward zero — a true blow-out self-inflates sigma and shifts mu
        toward itself, so the entry/stop thresholds (2.0 / 3.5) fire late or not at
        all. We need one extra historical bar, hence `window + 1`.
        """
        spread = self.compute_spread(price_a, price_b)
        if len(spread) < self.window + 1:
            return None
        ref = spread.iloc[-(self.window + 1):-1]   # trailing window, current bar excluded
        mu = float(ref.mean())
        sigma = float(ref.std())
        if not np.isfinite(sigma) or sigma == 0:
            return None
        return float((spread.iloc[-1] - mu) / sigma)

    def compute(self,
                price_a: pd.Series,
                price_b: pd.Series,
                in_position: bool = False) -> PairsSignalResult:
        """
        Evaluate the pair and return a PairsSignalResult.

        in_position: whether a pairs position is currently open (affects whether
                     we emit EXIT/STOP vs ENTER/HOLD).
        """
        spread = self.compute_spread(price_a, price_b)
        z = self.compute_zscore(price_a, price_b)

        last_spread = float(spread.iloc[-1]) if len(spread) else 0.0

        if z is None:
            return PairsSignalResult(
                pair=self.pair, z_score=0.0, action="HOLD",
                leg_a_direction="FLAT", leg_b_direction="FLAT",
                hedge_ratio=self.hedge_ratio, spread=last_spread,
                notes="insufficient data for z-score",
            )

        abs_z = abs(z)

        # Risk first: a diverging spread takes priority when in a position.
        if in_position and abs_z > self.stop_z:
            return PairsSignalResult(
                pair=self.pair, z_score=z, action="STOP",
                leg_a_direction="FLAT", leg_b_direction="FLAT",
                hedge_ratio=self.hedge_ratio, spread=last_spread,
                notes=f"|z|>{self.stop_z} cointegration may have broken",
            )

        # Mean reversion complete -> exit.
        if in_position and abs_z < self.exit_z:
            return PairsSignalResult(
                pair=self.pair, z_score=z, action="EXIT",
                leg_a_direction="FLAT", leg_b_direction="FLAT",
                hedge_ratio=self.hedge_ratio, spread=last_spread,
                notes="spread normalised",
            )

        # Entry conditions (only when flat).
        if not in_position and abs_z > self.entry_z:
            if z > 0:
                # Spread too wide -> short A, long B
                return PairsSignalResult(
                    pair=self.pair, z_score=z, action="ENTER",
                    leg_a_direction="SHORT", leg_b_direction="LONG",
                    hedge_ratio=self.hedge_ratio, spread=last_spread,
                    notes=f"z>{self.entry_z}: short {self.pair[0]}, long {self.pair[1]}",
                )
            else:
                # Spread too narrow -> long A, short B
                return PairsSignalResult(
                    pair=self.pair, z_score=z, action="ENTER",
                    leg_a_direction="LONG", leg_b_direction="SHORT",
                    hedge_ratio=self.hedge_ratio, spread=last_spread,
                    notes=f"z<-{self.entry_z}: long {self.pair[0]}, short {self.pair[1]}",
                )

        return PairsSignalResult(
            pair=self.pair, z_score=z, action="HOLD",
            leg_a_direction="FLAT", leg_b_direction="FLAT",
            hedge_ratio=self.hedge_ratio, spread=last_spread,
            notes="no actionable signal",
        )
