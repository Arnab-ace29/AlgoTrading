"""
Weekly Straddle Strategy - Phase 2 (Theta / Options Selling)

Sells an ATM short straddle on NIFTY weekly options to harvest the volatility
risk premium (IV consistently trades above realised vol on NSE weeklies).

This module contains the *decision logic* only. It takes market inputs
(India VIX, NIFTY spot, days-to-expiry, event-week flag, current position
P&L and delta) and returns entry/exit/sizing decisions. Actual order routing
is handled by live/openalgo_client.py.
"""

from __future__ import annotations
from dataclasses import dataclass, field


# NIFTY strikes are spaced 50 points apart.
NIFTY_STRIKE_STEP = 50
# NIFTY lot size (exchange-defined; update if SEBI/NSE revises it).
NIFTY_LOT_SIZE = 75


@dataclass
class StraddleLeg:
    option_type: str   # "CE" or "PE"
    strike: int
    action: str        # "SELL"
    lots: int


@dataclass
class StraddlePosition:
    legs: list[StraddleLeg]
    entry_premium: float          # total premium collected (per unit)
    current_premium: float        # current combined premium (per unit)
    net_delta: float              # net position delta
    days_to_expiry: int

    @property
    def pnl_pct(self) -> float:
        """
        P&L as a fraction of premium collected. For a short option, profit
        accrues as premium decays: (entry - current) / entry.
        Positive = profit, negative = loss.
        """
        if self.entry_premium <= 0:
            return 0.0
        return (self.entry_premium - self.current_premium) / self.entry_premium


@dataclass
class StraddleDecision:
    action: str                   # "ENTER", "EXIT", "HOLD", "ADJUST"
    legs: list[StraddleLeg] = field(default_factory=list)
    lots: int = 0
    reason: str = ""


class WeeklyStraddleStrategy:
    """ATM short straddle entry/exit/sizing logic for NIFTY weeklies."""

    def __init__(self,
                 vix_floor: float = 11.0,
                 vix_ceiling: float = 18.0,
                 vix_panic: float = 20.0,
                 vix_full_size: float = 14.0,   # VIX at/above which we take full (2-lot) size, up to the ceiling
                 min_days_to_expiry: int = 3,
                 profit_target_pct: float = 0.50,
                 stop_loss_pct: float = -1.0,
                 max_abs_delta: float = 0.35):
        self.vix_floor = vix_floor
        self.vix_ceiling = vix_ceiling
        self.vix_panic = vix_panic
        # Keep the sizing bands ordered even if mis-configured: floor ≤ full_size ≤ ceiling.
        self.vix_full_size = max(vix_floor, min(vix_full_size, vix_ceiling))
        self.min_days_to_expiry = min_days_to_expiry
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_abs_delta = max_abs_delta

    # ── Entry ─────────────────────────────────────────────────────────────
    def should_enter(self,
                     india_vix: float,
                     days_to_expiry: int,
                     is_event_week: bool) -> tuple[bool, str]:
        """Gate entry on VIX band, event weeks and remaining theta."""
        if is_event_week:
            return False, "event week (RBI/budget/expiry) — skip"
        if india_vix >= self.vix_ceiling:
            return False, f"VIX {india_vix:.1f} >= {self.vix_ceiling} (too risky)"
        if india_vix <= self.vix_floor:
            return False, f"VIX {india_vix:.1f} <= {self.vix_floor} (premium too thin)"
        if days_to_expiry < self.min_days_to_expiry:
            return False, f"only {days_to_expiry}d to expiry (<{self.min_days_to_expiry})"
        return True, "entry conditions met"

    def atm_strike(self, nifty_spot: float) -> int:
        """Nearest 50-point strike to spot."""
        return int(round(nifty_spot / NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP)

    def vix_to_lots(self, india_vix: float) -> int:
        """
        VIX-based position sizing, driven entirely by the configured VIX bounds
        (THETA-02 — previously hardcoded 11/14/18/20). Higher VIX = richer premium
        but more risk, so size is trimmed at both edges of the band:
            below vix_floor or ≥ vix_panic     -> 0 lots (no entry)
            [vix_floor, vix_full_size)         -> 1 lot   (premium still thin)
            [vix_full_size, vix_ceiling)       -> 2 lots  (sweet spot, full size)
            [vix_ceiling, vix_panic)           -> 1 lot   (elevated VIX, reduced size)
        With the defaults (11 / 14 / 18 / 20) this reproduces the original bands.
        """
        if india_vix < self.vix_floor or india_vix >= self.vix_panic:
            return 0
        if india_vix < self.vix_full_size:
            return 1
        if india_vix < self.vix_ceiling:
            return 2
        return 1   # [vix_ceiling, vix_panic): elevated VIX, reduced size

    def build_entry(self,
                    nifty_spot: float,
                    india_vix: float,
                    days_to_expiry: int,
                    is_event_week: bool) -> StraddleDecision:
        """Produce an ENTER decision with both short legs, or HOLD if gated."""
        ok, reason = self.should_enter(india_vix, days_to_expiry, is_event_week)
        if not ok:
            return StraddleDecision(action="HOLD", reason=reason)

        lots = self.vix_to_lots(india_vix)
        if lots <= 0:
            return StraddleDecision(action="HOLD", reason="VIX out of sizing band")

        strike = self.atm_strike(nifty_spot)
        legs = [
            StraddleLeg("CE", strike, "SELL", lots),
            StraddleLeg("PE", strike, "SELL", lots),
        ]
        return StraddleDecision(
            action="ENTER", legs=legs, lots=lots,
            reason=f"ATM short straddle @ {strike}, {lots} lot(s), VIX {india_vix:.1f}",
        )

    # ── Exit ──────────────────────────────────────────────────────────────
    def should_exit(self,
                    position: StraddlePosition,
                    india_vix: float) -> tuple[bool, str]:
        """Any one condition triggers a full exit of both legs."""
        if india_vix > self.vix_panic:
            return True, f"VIX spike {india_vix:.1f} > {self.vix_panic} — close now"
        if position.pnl_pct >= self.profit_target_pct:
            return True, f"profit target hit ({position.pnl_pct:.0%} of premium)"
        if position.pnl_pct <= self.stop_loss_pct:
            return True, f"stop loss hit ({position.pnl_pct:.0%} of premium)"
        if position.days_to_expiry <= 0:
            return True, "expiry day — close by 3:00 PM"
        if abs(position.net_delta) > self.max_abs_delta:
            return True, f"|delta| {abs(position.net_delta):.2f} > {self.max_abs_delta} — too directional"
        return False, "hold"

    def evaluate(self,
                 position: StraddlePosition,
                 india_vix: float) -> StraddleDecision:
        """Evaluate an open straddle and return EXIT or HOLD."""
        exit_now, reason = self.should_exit(position, india_vix)
        if exit_now:
            return StraddleDecision(action="EXIT", legs=position.legs,
                                    lots=position.legs[0].lots if position.legs else 0,
                                    reason=reason)
        return StraddleDecision(action="HOLD", reason=reason)
