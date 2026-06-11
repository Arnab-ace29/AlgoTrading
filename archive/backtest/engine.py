"""
Backtest Engine — event-driven, walk-forward.

Rewritten (June 2026) to fix BT-01..04:
  • BT-01  Each (symbol, fold) is simulated independently and its trades pooled.
           Nothing concatenates different instruments into one price series, so the
           equity curve / Sharpe are meaningful.
  • BT-02  Exits use the bar's HIGH/LOW to detect intrabar SL/target hits and fill
           AT the stop/target price — not at close. (SL assumed first if both hit.)
  • BT-03  The real PositionSizer sets qty + ATR-based SL/target, and the Indian
           transaction-cost model (analytics/costs.py) is applied to every trade.
  • BT-04  Per-fold metrics are computed and reported alongside the aggregate.

No look-ahead: features are computed on the full (train+test) window but signals are
only evaluated on the out-of-sample test window, and every signal reads only bars ≤ t.

This is a pure pandas/numpy simulator — no vectorbt dependency.

Usage:
    from backtest.engine import BacktestEngine
    res = BacktestEngine().run(["RELIANCE","TCS"], "2024-01-01", "2025-01-01")
    print(res.summary())
"""

from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import BACKTEST_RESULTS_DIR, SCORE_TIER_TRADE
from data.db import read_candles
from features.indicators import compute_all_features
from ensemble.aggregator import EnsembleAggregator
from ensemble.position_sizing import PositionSizer
from signals.base import Direction, Regime
from analytics.costs import round_trip_cost, is_cost_effective
from live.decision import passes_ml_gates
from signals.ml.macro_model import get_macro_model
from signals.ml.micro_model import get_micro_model
from signals.ml.strategy_outcomes import get_strategy_outcome_models
from models.rl_entry_agent import get_rl_entry_agent

# Regimes in which the live runner blocks new entries (EDGE-04).
_MOMENTUM_BLOCK_REGIMES: frozenset[Regime] = frozenset({Regime.CHOPPY})

INIT_CASH = 100_000.0
MIN_WARMUP = 60                       # bars of feature warm-up before trading
TRADING_DAYS = 252
_BARS_PER_DAY = {"1min": 375, "5min": 78, "15min": 26, "1day": 1}


@dataclass
class Trade:
    symbol:      str
    fold:        int
    side:        str
    qty:         int
    entry_time:  object
    exit_time:   object
    entry_price: float
    exit_price:  float
    gross_pnl:   float
    cost:        float
    net_pnl:     float
    return_pct:  float      # net return on notional (entry_price × qty)
    bars_held:   int
    exit_reason: str
    entry_score: float


def _metrics(trades: list[Trade], init_cash: float = INIT_CASH) -> dict:
    """Aggregate performance metrics from a list of trades (net of costs)."""
    n = len(trades)
    if n == 0:
        return {"total_trades": 0, "win_rate": 0.0, "total_return": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "avg_trade_pct": 0.0, "profit_factor": 0.0,
                "expectancy": 0.0, "gross_pnl": 0.0, "net_pnl": 0.0, "costs": 0.0}

    nets = np.array([t.net_pnl for t in trades], dtype=float)
    wins = nets[nets > 0]
    losses = nets[nets < 0]
    gross = float(sum(t.gross_pnl for t in trades))
    costs = float(sum(t.cost for t in trades))

    # Daily equity curve: attribute each trade's net PnL to its exit day.
    by_day: dict = defaultdict(float)
    for t in trades:
        d = pd.Timestamp(t.exit_time).date()
        by_day[d] += t.net_pnl
    eq = init_cash
    peak = init_cash
    max_dd = 0.0
    daily_rets: list[float] = []
    for d in sorted(by_day):
        prev = eq
        eq += by_day[d]
        daily_rets.append((eq - prev) / prev if prev > 0 else 0.0)
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)

    total_return = (eq - init_cash) / init_cash * 100.0
    dr = np.array(daily_rets, dtype=float)
    sharpe = float(np.sqrt(TRADING_DAYS) * dr.mean() / dr.std()) if dr.size > 1 and dr.std() > 0 else 0.0
    pf = float(wins.sum() / abs(losses.sum())) if losses.size and losses.sum() != 0 else (float("inf") if wins.size else 0.0)

    return {
        "total_trades":  n,
        "wins":          int((nets > 0).sum()),
        "losses":        int((nets < 0).sum()),
        "win_rate":      round(100.0 * (nets > 0).sum() / n, 2),
        "total_return":  round(total_return, 2),
        "sharpe":        round(sharpe, 3),
        "max_drawdown":  round(max_dd * 100.0, 2),
        "avg_trade_pct": round(float(np.mean([t.return_pct for t in trades])) * 100.0, 3),
        "profit_factor": round(pf, 3) if math.isfinite(pf) else None,
        "expectancy":    round(float(nets.mean()), 2),
        "gross_pnl":     round(gross, 2),
        "net_pnl":       round(float(nets.sum()), 2),
        "costs":         round(costs, 2),
    }


