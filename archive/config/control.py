"""
Cross-process control plane.

The dashboard API and the live runner are SEPARATE processes. The operational
store (SQLite WAL) now supports concurrent cross-process access (LIVE-06), but
live *control* intents (kill switch, pause, weights) are deliberately kept in a
small JSON file rather than the trade DB: they're tiny, frequently polled, and
shouldn't contend with trade/candle writes. The dashboard writes intents here and
the runner polls the file at the top of every loop and applies them.

This is what makes the dashboard kill switch / pause / weight sliders actually
affect live trading (issue CTRL-01).

Keys:
  kill_switch      bool  — emergency stop: block new entries AND flatten open positions
  trading_enabled  bool  — master auto-trade switch; pause new entries without flattening
  weights_override dict  — {signal_name: weight} applied to the live ensemble
  disabled_signals list  — signal names to run in shadow mode (computed, not traded)
  updated_at       str   — ISO timestamp of the last write (for the UI)
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

from config.settings import ROOT_DIR

CONTROL_PATH = ROOT_DIR / "config" / "control_state.json"
_lock = threading.Lock()

_DEFAULTS: dict = {
    "kill_switch":      False,
    "trading_enabled":  True,
    "weights_override": {},
    "disabled_signals": [],
    "risk_profile":     None,    # None → use the env/default profile; "LOW"|"MEDIUM"|"HIGH" overrides it live
    "capital":          None,    # None → use TRADING_CAPITAL; a positive number overrides it live
    "updated_at":       None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_control() -> dict:
    """Return the current control state, merged over defaults. Never raises."""
    with _lock:
        data: dict = {}
        if CONTROL_PATH.exists():
            try:
                data = json.loads(CONTROL_PATH.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {}
    merged = dict(_DEFAULTS)
    merged.update(data)
    return merged


def write_control(updates: dict) -> dict:
    """Merge `updates` into the control state and persist atomically."""
    with _lock:
        current = dict(_DEFAULTS)
        if CONTROL_PATH.exists():
            try:
                current.update(json.loads(CONTROL_PATH.read_text(encoding="utf-8")) or {})
            except Exception:
                pass
        current.update(updates)
        current["updated_at"] = _now()
        CONTROL_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONTROL_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        os.replace(tmp, CONTROL_PATH)   # atomic on POSIX + Windows
    return current


# ── Convenience accessors (used by API + runner) ──────────────────────────────

def is_kill_switch() -> bool:
    return bool(read_control().get("kill_switch", False))


def set_kill_switch(active: bool) -> dict:
    return write_control({"kill_switch": bool(active)})


def is_trading_enabled() -> bool:
    return bool(read_control().get("trading_enabled", True))


def set_trading_enabled(enabled: bool) -> dict:
    return write_control({"trading_enabled": bool(enabled)})


def get_weights_override() -> dict:
    return dict(read_control().get("weights_override") or {})


def set_weights_override(weights: dict) -> dict:
    return write_control({"weights_override": {k: float(v) for k, v in (weights or {}).items()}})


def get_disabled_signals() -> list:
    return list(read_control().get("disabled_signals") or [])


def set_disabled_signals(names: list) -> dict:
    return write_control({"disabled_signals": list(names or [])})


def get_risk_profile() -> str | None:
    """Live risk-profile override ('LOW'|'MEDIUM'|'HIGH'), or None to use the default."""
    v = read_control().get("risk_profile")
    return v.upper() if isinstance(v, str) and v else None


def set_risk_profile(name: str | None) -> dict:
    return write_control({"risk_profile": name.upper() if name else None})


def get_capital() -> float | None:
    """Live capital override, or None to use TRADING_CAPITAL."""
    v = read_control().get("capital")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def set_capital(amount: float | None) -> dict:
    return write_control({"capital": float(amount) if amount is not None else None})
