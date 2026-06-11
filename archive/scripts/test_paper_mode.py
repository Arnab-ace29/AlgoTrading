"""
Test PAPER vs LIVE trade-mode isolation (forward/paper-trading support).

Uses a temp SQLite so it doesn't collide with a running backend (LIVE-06):
    .venv/bin/python scripts/test_paper_mode.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import data.db as db

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def main() -> int:
    print("=" * 60); print("PAPER / LIVE MODE ISOLATION"); print("=" * 60)
    tmp = tempfile.mkdtemp()
    db.close_conn()
    db.DB_PATH = Path(tmp) / "t.db"
    db.init_db()

    # migration is idempotent (running it twice must not error)
    db._run_migrations(db.get_conn())
    check(True, "init_db + repeated migration run without error")

    # a PAPER (virtual) winner and a LIVE (real) loser, both today
    tp = db.log_trade_open("AAA", "s", "BUY", "INTRADAY", 10, 100, 99, 102, 0.7, "TRENDING_UP", "", mode="PAPER")
    db.log_trade_close(tp, 105, "TARGET_HIT", "")
    tl = db.log_trade_open("BBB", "s", "BUY", "INTRADAY", 5, 200, 198, 204, 0.7, "TRENDING_UP", "", mode="LIVE")
    db.log_trade_close(tl, 190, "SL_HIT", "")
    # default mode when omitted should be PAPER
    db.log_trade_open("CCC", "s", "BUY", "INTRADAY", 1, 10, 9, 11, 0.6, "", "")

    from analytics.pnl_tracker import PnLTracker
    tracker = PnLTracker()
    d = db.execute_query("SELECT date(MIN(entry_time)) AS d FROM trade_log").iloc[0]["d"]

    sp = tracker.compute_daily_stats(trade_date=d, mode="PAPER")
    sl = tracker.compute_daily_stats(trade_date=d, mode="LIVE")
    sa = tracker.compute_daily_stats(trade_date=d)

    check(sp["total_trades"] == 1 and abs(sp["gross_pnl"] - 50.0) < 1e-6,
          f"PAPER stats isolate the virtual winner (+50, n=1) — got {sp['gross_pnl']}")
    check(sl["total_trades"] == 1 and abs(sl["gross_pnl"] + 50.0) < 1e-6,
          f"LIVE stats isolate the real loser (-50, n=1) — got {sl['gross_pnl']}")
    check(sa["total_trades"] == 2, "unfiltered stats include both closed trades")

    paper_log = db.get_trade_log(mode="PAPER")
    check(set(paper_log["mode"]) == {"PAPER"}, "get_trade_log(mode=PAPER) returns only paper rows")
    check("CCC" in set(paper_log["symbol"]), "a trade logged without an explicit mode defaults to PAPER")
    check(len(db.get_trade_log()) == 3, "unfiltered trade log returns all rows")

    db.close_conn()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
