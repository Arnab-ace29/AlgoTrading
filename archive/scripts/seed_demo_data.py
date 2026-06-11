"""
Seed synthetic data so the dashboard has something to show in paper/dev mode.

DEMO/DEV ONLY — writes fake candles, trades, and a daily-performance equity curve
into SQLite. Safe to re-run. Never run against a real trading DB.

    python scripts/seed_demo_data.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from data.db import init_db, write_candles, log_trade_open, log_trade_close, upsert_daily_performance

# symbol → (start price, daily drift) — varied so the screener ranking differs
SYMBOLS = {
    "RELIANCE":  (2950, 0.0015),
    "TCS":       (3900, 0.0010),
    "INFY":      (1850, 0.0008),
    "HDFCBANK":  (1650, 0.0005),
    "ICICIBANK": (1150, 0.0012),
    "SBIN":      (820,  0.0002),
    "AXISBANK":  (1100, -0.0005),
    "WIPRO":     (480,  -0.0010),
}
N_BARS = 120
rng = np.random.default_rng(7)


def seed_candles() -> None:
    days = pd.bdate_range(end=date.today(), periods=N_BARS)
    ts = [datetime.combine(d.date(), dtime(15, 25)) for d in days]
    for sym, (p0, drift) in SYMBOLS.items():
        rets = rng.normal(drift, 0.012, N_BARS)
        close = p0 * np.cumprod(1 + rets)
        op = close * (1 + rng.normal(0, 0.003, N_BARS))
        hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.004, N_BARS)))
        lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.004, N_BARS)))
        vol = rng.integers(100_000, 500_000, N_BARS).astype(float)
        vol[-1] *= 2.5   # recent volume surge
        df = pd.DataFrame({
            "timestamp": ts, "symbol": sym, "timeframe": "5min",
            "open": op, "high": hi, "low": lo, "close": close, "volume": vol,
        })
        n = write_candles(df, source="seed")
        print(f"  candles: {sym:<10} {n} bars")


def seed_trades() -> None:
    trades = [
        ("RELIANCE",  2900, 2948, "BUY",  "TARGET_HIT"),
        ("TCS",       3955, 3902, "BUY",  "SL_HIT"),
        ("INFY",      1820, 1864, "BUY",  "TARGET_HIT"),
        ("ICICIBANK", 1130, 1158, "BUY",  "TARGET_HIT"),
        ("WIPRO",      488,  479, "BUY",  "SL_HIT"),
    ]
    for sym, entry, exit_px, side, reason in trades:
        tid = log_trade_open(
            symbol=sym, strategy="vwap_rsi_ensemble", side=side, product_type="INTRADAY",
            qty=10, entry_price=entry, sl_price=entry * 0.99, target_price=entry * 1.02,
            entry_score=0.71, regime="TRENDING_UP", openalgo_order_id="SEED",
        )
        log_trade_close(tid, exit_px, reason, "SEED")
        print(f"  trade:   {sym:<10} {side} {entry}->{exit_px} ({reason})")


def seed_equity_curve() -> None:
    cap = 100_000.0
    for d in pd.bdate_range(end=date.today(), periods=15):
        total = int(rng.integers(2, 8))
        wins = int(rng.integers(0, total + 1))
        gross = float(rng.normal(450, 900))
        net = gross * 0.97
        cap += net
        upsert_daily_performance({
            "date": str(d.date()), "total_trades": total, "wins": wins,
            "losses": total - wins, "win_rate": round(wins / total, 4) if total else 0.0,
            "gross_pnl": round(gross, 2), "net_pnl": round(net, 2),
            "max_drawdown_pct": 0.0, "sharpe_rolling": 1.2, "capital_end": round(cap, 2),
            "best_trade": round(abs(gross) * 0.6, 2), "worst_trade": round(-abs(gross) * 0.4, 2),
            "avg_hold_minutes": 42.0, "regime_of_day": "TRENDING_UP",
        })
    print(f"  equity:  15 days, capital_end ≈ ₹{cap:,.0f}")


def main() -> int:
    print("Seeding demo data (DEV ONLY)…")
    init_db()
    seed_candles()
    seed_trades()
    seed_equity_curve()
    print("Done. Refresh the dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
