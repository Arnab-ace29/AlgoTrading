"""
Ranking features and the screener score formula.

PURE numpy/stdlib — no pandas, no settings, no DB. This is the scoring core, so
it is fully unit-testable in isolation (see scripts/test_screener.py). The pandas
/ SQLite loading lives in daily_screener.py.

No look-ahead: compute_metrics() only uses bars strictly before `asof`.

Screener score (from MASTER_PLAN.md):
    0.30 * technical_setup        (breakout proximity + above SMA20)
  + 0.25 * momentum_rank          (cross-sectional 20-day return rank, set by caller)
  + 0.20 * volume_surge
  + 0.15 * volatility_opportunity (ATR percentile sweet spot 40–80th)
  + 0.10 * catalyst              (earnings / bulk deal / FII, set by caller)
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

MIN_BARS = 25   # need ≥21 for 20-day return + warm-up

WEIGHTS = {
    "technical_setup":         0.30,
    "momentum_rank":           0.25,
    "volume_surge":            0.20,
    "volatility_opportunity":  0.15,
    "catalyst":                0.10,
}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


def compute_metrics(
    dates: Sequence,
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    asof,
) -> Optional[dict]:
    """
    Compute per-symbol ranking metrics + symbol-local partial scores from daily
    OHLCV. Uses only bars with date < asof. Returns None if insufficient history.
    """
    try:
        idx = [i for i in range(len(dates)) if dates[i] < asof]
        if len(idx) < MIN_BARS:
            return None
        h = np.asarray([highs[i]   for i in idx], dtype=float)
        l = np.asarray([lows[i]    for i in idx], dtype=float)
        c = np.asarray([closes[i]  for i in idx], dtype=float)
        v = np.asarray([volumes[i] for i in idx], dtype=float)
        # Reject ANY non-positive close, not just the last one: a zero interior
        # close (e.g. a corrupt resampled bar at c[-6]/c[-21]) would make ret_5d/
        # ret_20d +inf, which then ranks top cross-sectionally — junk straight into
        # the watchlist (screener inf-return guard).
        if not np.all(np.isfinite(c)) or np.any(c <= 0):
            return None

        ret_5d  = float(c[-1] / c[-6]  - 1.0)
        ret_20d = float(c[-1] / c[-21] - 1.0)
        if not (np.isfinite(ret_5d) and np.isfinite(ret_20d)):
            return None

        # Volume surge vs the PRIOR 20 bars, excluding the current bar — otherwise a
        # genuine surge inflates its own denominator and the signal is damped
        # (volume_surge self-baseline). MIN_BARS=25 guarantees ≥24 prior bars.
        prior20_vol = v[-21:-1]
        avg_vol = float(np.mean(prior20_vol)) if prior20_vol.size else 0.0
        vol_surge = float(v[-1] / avg_vol) if avg_vol > 0 else 1.0

        # Daily ATR(14) as % of close + its percentile over recent history.
        prev_close = c[:-1]
        tr = np.maximum.reduce([
            h[1:] - l[1:],
            np.abs(h[1:] - prev_close),
            np.abs(l[1:] - prev_close),
        ])
        atr_pct_series = _rolling_mean(tr, 14) / c[1:]
        atr_pct_series = atr_pct_series[np.isfinite(atr_pct_series)]
        atr_pct = float(atr_pct_series[-1]) if atr_pct_series.size else 0.0
        recent = atr_pct_series[-60:] if atr_pct_series.size else np.array([atr_pct])
        atr_percentile = float(np.mean(recent <= atr_pct)) if recent.size else 0.5

        high20 = float(np.max(h[-20:]))
        dist_to_high20 = float(c[-1] / high20 - 1.0) if high20 > 0 else 0.0
        sma20 = float(np.mean(c[-20:]))
        above_sma20 = bool(c[-1] > sma20)

        std20 = float(np.std(c[-20:]))
        bandwidth = (4.0 * std20 / sma20) if sma20 > 0 else 0.0
        bw_series = _rolling_bandwidth(c, 20)
        bw_recent = bw_series[-60:] if bw_series.size else np.array([bandwidth])
        bb_squeeze = bool(np.mean(bw_recent <= bandwidth) <= 0.30) if bw_recent.size else False

        # Symbol-local partial scores (0..1). momentum_rank is cross-sectional → caller.
        proximity = _clamp(1.0 - abs(dist_to_high20) / 0.05)   # within 5% of 20d high
        technical_setup = _clamp(0.6 * proximity + 0.4 * (1.0 if above_sma20 else 0.0))
        volume_surge_score = _clamp((vol_surge - 1.0) / 2.0)   # 1×→0, 3×→1
        volatility_opportunity = _vol_opportunity(atr_percentile)

        return {
            "ret_5d":                 round(ret_5d, 5),
            "ret_20d":                round(ret_20d, 5),
            "vol_surge":              round(vol_surge, 3),
            "atr_pct":                round(atr_pct, 5),
            "atr_percentile":         round(atr_percentile, 3),
            "dist_to_high20":         round(dist_to_high20, 5),
            "above_sma20":            above_sma20,
            "bb_squeeze":             bb_squeeze,
            "technical_setup":        round(technical_setup, 4),
            "volume_surge":           round(volume_surge_score, 4),
            "volatility_opportunity": round(volatility_opportunity, 4),
        }
    except Exception:
        return None


def _rolling_mean(arr: np.ndarray, w: int) -> np.ndarray:
    """Trailing rolling mean; positions < w-1 are NaN."""
    if arr.size < w:
        return np.full(arr.shape, np.nan)
    cs = np.cumsum(np.insert(arr, 0, 0.0))
    out = np.full(arr.shape, np.nan)
    out[w - 1:] = (cs[w:] - cs[:-w]) / w
    return out


def _rolling_bandwidth(c: np.ndarray, w: int) -> np.ndarray:
    """Bollinger bandwidth (4·std/sma) over a trailing window."""
    if c.size < w:
        return np.array([])
    out = []
    for i in range(w - 1, c.size):
        win = c[i - w + 1:i + 1]
        sma = float(np.mean(win))
        out.append((4.0 * float(np.std(win)) / sma) if sma > 0 else 0.0)
    return np.asarray(out, dtype=float)


def _vol_opportunity(p: float) -> float:
    """Triangular preference peaking around the 40–80th ATR percentile band."""
    if p <= 0.10 or p >= 0.95:
        return 0.0
    return _clamp(1.0 - abs(p - 0.60) / 0.40)


def momentum_rank(values: Sequence[Optional[float]]) -> list[Optional[float]]:
    """
    Cross-sectional percentile rank (0..1) of each value within the universe.
    None values pass through as None. Uses mid-rank for ties.
    """
    present = [x for x in values if x is not None]
    n = len(present)
    if n == 0:
        return [None for _ in values]
    arr = np.asarray(present, dtype=float)
    out: list[Optional[float]] = []
    for x in values:
        if x is None:
            out.append(None)
        else:
            below = float(np.sum(arr < x))
            equal = float(np.sum(arr == x))
            out.append((below + 0.5 * equal) / n)
    return out


def screener_score(
    technical_setup: float,
    momentum_rank: float,
    volume_surge: float,
    volatility_opportunity: float,
    catalyst: float,
) -> float:
    """
    Weighted screener score. Inputs are 0..1 except catalyst, which is clamped to
    [-0.3, 1.0] so the catalyst detector's event-risk suppression (e.g. a board
    meeting today returns -0.3) actually PENALISES the score below a neutral
    symbol's, instead of being floored to 0 and ranking equal to a no-catalyst name.
    """
    w = WEIGHTS
    s = (
        w["technical_setup"]        * _clamp(technical_setup) +
        w["momentum_rank"]          * _clamp(momentum_rank) +
        w["volume_surge"]           * _clamp(volume_surge) +
        w["volatility_opportunity"] * _clamp(volatility_opportunity) +
        w["catalyst"]               * _clamp(catalyst, lo=-0.3, hi=1.0)
    )
    return round(float(s), 5)
