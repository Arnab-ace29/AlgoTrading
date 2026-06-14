"""Backtest metrics — turn a trades DataFrame into summary stats + an equity curve."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe(x, nd=2):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return 0.0


def equity_curve(trades: pd.DataFrame, capital: float) -> pd.DataFrame:
    """Daily equity from cumulative net PnL."""
    if trades.empty:
        return pd.DataFrame(columns=["date", "daily_net", "equity"])
    daily = trades.groupby("date")["net_pnl"].sum().reset_index(name="daily_net")
    daily["equity"] = capital + daily["daily_net"].cumsum()
    return daily


def max_drawdown(equity: pd.Series) -> float:
    """Max drawdown as a fraction (e.g. 0.12 = 12%)."""
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min())


def compute_metrics(trades: pd.DataFrame, capital: float) -> dict:
    if trades.empty:
        return {"total_trades": 0}

    wins = trades[trades["net_pnl"] > 0]
    losses = trades[trades["net_pnl"] <= 0]
    eq = equity_curve(trades, capital)
    daily = eq["daily_net"]

    gross_profit = wins["net_pnl"].sum()
    gross_loss = abs(losses["net_pnl"].sum())
    sharpe = 0.0
    if len(daily) > 1 and daily.std(ddof=1) > 0:
        sharpe = float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))
    sortino = 0.0
    downside = daily[daily < 0]
    if len(downside) > 1 and downside.std(ddof=1) > 0:
        sortino = float(daily.mean() / downside.std(ddof=1) * np.sqrt(252))

    net = trades["net_pnl"].sum()
    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _safe(len(wins) / len(trades) * 100, 1),
        "avg_win": _safe(wins["net_pnl"].mean() if len(wins) else 0),
        "avg_loss": _safe(losses["net_pnl"].mean() if len(losses) else 0),
        "expectancy_R": _safe(trades["R_multiple"].mean(), 3),
        "avg_R_win": _safe(wins["R_multiple"].mean() if len(wins) else 0, 2),
        "avg_R_loss": _safe(losses["R_multiple"].mean() if len(losses) else 0, 2),
        "profit_factor": _safe(gross_profit / gross_loss if gross_loss else np.inf, 2),
        "net_pnl": _safe(net),
        "return_pct": _safe(net / capital * 100, 2),
        "sharpe": _safe(sharpe, 2),
        "sortino": _safe(sortino, 2),
        "max_drawdown_pct": _safe(max_drawdown(eq["equity"]) * 100, 2),
        "trading_days": int(eq["date"].nunique()),
        "avg_trades_per_day": _safe(len(trades) / max(1, eq["date"].nunique()), 1),
        "avg_mfe_R": _safe(trades["mfe_R"].mean(), 2),
        "avg_mae_R": _safe(trades["mae_R"].mean(), 2),
    }


def breakdown(trades: pd.DataFrame, by: str) -> pd.DataFrame:
    """Group trades and report count / win-rate / expectancy per bucket."""
    if trades.empty or by not in trades.columns:
        return pd.DataFrame()
    g = trades.groupby(by)
    out = pd.DataFrame({
        "trades": g.size(),
        "win_rate": g["net_pnl"].apply(lambda s: round((s > 0).mean() * 100, 1)),
        "net_pnl": g["net_pnl"].sum().round(0),
        "expectancy_R": g["R_multiple"].mean().round(3),
    })
    return out.reset_index()
