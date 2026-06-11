"""
Upstox historical OHLCV data fetcher.
Fetches candles via the Upstox REST API and stores them in SQLite.

Usage:
    python data/upstox_history.py               # backfill all instruments
    python data/upstox_history.py --symbol TCS  # single symbol
"""

from __future__ import annotations
import time
import argparse
from datetime import timedelta, date
from typing import Optional

import pandas as pd
import upstox_client
from upstox_client.rest import ApiException
from loguru import logger

from config.settings import (
    INSTRUMENT_KEYS, INSTRUMENTS, TIMEFRAMES_STORE,
    CANDLE_LOOKBACK_DAYS, UPSTOX_ACCESS_TOKEN, ANALYTICS_TOKEN,
)
from data.db import init_db, write_candles, get_latest_candle_time
from data.instruments import resolve_instrument_key

# Upstox V3 API: /v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}
# unit = minutes | hours | days | weeks | months
# interval = any integer (1, 5, 15, 30, 60 ...)
# V3 supports all timeframes natively — no resampling needed.
UPSTOX_V3_TIMEFRAME_MAP: dict[str, tuple[str, str]] = {
    "1min":  ("minutes", "1"),
    "5min":  ("minutes", "5"),
    "15min": ("minutes", "15"),
    "30min": ("minutes", "30"),
    "1hr":   ("hours",   "1"),
    "1day":  ("days",    "1"),
}

# Rate limit: ~5 requests/second is safe (Upstox allows ~10/s)
REQUEST_DELAY_SEC = 0.25


def get_api_client() -> upstox_client.ApiClient:
    """
    Build an authenticated Upstox API client.

    Preference order:
      1. ANALYTICS_TOKEN  — 1-year lifetime, never expires mid-run (preferred for backfill)
      2. UPSTOX_ACCESS_TOKEN — daily OAuth token (fallback for live/sandbox mode)
    """
    token = ANALYTICS_TOKEN or UPSTOX_ACCESS_TOKEN
    if not token:
        raise ValueError(
            "No Upstox token found. Set ANALYTICS_TOKEN in .env for backfill "
            "(preferred), or run scripts/refresh_token.py for LIVE_ACCESS_TOKEN."
        )
    if ANALYTICS_TOKEN:
        logger.debug("Using ANALYTICS_TOKEN for API client (long-lived)")
    else:
        logger.debug("Using UPSTOX_ACCESS_TOKEN for API client (expires daily)")
    config = upstox_client.Configuration()
    config.access_token = token
    return upstox_client.ApiClient(config)


