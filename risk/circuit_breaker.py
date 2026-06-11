"""
Circuit Breaker — hard risk gates that halt trading when triggered.

Checks (in order):
  1. Daily loss limit     → halt for the rest of the day
  2. Max trades per day   → no more new entries
  3. Max concurrent pos.  → no more new entries
  4. Time blackout        → no entries in first/last N minutes
  5. Kill switch          → manual emergency stop (set via dashboard)

Usage:
    cb = CircuitBreaker()
    if not cb.allow_entry(symbol, direction, current_pnl, open_positions):
        return  # blocked
"""

from __future__ import annotations
import threading
from datetime import datetime, time
from typing import Optional

import pytz
from loguru import logger

from analytics import discord_notify as notify
from config.settings import (
    MARKET_OPEN, MARKET_CLOSE,
    BLACKOUT_OPEN_MINUTES, BLACKOUT_CLOSE_MINUTES,
    TRADING_CAPITAL,
)
from config.risk_profiles import ACTIVE, RiskProfile

IST = pytz.timezone("Asia/Kolkata")


class CircuitBreaker:
    """
    Singleton-safe circuit breaker. One instance per live session.
    All state resets at start of next trading day.
    """

    def __init__(self, capital: float = TRADING_CAPITAL, profile: RiskProfile = None):
        self.capital          = capital
        # Injected so the risk profile can be switched at runtime (dashboard)
        # without a module-global swap; falls back to the env-selected ACTIVE.
        self.risk             = profile or ACTIVE
        self._lock            = threading.Lock()
        self._kill_switch     = False       # manual emergency stop
        self._halted          = False       # triggered by daily loss
        self._halt_reason     = ""
        self._trades_today    = 0
        self._session_date    = None

    # ── Main gate ─────────────────────────────────────────────────────────────

    def allow_entry(
        self,
        symbol: str,
        session_pnl: float,
        open_position_count: int,
        now: Optional[datetime] = None,
    ) -> tuple[bool, str]:
        """
        Returns (allowed: bool, reason: str).
        Call this before placing any new entry order.
        """
        with self._lock:
            self._reset_if_new_day(now)

            if self._kill_switch:
                return False, "KILL_SWITCH_ACTIVE"

            if self._halted:
                return False, f"HALTED: {self._halt_reason}"

            # 1. Daily loss limit
            daily_loss_limit = self.capital * self.risk.max_daily_loss_pct / 100
            if session_pnl <= -daily_loss_limit:
                self._halted = True
                self._halt_reason = f"daily_loss_limit breached ({session_pnl:.0f})"
                logger.warning(f"CIRCUIT BREAKER: {self._halt_reason}")
                notify.alert(
                    "🛑 Circuit Breaker — Daily Loss Limit Hit",
                    f"Session P&L: ₹{session_pnl:,.0f}  |  Limit: ₹{-(self.capital * self.risk.max_daily_loss_pct / 100):,.0f}\nTrading halted for the rest of the day.",
                )
                return False, f"DAILY_LOSS_LIMIT: {session_pnl:.0f}"

            # 2. Max trades per day
            if self._trades_today >= self.risk.max_trades_per_day:
                return False, f"MAX_TRADES_PER_DAY ({self._trades_today}/{self.risk.max_trades_per_day})"

            # 3. Max concurrent positions
            if open_position_count >= self.risk.max_concurrent_positions:
                return False, f"MAX_CONCURRENT_POSITIONS ({open_position_count}/{self.risk.max_concurrent_positions})"

            # 4. Time blackout
            blackout, bl_reason = self._in_blackout(now)
            if blackout:
                return False, bl_reason

            return True, "OK"

    def record_entry(self) -> None:
        """Call when a trade is actually placed."""
        with self._lock:
            self._trades_today += 1

    def trigger_kill_switch(self, active: bool = True) -> None:
        """Activate or deactivate the manual kill switch (called from dashboard)."""
        with self._lock:
            self._kill_switch = active
            if active:
                logger.critical("KILL SWITCH ACTIVATED — all trading halted")
                notify.alert("🔴 KILL SWITCH ACTIVATED", "All trading has been halted manually.")
            else:
                logger.info("Kill switch deactivated")
                notify.log("Kill switch deactivated — trading resumed.", "INFO")

    def force_halt(self, reason: str) -> None:
        """
        Halt trading immediately for any reason (e.g. proactive daily-loss
        enforcement from the position monitor). Blocks all new entries until the
        next trading day or a manual reset.
        """
        with self._lock:
            self._halted      = True
            self._halt_reason = reason
            logger.critical(f"CIRCUIT BREAKER force-halt: {reason}")

    def reset_for_new_day(self) -> None:
        """Force-reset state for a new trading day (called by scheduler)."""
        with self._lock:
            self._halted       = False
            self._halt_reason  = ""
            self._trades_today = 0
            self._session_date = datetime.now(IST).date()
            logger.info("Circuit breaker reset for new session")

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            now_ist = datetime.now(IST)
            blackout, bl_reason = self._in_blackout(now_ist)
            return {
                "kill_switch":    self._kill_switch,
                "halted":         self._halted,
                "halt_reason":    self._halt_reason,
                "trades_today":   self._trades_today,
                "max_trades":     self.risk.max_trades_per_day,
                "in_blackout":    blackout,
                "blackout_reason": bl_reason,
                "session_date":   str(self._session_date),
            }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _reset_if_new_day(self, now: Optional[datetime]) -> None:
        """Auto-reset if it's a new trading day."""
        today = (now or datetime.now(IST)).date()
        if self._session_date != today:
            self._halted       = False
            self._halt_reason  = ""
            self._trades_today = 0
            self._session_date = today

    def _in_blackout(self, now: Optional[datetime]) -> tuple[bool, str]:
        """Check if current time is in the open or close blackout window."""
        now_ist = (now or datetime.now(IST)).astimezone(IST)
        now_time = now_ist.time()

        # Parse MARKET_OPEN and MARKET_CLOSE
        mo_h, mo_m = map(int, MARKET_OPEN.split(":"))
        mc_h, mc_m = map(int, MARKET_CLOSE.split(":"))
        market_open  = time(mo_h, mo_m)
        market_close = time(mc_h, mc_m)

        # Opening blackout: first N minutes after open. Use total-minute math so
        # BLACKOUT_OPEN_MINUTES >= 45 can't raise ValueError on minute overflow.
        open_end_min   = (mo_h * 60 + mo_m) + BLACKOUT_OPEN_MINUTES
        now_minutes    = now_time.hour * 60 + now_time.minute
        if (mo_h * 60 + mo_m) <= now_minutes < open_end_min:
            remaining = open_end_min - now_minutes
            return True, f"OPENING_BLACKOUT ({remaining}min remaining)"

        # Closing blackout: last N minutes before close
        close_blackout_start_min = (mc_h * 60 + mc_m) - BLACKOUT_CLOSE_MINUTES
        close_bl_h, close_bl_m   = divmod(close_blackout_start_min, 60)
        blackout_close_start     = time(close_bl_h, close_bl_m)
        if now_time >= blackout_close_start:
            return True, "CLOSING_BLACKOUT (force-exit zone)"

        # Outside market hours
        if now_time < market_open or now_time >= market_close:
            return True, "MARKET_CLOSED"

        return False, ""
