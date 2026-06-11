"""
Training script for Strategy Outcome Models - Phase 2 (Task 7.1)

For every closed trade in the trade_log, reconstruct the market feature vector
as it was at entry time (from candles up to entry_time), label it WIN/LOSS from
the realised PnL, group by strategy, and train one XGBoost win/loss classifier
per strategy.

Usage:
    python models/train_outcomes.py
"""

from __future__ import annotations
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from loguru import logger

from data.db import get_trade_log, read_candles
from features.indicators import compute_all_features, FEATURE_COLUMNS, MIN_BARS_REQUIRED
from signals.ml.strategy_outcomes import StrategyOutcomeModels


def reconstruct_entry_features(trade: pd.Series,
                               timeframe: str = "5min",
                               lookback_days: int = 10) -> pd.Series | None:
    """
    Rebuild the feature vector available at a trade's entry time.

    Loads candles ending at entry_time, computes features, and returns the
    last row (the bar at/just before entry). Returns None if data is thin.
    """
    entry_time = trade.get("entry_time")
    symbol = trade.get("symbol")
    if entry_time is None or symbol is None:
        return None

    from_dt = pd.Timestamp(entry_time) - timedelta(days=lookback_days)
    candles = read_candles(symbol, timeframe=timeframe, from_dt=from_dt, to_dt=entry_time)
    if candles.empty or len(candles) < MIN_BARS_REQUIRED:
        return None

    df = candles.set_index("timestamp").sort_index()
    try:
        feat = compute_all_features(df)
    except Exception as e:
        logger.warning(f"{symbol}: feature reconstruction failed: {e}")
        return None

    cols = [c for c in FEATURE_COLUMNS if c in feat.columns]
    # ffill only (no bfill) — we take the last row, which has no future to borrow.
    row = feat[cols].ffill().fillna(0.0).iloc[-1]
    return row


def build_training_frames() -> dict[str, pd.DataFrame]:
    """
    Build a per-strategy DataFrame of entry features + 'win' label from the
    closed trades in the trade_log.
    """
    trades = get_trade_log(limit=5000)
    if trades.empty:
        return {}

    closed = trades[trades["status"] == "CLOSED"].copy()
    per_strategy: dict[str, list[pd.Series]] = {}

    for _, t in closed.iterrows():
        pnl = t.get("pnl")
        if pnl is None:
            continue
        row = reconstruct_entry_features(t)
        if row is None:
            continue
        row = row.copy()
        row["win"] = 1 if float(pnl) > 0 else 0
        row["entry_time"] = pd.Timestamp(t.get("entry_time"))   # for chronological split (ML-02)
        per_strategy.setdefault(str(t.get("strategy", "unknown")), []).append(row)

    return {k: pd.DataFrame(v) for k, v in per_strategy.items() if v}


def train_and_evaluate():
    logger.info("Starting Strategy Outcome Model training")

    frames = build_training_frames()
    if not frames:
        print("\nNo closed trades available to train outcome models yet.")
        print("Outcome models activate after >=15 closed trades per strategy.")
        return

    feature_cols = list(FEATURE_COLUMNS)
    models = StrategyOutcomeModels()

    print("\n" + "=" * 60)
    print("STRATEGY OUTCOME MODEL TRAINING RESULTS")
    print("=" * 60)

    trained_any = False
    for strategy, df in frames.items():
        metrics = models.train_strategy(strategy, df, feature_cols)
        if metrics:
            trained_any = True
            auc = metrics["auc"]
            auc_str = f"{auc:.3f}" if auc == auc else "n/a"  # NaN check
            print(f"  {strategy:<18} n={metrics['n_trades']:<4} "
                  f"AUC={auc_str} acc={metrics['accuracy']:.3f}")
        else:
            print(f"  {strategy:<18} skipped (insufficient/!2-class data)")

    if trained_any:
        models.save_model()
        print("\nOutcome models saved.")
    else:
        print("\nNo strategy had enough data to train an outcome model.")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    try:
        train_and_evaluate()
        print("\nStrategy outcome training run complete.")
    except Exception as e:
        print(f"\nTraining failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
