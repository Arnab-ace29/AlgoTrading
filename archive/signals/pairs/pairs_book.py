"""
Pairs book — ties the z-score pairs signal to the cointegration health tracker.

Before this, `risk/pairs_risk.py` (the health tracker that halts a pair whose
cointegration has broken, and caps concurrent pairs) was never consulted by the
signal, so a halted or over-cap pair would still emit ENTER. The book gates ENTER
on both checks.

This is a PARALLEL market-neutral strategy book — it trades two legs in opposite
directions, so it is deliberately NOT part of the single-symbol technical ensemble.
Live 2-leg execution (the short leg needs futures/F&O) is a separate piece.
"""

from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

from signals.pairs.pairs_signal import PairsSignal, PairsSignalResult
from risk.pairs_risk import PairsHealthTracker


class PairsBook:
    """Health-gated evaluation across a set of cointegrated pairs."""

    def __init__(self,
                 signals: Iterable[PairsSignal],
                 health: Optional[PairsHealthTracker] = None):
        self.signals: dict[tuple, PairsSignal] = {tuple(s.pair): s for s in signals}
        self.health = health or PairsHealthTracker()

    def add_pair(self, signal: PairsSignal) -> None:
        self.signals[tuple(signal.pair)] = signal

    def evaluate(self,
                 pair: tuple[str, str],
                 price_a: pd.Series,
                 price_b: pd.Series,
                 in_position: bool = False,
                 open_pairs_count: int = 0) -> PairsSignalResult:
        """
        Evaluate one pair. ENTER is suppressed (downgraded to HOLD) when the pair
        is halted by the health tracker or the concurrent-pairs cap is reached.
        EXIT / STOP / HOLD always pass through (risk-reducing actions are never
        blocked).
        """
        sig = self.signals.get(tuple(pair))
        if sig is None:
            raise KeyError(f"no PairsSignal registered for pair {pair}")

        res = sig.compute(price_a, price_b, in_position=in_position)

        if res.action == "ENTER":
            if self.health.is_halted(*sig.pair):
                return self._hold(sig, res, "pair halted — cointegration broken")
            if not self.health.can_open_new_pair(open_pairs_count):
                return self._hold(sig, res, f"max concurrent pairs reached ({open_pairs_count})")
        return res

    @staticmethod
    def _hold(sig: PairsSignal, res: PairsSignalResult, note: str) -> PairsSignalResult:
        return PairsSignalResult(
            pair=sig.pair, z_score=res.z_score, action="HOLD",
            leg_a_direction="FLAT", leg_b_direction="FLAT",
            hedge_ratio=res.hedge_ratio, spread=res.spread, notes=note,
        )
