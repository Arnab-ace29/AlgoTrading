"""
Central configuration for the AlgoTrading system.
All constants, thresholds, weights, and instrument lists live here.
Edit this file to tune the system — do NOT hardcode values elsewhere.
"""

from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent
# SQLite (WAL) operational store. (.sqlite to avoid colliding with any legacy DuckDB .db file.)
DB_PATH  = ROOT_DIR / os.getenv("DB_PATH", "data/algo_trading.sqlite")
LOGS_DIR = ROOT_DIR / "logs"
MODELS_DIR = ROOT_DIR / "models" / "saved"
BACKTEST_RESULTS_DIR = ROOT_DIR / "backtest" / "results"
DAILY_WATCHLIST_PATH = ROOT_DIR / "config" / "daily_watchlist.json"

# ── Capital & Mode ────────────────────────────────────────────────────────────
TRADING_CAPITAL: float = float(os.getenv("TRADING_CAPITAL", 100_000))
PAPER_TRADE: bool      = os.getenv("PAPER_TRADE", "true").lower() == "true"
RISK_PROFILE: str      = os.getenv("RISK_PROFILE", "LOW")  # LOW / MEDIUM / HIGH

# ── MIS Margin leverage ────────────────────────────────────────────────────────
# When USE_MARGIN=true, the position sizer scales up qty using the broker's
# intraday (MIS) margin multiplier for each stock (from data/margin_multipliers.json).
# MAX_MIS_LEVERAGE caps how much leverage is applied regardless of what the broker allows.
# Populate the cache first: python scripts/fetch_margin_multipliers.py (needs live token).
USE_MARGIN:       bool  = os.getenv("USE_MARGIN", "false").lower() == "true"
MAX_MIS_LEVERAGE: float = float(os.getenv("MAX_MIS_LEVERAGE", "5.0"))

# ── Instruments ───────────────────────────────────────────────────────────────
# Phase 1 watchlist — highly liquid Nifty 50 stocks
INSTRUMENTS: list[str] = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "AXISBANK", "WIPRO", "HINDUNILVR", "BAJFINANCE",
]

# Upstox instrument keys for the above (NSE_EQ|ISIN format)
INSTRUMENT_KEYS: dict[str, str] = {
    "RELIANCE":    "NSE_EQ|INE002A01018",
    "TCS":         "NSE_EQ|INE467B01029",
    "INFY":        "NSE_EQ|INE009A01021",
    "HDFCBANK":    "NSE_EQ|INE040A01034",
    "ICICIBANK":   "NSE_EQ|INE090A01021",
    "SBIN":        "NSE_EQ|INE062A01020",
    "AXISBANK":    "NSE_EQ|INE238A01034",
    "WIPRO":       "NSE_EQ|INE075A01022",
    "HINDUNILVR":  "NSE_EQ|INE030A01027",
    "BAJFINANCE":  "NSE_EQ|INE296A01032",
    # Index (for regime detection + VIX)
    "NIFTY50":     "NSE_INDEX|Nifty 50",
    "INDIAVIX":    "NSE_INDEX|India VIX",
}

# ── Timeframes ────────────────────────────────────────────────────────────────
TIMEFRAME_PRIMARY: str        = "5min"
TIMEFRAMES_STORE: list[str]   = ["1min", "5min", "15min"]
CANDLE_LOOKBACK_DAYS: int     = 365      # days of history to backfill

# ── Trading Session ───────────────────────────────────────────────────────────
MARKET_OPEN:  str  = "09:15"
MARKET_CLOSE: str  = "15:30"
BLACKOUT_OPEN_MINUTES: int  = 15    # no entries 9:15–9:30 (opening volatility)
BLACKOUT_CLOSE_MINUTES: int = 30    # no entries 15:00–15:30 (force exit zone)
EOD_SQUAREOFF_TIME: str     = "15:25"  # force-close all positions before this

# ── Signal Thresholds ─────────────────────────────────────────────────────────
SCORE_THRESHOLD_SIGNAL: float = 0.45   # minimum to show as "active" in dashboard
SCORE_THRESHOLD_ENTRY: float  = 0.55   # composite ≥ this → direction is LONG/SHORT (signal is "live")
SCORE_THRESHOLD_STRONG: float = 0.70   # = the 2-lot tier boundary (see score-tiered lots below)

# ── Score-tiered lot bands (docs/SIGNALS.md → Position Sizing) ─────────────────
# The single source of truth for how composite score maps to lots. Drives
# ensemble/position_sizing.PositionSizer; keep in sync with the SIGNALS.md table.
#   0.55–0.65 → signal only (NO trade)
#   0.65–0.70 → 1 lot   (reduced to 0 in CHOPPY)
#   0.70–0.75 → 2 lots
#   ≥ 0.75    → 3 lots  (all capped by the risk profile's lot_size_cap)
SCORE_TIER_TRADE: float = 0.65         # min score to actually trade (below = signal only)
SCORE_TIER_2LOT:  float = SCORE_THRESHOLD_STRONG  # 0.70
SCORE_TIER_3LOT:  float = 0.75         # ≥ this → 3 lots (capped by risk profile)

# ── Correlation / sector exposure guard (EDGE-03) ─────────────────────────────
# Cap how much of the book can sit in one sector / correlated cluster, on top of the
# circuit breaker's global concurrency cap (a "max 3 positions" cap can still be 3
# banks). Sector cap is cheap + always on; the correlation check is opt-in.
SECTOR_GUARD_ENABLED:   bool  = os.getenv("SECTOR_GUARD_ENABLED", "true").lower() == "true"
MAX_POSITIONS_PER_SECTOR: int = int(os.getenv("MAX_POSITIONS_PER_SECTOR", 2))
CORRELATION_THRESHOLD:  float = float(os.getenv("CORRELATION_THRESHOLD", 0.75))
CORRELATION_LOOKBACK:   int   = int(os.getenv("CORRELATION_LOOKBACK", 60))