class BacktestResult:
    """Holds and formats results from a backtest run (no vectorbt)."""

    def __init__(self, run_id: str, trades: list[Trade], fold_metrics: list[dict], params: dict):
        self.run_id       = run_id
        self.trades       = trades
        self.fold_metrics = fold_metrics
        self.params       = params
        self.result_path  = ""

    def summary(self) -> dict:
        agg = _metrics(self.trades)
        agg.update({
            "run_id":      self.run_id,
            "params":      self.params,
            "per_fold":    self.fold_metrics,
            "result_path": self.result_path,
        })
        return agg

    def save(self) -> str:
        BACKTEST_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        base = BACKTEST_RESULTS_DIR / self.run_id
        if self.trades:
            pd.DataFrame([asdict(t) for t in self.trades]).to_csv(f"{base}_trades.csv", index=False)
        path = f"{base}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.summary(), f, indent=2, default=str)
        self.result_path = path
        logger.info(f"Backtest result saved: {path}")
        return path


class BacktestEngine:
    """Event-driven backtesting engine with walk-forward validation."""

    def __init__(self, aggregator: Optional[EnsembleAggregator] = None, loader=None,
                 use_ml_gates: bool = True):
        self.aggregator = aggregator or EnsembleAggregator()
        self.sizer = PositionSizer()
        # loader(symbol, timeframe, from_dt, to_dt) -> raw candle DataFrame | None.
        # Defaults to the SQLite reader; injectable for tests.
        self._loader = loader
        # Auto-disable ML gates when a custom aggregator/loader is injected (unit-test mode).
        self.use_ml_gates = use_ml_gates and aggregator is None and loader is None
        if self.use_ml_gates:
            self._macro   = get_macro_model()
            self._micro   = get_micro_model()
            self._outcome = get_strategy_outcome_models()
            self._rl_entry = get_rl_entry_agent()
        else:
            self._macro = self._micro = self._outcome = self._rl_entry = None

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(
        self,
        symbols:    list[str],
        from_date:  str,
        to_date:    str,
        timeframe:  str = "5min",
        walk_forward: bool = True,
        n_folds:    int = 5,
        train_days: int = 120,
        test_days:  int = 30,
        auto_window: bool = True,
    ) -> BacktestResult:
        run_id = str(uuid.uuid4())[:8]
        logger.info(f"Backtest [{run_id}]: {symbols} | {from_date} → {to_date} | wf={walk_forward}")
        from_dt = datetime.strptime(from_date, "%Y-%m-%d")
        to_dt   = datetime.strptime(to_date,   "%Y-%m-%d")
        max_hold = _BARS_PER_DAY.get(timeframe, 78)

        # BT-07: if the requested train/test windows don't fit the available span,
        # auto-shrink them so walk-forward still runs on short histories (e.g. the
        # ~60 days of 5-min data reachable today) instead of silently yielding 0
        # folds. Reserve ~60% of the span for the initial train, split the rest into
        # n_folds test windows. (≥150 days of real history removes the need for this.)
        if walk_forward and auto_window:
            span = (to_dt - from_dt).days
            if span > 0 and (train_days + test_days) > span:
                test_days  = max(5, int(span * 0.4 / max(1, n_folds)))
                train_days = max(10, int(span * 0.6))
                logger.info(f"  auto-window: span {span}d too short for requested folds → "
                            f"train={train_days}d test={test_days}d ×{n_folds}")

        all_trades: list[Trade] = []
        fold_metrics: list[dict] = []

        if walk_forward:
            cursor = from_dt
            for fold in range(n_folds):
                test_start = cursor + timedelta(days=train_days)
                test_end   = test_start + timedelta(days=test_days)
                if test_end > to_dt:
                    break
                logger.info(f"  Fold {fold+1}: train [{cursor.date()}→{test_start.date()}] "
                            f"test [{test_start.date()}→{test_end.date()}]")
                fold_trades: list[Trade] = []
                for symbol in symbols:
                    df = self._load_features(symbol, timeframe, cursor, test_end)
                    if df is None:
                        continue
                    fold_trades += self._simulate(df, symbol, fold, sim_start_time=test_start, max_hold=max_hold)
                if fold_trades:
                    fm = _metrics(fold_trades)
                    fm["fold"] = fold + 1
                    fold_metrics.append(fm)
                all_trades += fold_trades
                cursor += timedelta(days=test_days)
        else:
            for symbol in symbols:
                df = self._load_features(symbol, timeframe, from_dt, to_dt)
                if df is None:
                    continue
                all_trades += self._simulate(df, symbol, 0, sim_start_time=None, max_hold=max_hold)
            if all_trades:
                fm = _metrics(all_trades); fm["fold"] = 1
                fold_metrics.append(fm)

        params = {"symbols": symbols, "from": from_date, "to": to_date, "timeframe": timeframe,
                  "walk_forward": walk_forward, "n_folds": n_folds,
                  "train_days": train_days, "test_days": test_days}
        if not all_trades:
            logger.warning(f"Backtest [{run_id}]: no trades generated")
        return BacktestResult(run_id, all_trades, fold_metrics, params)

    # ── Data loading ────────────────────────────────────────────────────────────

    def _load_features(self, symbol: str, timeframe: str, from_dt: datetime,
                       to_dt: datetime) -> Optional[pd.DataFrame]:
        if self._loader is not None:
            df = self._loader(symbol, timeframe, from_dt, to_dt)
        else:
            df = read_candles(symbol, timeframe, from_dt=from_dt, to_dt=to_dt)
        if df is None or df.empty or len(df) < MIN_WARMUP + 5:
            logger.debug(f"  {symbol}: insufficient data ({0 if df is None else len(df)} bars)")
            return None
        df = df.set_index("timestamp")
        # Normalise the index to tz-naive so test-window slicing is unambiguous.
        idx = pd.to_datetime(df.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        df.index = idx
        return compute_all_features(df)

    # ── Per-(symbol, fold) simulation ────────────────────────────────────────────

    def _simulate(self, df: pd.DataFrame, symbol: str, fold: int,
                  sim_start_time: Optional[datetime], max_hold: int) -> list[Trade]:
        """
        Walk the bars and simulate LONG *and* SHORT trades with intrabar SL/target
        fills. The runner trades both directions, so the backtest must too — a
        long-only sim leaves half the strategy unvalidated.

        Realism:
          • Entry fills at the NEXT bar's OPEN (not the signal bar's close): you only
            know a bar's close once it has closed, so you can't trade on it. This
            removes the same-bar look-ahead in the old engine.
          • A cost-aware filter skips setups whose target move can't clear round-trip
            costs (mirrors the live runner).
          • Intrabar SL/target uses the bar's high/low and fills AT the stop/target
            price; SL is assumed first if both are touched in one bar (conservative).

        Trades are only OPENED on bars at/after sim_start_time (the out-of-sample
        window); a position opened late may close after test_end, which is fine.
        """
        n = len(df)
        if sim_start_time is not None:
            start_pos = int(df.index.searchsorted(pd.Timestamp(sim_start_time)))
        else:
            start_pos = MIN_WARMUP
        start_pos = max(start_pos, MIN_WARMUP)
        if start_pos >= n - 1:
            return []

        opens  = df["open"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        highs  = df["high"].to_numpy(dtype=float)
        lows   = df["low"].to_numpy(dtype=float)
        index  = df.index

        # BT-06: per-day EOD square-off. The live runner is strictly intraday (15:25
        # square-off), so the backtest must not carry a position overnight. Mark the
        # last bar of each IST session; force-close any open position there and never
        # fill an intraday entry across the session boundary. Only enabled for genuine
        # intraday data (multiple bars per day) — for daily bars it's degenerate and a
        # position would close one bar after entry, so we leave those to max_hold.
        from features.indicators import _ist_index
        ist = _ist_index(index)
        session_end = np.zeros(n, dtype=bool)
        intraday = False
        if isinstance(ist, pd.DatetimeIndex):
            day_keys = ist.normalize().asi8
            intraday = len(np.unique(day_keys)) < n      # at least one day has >1 bar
            if intraday:
                session_end[:-1] = day_keys[1:] != day_keys[:-1]
                session_end[-1] = True

        trades: list[Trade] = []
        in_pos = False
        direction = Direction.LONG
        entry_pos = entry_price = qty = sl = tgt = atr = entry_score = 0.0
        pending: Optional[dict] = None     # signal fired; fill at the NEXT bar's open

        for pos in range(start_pos, n):
            if in_pos:
                is_long = direction == Direction.LONG
                exit_price = None
                reason = None
                # 1) Intrabar SL/target on this bar's range (BT-02). SL first if both.
                if is_long:
                    if lows[pos] <= sl:
                        exit_price, reason = sl, "SL_HIT"
                    elif highs[pos] >= tgt:
                        exit_price, reason = tgt, "TARGET_HIT"
                else:  # SHORT: stop is above, target is below
                    if highs[pos] >= sl:
                        exit_price, reason = sl, "SL_HIT"
                    elif lows[pos] <= tgt:
                        exit_price, reason = tgt, "TARGET_HIT"

                if exit_price is None:
                    close = closes[pos]
                    # Intraday EOD square-off (BT-06) takes priority — never hold overnight.
                    if intraday and session_end[pos]:
                        exit_price, reason = close, "EOD"
                    else:
                        sl = self.sizer.compute_trailing_sl(direction, entry_price, close, sl, atr)
                        result = self.aggregator.compute(df.iloc[: pos + 1], symbol)
                        opposite = Direction.SHORT if is_long else Direction.LONG
                        if (result.actionable
                                and abs(result.composite_score) >= SCORE_TIER_TRADE
                                and result.regime not in _MOMENTUM_BLOCK_REGIMES
                                and result.direction == opposite):
                            exit_price, reason = close, "REVERSAL"
                        elif (pos - entry_pos) >= max_hold:
                            exit_price, reason = close, "EOD"

                if exit_price is not None:
                    trades.append(self._close_trade(symbol, fold, entry_pos, pos, index,
                                                     entry_price, exit_price, int(qty),
                                                     reason, entry_score, direction))
                    in_pos = False

            elif pending is not None:
                # Fill the pending entry at THIS bar's open (next-bar-open fill).
                d = pending["direction"]
                score = pending["score"]
                regime = pending["regime"]
                pending = None
                price = opens[pos]
                a = self._safe_atr(df, pos)
                # Don't open an intraday position that can't be held within the
                # session (BT-06): skip if the signal fired on the prior session's
                # last bar (overnight-gap fill) OR if this fill bar is itself a
                # session-end bar (the next bar is already a new session, so the
                # first exit-check would land on an overnight gap).
                crossed_session = intraday and (
                    (pos > 0 and session_end[pos - 1]) or session_end[pos])
                sizing = None if crossed_session else self.sizer.size(symbol, d, score, price, a, [], regime=regime)
                if sizing and sizing.qty > 0 and is_cost_effective(price, sizing.target_price, sizing.qty):
                    in_pos = True
                    direction = d
                    entry_pos = pos
                    entry_price = price
                    qty = sizing.qty
                    sl = sizing.sl_price
                    tgt = sizing.target_price
                    atr = a
                    entry_score = score
                # else: not sized / cost-trap → skip and look for the next signal

            else:
                result = self.aggregator.compute(df.iloc[: pos + 1], symbol)
                if (result.actionable
                        and abs(result.composite_score) >= SCORE_TIER_TRADE
                        and result.regime not in _MOMENTUM_BLOCK_REGIMES
                        and result.direction in (Direction.LONG, Direction.SHORT)):
                    # Apply ML gates (macro + micro + outcome + RL entry) — mirrors live runner.
                    if self.use_ml_gates:
                        _passed, _reason, _ = passes_ml_gates(
                            symbol=symbol, df=df.iloc[:pos + 1], result=result,
                            prev_score=0.0,
                            macro_model=self._macro, micro_model=self._micro,
                            outcome_models=self._outcome, rl_entry=self._rl_entry,
                            strategy_tag="vwap_rsi_ensemble",
                            session_pnl=0.0, daily_loss_limit=5_000.0, open_count=0,
                        )
                        if not _passed:
                            continue
                    # Don't arm a signal on the very last bar (no next bar to fill).
                    if pos < n - 1:
                        pending = {"direction": result.direction,
                                   "score": result.composite_score,
                                   "regime": result.regime}

        # Force-close any still-open position at the last available close.
        if in_pos:
            trades.append(self._close_trade(symbol, fold, int(entry_pos), n - 1, index,
                                            entry_price, closes[n - 1], int(qty),
                                            "EOD_FORCED", entry_score, direction))
        return trades

    def _close_trade(self, symbol, fold, entry_pos, exit_pos, index,
                     entry_price, exit_price, qty, reason, entry_score,
                     direction: Direction = Direction.LONG) -> Trade:
        side = "BUY" if direction == Direction.LONG else "SELL"
        if direction == Direction.LONG:
            gross = (exit_price - entry_price) * qty
        else:                                  # SHORT: profit when exit < entry
            gross = (entry_price - exit_price) * qty
        cost = round_trip_cost(entry_price, exit_price, qty)
        net = gross - cost
        notional = entry_price * qty
        return Trade(
            symbol=symbol, fold=fold, side=side, qty=qty,
            entry_time=index[entry_pos], exit_time=index[exit_pos],
            entry_price=round(float(entry_price), 2), exit_price=round(float(exit_price), 2),
            gross_pnl=round(float(gross), 2), cost=round(float(cost), 2), net_pnl=round(float(net), 2),
            return_pct=round(float(net / notional), 5) if notional > 0 else 0.0,
            bars_held=int(exit_pos - entry_pos), exit_reason=reason,
            entry_score=round(float(entry_score), 4),
        )

    @staticmethod
    def _safe_atr(df: pd.DataFrame, pos: int) -> float:
        try:
            v = float(df["atr_14"].iloc[pos])
            if math.isfinite(v) and v > 0:
                return v
        except Exception:
            pass
        # fallback: stdev of recent closes (never zero/NaN)
        recent = df["close"].iloc[max(0, pos - 20): pos + 1]
        s = float(recent.std()) if len(recent) > 1 else 0.0
        return s if s > 0 else max(1e-6, float(df["close"].iloc[pos]) * 0.01)
