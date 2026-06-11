"""System control endpoints — kill switch, status, log stream, mode toggle, token refresh."""

from __future__ import annotations
import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config.settings import PAPER_TRADE, RISK_PROFILE, TRADING_CAPITAL, UPSTOX_MODE, DASHBOARD_TOKEN
from config.risk_profiles import get_profile, PROFILES
from config import control
from risk.circuit_breaker import CircuitBreaker
from analytics.pnl_tracker import PnLTracker

router = APIRouter()
_breaker     = CircuitBreaker()
_pnl_tracker = PnLTracker()

# Resolve .env path (project root)
_ENV_PATH = Path(__file__).parent.parent.parent.parent / ".env"
# system.py → .parent=routes/ → .parent=api/ → .parent=dashboard/ → .parent=AlgoTrading/


def _read_env() -> str:
    """Read .env as raw text, return empty string if file missing."""
    if _ENV_PATH.exists():
        return _ENV_PATH.read_text(encoding="utf-8")
    return ""


def _set_env_key(key: str, value: str) -> None:
    """Update or append a key=value pair in .env, preserving all other content."""
    text = _read_env()
    pattern = rf"^({re.escape(key)}\s*=).*$"
    replacement = f"{key}={value}"
    if re.search(pattern, text, flags=re.MULTILINE):
        text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\n{replacement}\n"
    _ENV_PATH.write_text(text, encoding="utf-8")
    # Also update os.environ so the running process reflects the change
    os.environ[key] = value

# In-memory log buffer for SSE stream
_log_buffer: list[dict] = []
MAX_LOG_LINES = 200


@router.get("/status")
def get_status():
    """Overall system status — displayed in dashboard header."""
    stats = _pnl_tracker.compute_daily_stats()
    # Read live .env values so UI reflects last-written state
    mode = os.environ.get("UPSTOX_MODE", UPSTOX_MODE)
    paper = os.environ.get("PAPER_TRADE", str(PAPER_TRADE)).lower() == "true"

    # Kill switch / trading-enabled come from the shared control plane — the
    # single source of truth the live runner actually obeys (issue CTRL-01).
    ctrl = control.read_control()

    # Live risk / capital: control-plane override → .env → import-time default.
    live_risk    = control.get_risk_profile() or os.environ.get("RISK_PROFILE", RISK_PROFILE)
    try:
        live_capital = control.get_capital()
        if live_capital is None:
            live_capital = float(os.environ.get("TRADING_CAPITAL", TRADING_CAPITAL))
    except (TypeError, ValueError):
        live_capital = float(TRADING_CAPITAL)
    try:
        profile = get_profile(live_risk)
    except ValueError:
        profile, live_risk = get_profile("LOW"), "LOW"

    cb = _breaker.status()
    cb["kill_switch_active"] = bool(ctrl.get("kill_switch", False))
    cb["daily_loss_limit"]   = round(live_capital * profile.max_daily_loss_pct / 100, 2)

    return {
        "timestamp":       datetime.utcnow().isoformat(),
        "upstox_mode":     mode,
        "paper_mode":      paper,
        "risk_profile":    live_risk,
        "capital":         live_capital,
        "auth_enabled":    bool(DASHBOARD_TOKEN),
        "trading_enabled": bool(ctrl.get("trading_enabled", True)),
        "circuit_breaker": cb,
        "today_pnl":       stats.get("net_pnl", stats.get("gross_pnl", 0)),
        "today_gross_pnl": stats.get("gross_pnl", 0),
        "today_costs":     stats.get("total_costs", 0),
        "today_trades":    stats.get("total_trades", 0),
        "today_win_rate":  stats.get("win_rate", 0),
        "control_updated": ctrl.get("updated_at"),
    }


class KillSwitchRequest(BaseModel):
    active: bool


@router.post("/kill-switch")
def toggle_kill_switch(req: KillSwitchRequest):
    """
    Activate / deactivate the kill switch. Writes to the control plane so the
    running trading engine picks it up and flattens/halts (issues CTRL-01/02).
    """
    control.set_kill_switch(req.active)
    _breaker.trigger_kill_switch(req.active)   # also reflect in this process's status
    return {
        "kill_switch": req.active,
        "message": "Kill switch activated — runner will flatten + halt"
                   if req.active else "Kill switch deactivated — entries may resume",
    }


class TradingRequest(BaseModel):
    enabled: bool


@router.get("/trading")
def get_trading():
    """Auto-trade master switch (pause new entries without flattening)."""
    return {"trading_enabled": control.is_trading_enabled()}


