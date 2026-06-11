"""
Analytics endpoints — the "more data for tracking + run simulations" layer (DASH-02..05).

All endpoints are GET (read-only / idempotent) so they bypass the mutating-route
auth gate. PnL is decomposed gross → cost → net so a no-edge strategy is obvious
(this is what hid BT-EDGE). R-multiples and the what-if simulator let you judge and
re-price the trade log without re-running the engine.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query

from data.db import execute_query, to_records
from analytics.pnl_tracker import PnLTracker
from analytics.costs import round_trip_cost

router = APIRouter()
_tracker = PnLTracker()


def _safe(x, nd: int = 2):
    """Round + make JSON-safe (None for NaN/Inf)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _closed_trades(days: Optional[int], mode: Optional[str]) -> pd.DataFrame:
    where = ["status = 'CLOSED'"]
    params: list = []
    if mode:
        where.append("mode = ?")
        params.append(mode.upper())
    if days and days < 9999:
        where.append("date(entry_time) >= date('now', ?)")
        params.append(f"-{int(days)} days")
    return execute_query(
        "SELECT symbol, side, qty, entry_price, exit_price, sl_price, pnl, cost, net_pnl, "
        "pnl_pct, entry_score, exit_reason, regime_at_entry, entry_time, exit_time, mode "
        f"FROM trade_log WHERE {' AND '.join(where)} ORDER BY exit_time ASC",
        params,
    )


def _net(df: pd.DataFrame) -> pd.Series:
    return _tracker._net_series(df)


def _risk(df: pd.DataFrame) -> pd.Series:
    """Per-trade capital at risk = |entry - sl| × qty (the R denominator)."""
    entry = pd.to_numeric(df.get("entry_price"), errors="coerce")
    sl    = pd.to_numeric(df.get("sl_price"), errors="coerce")
    qty   = pd.to_numeric(df.get("qty"), errors="coerce")
    return (entry - sl).abs() * qty


def _aggregate(df: pd.DataFrame, net: pd.Series) -> dict:
    n = len(df)
    if n == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "gross_pnl": 0.0,
                "costs": 0.0, "net_pnl": 0.0, "expectancy": 0.0, "profit_factor": None,
                "avg_win": 0.0, "avg_loss": 0.0, "gross_bps": None, "cost_bps": None,
                "avg_R": None, "expectancy_R": None}
    gross = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    wins, losses = net[net > 0], net[net < 0]
    notional = (pd.to_numeric(df["entry_price"], errors="coerce") * pd.to_numeric(df["qty"], errors="coerce")).sum()
    risk = _risk(df)
    R = (net / risk).replace([np.inf, -np.inf], np.nan).dropna()
    pf = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else (float("inf") if len(wins) else 0.0)
    return {
        "trades": n,
        "wins": int((net > 0).sum()),
        "losses": int((net < 0).sum()),
        "win_rate": _safe(100.0 * (net > 0).sum() / n, 1),
        "gross_pnl": _safe(gross.sum()),
        "costs": _safe(gross.sum() - net.sum()),
        "net_pnl": _safe(net.sum()),
        "expectancy": _safe(net.mean()),
        "profit_factor": _safe(pf, 3),
        "avg_win": _safe(wins.mean()) if len(wins) else 0.0,
        "avg_loss": _safe(losses.mean()) if len(losses) else 0.0,
        # bps of traded notional — the headline "is there edge?" read.
        "gross_bps": _safe(1e4 * gross.sum() / notional, 2) if notional else None,
        "cost_bps": _safe(1e4 * (gross.sum() - net.sum()) / notional, 2) if notional else None,
        "avg_R": _safe(R.mean(), 3) if len(R) else None,
        "expectancy_R": _safe(R.mean(), 3) if len(R) else None,
    }


@router.get("/summary")
def summary(days: int = Query(default=90, le=9999), mode: Optional[str] = Query(default=None)):
    """Gross/net/cost decomposition + win-rate + expectancy + R-multiple stats (DASH-02/03)."""
    df = _closed_trades(days, mode)
    agg = _aggregate(df, _net(df)) if not df.empty else _aggregate(df, pd.Series(dtype=float))
    agg["window_days"] = days
    agg["mode"] = mode or "ALL"
    return agg


@router.get("/r-multiples")
def r_multiples(days: int = Query(default=90, le=9999), mode: Optional[str] = Query(default=None)):
    """Per-trade R-multiples (net PnL ÷ risk) for a histogram + scatter (DASH-03)."""
    df = _closed_trades(days, mode)
    if df.empty:
        return []
    net, risk = _net(df), _risk(df)
    out = pd.DataFrame({
        "symbol": df["symbol"], "exit_reason": df.get("exit_reason"),
        "net_pnl": net, "risk": risk,
        "R": (net / risk).replace([np.inf, -np.inf], np.nan),
        "entry_score": pd.to_numeric(df.get("entry_score"), errors="coerce"),
        "exit_time": df.get("exit_time"),
    })
    out = out[out["R"].notna()]
    return to_records(out)


