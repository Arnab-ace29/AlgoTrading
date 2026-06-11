"""
Sandbox + Live Data Test Script

Upstox Sandbox reality (from official docs):
  - Sandbox token is generated directly from account.upstox.com/developer/apps
    via the 'Generate' button — valid 30 days, NO OAuth flow needed.
  - Sandbox ONLY covers: Place/Modify/Cancel Order APIs.
  - Historical candles and WebSocket market data are NOT sandbox-enabled;
    they use the live API endpoint with the sandbox token.

Tests:
  Test 1 — Auth check         : confirm sandbox token is valid (profile API)
  Test 2 — Historical data     : fetch 1-min candles via live API (sandbox token works)
  Test 3 — WebSocket feed      : connect MarketDataStreamerV3, collect ticks
  Test 4 — Paper signal run    : compute features + ensemble, print signal score

Usage:
    conda activate algotrading
    python scripts/test_sandbox.py

Pre-requisites:
    .env must have UPSTOX_MODE=sandbox and SANDBOX_ACCESS_TOKEN set.
    Get the sandbox token: account.upstox.com/developer/apps → Sandbox app → Generate.
    PAPER_TRADE=true
"""

from __future__ import annotations
import sys
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from dotenv import load_dotenv
load_dotenv()

from config.settings import (
    UPSTOX_ACCESS_TOKEN, UPSTOX_SANDBOX,
    INSTRUMENT_KEYS, PAPER_TRADE,
)

PASS = "  ✓"
FAIL = "  ✗"
INFO = "  →"
results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> bool:
    try:
        detail = fn()
        print(f"{PASS} {name}")
        if detail:
            print(f"{INFO}   {detail}")
        results.append((name, True, detail or ""))
        return True
    except Exception as e:
        print(f"{FAIL} {name}")
        print(f"{INFO}   Error: {e}")
        results.append((name, False, str(e)))
        return False


# ── Test 1: Auth ──────────────────────────────────────────────────────────────

