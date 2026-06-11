"""
FastAPI backend for the AlgoTrading dashboard.
Runs on port 8000. React frontend (port 5173) proxies /api/* to this.

Start:
    uvicorn dashboard.api.main:app --reload --port 8000
"""

from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import DASHBOARD_TOKEN
from data.db import init_db
from dashboard.api.routes import system, trades, positions, signals, backtest, features, models, analytics, replay


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AlgoTrading API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth (SEC-01) ──────────────────────────────────────────────────────────────
# Every state-changing request (POST/PUT/PATCH/DELETE) must carry the shared secret
# in `X-API-Key` once DASHBOARD_TOKEN is set. Read-only GETs and CORS preflight stay
# open so the dashboard can render. When DASHBOARD_TOKEN is empty, auth is disabled
# (localhost-dev convenience) — set it before exposing the dashboard anywhere else.
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def require_token(request: Request, call_next):
    if DASHBOARD_TOKEN and request.method in _MUTATING:
        if request.headers.get("x-api-key") != DASHBOARD_TOKEN:
            return JSONResponse({"detail": "invalid or missing X-API-Key"}, status_code=401)
    return await call_next(request)


if not DASHBOARD_TOKEN:
    import warnings
    warnings.warn("DASHBOARD_TOKEN not set — dashboard mutating routes are UNAUTHENTICATED "
                  "(ok for localhost; set it before exposing the dashboard).")

app.include_router(system.router,   prefix="/api/system",   tags=["system"])
app.include_router(trades.router,   prefix="/api/trades",   tags=["trades"])
app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(signals.router,  prefix="/api/signals",  tags=["signals"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(features.router, prefix="/api/features", tags=["features"])
app.include_router(models.router,   prefix="/api/models",   tags=["models"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(replay.router,   prefix="/api/replay",   tags=["replay"])


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "algotrading-api"}
