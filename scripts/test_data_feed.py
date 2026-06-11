"""
Tests for the live data feed's CandleAggregator.

Verifies (without any WebSocket connection):
  - Emitted candles carry 'symbol' and 'timeframe'.
  - OHLC is built correctly across ticks.
  - Per-bar volume is the delta of cumulative session volume.
  - 1-minute and 5-minute interval flooring both work.
"""

from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.upstox_feed import CandleAggregator, _timeframe_to_minutes


def _ts(h, m, s=0):
    return datetime(2024, 6, 3, h, m, s, tzinfo=timezone.utc)


def test_timeframe_parsing() -> bool:
    print("Testing timeframe parsing...")
    assert _timeframe_to_minutes("1min") == 1
    assert _timeframe_to_minutes("5min") == 5
    assert _timeframe_to_minutes("15min") == 15
    assert _timeframe_to_minutes("1hr") == 60
    print("  OK")
    return True


def test_one_minute_aggregation() -> bool:
    print("Testing 1-minute aggregation...")
    emitted = []
    agg = CandleAggregator("RELIANCE", interval_minutes=1, timeframe_label="1min",
                           on_candle=emitted.append)

    # Cumulative session volume grows over time.
    agg.update(ltp=100.0, volume=1000, ts=_ts(9, 15, 1))   # bar 9:15 open
    agg.update(ltp=102.0, volume=1200, ts=_ts(9, 15, 30))  # high
    agg.update(ltp=99.0,  volume=1500, ts=_ts(9, 15, 59))  # low, close
    # New minute -> closes the 9:15 bar
    agg.update(ltp=101.0, volume=1600, ts=_ts(9, 16, 2))

    assert len(emitted) == 1, f"expected 1 emitted bar, got {len(emitted)}"
    bar = emitted[0]
    assert bar["symbol"] == "RELIANCE"
    assert bar["timeframe"] == "1min"
    assert bar["open"] == 100.0
    assert bar["high"] == 102.0
    assert bar["low"] == 99.0
    assert bar["close"] == 99.0
    # Per-bar volume = 1500 (last cumulative in bar) - 1000 (cumulative at open)
    assert bar["volume"] == 500, f"expected volume 500, got {bar['volume']}"
    assert "_vol_start" not in bar, "internal field must not leak"
    print(f"  Emitted bar: {bar}")
    return True


def test_five_minute_aggregation() -> bool:
    print("Testing 5-minute aggregation...")
    emitted = []
    agg = CandleAggregator("TCS", interval_minutes=5, timeframe_label="5min",
                           on_candle=emitted.append)

    # All within the 9:15-9:20 bucket
    agg.update(ltp=3000.0, volume=500,  ts=_ts(9, 15, 5))
    agg.update(ltp=3010.0, volume=800,  ts=_ts(9, 17, 0))
    agg.update(ltp=2995.0, volume=1100, ts=_ts(9, 19, 59))
    # Crosses into 9:20 bucket -> closes 9:15 5-min bar
    agg.update(ltp=3005.0, volume=1300, ts=_ts(9, 20, 1))

    assert len(emitted) == 1
    bar = emitted[0]
    assert bar["symbol"] == "TCS" and bar["timeframe"] == "5min"
    assert bar["timestamp"] == _ts(9, 15)
    assert bar["open"] == 3000.0 and bar["high"] == 3010.0
    assert bar["low"] == 2995.0 and bar["close"] == 2995.0
    assert bar["volume"] == 600, f"expected 600, got {bar['volume']}"  # 1100-500
    print(f"  Emitted bar: {bar}")
    return True


if __name__ == "__main__":
    print("Data Feed Aggregator Test\n" + "=" * 40)
    try:
        test_timeframe_parsing()
        test_one_minute_aggregation()
        test_five_minute_aggregation()
        print("\nAll data feed tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
