"""
Shared training-data loader for Phase 2 ML models.

Reads candles from SQLite (via data.db.read_candles) and computes features
per-symbol so rolling/shift operations never leak across instrument
boundaries. Returns a single stacked DataFrame with a 'symbol' column that
downstream model.train() methods group on.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pandas as pd
from loguru import logger

from data.db import read_candles
from features.indicators import compute_all_features, MIN_BARS_REQUIRED


def _to_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """Set the timestamp column as a sorted DatetimeIndex (required by features)."""
    if "timestamp" in df.columns:
        df = df.set_index("timestamp")
    df = df.sort_index()
    return df


def load_candles_with_features(
    symbols: list[str],
    timeframe: str = "5min",
    days: int = 180,
    compute_features: bool = True,
) -> pd.DataFrame:
    """
    Load candles for the given symbols/timeframe from SQLite and (optionally)
    compute the full feature set per symbol.

    Returns a stacked DataFrame (one block per symbol) with a 'symbol' column
    and a DatetimeIndex. Symbols with insufficient data are skipped.
    """
    from_dt = datetime.now(timezone.utc) - timedelta(days=days)
    frames: list[pd.DataFrame] = []

    for symbol in symbols:
        raw = read_candles(symbol, timeframe=timeframe, from_dt=from_dt)
        if raw.empty:
            logger.warning(f"{symbol} {timeframe}: no candles in SQLite")
            continue
        if len(raw) < MIN_BARS_REQUIRED:
            logger.warning(f"{symbol} {timeframe}: only {len(raw)} bars (<{MIN_BARS_REQUIRED}), skipping")
            continue

        df = _to_datetime_index(raw)
        if compute_features:
            try:
                df = compute_all_features(df)
            except Exception as e:
                logger.warning(f"{symbol}: feature computation failed: {e}")
                continue
        df["symbol"] = symbol
        frames.append(df)
        logger.info(f"{symbol} {timeframe}: loaded {len(df)} bars")

    if not frames:
        raise ValueError(
            f"No usable data for any of {symbols} ({timeframe}). "
            f"Backfill first: python data/upstox_history.py --tf {timeframe}"
        )

    combined = pd.concat(frames)
    logger.info(f"Total bars loaded across {len(frames)} symbols: {len(combined)}")
    return combined
