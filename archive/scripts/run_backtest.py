"""
Backtest runner — runs the full ensemble strategy on real SQLite candles.

Usage:
    # Default: INSTRUMENTS list, last 500 days, walk-forward
    python scripts/run_backtest.py --days 500

    # Single symbol, no walk-forward
    python scripts/run_backtest.py --days 365 --symbols RELIANCE TCS INFY --no-wf

    # Grid search: 12 configs (entry_threshold × score_tier)
    python scripts/run_backtest.py --days 500 --grid

    # Full universe from DB (slow — uses all symbols with ≥150 days data)
    python scripts/run_backtest.py --days 500 --full-universe
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from backtest.engine import BacktestEngine
from config.settings import INSTRUMENTS, DB_PATH
import sqlite3


def _get_symbols_with_data(min_days: int = 150) -> list[str]:
    """Return symbols that have at least min_days worth of 5min candles."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT symbol, COUNT(*) as bars FROM minute_candles "
        "WHERE timeframe = '5min' AND source IN ('upstox_hist', 'replay_fetch') "
        "GROUP BY symbol HAVING bars >= ? ORDER BY bars DESC",
        [min_days * 46],   # ~46 five-min bars per trading day
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def run_single(symbols: list[str], days: int, walk_forward: bool,
               use_ml_gates: bool = True, label: str = "") -> dict:
    to_date   = datetime.now()
    from_date = to_date - timedelta(days=days)

    logger.info(f"{'─'*60}")
    logger.info(f"Backtest {label or ''}: {len(symbols)} symbols | {from_date.date()} → {to_date.date()} | wf={walk_forward} | ml_gates={use_ml_gates}")

    engine = BacktestEngine(use_ml_gates=use_ml_gates)
    result = engine.run(
        symbols    = symbols,
        from_date  = from_date.strftime("%Y-%m-%d"),
        to_date    = to_date.strftime("%Y-%m-%d"),
        timeframe  = "5min",
        walk_forward = walk_forward,
    )
    result.save()
    s = result.summary()
    _print_summary(s, label)
    return s


def _print_summary(s: dict, label: str = "") -> None:
    title = f"  Result {label}  " if label else "  Result  "
    print(f"\n{'='*55}")
    print(f"{title:^55}")
    print(f"{'='*55}")
    print(f"  Trades      : {s['total_trades']}   (W:{s.get('wins',0)} / L:{s.get('losses',0)})")
    print(f"  Win rate    : {s['win_rate']:.1f}%")
    print(f"  Total return: {s['total_return']:.2f}%")
    print(f"  Sharpe      : {s['sharpe']:.3f}")
    print(f"  Max drawdown: {s['max_drawdown']:.2f}%")
    print(f"  Avg trade   : {s['avg_trade_pct']:.3f}%")
    print(f"  Profit factor: {s.get('profit_factor', 'N/A')}")
    print(f"  Net PnL     : ₹{s['net_pnl']:,.0f}  (costs ₹{s['costs']:,.0f})")
    if s.get("per_fold"):
        print(f"  Walk-forward folds: {len(s['per_fold'])}")
        for i, f in enumerate(s["per_fold"], 1):
            print(f"    Fold {i}: trades={f['total_trades']}  ret={f['total_return']:.1f}%  sharpe={f['sharpe']:.2f}")
    print(f"  Saved to    : {s.get('result_path', 'N/A')}")
    print(f"{'='*55}\n")


def run_grid(symbols: list[str], days: int) -> None:
    """Grid search over ENTRY_SCORE_THRESHOLD × SCORE_TIER_TRADE."""
    from config import settings as cfg

    entry_thresholds = [0.60, 0.65, 0.68]
    score_tiers      = [0.65, 0.70, 0.75, 0.80]

    orig_entry = cfg.ENTRY_SCORE_THRESHOLD
    orig_tier  = cfg.SCORE_TIER_TRADE

    results = []
    for et in entry_thresholds:
        for st in score_tiers:
            cfg.ENTRY_SCORE_THRESHOLD = et
            cfg.SCORE_TIER_TRADE      = st
            label = f"et={et} st={st}"
            s = run_single(symbols, days, walk_forward=False, label=label)
            results.append({"entry_threshold": et, "score_tier": st, **s})

    cfg.ENTRY_SCORE_THRESHOLD = orig_entry
    cfg.SCORE_TIER_TRADE      = orig_tier

    print("\n" + "="*65)
    print(f"{'GRID SEARCH SUMMARY':^65}")
    print("="*65)
    print(f"  {'et':>5}  {'st':>5}  {'trades':>7}  {'ret%':>7}  {'sharpe':>7}  {'dd%':>6}")
    print("  " + "-"*55)
    for r in sorted(results, key=lambda x: x["sharpe"], reverse=True):
        print(f"  {r['entry_threshold']:>5.2f}  {r['score_tier']:>5.2f}  "
              f"{r['total_trades']:>7}  {r['total_return']:>7.2f}  "
              f"{r['sharpe']:>7.3f}  {r['max_drawdown']:>6.2f}")
    print("="*65)
    best = max(results, key=lambda x: x["sharpe"])
    print(f"\nBest config by Sharpe: entry_threshold={best['entry_threshold']}  "
          f"score_tier={best['score_tier']}  Sharpe={best['sharpe']:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run backtest on real SQLite candles")
    parser.add_argument("--days",         type=int,   default=500,
                        help="Lookback window in calendar days (default: 500)")
    parser.add_argument("--symbols",      nargs="+",  default=None,
                        help="Symbols to test (default: INSTRUMENTS from settings)")
    parser.add_argument("--full-universe", action="store_true",
                        help="Use all symbols in DB with ≥150 days of data")
    parser.add_argument("--no-wf",        action="store_true",
                        help="Disable walk-forward (single pass, faster)")
    parser.add_argument("--grid",         action="store_true",
                        help="Grid search over entry_threshold × score_tier")
    parser.add_argument("--no-ml",        action="store_true",
                        help="Skip ML gates (faster, rule-based only — useful for debugging signals)")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="INFO")

    if args.full_universe:
        symbols = _get_symbols_with_data(min_days=150)
        logger.info(f"Full universe: {len(symbols)} symbols with ≥150 days data")
    elif args.symbols:
        symbols = args.symbols
    else:
        symbols = INSTRUMENTS
        logger.info(f"Using default INSTRUMENTS ({len(symbols)} symbols)")

    if not symbols:
        print("No symbols found. Run backfill first.")
        return 1

    if args.grid:
        run_grid(symbols, args.days)
    else:
        run_single(symbols, args.days, walk_forward=not args.no_wf, use_ml_gates=not args.no_ml)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
