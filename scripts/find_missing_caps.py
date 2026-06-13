"""
One-off: find large/mid-cap NSE stocks that are NOT in config/universes.json.

The universe (nifty_total, 746) was built from index membership. Some liquid
large/mid caps — especially recent IPOs — may have been missed. This fetches
market cap (yfinance) for every NSE symbol absent from the universe and reports
anything at or above a mid-cap threshold, so we can decide what to add.

Run:  python scripts/find_missing_caps.py
Out:  data/missing_caps.csv  (symbol, market_cap_cr, sector)  sorted desc
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
from loguru import logger

MIDCAP_CR = 5_000        # report anything >= this (mid + large cap)

def main():
    uni = json.load(open(ROOT / "config" / "universes.json", encoding="utf-8"))
    nse = json.load(open(ROOT / "data" / "nse_eq_keys.json", encoding="utf-8"))
    total = set(uni["nifty_total"])
    missing = sorted(set(nse.keys()) - total)
    logger.info(f"Checking {len(missing)} symbols absent from the universe...")

    import yfinance as yf
    rows = []
    for i, sym in enumerate(missing, 1):
        try:
            d = yf.Ticker(f"{sym}.NS").info
            cap = (d.get("marketCap") or 0) / 1e7   # -> INR Cr
            if cap >= MIDCAP_CR:
                rows.append({
                    "Symbol": sym,
                    "Market Cap (Cr)": round(cap),
                    "Sector": d.get("sector", ""),
                    "Name": d.get("longName", sym),
                })
                logger.success(f"  [{i}] {sym}: Rs{cap:,.0f} Cr  ({d.get('sector','')})")
        except Exception:
            pass
        if i % 100 == 0:
            logger.info(f"  ...{i}/{len(missing)} checked, {len(rows)} found so far")
        time.sleep(0.2)

    df = pd.DataFrame(rows).sort_values("Market Cap (Cr)", ascending=False)
    out = ROOT / "data" / "missing_caps.csv"
    df.to_csv(out, index=False)
    logger.success(f"\nDone. {len(df)} missing mid/large caps (>= Rs{MIDCAP_CR} Cr) -> {out}")
    # print the top of the list inline
    if not df.empty:
        print(df.head(60).to_string(index=False))

if __name__ == "__main__":
    main()
