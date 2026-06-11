"""
Live Trading Runner — Main loop for real-time signal generation and order execution.

Lifecycle:
  1. Pre-market (9:00): read daily_watchlist.json, init all components
  2. Connect Upstox WebSocket, subscribe to watchlist symbols
  3. Every 30s: compute features → signals → ensemble → risk check → order
  4. Every 1s:  monitor open positions for SL/target/trailing SL
  5. 15:25 IST: EOD square-off all positions
  6. 15:30 IST: save daily_performance, send Discord summary

Run:
    python live/runner.py
    python live/runner.py --paper  # force paper mode
"""

from __future__ import annotations
import json
import time
import queue
import argparse
import threading
from datetime import datetime
from typing import Optional

import pandas as pd
import pytz
from loguru import logger

from config.settings import (
    INSTRUMENTS, DAILY_WATCHLIST_PATH, TRADING_CAPITAL,
    EOD_SQUAREOFF_TIME, PAPER_TRADE, TIMEFRAME_PRIMARY,
    SECTOR_GUARD_ENABLED, MAX_POSITIONS_PER_SECTOR,
    USE_MARGIN, MAX_MIS_LEVERAGE,
)
from config import control
from config.risk_profiles import ACTIVE as RISK, get_profile
from risk.correlation_guard import CorrelationGuard
from data.db import init_db, read_candles, get_open_trades, log_trade_open, log_trade_close
from data.upstox_feed import UpstoxFeed
from features.indicators import compute_all_features
from ensemble.aggregator import EnsembleAggregator
from ensemble.position_sizing import PositionSizer
from risk.circuit_breaker import CircuitBreaker
from live import decision
from live.openalgo_client import OpenAlgoClient
from analytics.pnl_tracker import PnLTracker
from analytics.costs import round_trip_cost, is_cost_effective
from analytics import discord_notify as notify
from signals.base import Direction

# Phase 2 ML gates (singletons; load saved models if present, else stay neutral)
from signals.ml.macro_model import get_macro_model
from signals.ml.micro_model import get_micro_model
from signals.ml.strategy_outcomes import get_outcome_models
from models.rl_entry_agent import get_rl_entry_agent, EntryState

# Strategy tag used for trade_log + per-strategy outcome models. Keep in sync.
STRATEGY_TAG = "vwap_rsi_ensemble"

# A live price older than this (seconds) is treated as STALE — stops are not
# evaluated against it (we never substitute entry_price, issue FEED-02).
STALE_PRICE_SECONDS = 15.0
# Periodic full-rescan cadence as a fallback when bar-close events are quiet/absent.
FALLBACK_SWEEP_SECONDS = 60.0

# Encode regimes to the ints the RL entry agent expects.
_REGIME_ENCODING = {
    "TRENDING_UP": 0,
    "TRENDING_DOWN": 1,
    "MEAN_REVERTING": 2,
    "CHOPPY": 3,
}

IST = pytz.timezone("Asia/Kolkata")

# ── Global state (shared between main loop and position monitor) ──────────────
_open_positions: dict[str, dict] = {}   # trade_id → position details
_session_pnl:   float = 0.0
_state_lock     = threading.Lock()


