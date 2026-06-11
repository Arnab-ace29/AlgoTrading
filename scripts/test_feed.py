"""
Tests for FEED-01 (forced bar-close) and FEED-02 (in-memory price cache + staleness).

Runs in the venv — the feed no longer imports upstox_client at module load:
    .venv/bin/python scripts/test_feed.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.upstox_feed import CandleAggregator, UpstoxFeed

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def _t(h, m, s):
    return datetime(2025, 1, 1, h, m, s, tzinfo=timezone.utc)


def test_forced_close():
    print("FEED-01 — forced bar-close on a quiet period:")
    emitted = []
    agg = CandleAggregator("X", interval_minutes=1, timeframe_label="1min", on_candle=emitted.append)
    agg.update(100.0, 1000, _t(9, 15, 30))          # opens the 09:15 bar
    check(len(emitted) == 0, "no emit yet (bar still open)")

    fired = agg.flush_if_due(_t(9, 16, 1))           # minute elapsed, NO new tick
    check(fired and len(emitted) == 1, "bar force-closed by the timer with no new tick")
    check(emitted[0]["timestamp"].minute == 15 and emitted[0]["close"] == 100.0,
          "emitted the 09:15 bar at its last price")
    check(agg.flush_if_due(_t(9, 16, 5)) is False, "nothing left to flush after force-close")


def test_normal_close_still_works():
    print("normal tick-driven close still works:")
    emitted = []
    agg = CandleAggregator("X", interval_minutes=1, timeframe_label="1min", on_candle=emitted.append)
    agg.update(100.0, 1000, _t(9, 15, 30))
    agg.update(101.0, 1100, _t(9, 16, 10))           # new bar → emits 09:15
    check(len(emitted) == 1 and emitted[0]["timestamp"].minute == 15, "09:15 bar emitted on the 09:16 tick")


def test_5min_bucketing():
    print("5-min bucketing + forced close:")
    emitted = []
    agg = CandleAggregator("X", interval_minutes=5, timeframe_label="5min", on_candle=emitted.append)
    agg.update(50.0, 10, _t(9, 17, 0))               # floors to 09:15 bucket
    fired = agg.flush_if_due(_t(9, 21, 0))           # 09:20 bucket > 09:15 → force close
    check(fired and emitted[0]["timestamp"].minute == 15, "5-min bar floors to :15 and force-closes after the bucket")


def test_price_cache_staleness():
    print("FEED-02 — in-memory price cache + staleness:")
    feed = UpstoxFeed(symbols=["RELIANCE"])           # built, not connected (no SDK call)
    check(feed.get_quote("RELIANCE") is None, "no quote before any tick")

    feed._last_price["RELIANCE"] = (2950.0, time.monotonic())
    p, age = feed.get_quote("RELIANCE")
    check(p == 2950.0 and age < 1.0, "fresh tick → small age")

    feed._last_price["RELIANCE"] = (2950.0, time.monotonic() - 20.0)
    p, age = feed.get_quote("RELIANCE")
    check(age > 15.0, "20s-old tick reports as stale (age > threshold)")

    check(feed.get_latest_ltp().get("RELIANCE") == 2950.0, "get_latest_ltp reads the memory cache")
    check(feed.flush_due_bars(_t(9, 16, 0)) == 0, "flush_due_bars is a no-op when no bars are open")


def main() -> int:
    print("=" * 60); print("FEED TESTS (FEED-01 / FEED-02)"); print("=" * 60)
    test_forced_close()
    test_normal_close_still_works()
    test_5min_bucketing()
    test_price_cache_staleness()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
