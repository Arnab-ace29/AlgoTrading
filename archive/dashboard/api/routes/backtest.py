"""Backtest trigger and results endpoints."""

from __future__ import annotations
import json

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from loguru import logger

from config.settings import INSTRUMENTS
from data.db import execute_query, record_backtest_run, to_records

router = APIRouter()

# The backtest engine pulls in vectorbt (heavy). Import it lazily so the dashboard
# API boots — and serves trades/positions/roadmap — without the backtest stack
# installed. vectorbt is only needed when a backtest actually runs.
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from backtest.engine import BacktestEngine
        _engine = BacktestEngine()
    return _engine


# In-memory store of last backtest result (simplified for Phase 1)
_last_result: dict = {}


class BacktestRequest(BaseModel):
    symbols:      list[str] = INSTRUMENTS[:3]
    from_date:    str = "2024-01-01"
    to_date:      str = "2025-01-01"
    walk_forward: bool = True
    n_folds:      int = 5


@router.post("/run")
def run_backtest(req: BacktestRequest, background_tasks: BackgroundTasks):
    """Trigger a backtest run in the background."""
    background_tasks.add_task(_run_backtest_task, req)
    return {"message": "Backtest started", "params": req.model_dump()}


@router.get("/results")
def get_last_result():
    """Return the last completed backtest result."""
    return _last_result if _last_result else {"message": "No backtest run yet"}


@router.get("/history")
def get_backtest_history(limit: int = 20):
    """Return historical backtest run registry."""
    df = execute_query("SELECT * FROM backtest_runs ORDER BY run_time DESC LIMIT ?", [limit])
    return to_records(df)


def _run_backtest_task(req: BacktestRequest) -> None:
    global _last_result
    try:
        result = _get_engine().run(
            symbols=req.symbols,
            from_date=req.from_date,
            to_date=req.to_date,
            walk_forward=req.walk_forward,
            n_folds=req.n_folds,
        )
        result.save()                 # writes JSON/CSV and sets result_path
        summary = result.summary()    # now includes run_id + result_path
        _last_result = summary

        # Persist to backtest_runs so /history populates (issue UI-02).
        record_backtest_run({
            "run_id":       result.run_id,
            "strategy":     "ensemble",
            "symbols":      ",".join(req.symbols),
            "from_date":    req.from_date,
            "to_date":      req.to_date,
            "sharpe":       summary.get("sharpe"),
            "total_return": summary.get("total_return"),
            "max_drawdown": summary.get("max_drawdown"),
            "win_rate":     summary.get("win_rate"),
            "total_trades": summary.get("total_trades"),
            "params_json":  json.dumps(req.model_dump()),
            "result_path":  result.result_path,
        })
    except Exception as e:
        logger.error(f"Backtest task failed: {e}")
        _last_result = {"error": str(e)}
