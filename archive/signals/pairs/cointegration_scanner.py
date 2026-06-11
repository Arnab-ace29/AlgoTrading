"""
Cointegration Scanner - Phase 2 (Pairs Trading / Statistical Arbitrage)

Tests candidate stock pairs for cointegration (Engle-Granger) and stores the
hedge ratio for pairs that pass. Run once to discover pairs, then refresh
monthly (or via the daily health check in risk/pairs_risk.py).

Output: config/validated_pairs.json
"""

from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from loguru import logger

from data.db import read_candles
from config.settings import ROOT_DIR

# statsmodels is imported lazily inside the functions that need it (the
# Engle-Granger test + OLS hedge ratio). This keeps PairsSignal / PairsBook
# importable without statsmodels — only pair *discovery*/health checks need it.


# Strong historical cointegration candidates on NSE (from ROADMAP).
CANDIDATE_PAIRS: list[tuple[str, str]] = [
    ("HDFCBANK", "ICICIBANK"),   # banking peers — strongest pair
    ("TCS", "INFY"),             # IT sector
    ("HINDUNILVR", "DABUR"),     # FMCG
    ("RELIANCE", "ONGC"),        # oil & gas
    ("AXISBANK", "KOTAKBANK"),   # mid-size banks
    ("WIPRO", "HCLTECH"),        # IT tier-2
]

VALIDATED_PAIRS_PATH = ROOT_DIR / "config" / "validated_pairs.json"

# Engle-Granger p-value below which a pair is considered cointegrated.
COINT_PVALUE_THRESHOLD = 0.05


def compute_hedge_ratio(price_a: pd.Series, price_b: pd.Series) -> float:
    """
    OLS hedge ratio (beta) for spread = A - beta*B.
    Regresses A on B with an intercept and returns the B coefficient.
    """
    import statsmodels.api as sm
    b = sm.add_constant(price_b.values)
    model = sm.OLS(price_a.values, b).fit()
    # params[0] = intercept, params[1] = hedge ratio
    return float(model.params[1])


def test_pair(price_a: pd.Series, price_b: pd.Series) -> Optional[dict]:
    """
    Run the Engle-Granger cointegration test on an aligned price pair.

    Returns a dict with score, pvalue and hedge_ratio, or None if the series
    are too short / misaligned to test.
    """
    from statsmodels.tsa.stattools import coint
    aligned = pd.concat([price_a, price_b], axis=1, keys=["a", "b"]).dropna()
    if len(aligned) < 60:
        return None

    a, b = aligned["a"], aligned["b"]
    score, pvalue, _ = coint(a, b)
    hedge_ratio = compute_hedge_ratio(a, b)
    return {
        "score": float(score),
        "pvalue": float(pvalue),
        "hedge_ratio": hedge_ratio,
        "n_obs": int(len(aligned)),
    }


def _load_close_series(symbol: str, timeframe: str, days: int) -> pd.Series:
    """Load a close-price series indexed by timestamp for one symbol."""
    from_dt = datetime.now(timezone.utc) - timedelta(days=days)
    df = read_candles(symbol, timeframe=timeframe, from_dt=from_dt)
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index("timestamp")["close"].astype(float)
    s.name = symbol
    return s


def scan_pairs(
    candidate_pairs: Optional[list[tuple[str, str]]] = None,
    timeframe: str = "1day",
    days: int = 365,
    pvalue_threshold: float = COINT_PVALUE_THRESHOLD,
    save: bool = True,
) -> list[dict]:
    """
    Test all candidate pairs and return those that pass the cointegration test.

    Each validated entry: {a, b, pvalue, score, hedge_ratio, n_obs, tested_at}.
    """
    pairs = candidate_pairs or CANDIDATE_PAIRS
    validated: list[dict] = []

    for sym_a, sym_b in pairs:
        price_a = _load_close_series(sym_a, timeframe, days)
        price_b = _load_close_series(sym_b, timeframe, days)
        if price_a.empty or price_b.empty:
            logger.warning(f"{sym_a}-{sym_b}: missing price data, skipping")
            continue

        result = test_pair(price_a, price_b)
        if result is None:
            logger.warning(f"{sym_a}-{sym_b}: insufficient overlapping data")
            continue

        status = "PASS" if result["pvalue"] < pvalue_threshold else "FAIL"
        logger.info(
            f"{sym_a}-{sym_b}: p={result['pvalue']:.4f} "
            f"hedge={result['hedge_ratio']:.3f} [{status}]"
        )

        if result["pvalue"] < pvalue_threshold:
            validated.append({
                "a": sym_a,
                "b": sym_b,
                "pvalue": result["pvalue"],
                "score": result["score"],
                "hedge_ratio": result["hedge_ratio"],
                "n_obs": result["n_obs"],
                "tested_at": datetime.now(timezone.utc).isoformat(),
            })

    if save:
        VALIDATED_PAIRS_PATH.parent.mkdir(parents=True, exist_ok=True)
        VALIDATED_PAIRS_PATH.write_text(json.dumps(validated, indent=2))
        logger.success(f"Wrote {len(validated)} validated pairs to {VALIDATED_PAIRS_PATH}")

    return validated


def load_validated_pairs() -> list[dict]:
    """Load previously validated pairs from config/validated_pairs.json."""
    if not VALIDATED_PAIRS_PATH.exists():
        return []
    try:
        return json.loads(VALIDATED_PAIRS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read validated pairs: {e}")
        return []


def get_hedge_ratio(sym_a: str, sym_b: str) -> Optional[float]:
    """Return the stored hedge ratio for a validated pair, if present."""
    for p in load_validated_pairs():
        if p["a"] == sym_a and p["b"] == sym_b:
            return p["hedge_ratio"]
    return None


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda m: print(m, end=""), level="INFO")
    scan_pairs()
