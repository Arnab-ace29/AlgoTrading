"""
Fetch and display intraday (MIS) margin multipliers for all universe symbols
from the Upstox ChargeApi.post_margin endpoint.

Usage:
    python scripts/fetch_margin_multipliers.py               # full universe
    python scripts/fetch_margin_multipliers.py --symbols RELIANCE,TCS,INFY
    python scripts/fetch_margin_multipliers.py --price 500   # reference price
    python scripts/fetch_margin_multipliers.py --show-cached # print cached file

Requires a LIVE Upstox OAuth token (LIVE_ACCESS_TOKEN in .env, UPSTOX_MODE=live).
Sandbox token → 401 for this endpoint.

Results are saved to data/margin_multipliers.json for offline use.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()

from loguru import logger


def _universe_symbols() -> list[str]:
    import json
    universes_path = Path(__file__).resolve().parents[1] / "config" / "universes.json"
    if universes_path.exists():
        try:
            u = json.loads(universes_path.read_text())
            return sorted({s for lst in u.values() if isinstance(lst, list) for s in lst})
        except Exception:
            pass
    # Fallback: full NSE equity key map
    from data.instruments import get_all_equity_symbols
    return sorted(get_all_equity_symbols())


def main():
    ap = argparse.ArgumentParser(description="Fetch Upstox MIS margin multipliers")
    ap.add_argument("--symbols", default="", help="Comma-separated override symbol list")
    ap.add_argument("--price", type=float, default=1000.0,
                    help="Reference price sent to margin API (default 1000; ratio is price-invariant)")
    ap.add_argument("--show-cached", action="store_true",
                    help="Print the cached file and exit without hitting the API")
    ap.add_argument("--top", type=int, default=0,
                    help="Show only top-N by multiplier (0 = all)")
    args = ap.parse_args()

    if args.show_cached:
        from data.margin import load_margin_multipliers, _CACHE_PATH
        data = load_margin_multipliers(max_age_days=365)
        if not data:
            print(f"No cache found at {_CACHE_PATH}")
            return
        rows = sorted(data.items(), key=lambda x: x[1]["multiplier"], reverse=True)
        if args.top:
            rows = rows[:args.top]
        print(f"\n{'Symbol':<14} {'Multiplier':>10} {'Margin %':>10} {'Total Margin ₹':>14}")
        print("-" * 52)
        for sym, d in rows:
            print(f"{sym:<14} {d['multiplier']:>10.2f}x {d['margin_pct']:>9.1f}%"
                  f" {d['total_margin']:>14.2f}")
        return

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] \
        if args.symbols else _universe_symbols()

    logger.info(f"Fetching MIS margin multipliers for {len(symbols)} symbols "
                f"(reference price ₹{args.price:,.0f})…")
    logger.info("NOTE: Requires UPSTOX_MODE=live and a valid LIVE_ACCESS_TOKEN in .env")

    from data.margin import fetch_margin_multipliers
    results = fetch_margin_multipliers(symbols, reference_price=args.price)

    if not results:
        logger.error("No results returned — check LIVE_ACCESS_TOKEN and UPSTOX_MODE=live in .env")
        sys.exit(1)

    rows = sorted(results.items(), key=lambda x: x[1]["multiplier"], reverse=True)
    if args.top:
        rows = rows[:args.top]

    print(f"\n{'Symbol':<14} {'Multiplier':>10} {'Margin %':>10} {'Equity Margin ₹':>16} {'SPAN ₹':>10} {'Exposure ₹':>12}")
    print("-" * 76)
    for sym, d in rows:
        print(f"{sym:<14} {d['multiplier']:>10.2f}x {d['margin_pct']:>9.1f}%"
              f" {d['equity_margin']:>16.2f} {d['span_margin']:>10.2f} {d['exposure_margin']:>12.2f}")

    # Quick stats
    mults = [d["multiplier"] for d in results.values()]
    print(f"\nCovered: {len(results)}/{len(symbols)} symbols  |  "
          f"Min: {min(mults):.1f}x  Max: {max(mults):.1f}x  "
          f"Avg: {sum(mults)/len(mults):.1f}x")
    print(f"Saved → data/margin_multipliers.json")


if __name__ == "__main__":
    main()