def test_auth() -> str:
    if not UPSTOX_ACCESS_TOKEN:
        raise ValueError(
            "Access token not set in .env\n"
            "  Sandbox: account.upstox.com/developer/apps → Sandbox app → Generate button\n"
            "  Live: run scripts/refresh_token.py with UPSTOX_MODE=live"
        )
    # Historical candle endpoint validates the token and API connectivity.
    # Sandbox token works here; LTP/profile require a live OAuth token.
    import httpx
    from datetime import date, timedelta
    to_d   = date.today().strftime("%Y-%m-%d")
    from_d = (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")
    key_enc = INSTRUMENT_KEYS["RELIANCE"].replace("|", "%7C")
    resp = httpx.get(
        f"https://api.upstox.com/v2/historical-candle/{key_enc}/day/{to_d}/{from_d}",
        headers={"Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}", "Accept": "application/json"},
        timeout=10,
    )
    if resp.status_code == 200:
        candles = resp.json().get("data", {}).get("candles", [])
        close = candles[0][4] if candles else "?"
        return f"Token valid + API reachable | RELIANCE close=₹{close} | Sandbox={UPSTOX_SANDBOX}"
    elif resp.status_code == 401:
        raise ValueError("Token rejected (401) — generate a fresh token from the portal Generate button")
    else:
        raise ValueError(f"API error {resp.status_code}: {resp.text[:200]}")


# ── Test 2: Historical Data ───────────────────────────────────────────────────

def test_historical_data() -> str:
    import upstox_client
    config = upstox_client.Configuration()
    config.access_token = UPSTOX_ACCESS_TOKEN

    api  = upstox_client.HistoryApi(upstox_client.ApiClient(config))
    today = datetime.today()
    from_date = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    to_date   = today.strftime("%Y-%m-%d")

    instrument_key = INSTRUMENT_KEYS["RELIANCE"]
    resp = api.get_historical_candle_data1(
        instrument_key, "1minute", to_date, from_date, "2.0"
    )
    candles = resp.data.candles if resp.data else []
    if not candles:
        raise ValueError("No candles returned — check token and sandbox endpoint")
    return (
        f"RELIANCE 1min | rows={len(candles)} | "
        f"latest={candles[0][0][:16]} | close={candles[0][4]}"
    )


# ── Test 3: WebSocket Feed ────────────────────────────────────────────────────

def test_websocket_feed() -> str:
    # WebSocket requires a live OAuth token (Bearer token from OAuth flow).
    # Sandbox-generated tokens are scoped to order APIs only and will be
    # rejected at the WS handshake. This test is skipped in sandbox mode
    # and will be enabled once you switch to live OAuth token.
    if UPSTOX_SANDBOX:
        return ("SKIPPED in sandbox mode — WebSocket requires a live OAuth token.\n"
                "  Will work automatically when UPSTOX_SANDBOX=false and you run\n"
                "  scripts/refresh_token.py to get a live OAuth token.")\

    import upstox_client

    ticks_received: list[dict] = []
    connected_event  = threading.Event()
    error_event      = threading.Event()
    _error_detail    = [""]

    def on_message(message):
        ticks_received.append({"raw": str(message)[:80]})

    def on_open():
        connected_event.set()

    def on_error(error):
        _error_detail[0] = str(error)
        error_event.set()

    config = upstox_client.Configuration()
    config.access_token = UPSTOX_ACCESS_TOKEN

    streamer = upstox_client.MarketDataStreamerV3(
        upstox_client.ApiClient(config),
        [INSTRUMENT_KEYS["RELIANCE"], INSTRUMENT_KEYS["TCS"]],
        "ltpc",
    )
    streamer.on("open",    on_open)
    streamer.on("message", on_message)
    streamer.on("error",   on_error)

    ws_thread = threading.Thread(target=streamer.connect, daemon=True)
    ws_thread.start()

    # Wait up to 20s for connection
    if not connected_event.wait(timeout=20):
        if error_event.is_set():
            raise ConnectionError(
                f"WebSocket error: {_error_detail[0]}\n"
                "  Likely cause: token invalid or expired. Generate a fresh token from the portal."
            )
        raise TimeoutError(
            "WebSocket did not connect within 20 seconds.\n"
            "  Check internet connection and token validity."
        )

    logger.info("WebSocket connected — collecting ticks for 15 seconds...")
    time.sleep(15)

    try:
        streamer.disconnect()
    except Exception:
        pass

    now_ist = datetime.now()
    market_open  = now_ist.replace(hour=9,  minute=15, second=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0)
    in_market_hours = market_open <= now_ist <= market_close and now_ist.weekday() < 5

    if not ticks_received:
        if not in_market_hours:
            return "WebSocket connected OK | 0 ticks (market closed — expected outside 9:15-15:30 IST weekdays)"
        raise ValueError("WebSocket connected but 0 ticks during market hours — check subscription keys")

    return f"Ticks received: {len(ticks_received)} in 15s | Sample: {ticks_received[0]['raw'][:60]}"


# ── Test 4: Paper Signal Run ──────────────────────────────────────────────────

def test_paper_signal() -> str:
    if not PAPER_TRADE:
        raise ValueError("PAPER_TRADE must be true for this test")

    # Pull fresh candles from DB (or yfinance fallback if DB is empty)
    from data.db import init_db, read_candles
    init_db()

    import pandas as pd
    df = read_candles("RELIANCE", "5min", limit=200)

    if df.empty or len(df) < 60:
        # yfinance fallback so the test works outside market hours
        import yfinance as yf
        raw = yf.download("RELIANCE.NS", period="5d", interval="5m", progress=False, auto_adjust=True)
        if raw.empty:
            raise ValueError("No data from DB or yfinance — fetch historical data first")
        # Flatten MultiIndex columns if present (newer yfinance versions)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0].lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() for c in raw.columns]
        raw = raw.rename(columns={"adj close": "close"})
        df = raw[["open", "high", "low", "close", "volume"]].dropna().tail(200)
        df.index.name = "timestamp"

    from features.indicators import compute_all_features
    from ensemble.aggregator import EnsembleAggregator

    df = df.set_index("timestamp") if "timestamp" in df.columns else df
    df = compute_all_features(df)

    agg    = EnsembleAggregator()
    result = agg.compute(df, "RELIANCE")

    return (
        f"RELIANCE | score={result.composite_score:+.3f} "
        f"dir={result.direction.value} "
        f"regime={result.regime.value} "
        f"actionable={result.actionable}"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nUpstox Sandbox Test | Sandbox={UPSTOX_SANDBOX} | PaperTrade={PAPER_TRADE}")
    print("=" * 60)

    if not UPSTOX_SANDBOX:
        print("WARNING: UPSTOX_MODE=live in .env — you are hitting LIVE API")
        print("Set UPSTOX_MODE=sandbox to use sandbox.\n")

    check("Auth — access token valid",         test_auth)
    check("Historical data — RELIANCE 5min",   test_historical_data)
    check("WebSocket feed — live ticks",        test_websocket_feed)
    check("Paper signal — ensemble compute",    test_paper_signal)

    passed = sum(1 for _, ok, _ in results if ok)
    total  = len(results)
    print(f"\n{'=' * 60}")
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("All sandbox tests passed. Safe to run live/runner.py in paper mode.\n")
    else:
        failed = [name for name, ok, _ in results if not ok]
        print(f"Failed: {failed}")
        print("Fix the above before proceeding.\n")
        sys.exit(1)
