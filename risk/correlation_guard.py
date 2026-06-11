"""
Correlation / sector exposure guard (EDGE-03).

The first real backtest concentrated trades in correlated names — ICICIBANK + SBIN
(both banks) fired together and lost as a block. Holding several positions in one
sector (or several highly-correlated names) isn't diversification; one adverse move
hits them all, so a "max-3-positions" cap can still be 3 banks.

This guard adds two cheap, deterministic checks at entry, on top of the circuit
breaker's global concurrency cap:
  1. **Sector cap** — at most `max_per_sector` open positions in the same sector.
  2. **Correlation cap** (optional) — block a candidate whose recent return
     correlation with any open position exceeds `max_correlation`. Needs aligned
     close history, so it's opt-in (the sector cap alone fixes the demonstrated case
     and costs nothing).

Unknown symbols map to a unique sector (their own name), so they're never wrongly
grouped/blocked. stdlib + optional numpy; safe to import anywhere.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

# NSE sector classification for the configured universes (screener/universe.py).
# Refresh alongside the constituent lists. Symbols absent here are treated as their
# own unique sector (no grouping) — see sector_of().
SECTOR_MAP: dict[str, str] = {
    # Banks
    "HDFCBANK": "BANK", "ICICIBANK": "BANK", "SBIN": "BANK", "AXISBANK": "BANK",
    "KOTAKBANK": "BANK", "INDUSINDBK": "BANK", "BANKBARODA": "BANK", "PNB": "BANK",
    "CANBK": "BANK", "IDFCFIRSTB": "BANK", "AUBANK": "BANK", "BANDHANBNK": "BANK",
    # Financials / NBFC / insurance
    "BAJFINANCE": "FIN", "BAJAJFINSV": "FIN", "CHOLAFIN": "FIN", "SBICARD": "FIN",
    "SHRIRAMFIN": "FIN", "MFSL": "FIN", "SBILIFE": "FIN", "HDFCLIFE": "FIN",
    "ICICIGI": "FIN", "ICICIPRULI": "FIN",
    # IT
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "LTIM": "IT", "NAUKRI": "IT",
    # Energy / oil & gas / power
    "RELIANCE": "ENERGY", "ONGC": "ENERGY", "NTPC": "ENERGY", "POWERGRID": "ENERGY",
    "COALINDIA": "ENERGY", "BPCL": "ENERGY", "GAIL": "ENERGY", "IOC": "ENERGY",
    "HINDPETRO": "ENERGY",
    # Autos
    "MARUTI": "AUTO", "M&M": "AUTO", "TATAMOTORS": "AUTO", "EICHERMOT": "AUTO",
    "HEROMOTOCO": "AUTO", "BAJAJ-AUTO": "AUTO", "TVSMOTOR": "AUTO", "ASHOKLEY": "AUTO",
    "MOTHERSON": "AUTO", "BOSCHLTD": "AUTO",
    # Metals & mining
    "TATASTEEL": "METAL", "JSWSTEEL": "METAL", "HINDALCO": "METAL", "VEDL": "METAL",
    "JINDALSTEL": "METAL", "NMDC": "METAL", "SAIL": "METAL",
    # Pharma / healthcare
    "SUNPHARMA": "PHARMA", "DRREDDY": "PHARMA", "CIPLA": "PHARMA", "DIVISLAB": "PHARMA",
    "AUROPHARMA": "PHARMA", "LUPIN": "PHARMA", "TORNTPHARM": "PHARMA", "BIOCON": "PHARMA",
    "APOLLOHOSP": "PHARMA",
    # FMCG / consumer staples
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "TATACONSUM": "FMCG", "DABUR": "FMCG", "MARICO": "FMCG", "GODREJCP": "FMCG",
    "COLPAL": "FMCG", "DMART": "FMCG",
    # Cement
    "ULTRACEMCO": "CEMENT", "GRASIM": "CEMENT", "SHREECEM": "CEMENT",
    "AMBUJACEM": "CEMENT", "ACC": "CEMENT",
    # Paints / chemicals
    "ASIANPAINT": "CHEM", "BERGEPAINT": "CHEM", "PIDILITIND": "CHEM", "SRF": "CHEM",
    "UPL": "CHEM", "PIIND": "CHEM",
    # Capital goods / infra
    "LT": "INFRA", "SIEMENS": "INFRA", "ABB": "INFRA", "HAVELLS": "INFRA",
    # Realty
    "DLF": "REALTY", "GODREJPROP": "REALTY",
    # Adani group (move together)
    "ADANIENT": "ADANI", "ADANIPORTS": "ADANI",
    # Telecom
    "BHARTIARTL": "TELECOM",
    # Consumer discretionary / retail / new-age
    "TITAN": "RETAIL", "TRENT": "RETAIL", "INDHOTEL": "RETAIL", "IRCTC": "RETAIL",
    "ZOMATO": "RETAIL", "PAYTM": "RETAIL",
}


def correlation(a: Sequence[float], b: Sequence[float], lookback: int = 60) -> Optional[float]:
    """
    Pearson correlation of the two series' recent simple returns over `lookback`
    bars. Returns None if there isn't enough overlapping history. Uses numpy if
    present, else a stdlib fallback.
    """
    n = min(len(a), len(b))
    if n < 5:
        return None
    a = list(a)[-(lookback + 1):]
    b = list(b)[-(lookback + 1):]
    m = min(len(a), len(b))
    if m < 5:
        return None
    a, b = a[-m:], b[-m:]
    ra = [a[i] / a[i - 1] - 1.0 for i in range(1, m) if a[i - 1]]
    rb = [b[i] / b[i - 1] - 1.0 for i in range(1, m) if b[i - 1]]
    k = min(len(ra), len(rb))
    if k < 4:
        return None
    ra, rb = ra[-k:], rb[-k:]
    try:
        import numpy as np
        if np.std(ra) == 0 or np.std(rb) == 0:
            return None
        return float(np.corrcoef(ra, rb)[0, 1])
    except ImportError:
        ma, mb = sum(ra) / k, sum(rb) / k
        cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
        va = sum((x - ma) ** 2 for x in ra)
        vb = sum((y - mb) ** 2 for y in rb)
        if va == 0 or vb == 0:
            return None
        return cov / (va ** 0.5 * vb ** 0.5)


class CorrelationGuard:
    """Blocks an entry that would over-concentrate the book in one sector / cluster."""

    def __init__(self, max_per_sector: int = 2, max_correlation: float = 0.75,
                 lookback: int = 60, enabled: bool = True):
        self.max_per_sector = max_per_sector
        self.max_correlation = max_correlation
        self.lookback = lookback
        self.enabled = enabled

    @staticmethod
    def sector_of(symbol: str) -> str:
        """Sector for a symbol; unknown → its own name (so it's never grouped)."""
        return SECTOR_MAP.get(symbol, f"_{symbol}")

    def allow(
        self,
        symbol: str,
        open_symbols: Sequence[str],
        price_provider: Optional[Callable[[str], Sequence[float]]] = None,
    ) -> tuple[bool, str]:
        """
        (allowed, reason) for opening `symbol` given the currently open symbols.

        price_provider(symbol) -> recent close series enables the optional
        correlation check; omit it to use the sector cap only (cheap, deterministic).
        """
        if not self.enabled or not open_symbols:
            return True, "OK"

        # 1. Sector cap.
        sec = self.sector_of(symbol)
        same = [s for s in open_symbols if self.sector_of(s) == sec]
        if len(same) >= self.max_per_sector:
            return False, f"SECTOR_CAP {sec} ({len(same)}/{self.max_per_sector}: {same})"

        # 2. Correlation cap (optional — needs aligned history).
        if price_provider is not None:
            try:
                cand = price_provider(symbol)
            except Exception:
                cand = None
            if cand is not None and len(cand) >= 5:
                for s in open_symbols:
                    try:
                        other = price_provider(s)
                    except Exception:
                        other = None
                    if other is None:
                        continue
                    c = correlation(cand, other, self.lookback)
                    if c is not None and c >= self.max_correlation:
                        return False, f"CORRELATED {symbol}~{s} (ρ={c:.2f} ≥ {self.max_correlation})"

        return True, "OK"
