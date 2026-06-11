"""
Daily pre-market screener.

For each strategy, ranks its universe on EOD data (using only bars before `asof` —
no look-ahead) and writes the top-N candidates to config/daily_watchlist.json, which
live/runner.py reads at startup. A per-symbol score breakdown is written alongside
for transparency.

The scoring core lives in ranking_features.py (pure numpy). This module is the glue:
it loads daily OHLCV from SQLite (resampling intraday candles when no daily series
exists) and writes the outputs.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from config.settings import DAILY_WATCHLIST_PATH, SCREENER_TOP_N, SCREENER_LOOKBACK_DAYS
from screener import catalyst_detector
from screener.ranking_features import compute_metrics, momentum_rank, screener_score
from screener.universe import DEFAULT_STRATEGIES, universe_for_strategy

_BREAKDOWN_PATH = Path(DAILY_WATCHLIST_PATH).parent / "screener_breakdown.json"

# loader(symbol, asof, lookback_days) -> (dates, opens, highs, lows, closes, volumes) | None
Loader = Callable[[str, date, int], Optional[tuple]]


def _db_loader(symbol: str, asof: date, lookback_days: int) -> Optional[tuple]:
    """Load daily OHLCV from SQLite, resampling the finest available timeframe."""
    import pandas as pd                 # lazy: keeps the module importable without pandas
    from data.db import read_candles

    to_dt   = datetime.combine(asof, dtime.min)
    from_dt = datetime.combine(asof - timedelta(days=lookback_days + 60), dtime.min)

    df = None
    for tf in ("1day", "day", "15min", "5min", "1min"):
        try:
            cand = read_candles(symbol, tf, from_dt=from_dt, to_dt=to_dt)
        except Exception:
            cand = None
        if cand is not None and not cand.empty:
            df = cand
            break
    if df is None or df.empty:
        return None

    df = df.copy()
    df["d"] = pd.to_datetime(df["timestamp"]).dt.date
    g = (
        df.sort_values("timestamp")
          .groupby("d", as_index=False)
          .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
               close=("close", "last"), volume=("volume", "sum"))
          .sort_values("d")
    )
    return (
        list(g["d"]), list(g["open"]), list(g["high"]),
        list(g["low"]), list(g["close"]), list(g["volume"]),
    )


class DailyScreener:
    def __init__(self, top_n: int = SCREENER_TOP_N, lookback_days: int = SCREENER_LOOKBACK_DAYS,
                 loader: Optional[Loader] = None):
        self.top_n = top_n
        self.lookback_days = lookback_days
        self.loader = loader or _db_loader

    def _rank(self, strategy: str, symbols: list[str], asof: date, catalyst_table: dict) -> list[dict]:
        rows: list[dict] = []
        skipped = 0
        for sym in symbols:
            try:
                data = self.loader(sym, asof, self.lookback_days)
            except Exception as e:
                logger.debug(f"screener loader failed for {sym}: {e}")
                data = None
            if not data:
                skipped += 1
                continue
            dates, o, h, l, c, v = data
            m = compute_metrics(dates, o, h, l, c, v, asof)
            if m is None:
                skipped += 1
                continue
            cat_score, cat_reasons = catalyst_detector.get_catalyst_score(sym, asof, catalyst_table)
            rows.append({"symbol": sym, "metrics": m, "catalyst": cat_score, "catalyst_reasons": cat_reasons})

        # Cross-sectional momentum rank on 20-day return.
        ranks = momentum_rank([r["metrics"]["ret_20d"] for r in rows])
        for r, mr in zip(rows, ranks):
            m = r["metrics"]
            mr = mr if mr is not None else 0.0
            score = screener_score(
                technical_setup=m["technical_setup"],
                momentum_rank=mr,
                volume_surge=m["volume_surge"],
                volatility_opportunity=m["volatility_opportunity"],
                catalyst=r["catalyst"],
            )
            r["momentum_rank"] = round(mr, 4)
            r["score"] = score

        rows.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"[screener] {strategy}: ranked {len(rows)}, skipped {skipped} (insufficient data)")
        return rows

    def run(self, asof: Optional[date] = None, strategies: Optional[list[str]] = None,
            write: bool = True) -> tuple[dict, dict]:
        asof = asof or date.today()
        strategies = strategies or DEFAULT_STRATEGIES
        catalyst_table = catalyst_detector.load_table()

        watchlist: dict[str, list[str]] = {}
        breakdown: dict[str, list[dict]] = {}
        for strat in strategies:
            symbols = universe_for_strategy(strat)
            scored = self._rank(strat, symbols, asof, catalyst_table)
            top = scored[: self.top_n]
            watchlist[strat] = [r["symbol"] for r in top]
            breakdown[strat] = [
                {
                    "symbol":        r["symbol"],
                    "score":         r["score"],
                    "momentum_rank": r.get("momentum_rank", 0.0),
                    "catalyst":      r["catalyst"],
                    "reasons":       r["catalyst_reasons"],
                    **r["metrics"],
                }
                for r in top
            ]

        if write:
            self._write(watchlist, breakdown, asof)
        return watchlist, breakdown

    def _write(self, watchlist: dict, breakdown: dict, asof: date) -> None:
        meta = {
            "_meta": {
                "asof":         str(asof),
                "generated_at": datetime.now().isoformat(),
                "top_n":        self.top_n,
                "counts":       {k: len(v) for k, v in watchlist.items()},
            }
        }
        out_wl = {**meta, **watchlist}
        Path(DAILY_WATCHLIST_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(DAILY_WATCHLIST_PATH).write_text(json.dumps(out_wl, indent=2), encoding="utf-8")
        _BREAKDOWN_PATH.write_text(json.dumps({**meta, "strategies": breakdown}, indent=2), encoding="utf-8")
        logger.success(f"[screener] watchlist written → {DAILY_WATCHLIST_PATH}")
