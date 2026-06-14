"""
Run an H1 cross-sectional-ranking backtest and write the result artifacts.

    python scripts/run_backtest.py                          # default: last 1yr, all symbols
    python scripts/run_backtest.py --from 2025-09-01 --to 2026-03-01
    python scripts/run_backtest.py --top-pct 0.02 --min-rvol 2.5 --limit 150

Outputs land in backtest/results/<run_id>/  (trades.csv, summary.md, summary.json, equity_curve.csv).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger

from config.settings import DB_PATH
from backtest.engine import BacktestConfig, run_backtest
from backtest.report import write_run
from strategy.ranking import RankParams
from strategy.sizing import SizingParams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_date", default="2025-06-01")
    ap.add_argument("--to",   dest="to_date",   default="2026-06-01")
    ap.add_argument("--entry", default="09:45")
    ap.add_argument("--time-stop", default="10:30")
    ap.add_argument("--top-pct", type=float, default=0.01)
    ap.add_argument("--min-rvol", type=float, default=2.0)
    ap.add_argument("--max-per-side", type=int, default=3)
    ap.add_argument("--atr-stop", type=float, default=1.5)
    ap.add_argument("--atr-trail", type=float, default=2.0)
    ap.add_argument("--slippage", type=float, default=0.005)
    ap.add_argument("--capital", type=float, default=20_000.0)
    ap.add_argument("--risk-pct", type=float, default=0.01)
    ap.add_argument("--limit", type=int, default=0, help="cap universe size (0 = all)")
    args = ap.parse_args()

    # Universe: all symbols with 5-min coverage (optionally capped for a fast run).
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    syms = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM minute_candles WHERE timeframe='5min'").fetchall())
    conn.close()
    # Drop index/macro pseudo-symbols (they aren't tradable equities).
    drop = {"INDIAVIX", "NIFTY50", "NIFTY50_YF", "NIFTYNEXT50", "NIFTYBANK", "NIFTYIT",
            "NIFTYFMCG", "NIFTYPHARMA", "NIFTYAUTO", "NIFTYMETAL", "NIFTYREALTY",
            "NIFTYINFRA", "SP500", "NASDAQ"}
    syms = [s for s in syms if s not in drop]
    if args.limit:
        syms = syms[:args.limit]

    cfg = BacktestConfig(
        from_date=args.from_date, to_date=args.to_date,
        entry_time=args.entry, time_stop=args.time_stop,
        atr_stop_mult=args.atr_stop, atr_trail_mult=args.atr_trail,
        slippage_pct=args.slippage, capital=args.capital, symbols=syms,
        rank=RankParams(entry_time_ist=args.entry, top_pct=args.top_pct,
                        min_rvol=args.min_rvol, max_per_side=args.max_per_side),
        sizing=SizingParams(base_risk_pct=args.risk_pct),
    )

    trades = run_backtest(cfg)
    res = write_run(trades, cfg)
    logger.success(f"Run {res['run_id']} → {res['dir']}")
    m = res["metrics"]
    if m.get("total_trades"):
        logger.info(f"  trades={m['total_trades']}  win%={m['win_rate']}  "
                    f"expectancy_R={m['expectancy_R']}  netPnL={m['net_pnl']}  "
                    f"Sharpe={m['sharpe']}  maxDD%={m['max_drawdown_pct']}")
    else:
        logger.warning("  No trades — adjust filters.")


if __name__ == "__main__":
    main()
