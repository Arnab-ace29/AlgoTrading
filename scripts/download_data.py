"""
Download all missing OHLCV data from Upstox + India VIX from yfinance.

What this script does:
  1. Loads the full NSE universe from config/universes.json
  2. Checks existing DB coverage (what we already have)
  3. Downloads 5-min candles for any symbol with < 7 days of data (new or stale)
  4. Downloads 1-day candles for all symbols (incremental — only gaps)
  5. Downloads India VIX + key sector indices daily via yfinance as backup
  6. Downloads sector indices (Nifty Bank, IT, etc.) via Upstox

Run:
    python scripts/download_data.py             # full run (5min + 1day + VIX)
    python scripts/download_data.py --tf 1day   # only daily candles
    python scripts/download_data.py --vix-only  # only VIX + indices

Token used: ANALYTICS_TOKEN from .env (1-year lifetime, read-only, safe for backfill)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlite3
import pandas as pd
from loguru import logger

from config.settings import DB_PATH, ANALYTICS_TOKEN, UPSTOX_ACCESS_TOKEN
from data.db import init_db, write_candles, get_latest_candle_time
from data.instruments import resolve_instrument_key
from data.upstox_history import (
    get_api_client,
    backfill_symbol,
    UPSTOX_V3_TIMEFRAME_MAP,
)

# ── Constants ─────────────────────────────────────────────────────────────────

UNIVERSES_FILE = ROOT / "config" / "universes.json"
LOOKBACK_DAYS  = 730    # 2 years of history

# Sector indices available via Upstox V3 (NSE_INDEX keys)
SECTOR_INDICES: dict[str, str] = {
    "NIFTY50":       "NSE_INDEX|Nifty 50",
    "NIFTYNEXT50":   "NSE_INDEX|Nifty Next 50",
    "NIFTYBANK":     "NSE_INDEX|Nifty Bank",
    "NIFTYIT":       "NSE_INDEX|Nifty IT",
    "NIFTYFMCG":     "NSE_INDEX|Nifty FMCG",
    "NIFTYPHARMA":   "NSE_INDEX|Nifty Pharma",
    "NIFTYAUTO":     "NSE_INDEX|Nifty Auto",
    "NIFTYMETAL":    "NSE_INDEX|Nifty Metal",
    "NIFTYREALTY":   "NSE_INDEX|Nifty Realty",
    "NIFTYINFRA":    "NSE_INDEX|Nifty Infrastructure",
    "INDIAVIX":      "NSE_INDEX|India VIX",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_universe() -> list[str]:
    """All unique symbols across every universe list."""
    with open(UNIVERSES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    all_syms: set[str] = set()
    for lst in data.values():
        all_syms.update(lst)
    return sorted(all_syms)


def get_db_coverage(conn: sqlite3.Connection, symbols: list[str], timeframe: str) -> dict[str, dict]:
    """Return {symbol: {bars, first, last}} for each symbol."""
    coverage = {}
    rows = conn.execute(
        """SELECT symbol, COUNT(*) as bars, MIN(timestamp) as first, MAX(timestamp) as last
           FROM minute_candles WHERE timeframe=?
           GROUP BY symbol""",
        (timeframe,),
    ).fetchall()
    lookup = {r[0]: {"bars": r[1], "first": str(r[2])[:10], "last": str(r[3])[:10]} for r in rows}
    for sym in symbols:
        coverage[sym] = lookup.get(sym, {"bars": 0, "first": None, "last": None})
    return coverage


def download_vix_yfinance(conn: sqlite3.Connection, days: int = 730) -> int:
    """Download India VIX + key global indices from yfinance and store in DB."""
    import yfinance as yf

    yf_map = {
        "INDIAVIX":  "^INDIAVIX",
        "NIFTY50_YF": "^NSEI",
        "SP500":     "^GSPC",
        "NASDAQ":    "^IXIC",
    }

    total = 0
    for symbol, ticker in yf_map.items():
        try:
            df = yf.download(ticker, period=f"{days}d", interval="1d", progress=False, auto_adjust=True)
            if df.empty:
                logger.warning(f"yfinance: no data for {ticker}")
                continue
            df = df.reset_index()
            df.columns = [str(c[0]).lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
            ts_col = "date" if "date" in df.columns else "datetime"
            df = df.rename(columns={ts_col: "timestamp"})
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df["symbol"]    = symbol
            df["timeframe"] = "1day"
            df["volume"]    = df.get("volume", 0).fillna(0).astype(int)
            cols = ["timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume"]
            rows = write_candles(df[[c for c in cols if c in df.columns]], source="yfinance")
            logger.success(f"  {symbol} ({ticker}): {rows} rows written")
            total += rows
        except Exception as e:
            logger.error(f"  yfinance error for {ticker}: {e}")
    return total


# ── Main download logic ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tf",        choices=["5min", "1day", "both"], default="both")
    parser.add_argument("--vix-only",  action="store_true", help="Only download VIX + indices")
    parser.add_argument("--days",      type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--force",     action="store_true", help="Re-fetch even if data exists")
    args = parser.parse_args()

    if not (ANALYTICS_TOKEN or UPSTOX_ACCESS_TOKEN):
        logger.error("No Upstox token found. Set ANALYTICS_TOKEN in .env")
        sys.exit(1)

    init_db()
    conn = sqlite3.connect(str(DB_PATH), timeout=30)

    # ── VIX + global indices via yfinance ──────────────────────────────────────
    logger.info("=== Step 1: India VIX + global indices (yfinance) ===")
    vix_rows = download_vix_yfinance(conn, days=args.days)
    logger.success(f"VIX/indices: {vix_rows} total rows")

    if args.vix_only:
        conn.close()
        return

    # ── Universe ───────────────────────────────────────────────────────────────
    symbols = load_universe()
    logger.info(f"Universe: {len(symbols)} symbols from universes.json")

    api_client = get_api_client()
    import upstox_client
    history_api = upstox_client.HistoryV3Api(api_client)

    # ── 5-min candles ──────────────────────────────────────────────────────────
    if args.tf in ("5min", "both"):
        logger.info("\n=== Step 2: 5-min OHLCV (equity) ===")
        coverage_5m = get_db_coverage(conn, symbols, "5min")

        # Determine which symbols need download
        to_fetch_5m = []
        for sym in symbols:
            cov = coverage_5m[sym]
            if args.force or cov["bars"] < 500:   # < ~7 trading days → fetch
                to_fetch_5m.append(sym)

        logger.info(f"  Symbols to fetch/update (5min): {len(to_fetch_5m)}")

        for i, sym in enumerate(to_fetch_5m, 1):
            ikey = resolve_instrument_key(sym)
            if not ikey:
                logger.warning(f"  [{i}/{len(to_fetch_5m)}] {sym}: no instrument key, skip")
                continue
            logger.info(f"  [{i}/{len(to_fetch_5m)}] {sym}")
            backfill_symbol(history_api, sym, ikey, timeframes=["5min"],
                            days=args.days, force=args.force)

    # ── 1-day candles ─────────────────────────────────────────────────────────
    if args.tf in ("1day", "both"):
        logger.info("\n=== Step 3: 1-day OHLCV (all symbols) ===")
        coverage_1d = get_db_coverage(conn, symbols, "1day")

        to_fetch_1d = [s for s in symbols if args.force or coverage_1d[s]["bars"] < 50]
        logger.info(f"  Symbols to fetch/update (1day): {len(to_fetch_1d)}")

        for i, sym in enumerate(to_fetch_1d, 1):
            ikey = resolve_instrument_key(sym)
            if not ikey:
                logger.warning(f"  [{i}/{len(to_fetch_1d)}] {sym}: no instrument key, skip")
                continue
            logger.info(f"  [{i}/{len(to_fetch_1d)}] {sym}")
            backfill_symbol(history_api, sym, ikey, timeframes=["1day"],
                            days=args.days, force=args.force)

    # ── Sector indices via Upstox ─────────────────────────────────────────────
    logger.info("\n=== Step 4: Sector indices (Upstox) ===")
    for sym, ikey in SECTOR_INDICES.items():
        if sym == "INDIAVIX":
            continue  # already fetched via yfinance
        logger.info(f"  Index: {sym}")
        backfill_symbol(history_api, sym, ikey, timeframes=["1day"],
                        days=args.days, force=args.force)

    conn.close()
    logger.success("\nDownload complete.")


if __name__ == "__main__":
    main()
