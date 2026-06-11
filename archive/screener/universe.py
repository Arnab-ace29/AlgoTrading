"""
Strategy universes.

Each strategy only trades the stocks it's designed for (MASTER_PLAN.md).

Universe sources (in priority order for live data):
  1. config/universes.json  — written by build_universes_json() (run monthly via
                               scripts/refresh_universe.py). Contains real constituents
                               from niftyindices.com + F&O list from Upstox master.
  2. _DEFAULT_UNIVERSES     — hardcoded Nifty 50 + 50 liquid names as a safety net
                               when the JSON file doesn't exist yet.

The screener intersects any universe with symbols that actually have candle data,
so it degrades gracefully to whatever is loaded.
"""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_UNIVERSES_JSON = _ROOT / "config" / "universes.json"

# Strategy book → universe name.
STRATEGY_UNIVERSE: dict[str, str] = {
    "momentum_vwap":  "nifty50",        # liquidity critical
    "rsi_momentum":   "nifty_total",    # 750-stock Nifty Total Market
    "mean_reversion": "fo_eligible",    # F&O names have more tradable volatility
    "options_flow":   "fo_eligible",
    "ml_macro":       "nifty_total",
}

# Strategies the daily watchlist run covers (pairs / news handled separately).
DEFAULT_STRATEGIES: list[str] = ["momentum_vwap", "rsi_momentum", "mean_reversion", "ml_macro"]

# ── Hardcoded safety-net (used only when universes.json doesn't exist) ─────────
_NIFTY50 = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC", "SBIN",
    "BHARTIARTL", "BAJFINANCE", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "SUNPHARMA", "TITAN", "ULTRACEMCO", "NESTLEIND", "WIPRO", "ONGC", "NTPC", "POWERGRID",
    "M&M", "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "ADANIENT", "ADANIPORTS", "COALINDIA",
    "HCLTECH", "TECHM", "BAJAJFINSV", "GRASIM", "HINDALCO", "DRREDDY", "CIPLA", "DIVISLAB",
    "BRITANNIA", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO", "INDUSINDBK", "APOLLOHOSP",
    "BPCL", "TATACONSUM", "SBILIFE", "HDFCLIFE", "LTIM", "SHRIRAMFIN",
]

_NEXT50 = [
    "DMART", "PIDILITIND", "GODREJCP", "DABUR", "MARICO", "COLPAL", "BERGEPAINT", "HAVELLS",
    "SIEMENS", "ABB", "BANKBARODA", "PNB", "CANBK", "IDFCFIRSTB", "AUBANK", "BANDHANBNK",
    "CHOLAFIN", "ICICIGI", "ICICIPRULI", "SBICARD", "DLF", "GODREJPROP", "INDHOTEL", "NAUKRI",
    "ZOMATO", "PAYTM", "IRCTC", "GAIL", "IOC", "HINDPETRO", "VEDL", "JINDALSTEL", "NMDC",
    "SAIL", "AMBUJACEM", "ACC", "SHREECEM", "PIIND", "SRF", "UPL", "AUROPHARMA", "LUPIN",
    "TORNTPHARM", "BIOCON", "MOTHERSON", "BOSCHLTD", "TVSMOTOR", "ASHOKLEY", "TRENT", "MFSL",
]

_DEFAULT_UNIVERSES: dict[str, list[str]] = {
    "nifty50":     list(_NIFTY50),
    "nifty100":    list(_NIFTY50) + list(_NEXT50),
    "nifty_total": list(_NIFTY50) + list(_NEXT50),   # replaced by universes.json when available
    "fo_eligible": list(_NIFTY50) + list(_NEXT50),   # replaced by universes.json when available
}


def _load_overrides() -> dict[str, list[str]]:
    if _UNIVERSES_JSON.exists():
        try:
            data = json.loads(_UNIVERSES_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: list(v) for k, v in data.items() if isinstance(v, list)}
        except Exception:
            pass
    return {}


def _dedupe(lst: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in lst:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def get_universe(name: str) -> list[str]:
    """Symbols in a named universe (config/universes.json overrides defaults)."""
    overrides = _load_overrides()
    base = overrides.get(name, _DEFAULT_UNIVERSES.get(name, []))
    return _dedupe(base)


def universe_for_strategy(strategy: str) -> list[str]:
    if strategy not in STRATEGY_UNIVERSE:
        from loguru import logger
        logger.warning(f"unknown strategy '{strategy}' — falling back to nifty50 "
                       f"(known: {sorted(STRATEGY_UNIVERSE)})")
    return get_universe(STRATEGY_UNIVERSE.get(strategy, "nifty50"))


def build_universes_json(force: bool = False) -> dict[str, list[str]]:
    """
    Build and write config/universes.json from live sources:
      - nifty_total  : Nifty Total Market 750 from niftyindices.com (screener/universe_fetcher.py)
      - fo_eligible  : F&O eligible underlyings from Upstox NSE instrument master
      - nifty50      : hardcoded (stable)
      - nifty100     : Nifty 50 + Next 50 hardcoded (stable)

    Call this monthly via scripts/refresh_universe.py.
    Returns the universe dict that was written.
    """
    from loguru import logger
    from screener.universe_fetcher import fetch_nifty_universe
    from data.instruments import get_fo_eligible_symbols, get_all_equity_symbols

    nifty_total = fetch_nifty_universe(force=force)
    fo_syms     = get_fo_eligible_symbols()
    eq_symbols  = set(get_all_equity_symbols())  # all genuine NSE equities in Upstox master

    if not nifty_total:
        logger.warning(
            "Nifty Total Market fetch returned empty — universes.json not updated.\n"
            f"  → Manually download: https://www.niftyindices.com/IndexConstituent/"
            f"ind_niftytotalmarket_list.csv\n"
            f"  → Save to: {_ROOT / 'config' / 'nifty_total_market.csv'}"
        )
        return {}

    # fo_eligible = all F&O underlying symbols that are genuine NSE equities.
    # Filter by presence in the equity key map (eq_symbols) to exclude index
    # derivatives like NIFTY, BANKNIFTY, FINNIFTY which appear in the FUT list
    # but are not tradable equity instruments.
    # Do NOT intersect with nifty_total — valid F&O stocks exist outside the 750.
    fo_filtered = [s for s in fo_syms if s in eq_symbols] if fo_syms else list(_NIFTY50)
    if not fo_filtered:
        fo_filtered = list(_NIFTY50) + list(_NEXT50)

    universes: dict[str, list[str]] = {
        "nifty50":     _dedupe(list(_NIFTY50)),
        "nifty100":    _dedupe(list(_NIFTY50) + list(_NEXT50)),
        "nifty_total": _dedupe(nifty_total),
        "fo_eligible": _dedupe(fo_filtered),
    }

    _UNIVERSES_JSON.parent.mkdir(parents=True, exist_ok=True)
    _UNIVERSES_JSON.write_text(json.dumps(universes, indent=2), encoding="utf-8")
    logger.success(
        f"universes.json written → "
        f"nifty_total={len(universes['nifty_total'])}, "
        f"fo_eligible={len(universes['fo_eligible'])}"
    )
    return universes