def fetch_candles_for_range(
    api: upstox_client.HistoryV3Api,
    instrument_key: str,
    unit: str,
    interval: str,
    from_date: date,
    to_date: date,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles from Upstox V3 API.
    unit     = 'minutes' | 'hours' | 'days' | 'weeks' | 'months'
    interval = any integer as string: '1', '5', '15', '30' ...
    """
    try:
        resp = api.get_historical_candle_data1(
            instrument_key=instrument_key,
            unit=unit,
            interval=interval,
            to_date=str(to_date),
            from_date=str(from_date),
        )
        if not resp or not resp.data or not resp.data.candles:
            return pd.DataFrame()

        candles = resp.data.candles
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    except ApiException as e:
        logger.error(f"Upstox API error for {instrument_key} {unit}/{interval}: {e.status} {e.reason} | body={str(e.body)[:200]}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Unexpected error fetching {instrument_key}: {e}")
        return pd.DataFrame()


def backfill_symbol(
    api: upstox_client.HistoryV3Api,
    symbol: str,
    instrument_key: str,
    timeframes: Optional[list[str]] = None,
    days: int = CANDLE_LOOKBACK_DAYS,
    force: bool = False,
) -> dict[str, int]:
    """
    Backfill historical data for a single symbol using Upstox V3 API.
    V3 supports all timeframes natively (minutes/5, minutes/15, hours/1, etc.)

    force=True: ignore existing data in DB and always fetch the full `days` window.
    Use this when the DB has demo/synthetic data that would otherwise trigger
    incremental mode and skip the real historical backfill.
    """
    if timeframes is None:
        timeframes = TIMEFRAMES_STORE  # ["1min", "5min", "15min"]

    results: dict[str, int] = {}
    to_date = date.today()

    for tf in timeframes:
        if tf not in UPSTOX_V3_TIMEFRAME_MAP:
            logger.warning(f"Unknown timeframe '{tf}', skipping")
            continue

        unit, interval = UPSTOX_V3_TIMEFRAME_MAP[tf]

        latest = None if force else get_latest_candle_time(symbol, tf)
        if latest:
            from_date = latest.date() - timedelta(days=1)
            logger.info(f"{symbol} {tf}: incremental from {from_date}")
        else:
            from_date = to_date - timedelta(days=days)
            logger.info(f"{symbol} {tf}: full backfill from {from_date} ({days}d)")

        all_dfs: list[pd.DataFrame] = []
        # Upstox V3 enforces a 30-day max date range per request for
        # all minute and hour intervals (UDAPI1148 error beyond 30d).
        # Day/week/month intervals support up to 365 days per request.
        chunk_days = 30 if unit == "minutes" else 365
        current_from = from_date

        while current_from < to_date:
            current_to = min(current_from + timedelta(days=chunk_days), to_date)
            df = fetch_candles_for_range(api, instrument_key, unit, interval, current_from, current_to)
            if not df.empty:
                all_dfs.append(df)
            current_from = current_to + timedelta(days=1)
            time.sleep(REQUEST_DELAY_SEC)

        if not all_dfs:
            logger.warning(f"{symbol} {tf}: no data returned")
            results[tf] = 0
            continue

        combined = pd.concat(all_dfs, ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        combined["symbol"]    = symbol
        combined["timeframe"] = tf
        rows = write_candles(combined, source="upstox_hist")
        results[tf] = rows
        logger.success(f"{symbol} {tf}: wrote {rows} candles")

    return results


def backfill_all(
    symbols: Optional[list[str]] = None,
    timeframes: Optional[list[str]] = None,
    days: int = CANDLE_LOOKBACK_DAYS,
    force: bool = False,
) -> None:
    """
    Backfill historical data for a list of symbols.

    Instrument keys are resolved in priority order:
      1. config.INSTRUMENT_KEYS  (hand-maintained, always accurate)
      2. data.instruments.resolve_instrument_key()  (full NSE master, covers all 750+)

    Pass symbols=None to backfill only the core INSTRUMENTS list.
    Pass a custom list (e.g. from screener/universe_fetcher) for the full universe.
    """
    if symbols is None:
        symbols = INSTRUMENTS

    init_db()
    api_client = get_api_client()
    history_api = upstox_client.HistoryV3Api(api_client)

    total_rows = 0
    skipped_symbols: list[str] = []
    for i, symbol in enumerate(symbols, 1):
        instrument_key = INSTRUMENT_KEYS.get(symbol) or resolve_instrument_key(symbol)
        if not instrument_key:
            logger.warning(f"[{i}/{len(symbols)}] No instrument key for '{symbol}', skipping")
            skipped_symbols.append(symbol)
            continue

        logger.info(f"[{i}/{len(symbols)}] ── Backfilling {symbol} ──")
        result = backfill_symbol(history_api, symbol, instrument_key, timeframes, days, force=force)
        symbol_total = sum(result.values())
        total_rows += symbol_total
        logger.info(f"{symbol} done: {result}")

    logger.success(
        f"Backfill complete. Total rows written: {total_rows} | "
        f"Skipped: {len(skipped_symbols)}/{len(symbols)}"
    )
    if skipped_symbols:
        logger.warning(
            f"Symbols with no instrument key (likely delisted / renamed / not in NSE master):\n"
            + "\n".join(f"  - {s}" for s in skipped_symbols)
        )


# ── Fallback: yfinance (when Upstox token not available) ─────────────────────
def backfill_with_yfinance(
    symbols: Optional[list[str]] = None,
    period: str = "1y",
    interval: str = "5m",
) -> None:
    """
    Backfill using yfinance as a fallback (for testing without Upstox token).
    yfinance supports 5m data up to 60 days, 1d data up to 10 years.
    """
    import yfinance as yf

    if symbols is None:
        symbols = INSTRUMENTS

    init_db()
    tf_map = {"5m": "5min", "1m": "1min", "15m": "15min", "1d": "1day"}
    tf_label = tf_map.get(interval, interval)

    for symbol in symbols:
        ticker = f"{symbol}.NS"
        logger.info(f"yfinance: fetching {ticker} {interval} for {period}")
        try:
            df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
            if df.empty:
                logger.warning(f"yfinance returned no data for {ticker}")
                continue

            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            ts_col = "datetime" if "datetime" in df.columns else "date"
            df = df.rename(columns={ts_col: "timestamp"})
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df["symbol"]    = symbol
            df["timeframe"] = tf_label
            if "volume" not in df.columns:
                df["volume"] = 0

            rows = write_candles(df[["timestamp","symbol","timeframe","open","high","low","close","volume"]], source="yfinance")
            logger.success(f"{symbol} ({tf_label}): wrote {rows} rows via yfinance")
        except Exception as e:
            logger.error(f"yfinance error for {ticker}: {e}")


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical OHLCV data")
    parser.add_argument("--symbol",    type=str,  help="Single symbol (overrides --universe)")
    parser.add_argument("--days",      type=int,  default=CANDLE_LOOKBACK_DAYS,
                        help="Lookback days (default: CANDLE_LOOKBACK_DAYS). Use 730 for 2-year RL backfill.")
    parser.add_argument("--tf",        type=str,  help="Single timeframe e.g. 5min (default: all TIMEFRAMES_STORE)")
    parser.add_argument("--universe",  action="store_true",
                        help="Backfill full Nifty Total Market universe (~750 symbols) via screener/universe_fetcher")
    parser.add_argument("--force",     action="store_true",
                        help="Ignore existing DB data and always fetch the full --days window. "
                             "Use when DB has demo/synthetic data blocking a real historical backfill.")
    parser.add_argument("--yfinance",  action="store_true", help="Use yfinance fallback (no Upstox token)")
    args = parser.parse_args()

    timeframes = [args.tf] if args.tf else None

    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.universe:
        from screener.universe_fetcher import fetch_nifty_universe
        symbols = fetch_nifty_universe()
        logger.info(f"Universe mode: {len(symbols)} symbols loaded from Nifty Total Market")
    else:
        symbols = None  # falls back to core INSTRUMENTS list

    token_available = bool(ANALYTICS_TOKEN or UPSTOX_ACCESS_TOKEN)
    if args.yfinance or not token_available:
        logger.warning("Using yfinance fallback (no Upstox token set or --yfinance flag)")
        interval_map = {"1min": "1m", "5min": "5m", "15min": "15m", "1day": "1d"}
        tf = timeframes[0] if timeframes else "5min"
        backfill_with_yfinance(symbols, period=f"{args.days}d", interval=interval_map.get(tf, "5m"))
    else:
        if args.force:
            logger.warning(f"--force mode: ignoring existing DB data, fetching full {args.days}-day window for all symbols")
        backfill_all(symbols, timeframes, args.days, force=args.force)
