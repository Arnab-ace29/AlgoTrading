"""
Monthly universe refresh script.

Fetches the latest Nifty Total Market (750) constituent list from niftyindices.com
and F&O eligible symbols from the Upstox NSE instrument master, then writes
config/universes.json. Run this once a month (or before a major backfill).

Usage:
    python scripts/refresh_universe.py
    python scripts/refresh_universe.py --force   # bypass cache age check
    python scripts/refresh_universe.py --show    # print universe sizes and exit

If the niftyindices.com fetch fails, the script will print the manual download
URL and save path. Place the CSV there and re-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from screener.universe import build_universes_json, get_universe


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh stock universe lists")
    parser.add_argument("--force", action="store_true", help="Bypass cache, always re-fetch")
    parser.add_argument("--show",  action="store_true", help="Print current universe sizes and exit")
    args = parser.parse_args()

    if args.show:
        for name in ("nifty50", "nifty100", "nifty_total", "fo_eligible"):
            syms = get_universe(name)
            logger.info(f"  {name:15s}: {len(syms):4d} symbols   sample={syms[:5]}")
        return

    result = build_universes_json(force=args.force)
    if not result:
        logger.error("Universe build failed — see warnings above.")
        sys.exit(1)

    logger.success("Universe refresh complete:")
    for name, syms in result.items():
        logger.info(f"  {name:15s}: {len(syms):4d} symbols")


if __name__ == "__main__":
    main()
