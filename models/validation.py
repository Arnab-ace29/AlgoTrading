"""
Leakage-safe validation splits for the Phase 2 ML models.

Two helpers:
  • purged_split  — per-symbol chronological train/val split with an embargo gap,
    so a training label's look-ahead window cannot overlap the validation block
    and the validation block is always the *latest* bars per symbol (fixes ML-01/02).
  • time_holdout_split — split a DatetimeIndexed frame into (fit, holdout) by
    calendar time, for champion/challenger out-of-sample evaluation (RETRAIN-02).

Pure pandas — no model/lib deps, unit-testable in isolation.
"""

from __future__ import annotations

from typing import Sequence, Tuple

import pandas as pd


def purged_split(
    frames: Sequence[Tuple[pd.DataFrame, pd.Series]],
    test_frac: float = 0.2,
    embargo: int = 0,
) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """
    Chronological train/val split applied PER SYMBOL, then pooled.

    frames: list of (X, y) per symbol, each already in time order.
    Per symbol: the first (1 - test_frac) rows are train, the last test_frac are
    validation. The final `embargo` rows of each train block are dropped so that a
    train row whose label looks `embargo` bars ahead cannot peek into validation.

    Returns pooled (X_train, y_train, X_val, y_val).
    """
    Xtr, ytr, Xva, yva = [], [], [], []
    for X, y in frames:
        n = len(X)
        if n < 5:
            continue
        cut = int(round(n * (1.0 - test_frac)))
        cut = min(max(cut, 1), n - 1)            # both sides non-empty
        train_end = max(0, cut - int(embargo))   # purge the label-horizon overlap
        if train_end > 0:
            Xtr.append(X.iloc[:train_end]); ytr.append(y.iloc[:train_end])
        Xva.append(X.iloc[cut:]); yva.append(y.iloc[cut:])

    if not Xtr or not Xva:
        raise ValueError("purged_split: not enough data to form train/validation sets")

    return (
        pd.concat(Xtr, ignore_index=True), pd.concat(ytr, ignore_index=True),
        pd.concat(Xva, ignore_index=True), pd.concat(yva, ignore_index=True),
    )


def time_holdout_split(df: pd.DataFrame, holdout_days: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split a DatetimeIndexed frame into (fit, holdout) where holdout is the most
    recent `holdout_days` calendar days across all symbols. Used to train a
    challenger on older data and score it on data it has never seen.
    """
    if df is None or len(df) == 0:
        return df, df
    tmax = df.index.max()
    cutoff = tmax - pd.Timedelta(days=holdout_days)
    fit = df[df.index < cutoff]
    holdout = df[df.index >= cutoff]
    return fit, holdout
