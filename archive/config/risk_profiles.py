"""
Risk profiles for the trading system.
Select active profile via RISK_PROFILE env var (LOW / MEDIUM / HIGH).
"""

from __future__ import annotations
from dataclasses import dataclass
from config.settings import RISK_PROFILE


@dataclass(frozen=True)
class RiskProfile:
    name: str
    max_daily_loss_pct: float       # halt trading if daily loss exceeds X% of capital
    max_trades_per_day: int         # hard cap on number of new entries per day
    lot_size_cap: int               # maximum lots per single trade
    sl_atr_multiplier: float        # stop-loss = entry ± ATR14 × this
    target_atr_multiplier: float    # profit target = entry ± ATR14 × this
    trailing_sl_activation: float   # activate trailing SL after +X × ATR unrealized profit
    trailing_sl_lock: float         # once trailing active, lock in X × ATR profit
    max_concurrent_positions: int   # max open positions at the same time
    portfolio_heat_limit_pct: float # max total risk (sum of SL distances) as % of capital


LOW = RiskProfile(
    name                    = "LOW",
    max_daily_loss_pct      = 1.0,
    max_trades_per_day      = 5,
    lot_size_cap            = 1,
    sl_atr_multiplier       = 1.5,
    target_atr_multiplier   = 2.5,
    trailing_sl_activation  = 1.2,
    trailing_sl_lock        = 0.8,
    max_concurrent_positions= 3,
    portfolio_heat_limit_pct= 2.0,
)

MEDIUM = RiskProfile(
    name                    = "MEDIUM",
    max_daily_loss_pct      = 1.5,
    max_trades_per_day      = 8,
    lot_size_cap            = 2,
    sl_atr_multiplier       = 1.5,
    target_atr_multiplier   = 2.0,
    trailing_sl_activation  = 1.0,
    trailing_sl_lock        = 0.7,
    max_concurrent_positions= 5,
    portfolio_heat_limit_pct= 3.5,
)

HIGH = RiskProfile(
    name                    = "HIGH",
    max_daily_loss_pct      = 2.0,
    max_trades_per_day      = 12,
    lot_size_cap            = 3,
    sl_atr_multiplier       = 1.2,
    target_atr_multiplier   = 1.8,
    trailing_sl_activation  = 0.8,
    trailing_sl_lock        = 0.5,
    max_concurrent_positions= 8,
    portfolio_heat_limit_pct= 5.0,
)

PROFILES: dict[str, RiskProfile] = {"LOW": LOW, "MEDIUM": MEDIUM, "HIGH": HIGH}


def get_profile(name: str) -> RiskProfile:
    """Look up a risk profile by name (case-insensitive). Raises on unknown name."""
    profile = PROFILES.get((name or "").upper())
    if profile is None:
        raise ValueError(f"Unknown risk profile '{name}'. Must be LOW, MEDIUM, or HIGH.")
    return profile


def get_active_profile() -> RiskProfile:
    """Return the active risk profile based on RISK_PROFILE env var."""
    return get_profile(RISK_PROFILE)


ACTIVE = get_active_profile()
