"""Write backtest artifacts: trades.csv, summary.md, summary.json (per docs/BACKTEST_OUTPUT.md)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtest.metrics import compute_metrics, breakdown, equity_curve

RESULTS_DIR = Path(__file__).parent / "results"


def _md_table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_(none)_\n"
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out) + "\n"


def write_run(trades: pd.DataFrame, cfg, strategy: str = "H1_xsec_rank") -> dict:
    """Write all artifacts for one run; return {run_id, dir, metrics}."""
    run_id = uuid.uuid4().hex[:8]
    outdir = RESULTS_DIR / run_id
    outdir.mkdir(parents=True, exist_ok=True)

    # Format 1 — trades.csv
    if not trades.empty:
        trades = trades.copy()
        trades.insert(0, "run_id", run_id)
        trades.insert(1, "strategy", strategy)
    trades.to_csv(outdir / "trades.csv", index=False)

    m = compute_metrics(trades, cfg.capital)

    # Format 2 — summary.json
    summary = {
        "run_id": run_id,
        "run_time": datetime.now().isoformat(timespec="seconds"),
        "strategy": strategy,
        "period": {"from": cfg.from_date, "to": cfg.to_date},
        "params": {
            "entry_time": cfg.entry_time, "time_stop": cfg.time_stop,
            "atr_stop_mult": cfg.atr_stop_mult, "atr_trail_mult": cfg.atr_trail_mult,
            "slippage_pct": cfg.slippage_pct, "capital": cfg.capital,
            "base_risk_pct": cfg.sizing.base_risk_pct,
            "top_pct": cfg.rank.top_pct, "min_rvol": cfg.rank.min_rvol,
            "max_per_side": cfg.rank.max_per_side,
        },
        "metrics": m,
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Format 2 — summary.md
    md = [f"# Backtest Summary — `{run_id}`  ({strategy})", "",
          f"Period: **{cfg.from_date} → {cfg.to_date}**  ·  Capital: ₹{cfg.capital:,.0f}  ·  "
          f"Risk/trade: {cfg.sizing.base_risk_pct*100:.1f}%  ·  Slippage: {cfg.slippage_pct*100:.2f}%/leg",
          ""]
    if m.get("total_trades", 0) == 0:
        md.append("**No trades generated.** Loosen `min_rvol`/`min_abs_ret`/`top_pct` or widen the period.")
        (outdir / "summary.md").write_text("\n".join(md), encoding="utf-8")
        return {"run_id": run_id, "dir": str(outdir), "metrics": m}

    headline = pd.DataFrame([
        ("Total trades", m["total_trades"]), ("Win rate %", m["win_rate"]),
        ("Expectancy (R)", m["expectancy_R"]), ("Profit factor", m["profit_factor"]),
        ("Net PnL ₹", m["net_pnl"]), ("Return %", m["return_pct"]),
        ("Sharpe", m["sharpe"]), ("Sortino", m["sortino"]),
        ("Max drawdown %", m["max_drawdown_pct"]),
        ("Avg win ₹", m["avg_win"]), ("Avg loss ₹", m["avg_loss"]),
        ("Avg MFE (R)", m["avg_mfe_R"]), ("Avg MAE (R)", m["avg_mae_R"]),
        ("Trades/day", m["avg_trades_per_day"]),
    ], columns=["Metric", "Value"])
    md += ["## Headline", "", _md_table(headline)]
    md += ["## By direction", "", _md_table(breakdown(trades, "direction"))]
    md += ["## By exit reason", "", _md_table(breakdown(trades, "exit_reason"))]
    md += ["## By conviction", "", _md_table(breakdown(trades, "conviction"))]

    # Best / worst
    top = trades.nlargest(5, "R_multiple")[["date", "symbol", "direction", "R_multiple", "net_pnl"]]
    bot = trades.nsmallest(5, "R_multiple")[["date", "symbol", "direction", "R_multiple", "net_pnl"]]
    md += ["## Best 5 (by R)", "", _md_table(top), "## Worst 5 (by R)", "", _md_table(bot)]

    (outdir / "summary.md").write_text("\n".join(md), encoding="utf-8")

    # equity curve csv (feeds the future tearsheet)
    equity_curve(trades, cfg.capital).to_csv(outdir / "equity_curve.csv", index=False)

    return {"run_id": run_id, "dir": str(outdir), "metrics": m}
