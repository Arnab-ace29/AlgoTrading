"""
Walk-forward validation + negative controls (docs/EDGE_RESEARCH.md §1, §6).

Two questions every candidate edge must answer before it's believed:
  1. STABILITY — does it hold across time folds, or just one lucky window?
     (Sign stability across folds matters more than the magnitude in any one.)
  2. REAL?     — does it beat negative controls (random entries, shuffled signal)?
     If random picking scores the same, you found noise.

Features are built once (cached) and reused across folds + controls, so this is cheap.
When tunable params arrive (e.g. exit targets), extend to optimise-on-train / score-on-test;
for the current fixed signal, this measures fold-stability + control-superiority.
"""
from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

ROOT = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(ROOT))

from config.settings import DB_PATH
from backtest.engine import (
    BacktestConfig, build_entry_features, simulate_from_features, resolve_symbols,
)
from backtest.metrics import compute_metrics


def time_folds(feat: pd.DataFrame, n_folds: int) -> list[tuple[str, list]]:
    """Split sorted unique dates into n contiguous folds. Returns [(label, [dates]), ...]."""
    dates = sorted(feat["date"].unique())
    chunks = np.array_split(dates, n_folds)
    return [(f"fold{i+1} [{c[0]}..{c[-1]}]", list(c)) for i, c in enumerate(chunks) if len(c)]


def _eval(feat: pd.DataFrame, cfg: BacktestConfig, conn) -> dict:
    trades = simulate_from_features(feat, cfg, conn)
    m = compute_metrics(trades, cfg.capital)
    return m


def run_walkforward(cfg: BacktestConfig, n_folds: int = 4,
                    controls=("random", "shuffle")) -> dict:
    """Build features once, then evaluate the strategy per fold + the controls overall."""
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    try:
        symbols = resolve_symbols(cfg, conn)
        logger.info(f"Walk-forward: {len(symbols)} symbols, {cfg.from_date}..{cfg.to_date}, "
                    f"{n_folds} folds")
        feat = build_entry_features(cfg, conn, symbols, use_cache=True)
        if feat.empty:
            logger.warning("No features — aborting.")
            return {}

        # Per-fold strategy evaluation (OOS stability).
        folds = time_folds(feat, n_folds)
        fold_results = []
        for label, dates in folds:
            ff = feat[feat["date"].isin(dates)]
            m = _eval(ff, cfg, conn)
            m["fold"] = label
            fold_results.append(m)
            logger.info(f"  {label}: trades={m.get('total_trades',0)} "
                        f"win%={m.get('win_rate',0)} exp_R={m.get('expectancy_R',0)}")

        # Whole-period strategy vs negative controls.
        strat = _eval(feat, cfg, conn)
        control_results = {}
        for c in controls:
            cm = _eval(feat, replace(cfg, control=c), conn)
            control_results[c] = cm
            logger.info(f"  control[{c}]: trades={cm.get('total_trades',0)} "
                        f"exp_R={cm.get('expectancy_R',0)}")
    finally:
        conn.close()

    # Verdicts.
    exps = [f.get("expectancy_R", 0) for f in fold_results if f.get("total_trades", 0) > 0]
    sign_stable = len(exps) > 0 and (all(e > 0 for e in exps) or all(e < 0 for e in exps))
    beats_controls = all(
        strat.get("expectancy_R", -9) > control_results[c].get("expectancy_R", 9)
        for c in controls
    ) if control_results else False

    return {
        "config": {
            "from": cfg.from_date, "to": cfg.to_date, "fade": cfg.fade,
            "slippage_pct": cfg.slippage_pct, "top_pct": cfg.rank.top_pct,
            "min_rvol": cfg.rank.min_rvol, "entry": cfg.entry_time, "time_stop": cfg.time_stop,
        },
        "folds": fold_results,
        "overall": strat,
        "controls": control_results,
        "verdict": {
            "sign_stable_across_folds": sign_stable,
            "all_fold_expectancies": [round(e, 3) for e in exps],
            "beats_negative_controls": beats_controls,
            "overall_expectancy_R": strat.get("expectancy_R", 0),
            "tradeable_candidate": bool(sign_stable and beats_controls
                                        and strat.get("expectancy_R", -9) > 0),
        },
    }


def format_report(res: dict) -> str:
    if not res:
        return "No results."
    c = res["config"]
    out = ["# Walk-Forward Validation", "",
           f"Period **{c['from']}→{c['to']}** · fade={c['fade']} · slippage={c['slippage_pct']*100:.2f}%/leg "
           f"· top_pct={c['top_pct']} · entry {c['entry']} · stop {c['time_stop']}", ""]

    out += ["## Per-fold OOS stability", "",
            "| fold | trades | win% | expectancy_R | Sharpe | maxDD% |",
            "|---|---|---|---|---|---|"]
    for f in res["folds"]:
        out.append(f"| {f.get('fold','')} | {f.get('total_trades',0)} | {f.get('win_rate',0)} | "
                   f"{f.get('expectancy_R',0)} | {f.get('sharpe',0)} | {f.get('max_drawdown_pct',0)} |")

    o = res["overall"]
    out += ["", "## Strategy vs negative controls (whole period)", "",
            "| variant | trades | win% | expectancy_R |", "|---|---|---|---|",
            f"| **strategy** | {o.get('total_trades',0)} | {o.get('win_rate',0)} | **{o.get('expectancy_R',0)}** |"]
    for name, cm in res["controls"].items():
        out.append(f"| control: {name} | {cm.get('total_trades',0)} | {cm.get('win_rate',0)} | {cm.get('expectancy_R',0)} |")

    v = res["verdict"]
    out += ["", "## Verdict", "",
            f"- Fold expectancies: `{v['all_fold_expectancies']}`",
            f"- Sign-stable across folds: **{v['sign_stable_across_folds']}**",
            f"- Beats negative controls: **{v['beats_negative_controls']}**",
            f"- Overall expectancy: **{v['overall_expectancy_R']} R**",
            f"- **Tradeable candidate: {v['tradeable_candidate']}**", ""]
    if not v["tradeable_candidate"]:
        out.append("> Not a tradeable edge yet — needs a positive, sign-stable, control-beating result.")
    return "\n".join(out)
