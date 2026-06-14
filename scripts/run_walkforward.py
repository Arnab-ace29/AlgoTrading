"""
Walk-forward validation of an H1 config: per-fold OOS stability + negative controls.

    python scripts/run_walkforward.py --fade --slippage 0.002 --folds 4
    python scripts/run_walkforward.py --fade --slippage 0.002 --from 2025-06-01 --to 2026-06-01

Writes backtest/results/wf_<id>.md and prints the verdict.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger

from config.settings import DB_PATH
from backtest.engine import BacktestConfig
from backtest.walkforward import run_walkforward, format_report
from strategy.ranking import RankParams
from strategy.sizing import SizingParams

RESULTS = ROOT / "backtest" / "results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_date", default="2025-06-01")
    ap.add_argument("--to",   dest="to_date",   default="2026-06-01")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--fade", action="store_true")
    ap.add_argument("--slippage", type=float, default=0.002)
    ap.add_argument("--top-pct", type=float, default=0.01)
    ap.add_argument("--min-rvol", type=float, default=2.0)
    ap.add_argument("--entry", default="09:45")
    ap.add_argument("--time-stop", default="10:30")
    ap.add_argument("--capital", type=float, default=20_000.0)
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    syms = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM minute_candles WHERE timeframe='5min'").fetchall())
    conn.close()
    drop = {"INDIAVIX", "NIFTY50", "NIFTY50_YF", "NIFTYNEXT50", "NIFTYBANK", "NIFTYIT",
            "NIFTYFMCG", "NIFTYPHARMA", "NIFTYAUTO", "NIFTYMETAL", "NIFTYREALTY",
            "NIFTYINFRA", "SP500", "NASDAQ"}
    syms = [s for s in syms if s not in drop]

    cfg = BacktestConfig(
        from_date=args.from_date, to_date=args.to_date,
        entry_time=args.entry, time_stop=args.time_stop,
        slippage_pct=args.slippage, capital=args.capital, symbols=syms, fade=args.fade,
        rank=RankParams(entry_time_ist=args.entry, top_pct=args.top_pct, min_rvol=args.min_rvol),
        sizing=SizingParams(),
    )

    res = run_walkforward(cfg, n_folds=args.folds)
    report = format_report(res)

    rid = "wf_" + uuid.uuid4().hex[:8]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{rid}.md").write_text(report, encoding="utf-8")
    (RESULTS / f"{rid}.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")

    print("\n" + report)
    v = res.get("verdict", {})
    logger.success(f"{rid} → tradeable_candidate={v.get('tradeable_candidate')}")


if __name__ == "__main__":
    main()
