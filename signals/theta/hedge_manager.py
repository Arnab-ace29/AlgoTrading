"""
Delta Hedge Manager - Phase 2 (Theta / Options Selling)

Keeps a short-straddle position close to delta-neutral by hedging with NIFTY
futures when the net delta drifts too far. Checked periodically (e.g. every
15 minutes) during market hours.

Logic (from ROADMAP):
  - If |net_delta| > hedge_trigger -> hedge with futures to neutralise.
  - Don't over-hedge small moves (only act above min_hedge_delta).
  - One NIFTY futures lot has a delta of LOT_SIZE (≈ +1 per unit * lot size).
"""

from __future__ import annotations
from dataclasses import dataclass

from signals.theta.weekly_straddle import NIFTY_LOT_SIZE


@dataclass
class HedgeAction:
    action: str        # "HEDGE_BUY", "HEDGE_SELL", "NONE"
    futures_lots: int  # number of NIFTY futures lots to trade
    reason: str = ""


class DeltaHedgeManager:
    """Computes futures hedges to neutralise straddle delta."""

    def __init__(self,
                 hedge_trigger_delta: float = 0.20,
                 min_hedge_delta: float = 0.15,
                 lot_size: int = NIFTY_LOT_SIZE):
        self.hedge_trigger_delta = hedge_trigger_delta
        self.min_hedge_delta = min_hedge_delta
        self.lot_size = lot_size

    def compute_hedge(self, net_delta: float, position_lots: int) -> HedgeAction:
        """
        Decide a futures hedge from the straddle's net delta (issue THETA-01).

        `net_delta` is the position delta PER UNIT of the underlying (e.g. +0.25
        means each underlying-share-equivalent is net long 0.25). The straddle
        holds `position_lots × lot_size` share-equivalents, so the position's total
        share-delta is `net_delta × position_lots × lot_size`. One NIFTY future
        carries a delta of `lot_size` share-deltas, so:

            futures_lots = (net_delta × position_lots × lot_size) / lot_size
                         =  net_delta × position_lots         (lot_size cancels)

        i.e. the hedge size scales with how many straddle lots you hold, NOT with
        `round(net_delta)` (the old bug, which treated a 0.25 per-unit delta as a
        whole lot). A positive net delta is neutralised by SELLING futures; a
        negative one by BUYING. Rounds to whole lots and may be 0 (a sub-lot drift
        isn't hedgeable with whole futures).
        """
        abs_delta = abs(net_delta)

        if abs_delta <= self.min_hedge_delta:
            return HedgeAction("NONE", 0, "delta within tolerance")
        if abs_delta <= self.hedge_trigger_delta:
            return HedgeAction("NONE", 0, "below hedge trigger")

        lots = int(round(abs_delta * max(0, position_lots)))
        if lots <= 0:
            return HedgeAction(
                "NONE", 0,
                f"net delta {net_delta:+.2f} × {position_lots} lot(s) < 1 future — not hedgeable in whole lots",
            )

        if net_delta > 0:
            return HedgeAction(
                "HEDGE_SELL", lots,
                f"net delta +{net_delta:.2f} on {position_lots} lot(s) — sell {lots} fut lot(s)",
            )
        return HedgeAction(
            "HEDGE_BUY", lots,
            f"net delta {net_delta:.2f} on {position_lots} lot(s) — buy {lots} fut lot(s)",
        )
