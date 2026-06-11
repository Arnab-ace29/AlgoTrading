"""
Theta book — single decision surface for the short-volatility strategy.

Ties together the three pieces that previously didn't talk to each other:
  • WeeklyStraddleStrategy — VIX-band / expiry / profit-target logic
  • ThetaRiskManager       — hard rails (VIX panic, book-capital cap, concurrency)
  • DeltaHedgeManager      — delta-neutralising futures hedge (THETA-01 sizing)

Before this, `risk/theta_risk.py` was never consulted by the strategy. The book
enforces the risk rails on every entry/exit decision.

This is a PARALLEL strategy book — a short straddle is multi-leg and short-vol, so
it is deliberately NOT folded into the single-symbol technical ensemble. The book
produces decisions from market inputs; live multi-leg order routing (option-chain
feed + futures hedge orders) is a separate piece that still needs building.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from signals.theta.weekly_straddle import WeeklyStraddleStrategy, StraddlePosition, StraddleLeg
from signals.theta.hedge_manager import DeltaHedgeManager, HedgeAction
from risk.theta_risk import ThetaRiskManager


@dataclass
class ThetaDecision:
    action: str                                   # ENTER / EXIT / HOLD
    legs: list[StraddleLeg] = field(default_factory=list)
    lots: int = 0
    hedge: Optional[HedgeAction] = None           # set when HOLDing and a hedge is due
    reason: str = ""


class ThetaBook:
    """Risk-gated entry/exit/hedge decisions for the weekly straddle book."""

    def __init__(self,
                 total_capital: float,
                 strategy: Optional[WeeklyStraddleStrategy] = None,
                 risk: Optional[ThetaRiskManager] = None,
                 hedger: Optional[DeltaHedgeManager] = None):
        self.strategy = strategy or WeeklyStraddleStrategy()
        self.risk = risk or ThetaRiskManager(total_capital)
        self.hedger = hedger or DeltaHedgeManager()

    def evaluate_entry(self,
                       india_vix: float,
                       nifty_spot: float,
                       days_to_expiry: int,
                       is_event_week: bool,
                       open_straddles: int,
                       current_book_capital: float,
                       new_position_capital: float) -> ThetaDecision:
        """Risk rails first, then the strategy's own entry logic."""
        ok, why = self.risk.can_enter(india_vix, open_straddles,
                                      current_book_capital, new_position_capital)
        if not ok:
            return ThetaDecision("HOLD", reason=f"risk: {why}")

        dec = self.strategy.build_entry(nifty_spot, india_vix, days_to_expiry, is_event_week)
        if dec.action != "ENTER":
            return ThetaDecision("HOLD", reason=dec.reason)
        return ThetaDecision("ENTER", legs=dec.legs, lots=dec.lots, reason=dec.reason)

    def evaluate_open(self, position: StraddlePosition, india_vix: float) -> ThetaDecision:
        """Hard risk exits override; else strategy exit; else HOLD (+ maybe hedge)."""
        forced, why = self.risk.must_force_exit(india_vix, position.pnl_pct)
        if forced:
            return ThetaDecision("EXIT", legs=position.legs,
                                 lots=position.legs[0].lots if position.legs else 0,
                                 reason=f"risk: {why}")

        dec = self.strategy.evaluate(position, india_vix)
        if dec.action == "EXIT":
            return ThetaDecision("EXIT", legs=dec.legs, lots=dec.lots, reason=dec.reason)

        # Holding → check whether a delta hedge is due (correct lot sizing, THETA-01).
        pos_lots = position.legs[0].lots if position.legs else 0
        hedge = self.hedger.compute_hedge(position.net_delta, position_lots=pos_lots)
        if hedge.action != "NONE":
            return ThetaDecision("HOLD", legs=position.legs, lots=pos_lots,
                                 hedge=hedge, reason=hedge.reason)
        return ThetaDecision("HOLD", legs=position.legs, lots=pos_lots, reason=dec.reason)
