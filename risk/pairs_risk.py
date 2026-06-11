"""
Pairs Trading Risk Management - Phase 2

Daily cointegration health check. A pair whose Engle-Granger p-value drifts
above the threshold for several consecutive days has likely broken (e.g. a
merger or scandal changed the historical relationship) and should be halted.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from loguru import logger

from data.db import read_candles
from signals.pairs.cointegration_scanner import test_pair

# If p-value exceeds this, the pair is considered no longer cointegrated.
HEALTH_PVALUE_THRESHOLD = 0.10
# Number of consecutive unhealthy days before halting the pair.
CONSECUTIVE_DAYS_TO_HALT = 5

# Maximum simultaneous pairs positions (capital constraint).
MAX_CONCURRENT_PAIRS = 3


def _load_close_series(symbol: str, timeframe: str, days: int) -> pd.Series:
    from_dt = datetime.now(timezone.utc) - timedelta(days=days)
    df = read_candles(symbol, timeframe=timeframe, from_dt=from_dt)
    if df.empty:
        return pd.Series(dtype=float)
    return df.set_index("timestamp")["close"].astype(float)


def check_pair_health(
    sym_a: str,
    sym_b: str,
    timeframe: str = "1day",
    rolling_window_days: int = 150,
    pvalue_threshold: float = HEALTH_PVALUE_THRESHOLD,
) -> tuple[Optional[bool], float]:
    """
    Check whether a pair is still cointegrated over a recent rolling window.

    Returns ``(is_healthy, pvalue)``. ``is_healthy`` is a TRI-STATE:
      • True  — cointegration intact (pvalue < threshold),
      • False — cointegration broken (pvalue ≥ threshold),
      • None  — could NOT be tested (missing data or too few aligned observations).

    The None case must NOT be treated as "broken": conflating a holiday/data gap with
    a real cointegration break silently halts healthy, profitable pairs (the window is
    only ~107 weekdays and the test needs ≥60 aligned obs). The window default is 150
    calendar days for headroom over NSE holidays.
    """
    price_a = _load_close_series(sym_a, timeframe, rolling_window_days)
    price_b = _load_close_series(sym_b, timeframe, rolling_window_days)
    if price_a.empty or price_b.empty:
        logger.warning(f"{sym_a}-{sym_b}: missing data for health check — not testable")
        return None, 1.0

    result = test_pair(price_a, price_b)
    if result is None:
        logger.warning(f"{sym_a}-{sym_b}: too few aligned observations — health not testable")
        return None, 1.0

    pvalue = result["pvalue"]
    healthy = pvalue < pvalue_threshold
    return healthy, pvalue


class PairsHealthTracker:
    """
    Tracks consecutive unhealthy days per pair and decides when to halt.

    Intended to be called once per day (post-market) for each active pair.
    """

    def __init__(self,
                 consecutive_days_to_halt: int = CONSECUTIVE_DAYS_TO_HALT,
                 max_concurrent_pairs: int = MAX_CONCURRENT_PAIRS):
        self.consecutive_days_to_halt = consecutive_days_to_halt
        self.max_concurrent_pairs = max_concurrent_pairs
        # pair_key -> consecutive unhealthy day count
        self._unhealthy_streak: dict[str, int] = {}
        # set of halted pair keys
        self._halted: set[str] = set()

    @staticmethod
    def _key(sym_a: str, sym_b: str) -> str:
        return f"{sym_a}-{sym_b}"

    def record_daily_check(self, sym_a: str, sym_b: str) -> dict:
        """
        Run a health check and update the streak. Returns a status dict with
        keys: pair, healthy, pvalue, streak, halted.
        """
        key = self._key(sym_a, sym_b)
        healthy, pvalue = check_pair_health(sym_a, sym_b)

        if healthy is None:
            # Not testable today (data gap / holidays) — do NOT count it toward the
            # halt streak. Leaving the streak unchanged avoids halting a healthy pair
            # just because the lookback couldn't run.
            logger.info(f"{key}: health not testable today — streak unchanged")
        elif healthy:
            self._unhealthy_streak[key] = 0
        else:
            self._unhealthy_streak[key] = self._unhealthy_streak.get(key, 0) + 1

        if self._unhealthy_streak.get(key, 0) >= self.consecutive_days_to_halt:
            if key not in self._halted:
                logger.warning(
                    f"HALTING pair {key}: unhealthy for "
                    f"{self._unhealthy_streak[key]} consecutive days"
                )
            self._halted.add(key)

        return {
            "pair": key,
            "healthy": healthy,
            "pvalue": pvalue,
            "streak": self._unhealthy_streak.get(key, 0),
            "halted": key in self._halted,
        }

    def is_halted(self, sym_a: str, sym_b: str) -> bool:
        return self._key(sym_a, sym_b) in self._halted

    def can_open_new_pair(self, open_pairs_count: int) -> bool:
        """True if we are below the concurrent-pairs cap."""
        return open_pairs_count < self.max_concurrent_pairs

    def reset_pair(self, sym_a: str, sym_b: str) -> None:
        """Clear halt/streak for a pair (e.g. after re-validation)."""
        key = self._key(sym_a, sym_b)
        self._unhealthy_streak.pop(key, None)
        self._halted.discard(key)
