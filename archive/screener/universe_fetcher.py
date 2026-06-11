"""
Universe constituent fetcher.

Fetches the Nifty Total Market (750) constituent list from niftyindices.com
and writes it to config/nifty_total_market.csv for use by screener/universe.py.

Falls back gracefully to a manually-placed CSV if the live fetch fails.
Run this once monthly (or trigger from scripts/refresh_universe.py).

Usage:
    python screener/universe_fetcher.py
    python screener/universe_fetcher.py --force   # bypass age check
"""

from __future__ import annotations

import argparse
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

_ROOT = Path(__file__).resolve().parents[1]
_CSV_PATH   = _ROOT / "config" / "nifty_total_market.csv"
_MAX_AGE_SEC = 30 * 86400       # 30 days

# niftyindices.com requires these headers to serve the CSV.
_NIFTY_CSV_URL  = "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"
_NIFTY_CSV_URL_FALLBACK = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

_BROWSER_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/125.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer":         "https://www.niftyindices.com/",
}


def _is_stale(path: Path) -> bool:
    if not path.exists():
        return True
    return time.time() - path.stat().st_mtime > _MAX_AGE_SEC


def _fetch_csv(url: str) -> Optional[str]:
    """Try to download CSV text from niftyindices.com with browser-like headers."""
    try:
        import httpx
        resp = httpx.get(url, headers=_BROWSER_HEADERS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        text = resp.text
        if "Company Name" in text or "Symbol" in text:
            return text
        logger.warning(f"Unexpected CSV content from {url}")
        return None
    except Exception as e:
        logger.warning(f"Could not fetch {url}: {e}")
        return None


def _parse_symbols(csv_text: str) -> list[str]:
    """
    Parse trading symbols from the niftyindices.com constituent CSV.
    Expected columns: Company Name, Industry, Symbol, Series, ISIN Code
    """
    lines = [ln.strip() for ln in csv_text.splitlines() if ln.strip()]
    header_idx = None
    for i, line in enumerate(lines):
        if "Symbol" in line or "symbol" in line:
            header_idx = i
            break
    if header_idx is None:
        logger.error("Could not locate 'Symbol' column in CSV")
        return []

    headers = [h.strip().strip('"') for h in lines[header_idx].split(",")]
    try:
        sym_col = next(i for i, h in enumerate(headers) if h.lower() == "symbol")
    except StopIteration:
        logger.error(f"No 'Symbol' column; found: {headers}")
        return []

    symbols: list[str] = []
    for line in lines[header_idx + 1:]:
        if not line:
            continue
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) > sym_col and parts[sym_col]:
            sym = parts[sym_col].strip().upper()
            # Skip index/fund entries (no alphabetic NSE symbol)
            if sym and sym.isalpha() or "-" in sym or "&" in sym:
                symbols.append(sym)
    return symbols


def fetch_nifty_universe(force: bool = False) -> list[str]:
    """
    Return the Nifty Total Market (750) constituent symbols.

    Priority:
      1. Fresh cached CSV at config/nifty_total_market.csv
      2. Live download from niftyindices.com (Total Market → 500 fallback)
      3. Stale cached CSV (still usable, just old)
      4. Empty list (screener falls back to _DEFAULT_UNIVERSES)

    The caller (screener/universe.py) handles an empty list gracefully.
    """
    if not force and not _is_stale(_CSV_PATH):
        logger.debug(f"Universe CSV fresh, loading from {_CSV_PATH.name}")
        return _parse_symbols(_CSV_PATH.read_text(encoding="utf-8"))

    logger.info("Refreshing Nifty Total Market constituent list…")
    text = _fetch_csv(_NIFTY_CSV_URL)
    if text is None:
        logger.info("Total Market CSV failed, trying Nifty 500 fallback URL…")
        text = _fetch_csv(_NIFTY_CSV_URL_FALLBACK)

    if text:
        _CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CSV_PATH.write_text(text, encoding="utf-8")
        logger.success(f"Universe CSV saved → {_CSV_PATH.name}")
        return _parse_symbols(text)

    # Both URLs failed — use stale cache if available
    if _CSV_PATH.exists():
        age_days = (time.time() - _CSV_PATH.stat().st_mtime) / 86400
        logger.warning(f"Live fetch failed; using stale CSV ({age_days:.0f}d old)")
        return _parse_symbols(_CSV_PATH.read_text(encoding="utf-8"))

    logger.error(
        "Could not fetch Nifty constituent list and no cached CSV found.\n"
        f"  → Download manually: {_NIFTY_CSV_URL}\n"
        f"  → Save to: {_CSV_PATH}"
    )
    return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh Nifty Total Market constituent list")
    parser.add_argument("--force", action="store_true", help="Bypass age check, always re-download")
    args = parser.parse_args()

    syms = fetch_nifty_universe(force=args.force)
    if syms:
        logger.success(f"Universe loaded: {len(syms)} symbols")
        logger.info(f"Sample: {syms[:10]}")
    else:
        logger.error("Universe is empty — check network or place CSV manually")
