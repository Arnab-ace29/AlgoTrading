"""
Backtest engine for the H1 cross-sectional ranking strategy.

Pipeline (per trading day, no look-ahead):
  1. SIGNAL  — at the entry bar (default 09:45 IST) build a cross-section snapshot:
               per symbol = same-window RVOL + intraday return-from-open + ATR.
  2. SELECT  — strategy.ranking.select() ranks the cross-section, picks top/bottom %.
  3. SIZE    — ATR stop → strategy.sizing.position_size() (1% risk, daily cap).
  4. SIMULATE— fill at the NEXT bar's open (slipped), then walk bars forward applying
               ATR trailing stop + 10:30 time-stop, tracking MFE/MAE, booking net PnL.

Look-ahead safety: the signal uses bars with ts <= entry_time; the fill is the open of
the first bar with ts > entry_time. Nothing reads a future bar.

Two passes for memory safety on a 756-name / 2-yr DB:
  Pass A — scan each symbol once, extract per-day entry features (cheap table).
  Pass B — for the few daily picks, re-load that day's post-entry bars and simulate.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

ROOT = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(ROOT))

from config.settings import DB_PATH
from features.indicators import (
    to_ist, atr as atr_ind, rvol_same_window, intraday_return_from_open,
)
from strategy.ranking import select, RankParams
from strategy.sizing import position_size, SizingParams
from analytics.costs import round_trip_cost, slip_price


# ── Config ────────────────────────────────────────────────────────────────────
@dataclass
class BacktestConfig:
    from_date: str = "2025-06-01"
    to_date: str   = "2026-06-01"
    entry_time: str = "09:45"          # IST signal bar
    time_stop: str  = "10:30"          # IST hard exit
    eod_time: str   = "15:15"          # IST square-off
    atr_period: int = 14
    atr_stop_mult: float  = 1.5        # initial stop = entry -/+ this * ATR
    atr_trail_mult: float = 2.0        # trail distance from the best favorable price
    slippage_pct: float   = 0.005      # 0.5% per fill (fast momentum names)
    capital: float        = 20_000.0
    symbols: list[str] = field(default_factory=list)   # empty => all in universe table coverage
    rank: RankParams = field(default_factory=RankParams)
    sizing: SizingParams = field(default_factory=SizingParams)
    rvol_lookback_days: int = 20


def _ist_t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


# ── Pass A: per-symbol entry-bar features ─────────────────────────────────────
def _load_5m(conn, symbol: str, from_date: str, to_date: str) -> pd.DataFrame:
    q = """SELECT timestamp, open, high, low, close, volume
           FROM minute_candles WHERE symbol=? AND timeframe='5min'
             AND timestamp >= ? AND timestamp <= ?
           ORDER BY timestamp ASC"""
    df = pd.read_sql_query(q, conn, params=[symbol, from_date, to_date + " 23:59:59"])
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True)
    return df.set_index("timestamp")


def _load_daily_atr(conn, symbol: str, period: int) -> pd.Series:
    q = """SELECT timestamp, high, low, close FROM minute_candles
           WHERE symbol=? AND timeframe='1day' ORDER BY timestamp ASC"""
    d = pd.read_sql_query(q, conn, params=[symbol])
    if d.empty:
        return pd.Series(dtype=float)
    d["timestamp"] = pd.to_datetime(d["timestamp"], format="ISO8601", utc=True)
    d = d.set_index("timestamp")
    a = atr_ind(d, period)
    a.index = to_ist(a.index).normalize()   # key by IST date
    return a


def entry_features_for_symbol(conn, symbol: str, cfg: BacktestConfig) -> pd.DataFrame:
    """Per-day entry-bar features for one symbol. Returns date-indexed frame."""
    df = _load_5m(conn, symbol, cfg.from_date, cfg.to_date)
    if df.empty or len(df) < 50:
        return pd.DataFrame()

    rvol = rvol_same_window(df, cfg.rvol_lookback_days)
    rfo  = intraday_return_from_open(df)
    ist  = to_ist(df.index)
    day  = ist.normalize()
    tod  = pd.Series(ist.time, index=df.index)

    entry_t = _ist_t(cfg.entry_time)
    mask = tod == entry_t
    if not mask.any():
        return pd.DataFrame()

    daily_atr = _load_daily_atr(conn, symbol, cfg.atr_period)

    rows = []
    sub = df[mask]
    for ts in sub.index:
        d = pd.Timestamp(to_ist(pd.DatetimeIndex([ts]))[0]).normalize()
        # ATR from the PRIOR day's daily candle (no look-ahead).
        atr_val = np.nan
        if not daily_atr.empty:
            prior = daily_atr[daily_atr.index < d]
            if len(prior):
                atr_val = float(prior.iloc[-1])
        rows.append({
            "date": d.date(),
            "rvol": float(rvol.get(ts, np.nan)),
            "ret_open": float(rfo.get(ts, np.nan)),
            "entry_signal_price": float(df.loc[ts, "close"]),
            "atr": atr_val,
        })
    out = pd.DataFrame(rows).dropna(subset=["rvol", "ret_open", "atr"])
    out["symbol"] = symbol
    return out


# ── Pass B: simulate one trade forward ────────────────────────────────────────
def simulate_trade(path: pd.DataFrame, direction: str, entry_price: float,
                   atr: float, qty: int, cfg: BacktestConfig) -> dict:
    """
    Walk post-entry bars; apply ATR trailing stop + time/EOD exit. Track MFE/MAE.
    `path` = bars AFTER the entry signal bar (already slipped entry given separately).
    Returns a partial trade dict (prices, exit reason, mfe/mae in price units).
    """
    long = direction == "LONG"
    sign = 1.0 if long else -1.0
    stop = entry_price - sign * cfg.atr_stop_mult * atr
    best = entry_price                      # best favorable price seen
    mfe = 0.0                               # max favorable excursion (price, >=0)
    mae = 0.0                               # max adverse excursion (price, <=0)
    t_stop = _ist_t(cfg.time_stop)
    t_eod  = _ist_t(cfg.eod_time)

    exit_price, exit_reason, exit_ts = None, None, None
    for ts, bar in path.iterrows():
        tod = to_ist(pd.DatetimeIndex([ts]))[0].time()
        hi, lo, cl = bar["high"], bar["low"], bar["open"]  # use open as conservative ref
        # Excursions (favorable uses high for long / low for short).
        fav = (bar["high"] - entry_price) if long else (entry_price - bar["low"])
        adv = (bar["low"] - entry_price) if long else (entry_price - bar["high"])
        mfe = max(mfe, fav)
        mae = min(mae, adv)

        # Stop breach within the bar (conservative: filled at stop).
        breached = (bar["low"] <= stop) if long else (bar["high"] >= stop)
        if breached:
            exit_price, exit_reason, exit_ts = stop, "STOP", ts
            break

        # Time / EOD exit at this bar's open price.
        if tod >= t_stop or tod >= t_eod:
            exit_price, exit_reason, exit_ts = bar["open"], ("TIME" if tod >= t_stop else "EOD"), ts
            break

        # Trail the stop using the bar extreme in our favor.
        best = max(best, bar["high"]) if long else min(best, bar["low"])
        new_stop = best - sign * cfg.atr_trail_mult * atr
        stop = max(stop, new_stop) if long else min(stop, new_stop)

    if exit_price is None:   # ran out of bars
        last = path.iloc[-1]
        exit_price, exit_reason, exit_ts = last["close"], "EOD", path.index[-1]
        # whether it became a trail vs initial stop
    elif exit_reason == "STOP" and stop != entry_price - sign * cfg.atr_stop_mult * atr:
        exit_reason = "TRAIL"

    return {
        "exit_price": float(exit_price), "exit_reason": exit_reason, "exit_ts": exit_ts,
        "mfe_price": float(mfe), "mae_price": float(mae),
    }


# ── Orchestration ─────────────────────────────────────────────────────────────
def run_backtest(cfg: BacktestConfig) -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH), timeout=60)

    # Which symbols? default = everything with 5-min coverage in range.
    if cfg.symbols:
        symbols = cfg.symbols
    else:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM minute_candles WHERE timeframe='5min'"
        ).fetchall()
        symbols = sorted(r[0] for r in rows)
    logger.info(f"Backtest universe: {len(symbols)} symbols, {cfg.from_date}..{cfg.to_date}")

    # Pass A — entry features per symbol.
    feats = []
    for i, sym in enumerate(symbols, 1):
        f = entry_features_for_symbol(conn, sym, cfg)
        if not f.empty:
            feats.append(f)
        if i % 100 == 0:
            logger.info(f"  scanned {i}/{len(symbols)} symbols")
    if not feats:
        logger.warning("No entry features — empty backtest.")
        return pd.DataFrame()
    feat = pd.concat(feats, ignore_index=True)
    logger.info(f"Entry-feature rows: {len(feat)} across {feat['date'].nunique()} days")

    # Pass B — per day: rank, size, simulate.
    trades = []
    for d, day_feat in feat.groupby("date"):
        snap = day_feat.set_index("symbol")[["rvol", "ret_open"]]
        picks = select(snap, cfg.rank)
        if picks.empty:
            continue
        open_risk = 0.0
        for sym, prow in picks.iterrows():
            meta = day_feat[day_feat["symbol"] == sym].iloc[0]
            atr = float(meta["atr"])
            direction = prow["direction"]
            sign = 1.0 if direction == "LONG" else -1.0

            # Load that day's post-entry bars to find the fill + simulate.
            ds = pd.Timestamp(d).strftime("%Y-%m-%d")
            bars = _load_5m(conn, sym, ds, ds)
            if bars.empty:
                continue
            ist = to_ist(bars.index)
            after = bars[ist.time > _ist_t(cfg.entry_time)]
            if after.empty:
                continue
            raw_entry = float(after.iloc[0]["open"])           # next-bar open (no look-ahead)
            entry_price = slip_price(raw_entry, direction, cfg.slippage_pct)
            stop0 = entry_price - sign * cfg.atr_stop_mult * atr

            # Conviction from rank extremity: deeper into the tail => more conviction.
            conviction = 1.5 if abs(prow["rank_pct"] - 0.5) >= 0.49 else 1.0
            sz = position_size(cfg.capital, conviction, entry_price, stop0, atr,
                               cfg.sizing, open_risk)
            if sz.qty == 0:
                continue
            open_risk += sz.risk

            sim = simulate_trade(after.iloc[1:] if len(after) > 1 else after,
                                 direction, entry_price, atr, sz.qty, cfg)
            exit_price = slip_price(sim["exit_price"], "SELL" if direction == "LONG" else "BUY",
                                    cfg.slippage_pct)

            gross = sign * (exit_price - entry_price) * sz.qty
            cost  = round_trip_cost(entry_price, exit_price, sz.qty)
            net   = gross - cost
            risk_per_share = abs(entry_price - stop0) + cfg.sizing.slippage_pad_atr * atr
            r_mult = net / sz.risk if sz.risk else 0.0
            mfe_R = (sim["mfe_price"] * sz.qty) / sz.risk if sz.risk else 0.0
            mae_R = (sim["mae_price"] * sz.qty) / sz.risk if sz.risk else 0.0

            trades.append({
                "date": ds, "symbol": sym, "direction": direction,
                "signal": round(float(prow["signal"]), 5),
                "rank_pct": round(float(prow["rank_pct"]), 3),
                "conviction": conviction,
                "rvol": round(float(meta["rvol"]), 2),
                "ret_open_pct": round(float(meta["ret_open"]) * 100, 2),
                "atr": round(atr, 2),
                "entry_price": round(entry_price, 2),
                "stop_price": round(stop0, 2),
                "exit_price": round(exit_price, 2),
                "exit_reason": sim["exit_reason"],
                "qty": sz.qty, "exposure": round(sz.exposure, 0), "risk": round(sz.risk, 2),
                "gross_pnl": round(gross, 2), "cost": round(cost, 2), "net_pnl": round(net, 2),
                "pnl_pct": round((net / sz.exposure * 100) if sz.exposure else 0, 3),
                "R_multiple": round(r_mult, 3),
                "mfe_R": round(mfe_R, 2), "mae_R": round(mae_R, 2),
            })
    conn.close()
    tdf = pd.DataFrame(trades)
    logger.success(f"Backtest produced {len(tdf)} trades.")
    return tdf
