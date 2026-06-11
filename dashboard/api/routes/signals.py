"""Signal control and scanner endpoints."""

from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

from config.settings import INSTRUMENTS, TIMEFRAME_PRIMARY
from config import control
from data.db import read_candles
from features.indicators import compute_all_features
from ensemble.aggregator import EnsembleAggregator

router = APIRouter()
_aggregator = EnsembleAggregator()


class WeightUpdate(BaseModel):
    weights: dict[str, float]


class SignalToggle(BaseModel):
    signal_name: str
    enabled: bool


@router.get("/weights")
def get_weights():
    """Return current signal weights."""
    return _aggregator.base_weights


@router.post("/weights")
def update_weights(update: WeightUpdate):
    """Update signal weights — applied here and pushed to the live runner (CTRL-01)."""
    _aggregator.update_weights(update.weights)
    control.set_weights_override(update.weights)
    return {"updated": update.weights}


@router.post("/toggle")
def toggle_signal(toggle: SignalToggle):
    """Enable or disable a signal — persisted to the control plane for the runner."""
    _aggregator.set_signal_enabled(toggle.signal_name, toggle.enabled)
    disabled = set(control.get_disabled_signals())
    if toggle.enabled:
        disabled.discard(toggle.signal_name)
    else:
        disabled.add(toggle.signal_name)
    control.set_disabled_signals(sorted(disabled))
    return {"signal": toggle.signal_name, "enabled": toggle.enabled, "disabled": sorted(disabled)}


@router.get("/scan")
def run_scanner(symbols: Optional[str] = Query(default=None)):
    """
    Run signals on all instruments and return current scores.
    Used by the Live Signal Scanner page.
    """
    sym_list = symbols.split(",") if symbols else list(INSTRUMENTS)
    results = []
    for symbol in sym_list:
        df = read_candles(symbol, TIMEFRAME_PRIMARY, limit=150)
        if df.empty or len(df) < 60:
            continue
        df = df.set_index("timestamp")
        df = compute_all_features(df)
        result = _aggregator.compute(df, symbol)
        results.append(result.to_dict())

    results.sort(key=lambda x: abs(x["composite_score"]), reverse=True)
    return results
