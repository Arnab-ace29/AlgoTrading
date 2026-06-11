"""
Daily Model Retraining Pipeline - Phase 2
Runs post-market (after 15:30 IST) to retrain all ML models.

Pipeline:
1. Load last 180-day rolling window of candles
2. Retrain macro model (incremental_train.py)
3. Retrain micro model
4. Retrain RL exit agent (train_rl_on_journeys.py, 50 epochs)
5. Backup old models to models/saved/backups/YYYYMMDD/
6. Log: new vs old AUC, training duration, sample count
7. Send Telegram summary

Usage:
    python scripts/retrain_daily.py
"""

from __future__ import annotations
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import sqlite3
import pandas as pd
from datetime import datetime
import shutil
import json
from typing import Dict, Any, List
from loguru import logger

from signals.ml.macro_model import get_macro_model, MacroXGBoostModel
from signals.ml.micro_model import get_micro_model, MicroXGBoostModel
from models.rl_exit_agent import get_rl_exit_agent
from models._data_loader import load_candles_with_features
from models.promotion import champion_challenger
from config.settings import INSTRUMENTS, MODELS_DIR, DB_PATH

# Promote a challenger only if it beats the live model by at least this AUC margin.
PROMOTION_MARGIN = 0.0

# Macro training: max symbols to load with full features (each ~24 MB RAM after feature compute).
# 100 symbols × 730 days × 86 features ≈ 2.3 GB — safe default for 16 GB systems.
# 200 symbols ≈ 4.6 GB, 400 symbols ≈ 9.2 GB (causes OOM on 16 GB — avoid).
# Micro training: all symbols in DB (OHLCV-only, ~200 MB for 739 symbols × 180 days).
_MACRO_MAX_SYMBOLS = 100
_MB_PER_MACRO_SYMBOL = 24  # ~24 MB per symbol after feature computation


def _get_universe_from_db(timeframe: str = "5min", max_symbols: int = 0) -> list[str]:
    """Return symbols from minute_candles ordered by bar count DESC (most data first).
    max_symbols=0 means all symbols.
    """
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT symbol, COUNT(*) as bars FROM minute_candles "
        "WHERE timeframe = ? AND source IN ('upstox_hist', 'replay_fetch') "
        "GROUP BY symbol ORDER BY bars DESC",
        [timeframe],
    ).fetchall()
    conn.close()
    symbols = [r[0] for r in rows]
    if max_symbols and len(symbols) > max_symbols:
        logger.info(f"Universe: {len(symbols)} symbols in DB, capping at {max_symbols} (most data first)")
        symbols = symbols[:max_symbols]
    else:
        logger.info(f"Universe: {len(symbols)} symbols loaded from DB")
    if max_symbols:
        est_gb = (max_symbols * _MB_PER_MACRO_SYMBOL) / 1024
        logger.info(f"Estimated macro RAM usage: ~{est_gb:.1f} GB ({max_symbols} symbols × {_MB_PER_MACRO_SYMBOL} MB each)")
    return symbols


def create_backup_directory() -> Path:
    """Create backup directory with today's date."""
    today = datetime.now().strftime("%Y%m%d")
    backup_dir = Path("models/saved/backups") / today
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def backup_existing_models(backup_dir: Path) -> None:
    """Backup existing models before retraining."""
    logger.info(f"Backing up existing models to {backup_dir}")
    
    model_files = [
        "models/saved/macro_xgb.pkl",
        "models/saved/micro_xgb.pkl", 
        "models/saved/rl_exit_agent.pkl"
    ]
    
    for model_file in model_files:
        src = Path(model_file)
        if src.exists():
            dst = backup_dir / src.name
            shutil.copy2(src, dst)
            logger.info(f"Backed up {src.name}")


def load_macro_data(symbols: List[str], days: int = 180) -> pd.DataFrame:
    """Load 5-min candles with full features for the macro model."""
    return load_candles_with_features(symbols, timeframe="5min", days=days)


def load_micro_data(symbols: List[str], days: int = 45) -> pd.DataFrame:
    """
    Load 5-min candles (raw OHLCV) for the micro model. The micro model is SERVED
    on the primary 5-min feed in live/runner.py, so it must be TRAINED on 5-min too
    — training on 1-min (the old behaviour) made its features/threshold meaningless
    at serve time (train/serve skew).
    """
    return load_candles_with_features(symbols, timeframe="5min", days=days,
                                      compute_features=False)