class LiveRunner:
    """
    Orchestrates the full live trading session.
    """

    def __init__(self, paper: bool = PAPER_TRADE, use_ml_gates: bool = True):
        self.paper       = paper
        self.use_margin  = USE_MARGIN
        self.aggregator  = EnsembleAggregator()
        self.sizer       = PositionSizer(capital=TRADING_CAPITAL)
        self.breaker     = CircuitBreaker(capital=TRADING_CAPITAL)
        # Load margin multiplier cache (populated by scripts/fetch_margin_multipliers.py)
        try:
            from data.margin import load_margin_multipliers
            self._margin: dict = load_margin_multipliers()
        except Exception:
            self._margin = {}
        if self.use_margin and not self._margin:
            logger.warning("USE_MARGIN=true but margin cache is empty. "
                           "Run: python scripts/fetch_margin_multipliers.py (needs live token). "
                           "Falling back to cash sizing.")
        self.corr_guard  = CorrelationGuard(
            max_per_sector=MAX_POSITIONS_PER_SECTOR, enabled=SECTOR_GUARD_ENABLED)
        self.client      = OpenAlgoClient(paper=paper)
        self.pnl_tracker = PnLTracker()
        self.feed: Optional[UpstoxFeed] = None
        self._running    = False
        self._symbols: list[str] = []

        # ── Control-plane / safety state ──────────────────────────────────────
        self._kill_active       = False   # dashboard kill switch currently active
        self._entries_paused    = False   # auto-trade paused (or halted)
        self._daily_loss_halted = False   # proactive daily-loss halt fired today
        self._exiting: set[str] = set()   # trade_ids with an exit in flight (no double-exit)
        self._control_lock      = threading.Lock()

        # Event-driven signalling: the feed enqueues a symbol when its primary-tf
        # bar closes; the signal loop processes those instead of a blind 30s sweep.
        self._candle_q: "queue.Queue[str]" = queue.Queue()
        self._stale_warned: dict[str, float] = {}   # symbol -> last stale-warn monotonic ts

        # ── Phase 2 ML gates ──────────────────────────────────────────────
        # Each gate is "open" (allows entry) until its model is trained, so the
        # rule-based system keeps trading while live data accumulates.
        self.use_ml_gates = use_ml_gates
        self.macro_model   = get_macro_model()
        self.micro_model   = get_micro_model()
        self.outcome_models = get_outcome_models()
        self.rl_entry      = get_rl_entry_agent()
        # Macro directional gate centres on the model's training base rate
        # (macro_res.base_rate), not a fixed 0.50 — see _passes_ml_gates.
        # Daily loss limit (for RL entry session-PnL feature).
        self._daily_loss_limit = TRADING_CAPITAL * RISK.max_daily_loss_pct / 100.0
        # Last composite score per symbol (for score_momentum feature).
        self._last_score: dict[str, float] = {}

    # ── Startup ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        logger.info("=" * 60)
        logger.info(f"AlgoTrading Live Runner | Paper={self.paper}")
        logger.info("=" * 60)

        init_db()

        # Adopt any positions that were open when we last stopped/crashed, so they
        # are monitored and squared off rather than orphaned (issue LIVE-04).
        self._reconcile_open_positions()

        # Prime the sizer's Kelly layer from trade history so it's already calibrated
        # at boot rather than only after the first exit of the session (issue SIZE-03).
        self._refresh_kelly_stats()

        self._symbols = self._load_watchlist()
        logger.info(f"Today's watchlist ({len(self._symbols)} symbols): {self._symbols}")

        if not self.paper and not self.client.check_connection():
            logger.warning("OpenAlgo not reachable — switching to PAPER mode")
            self.client.paper_mode = True

        # Start live feed
        self.feed = UpstoxFeed(
            symbols=self._symbols,
            on_candle=self._on_candle,
        )
        try:
            self.feed.start()
        except ValueError as e:
            logger.warning(f"Feed start failed ({e}) — running in data-less mode")

        self._running = True

        # Start position monitor in background thread
        monitor_thread = threading.Thread(target=self._position_monitor_loop, daemon=True)
        monitor_thread.start()

        # Main signal loop
        self._signal_loop()

    def stop(self) -> None:
        self._running = False
        if self.feed:
            self.feed.stop()
        self._eod_close()
        logger.info("Runner stopped")

    # ── Main signal loop (every 30s) ──────────────────────────────────────────

    def _signal_loop(self) -> None:
        """
        Event-driven signal loop: process a symbol when its primary-timeframe bar
        closes (pushed by the feed via _on_candle), instead of a blind 30s sweep.
        A periodic full-rescan is kept as a fallback so a quiet/dead feed can't
        stall trading. Control state + EOD are checked every ~1s, so the kill
        switch / pause now take effect within a second instead of up to 30s.
        """
        logger.info("Signal loop started (event-driven on bar close, with periodic fallback)")
        last_sweep = 0.0
        while self._running:
            self._apply_control_state()     # pick up dashboard kill switch / pause / weights
            self._check_eod(datetime.now(IST))

            # Drain bar-close events (blocks up to 1s so control/EOD stay responsive).
            try:
                while True:
                    symbol = self._candle_q.get(timeout=1.0)
                    if symbol in self._symbols:
                        try:
                            self._process_symbol(symbol)
                        except Exception as e:
                            logger.error(f"Signal error for {symbol}: {e}")
            except queue.Empty:
                pass

            # Fallback: periodic full rescan (covers a quiet/dead feed).
            if time.time() - last_sweep >= FALLBACK_SWEEP_SECONDS:
                for symbol in self._symbols:
                    try:
                        self._process_symbol(symbol)
                    except Exception as e:
                        logger.error(f"Signal sweep error for {symbol}: {e}")
                last_sweep = time.time()

    def _process_symbol(self, symbol: str) -> None:
        """Load latest candles, compute features, check for signal, place order."""
        global _session_pnl, _open_positions

        # Load candles
        df = read_candles(symbol, TIMEFRAME_PRIMARY, limit=200)
        if df.empty or len(df) < 60:
            return

        df = df.set_index("timestamp")
        df = compute_all_features(df)

        # Compute ensemble score
        result = self.aggregator.compute(df, symbol)

        # Track score momentum (now vs previous poll) for the RL entry agent.
        prev_score = self._last_score.get(symbol, result.composite_score)
        self._last_score[symbol] = result.composite_score

        if not result.actionable:
            return

        # Already have a position in this symbol?
        with _state_lock:
            already_in = any(p["symbol"] == symbol for p in _open_positions.values())

        if already_in:
            return

        # Control plane: kill switch active or auto-trade paused → no new entries
        # (existing positions are still monitored / managed).
        if self._kill_active or self._entries_paused:
            logger.debug(f"ENTRY SUPPRESSED [{symbol}]: "
                         f"{'kill_switch' if self._kill_active else 'trading_paused'}")
            return

        # ML gates: macro direction, micro entry, strategy outcome, RL entry.
        if self.use_ml_gates:
            passed, gate_reason = self._passes_ml_gates(symbol, df, result, prev_score)
            if not passed:
                logger.debug(f"ML GATE BLOCKED [{symbol}]: {gate_reason}")
                return

        # Circuit breaker check
        with _state_lock:
            open_count = len(_open_positions)
            open_risks = [p.get("risk_amount", 0) for p in _open_positions.values()]

        allowed, reason = self.breaker.allow_entry(symbol, _session_pnl, open_count)
        if not allowed:
            logger.debug(f"BLOCKED [{symbol}]: {reason}")
            return

        # Correlation / sector guard (EDGE-03): don't stack the book into one sector
        # or a correlated cluster, even within the global concurrency cap.
        with _state_lock:
            open_symbols = [p["symbol"] for p in _open_positions.values()]
        corr_ok, corr_reason = self.corr_guard.allow(symbol, open_symbols)
        if not corr_ok:
            logger.debug(f"SECTOR/CORR BLOCKED [{symbol}]: {corr_reason}")
            return

        # Position sizing
        last_bar = df.iloc[-1]
        atr      = float(last_bar.get("atr_14", df["close"].std()))
        price    = float(last_bar["close"])

        _sym_mult = 1.0
        if self.use_margin and self._margin:
            raw = float(self._margin.get(symbol, {}).get("multiplier", 1.0))
            _sym_mult = min(raw, MAX_MIS_LEVERAGE)
        sizing = self.sizer.size(
            symbol=symbol,
            direction=result.direction,
            score=result.composite_score,
            entry_price=price,
            atr=atr,
            open_positions_risk=open_risks,
            regime=result.regime,
            margin_multiplier=_sym_mult,
        )
        if not sizing:
            logger.debug(f"SIZING BLOCKED [{symbol}]: portfolio heat exceeded")
            return

        # Cost-aware gate: skip setups whose best-case (target) move can't clear
        # round-trip costs by a safe margin — the marginal trades that turn a gross
        # edge into a net loss (PnL-NET).
        if not is_cost_effective(price, sizing.target_price, sizing.qty):
            logger.debug(f"COST-FILTER BLOCKED [{symbol}]: best-case target move "
                         f"doesn't clear round-trip costs by the required margin")
            return

        # Place order (consistent SEBI strategy tag — issue TAG-01)
        action = "BUY" if result.direction == Direction.LONG else "SELL"
        order  = self.client.place_order(
            symbol=symbol,
            action=action,
            quantity=sizing.qty,
            strategy_tag=STRATEGY_TAG,
        )

        if not order.success:
            logger.error(f"ORDER FAILED [{symbol}]: {order.error}")
            return

        # Book the actually-FILLED quantity at the broker-reported average fill price
        # (issue LIVE-03). A rejected/0-fill accept never becomes a position; a partial
        # entry books only what filled, so the SL monitor manages the real exposure.
        filled_qty = order.filled_qty if order.filled_qty > 0 else sizing.qty
        if filled_qty <= 0:
            logger.error(f"ORDER ACCEPTED BUT 0 FILLED [{symbol}] — not booking a position")
            return
        if filled_qty < sizing.qty:
            logger.warning(f"PARTIAL ENTRY [{symbol}] filled {filled_qty}/{sizing.qty} — booking the filled qty")
        price = order.avg_price if order.avg_price > 0 else self._confirm_fill_price(order.order_id, fallback=price)
        risk_amount = abs(price - sizing.sl_price) * filled_qty

        # Record in DB
        trade_id = log_trade_open(
            symbol=symbol,
            strategy=STRATEGY_TAG,
            side=action,
            product_type="INTRADAY",
            qty=filled_qty,
            entry_price=price,
            sl_price=sizing.sl_price,
            target_price=sizing.target_price,
            entry_score=result.composite_score,
            regime=result.regime.value,
            openalgo_order_id=order.order_id,
            mode="PAPER" if self.paper else "LIVE",
        )

        with _state_lock:
            _open_positions[trade_id] = {
                "symbol":       symbol,
                "side":         action,
                "qty":          filled_qty,
                "entry_price":  price,
                "sl_price":     sizing.sl_price,
                "target_price": sizing.target_price,
                "atr":          atr,
                "risk_amount":  risk_amount,
                "exit_filled":  0,                   # cumulative exit fills (partial handling)
                "entry_time":   datetime.now(IST),   # so hold-time is real (was always ~0)
            }

        self.breaker.record_entry()
        logger.success(
            f"ENTRY [{symbol}] {action} × {filled_qty} @ {price:.2f} | "
            f"SL={sizing.sl_price:.2f} TGT={sizing.target_price:.2f} | "
            f"Score={result.composite_score:.3f} | {sizing.sizing_note}"
        )
        notify.trade_entry(
            symbol, action, filled_qty, price,
            sizing.sl_price, sizing.target_price,
            result.composite_score, STRATEGY_TAG, result.regime.value,
        )

    # ── ML gates (Phase 2) ────────────────────────────────────────────────────

    def _passes_ml_gates(self, symbol: str, df, result, prev_score: float) -> tuple[bool, str]:
        """
        Thin wrapper over the shared decision pipeline (live/decision.py) so the
        live runner and Action Replay take the identical ML-gate code path. The
        2-tuple (passed, reason) contract is preserved for callers/tests.
        """
        with _state_lock:
            open_count = len(_open_positions)
        passed, reason, _macro = decision.passes_ml_gates(
            symbol=symbol, df=df, result=result, prev_score=prev_score,
            macro_model=self.macro_model, micro_model=self.micro_model,
            outcome_models=self.outcome_models, rl_entry=self.rl_entry,
            strategy_tag=STRATEGY_TAG, session_pnl=_session_pnl,
            daily_loss_limit=self._daily_loss_limit, open_count=open_count,
            recent_win_rate=self._recent_win_rate(),
        )
        return passed, reason

    def _build_entry_state(self, symbol: str, df, result, prev_score: float,
                           macro_prob: float) -> EntryState:
        """Assemble the EntryState feature vector (delegates to live/decision.py)."""
        with _state_lock:
            open_count = len(_open_positions)
        return decision.build_entry_state(
            result=result, df=df, prev_score=prev_score, macro_prob=macro_prob,
            session_pnl=_session_pnl, daily_loss_limit=self._daily_loss_limit,
            open_count=open_count, recent_win_rate=self._recent_win_rate(),
        )

    def _recent_win_rate(self) -> float:
        return (self.pnl_tracker.recent_win_rate()
                if hasattr(self.pnl_tracker, "recent_win_rate") else 0.5)

    # ── Position monitor (every 1s) ───────────────────────────────────────────

    def _position_monitor_loop(self) -> None:
        """Background thread: check SL/target/trailing SL for all open positions."""
        logger.info("Position monitor started")
        while self._running:
            try:
                self._apply_control_state()    # fast kill-switch reaction (every 1s)
                self._enforce_daily_loss()     # proactive daily-loss halt (issue LIVE-05)
                self._check_all_positions()
            except Exception as e:
                logger.error(f"Position monitor error: {e}")
            time.sleep(1)

    def _check_all_positions(self) -> None:
        global _session_pnl, _open_positions

        with _state_lock:
            to_exit = []
            for trade_id, pos in _open_positions.items():
                symbol = pos["symbol"]
                # Use a FRESH live price only. If it's missing/stale we skip the
                # stop check and raise a (throttled) alert — we never substitute
                # entry_price, which would silently disable the stop (issue FEED-02).
                price, age = self._live_price(symbol)
                if price is None or (age is not None and age > STALE_PRICE_SECONDS):
                    self._warn_stale_feed(symbol, age)
                    continue
                ltp    = price
                side   = pos["side"]
                sl     = pos["sl_price"]
                tgt    = pos["target_price"]

                direction = Direction.LONG if side == "BUY" else Direction.SHORT

                # Update trailing SL
                new_sl = self.sizer.compute_trailing_sl(
                    direction=direction,
                    entry_price=pos["entry_price"],
                    current_price=ltp,
                    current_sl=sl,
                    atr=pos["atr"],
                )
                if new_sl != sl:
                    pos["sl_price"] = new_sl

                # Check exit conditions
                exit_reason = None
                if direction == Direction.LONG:
                    if ltp <= pos["sl_price"]:
                        exit_reason = "SL_HIT"
                    elif ltp >= tgt:
                        exit_reason = "TARGET_HIT"
                else:
                    if ltp >= pos["sl_price"]:
                        exit_reason = "SL_HIT"
                    elif ltp <= tgt:
                        exit_reason = "TARGET_HIT"

                if exit_reason:
                    to_exit.append((trade_id, pos, ltp, exit_reason))

        for trade_id, pos, ltp, reason in to_exit:
            self._exit_position(trade_id, pos, ltp, reason)

    def _exit_position(self, trade_id: str, pos: dict, exit_price: float, reason: str) -> None:
        """
        Exit a position. Critically (issue LIVE-01): the position is only removed
        from the book after a CONFIRMED exit order. On failure it is kept open and
        retried with backoff, escalating to a broker-side close-all after 3 tries.
        A per-trade guard prevents two threads (monitor + EOD/kill flatten) from
        double-exiting the same position.
        """
        global _session_pnl, _open_positions
        symbol    = pos["symbol"]
        exit_side = "SELL" if pos["side"] == "BUY" else "BUY"

        # Claim this trade for exit; bail if already exiting or already gone.
        with _state_lock:
            if trade_id in self._exiting or trade_id not in _open_positions:
                return
            # Backoff: don't hammer the broker after a failed attempt.
            last = pos.get("last_exit_attempt", 0.0)
            if pos.get("exit_attempts", 0) > 0 and (time.time() - last) < 5.0:
                return
            self._exiting.add(trade_id)
            pos["last_exit_attempt"] = time.time()

        # Only the still-open residual needs exiting (a prior attempt may have
        # partially filled). pos["qty"] stays the full size for PnL bookkeeping.
        residual = int(pos["qty"]) - int(pos.get("exit_filled", 0))
        if residual <= 0:
            with _state_lock:
                _open_positions.pop(trade_id, None)
            self._exiting.discard(trade_id)
            return

        try:
            order = self.client.place_order(
                symbol=symbol, action=exit_side,
                quantity=residual, strategy_tag=STRATEGY_TAG,
            )

            if not order.success:
                # Position is STILL LIVE — keep it in the book and retry next tick.
                attempts = pos.get("exit_attempts", 0) + 1
                pos["exit_attempts"] = attempts
                logger.error(f"EXIT ORDER FAILED [{symbol}] attempt {attempts}: "
                             f"{order.error} — position kept open, will retry")
                notify.error(f"Exit failed for {symbol} (attempt {attempts}): {order.error}")
                if attempts >= 3:
                    logger.critical(f"Exit failed {attempts}× for {symbol} — escalating to broker close-all")
                    try:
                        self.client.close_all_positions(strategy_tag=STRATEGY_TAG)
                    except Exception as e:
                        logger.error(f"close_all_positions escalation failed: {e}")
                    notify.alert("⚠️ EXIT FAILURE",
                                 f"{symbol} exit failed {attempts}×. Manual intervention may be required.")
                return

            # Confirmed accepted — book at the actual fill price where reported.
            fill_price = order.avg_price if order.avg_price > 0 else \
                self._confirm_fill_price(order.order_id, fallback=exit_price)
            filled = order.filled_qty if order.filled_qty > 0 else residual

            # Partial exit: shares are still live. Track cumulative fills and keep the
            # position open to retry the remainder rather than popping it (LIVE-03).
            if filled < residual:
                pos["exit_filled"] = int(pos.get("exit_filled", 0)) + int(filled)
                pos["exit_attempts"] = 0   # genuine progress — reset the backoff
                with _state_lock:
                    if trade_id in _open_positions:
                        _open_positions[trade_id]["exit_filled"] = pos["exit_filled"]
                still_live = int(pos["qty"]) - pos["exit_filled"]
                logger.warning(f"PARTIAL EXIT [{symbol}] {filled}/{residual} @ {fill_price:.2f}; "
                               f"{still_live} still live — will retry")
                notify.log(f"Partial exit {symbol}: {filled} filled, {still_live} retrying", "WARN")
                return

            # Fully exited — book PnL on the entire original position and close it out.
            log_trade_close(trade_id, fill_price, reason, order.order_id)

            gross = (fill_price - pos["entry_price"]) * pos["qty"]
            if pos["side"] == "SELL":
                gross = -gross
            # Book NET of transaction costs so the session-PnL the daily-loss rail
            # watches is what actually hits the account, not gross (PnL-NET). Net
            # losses are larger than gross, so a gross-based rail halts too late.
            cost = round_trip_cost(pos["entry_price"], fill_price, pos["qty"])
            pnl  = gross - cost

            with _state_lock:
                _session_pnl += pnl
                _open_positions.pop(trade_id, None)

            logger.info(
                f"EXIT [{symbol}] {reason} @ {fill_price:.2f} | "
                f"net PnL={pnl:+.2f} (gross {gross:+.2f}, cost {cost:.2f}) | "
                f"Session PnL={_session_pnl:+.2f}"
            )
            hold_min = (datetime.now(IST) - pos.get("entry_time", datetime.now(IST))).total_seconds() / 60
            notify.trade_exit(symbol, pos["side"], pos["qty"], pos["entry_price"],
                              fill_price, reason, pnl, hold_min)

            # SIZE-03: another trade just closed — refresh the sizer's Kelly inputs
            # from realized results. Without this the Kelly layer stays inert
            # (it never saw a win-rate / reward:risk and never passes its activation gate).
            self._refresh_kelly_stats()
        finally:
            self._exiting.discard(trade_id)

    def _refresh_kelly_stats(self) -> None:
        """
        Feed realized win-rate / reward:risk / closed-trade count into the position
        sizer so its Kelly layer actually engages (issue SIZE-03). Never raises — a
        stats refresh must not be able to interfere with trading.
        """
        try:
            wr, rr, n = self.pnl_tracker.kelly_stats()
            self.sizer.update_kelly_stats(wr, rr, n)
            logger.debug(
                f"Kelly stats refreshed | win_rate={wr:.2f} rr={rr:.2f} n={n}"
                f"{' (active)' if n >= 20 else ' (warming up <20)'}"
            )
        except Exception as e:
            logger.debug(f"Kelly stats refresh skipped: {e}")

    # ── Control plane + safety ─────────────────────────────────────────────────

    def _apply_control_state(self) -> None:
        """
        Read the dashboard control file and apply it to this live session
        (issue CTRL-01). Makes the kill switch, auto-trade pause, weight overrides
        and signal toggles actually affect live trading.
        """
        try:
            ctrl = control.read_control()
        except Exception as e:
            logger.debug(f"control read failed: {e}")
            return

        ks = bool(ctrl.get("kill_switch", False))
        with self._control_lock:
            if ks and not self._kill_active:
                self._kill_active = True
                self.breaker.trigger_kill_switch(True)
                logger.critical("KILL SWITCH (dashboard) — flattening all positions")
                fire_flatten = True
            elif not ks and self._kill_active:
                self._kill_active = False
                self.breaker.trigger_kill_switch(False)
                logger.info("Kill switch cleared (dashboard) — entries may resume")
                fire_flatten = False
            else:
                fire_flatten = False
        if fire_flatten:
            self._flatten_all("KILL_SWITCH")

        # Auto-trade pause (does not flatten). Daily-loss halt also pauses entries.
        self._entries_paused = (not bool(ctrl.get("trading_enabled", True))) or self._daily_loss_halted

        # Live weight overrides + signal enable/disable from the dashboard.
        wo = ctrl.get("weights_override") or {}
        if wo:
            try:
                self.aggregator.update_weights({k: float(v) for k, v in wo.items()})
            except Exception as e:
                logger.debug(f"weights override failed: {e}")
        disabled = set(ctrl.get("disabled_signals") or [])
        for s in self.aggregator.signals:
            self.aggregator.set_signal_enabled(s.name, s.name not in disabled)

        # Live risk-profile / capital overrides from the dashboard header.
        self._apply_risk_capital(ctrl)

    def _apply_risk_capital(self, ctrl: dict) -> None:
        """
        Apply dashboard risk-profile / capital changes WITHOUT a restart by updating
        the sizer + breaker in place (their `risk`/`capital` are injected attributes,
        so no session state — trades_today, halts, Kelly stats — is lost).
        """
        rp = ctrl.get("risk_profile")
        if rp:
            try:
                prof = get_profile(rp)
                if prof is not self.sizer.risk:
                    self.sizer.risk = prof
                    self.breaker.risk = prof
                    self._daily_loss_limit = self.breaker.capital * prof.max_daily_loss_pct / 100.0
                    logger.info(f"Risk profile applied live → {rp}")
            except ValueError:
                logger.warning(f"ignoring unknown risk_profile from control plane: {rp}")

        cap = ctrl.get("capital")
        if cap:
            try:
                cap = float(cap)
                if cap > 0 and abs(cap - self.sizer.capital) > 1e-6:
                    self.sizer.capital = cap
                    self.breaker.capital = cap
                    self._daily_loss_limit = cap * self.breaker.risk.max_daily_loss_pct / 100.0
                    logger.info(f"Trading capital applied live → ₹{cap:,.0f}")
            except (TypeError, ValueError):
                pass

    def _enforce_daily_loss(self) -> None:
        """Halt + flatten the instant session PnL breaches the daily loss limit (LIVE-05)."""
        if self._daily_loss_halted:
            return
        if self._daily_loss_limit > 0 and _session_pnl <= -self._daily_loss_limit:
            self._daily_loss_halted = True
            self._entries_paused    = True
            self.breaker.force_halt(f"daily_loss_limit ({_session_pnl:.0f})")
            logger.critical(f"DAILY LOSS LIMIT breached (PnL={_session_pnl:+.0f}) — flattening + halting entries")
            notify.alert("🛑 Daily Loss Limit",
                         f"Session PnL ₹{_session_pnl:,.0f} ≤ -₹{self._daily_loss_limit:,.0f}. "
                         f"Flattening all positions and halting new entries for the day.")
            self._flatten_all("DAILY_LOSS_HALT")

    def _flatten_all(self, reason: str) -> None:
        """Close every open position now, then ask the broker to close anything left."""
        with _state_lock:
            positions_copy = dict(_open_positions)
        for trade_id, pos in positions_copy.items():
            ltp = self._last_known_price(pos["symbol"], pos)   # best price; never silently entry
            self._exit_position(trade_id, pos, ltp, reason)
        # Safety net: tell the broker to close anything our book might have missed.
        try:
            self.client.close_all_positions(strategy_tag=STRATEGY_TAG)
        except Exception as e:
            logger.error(f"close_all_positions ({reason}) failed: {e}")

    def _confirm_fill_price(self, order_id: str, fallback: float) -> float:
        """
        Best-effort: poll order status once and return the actual fill price when
        the broker reports it; otherwise the reference price (issue LIVE-03).
        Paper mode / missing id → fallback.
        """
        if not order_id or self.paper or order_id.startswith("PAPER_"):
            return float(fallback)
        try:
            st = self.client.get_order_status(order_id) or {}
            for k in ("average_price", "averageprice", "avgprice", "fill_price", "price"):
                v = st.get(k)
                if v not in (None, "", 0, "0"):
                    fv = float(v)
                    if fv > 0:
                        return fv
        except Exception as e:
            logger.debug(f"fill-price confirm failed for {order_id}: {e}")
        return float(fallback)

    def _reconcile_open_positions(self) -> None:
        """Rehydrate the in-memory book from open DB trades on startup (issue LIVE-04)."""
        try:
            df = get_open_trades()
        except Exception as e:
            logger.warning(f"reconcile: could not read open trades: {e}")
            return
        if df is None or df.empty:
            return
        adopted = 0
        for _, r in df.iterrows():
            try:
                tid    = str(r["trade_id"])
                symbol = str(r["symbol"])
                entry  = float(r["entry_price"])
                sl     = float(r["sl_price"]) if pd.notna(r.get("sl_price")) else entry
                tgt    = float(r["target_price"]) if pd.notna(r.get("target_price")) else entry
                qty    = int(r["qty"])

                # Best-effort ATR for the trailing-SL logic.
                atr = 0.0
                try:
                    cdf = read_candles(symbol, TIMEFRAME_PRIMARY, limit=60)
                    if not cdf.empty and len(cdf) >= 20:
                        cdf = compute_all_features(cdf.set_index("timestamp"))
                        atr = float(cdf.iloc[-1].get("atr_14", 0.0) or 0.0)
                except Exception:
                    pass

                et = pd.to_datetime(r["entry_time"]) if pd.notna(r.get("entry_time")) else None
                if et is not None:
                    et = et.to_pydatetime()
                    if et.tzinfo is None:
                        et = IST.localize(et)
                else:
                    et = datetime.now(IST)

                with _state_lock:
                    _open_positions[tid] = {
                        "symbol":       symbol,
                        "side":         str(r["side"]),
                        "qty":          qty,
                        "entry_price":  entry,
                        "sl_price":     sl,
                        "target_price": tgt,
                        "atr":          atr,
                        "risk_amount":  abs(entry - sl) * qty,
                        "entry_time":   et,
                    }
                adopted += 1
            except Exception as e:
                logger.warning(f"reconcile: skipped a row: {e}")
        if adopted:
            logger.warning(f"Reconciled {adopted} open position(s) from DB on startup")
            notify.log(f"Adopted {adopted} open position(s) from DB on startup", "WARN")

    # ── EOD handling ──────────────────────────────────────────────────────────

    def _check_eod(self, now_ist: datetime) -> None:
        eod_h, eod_m = map(int, EOD_SQUAREOFF_TIME.split(":"))
        if now_ist.hour == eod_h and now_ist.minute >= eod_m:
            self._eod_close()
            self._running = False

    def _eod_close(self) -> None:
        global _open_positions
        logger.info("EOD square-off — closing all open positions")
        with _state_lock:
            positions_copy = dict(_open_positions)

        for trade_id, pos in positions_copy.items():
            ltp = self._last_known_price(pos["symbol"], pos)
            self._exit_position(trade_id, pos, ltp, "EOD_SQUAREOFF")

        self.pnl_tracker.save_daily(_session_pnl)
        logger.success(f"EOD complete | Session PnL: {_session_pnl:+.2f}")
        stats = self.pnl_tracker.compute_daily_stats()
        notify.daily_summary(stats)

    # ── WebSocket callbacks ───────────────────────────────────────────────────

    def _on_candle(self, candle: dict) -> None:
        """
        Called by UpstoxFeed (feed thread) when a bar closes — including timer-forced
        closes (FEED-01). Enqueue the symbol for the signal loop to process on its
        primary timeframe. Only enqueue (cheap + thread-safe); all heavy work and
        order placement stay on the single signal-loop thread.
        """
        if candle.get("timeframe") == TIMEFRAME_PRIMARY:
            sym = candle.get("symbol")
            if sym:
                self._candle_q.put(sym)

    # ── Live price helpers (FEED-02) ───────────────────────────────────────────

    def _live_price(self, symbol: str) -> tuple[Optional[float], Optional[float]]:
        """Fresh (price, age_seconds) from the feed's in-memory cache, or (None, None)."""
        if self.feed is not None and hasattr(self.feed, "get_quote"):
            q = self.feed.get_quote(symbol)
            if q is not None:
                return q
        return None, None

    def _last_known_price(self, symbol: str, pos: Optional[dict] = None) -> float:
        """
        Best available price for a forced exit (flatten / EOD), in order:
        in-memory tick → last stored candle close → entry price (with a loud warning,
        since PnL booked at entry is unreliable). Never silently uses entry.
        """
        price, _ = self._live_price(symbol)
        if price is not None and price > 0:
            return price
        try:
            df = read_candles(symbol, TIMEFRAME_PRIMARY, limit=1)
            if not df.empty:
                return float(df.iloc[-1]["close"])
        except Exception:
            pass
        fallback = float(pos["entry_price"]) if pos else 0.0
        logger.error(f"No live/candle price for {symbol}; exiting at entry price "
                     f"{fallback:.2f} — booked PnL is UNRELIABLE")
        return fallback

    def _warn_stale_feed(self, symbol: str, age: Optional[float]) -> None:
        """Throttled warning when a position has no fresh price (stops can't fire)."""
        now = time.monotonic()
        last = self._stale_warned.get(symbol, 0.0)
        if now - last >= 30.0:   # at most once / 30s / symbol
            self._stale_warned[symbol] = now
            age_str = f"{age:.0f}s" if age is not None else "no tick yet"
            logger.warning(f"STALE FEED [{symbol}] ({age_str}) — SL/target NOT evaluated this tick; "
                           f"position is unprotected until a fresh price arrives")
            notify.alert("⚠️ Stale feed", f"{symbol}: no fresh price ({age_str}); stops paused.")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_watchlist(self) -> list[str]:
        """Load today's screener output, fallback to INSTRUMENTS config."""
        if DAILY_WATCHLIST_PATH.exists():
            try:
                data = json.loads(DAILY_WATCHLIST_PATH.read_text())
                # Flatten the per-strategy lists. Skip metadata keys (e.g. "_meta")
                # and any non-list values so screener metadata can't leak in as symbols.
                symbols = sorted({
                    s
                    for key, lst in data.items()
                    if not key.startswith("_") and isinstance(lst, list)
                    for s in lst
                })
                if symbols:
                    return symbols
            except Exception as e:
                logger.warning(f"Could not load watchlist: {e}")
        return list(INSTRUMENTS)


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AlgoTrading Live Runner")
    parser.add_argument("--paper", action="store_true", help="Force paper trade mode")
    parser.add_argument("--no-ml-gates", action="store_true",
                        help="Disable Phase 2 ML gates (run pure rule-based ensemble)")
    args = parser.parse_args()

    paper = args.paper or PAPER_TRADE
    runner = LiveRunner(paper=paper, use_ml_gates=not args.no_ml_gates)

    try:
        runner.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        runner.stop()
