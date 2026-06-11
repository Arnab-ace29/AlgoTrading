"""
Catalyst detector — the 0.10 catalyst term of the screener score.

Reads an optional config/catalysts.json that can be maintained manually or filled
by a future NSE/FII feed. Until that's wired this returns a neutral 0.0, so the
screener works without it. Schema (all fields optional):

    {
      "RELIANCE": {
        "earnings_date":      "2026-06-07",   # PEAD opportunity if within 3 days
        "bulk_deal_buy":      true,           # institutional buying
        "fii_net_buy_cr":     650,            # > 500 Cr → bullish bias
        "board_meeting_today": false          # event risk → suppress
      }
    }

stdlib only — safe to import anywhere.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

_CATALYSTS_JSON = Path(__file__).resolve().parents[1] / "config" / "catalysts.json"


def _load() -> dict:
    if _CATALYSTS_JSON.exists():
        try:
            data = json.loads(_CATALYSTS_JSON.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _parse_date(s) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def get_catalyst_score(symbol: str, asof: date, table: dict | None = None) -> tuple[float, list[str]]:
    """
    Return (score, reasons). Score is roughly [-0.3, +0.7] and is clamped to [0,1]
    by the screener. `table` lets callers pass a preloaded dict (avoids re-reading).
    """
    cat = (table if table is not None else _load()).get(symbol)
    if not cat:
        return 0.0, []

    score = 0.0
    reasons: list[str] = []

    ed = _parse_date(cat.get("earnings_date"))
    if ed is not None:
        days = (ed - asof).days
        if 0 <= days <= 3:
            score += 0.3
            reasons.append(f"earnings in {days}d")

    if cat.get("bulk_deal_buy"):
        score += 0.2
        reasons.append("bulk deal buy")

    try:
        fii = float(cat.get("fii_net_buy_cr", 0) or 0)
    except (TypeError, ValueError):
        fii = 0.0
    if fii > 500:
        score += 0.2
        reasons.append(f"FII +₹{fii:.0f}Cr")

    if cat.get("board_meeting_today"):
        score -= 0.3
        reasons.append("board meeting today (event risk)")

    return round(score, 4), reasons


def load_table() -> dict:
    """Preload the catalyst table once per screener run."""
    return _load()
