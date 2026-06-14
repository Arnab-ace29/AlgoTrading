"""
Pure indicator functions — no I/O, no globals, no look-ahead.

Each function takes a price/OHLCV DataFrame (DatetimeIndex, UTC-stored) or Series and
returns a Series/scalar. They are shared verbatim by the backtest and (later) the live
runner, so a signal can never drift between research and production.

Candles are stored in UTC; session-relative features convert to IST (NSE 09:15-15:30).
Conventions: df has columns open/high/low/close/volume and a DatetimeIndex.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ── Time / session helpers ────────────────────────────────────────────────────
def to_ist(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """IST view of a candle index. tz-naive is assumed UTC (how we store)."""
    if not isinstance(index, pd.DatetimeIndex):
        return index
    try:
        if index.tz is None:
            return index.tz_localize("UTC").tz_convert("Asia/Kolkata")
        return index.tz_convert("Asia/Kolkata")
    except (TypeError, ValueError):
        return index


def session_day(index: pd.DatetimeIndex) -> pd.Series:
    """Calendar-day key (IST) for grouping bars into trading sessions."""
    ist = to_ist(index)
    return pd.Series(ist.normalize(), index=index)


# ── Trend / price ─────────────────────────────────────────────────────────────
def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Session-anchored VWAP, reset each trading day. Typical price (H+L+C)/3."""
    price = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"].fillna(0)
    pv = price * volume
    if isinstance(df.index, pd.DatetimeIndex):
        day = to_ist(df.index).normalize()
        cum_pv = pv.groupby(day).cumsum()
        cum_v = volume.groupby(day).cumsum().replace(0, np.nan)
        return cum_pv / cum_v
    return pv.rolling(78).sum() / volume.rolling(78).sum().replace(0, np.nan)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def ret(series: pd.Series, periods: int = 1) -> pd.Series:
    """Simple return over N periods."""
    return series.pct_change(periods)


# ── Volatility ────────────────────────────────────────────────────────────────
def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder). In price units — used for stops/targets."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ── Volume ────────────────────────────────────────────────────────────────────
def rvol_same_window(df: pd.DataFrame, lookback_days: int = 20) -> pd.Series:
    """
    Relative volume vs the SAME time-of-day window (EDGE_RESEARCH §H1/H3 note).

    A stock always trades more in the first 30 min, so comparing 9:20's volume to the
    full-day average is misleading. We compare each bar's volume to the trailing
    `lookback_days` average volume for THAT exact time-of-day slot (excluding today).

    Returns a Series of ratios (1.0 = average; 3.0 = 3x normal for that slot). No
    look-ahead: the baseline uses only prior days (shift(1) inside each slot group).
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("rvol_same_window requires a DatetimeIndex")
    ist = to_ist(df.index)
    slot = pd.Series(ist.strftime("%H:%M"), index=df.index)   # time-of-day key
    vol = df["volume"].fillna(0)
    # Trailing mean of volume for each slot, using only PRIOR days.
    baseline = (
        vol.groupby(slot)
           .transform(lambda s: s.shift(1).rolling(lookback_days, min_periods=3).mean())
    )
    return (vol / baseline.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def intraday_return_from_open(df: pd.DataFrame) -> pd.Series:
    """Return of close vs the session's first open, per bar (intraday momentum)."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("intraday_return_from_open requires a DatetimeIndex")
    day = to_ist(df.index).normalize()
    session_open = df["open"].groupby(day).transform("first")
    return (df["close"] - session_open) / session_open


# ── Cross-sectional helpers (operate across symbols at one timestamp) ──────────
def zscore(series: pd.Series) -> pd.Series:
    """Standardise a cross-section. NaN-safe; returns 0 where std is 0/undefined."""
    s = series.astype(float)
    mu, sd = s.mean(), s.std()
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=series.index)
    return (s - mu) / sd


def relative_strength(stock_close: pd.Series, index_close: pd.Series,
                      periods: int = 1) -> pd.Series:
    """Stock return / index return over N periods (momentum vs the market)."""
    sr = stock_close.pct_change(periods)
    ir = index_close.pct_change(periods)
    return sr - ir   # excess return (additive RS; robust when index return ~0)