def retrain_macro_model(df_5min: pd.DataFrame) -> Dict[str, Any]:
    """Retrain the macro model via champion/challenger (20-day out-of-sample holdout)."""
    logger.info("Retraining macro XGBoost model (champion/challenger)...")
    return champion_challenger(
        "macro_xgb", get_macro_model(),
        lambda: MacroXGBoostModel(model_path=Path(MODELS_DIR) / "_challenger_macro.pkl"),
        df_5min, holdout_days=20, margin=PROMOTION_MARGIN,
    )


def retrain_micro_model(df_5min: pd.DataFrame) -> Dict[str, Any]:
    """Retrain the micro model via champion/challenger (5-day out-of-sample holdout).
    Trains on 5-min data to match the live serving timeframe (no train/serve skew)."""
    logger.info("Retraining micro XGBoost model (champion/challenger)...")
    return champion_challenger(
        "micro_xgb", get_micro_model(),
        lambda: MicroXGBoostModel(model_path=Path(MODELS_DIR) / "_challenger_micro.pkl"),
        df_5min, holdout_days=5, margin=PROMOTION_MARGIN,
    )


def retrain_rl_exit_agent() -> Dict[str, Any]:
    """Retrain the RL exit agent."""
    logger.info("Retraining RL exit agent...")
    
    start_time = datetime.now()
    
    # Reconstruct journeys from the real trade_log; bootstrap with synthetic
    # journeys until enough live trades have accumulated.
    from models.train_rl_on_journeys import (
        build_journeys_from_trade_log, create_synthetic_trade_journeys,
    )
    
    journeys = build_journeys_from_trade_log()
    if len(journeys) < 20:
        logger.warning(
            f"Only {len(journeys)} real journeys; bootstrapping with synthetic."
        )
        journeys = create_synthetic_trade_journeys(n_journeys=200)
    
    # Train agent and persist it (the old pipeline never saved the exit agent).
    agent = get_rl_exit_agent()
    metrics = agent.train_on_historical_trades(journeys)
    agent.save_model()

    training_time = (datetime.now() - start_time).total_seconds()
    
    result = {
        'model': 'rl_exit_agent',
        'old_avg_reward': None,  # Could track previous performance
        'new_avg_reward': metrics['avg_reward'],
        'reward_change': None,
        'training_episodes': metrics['total_episodes'],
        'training_time_seconds': training_time,
        'q_table_size': metrics['q_table_size'],
        'timestamp': datetime.now().isoformat()
    }
    
    logger.info(f"RL exit agent retrained: Avg reward {metrics['avg_reward']:.3f}")
    
    return result


def retrain_strategy_outcomes() -> Dict[str, Any]:
    """Retrain per-strategy WIN/LOSS outcome models from the trade_log."""
    logger.info("Retraining strategy outcome models...")
    start_time = datetime.now()

    from models.train_outcomes import build_training_frames
    from signals.ml.strategy_outcomes import get_outcome_models
    from features.indicators import FEATURE_COLUMNS

    frames = build_training_frames()
    models = get_outcome_models()
    trained: list[str] = []
    for strategy, df in frames.items():
        metrics = models.train_strategy(strategy, df, list(FEATURE_COLUMNS))
        if metrics:
            trained.append(strategy)
    if trained:
        models.save_model()

    training_time = (datetime.now() - start_time).total_seconds()
    note = f"trained {len(trained)} strategies" if trained else "insufficient trades (<15/strategy)"
    logger.info(f"Strategy outcome models: {note}")
    return {
        'model': 'strategy_outcomes',
        'trained_strategies': trained,
        'training_time_seconds': training_time,
        'note': note,
        'timestamp': datetime.now().isoformat(),
    }


def retrain_rl_entry_agent() -> Dict[str, Any]:
    """Retrain the RL entry agent from logged entry decisions."""
    logger.info("Retraining RL entry agent...")
    start_time = datetime.now()

    from models.train_rl_entry import build_entry_decisions, create_synthetic_entry_decisions
    from models.rl_entry_agent import get_rl_entry_agent

    decisions = build_entry_decisions()
    used_synthetic = False
    if len(decisions) < 50:
        logger.warning(f"Only {len(decisions)} real entry decisions; bootstrapping synthetic.")
        decisions = create_synthetic_entry_decisions()
        used_synthetic = True

    agent = get_rl_entry_agent()
    # Synthetic bootstrap must not trip the activation gate (RL-03).
    metrics = agent.train_on_decisions(decisions, count_for_activation=not used_synthetic)
    agent.save_model()

    training_time = (datetime.now() - start_time).total_seconds()
    return {
        'model': 'rl_entry_agent',
        'new_avg_reward': metrics['avg_reward'],
        'training_episodes': metrics['total_episodes'],
        'q_table_size': metrics['q_table_size'],
        'active': agent.is_active(),
        'training_time_seconds': training_time,
        'timestamp': datetime.now().isoformat(),
    }


