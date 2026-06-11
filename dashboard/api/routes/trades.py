"""Trade history and performance analytics endpoints."""

from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Query

from data.db import get_trade_log, execute_query, to_records
from analytics.pnl_tracker import PnLTracker

router = APIRouter()
_tracker = PnLTracker()


@router.get("/")
def get_trades(limit: int = Query(default=100, le=500),
               mode: Optional[str] = Query(default=None)):
    """Return recent trade log. Optional ?mode=PAPER|LIVE to isolate virtual vs real."""
    return to_records(get_trade_log(limit=limit, mode=mode))


@router.get("/equity-curve")
def get_equity_curve(days: int = Query(default=90, le=365)):
    """Return equity curve data for dashboard chart."""
    return to_records(_tracker.get_equity_data(days=days))


@router.get("/daily-stats")
def get_daily_stats(mode: Optional[str] = Query(default=None)):
    """Today's performance stats. Optional ?mode=PAPER|LIVE."""
    return _tracker.compute_daily_stats(mode=mode)


@router.get("/performance-history")
def get_performance_history(days: int = Query(default=30, le=365)):
    """Daily performance table for the last N days."""
    df = execute_query("""
        SELECT * FROM daily_performance
        ORDER BY date DESC
        LIMIT ?
    """, [days])
    return to_records(df)


@router.get("/by-strategy")
def get_trades_by_strategy():
    """Performance grouped by strategy."""
    # Win/loss + totals on NET pnl (COALESCE for legacy rows without net_pnl) so a
    # gross-positive cost-eaten trade isn't counted as a win (PnL-NET).
    df = execute_query("""
        SELECT
            strategy,
            COUNT(*) AS total_trades,
            SUM(CASE WHEN COALESCE(net_pnl, pnl) > 0 THEN 1 ELSE 0 END) AS wins,
            ROUND(AVG(CASE WHEN COALESCE(net_pnl, pnl) > 0 THEN 1.0 ELSE 0.0 END), 4) AS win_rate,
            ROUND(SUM(COALESCE(net_pnl, pnl)), 2) AS total_pnl,
            ROUND(SUM(pnl), 2) AS gross_pnl,
            ROUND(AVG(COALESCE(net_pnl, pnl)), 2) AS avg_pnl,
            ROUND(AVG(pnl_pct), 4) AS avg_pnl_pct
        FROM trade_log
        WHERE status = 'CLOSED'
        GROUP BY strategy
        ORDER BY total_pnl DESC
    """)
    return to_records(df)
