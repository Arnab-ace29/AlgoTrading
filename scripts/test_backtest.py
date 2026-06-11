"""
Tests for the event-driven backtest engine (BT-01..04).

Runs with the project venv (needs pandas + ta):
    .venv/bin/python scripts/test_backtest.py

Uses an injected candle loader + a stubbed aggregator so entries fire on a known
bar — this lets us assert the intrabar SL/target fill behaviour deterministically
without depending on the real 80-feature ensemble crossing a threshold.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine, Trade, _metrics
from signals.base import Direction

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


# ── Stub aggregator: fire LONG on a chosen bar index, else NEUTRAL ────────────
class _Result:
    def __init__(self, score, direction, actionable):
        self.composite_score = score
        self.direction = direction
        self.actionable = actionable
        self.regime = type("R", (), {"value": "TRENDING_UP"})()


class _StubAgg:
    def __init__(self, fire_after: int, direction: Direction = Direction.LONG):
        self.fire_after = fire_after   # fire once when the slice length first exceeds this
        self.direction = direction
        self.fired = False

    def compute(self, df, symbol):
        if not self.fired and len(df) > self.fire_after:
            self.fired = True
            score = 0.80 if self.direction == Direction.LONG else -0.80
            return _Result(score, self.direction, True)
        return _Result(0.0, Direction.NEUTRAL, False)


def _make_loader(closes):
    """Return a loader producing a daily OHLCV frame from a close path."""
    n = len(closes)
    start = datetime(2024, 1, 1)
    ts = [start + timedelta(days=i) for i in range(n)]

    def loader(symbol, timeframe, from_dt, to_dt):
        c = np.asarray(closes, dtype=float)
        # high/low straddle close by ±0.3% by default; caller can pre-bake dips into closes
        df = pd.DataFrame({
            "timestamp": ts, "symbol": symbol, "timeframe": timeframe,
            "open": c, "high": c * 1.003, "low": c * 0.997,
            "close": c, "volume": np.full(n, 200_000.0),
        })
        return df
    return loader, ts


def test_metrics_pure():
    print("metrics:")
    def mk(net, day, entry=100.0, qty=10):
        exit_p = entry + net / qty
        return Trade("X", 0, "BUY", qty, datetime(2024, 1, day), datetime(2024, 1, day),
                     entry, exit_p, net, 0.0, net, net / (entry * qty), 1,
                     "T", 0.7)
    trades = [mk(500, 1), mk(-200, 2), mk(300, 3), mk(-100, 4)]   # 2W/2L, net +500
    m = _metrics(trades)
    check(m["total_trades"] == 4, "counts all trades")
    check(m["win_rate"] == 50.0, "win rate 50%")
    check(m["net_pnl"] == 500.0, "net pnl summed")
    check(abs(m["profit_factor"] - (800 / 300)) < 0.01, "profit factor = gross win / gross loss")
    check(m["total_return"] > 0, "positive total return on net-positive book")
    check(m["max_drawdown"] >= 0, "drawdown non-negative")
    check(_metrics([])["total_trades"] == 0, "empty trade list → zeros")


def test_intrabar_stop_fill():
    print("intrabar SL fill (BT-02):")
    # 70 flat bars (entry fires ~bar 60), then a bar that gaps DOWN hard so low <= SL.
    closes = [100.0] * 70
    closes[65] = 80.0   # a -20% bar after entry → low (79.76) well below any ATR stop
    loader, ts = _make_loader(closes)
    eng = BacktestEngine(aggregator=_StubAgg(fire_after=60), loader=loader)
    # 5min timeframe → max_hold=78 bars, so the position survives to the dip at bar 65
    res = eng.run(["X"], "2024-01-01", "2024-12-31", timeframe="5min", walk_forward=False)
    trades = res.trades
    check(len(trades) == 1, "exactly one trade taken")
    if trades:
        t = trades[0]
        check(t.exit_reason == "SL_HIT", "exited via stop-loss")
        check(t.exit_price < t.entry_price, "stop fill below entry (not at the recovered close)")
        check(t.net_pnl < 0, "loss net of costs")
        check(t.cost > 0, "transaction cost applied (BT-03/PnL)")


def test_intrabar_target_fill():
    print("intrabar target fill (BT-02):")
    closes = [100.0] * 70
    closes[64] = 130.0   # +30% bar → high above target
    loader, ts = _make_loader(closes)
    eng = BacktestEngine(aggregator=_StubAgg(fire_after=60), loader=loader)
    res = eng.run(["X"], "2024-01-01", "2024-12-31", timeframe="5min", walk_forward=False)
    trades = res.trades
    check(len(trades) == 1, "exactly one trade taken")
    if trades:
        t = trades[0]
        check(t.exit_reason == "TARGET_HIT", "exited via target")
        check(t.exit_price > t.entry_price, "target fill above entry")
        check(t.return_pct > 0, "positive net return on notional")


def test_short_target_fill():
    print("short-side target fill (profit when price falls):")
    closes = [100.0] * 70
    closes[64] = 70.0    # -30% bar → low below a short's target
    loader, ts = _make_loader(closes)
    eng = BacktestEngine(aggregator=_StubAgg(fire_after=60, direction=Direction.SHORT), loader=loader)
    res = eng.run(["X"], "2024-01-01", "2024-12-31", timeframe="5min", walk_forward=False)
    check(len(res.trades) == 1, "exactly one short trade taken")
    if res.trades:
        t = res.trades[0]
        check(t.side == "SELL", "trade booked as SELL (short)")
        check(t.exit_reason == "TARGET_HIT", "short exited via target")
        check(t.exit_price < t.entry_price, "short target fill below entry")
        check(t.net_pnl > 0, "short is profitable when price falls (net of costs)")


def test_short_stop_fill():
    print("short-side stop fill (loss when price spikes up):")
    closes = [100.0] * 70
    closes[64] = 130.0   # +30% bar → high above a short's stop
    loader, ts = _make_loader(closes)
    eng = BacktestEngine(aggregator=_StubAgg(fire_after=60, direction=Direction.SHORT), loader=loader)
    res = eng.run(["X"], "2024-01-01", "2024-12-31", timeframe="5min", walk_forward=False)
    check(len(res.trades) == 1, "exactly one short trade taken")
    if res.trades:
        t = res.trades[0]
        check(t.exit_reason == "SL_HIT", "short stopped out")
        check(t.exit_price > t.entry_price, "short stop fill above entry")
        check(t.net_pnl < 0, "short loses when price spikes up")


def _intraday_loader(days_n: int, bars_per_day: int = 75):
    """Loader producing real 5-min UTC timestamps across multiple IST sessions."""
    import numpy as _np
    rows_ts = []
    base = pd.Timestamp("2026-03-02 03:45:00", tz="UTC")  # 09:15 IST
    for d in range(days_n):
        day0 = base + pd.Timedelta(days=d)
        for b in range(bars_per_day):
            rows_ts.append(day0 + pd.Timedelta(minutes=5 * b))
    ts = pd.DatetimeIndex(rows_ts)
    n = len(ts)
    c = _np.full(n, 100.0)   # flat → no SL/target, must EOD-square-off each day

    def loader(symbol, timeframe, from_dt, to_dt):
        return pd.DataFrame({
            "timestamp": ts, "symbol": symbol, "timeframe": timeframe,
            "open": c, "high": c * 1.001, "low": c * 0.999, "close": c,
            "volume": _np.full(n, 200_000.0),
        })
    return loader, ts


def test_eod_squareoff_intraday():
    print("intraday EOD square-off (BT-06 — no overnight holds):")
    loader, ts = _intraday_loader(days_n=3)
    eng = BacktestEngine(aggregator=_StubAgg(fire_after=60), loader=loader)
    res = eng.run(["X"], "2026-03-01", "2026-03-10", timeframe="5min", walk_forward=False)
    check(len(res.trades) >= 1, "at least one trade taken on intraday data")
    if res.trades:
        # No trade may span more than one IST calendar day (strictly intraday).
        spans = []
        for t in res.trades:
            e = pd.Timestamp(t.entry_time).tz_localize("UTC").tz_convert("Asia/Kolkata").date() \
                if pd.Timestamp(t.entry_time).tz is None else pd.Timestamp(t.entry_time).tz_convert("Asia/Kolkata").date()
            x = pd.Timestamp(t.exit_time).tz_localize("UTC").tz_convert("Asia/Kolkata").date() \
                if pd.Timestamp(t.exit_time).tz is None else pd.Timestamp(t.exit_time).tz_convert("Asia/Kolkata").date()
            spans.append(e == x)
        check(all(spans), "every trade entered and exited within the same IST session")
        check(any(t.exit_reason == "EOD" for t in res.trades), "flat position is squared off at EOD")


def test_next_bar_open_entry():
    print("next-bar-open entry fill (no same-bar look-ahead):")
    # Signal fires at the bar where len>60 (pos 60); entry must fill at bar 61's OPEN.
    closes = [100.0] * 70
    loader, ts = _make_loader(closes)
    eng = BacktestEngine(aggregator=_StubAgg(fire_after=60), loader=loader)
    res = eng.run(["X"], "2024-01-01", "2024-12-31", timeframe="5min", walk_forward=False)
    check(len(res.trades) == 1, "a trade is taken")
    if res.trades:
        # entry_time must be the bar AFTER the signal bar (index 61, not 60).
        check(res.trades[0].entry_time == ts[61], f"entry filled at next bar's open ({res.trades[0].entry_time})")


def test_no_entry_no_trades():
    print("no signal → no trades:")
    loader, _ = _make_loader([100.0] * 70)

    class _Never:
        def compute(self, df, symbol):
            return _Result(0.0, Direction.NEUTRAL, False)

    eng = BacktestEngine(aggregator=_Never(), loader=loader)
    res = eng.run(["X"], "2024-01-01", "2024-12-31", timeframe="1day", walk_forward=False)
    check(len(res.trades) == 0, "zero trades when nothing fires")
    s = res.summary()
    check(s["total_trades"] == 0 and s["sharpe"] == 0.0, "summary is well-formed and zeroed")


def test_summary_contract():
    print("summary API contract:")
    loader, _ = _make_loader([100.0] * 70)
    eng = BacktestEngine(aggregator=_StubAgg(fire_after=60), loader=loader)
    s = eng.run(["X"], "2024-01-01", "2024-12-31", timeframe="1day", walk_forward=False).summary()
    for k in ("run_id", "total_return", "sharpe", "max_drawdown", "win_rate",
              "total_trades", "avg_trade_pct", "per_fold", "params"):
        check(k in s, f"summary has '{k}'")


def main() -> int:
    print("=" * 60); print("BACKTEST ENGINE TESTS"); print("=" * 60)
    test_metrics_pure()
    test_intrabar_stop_fill()
    test_intrabar_target_fill()
    test_short_target_fill()
    test_short_stop_fill()
    test_eod_squareoff_intraday()
    test_next_bar_open_entry()
    test_no_entry_no_trades()
    test_summary_contract()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
