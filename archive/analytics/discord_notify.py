"""
Discord Notification Module
Sends rich embed messages to different Discord channels via webhooks.

All functions are fire-and-forget (non-blocking via background thread).
If the webhook URL is blank, the call is silently skipped.

Usage:
    from analytics.discord_notify import notify
    notify.trade_entry("RELIANCE", "BUY", 150, 2950.0, 2910.0, 3020.0, 0.74)
    notify.trade_exit("RELIANCE", "BUY", 150, 2950.0, 3018.0, "TARGET_HIT", +10200.0)
    notify.daily_summary(stats_dict)
    notify.alert("Circuit breaker triggered — daily loss limit hit")
    notify.error("WebSocket disconnected", exc=e)
"""

from __future__ import annotations
import threading
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

from config.settings import (
    DISCORD_WEBHOOK_TRADES,
    DISCORD_WEBHOOK_EXITS,
    DISCORD_WEBHOOK_DAILY,
    DISCORD_WEBHOOK_ALERTS,
    DISCORD_WEBHOOK_ERRORS,
    DISCORD_WEBHOOK_LOGS,
    PAPER_TRADE,
    UPSTOX_SANDBOX,
)

# Discord embed colours
COLOR_GREEN  = 0x2ECC71   # entry / profit
COLOR_RED    = 0xE74C3C   # exit loss / alert
COLOR_BLUE   = 0x3498DB   # daily summary
COLOR_ORANGE = 0xE67E22   # warning / circuit breaker
COLOR_GREY   = 0x95A5A6   # log / info
COLOR_GOLD   = 0xF1C40F   # strong signal


def _mode_tag() -> str:
    if UPSTOX_SANDBOX:
        return "🧪 SANDBOX"
    if PAPER_TRADE:
        return "📄 PAPER"
    return "🔴 LIVE"


def _send(webhook_url: str, payload: dict) -> None:
    """Fire-and-forget POST to a Discord webhook."""
    if not webhook_url:
        return

    def _post():
        try:
            resp = httpx.post(webhook_url, json=payload, timeout=5)
            if resp.status_code not in (200, 204):
                logger.warning(f"Discord webhook returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Discord notify failed: {e}")

    threading.Thread(target=_post, daemon=True).start()


def _now_str() -> str:
    return datetime.now().strftime("%d %b %Y  %H:%M:%S")


# ── Public API ────────────────────────────────────────────────────────────────

def trade_entry(
    symbol:      str,
    side:        str,       # BUY / SELL
    qty:         int,
    entry_price: float,
    sl_price:    float,
    target_price: float,
    score:       float,
    strategy:    str = "ensemble",
    regime:      str = "",
) -> None:
    """Send a trade entry notification to #trade-entries."""
    direction_emoji = "📈" if side == "BUY" else "📉"
    risk_amt   = abs(entry_price - sl_price) * qty
    reward_amt = abs(target_price - entry_price) * qty
    rr_ratio   = reward_amt / risk_amt if risk_amt > 0 else 0

    payload = {
        "embeds": [{
            "title":       f"{direction_emoji} ENTRY — {symbol}",
            "color":       COLOR_GREEN if side == "BUY" else COLOR_RED,
            "description": f"`{_mode_tag()}`  |  Strategy: **{strategy}**",
            "fields": [
                {"name": "Side",         "value": f"**{side}**",                    "inline": True},
                {"name": "Qty",          "value": f"{qty}",                         "inline": True},
                {"name": "Entry",        "value": f"₹{entry_price:,.2f}",           "inline": True},
                {"name": "Stop-Loss",    "value": f"₹{sl_price:,.2f}",              "inline": True},
                {"name": "Target",       "value": f"₹{target_price:,.2f}",          "inline": True},
                {"name": "R:R",          "value": f"{rr_ratio:.1f}x",               "inline": True},
                {"name": "Signal Score", "value": f"{score:+.3f}",                  "inline": True},
                {"name": "Regime",       "value": regime or "—",                    "inline": True},
            ],
            "footer": {"text": _now_str()},
        }]
    }
    _send(DISCORD_WEBHOOK_TRADES, payload)


def trade_exit(
    symbol:      str,
    side:        str,
    qty:         int,
    entry_price: float,
    exit_price:  float,
    reason:      str,       # SL_HIT / TARGET_HIT / EOD_SQUAREOFF / SIGNAL_REVERSAL
    pnl:         float,
    hold_minutes: float = 0,
) -> None:
    """Send a trade exit notification to #trade-exits."""
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    color     = COLOR_GREEN if pnl >= 0 else COLOR_RED
    pnl_pct   = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
    if side == "SELL":
        pnl_pct = -pnl_pct

    payload = {
        "embeds": [{
            "title":       f"{pnl_emoji} EXIT — {symbol}  ({reason})",
            "color":       color,
            "description": f"`{_mode_tag()}`",
            "fields": [
                {"name": "Side",          "value": side,                             "inline": True},
                {"name": "Qty",           "value": str(qty),                         "inline": True},
                {"name": "Entry → Exit",  "value": f"₹{entry_price:,.2f} → ₹{exit_price:,.2f}", "inline": True},
                {"name": "P&L",           "value": f"**₹{pnl:+,.2f}  ({pnl_pct:+.2f}%)**",     "inline": True},
                {"name": "Hold Time",     "value": f"{hold_minutes:.0f} min",        "inline": True},
                {"name": "Exit Reason",   "value": reason,                           "inline": True},
            ],
            "footer": {"text": _now_str()},
        }]
    }
    _send(DISCORD_WEBHOOK_EXITS, payload)


