"""
Action Replay endpoints.

Full-fidelity single-day replay of the live strategy (see replay/engine.py).
A run is kicked off in the background; the UI polls /status for progress and
/result for the finished event stream + trades + universe + PnL.

Routes:
  POST /api/replay/run        {date, capital?, risk_profile?, use_ml_gates?}
  GET  /api/replay/status     -> {state, progress, message, run_id, date}
  GET  /api/replay/result     -> full result dict (or {message} if none yet)
  GET  /api/replay/history    -> recent saved replay runs (from replay/results)
"""

from __future__ import annotations

import json
import threading
from datetime import date

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from loguru import logger

router = APIRouter()

# In-memory single-run state (one replay at a time, like the backtest page).
_lock = threading.Lock()
_state: dict = {"state": "idle", "progress": 0.0, "message": "", "run_id": None, "date": None}
_result: dict = {}


class ReplayRequest(BaseModel):
    date: str                            # 'YYYY-MM-DD' (IST session date)
    capital: float | None = None
    risk_profile: str | None = None      # LOW / MEDIUM / HIGH
    use_ml_gates: bool = True
    use_margin: bool = False             # scale position size using MIS margin multipliers


@router.post("/run")
def run_replay(req: ReplayRequest, background_tasks: BackgroundTasks):
    with _lock:
        if _state["state"] == "running":
            return {"message": "A replay is already running", "state": _state}
        # Validate the date early so the user gets immediate feedback.
        try:
            date.fromisoformat(req.date)
        except ValueError:
            return {"message": f"Invalid date '{req.date}' (expected YYYY-MM-DD)"}
        _state.update({"state": "running", "progress": 0.0,
                       "message": "Starting…", "run_id": None, "date": req.date})
    background_tasks.add_task(_run_task, req)
    return {"message": "Replay started", "params": req.model_dump()}


@router.get("/status")
def get_status():
    with _lock:
        return dict(_state)


@router.get("/result")
def get_result():
    with _lock:
        return _result if _result else {"message": "No replay run yet"}


@router.get("/history")
def get_history(limit: int = 20):
    from replay.engine import RESULTS_DIR
    if not RESULTS_DIR.exists():
        return []
    out = []
    for p in sorted(RESULTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "run_id": d.get("run_id"),
                "date": d.get("date"),
                "summary": d.get("summary", {}),
                "params": d.get("params", {}),
                "file": p.name,
            })
        except Exception:
            continue
    return out


def _run_task(req: ReplayRequest) -> None:
    global _result
    from replay.engine import ReplayEngine

    def _progress(frac: float, msg: str) -> None:
        with _lock:
            _state["progress"] = round(float(frac), 3)
            _state["message"] = msg

    try:
        engine = ReplayEngine(
            capital=req.capital or _default_capital(),
            risk_profile=req.risk_profile,
            use_ml_gates=req.use_ml_gates,
            use_margin=req.use_margin,
        )
        result = engine.run(req.date, progress=_progress)
        with _lock:
            _result = result
            _state.update({"state": "done", "progress": 1.0,
                           "message": "Complete", "run_id": result.get("run_id"),
                           "date": result.get("date")})
        logger.success(f"Action Replay done: {req.date} "
                       f"trades={result.get('summary', {}).get('total_trades')}")
    except Exception as e:
        logger.exception(f"Action Replay failed: {e}")
        with _lock:
            _result = {"error": str(e)}
            _state.update({"state": "error", "message": str(e)})


def _default_capital() -> float:
    from config.settings import TRADING_CAPITAL
    return TRADING_CAPITAL