# ── ML gates (Phase 2) ────────────────────────────────────────────────────────
# A model may only VETO a rule-based entry once it has demonstrated at least this
# out-of-sample AUC on its held-out validation fold. Below this bar the model has
# no proven edge, so it stays advisory (is_reliable=False) and the rule-based
# system trades unimpeded — a weak/under-trained model can't silently suppress
# trading. 0.50 = coin flip; 0.53 demands a small but real edge.
ML_GATE_MIN_AUC: float = 0.53

# ── Phase 1 Signal Weights (sum must equal 1.0) ───────────────────────────────
SIGNAL_WEIGHTS: dict[str, float] = {
    "vwap_breakout":  0.40,
    "rsi_momentum":   0.35,
    "mean_reversion": 0.25,
}

# ── Ensemble ──────────────────────────────────────────────────────────────────
REGIME_WEIGHT_MAP: dict[str, dict[str, float]] = {
    "TRENDING_UP":    {"vwap_breakout": 0.50, "rsi_momentum": 0.40, "mean_reversion": 0.10},
    "TRENDING_DOWN":  {"vwap_breakout": 0.50, "rsi_momentum": 0.40, "mean_reversion": 0.10},
    "MEAN_REVERTING": {"vwap_breakout": 0.10, "rsi_momentum": 0.20, "mean_reversion": 0.70},
    "CHOPPY":         {"vwap_breakout": 0.33, "rsi_momentum": 0.33, "mean_reversion": 0.34},
}

# ── Backtest ──────────────────────────────────────────────────────────────────
BACKTEST_COMMISSION: float  = 0.0005   # 0.05% per side (slippage + STT + brokerage)
BACKTEST_SLIPPAGE:   float  = 0.0003   # additional slippage model

# ── Screener ──────────────────────────────────────────────────────────────────
SCREENER_TOP_N: int = 10               # how many stocks to select per strategy daily
SCREENER_LOOKBACK_DAYS: int = 120      # daily history used for ranking features

# ── Upstox — dual credential support ─────────────────────────────────────────
# Switch between sandbox and live by changing UPSTOX_MODE in .env only.
# Never comment/uncomment credentials manually.
UPSTOX_MODE: str = os.getenv("UPSTOX_MODE", "sandbox").lower()   # "sandbox" | "live"
UPSTOX_SANDBOX: bool = (UPSTOX_MODE == "sandbox")                 # backward compat flag

if UPSTOX_MODE == "live":
    UPSTOX_API_KEY      = os.getenv("LIVE_API_KEY", "")
    UPSTOX_API_SECRET   = os.getenv("LIVE_API_SECRET", "")
    UPSTOX_REDIRECT_URI = os.getenv("LIVE_REDIRECT_URI", "http://127.0.0.1")
    UPSTOX_ACCESS_TOKEN = os.getenv("LIVE_ACCESS_TOKEN", "")
else:  # sandbox (default)
    UPSTOX_API_KEY      = os.getenv("SANDBOX_API_KEY", "")
    UPSTOX_API_SECRET   = os.getenv("SANDBOX_API_SECRET", "")
    UPSTOX_REDIRECT_URI = os.getenv("SANDBOX_REDIRECT_URI", "http://127.0.0.1")
    UPSTOX_ACCESS_TOKEN = os.getenv("SANDBOX_ACCESS_TOKEN", "")

UPSTOX_BASE_URL: str = "https://api.upstox.com"  # same for both modes

# Analytics Token — 1-year lifetime, read-only (historical + market data, no orders).
# Preferred for all unattended backfill / screener jobs — never expires mid-run.
# Generate at: developer.upstox.com → Analytics tab → Generate Token.
ANALYTICS_TOKEN: str = os.getenv("ANALYTICS_TOKEN", "")

# ── OpenAlgo ──────────────────────────────────────────────────────────────────
OPENALGO_HOST:    str = os.getenv("OPENALGO_HOST", "http://127.0.0.1:3000")
OPENALGO_API_KEY: str = os.getenv("OPENALGO_API_KEY", "")

# ── Dashboard ─────────────────────────────────────────────────────────────────
DASHBOARD_API_PORT:   int = int(os.getenv("DASHBOARD_API_PORT", 8000))
DASHBOARD_SECRET_KEY: str = os.getenv("DASHBOARD_SECRET_KEY", "changeme")
# Shared secret for mutating dashboard requests (SEC-01). If empty, auth is DISABLED
# (fine for localhost dev); set it before exposing the dashboard on any other interface.
DASHBOARD_TOKEN:      str = os.getenv("DASHBOARD_TOKEN", "")

# ── Discord Webhooks ───────────────────────────────────────────────────────────
DISCORD_WEBHOOK_TRADES: str = os.getenv("DISCORD_WEBHOOK_TRADES", "")
DISCORD_WEBHOOK_EXITS:  str = os.getenv("DISCORD_WEBHOOK_EXITS",  "")
DISCORD_WEBHOOK_DAILY:  str = os.getenv("DISCORD_WEBHOOK_DAILY",  "")
DISCORD_WEBHOOK_ALERTS: str = os.getenv("DISCORD_WEBHOOK_ALERTS", "")
DISCORD_WEBHOOK_ERRORS: str = os.getenv("DISCORD_WEBHOOK_ERRORS", "")
DISCORD_WEBHOOK_LOGS:   str = os.getenv("DISCORD_WEBHOOK_LOGS",   "")