def daily_summary(stats: dict) -> None:
    """Send EOD daily summary to #daily-summary."""
    pnl        = stats.get("gross_pnl", 0)
    net_pnl    = stats.get("net_pnl", 0)
    win_rate   = stats.get("win_rate", 0) * 100
    trades     = stats.get("total_trades", 0)
    wins       = stats.get("wins", 0)
    losses     = stats.get("losses", 0)
    best       = stats.get("best_trade", 0)
    worst      = stats.get("worst_trade", 0)
    sharpe     = stats.get("sharpe_rolling", 0)
    cap_end    = stats.get("capital_end", 0)
    trade_date = stats.get("date", datetime.today().strftime("%Y-%m-%d"))

    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    color     = COLOR_GREEN if pnl >= 0 else COLOR_RED

    # Charges estimate: ~0.05% brokerage + 0.1% STT (sell side) + misc
    charges_est = abs(pnl * 0.002)

    payload = {
        "embeds": [{
            "title":       f"📊 Daily Summary — {trade_date}",
            "color":       color,
            "description": f"`{_mode_tag()}`  |  {pnl_emoji} Net P&L: **₹{net_pnl:+,.2f}**",
            "fields": [
                {"name": "Gross P&L",      "value": f"₹{pnl:+,.2f}",                "inline": True},
                {"name": "Est. Charges",   "value": f"₹{charges_est:,.2f}",          "inline": True},
                {"name": "Net P&L",        "value": f"**₹{net_pnl:+,.2f}**",         "inline": True},
                {"name": "Trades",         "value": f"{trades}  ({wins}W / {losses}L)", "inline": True},
                {"name": "Win Rate",       "value": f"{win_rate:.1f}%",              "inline": True},
                {"name": "Sharpe (20d)",   "value": f"{sharpe:.2f}",                 "inline": True},
                {"name": "Best Trade",     "value": f"₹{best:+,.2f}",               "inline": True},
                {"name": "Worst Trade",    "value": f"₹{worst:+,.2f}",              "inline": True},
                {"name": "Capital (EOD)",  "value": f"₹{cap_end:,.0f}",             "inline": True},
            ],
            "footer": {"text": f"AlgoTrading  •  {_now_str()}"},
        }]
    }
    _send(DISCORD_WEBHOOK_DAILY, payload)


def alert(message: str, detail: str = "") -> None:
    """Send a risk/circuit breaker alert to #alerts."""
    payload = {
        "embeds": [{
            "title":       "⚠️ ALERT",
            "color":       COLOR_ORANGE,
            "description": f"`{_mode_tag()}`\n**{message}**",
            "fields":      [{"name": "Detail", "value": detail, "inline": False}] if detail else [],
            "footer":      {"text": _now_str()},
        }]
    }
    _send(DISCORD_WEBHOOK_ALERTS, payload)


def error(message: str, exc: Optional[Exception] = None) -> None:
    """Send an error/exception to #errors."""
    detail = f"```{type(exc).__name__}: {exc}```" if exc else ""
    payload = {
        "embeds": [{
            "title":       "🚨 ERROR",
            "color":       COLOR_RED,
            "description": f"`{_mode_tag()}`\n**{message}**\n{detail}",
            "footer":      {"text": _now_str()},
        }]
    }
    _send(DISCORD_WEBHOOK_ERRORS, payload)


def log(message: str, level: str = "INFO") -> None:
    """Send a verbose log line to #system-logs (optional channel)."""
    icons = {"INFO": "ℹ️", "WARNING": "⚠️", "SUCCESS": "✅", "DEBUG": "🔍"}
    icon  = icons.get(level, "•")
    payload = {
        "embeds": [{
            "title":       f"{icon} {level}",
            "color":       COLOR_GREY,
            "description": message,
            "footer":      {"text": _now_str()},
        }]
    }
    _send(DISCORD_WEBHOOK_LOGS, payload)


def test_all_channels() -> None:
    """
    Send a test message to every configured channel.
    Run this after setting up your webhooks to confirm they all work.
    
    Usage:
        python -c "from analytics.discord_notify import test_all_channels; test_all_channels()"
    """
    import time

    print("Sending test messages to all configured Discord channels...")

    trade_entry("RELIANCE", "BUY", 150, 2950.0, 2910.0, 3025.0, 0.74, "ensemble", "TRENDING_UP")
    time.sleep(0.5)

    trade_exit("RELIANCE", "BUY", 150, 2950.0, 3020.0, "TARGET_HIT", +10_500.0, hold_minutes=47)
    time.sleep(0.5)

    daily_summary({
        "date": datetime.today().strftime("%Y-%m-%d"),
        "gross_pnl": 18500.0, "net_pnl": 17800.0,
        "total_trades": 6, "wins": 4, "losses": 2,
        "win_rate": 0.667, "best_trade": 10500.0, "worst_trade": -3200.0,
        "sharpe_rolling": 1.82, "capital_end": 117800.0,
    })
    time.sleep(0.5)

    alert("Circuit breaker triggered", "Daily loss limit of ₹5,000 breached at 11:32 IST")
    time.sleep(0.5)

    error("WebSocket disconnected", exc=ConnectionError("Connection reset by peer"))
    time.sleep(0.5)

    log("System started. Watching 10 instruments on 5min timeframe.", "INFO")

    time.sleep(1)
    print("Done. Check your Discord channels.")