@router.post("/trading")
def set_trading(req: TradingRequest):
    """Pause / resume new entries. Open positions keep being managed."""
    control.set_trading_enabled(req.enabled)
    return {
        "trading_enabled": req.enabled,
        "message": "Auto-trading resumed" if req.enabled else "Auto-trading paused (entries suppressed)",
    }


@router.get("/control")
def get_control_state():
    """Return the full control-plane state (for the dashboard)."""
    return control.read_control()


# ── Risk profile + capital (editable from the dashboard header) ─────────────────

class RiskRequest(BaseModel):
    profile: str   # "LOW" | "MEDIUM" | "HIGH"


@router.post("/risk")
def set_risk(req: RiskRequest):
    """
    Change the active risk profile. Written to the control plane (the runner
    applies it live by swapping its sizer/breaker profile) AND persisted to .env
    so it survives a restart.
    """
    name = (req.profile or "").upper()
    if name not in PROFILES:
        raise HTTPException(status_code=400, detail="profile must be LOW, MEDIUM, or HIGH")
    control.set_risk_profile(name)
    _set_env_key("RISK_PROFILE", name)
    return {"risk_profile": name, "message": f"Risk profile → {name} (applied live + saved to .env)"}


class CapitalRequest(BaseModel):
    capital: float


@router.post("/capital")
def set_capital(req: CapitalRequest):
    """
    Set the trading capital. Written to the control plane (runner re-sizes live)
    AND persisted to .env. This is the capital used for sizing / risk limits — not
    the broker's actual funds (see /system/funds for that).
    """
    if req.capital is None or req.capital <= 0:
        raise HTTPException(status_code=400, detail="capital must be a positive number")
    cap = float(req.capital)
    control.set_capital(cap)
    _set_env_key("TRADING_CAPITAL", str(int(cap)) if cap.is_integer() else str(cap))
    return {"capital": cap, "message": f"Trading capital → ₹{cap:,.0f} (applied live + saved to .env)"}


@router.get("/funds")
def get_funds():
    """
    Actual broker funds from Upstox, routed via OpenAlgo (`/api/v1/funds`).
    Returns ``ok: false`` with a reason in paper/sandbox mode or when the broker
    can't be reached — the dashboard shows the configured capital in that case.
    """
    from live.openalgo_client import OpenAlgoClient
    client = OpenAlgoClient()
    funds = client.get_funds()
    if funds is None:
        reason = "paper mode — no broker funds" if client.paper_mode \
            else "broker funds unavailable (OpenAlgo not connected or no live token)"
        return {"ok": False, "available": None, "used": None, "total": None, "reason": reason}
    return {"ok": True, **funds}


@router.get("/log/stream")
async def log_stream():
    """Server-Sent Events stream of live log messages for the dashboard sidebar."""
    async def generate():
        sent = 0
        while True:
            if sent < len(_log_buffer):
                for entry in _log_buffer[sent:]:
                    yield f"data: {entry}\n\n"
                sent = len(_log_buffer)
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream")


def push_log(message: str, level: str = "INFO") -> None:
    """Push a log line to the SSE buffer (called from live/runner.py via loguru sink)."""
    import json
    entry = json.dumps({"ts": datetime.utcnow().isoformat(), "level": level, "msg": message})
    _log_buffer.append(entry)
    if len(_log_buffer) > MAX_LOG_LINES:
        _log_buffer.pop(0)


# ── Mode toggle ────────────────────────────────────────────────────────────────

class ModeRequest(BaseModel):
    mode: str          # "sandbox" | "live"
    paper_trade: bool  # always True unless user explicitly goes live


