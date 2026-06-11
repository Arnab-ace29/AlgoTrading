"""
Upstox margin-multiplier utility.

Calls ChargeApi.post_margin (POST /v2/charges/margin) in batches to get the
intraday (MIS) margin requirement for each equity symbol.  From that we derive:

    multiplier = notional / total_margin_required

meaning "for every ₹X of capital deployed, the broker lets you hold ₹X × multiplier
worth of stock on MIS".

Results are saved to data/margin_multipliers.json and can be read back without
making an API call.

Requires a LIVE Upstox OAuth token — sandbox token returns 401 for this endpoint.
"""

from __future__ import annotations

import json
import math
import time
from datetime import date
from pathlib import Path
from typing import Optional

from loguru import logger

from config.settings import ROOT_DIR
from data.instruments import resolve_instrument_key

_CACHE_PATH = ROOT_DIR / "data" / "margin_multipliers.json"
_BATCH_SIZE = 1           # post_margin is a single-order API; UDAPI1102 fires for batches > 1
_REQUEST_DELAY = 0.25     # seconds between calls (~4 req/s, well under Upstox rate limit)


def _build_api():
    """Return an authenticated ChargeApi. Raises if no live token."""
    import upstox_client
    from data.upstox_history import get_api_client
    return upstox_client.ChargeApi(get_api_client())


def fetch_margin_multipliers(
    symbols: list[str],
    reference_price: float = 1000.0,
    save: bool = True,
) -> dict[str, dict]:
    """
    Fetch intraday (MIS, product='I') margin multipliers for each symbol via
    the Upstox ChargeApi.post_margin endpoint.

    Parameters
    ----------
    symbols : list of NSE equity symbols (e.g. ['RELIANCE', 'TCS'])
    reference_price : price sent to the API per instrument.  Since intraday
        equity margin is a fixed percentage of notional, the ratio
        required_margin/(price×qty) is constant — any round price works.
    save : if True, persist results to data/margin_multipliers.json

    Returns
    -------
    dict keyed by symbol:
        {
            "instrument_key": "NSE_EQ|...",
            "reference_price": 1000.0,
            "total_margin":    200.0,   # ₹ per share
            "margin_pct":      20.0,    # % of notional
            "multiplier":      5.0,     # notional / margin
            "span_margin":     ...,
            "exposure_margin": ...,
            "equity_margin":   ...,
        }
    Symbols without a known instrument key or with zero/null margin are skipped.
    """
    import upstox_client

    api = _build_api()

    # Resolve to instrument keys; skip unknowns
    keyed: list[tuple[str, str]] = []   # [(symbol, instrument_key), ...]
    for sym in symbols:
        key = resolve_instrument_key(sym)
        if key:
            keyed.append((sym, key))
        else:
            logger.debug(f"margin: no instrument key for {sym}, skipping")

    if not keyed:
        logger.warning("margin: no resolvable symbols — check instruments cache")
        return {}

    results: dict[str, dict] = {}
    qty = 1

    # Process in batches
    for batch_start in range(0, len(keyed), _BATCH_SIZE):
        batch = keyed[batch_start: batch_start + _BATCH_SIZE]
        instruments = [
            upstox_client.Instrument(
                instrument_key=ikey,
                quantity=qty,
                product="I",               # I = intraday (MIS)
                transaction_type="BUY",
                price=float(reference_price),
            )
            for _, ikey in batch
        ]
        body = upstox_client.MarginRequest(instruments=instruments)
        try:
            resp = api.post_margin(body)
        except Exception as exc:
            logger.error(f"margin API error (batch {batch_start}): {exc}")
            time.sleep(1)
            continue

        margins = (resp.data.margins or []) if resp.data else []

        for (sym, ikey), m in zip(batch, margins):
            total = float(m.total_margin or 0)
            notional = float(reference_price) * qty
            if total <= 0 or not math.isfinite(total):
                logger.debug(f"margin: {sym} returned zero/null margin, skipped")
                continue
            margin_pct = 100.0 * total / notional
            multiplier  = notional / total
            results[sym] = {
                "instrument_key":  ikey,
                "reference_price": reference_price,
                "total_margin":    round(total, 4),
                "margin_pct":      round(margin_pct, 2),
                "multiplier":      round(multiplier, 2),
                "span_margin":     round(float(m.span_margin     or 0), 4),
                "exposure_margin": round(float(m.exposure_margin or 0), 4),
                "equity_margin":   round(float(m.equity_margin   or 0), 4),
            }
            logger.debug(f"  {sym}: margin={margin_pct:.1f}%  multiplier={multiplier:.1f}x")

        processed = batch_start + len(batch)
        if processed % 50 == 0 or processed == len(keyed):
            logger.info(f"  {processed}/{len(keyed)} symbols processed, {len(results)} fetched so far…")
        if batch_start + _BATCH_SIZE < len(keyed):
            time.sleep(_REQUEST_DELAY)

    if save and results:
        payload = {"date": str(date.today()), "symbols": results}
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(payload, indent=2))
        logger.info(f"Saved margin multipliers for {len(results)} symbols → {_CACHE_PATH}")

    return results


def load_margin_multipliers(max_age_days: int = 7) -> dict[str, dict]:
    """
    Load cached margin multipliers from data/margin_multipliers.json.
    Returns empty dict if cache is absent or older than max_age_days.
    """
    if not _CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(_CACHE_PATH.read_text())
        cached_date = date.fromisoformat(payload.get("date", "2000-01-01"))
        if (date.today() - cached_date).days > max_age_days:
            logger.info(f"margin_multipliers.json is {(date.today()-cached_date).days}d old — refresh recommended")
        return payload.get("symbols", {})
    except Exception as exc:
        logger.warning(f"Could not load margin_multipliers.json: {exc}")
        return {}


def get_multiplier(symbol: str, default: float = 1.0) -> float:
    """
    Quick single-symbol lookup from cache.  Returns `default` if not found.
    Does NOT hit the network — use fetch_margin_multipliers() to refresh.
    """
    cache = load_margin_multipliers()
    return cache.get(symbol, {}).get("multiplier", default)
