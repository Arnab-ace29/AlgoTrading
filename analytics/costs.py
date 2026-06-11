"""
Transaction cost model for NSE intraday equity (MIS).

Indian charges are asymmetric (STT on sell side, stamp duty on buy side) so a
single flat "0.05%" figure understates real costs. This models each component so
that net P&L means net of everything the broker/exchange actually deducts.

Rates as of 2026 for Upstox intraday equity. Tune in one place.

Usage:
    from analytics.costs import round_trip_cost
    cost = round_trip_cost(entry_price, exit_price, qty)   # ₹, always >= 0
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
SLIPPAGE_PCT            = 0.0003     # modelled execution slippage per leg


def _brokerage(turnover: float) -> float:
    return min(BROKERAGE_PER_ORDER_CAP, BROKERAGE_PCT * turnover)


def round_trip_cost(entry_price: float, exit_price: float, qty: float) -> float:
    """
    Total round-trip cost (entry + exit) in rupees for an intraday equity trade.
    Returns 0.0 if inputs are non-positive.
    """
    try:
        entry_price = float(entry_price)
        exit_price  = float(exit_price)
        qty         = float(qty)
    except (TypeError, ValueError):
        return 0.0
    if entry_price <= 0 or exit_price <= 0 or qty <= 0:
        return 0.0

    buy_turnover  = entry_price * qty
    sell_turnover = exit_price * qty
    total_turnover = buy_turnover + sell_turnover

    brokerage   = _brokerage(buy_turnover) + _brokerage(sell_turnover)
    stt         = STT_SELL_PCT * sell_turnover
    exchange    = EXCHANGE_TXN_PCT * total_turnover
    sebi        = SEBI_PCT * total_turnover
    stamp       = STAMP_DUTY_BUY_PCT * buy_turnover
    gst         = GST_PCT * (brokerage + exchange + sebi)
    slippage    = SLIPPAGE_PCT * total_turnover

    return round(brokerage + stt + exchange + sebi + stamp + gst + slippage, 2)


def cost_breakdown(entry_price: float, exit_price: float, qty: float) -> dict:
    """
    Itemised round-trip cost components (₹) for an intraday equity trade — same
    maths as round_trip_cost, split out so the UI can show where the cost went
    (STT, brokerage, slippage, etc.). All values rounded to 2dp; 'total' matches
    round_trip_cost. Returns all-zero on degenerate inputs.
    """
    try:
        entry_price = float(entry_price)
        exit_price  = float(exit_price)
        qty         = float(qty)
    except (TypeError, ValueError):
        entry_price = exit_price = qty = 0.0
    if entry_price <= 0 or exit_price <= 0 or qty <= 0:
        return {"brokerage": 0.0, "stt": 0.0, "exchange": 0.0, "sebi": 0.0,
                "stamp": 0.0, "gst": 0.0, "slippage": 0.0, "total": 0.0}

    buy_turnover   = entry_price * qty
    sell_turnover  = exit_price * qty
    total_turnover = buy_turnover + sell_turnover

    brokerage = _brokerage(buy_turnover) + _brokerage(sell_turnover)
    stt       = STT_SELL_PCT * sell_turnover
    exchange  = EXCHANGE_TXN_PCT * total_turnover
    sebi      = SEBI_PCT * total_turnover
    stamp     = STAMP_DUTY_BUY_PCT * buy_turnover
    gst       = GST_PCT * (brokerage + exchange + sebi)
    slippage  = SLIPPAGE_PCT * total_turnover
    total     = brokerage + stt + exchange + sebi + stamp + gst + slippage

    return {
        "brokerage": round(brokerage, 2),
        "stt":       round(stt, 2),
        "exchange":  round(exchange, 2),
        "sebi":      round(sebi, 2),
        "stamp":     round(stamp, 2),
        "gst":       round(gst, 2),
        "slippage":  round(slippage, 2),
        "total":     round(total, 2),
    }


def per_leg_slippage(price: float, qty: float) -> float:
    """Modelled slippage cost for a single fill (entry OR exit)."""
    try:
        return round(SLIPPAGE_PCT * float(price) * float(qty), 2)
    except (TypeError, ValueError):
        return 0.0


# Minimum ratio of best-case (target) gross profit to round-trip cost for a trade
# to be worth taking. At 2.0, costs may eat at most half of a perfect outcome; in
# practice they eat far less on liquid large-caps, so this only blocks cost-traps
# (tiny-ATR / sub-rupee-edge setups) rather than normal trades.
MIN_TARGET_COST_MULTIPLE = 2.0


def is_cost_effective(entry_price: float, target_price: float, qty: float,
                      min_multiple: float = MIN_TARGET_COST_MULTIPLE) -> bool:
    """
    True if the trade's best-case gross profit (entry→target) is at least
    `min_multiple` × its round-trip transaction cost. Use as a pre-trade filter so
    the system never takes a setup whose edge the costs would erase (PnL-NET).
    Degenerate inputs (non-positive prices/qty) return False (skip).
    """
    try:
        entry_price  = float(entry_price)
        target_price = float(target_price)
        qty          = float(qty)
    except (TypeError, ValueError):
        return False
    if entry_price <= 0 or target_price <= 0 or qty <= 0:
        return False
    target_gross = abs(target_price - entry_price) * qty
    cost = round_trip_cost(entry_price, target_price, qty)
    if cost <= 0:
        return target_gross > 0
    return target_gross >= min_multiple * cost
