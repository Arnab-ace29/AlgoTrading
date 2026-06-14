"""
H1 — Cross-sectional momentum-volume ranking  (docs/EDGE_RESEARCH.md §H1).

Thesis: on any day the *extreme tail* of a 750-name cross-section continues hardest.
Instead of absolute thresholds ("RVOL > 3"), we rank ALL symbols each entry bar by a
signed volume-weighted momentum signal and trade only the top/bottom percentile —
long the strongest, short the weakest. Self-normalising across volatility regimes.

This module is PURE: given a cross-section snapshot (one row per symbol at the entry
bar), it returns the signal and the selected longs/shorts. No I/O. The backtest and
the live runner both call `select()` with the same contract.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RankParams:
    entry_time_ist: str = "09:45"   # bar at which the cross-section is scored
    top_pct: float      = 0.01      # trade the top/bottom this fraction of the universe
    min_rvol: float     = 2.0       # must-have: minimum same-window relative volume
    min_abs_ret: float  = 0.005     # must-have: at least 0.5% intraday move from open
    max_per_side: int   = 3         # cap longs and shorts separately, per day


def compute_signal(snap: pd.DataFrame) -> pd.Series:
    """
    Signed ranking signal per symbol. Input `snap` is indexed by symbol with columns:
        rvol      : same-window relative volume (>=0; 1.0 = normal)
        ret_open  : intraday return from the session open (signed)

    signal = log1p(rvol) * ret_open
      - log1p(rvol) emphasises unusual volume with diminishing returns (5x isn't 5/3x
        more meaningful than 3x), and is always >= 0 so it never flips the sign.
      - ret_open carries BOTH direction and magnitude of the move so far.
    Result: large positive = high-volume up-move (long); large negative = high-volume
    down-move (short); near zero = noise.
    """
    rvol = snap["rvol"].astype(float).clip(lower=0).fillna(0.0)
    mom  = snap["ret_open"].astype(float).fillna(0.0)
    return np.log1p(rvol) * mom


def select(snap: pd.DataFrame, params: RankParams = RankParams()) -> pd.DataFrame:
    """
    Rank the cross-section and return the chosen trades.

    Returns a DataFrame indexed by symbol with columns:
        signal, rank_pct, direction ("LONG"/"SHORT")
    Only names passing the must-have gates (min_rvol, min_abs_ret) and landing in the
    top/bottom `top_pct` are returned, capped at `max_per_side` each side.
    """
    if snap.empty:
        return pd.DataFrame(columns=["signal", "rank_pct", "direction"])

    sig = compute_signal(snap)

    # Must-have gates: enough relative volume AND a real move.
    eligible = (
        (snap["rvol"].astype(float) >= params.min_rvol)
        & (snap["ret_open"].astype(float).abs() >= params.min_abs_ret)
    )
    sig = sig[eligible]
    if sig.empty:
        return pd.DataFrame(columns=["signal", "rank_pct", "direction"])

    # Percentile rank across the eligible cross-section (0..1).
    rank_pct = sig.rank(pct=True)

    n = max(1, int(round(len(sig) * params.top_pct)))
    longs  = sig[sig > 0].nlargest(n).head(params.max_per_side)
    shorts = sig[sig < 0].nsmallest(n).head(params.max_per_side)

    out = []
    for sym, s in longs.items():
        out.append((sym, s, float(rank_pct.get(sym, np.nan)), "LONG"))
    for sym, s in shorts.items():
        out.append((sym, s, float(rank_pct.get(sym, np.nan)), "SHORT"))

    res = pd.DataFrame(out, columns=["symbol", "signal", "rank_pct", "direction"])
    return res.set_index("symbol")
