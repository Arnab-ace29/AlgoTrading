"""
Transaction cost model for NSE intraday equity (MIS).

Indian charges are asymmetric (STT on the SELL leg, stamp duty on the BUY leg), so a
single flat "0.05%" understates real costs. This models each component, so net P&L
means net of everything the broker + exchange actually deduct.

Design note — slippage is NOT in round_trip_cost:
    Slippage is an execution effect on the FILL PRICE, not a charge. The backtest
    engine applies it to entry/exit prices (and uses a bigger value for fast names);
    live fills already contain real slippage. Folding a modelled slippage % into the
    cost here as well would double-count it. So round_trip_cost = pure charges only,
    and slippage is handled separately (per_leg_slippage / the engine's fill model).

Rates as of 2026 for Upstox intraday equity. Tune in one place.

    from analytics.costs import round_trip_cost
    cost = round_trip_cost(entry_price, exit_price, qty)   # ₹, always >= 0, charges only
    net  = gross_pnl - cost
"""

from __future__ import annotations

# ── Rate table (intraday equity, MIS) ─────────────────────────────────────────
BROKERAGE_PER_ORDER_CAP = 20.0      # ₹ per executed order, capped
BROKERAGE_PCT           = 0.0003    # 0.03% per leg (Upstox: lower of ₹20 or 0.03%)
STT_SELL_PCT            = 0.00025   # 0.025% on the SELL leg only (intraday)
EXCHANGE_TXN_PCT        = 0.0000297 # NSE ~0.00297% on total turnover
SEBI_PCT                = 0.000001  # ₹10 per crore
STAMP_DUTY_BUY_PCT      = 0.00003   # 0.003% on the BUY leg only
GST_PCT                 = 0.18      # 18% GST on (brokerage + exchange txn + sebi)

# Default modelled slippage per leg (the ENGINE overrides this per-name; fast
# momentum stocks in the first 15 min deserve more). Kept here as the reference.
DEFAULT_SLIPPAGE_PCT    = 0.0005    # 0.05% per leg baseline


def _brokerage(turnover: float) -> float:
    return min(BROKERAGE_PER_ORDER_CAP, BROKERAGE_PCT * turnover)


def round_trip_cost(entry_price: float, exit_price: float, qty: float) -> float:
    """
    Round-trip statutory + brokerage cost (entry + exit) in ₹ for an intraday equity
    trade. Charges only — NO slippage (see module docstring). 0.0 on degenerate input.
    """
    try:
        entry_price, exit_price, qty = float(entry_price), float(exit_price), float(qty)
    except (TypeError, ValueError):
        return 0.0
    if entry_price <= 0 or exit_price <= 0 or qty <= 0:
        return 0.0

    buy_turnover   = entry_price * qty
    sell_turnover  = exit_price * qty
    total_turnover = buy_turnover + sell_turnover

    brokerage = _brokerage(buy_turnover) + _brokerage(sell_turnover)
    stt       = STT_SELL_PCT * sell_turnover
    exchange  = EXCHANGE_TXN_PCT * total_turnover
    sebi      = SEBI_PCT * total_turnover
    stamp     = STAMP_DUTY_BUY_PCT * buy_turnover
    gst       = GST_PCT * (brokerage + exchange + sebi)
    return round(brokerage + stt + exchange + sebi + stamp + gst, 2)


def cost_breakdown(entry_price: float, exit_price: float, qty: float) -> dict:
    """Itemised round-trip charges (₹). 'total' matches round_trip_cost."""
    try:
        entry_price, exit_price, qty = float(entry_price), float(exit_price), float(qty)
    except (TypeError, ValueError):
        entry_price = exit_price = qty = 0.0
    if entry_price <= 0 or exit_price <= 0 or qty <= 0:
        return {k: 0.0 for k in ("brokerage", "stt", "exchange", "sebi", "stamp", "gst", "total")}

    buy_turnover   = entry_price * qty
    sell_turnover  = exit_price * qty
    total_turnover = buy_turnover + sell_turnover

    brokerage = _brokerage(buy_turnover) + _brokerage(sell_turnover)
    stt       = STT_SELL_PCT * sell_turnover
    exchange  = EXCHANGE_TXN_PCT * total_turnover
    sebi      = SEBI_PCT * total_turnover
    stamp     = STAMP_DUTY_BUY_PCT * buy_turnover
    gst       = GST_PCT * (brokerage + exchange + sebi)
    total     = brokerage + stt + exchange + sebi + stamp + gst
    return {
        "brokerage": round(brokerage, 2), "stt": round(stt, 2),
        "exchange":  round(exchange, 2),  "sebi": round(sebi, 2),
        "stamp":     round(stamp, 2),     "gst": round(gst, 2),
        "total":     round(total, 2),
    }


def per_leg_slippage(price: float, qty: float, slippage_pct: float = DEFAULT_SLIPPAGE_PCT) -> float:
    """Modelled slippage cost (₹) for a single fill. The engine passes its own pct."""
    try:
        return round(float(slippage_pct) * float(price) * float(qty), 2)
    except (TypeError, ValueError):
        return 0.0


def slip_price(price: float, side: str, slippage_pct: float = DEFAULT_SLIPPAGE_PCT) -> float:
    """
    Apply slippage to a fill price so it always hurts: a BUY fills higher, a SELL
    fills lower. Used by the backtest engine to make fills pessimistic.
    """
    try:
        price = float(price)
    except (TypeError, ValueError):
        return price
    direction = 1.0 if str(side).upper() in ("BUY", "LONG") else -1.0
    return round(price * (1 + direction * float(slippage_pct)), 4)


# Minimum ratio of best-case (target) gross profit to round-trip cost for a trade to
# be worth taking. At 2.0, costs may eat at most half of a perfect outcome.
MIN_TARGET_COST_MULTIPLE = 2.0


def is_cost_effective(entry_price: float, target_price: float, qty: float,
                      min_multiple: float = MIN_TARGET_COST_MULTIPLE) -> bool:
    """True if best-case gross profit (entry→target) ≥ min_multiple × round-trip cost."""
    try:
        entry_price, target_price, qty = float(entry_price), float(target_price), float(qty)
    except (TypeError, ValueError):
        return False
    if entry_price <= 0 or target_price <= 0 or qty <= 0:
        return False
    target_gross = abs(target_price - entry_price) * qty
    cost = round_trip_cost(entry_price, target_price, qty)
    if cost <= 0:
        return target_gross > 0
    return target_gross >= min_multiple * cost
