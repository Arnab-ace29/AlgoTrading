"""
Risk engine — position sizing (docs/BUILD_PLAN.md Part 2A).

Three separated knobs (never collapse into one "% allocation"):
  1. conviction  -> how much to RISK   (risk_budget)
  2. stop dist   -> how many SHARES     (qty = budget / risk-per-share)
  3. caps        -> bound the DOWNSIDE  (exposure cap + daily risk rail)

PURE function. The engine/live runner compute entry/stop/atr and call position_size().
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class SizingParams:
    base_risk_pct: float      = 0.01      # risk per trade at conviction 1.0 (1% of capital)
    daily_risk_cap_pct: float = 0.03      # stop trading once cumulative open risk hits this
    max_exposure: float       = 100_000   # leverage cap per position (₹ notional)
    slippage_pad_atr: float   = 0.4       # stop padding: momentum stocks gap THROUGH the stop


@dataclass(frozen=True)
class SizeResult:
    qty: int
    risk: float        # ₹ actually put at risk (qty * risk-per-share)
    exposure: float    # ₹ notional (qty * entry)
    reason: str        # "ok" or why qty is 0


def position_size(capital: float, conviction: float, entry: float, stop: float,
                  atr: float, params: SizingParams = SizingParams(),
                  open_risk: float = 0.0) -> SizeResult:
    """
    Size a trade so risk == base_risk_pct * conviction of capital, capped by exposure
    and the daily risk rail. `conviction` scales the budget (e.g. 0.5 / 1.0 / 1.5).
    Returns qty=0 (with a reason) when the trade can't be taken.
    """
    if entry <= 0 or atr < 0 or conviction <= 0:
        return SizeResult(0, 0.0, 0.0, "bad_input")

    risk_budget   = capital * params.base_risk_pct * conviction
    pad           = params.slippage_pad_atr * atr
    risk_per_share = abs(entry - stop) + pad
    if risk_per_share <= 0:
        return SizeResult(0, 0.0, 0.0, "bad_stop")

    qty = floor(risk_budget / risk_per_share)
    qty = min(qty, floor(params.max_exposure / entry))   # leverage cap
    if qty <= 0:
        return SizeResult(0, 0.0, 0.0, "qty_zero")

    actual_risk = qty * risk_per_share
    # Portfolio gate: refuse if it would breach the daily risk cap.
    if open_risk + actual_risk > capital * params.daily_risk_cap_pct:
        return SizeResult(0, 0.0, 0.0, "daily_risk_cap")

    return SizeResult(qty=qty, risk=round(actual_risk, 2),
                      exposure=round(qty * entry, 2), reason="ok")
