"""
Upstox instrument-key resolver.

The hand-maintained `config.settings.INSTRUMENT_KEYS` only covers a handful of
symbols, which capped the tradable/replayable universe to ~10 names. This module
resolves an instrument key for ANY NSE equity by downloading Upstox's official
instrument master (NSE.json.gz) once and caching the trading_symbol → key map to
disk. Strictly Upstox — the same source the live feed uses.

Master schema (per Upstox docs), NSE equity rows look like:
    {"segment": "NSE_EQ", "instrument_type": "EQ",
     "instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE", ...}
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from config.settings import INSTRUMENT_KEYS, ROOT_DIR

_NSE_URL  = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
_CACHE    = ROOT_DIR / "data" / "nse_eq_keys.json"
_FO_CACHE = ROOT_DIR / "data" / "nse_fo_symbols.json"  # F&O eligible equity symbols
_MAX_AGE_SEC = 7 * 86400        # refresh the master weekly

_map: Optional[dict[str, str]] = None    # in-process cache: trading_symbol → key
_fo_symbols: Optional[list[str]] = None  # in-process cache: F&O eligible symbols


def _load_cache() -> Optional[dict[str, str]]:
    if not _CACHE.exists():
        return None
    if time.time() - _CACHE.stat().st_mtime > _MAX_AGE_SEC:
        return None
    try:
        data = json.loads(_CACHE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data else None
    except Exception:
        return None


def _download() -> dict[str, str]:
    """
    Download + parse the Upstox NSE master.

    Produces two caches in one pass:
      - nse_eq_keys.json  : {trading_symbol: instrument_key} for NSE_EQ equities
      - nse_fo_symbols.json: sorted list of underlying equity symbols for NSE_FO futures
        (i.e. F&O eligible stocks)
    """
    import httpx
    logger.info("Downloading Upstox NSE instrument master (one-time, cached weekly)…")
    resp = httpx.get(_NSE_URL, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    rows = json.loads(gzip.decompress(resp.content))

    eq_map: dict[str, str] = {}
    fo_underlyings: set[str] = set()

    for it in rows:
        seg  = it.get("segment", "")
        itype = it.get("instrument_type", "")

        if seg == "NSE_EQ" and itype == "EQ":
            ts, ik = it.get("trading_symbol"), it.get("instrument_key")
            if ts and ik:
                eq_map[str(ts).upper()] = ik

        elif seg == "NSE_FO" and itype == "FUT":
            # underlying_symbol is the equity symbol (e.g. "RELIANCE")
            underlying = it.get("underlying_symbol") or it.get("name") or ""
            if underlying:
                fo_underlyings.add(str(underlying).upper().split("-")[0].strip())

    if eq_map:
        try:
            _CACHE.write_text(json.dumps(eq_map), encoding="utf-8")
            logger.success(f"Cached {len(eq_map)} NSE equity keys → {_CACHE.name}")
        except Exception as e:
            logger.warning(f"Could not write equity key cache: {e}")

    fo_list = sorted(fo_underlyings)
    if fo_list:
        try:
            _FO_CACHE.write_text(json.dumps(fo_list), encoding="utf-8")
            logger.success(f"Cached {len(fo_list)} F&O eligible symbols → {_FO_CACHE.name}")
        except Exception as e:
            logger.warning(f"Could not write F&O cache: {e}")

    return eq_map


def _get_map(allow_download: bool = True) -> dict[str, str]:
    global _map
    if _map is not None:
        return _map
    m = _load_cache()
    if m is None and allow_download:
        try:
            m = _download()
        except Exception as e:
            logger.warning(f"Instrument master unavailable ({e}); "
                           f"falling back to config.INSTRUMENT_KEYS only.")
            m = {}
    _map = m or {}
    return _map


def resolve_instrument_key(symbol: str, allow_download: bool = True) -> Optional[str]:
    """
    Instrument key for an NSE equity symbol. Checks the curated config map first
    (covers indices like NIFTY50), then the full Upstox NSE master. None if unknown.
    """
    if not symbol:
        return None
    if symbol in INSTRUMENT_KEYS:
        return INSTRUMENT_KEYS[symbol]
    return _get_map(allow_download).get(symbol.upper())


def get_fo_eligible_symbols(allow_download: bool = True) -> list[str]:
    """
    Return the list of F&O eligible underlying equity symbols extracted from the
    Upstox NSE instrument master (NSE_FO futures rows). No extra API call — the
    same file used for resolve_instrument_key() is parsed in a single pass.

    Returns an empty list if the master is unavailable.
    """
    global _fo_symbols
    if _fo_symbols is not None:
        return _fo_symbols

    # Try the dedicated F&O cache first (populated by _download()).
    if _FO_CACHE.exists() and (time.time() - _FO_CACHE.stat().st_mtime < _MAX_AGE_SEC):
        try:
            data = json.loads(_FO_CACHE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                _fo_symbols = data
                return _fo_symbols
        except Exception:
            pass

    # F&O cache missing or stale — need a fresh download of the NSE master.
    # Can't rely on _get_map() here: if the equity cache is still fresh it will
    # return without calling _download(), so _FO_CACHE would never get written.
    if allow_download:
        try:
            _download()
        except Exception as e:
            logger.warning(f"Could not re-download NSE master for F&O symbols: {e}")
    else:
        _get_map(allow_download=False)

    if _FO_CACHE.exists():
        try:
            data = json.loads(_FO_CACHE.read_text(encoding="utf-8"))
            _fo_symbols = data if isinstance(data, list) else []
        except Exception:
            _fo_symbols = []
    else:
        _fo_symbols = []

    return _fo_symbols


def get_all_equity_symbols(allow_download: bool = True) -> list[str]:
    """All NSE equity symbols in the Upstox master (~2452)."""
    return sorted(_get_map(allow_download).keys())