@router.get("/by-exit-reason")
def by_exit_reason(days: int = Query(default=90, le=9999), mode: Optional[str] = Query(default=None)):
    """Net performance grouped by exit reason (SL_HIT / TARGET_HIT / REVERSAL / EOD)."""
    df = _closed_trades(days, mode)
    if df.empty:
        return []
    df = df.copy()
    df["_net"] = _net(df)
    rows = []
    for reason, g in df.groupby(df["exit_reason"].fillna("UNKNOWN")):
        rows.append({
            "exit_reason": reason, "trades": len(g),
            "net_pnl": _safe(g["_net"].sum()),
            "win_rate": _safe(100.0 * (g["_net"] > 0).mean(), 1),
            "avg_net": _safe(g["_net"].mean()),
        })
    return sorted(rows, key=lambda r: (r["net_pnl"] or 0), reverse=True)


@router.get("/whatif")
def whatif(
    days: int = Query(default=90, le=9999),
    mode: Optional[str] = Query(default=None),
    cost_mult: float = Query(default=1.0, ge=0.0, le=5.0),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0),
    only_target_exits: bool = Query(default=False),
):
    """
    Re-price the closed-trade log under different assumptions WITHOUT re-running the
    engine (DASH-04). Levers:
      • cost_mult — scale transaction costs (0.5 = "if costs were halved")
      • min_score — keep only trades whose entry_score ≥ this ("if I'd been more selective")
      • only_target_exits — drop trades that didn't reach target (exit-discipline what-if)
    Returns the baseline and the re-priced aggregate side by side.
    """
    df = _closed_trades(days, mode)
    baseline = _aggregate(df, _net(df)) if not df.empty else _aggregate(df, pd.Series(dtype=float))

    if df.empty:
        return {"baseline": baseline, "scenario": baseline, "params": {
            "cost_mult": cost_mult, "min_score": min_score, "only_target_exits": only_target_exits}}

    f = df.copy()
    if min_score > 0:
        f = f[pd.to_numeric(f["entry_score"], errors="coerce").fillna(0.0) >= min_score]
    if only_target_exits:
        f = f[f["exit_reason"] == "TARGET_HIT"]

    if f.empty:
        scenario = _aggregate(f, pd.Series(dtype=float))
    else:
        gross = pd.to_numeric(f["pnl"], errors="coerce").fillna(0.0)
        # cost: stored cost where present, else recompute; then scale by cost_mult.
        cost = pd.to_numeric(f.get("cost"), errors="coerce")
        cost = cost.fillna(f.apply(
            lambda r: round_trip_cost(r.get("entry_price"), r.get("exit_price"), r.get("qty")), axis=1))
        net = gross - cost * cost_mult
        scenario = _aggregate(f, net)

    return {"baseline": baseline, "scenario": scenario, "params": {
        "cost_mult": cost_mult, "min_score": min_score, "only_target_exits": only_target_exits,
        "kept_trades": int(len(f)), "dropped_trades": int(len(df) - len(f))}}


@router.get("/data-health")
def data_health():
    """
    Candle coverage / freshness per (symbol, timeframe, source) (DASH-05). Surfaces
    stale or demo-only data before you trust a backtest on it.
    """
    df = execute_query(
        "SELECT symbol, timeframe, source, COUNT(*) AS bars, "
        "MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts "
        "FROM minute_candles GROUP BY symbol, timeframe, source ORDER BY symbol, timeframe"
    )
    if df.empty:
        return {"rows": [], "symbols": 0, "total_bars": 0, "now_utc": datetime.now(timezone.utc).isoformat()}
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for _, r in df.iterrows():
        last = pd.to_datetime(r["last_ts"], utc=True, errors="coerce")
        age_h = (now - last).total_seconds() / 3600.0 if pd.notna(last) else None
        rows.append({
            "symbol": r["symbol"], "timeframe": r["timeframe"], "source": r["source"],
            "bars": int(r["bars"]),
            "first_ts": str(r["first_ts"]), "last_ts": str(r["last_ts"]),
            "age_hours": _safe(age_h, 1),
            "is_demo": str(r["source"] or "").lower() in ("demo", "seed", "seed_demo"),
        })
    return {
        "rows": rows,
        "symbols": int(df["symbol"].nunique()),
        "total_bars": int(df["bars"].sum()),
        "now_utc": now.isoformat(),
    }
