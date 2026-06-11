"""
Action Replay engine — full-fidelity single-day live simulation.

Unlike backtest/engine.py (which validates each symbol in isolation over months,
walk-forward), this replays ONE historical trading day exactly as the live runner
would have lived it:

  1. Pre-market (T-1 close): the daily screener ranks the universe with NO
     look-ahead and produces the day's watchlist + per-symbol "why chosen".
  2. The day's 5-min bars for every watchlist symbol are stepped through on a
     single shared clock (09:15 -> 15:30), not per-symbol in isolation.
  3. At each bar the SAME components the live runner uses are applied:
        EnsembleAggregator  -> score / direction / regime
        live.decision        -> Phase 2 ML gates (macro/micro/outcome/RL)
        CircuitBreaker       -> daily-loss / max-trades / concurrency / blackout
        CorrelationGuard     -> sector cap
        PositionSizer        -> qty + ATR stop/target + heat + Kelly
        analytics.costs      -> Indian round-trip costs
     A real portfolio is maintained (concurrent positions, running session PnL,
     daily-loss halt, EOD square-off).
  4. Every decision is emitted as a timestamped event, so the dashboard can
     replay the day on a clock (▶/⏸/speed) with a timeline of milestones.

Fill model (mirrors backtest realism): a signal is evaluated through all gates on
the bar that CLOSES it; if it passes, the entry fills at the NEXT bar's OPEN.
Intrabar SL/target use the bar's high/low and fill AT the stop/target (SL first if
both are touched). Strictly intraday — any position still open at the last session
bar is squared off at its close.

This module reuses live.decision so the gating logic is guaranteed identical to
live/runner.py (single source of truth).
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import ROOT_DIR, TRADING_CAPITAL, TIMEFRAME_PRIMARY, USE_MARGIN, MAX_MIS_LEVERAGE
from config.risk_profiles import get_profile, ACTIVE
from data.db import read_candles
from features.indicators import compute_all_features, _ist_index
from ensemble.aggregator import EnsembleAggregator
from ensemble.position_sizing import PositionSizer
from risk.circuit_breaker import CircuitBreaker
from risk.correlation_guard import CorrelationGuard
from analytics.costs import cost_breakdown, is_cost_effective
from signals.base import Direction, Regime
from screener.daily_screener import DailyScreener
from live import decision

# Strategy tag — must match live/runner.STRATEGY_TAG so the outcome-model gate
# reads the same per-strategy model.
STRATEGY_TAG = "vwap_rsi_ensemble"

MIN_WARMUP = 60                         # feature warm-up bars before trading
RESULTS_DIR = ROOT_DIR / "replay" / "results"

# Regimes in which momentum entries are blocked (mirrors backtest/runner EDGE-04).
_BLOCK_REGIMES = {Regime.CHOPPY}


@dataclass
class ReplayTrade:
    symbol:       str
    side:         str            # BUY / SELL (order side)
    direction:    str            # LONG / SHORT (position direction)
    qty:          int
    entry_time:   str
    exit_time:    str
    entry_price:  float
    exit_price:   float
    notional:     float          # entry_price × qty (capital deployed)
    leverage:     float          # notional / account capital
    gross_pnl:    float
    cost:         float
    net_pnl:      float
    return_pct:   float
    bars_held:    int
    exit_reason:  str
    entry_score:  float
    regime:       str
    sizing_note:  str
    cost_parts:   dict = field(default_factory=dict)
    signal_scores: dict = field(default_factory=dict)
    margin_multiplier: float = 1.0   # MIS leverage from broker (1.0 = no data)
    margin_required:   float = 0.0   # ₹ margin blocked = notional / multiplier


def _ev(t: str, kind: str, symbol: str = "", **detail) -> dict:
    """Build a timeline event."""
    return {"t": t, "type": kind, "symbol": symbol, "detail": detail}


class ReplayEngine:
    """Full-fidelity single-day replay. Instantiate per run."""

    def __init__(
        self,
        capital: float = TRADING_CAPITAL,
        risk_profile: Optional[str] = None,
        use_ml_gates: bool = True,
        timeframe: str = TIMEFRAME_PRIMARY,
        loader: Optional[Callable] = None,
        auto_fetch: bool = True,
        use_margin: bool = USE_MARGIN,
    ):
        self.capital = float(capital)
        self.risk = get_profile(risk_profile) if risk_profile else ACTIVE
        self.use_ml_gates = use_ml_gates
        self.timeframe = timeframe
        self._loader = loader               # loader(symbol, tf, from_dt, to_dt) -> df | None
        # When the local DB lacks bars for the requested day, pull them on demand
        # from the SAME source the live feed uses — Upstox (NEVER yfinance, so the
        # replay always mirrors live data). Disabled if a custom loader is given.
        self.auto_fetch = auto_fetch and loader is None
        self._hist_api = None               # lazy Upstox HistoryV3Api (built once)
        self._hist_api_failed = False       # don't retry if token missing/invalid
        self._fetched: set[str] = set()     # symbols already backfilled this run

        self.aggregator = EnsembleAggregator()
        self.sizer = PositionSizer(capital=self.capital, profile=self.risk)
        self.breaker = CircuitBreaker(capital=self.capital, profile=self.risk)
        self.corr_guard = CorrelationGuard()

        # ML gate singletons (use whatever is in models/saved; gates stay open if
        # untrained — exactly like live).
        if use_ml_gates:
            from signals.ml.macro_model import get_macro_model
            from signals.ml.micro_model import get_micro_model
            from signals.ml.strategy_outcomes import get_outcome_models
            from models.rl_entry_agent import get_rl_entry_agent
            self.macro_model = get_macro_model()
            self.micro_model = get_micro_model()
            self.outcome_models = get_outcome_models()
            self.rl_entry = get_rl_entry_agent()
        else:
            self.macro_model = self.micro_model = self.outcome_models = self.rl_entry = None

        self.use_margin = use_margin
        self._daily_loss_limit = self.capital * self.risk.max_daily_loss_pct / 100.0
        self._bars_per_day = {"1min": 375, "5min": 78, "15min": 26}.get(timeframe, 78)
        # Thread-safety: serialise SQLite writes when prefetch/load run in parallel.
        self._write_lock = threading.Lock()
        # Margin multipliers from cache (data/margin_multipliers.json); empty if not yet fetched.
        try:
            from data.margin import load_margin_multipliers
            self._margin: dict = load_margin_multipliers()
        except Exception:
            self._margin = {}
        if use_margin and not self._margin:
            logger.warning("use_margin=True but margin cache is empty. "
                           "Run: python scripts/fetch_margin_multipliers.py (needs live token). "
                           "Falling back to cash sizing.")

    # ── Public entry point ──────────────────────────────────────────────────────

    def run(self, date_str: str, progress: Optional[Callable[[float, str], None]] = None) -> dict:
        """Replay a single day. date_str = 'YYYY-MM-DD' (IST session date)."""
        run_id = str(uuid.uuid4())[:8]
        asof = date.fromisoformat(date_str)
        events: list[dict] = []
        margin_note = f" | margin={MAX_MIS_LEVERAGE:.0f}x-cap" if self.use_margin else " | margin=OFF"
        logger.info(f"Action Replay [{run_id}]: {asof} | capital=₹{self.capital:,.0f} "
                    f"| risk={self.risk.name if hasattr(self.risk,'name') else '?'} | ml={self.use_ml_gates}"
                    f"{margin_note}")

        def _p(frac: float, msg: str) -> None:
            if progress:
                try:
                    progress(frac, msg)
                except Exception:
                    pass

        # 0) If the DB is missing this day, pull it from Upstox first (live source).
        if self.auto_fetch:
            try:
                self._prefetch(asof, _p)
            except Exception as e:
                logger.warning(f"Action Replay prefetch skipped: {e}")

        # 1) Pre-market universe selection (no look-ahead, no file write).
        _p(0.02, "Running pre-market screener…")
        screener = DailyScreener()
        try:
            watchlist, breakdown = screener.run(asof=asof, write=False)
        except Exception as e:
            logger.error(f"screener failed: {e}")
            watchlist, breakdown = {}, {}
        symbols = sorted({s for k, lst in watchlist.items()
                          if isinstance(lst, list) for s in lst})
        events.append(_ev(self._t0(asof, "09:00"), "UNIVERSE_SET",
                          detail_strategies=watchlist, n=len(symbols)))
        # flatten breakdown -> {symbol: {...}}
        why: dict[str, dict] = {}
        for strat, rows in (breakdown or {}).items():
            for r in rows:
                why.setdefault(r["symbol"], {"strategies": [], "score": r.get("score"),
                                             "reasons": r.get("reasons", [])})
                why[r["symbol"]]["strategies"].append(strat)

        if not symbols:
            logger.warning(f"Action Replay [{run_id}]: empty universe for {asof}")
            note = ("Screener selected no symbols — not enough history in the DB to rank the "
                    "universe for this date.")
            if self._hist_api_failed:
                note += " Upstox auto-fetch is unavailable (missing/expired token); run scripts/refresh_token.py."
            events.append(_ev(self._t0(asof, "09:00"), "NO_DATA", detail_note=note))
            return self._finish(run_id, asof, [], events, watchlist, why, symbols)

        # 2) Load each symbol's day bars (+ warm-up tail) with features.
        _p(0.08, f"Loading candles for {len(symbols)} symbols…")
        data = self._load_day(symbols, asof, progress=_p)
        if not data:
            logger.warning(f"Action Replay [{run_id}]: no candle data for {asof}")
            note = ("No 5-min candles found for any universe symbol on this date. "
                    "It may be a market holiday/weekend, or outside Upstox's historical range.")
            if self._hist_api_failed:
                note = ("No candles in the DB and Upstox auto-fetch is unavailable "
                        "(missing/expired token). Run scripts/refresh_token.py, then retry.")
            events.append(_ev(self._t0(asof, "09:15"), "NO_DATA", detail_note=note))
            return self._finish(run_id, asof, [], events, watchlist, why, symbols)

        traded_symbols = sorted(data.keys())
        # Master ordered timeline of session-bar timestamps (union across symbols).
        all_ts = sorted({ts for d in data.values() for ts in d["day_ts"]})
        if not all_ts:
            return self._finish(run_id, asof, [], events, watchlist, why, traded_symbols)
        last_ts = all_ts[-1]
        events.append(_ev(self._iso(all_ts[0]), "SESSION_OPEN",
                          symbols_with_data=traded_symbols, bars=len(all_ts)))

        # 3) Portfolio state.
        trades: list[ReplayTrade] = []
        open_pos: dict[str, dict] = {}      # symbol -> position
        pending: dict[str, dict] = {}       # symbol -> armed entry (fill next bar open)
        session_pnl = 0.0
        last_score: dict[str, float] = {}
        halted = False
        # per-symbol status tracking for the universe table
        status: dict[str, str] = {s: "SCANNING" for s in traded_symbols}
        gate_counts: dict[str, int] = defaultdict(int)   # aggregate "why no trade"

        n_ts = len(all_ts)
        _agg_cache: dict = {}   # (sym, ts) -> AggregatorResult; cleared each bar
        for i, ts in enumerate(all_ts):
            if i % 5 == 0:
                _p(0.10 + 0.85 * i / max(1, n_ts), f"Replaying {self._iso(ts)} ({i+1}/{n_ts})…")
            is_last = ts == last_ts
            ts_ist = self._to_ist(ts)

            # A) Manage open positions (exits) on this just-closed bar.
            for sym in list(open_pos.keys()):
                d = data.get(sym)
                if d is None or ts not in d["pos_of"]:
                    continue
                pos = open_pos[sym]
                p = d["pos_of"][ts]
                hi, lo, cl = d["high"][p], d["low"][p], d["close"][p]
                is_long = pos["direction"] == Direction.LONG
                exit_price = None
                reason = None
                # Intrabar SL/target (SL first if both touched).
                if is_long:
                    if lo <= pos["sl"]:
                        exit_price, reason = pos["sl"], "SL_HIT"
                    elif hi >= pos["tgt"]:
                        exit_price, reason = pos["tgt"], "TARGET_HIT"
                else:
                    if hi >= pos["sl"]:
                        exit_price, reason = pos["sl"], "SL_HIT"
                    elif lo <= pos["tgt"]:
                        exit_price, reason = pos["tgt"], "TARGET_HIT"

                if exit_price is None:
                    if is_last:
                        exit_price, reason = cl, "EOD_SQUAREOFF"
                    else:
                        # Trailing SL update on close.
                        new_sl = self.sizer.compute_trailing_sl(
                            pos["direction"], pos["entry_price"], cl, pos["sl"], pos["atr"])
                        if new_sl != pos["sl"]:
                            pos["sl"] = new_sl
                            events.append(_ev(self._iso(ts), "TRAIL_SL", sym,
                                              sl=round(new_sl, 2), ltp=round(float(cl), 2)))
                        # Reversal exit: reuse cached result if already computed this bar.
                        cache_key = (sym, ts)
                        if cache_key not in _agg_cache:
                            _agg_cache[cache_key] = self.aggregator.compute(d["df"].iloc[: p + 1], sym)
                        res = _agg_cache[cache_key]
                        opp = Direction.SHORT if is_long else Direction.LONG
                        if res.actionable and res.direction == opp:
                            exit_price, reason = cl, "REVERSAL"

                if exit_price is not None:
                    tr = self._close(sym, pos, ts, exit_price, reason)
                    trades.append(tr)
                    session_pnl += tr.net_pnl
                    open_pos.pop(sym, None)
                    status[sym] = "TRADED"
                    events.append(_ev(self._iso(ts), "EXIT", sym,
                                      side=pos["side"], qty=pos["qty"],
                                      entry_price=tr.entry_price, exit_price=tr.exit_price,
                                      reason=reason, gross=tr.gross_pnl, cost=tr.cost,
                                      net=tr.net_pnl, session_pnl=round(session_pnl, 2)))

            # B) Fill pending entries armed on the previous bar — at THIS bar's open.
            for sym in list(pending.keys()):
                d = data.get(sym)
                if d is None or ts not in d["pos_of"]:
                    continue
                arm = pending.pop(sym)
                p = d["pos_of"][ts]
                # Don't open across a session boundary or on the last bar.
                if is_last:
                    continue
                price = float(d["open"][p])
                atr = self._safe_atr(d["df"], p)
                _sym_mult = 1.0
                if self.use_margin and self._margin:
                    raw = float(self._margin.get(sym, {}).get("multiplier", 1.0))
                    _sym_mult = min(raw, MAX_MIS_LEVERAGE)
                sizing = self.sizer.size(
                    symbol=sym, direction=arm["direction"], score=arm["score"],
                    entry_price=price, atr=atr,
                    open_positions_risk=[pp["risk_amount"] for pp in open_pos.values()],
                    regime=arm["regime"],
                    margin_multiplier=_sym_mult,
                )
                if not sizing or sizing.qty <= 0:
                    status[sym] = "ARMED"
                    gate_counts["sizing/heat"] += 1
                    events.append(_ev(self._iso(ts), "ENTRY_SKIPPED", sym,
                                      reason="sizing/heat -> qty 0"))
                    continue
                if not is_cost_effective(price, sizing.target_price, sizing.qty):
                    status[sym] = "ARMED"
                    gate_counts["cost_filter"] += 1
                    events.append(_ev(self._iso(ts), "ENTRY_SKIPPED", sym,
                                      reason="cost filter (target can't clear costs)"))
                    continue
                risk_amount = abs(price - sizing.sl_price) * sizing.qty
                _mis = self._margin.get(sym, {}) if self.use_margin else {}
                _multiplier = float(_mis.get("multiplier", 1.0))
                _margin_pct  = float(_mis.get("margin_pct",  100.0))
                _notional    = round(price * int(sizing.qty), 2)
                _margin_req  = round(_notional / _multiplier, 2) if self.use_margin else _notional
                open_pos[sym] = {
                    "symbol": sym, "side": arm["side"], "direction": arm["direction"],
                    "qty": int(sizing.qty), "entry_price": price,
                    "sl": sizing.sl_price, "tgt": sizing.target_price, "atr": atr,
                    "risk_amount": risk_amount, "entry_time": self._iso(ts),
                    "entry_pos": p, "entry_score": arm["score"],
                    "regime": arm["regime"].value, "sizing_note": sizing.sizing_note,
                    "signal_scores": arm["signal_scores"],
                    "margin_multiplier": _multiplier,
                    "margin_required":   _margin_req,
                }
                self.breaker.record_entry()
                status[sym] = "IN_POSITION"
                _dir = "LONG" if arm["direction"] == Direction.LONG else "SHORT"
                events.append(_ev(self._iso(ts), "ENTRY", sym,
                                  side=arm["side"], direction=_dir, qty=int(sizing.qty),
                                  price=round(price, 2), notional=_notional,
                                  leverage=round(_notional / self.capital, 2) if self.capital > 0 else 0.0,
                                  sl=sizing.sl_price,
                                  tgt=sizing.target_price, score=round(arm["score"], 4),
                                  regime=arm["regime"].value, sizing_note=sizing.sizing_note,
                                  reason_chain=arm["reason_chain"],
                                  signal_scores={k: round(v, 4) for k, v in arm["signal_scores"].items()},
                                  margin_multiplier=round(_multiplier, 2),
                                  margin_required=_margin_req,
                                  margin_pct=round(_margin_pct, 1)))

            # C) Scan flat symbols for new signals -> arm for next bar.
            if not halted:
                for sym in traded_symbols:
                    if sym in open_pos or sym in pending:
                        continue
                    d = data[sym]
                    if ts not in d["pos_of"]:
                        continue
                    p = d["pos_of"][ts]
                    if p >= d["n"] - 1 or is_last:
                        continue   # no next bar to fill on
                    cache_key = (sym, ts)
                    if cache_key not in _agg_cache:
                        _agg_cache[cache_key] = self.aggregator.compute(d["df"].iloc[: p + 1], sym)
                    res = _agg_cache[cache_key]
                    prev = last_score.get(sym, res.composite_score)
                    last_score[sym] = res.composite_score
                    d["last_result"] = res
                    if not res.actionable:
                        continue
                    if status[sym] == "SCANNING":
                        status[sym] = "SIGNAL"

                    # Regime block (EDGE-04).
                    if res.regime in _BLOCK_REGIMES:
                        gate_counts["regime_choppy"] += 1
                        status[sym] = "GATED"
                        continue

                    # ML gates (identical code path as live via live.decision).
                    if self.use_ml_gates:
                        passed, greason, _mp = decision.passes_ml_gates(
                            symbol=sym, df=d["df"].iloc[: p + 1], result=res,
                            prev_score=prev, macro_model=self.macro_model,
                            micro_model=self.micro_model, outcome_models=self.outcome_models,
                            rl_entry=self.rl_entry, strategy_tag=STRATEGY_TAG,
                            session_pnl=session_pnl, daily_loss_limit=self._daily_loss_limit,
                            open_count=len(open_pos), recent_win_rate=0.5)
                        if not passed:
                            gate_counts[f"ml:{greason.split('(')[0].split('=')[0].strip()}"] += 1
                            status[sym] = "GATED"
                            events.append(_ev(self._iso(ts), "GATE_BLOCK", sym, reason=greason))
                            continue

                    # Circuit breaker (daily-loss / max-trades / concurrency / blackout).
                    allowed, breason = self.breaker.allow_entry(
                        sym, session_pnl, len(open_pos), now=ts_ist)
                    if not allowed:
                        gate_counts[f"breaker:{breason.split(':')[0].split('(')[0].strip()}"] += 1
                        status[sym] = "GATED"
                        events.append(_ev(self._iso(ts), "GATE_BLOCK", sym, reason=breason))
                        if breason.startswith("DAILY_LOSS") or breason.startswith("HALTED"):
                            if not halted:
                                halted = True
                                events.append(_ev(self._iso(ts), "BREAKER_HALT",
                                                  reason=breason, session_pnl=round(session_pnl, 2)))
                        continue

                    # Sector / correlation guard.
                    corr_ok, creason = self.corr_guard.allow(sym, list(open_pos.keys()))
                    if not corr_ok:
                        gate_counts["sector_corr"] += 1
                        status[sym] = "GATED"
                        events.append(_ev(self._iso(ts), "GATE_BLOCK", sym, reason=creason))
                        continue

                    # Passed all gates -> arm for next-bar-open fill.
                    side = "BUY" if res.direction == Direction.LONG else "SELL"
                    pending[sym] = {
                        "direction": res.direction, "side": side,
                        "score": res.composite_score, "regime": res.regime,
                        "signal_scores": dict(res.signal_scores),
                        "reason_chain": self._reason_chain(res),
                    }
                    status[sym] = "ARMED"
                    events.append(_ev(self._iso(ts), "ARMED", sym, side=side,
                                      score=round(res.composite_score, 4),
                                      regime=res.regime.value))

        _agg_cache.clear()   # free memory
        events.append(_ev(self._iso(last_ts), "SESSION_CLOSE",
                          session_pnl=round(session_pnl, 2), trades=len(trades)))
        _p(0.98, "Finalising…")
        return self._finish(run_id, asof, trades, events, watchlist, why, traded_symbols,
                            status=status, gate_counts=dict(gate_counts), last_score=last_score,
                            data=data)

    # ── Data loading ──────────────────────────────────────────────────────────

    def _read(self, sym: str, from_dt: datetime, to_dt: datetime):
        """Read candles via the injected loader (tests) or the DB. Never raises."""
        try:
            if self._loader is not None:
                return self._loader(sym, self.timeframe, from_dt, to_dt)
            return read_candles(sym, self.timeframe, from_dt=from_dt, to_dt=to_dt)
        except Exception as e:
            logger.debug(f"  {sym}: load failed {e}")
            return None

    @staticmethod
    def _has_day_bars(raw, asof: date) -> bool:
        """True if `raw` already contains usable bars on the asof IST date."""
        if raw is None or getattr(raw, "empty", True) or "timestamp" not in raw:
            return False
        try:
            ts = pd.to_datetime(raw["timestamp"], utc=True).dt.tz_convert("Asia/Kolkata")
            return bool((ts.dt.date == asof).any())
        except Exception:
            return False

    def _ensure_hist_api(self):
        """Lazily build the Upstox HistoryV3Api once. Returns None if unavailable."""
        if self._hist_api is not None or self._hist_api_failed:
            return self._hist_api
        try:
            import upstox_client
            from data.upstox_history import get_api_client
            self._hist_api = upstox_client.HistoryV3Api(get_api_client())
        except Exception as e:
            logger.warning(f"Action Replay: Upstox history unavailable ({e}). "
                           f"Replaying with whatever is in the DB. Run scripts/refresh_token.py "
                           f"and ensure a valid UPSTOX_ACCESS_TOKEN to auto-fetch missing days.")
            self._hist_api_failed = True
        return self._hist_api

    def _upstox_backfill(self, sym: str, from_dt: datetime, to_dt: datetime,
                         timeframe: Optional[str] = None) -> None:
        """
        Fetch [from_dt, to_dt] bars for one symbol from Upstox and store them.
        Strictly Upstox (the live feed's source) — never yfinance — so the replay
        always uses live-equivalent data. Best-effort: failures are logged, not raised.
        """
        from data.instruments import resolve_instrument_key
        from data.upstox_history import (
            UPSTOX_V3_TIMEFRAME_MAP, fetch_candles_for_range,
        )
        from data.db import write_candles

        tf = timeframe or self.timeframe
        key = resolve_instrument_key(sym)
        if not key or tf not in UPSTOX_V3_TIMEFRAME_MAP:
            return
        api = self._ensure_hist_api()
        if api is None:
            return
        unit, interval = UPSTOX_V3_TIMEFRAME_MAP[tf]
        # Upstox caps minute ranges at 30 days/request (day/week/month allow 365).
        chunk = 30 if unit == "minutes" else 365
        frm, to = from_dt.date(), to_dt.date()
        dfs = []
        cur = frm
        while cur <= to:
            nxt = min(cur + timedelta(days=chunk), to)
            df = fetch_candles_for_range(api, key, unit, interval, cur, nxt)
            if df is not None and not df.empty:
                dfs.append(df)
            cur = nxt + timedelta(days=1)
        if not dfs:
            logger.debug(f"  {sym} {tf}: Upstox returned no candles for {frm}..{to}")
            return
        combined = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=["timestamp"])
        combined["symbol"] = sym
        combined["timeframe"] = tf
        try:
            with self._write_lock:
                rows = write_candles(combined, source="replay_fetch")
            logger.info(f"  {sym} {tf}: fetched {rows} bars from Upstox for replay")
        except Exception as e:
            logger.warning(f"  {sym} {tf}: failed to store fetched candles ({e})")

    def _prefetch(self, asof: date, progress: Optional[Callable[[float, str], None]] = None) -> None:
        """
        Before screening, ensure the fetchable universe (screener symbols that have
        an Upstox instrument key) has data for `asof`. Pulls cheap daily bars for the
        screener's ranking lookback + intraday bars for the replay window — all from
        Upstox. No-op for symbols already present or without a key.
        """
        from screener.universe import DEFAULT_STRATEGIES, universe_for_strategy
        from config.settings import SCREENER_LOOKBACK_DAYS
        from data.instruments import resolve_instrument_key

        universe = sorted({s for strat in DEFAULT_STRATEGIES
                           for s in universe_for_strategy(strat)})
        # Only symbols Upstox can serve (curated map + full NSE master) are fetchable.
        cands = [s for s in universe if resolve_instrument_key(s)]
        if not cands:
            return
        intraday_from = datetime.combine(asof - timedelta(days=20), datetime.min.time())
        intraday_to   = datetime.combine(asof + timedelta(days=1), datetime.min.time())
        daily_from    = datetime.combine(asof - timedelta(days=SCREENER_LOOKBACK_DAYS + 90), datetime.min.time())
        missing = [s for s in cands
                   if not self._has_day_bars(self._read(s, intraday_from, intraday_to), asof)]
        if not missing:
            return
        logger.info(f"Action Replay: fetching {len(missing)}/{len(cands)} universe symbols "
                    f"from Upstox (missing for {asof})…")
        if progress:
            progress(0.01, f"Fetching {len(missing)} symbols from Upstox (parallel)…")

        _MAX_WORKERS = min(12, len(missing))

        def _fetch_sym(sym: str) -> str:
            if self._hist_api_failed:
                return sym
            self._upstox_backfill(sym, daily_from, intraday_to, timeframe="1day")
            self._upstox_backfill(sym, intraday_from, intraday_to, timeframe=self.timeframe)
            self._fetched.add(sym)
            return sym

        done = 0
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futs = {pool.submit(_fetch_sym, sym): sym for sym in missing}
            for fut in as_completed(futs):
                done += 1
                if progress:
                    progress(0.01 + 0.06 * done / max(1, len(missing)),
                             f"Fetched {done}/{len(missing)} symbols from Upstox…")
                try:
                    fut.result()
                except Exception as exc:
                    logger.warning(f"prefetch {futs[fut]}: {exc}")

    def _load_day(self, symbols: list[str], asof: date,
                  progress: Optional[Callable[[float, str], None]] = None) -> dict:
        """
        For each symbol load enough history to warm features, compute them, and
        record which rows fall on `asof` (IST). Returns {symbol: {...}} only for
        symbols that have day bars.

        If the local DB lacks bars for `asof` and auto_fetch is on, the missing
        window is pulled on demand from Upstox (the live feed's source) and stored,
        so a fresh DB can still replay any in-range trading day.
        """
        out: dict[str, dict] = {}
        from_dt = datetime.combine(asof - timedelta(days=20), datetime.min.time())
        to_dt   = datetime.combine(asof + timedelta(days=1),  datetime.min.time())

        def _load_one(sym: str):
            """Load, optionally backfill, and compute features for one symbol."""
            raw = self._read(sym, from_dt, to_dt)
            if (self.auto_fetch and sym not in self._fetched
                    and not self._has_day_bars(raw, asof)):
                self._upstox_backfill(sym, from_dt, to_dt)
                self._fetched.add(sym)
                raw = self._read(sym, from_dt, to_dt)
            if raw is None or raw.empty or len(raw) < MIN_WARMUP + 2:
                return sym, None
            df = raw.set_index("timestamp")
            idx = pd.to_datetime(df.index)
            if getattr(idx, "tz", None) is None:
                idx = idx.tz_localize("UTC")
            df.index = idx
            df = compute_all_features(df)
            ist = _ist_index(df.index)
            if not isinstance(ist, pd.DatetimeIndex):
                return sym, None
            day_mask      = (ist.date == asof)
            day_positions = np.flatnonzero(day_mask)
            if day_positions.size == 0:
                return sym, None
            day_ts = list(df.index[day_positions])
            pos_of = {ts: int(p) for ts, p in zip(day_ts, day_positions)}
            return sym, {
                "df":   df,
                "open":  df["open"].to_numpy(dtype=float),
                "high":  df["high"].to_numpy(dtype=float),
                "low":   df["low"].to_numpy(dtype=float),
                "close": df["close"].to_numpy(dtype=float),
                "n":     len(df),
                "day_ts": day_ts,
                "pos_of": pos_of,
                "last_result": None,
            }

        _MAX_WORKERS = min(12, len(symbols))
        done = 0
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futs = {pool.submit(_load_one, sym): sym for sym in symbols}
            for fut in as_completed(futs):
                done += 1
                if progress and done % 5 == 0:
                    progress(0.08 + 0.12 * done / max(1, len(symbols)),
                             f"Loaded {done}/{len(symbols)} symbols…")
                try:
                    sym, result = fut.result()
                    if result is not None:
                        out[sym] = result
                except Exception as exc:
                    logger.debug(f"_load_day {futs[fut]}: {exc}")
        return out

    # ── Trade close / helpers ───────────────────────────────────────────────────

    def _close(self, sym: str, pos: dict, ts, exit_price: float, reason: str) -> ReplayTrade:
        entry = pos["entry_price"]
        qty = int(pos["qty"])
        if pos["direction"] == Direction.LONG:
            gross = (exit_price - entry) * qty
        else:
            gross = (entry - exit_price) * qty
        parts = cost_breakdown(entry, exit_price, qty)
        cost = parts["total"]
        net = gross - cost
        notional = entry * qty
        direction = "LONG" if pos["direction"] == Direction.LONG else "SHORT"
        _mult = float(pos.get("margin_multiplier", 1.0))
        _mreq = float(pos.get("margin_required", notional))
        return ReplayTrade(
            symbol=sym, side=pos["side"], direction=direction, qty=qty,
            entry_time=pos["entry_time"], exit_time=self._iso(ts),
            entry_price=round(entry, 2), exit_price=round(float(exit_price), 2),
            notional=round(float(notional), 2),
            leverage=round(float(notional / self.capital), 3) if self.capital > 0 else 0.0,
            gross_pnl=round(float(gross), 2), cost=round(float(cost), 2),
            net_pnl=round(float(net), 2),
            return_pct=round(float(net / notional), 5) if notional > 0 else 0.0,
            bars_held=int(self._bars_held(pos, ts)), exit_reason=reason,
            entry_score=round(float(pos["entry_score"]), 4), regime=pos["regime"],
            sizing_note=pos["sizing_note"], cost_parts=parts,
            signal_scores={k: round(v, 4) for k, v in pos["signal_scores"].items()},
            margin_multiplier=round(_mult, 2),
            margin_required=round(_mreq, 2),
        )

    @staticmethod
    def _bars_held(pos: dict, ts) -> int:
        try:
            return max(0, int((pd.Timestamp(ts) - pd.Timestamp(pos["entry_time"])).total_seconds() // 300))
        except Exception:
            return 0

    @staticmethod
    def _reason_chain(res) -> list[str]:
        """Human-readable 'why this entry' — top contributing signals + regime."""
        contribs = []
        for name, score in res.signal_scores.items():
            w = res.weights_used.get(name, 0.0)
            contribs.append((name, score * w))
        contribs.sort(key=lambda x: abs(x[1]), reverse=True)
        top = ", ".join(f"{n} ({c:+.2f})" for n, c in contribs[:3] if abs(c) > 1e-6)
        return [f"composite {res.composite_score:+.3f} @ {res.regime.value}",
                f"top signals: {top}" if top else "no dominant signal"]

    @staticmethod
    def _safe_atr(df: pd.DataFrame, pos: int) -> float:
        try:
            v = float(df["atr_14"].iloc[pos])
            if math.isfinite(v) and v > 0:
                return v
        except Exception:
            pass
        recent = df["close"].iloc[max(0, pos - 20): pos + 1]
        s = float(recent.std()) if len(recent) > 1 else 0.0
        return s if s > 0 else max(1e-6, float(df["close"].iloc[pos]) * 0.01)

    @staticmethod
    def _to_ist(ts) -> datetime:
        t = pd.Timestamp(ts)
        t = t.tz_localize("UTC") if t.tz is None else t
        return t.tz_convert("Asia/Kolkata").to_pydatetime()

    @classmethod
    def _iso(cls, ts) -> str:
        return cls._to_ist(ts).isoformat()

    @staticmethod
    def _t0(asof: date, hhmm: str) -> str:
        h, m = map(int, hhmm.split(":"))
        return datetime(asof.year, asof.month, asof.day, h, m).isoformat()

    # ── Summary + persistence ───────────────────────────────────────────────────

    def _finish(self, run_id, asof, trades, events, watchlist, why, symbols,
                status=None, gate_counts=None, last_score=None, data=None) -> dict:
        summary = self._summary(trades)
        universe = self._universe_table(symbols, why, status or {}, last_score or {}, data or {})
        result = {
            "run_id": run_id,
            "date": str(asof),
            "params": {
                "capital": self.capital,
                "risk_profile": getattr(self.risk, "name", str(self.risk)),
                "use_ml_gates": self.use_ml_gates,
                "use_margin": self.use_margin,
                "timeframe": self.timeframe,
            },
            "summary": summary,
            "universe": universe,
            "trades": [asdict(t) for t in trades],
            "events": events,
            "gate_counts": gate_counts or {},
            "watchlist": watchlist,
        }
        try:
            self._save(run_id, result)
        except Exception as e:
            logger.warning(f"could not save replay result: {e}")
        return result

    def _universe_table(self, symbols, why, status, last_score, data) -> list[dict]:
        rows = []
        for s in symbols:
            res = (data.get(s) or {}).get("last_result")
            _mis = self._margin.get(s, {})
            rows.append({
                "symbol": s,
                "strategies": why.get(s, {}).get("strategies", []),
                "screener_score": why.get(s, {}).get("score"),
                "reasons": why.get(s, {}).get("reasons", []),
                "last_score": round(last_score.get(s, 0.0), 4) if s in last_score else None,
                "direction": res.direction.value if res else None,
                "regime": res.regime.value if res else None,
                "status": status.get(s, "SCANNING"),
                "multiplier": _mis.get("multiplier"),
                "margin_pct": _mis.get("margin_pct"),
            })
        # Sort: in-position / traded first, then by |last_score|.
        order = {"IN_POSITION": 0, "TRADED": 1, "ARMED": 2, "GATED": 3, "SIGNAL": 4, "SCANNING": 5}
        rows.sort(key=lambda r: (order.get(r["status"], 9), -abs(r["last_score"] or 0)))
        return rows

    def _summary(self, trades: list[ReplayTrade]) -> dict:
        n = len(trades)
        if n == 0:
            return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                    "gross_pnl": 0.0, "costs": 0.0, "net_pnl": 0.0, "max_drawdown": 0.0,
                    "return_pct": 0.0, "profit_factor": None, "expectancy": 0.0,
                    "cost_parts": {}, "by_exit_reason": {},
                    "longs": 0, "shorts": 0, "capital": round(self.capital, 2),
                    "peak_exposure": 0.0, "peak_exposure_pct": 0.0,
                    "peak_leverage": 0.0, "uses_margin": False}
        nets = np.array([t.net_pnl for t in trades], dtype=float)
        gross = float(sum(t.gross_pnl for t in trades))
        costs = float(sum(t.cost for t in trades))
        wins = nets[nets > 0]
        losses = nets[nets < 0]
        # Intraday equity curve in trade order (by exit time).
        order = sorted(trades, key=lambda t: t.exit_time)
        eq = self.capital
        peak = eq
        max_dd = 0.0
        for t in order:
            eq += t.net_pnl
            peak = max(peak, eq)
            if peak > 0:
                max_dd = max(max_dd, (peak - eq) / peak)
        pf = float(wins.sum() / abs(losses.sum())) if losses.size and losses.sum() != 0 else (
            float("inf") if wins.size else 0.0)
        parts_sum: dict = defaultdict(float)
        for t in trades:
            for k, v in (t.cost_parts or {}).items():
                parts_sum[k] += v
        by_reason: dict = defaultdict(lambda: {"trades": 0, "net": 0.0})
        for t in trades:
            by_reason[t.exit_reason]["trades"] += 1
            by_reason[t.exit_reason]["net"] += t.net_pnl
        # Peak concurrent exposure (sweep over open intervals) → margin/leverage use.
        marks: list[tuple[str, float]] = []
        for t in trades:
            marks.append((t.entry_time, t.notional))
            marks.append((t.exit_time, -t.notional))
        marks.sort(key=lambda x: (x[0], x[1]))   # process exits(-) before entries(+) at a tie
        run_exp = 0.0
        peak_exp = 0.0
        for _, delta in marks:
            run_exp += delta
            peak_exp = max(peak_exp, run_exp)
        peak_lev = peak_exp / self.capital if self.capital > 0 else 0.0
        return {
            "total_trades": n,
            "wins": int((nets > 0).sum()),
            "losses": int((nets < 0).sum()),
            "win_rate": round(100.0 * (nets > 0).sum() / n, 2),
            "longs": int(sum(1 for t in trades if t.direction == "LONG")),
            "shorts": int(sum(1 for t in trades if t.direction == "SHORT")),
            "gross_pnl": round(gross, 2),
            "costs": round(costs, 2),
            "net_pnl": round(float(nets.sum()), 2),
            "max_drawdown": round(max_dd * 100.0, 2),
            "return_pct": round(float(nets.sum()) / self.capital * 100.0, 3),
            "profit_factor": round(pf, 3) if math.isfinite(pf) else None,
            "expectancy": round(float(nets.mean()), 2),
            "capital": round(self.capital, 2),
            "peak_exposure": round(peak_exp, 2),
            "peak_exposure_pct": round(peak_exp / self.capital * 100.0, 1) if self.capital > 0 else 0.0,
            "peak_leverage": round(peak_lev, 2),
            # MIS intraday equity: exposure beyond cash means broker margin/leverage is used.
            "uses_margin": bool(peak_exp > self.capital),
            "cost_parts": {k: round(v, 2) for k, v in parts_sum.items()},
            "by_exit_reason": {k: {"trades": v["trades"], "net": round(v["net"], 2)}
                               for k, v in by_reason.items()},
        }

    def _save(self, run_id: str, result: dict) -> str:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / f"{result['date']}_{run_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        logger.info(f"Action Replay result saved: {path}")
        return str(path)
