"""
Theta / Options-Selling Risk Management - Phase 2

Hard risk rails for the short-volatility book. Short straddles can lose many
multiples of the premium collected during a black-swan move, so these guards
are non-negotiable:

  - Hard VIX stop: never hold through a VIX spike above the panic level.
  - Book cap: theta book must stay <= a fraction of total capital.
  - No new entries when the book is already at capacity.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional



@dataclass
class ThetaRiskLimits:
    vix_panic: float = 20.0           # close all straddles above this VIX
    max_book_pct: float = 0.20        # theta book <= 20% of total capital
    max_concurrent_straddles: int = 1  # weekly straddles open at once
    max_loss_pct_of_premium: float = -1.0  # stop at -100% of premium (2x premium loss)


class ThetaRiskManager:
    """Validates theta entries/exits against capital and volatility limits."""

    def __init__(self, total_capital: float, limits: Optional[ThetaRiskLimits] = None):
        self.total_capital = total_capital
        self.limits = limits or ThetaRiskLimits()

    def max_premium_capital(self) -> float:
        """Maximum capital (margin proxy) allowed in the theta book."""
        return self.total_capital * self.limits.max_book_pct

    def can_enter(self,
                  india_vix: float,
                  open_straddles: int,
                  current_book_capital: float,
                  new_position_capital: float) -> tuple[bool, str]:
        """Check all entry guards. Returns (allowed, reason)."""
        if india_vix >= self.limits.vix_panic:
            return False, f"VIX {india_vix:.1f} >= panic {self.limits.vix_panic}"
        if open_straddles >= self.limits.max_concurrent_straddles:
            return False, f"already {open_straddles} straddle(s) open (max {self.limits.max_concurrent_straddles})"
        projected = current_book_capital + new_position_capital
        if projected > self.max_premium_capital():
            return False, (
                f"book capital {projected:.0f} would exceed cap "
                f"{self.max_premium_capital():.0f} ({self.limits.max_book_pct:.0%} of capital)"
            )
        return True, "ok"

    def must_force_exit(self, india_vix: float, position_pnl_pct: float) -> tuple[bool, str]:
        """Hard exit triggers that override any other logic."""
        if india_vix >= self.limits.vix_panic:
            return True, f"VIX panic {india_vix:.1f} — force close theta book"
        if position_pnl_pct <= self.limits.max_loss_pct_of_premium:
            return True, f"loss {position_pnl_pct:.0%} of premium hit hard stop"
        return False, "within limits"
