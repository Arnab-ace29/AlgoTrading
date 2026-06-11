"""
PnL Tracker — computes daily performance stats and maintains equity curve.
Called by live/runner.py at EOD and by the dashboard API.
"""

from __future__ import annotations
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import TRADING_CAPITAL
from analytics.costs import round_trip_cost
from data.db import (
    upsert_daily_performance, get_equity_curve, execute_query
)


class PnLTracker:

    def __init__(self, capital: float = TRADING_CAPITAL):
        self.capital = capital

    @staticmethod
    def _net_series(trades: pd.DataFrame) -> pd.Series:
        """
        Net (cost-adjusted) pnl per trade, robust across schema versions:
          • use the stored `net_pnl` column where present (new rows),
          • else `pnl - cost` if a stored cost exists,
          • else recompute the round-trip cost from entry/exit/qty (legacy rows).
        This is the single source of truth for win/loss + Kelly classification, so a
        gross-positive but cost-negative trade is correctly counted as a loss (PnL-NET).
        """
        if trades is None or trades.empty:
            return pd.Series(dtype=float)
        gross = pd.to_numeric(trades.get("pnl"), errors="coerce")
        if "net_pnl" in trades.columns:
            net = pd.to_numeric(trades["net_pnl"], errors="coerce")
        else:
            net = pd.Series([float("nan")] * len(trades), index=trades.index)
        # Fill any missing net from cost, then from a fresh cost computation.
        if "cost" in trades.columns:
            cost = pd.to_numeric(trades["cost"], errors="coerce")
            net = net.fillna(gross - cost)
        recomputed = trades.apply(
            lambda r: (r.get("pnl") or 0.0) - round_trip_cost(
                r.get("entry_price"), r.get("exit_price"), r.get("qty")),
            axis=1,
        )
        return net.fillna(recomputed).fillna(gross).astype(float)

    def compute_daily_stats(self, trade_date: Optional[date] = None,
                            mode: Optional[str] = None) -> dict:
        """
        Compute performance stats for a given date (default: today).
        `mode` ('PAPER' | 'LIVE') isolates virtual paper-trading results from real
        ones, so a forward/paper-test day reports cleanly on its own.
        """
        if trade_date is None:
            trade_date = date.today()

        if mode:
            trades = execute_query("""
                SELECT * FROM trade_log
                WHERE date(entry_time) = ? AND status = 'CLOSED' AND mode = ?
            """, [str(trade_date), mode.upper()])
        else:
            trades = execute_query("""
                SELECT * FROM trade_log
                WHERE date(entry_time) = ? AND status = 'CLOSED'
            """, [str(trade_date)])

        if trades.empty:
            return self._empty_stats(trade_date)

        # Win/loss is decided on NET pnl (after costs) — a trade the broker fees turn
        # negative is a loss, not a win (PnL-NET). This is what the win-rate metric,
        # the Kelly sizer and the success criteria all key off.
        net = self._net_series(trades)
        wins   = trades[net > 0]
        losses = trades[net < 0]   # breakeven (net == 0) is neither win nor loss

        total_trades  = len(trades)
        win_count     = len(wins)
        loss_count    = len(losses)
        win_rate      = win_count / total_trades if total_trades > 0 else 0
        gross_pnl     = float(pd.to_numeric(trades["pnl"], errors="coerce").sum())
        net_pnl       = float(net.sum())
        total_costs   = gross_pnl - net_pnl

        # Hold time in minutes
        trades["hold_minutes"] = (
            pd.to_datetime(trades["exit_time"]) - pd.to_datetime(trades["entry_time"])
        ).dt.total_seconds() / 60
        avg_hold = float(trades["hold_minutes"].mean()) if total_trades > 0 else 0

        # Equity at end of day (net of costs)
        prev_capital = self._get_capital_yesterday()
        capital_end  = prev_capital + net_pnl

        return {
            "date":             str(trade_date),
            "total_trades":     total_trades,
            "wins":             win_count,
            "losses":           loss_count,
            "win_rate":         round(win_rate, 4),
            "gross_pnl":        round(gross_pnl, 2),
            "total_costs":      round(total_costs, 2),
            "net_pnl":          round(net_pnl, 2),
            "max_drawdown_pct": 0.0,   # computed on equity curve, not daily
            "sharpe_rolling":   self._rolling_sharpe(),
            "capital_end":      round(capital_end, 2),
            "best_trade":       round(float(trades["pnl"].max()), 2) if total_trades > 0 else 0,
            "worst_trade":      round(float(trades["pnl"].min()), 2) if total_trades > 0 else 0,
            "avg_hold_minutes": round(avg_hold, 1),
            "regime_of_day":    "",
        }

    def save_daily(self, session_pnl: float, trade_date: Optional[date] = None) -> None:
        """Compute and persist today's stats to SQLite. Called at EOD."""
        stats = self.compute_daily_stats(trade_date)
        upsert_daily_performance(stats)
        logger.info(
            f"Daily stats saved | Trades={stats['total_trades']} "
            f"WR={stats['win_rate']:.0%} net PnL={stats['net_pnl']:+.2f} "
            f"(gross {stats['gross_pnl']:+.2f}, costs {stats['total_costs']:.2f})"
        )

    def get_equity_data(self, days: int = 90) -> pd.DataFrame:
        """Return equity curve DataFrame for dashboard chart."""
        return get_equity_curve(days)

    def recent_win_rate(self, n: int = 10) -> float:
        """Net win rate over the last N closed trades (for the RL entry state)."""
        try:
            df = execute_query("""
                SELECT pnl, cost, net_pnl, entry_price, exit_price, qty FROM trade_log
                WHERE status = 'CLOSED'
                ORDER BY exit_time DESC LIMIT ?
            """, [n])
            if df.empty:
                return 0.5
            return float((self._net_series(df) > 0).mean())
        except Exception:
            return 0.5

    def kelly_stats(self, n: int = 50) -> tuple[float, float, int]:
        """
        Kelly inputs for the live position sizer (issue SIZE-03), as a tuple
        ``(win_rate, reward_risk_ratio, total_closed_trades)``:

          • ``win_rate``  — rolling fraction of winners over the last ``n`` closed
            trades (breakeven counts as non-win).
          • ``reward_risk_ratio`` — empirical Kelly odds ``b`` = avg win / avg loss
            (absolute), over the same window. Clamped to [0.1, 5.0] so a single
            tiny loss can't blow up the fraction.
          • ``total_closed_trades`` — all-time closed-trade count, which the sizer
            uses to gate Kelly on (active only after 20 trades).

        Returns the sizer's safe defaults ``(0.55, 1.5, 0)`` on any error / no data.
        """
        try:
            df = execute_query("""
                SELECT pnl, cost, net_pnl, entry_price, exit_price, qty FROM trade_log
                WHERE status = 'CLOSED' AND pnl IS NOT NULL
                ORDER BY exit_time DESC LIMIT ?
            """, [n])
            total = int(execute_query(
                "SELECT COUNT(*) AS c FROM trade_log WHERE status = 'CLOSED' AND pnl IS NOT NULL"
            ).iloc[0]["c"])
        except Exception:
            return 0.55, 1.5, 0

        if df.empty:
            return 0.55, 1.5, total

        # Kelly edge is computed on NET pnl — sizing up on a gross edge that costs
        # erase would systematically over-bet (PnL-NET).
        net = self._net_series(df)
        wins   = net[net > 0]
        losses = net[net < 0]
        win_rate = float((net > 0).mean())
        avg_win  = float(wins.mean())   if not wins.empty   else 0.0
        avg_loss = float(-losses.mean()) if not losses.empty else 0.0   # positive magnitude
        rr = (avg_win / avg_loss) if avg_loss > 0 else 1.5
        rr = max(0.1, min(5.0, rr))
        return round(win_rate, 4), round(rr, 3), total

    def _rolling_sharpe(self, window: int = 20) -> float:
        """Rolling Sharpe over last N trading days."""
        try:
            df = execute_query("""
                SELECT net_pnl FROM daily_performance
                ORDER BY date DESC LIMIT ?
            """, [window])
            if df.empty or len(df) < 5:
                return 0.0
            returns = df["net_pnl"].values / self.capital
            if returns.std() == 0:
                return 0.0
            return float(np.sqrt(252) * returns.mean() / returns.std())
        except Exception:
            return 0.0

    def _get_capital_yesterday(self) -> float:
        """Get capital at end of previous trading day."""
        try:
            row = execute_query("""
                SELECT capital_end FROM daily_performance
                ORDER BY date DESC LIMIT 1
            """)
            if not row.empty:
                return float(row.iloc[0]["capital_end"])
        except Exception:
            pass
        return self.capital

    @staticmethod
    def _empty_stats(trade_date: date) -> dict:
        return {
            "date": str(trade_date), "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "gross_pnl": 0.0, "total_costs": 0.0, "net_pnl": 0.0,
            "max_drawdown_pct": 0.0, "sharpe_rolling": 0.0, "capital_end": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0, "avg_hold_minutes": 0.0,
            "regime_of_day": "",
        }