@router.post("/mode")
def set_mode(req: ModeRequest):
    """Switch between sandbox and live mode. Writes UPSTOX_MODE + PAPER_TRADE to .env."""
    if req.mode not in ("sandbox", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'sandbox' or 'live'")
    _set_env_key("UPSTOX_MODE", req.mode)
    _set_env_key("PAPER_TRADE", "true" if req.paper_trade else "false")
    return {
        "upstox_mode": req.mode,
        "paper_mode":  req.paper_trade,
        "message":     f"Switched to {req.mode.upper()} mode — restart trading runner to apply",
    }


@router.get("/mode")
def get_mode():
    """Return current UPSTOX_MODE and PAPER_TRADE from os.environ (reflects latest .env write)."""
    mode  = os.environ.get("UPSTOX_MODE", UPSTOX_MODE)
    paper = os.environ.get("PAPER_TRADE", str(PAPER_TRADE)).lower() == "true"
    return {"upstox_mode": mode, "paper_mode": paper}


# ── Live access token updater ──────────────────────────────────────────────────

class TokenRequest(BaseModel):
    callback_url: str   # full redirect URL Upstox sends back, e.g. http://127.0.0.1?code=xxx
    token_type: str = "live"  # "live" | "sandbox"


def _exchange_code_for_token(auth_code: str, token_type: str) -> str:
    """
    Exchange a one-time Upstox OAuth auth code for an access token.
    Reads credentials from the environment (LIVE_* or SANDBOX_* keys).
    Raises HTTPException on any failure so the caller gets a clean 400.
    """
    import httpx as _httpx

    prefix = "LIVE" if token_type == "live" else "SANDBOX"
    api_key    = os.environ.get(f"{prefix}_API_KEY", "")
    api_secret = os.environ.get(f"{prefix}_API_SECRET", "")
    redirect   = os.environ.get(f"{prefix}_REDIRECT_URI", "http://127.0.0.1")

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"{prefix}_API_KEY is not set in .env — cannot exchange auth code. "
                   f"Set it first, then retry.",
        )
    if not api_secret:
        raise HTTPException(
            status_code=400,
            detail=f"{prefix}_API_SECRET is not set in .env — cannot exchange auth code.",
        )

    try:
        resp = _httpx.post(
            "https://api.upstox.com/v2/login/authorization/token",
            data={
                "code":          auth_code,
                "client_id":     api_key,
                "client_secret": api_secret,
                "redirect_uri":  redirect,
                "grant_type":    "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstox unreachable: {exc}") from exc

    if not resp.is_success:
        # Surface the Upstox error message directly so the user knows what went wrong
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=400, detail=f"Upstox token exchange failed: {detail}")

    data = resp.json()
    access_token = data.get("access_token", "")
    if not access_token:
        raise HTTPException(
            status_code=400,
            detail=f"No access_token in Upstox response: {data}",
        )
    return access_token


@router.get("/auth-url")
def get_auth_url(token_type: str = "live"):
    """
    Return the Upstox OAuth authorization URL for the given token_type (live/sandbox).
    The frontend can't read .env, so the backend builds the URL with the correct API key.
    """
    if token_type not in ("live", "sandbox"):
        raise HTTPException(status_code=400, detail="token_type must be 'live' or 'sandbox'")
    prefix = "LIVE" if token_type == "live" else "SANDBOX"
    api_key  = os.environ.get(f"{prefix}_API_KEY", "")
    redirect = os.environ.get(f"{prefix}_REDIRECT_URI", "http://127.0.0.1")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"{prefix}_API_KEY not set in .env — cannot build auth URL.",
        )
    auth_url = (
        f"https://api.upstox.com/v2/login/authorization/dialog"
        f"?response_type=code&client_id={api_key}&redirect_uri={redirect}"
    )
    return {"auth_url": auth_url, "redirect_uri": redirect}


@router.post("/token")
def update_token(req: TokenRequest):
    """
    Accept the Upstox OAuth callback URL (or a raw token) and persist the
    access token to .env. Three input formats are supported:

      1. Full redirect URL with ?code=   → exchange auth code → get real token
      2. Full redirect URL with ?access_token=  → store directly
      3. Raw JWT / token string (no URL)  → store directly (sandbox shortcut)
    """
    if req.token_type not in ("live", "sandbox"):
        raise HTTPException(status_code=400, detail="token_type must be 'live' or 'sandbox'")

    url = req.callback_url.strip()
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    token: str | None = None

    if "access_token" in params:
        # Upstox returned token directly in URL (implicit flow)
        token = params["access_token"][0]

    elif "code" in params:
        # Standard authorization-code flow: exchange the code for a real token.
        auth_code = params["code"][0]
        token = _exchange_code_for_token(auth_code, req.token_type)

    else:
        # Not a URL — treat as a raw token string (common for sandbox paste)
        if len(url) > 20 and " " not in url and not url.startswith("http"):
            token = url
        else:
            raise HTTPException(
                status_code=400,
                detail="Could not find access_token or code in the URL. "
                       "Paste the full redirect URL (http://127.0.0.1?code=…) or the raw token.",
            )

    env_key = "LIVE_ACCESS_TOKEN" if req.token_type == "live" else "SANDBOX_ACCESS_TOKEN"
    _set_env_key(env_key, token)

    # Reflect in the running process immediately if this matches the active mode
    current_mode = os.environ.get("UPSTOX_MODE", UPSTOX_MODE)
    if (req.token_type == "live" and current_mode == "live") or \
       (req.token_type == "sandbox" and current_mode == "sandbox"):
        os.environ["UPSTOX_ACCESS_TOKEN"] = token

    return {
        "env_key":       env_key,
        "token_preview": token[:12] + "…" + token[-6:] if len(token) > 20 else token,
        "message":       f"{req.token_type.upper()} access token updated in .env",
    }
