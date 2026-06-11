"""Model status endpoints — backs the dashboard AI Models page (replaces missing /api/rl/status)."""

from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter

from config.settings import MODELS_DIR
from data.db import execute_query, to_records

router = APIRouter()

# Expected model artifacts and a human label for each.
_EXPECTED = [
    ("macro_xgb.pkl",        "Macro XGBoost",       "Directional gate — P(+0.1% in 15m)"),
    ("micro_xgb.pkl",        "Micro XGBoost",       "Entry confirmation — buying pressure"),
    ("strategy_outcomes.pkl","Strategy Outcomes",   "P(win) gate per strategy (needs ≥15 trades)"),
    ("rl_exit_agent.pkl",    "RL Exit Agent",       "Q-learning exit timing"),
    ("rl_entry_agent.pkl",   "RL Entry Agent",      "Q-learning enter / skip"),
]


@router.get("/status")
def model_status():
    """Report saved-model presence + last training metrics for each model."""
    models = []
    for fname, label, desc in _EXPECTED:
        path = MODELS_DIR / fname
        exists = path.exists()
        info = {
            "file":        fname,
            "label":       label,
            "description": desc,
            "loaded":      exists,
            "size_kb":     round(path.stat().st_size / 1024, 1) if exists else 0,
            "modified":    datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat() if exists else None,
        }
        models.append(info)

    # Last training metrics, if the training log has rows.
    try:
        log = to_records(execute_query(
            "SELECT * FROM model_training_log ORDER BY run_time DESC LIMIT 20"
        ))
    except Exception:
        log = []

    loaded = sum(1 for m in models if m["loaded"])
    return {
        "models":        models,
        "loaded_count":  loaded,
        "total_count":   len(models),
        "training_log":  log,
        "models_dir":    str(MODELS_DIR),
    }
