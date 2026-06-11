"""
Run the pre-market screener (≈09:00 IST).

Ranks each strategy's universe on EOD data and writes config/daily_watchlist.json,
which live/runner.py reads at startup.

    python scripts/run_screener.py                  # asof = today
    python scripts/run_screener.py --asof 2026-06-05
    python scripts/run_screener.py --top 15 --strategies momentum_vwap,rsi_momentum
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Allow `python scripts/run_screener.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from screener.daily_screener import DailyScreener
from screener.universe import DEFAULT_STRATEGIES


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-market screener")
    ap.add_argument("--asof", type=str, default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--top", type=int, default=None, help="top N per strategy (default: settings.SCREENER_TOP_N)")
    ap.add_argument("--strategies", type=str, default=None,
                    help="comma-separated subset (default: all)")
    args = ap.parse_args()

    asof = datetime.strptime(args.asof, "%Y-%m-%d").date() if args.asof else None
    # Strip + drop empties so "--strategies momentum_vwap, rsi_momentum" (space after
    # the comma) doesn't silently fall back to nifty50 under a malformed key.
    strategies = ([s.strip() for s in args.strategies.split(",") if s.strip()]
                  if args.strategies else DEFAULT_STRATEGIES)

    kwargs = {}
    if args.top:
        kwargs["top_n"] = args.top
    screener = DailyScreener(**kwargs)

    watchlist, breakdown = screener.run(asof=asof, strategies=strategies)

    print("\n=== Daily Watchlist ===")
    any_rows = False
    for strat, syms in watchlist.items():
        print(f"\n{strat}  ({len(syms)})")
        for r in breakdown.get(strat, []):
            any_rows = True
            reasons = (" | " + ", ".join(r["reasons"])) if r.get("reasons") else ""
            print(f"  {r['symbol']:<12} score={r['score']:.3f}  "
                  f"mom={r['momentum_rank']:.2f} tech={r['technical_setup']:.2f} "
                  f"vol={r['volume_surge']:.2f} volat={r['volatility_opportunity']:.2f}{reasons}")
    if not any_rows:
        logger.warning("No symbols ranked — is there candle data in SQLite for the universe?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
