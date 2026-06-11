"""
Upstox live WebSocket feed (MarketDataStreamerV3).
Receives ticks for subscribed symbols and writes them to SQLite.
Also aggregates 1-minute candles in-memory and flushes to DB on bar close.

Usage (normally called by live/runner.py, not directly):
    feed = UpstoxFeed(symbols=["RELIANCE", "TCS"])
    feed.start()   # non-blocking, runs in background thread
    feed.stop()
"""

from __future__ import annotations
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import pandas as pd
from loguru import logger

from config.settings import INSTRUMENT_KEYS, UPSTOX_ACCESS_TOKEN, TIMEFRAME_PRIMARY
from data.db import upsert_ticks, write_candles

# upstox_client (the broker SDK) is imported lazily inside start(), so this module
# — and the CandleAggregator / price-cache logic — can be imported and unit-tested
# without the SDK installed.


# Map timeframe labels (e.g. "5min") to interval minutes for live aggregation.
def _timeframe_to_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("min"):
        return max(1, int(tf[:-3] or 1))
    if tf.endswith("m"):
        return max(1, int(tf[:-1] or 1))
    if tf.endswith("hr") or tf.endswith("h"):
        return max(1, int("".join(c for c in tf if c.isdigit()) or 1)) * 60
    return 1


class CandleAggregator:
    """
    Aggregates raw ticks into OHLCV candles of a configurable interval
    (e.g. 1-minute or 5-minute) in-memory. Emits a completed candle dict
    when the bar closes.

    Notes:
    - Upstox reports CUMULATIVE session volume (vtt). We derive per-bar volume
      as (current_cumulative - cumulative_at_bar_start), clamped at >= 0.
    - The emitted candle carries 'symbol' and 'timeframe' so it can be written
      straight to SQLite and read back via read_candles().
    """

    def __init__(self,
                 symbol: str,
                 interval_minutes: int = 1,
                 timeframe_label: str = "1min",
                 on_candle: Optional[Callable] = None):
        self.symbol           = symbol
        self.interval_minutes = max(1, int(interval_minutes))
        self.timeframe_label  = timeframe_label
        self.on_candle        = on_candle
        self._bar: Optional[dict] = None
        self._lock = threading.Lock()

    def _bar_key(self, ts: datetime) -> datetime:
        """Floor timestamp to the current interval bar start."""
        floored_minute = (ts.minute // self.interval_minutes) * self.interval_minutes
        return ts.replace(minute=floored_minute, second=0, microsecond=0)

    def update(self, ltp: float, volume: int, ts: datetime) -> None:
        bar_start = self._bar_key(ts)
        completed = None
        with self._lock:
            if self._bar is None:
                self._bar = self._new_bar(bar_start, ltp, volume)
            elif bar_start > self._bar["timestamp"]:
                # Bar closed — emit completed bar, start a fresh one
                completed = self._bar.copy()
                completed.pop("_vol_start", None)
                self._bar = self._new_bar(bar_start, ltp, volume)
            else:
                # Update current bar
                self._bar["high"]   = max(self._bar["high"], ltp)
                self._bar["low"]    = min(self._bar["low"],  ltp)
                self._bar["close"]  = ltp
                # Per-bar volume = cumulative now - cumulative at bar start
                self._bar["volume"] = max(0, volume - self._bar["_vol_start"])
        # Emit outside the lock (the callback writes to DB / may do real work).
        if completed is not None and self.on_candle:
            self.on_candle(completed)

    def flush_if_due(self, now: datetime) -> bool:
        """
        Force-close the in-progress bar if its interval has elapsed, even when no
        newer tick has arrived (issue FEED-01). Without this, the last bar of a
        quiet period — or the final bar before EOD — is never emitted, so the
        signal loop reads stale candles. Returns True if a bar was emitted.
        """
        completed = None
        with self._lock:
            if self._bar is not None and self._bar_key(now) > self._bar["timestamp"]:
                completed = self._bar.copy()
                completed.pop("_vol_start", None)
                self._bar = None   # no new tick yet — next tick opens a fresh bar
        if completed is not None and self.on_candle:
            self.on_candle(completed)
            return True
        return False

    def _new_bar(self, ts: datetime, price: float, volume: int) -> dict:
        return {
            "timestamp": ts,
            "symbol":    self.symbol,
            "timeframe": self.timeframe_label,
            "open": price, "high": price, "low": price, "close": price,
            "volume": 0,
            "_vol_start": volume,   # cumulative session volume at bar open
        }


class UpstoxFeed:
    """
    Manages the Upstox MarketDataStreamerV3 WebSocket connection.
    Writes ticks to SQLite and emits 1-minute candles.
    """

    def __init__(
        self,
        symbols: Optional[list[str]] = None,
        on_tick: Optional[Callable]   = None,
        on_candle: Optional[Callable] = None,
        mode: str = "full",  # "ltpc" | "full" | "option_greeks"
    ):
        self.symbols    = symbols or list(INSTRUMENT_KEYS.keys())
        self.on_tick    = on_tick
        self.on_candle  = on_candle
        self.mode       = mode
        self._streamer  = None
        self._running   = False
        self._timer_thread: Optional[threading.Thread] = None
        # symbol -> list of CandleAggregator (one per timeframe)
        self._aggregators: dict[str, list[CandleAggregator]] = {}
        # symbol -> (last_price, monotonic_timestamp) — in-memory, for fresh/stale
        # price checks without a DB round-trip (issue FEED-02).
        self._last_price: dict[str, tuple[float, float]] = {}
        self._price_lock = threading.Lock()
        # How often the bar-close timer fires (seconds).
        self._timer_interval = 1.0

        # Timeframes to aggregate live: always 1min, plus the primary tf the
        # signal loop reads (deduped, e.g. ["1min", "5min"]).
        self._timeframes: list[str] = list(dict.fromkeys(["1min", TIMEFRAME_PRIMARY]))

        # Build instrument key list for subscription
        self._instrument_keys = [
            INSTRUMENT_KEYS[s] for s in self.symbols if s in INSTRUMENT_KEYS
        ]
        if not self._instrument_keys:
            raise ValueError("No valid instrument keys found for given symbols")

        # Create one aggregator per (symbol, timeframe)
        for symbol in self.symbols:
            if symbol not in INSTRUMENT_KEYS:
                continue
            self._aggregators[symbol] = [
                CandleAggregator(
                    symbol=symbol,
                    interval_minutes=_timeframe_to_minutes(tf),
                    timeframe_label=tf,
                    on_candle=self._on_candle_close,
                )
                for tf in self._timeframes
            ]

    def start(self) -> None:
        """Connect to Upstox WebSocket in a background thread."""
        if not UPSTOX_ACCESS_TOKEN:
            raise ValueError("UPSTOX_ACCESS_TOKEN not set. Cannot start live feed.")

        import upstox_client   # lazy: only needed for the live connection
        config = upstox_client.Configuration()
        config.access_token = UPSTOX_ACCESS_TOKEN
        api_client = upstox_client.ApiClient(config)

        self._streamer = upstox_client.MarketDataStreamerV3(
            api_client,
            self._instrument_keys,
            self.mode,
        )
        self._streamer.on("message",    self._on_message)
        self._streamer.on("open",       self._on_open)
        self._streamer.on("close",      self._on_close)
        self._streamer.on("error",      self._on_error)
        self._streamer.on("reconnect",  self._on_reconnect)

        self._running = True
        self._start_bar_timer()          # wall-clock bar-close events (FEED-01)
        self._streamer.connect()
        logger.info(f"Upstox feed starting for {len(self._instrument_keys)} instruments")

    def _start_bar_timer(self) -> None:
        """Background thread that force-closes due bars even without new ticks."""
        if self._timer_thread and self._timer_thread.is_alive():
            return
        self._timer_thread = threading.Thread(target=self._bar_timer_loop, daemon=True)
        self._timer_thread.start()

    def _bar_timer_loop(self) -> None:
        while self._running:
            try:
                self.flush_due_bars()
            except Exception as e:
                logger.error(f"bar timer error: {e}")
            time.sleep(self._timer_interval)

    def flush_due_bars(self, now: Optional[datetime] = None) -> int:
        """Force-close any aggregator bars whose interval has elapsed. Returns count."""
        now = now or datetime.now(timezone.utc)
        emitted = 0
        for aggs in self._aggregators.values():
            for agg in aggs:
                if agg.flush_if_due(now):
                    emitted += 1
        return emitted

    def stop(self) -> None:
        self._running = False
        if self._streamer:
            try:
                self._streamer.disconnect()
            except Exception:
                pass
        # Flush any in-progress bars so the final bar of the session isn't lost.
        try:
            self.flush_due_bars(datetime.now(timezone.utc))
        except Exception:
            pass
        logger.info("Upstox feed stopped")

    # ── WebSocket event handlers ──────────────────────────────────────────────

    def _on_open(self) -> None:
        logger.success("Upstox WebSocket connected")

    def _on_close(self) -> None:
        logger.warning("Upstox WebSocket disconnected")

    def _on_error(self, error) -> None:
        logger.error(f"Upstox WebSocket error: {error}")

    def _on_reconnect(self, attempt: int) -> None:
        logger.info(f"Upstox WebSocket reconnecting (attempt {attempt})")

    def _on_message(self, message: dict) -> None:
        """
        Parse incoming tick message and:
        1. Write raw tick to SQLite
        2. Feed into candle aggregator
        3. Call user on_tick callback if provided
        """
        try:
            feeds = message.get("feeds", {})
            for instrument_key, feed_data in feeds.items():
                symbol = self._key_to_symbol(instrument_key)
                if not symbol:
                    continue

                # Extract tick fields (Upstox full mode structure)
                ff = feed_data.get("ff", {})
                market_ff = ff.get("marketFF", {}) or ff.get("indexFF", {})
                ltpc = market_ff.get("ltpc", {})

                ltp       = float(ltpc.get("ltp", 0))
                ltt_str   = ltpc.get("ltt", "")
                volume    = int(market_ff.get("vtt", {}).get("vtt", 0))
                buy_qty   = int(market_ff.get("eFeedDetails", {}).get("tbq", 0))
                sell_qty  = int(market_ff.get("eFeedDetails", {}).get("tsq", 0))
                avg_price = float(market_ff.get("vtt", {}).get("ap", 0) or 0)

                # Best bid/ask
                depth = market_ff.get("marketLevel", {}).get("bidAskQuote", [])
                bid_price = float(depth[0].get("bp", 0)) if depth else 0.0
                ask_price = float(depth[0].get("sp", 0)) if depth else 0.0
                bid_qty   = int(depth[0].get("bq", 0))   if depth else 0
                ask_qty   = int(depth[0].get("sq", 0))   if depth else 0

                ts = datetime.now(timezone.utc)
                if ltt_str:
                    try:
                        ts = pd.to_datetime(ltt_str, utc=True).to_pydatetime()
                    except Exception:
                        pass

                if ltp <= 0:
                    continue

                # Write tick to SQLite
                tick_df = pd.DataFrame([{
                    "timestamp":       ts,
                    "symbol":          symbol,
                    "ltp":             ltp,
                    "open_price":      None,
                    "high_price":      None,
                    "low_price":       None,
                    "close_price":     ltp,
                    "volume":          volume,
                    "buy_qty":         buy_qty,
                    "sell_qty":        sell_qty,
                    "bid_price":       bid_price,
                    "bid_qty":         bid_qty,
                    "ask_price":       ask_price,
                    "ask_qty":         ask_qty,
                    "avg_price":       avg_price,
                    "oi":              None,
                    "instrument_type": "EQ",
                }])
                upsert_ticks(tick_df)

                # Cache the fresh price in memory (monotonic clock) for stale checks.
                with self._price_lock:
                    self._last_price[symbol] = (ltp, time.monotonic())

                # Feed into every timeframe aggregator for this symbol
                for agg in self._aggregators.get(symbol, []):
                    agg.update(ltp, volume, ts)

                # User callback
                if self.on_tick:
                    self.on_tick(symbol, ltp, volume, ts)

        except Exception as e:
            logger.error(f"Error processing tick: {e}")

    def _on_candle_close(self, candle: dict) -> None:
        """Called by a CandleAggregator when one of its bars completes.

        The candle already carries 'symbol' and 'timeframe', so it can be
        written straight to SQLite with the correct labels.
        """
        try:
            df = pd.DataFrame([candle])
            # Defensive defaults in case a field is missing.
            if "symbol" not in df.columns:
                df["symbol"] = ""
            if "timeframe" not in df.columns:
                df["timeframe"] = "1min"
            write_candles(df, source="upstox_live")

            if self.on_candle:
                self.on_candle(candle)
        except Exception as e:
            logger.error(f"Error writing candle: {e}")

    def _key_to_symbol(self, instrument_key: str) -> Optional[str]:
        """Reverse-lookup symbol name from instrument key."""
        for sym, key in INSTRUMENT_KEYS.items():
            if key == instrument_key:
                return sym
        return None

    def get_quote(self, symbol: str) -> Optional[tuple[float, float]]:
        """
        Latest in-memory (price, age_seconds) for a symbol, or None if no tick has
        been seen. Age is measured on a monotonic clock so it's robust to wall-clock
        changes. Used for fresh/stale price decisions (issue FEED-02).
        """
        with self._price_lock:
            rec = self._last_price.get(symbol)
        if rec is None:
            return None
        price, mono = rec
        return price, max(0.0, time.monotonic() - mono)

    def get_latest_ltp(self) -> dict[str, float]:
        """Return the last known LTP for each subscribed symbol (in-memory cache)."""
        with self._price_lock:
            return {sym: price for sym, (price, _) in self._last_price.items()}