def save_training_report(results: List[Dict[str, Any]], backup_dir: Path) -> None:
    """Save training report to backup directory."""
    report = {
        'retraining_date': datetime.now().isoformat(),
        'results': results,
        'summary': {
            'models_retrained': len(results),
            'total_training_time': sum(r.get('training_time_seconds', 0) for r in results),
            'performance_improved': sum(1 for r in results 
                                     if r.get('auc_change') and r['auc_change'] > 0)
        }
    }
    
    report_file = backup_dir / "retraining_report.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"Training report saved to {report_file}")


def send_telegram_summary(results: List[Dict[str, Any]]) -> None:
    """Send summary to Telegram (placeholder)."""
    logger.info("Telegram summary integration not implemented yet")
    
    summary = "🤖 Daily Model Retraining Summary\n"
    summary += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    
    for result in results:
        model_name = result['model'].replace('_', ' ').title()
        if 'new_auc' in result and result['new_auc'] is not None:
            change = result.get('auc_change')
            change_str = f" ({change:+.3f})" if change else ""
            summary += f"📊 {model_name}: AUC {result['new_auc']:.3f}{change_str}\n"
        elif 'new_avg_reward' in result and result['new_avg_reward'] is not None:
            summary += f"🧠 {model_name}: Reward {result['new_avg_reward']:.3f}\n"
        else:
            summary += f"📝 {model_name}: {result.get('note', 'updated')}\n"
    
    total_time = sum(r.get('training_time_seconds', 0) for r in results)
    summary += f"\n⏱️ Total time: {total_time:.1f}s"
    
    logger.info(f"Summary: {summary}")


def run_daily_retraining(args=None):
    """Main daily retraining pipeline."""
    if args is None:
        import argparse
        args = argparse.Namespace(full_universe=False, max_symbols=_MACRO_MAX_SYMBOLS)
    logger.info("Starting daily model retraining pipeline...")
    
    try:
        # Create backup directory
        backup_dir = create_backup_directory()
        
        # Backup existing models
        backup_existing_models(backup_dir)
        
        # Load training data per timeframe from SQLite
        results = []

        macro_symbols = _get_universe_from_db("5min", max_symbols=args.max_symbols) if args.full_universe else INSTRUMENTS
        micro_symbols  = _get_universe_from_db("5min", max_symbols=0)              if args.full_universe else INSTRUMENTS
        logger.info(f"Macro training symbols: {len(macro_symbols)} | Micro training symbols: {len(micro_symbols)}")

        # Retrain macro model on 5-min data (with full features)
        try:
            df_5min = load_macro_data(macro_symbols, days=730)
            results.append(retrain_macro_model(df_5min))
        except Exception as e:
            logger.warning(f"Skipping macro retrain: {e}")

        # Retrain micro model on 5-min data (raw OHLCV, all symbols)
        try:
            df_micro = load_micro_data(micro_symbols, days=180)
            results.append(retrain_micro_model(df_micro))
        except Exception as e:
            logger.warning(f"Skipping micro retrain: {e}")
        
        # Retrain RL exit agent
        results.append(retrain_rl_exit_agent())

        # Retrain strategy outcome models (only trains strategies with >=15 trades)
        try:
            results.append(retrain_strategy_outcomes())
        except Exception as e:
            logger.warning(f"Skipping strategy outcome retrain: {e}")

        # Retrain RL entry agent
        try:
            results.append(retrain_rl_entry_agent())
        except Exception as e:
            logger.warning(f"Skipping RL entry retrain: {e}")
        
        # Save report
        save_training_report(results, backup_dir)
        
        # Send summary
        send_telegram_summary(results)
        
        logger.info("Daily retraining completed successfully!")
        
    except Exception as e:
        logger.error(f"Daily retraining failed: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily model retraining pipeline")
    parser.add_argument(
        "--full-universe", action="store_true",
        help="Train on all symbols in the DB instead of just INSTRUMENTS. "
             "Macro capped at --max-symbols (RAM guard). Micro uses all symbols.",
    )
    parser.add_argument(
        "--max-symbols", type=int, default=_MACRO_MAX_SYMBOLS,
        help=f"Max symbols for macro model when --full-universe is set (default: {_MACRO_MAX_SYMBOLS}). "
             "Each symbol adds ~24 MB RAM. 200 ≈ 4 GB, 400 ≈ 8 GB.",
    )
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="INFO")
    logger.add("logs/retrain_daily.log", rotation="1 day", retention="30 days")

    try:
        run_daily_retraining(args)
        print("\n✅ Daily retraining completed successfully!")
    except Exception as e:
        print(f"\n❌ Retraining failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
