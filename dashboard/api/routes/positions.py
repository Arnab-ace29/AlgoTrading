"""Open positions and order status endpoints (proxied from OpenAlgo)."""

from __future__ import annotations
from fastapi import APIRouter

from data.db import get_open_trades, to_records
from live.openalgo_client import OpenAlgoClient

router = APIRouter()
_client = OpenAlgoClient()


@router.get("/open")
def get_open_positions():
    """Return currently open positions from our DB."""
    return to_records(get_open_trades())


@router.get("/broker")
def get_broker_positions():
    """Fetch live positions from OpenAlgo / broker."""
    return _client.get_positions()


@router.post("/close-all")
def close_all_positions():
    """Emergency close all positions (kill switch support)."""
    results = _client.close_all_positions()
    return {"closed": len(results), "results": [r.__dict__ for r in results]}
