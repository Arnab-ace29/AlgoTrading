"""
LIVE-06 regression: prove a separate WRITER PROCESS and a concurrent READER can
share the SQLite DB at once — the exact thing DuckDB could not do (it allows only
one read-write process and the second open failed with a lock error).

    .venv/bin/python scripts/test_concurrency.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import data.db as db

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


WRITER_CODE = """
import time
from data.db import log_trade_open
for i in range(60):
    log_trade_open(f"SYM{i}", "s", "BUY", "INTRADAY", 1, 100.0 + i, 99.0, 101.0, 0.6, mode="PAPER")
    time.sleep(0.02)
"""


def main() -> int:
    print("=" * 60); print("LIVE-06 — multi-process SQLite concurrency"); print("=" * 60)
    tmp = tempfile.mkdtemp()
    dbp = Path(tmp) / "concurrency.sqlite"

    # Parent creates the schema (WAL) and will READ.
    db.close_conn()
    db.DB_PATH = dbp
    db.init_db()

    # A separate PROCESS opens the SAME DB and WRITES 60 trades over ~1.2s.
    env = {**os.environ, "DB_PATH": str(dbp), "PYTHONPATH": str(ROOT)}
    writer = subprocess.Popen([sys.executable, "-c", WRITER_CODE],
                              cwd=str(ROOT), env=env, stderr=subprocess.PIPE, text=True)

    # While the writer runs, READ concurrently from this process. Under DuckDB this
    # whole setup never even starts (the second open throws a lock error).
    errors: list[str] = []
    reads = 0
    max_seen = 0
    t0 = time.time()
    while writer.poll() is None and time.time() - t0 < 30:
        try:
            n = len(db.get_trade_log(limit=1000))
            max_seen = max(max_seen, n)
            reads += 1
        except Exception as e:
            errors.append(str(e))
        time.sleep(0.02)

    _, stderr = writer.communicate(timeout=30)
    final = len(db.get_trade_log(limit=1000))

    check(writer.returncode == 0, f"writer process exited cleanly (rc={writer.returncode})")
    if writer.returncode != 0:
        print("    writer stderr:", (stderr or "")[-400:])
    check(not errors, f"reader saw 0 lock errors across {reads} concurrent reads")
    check(reads > 5, f"reader actually ran concurrently with the writer ({reads} reads)")
    check(max_seen > 0, f"reader observed the writer's rows during concurrent operation (peak {max_seen})")
    check(final == 60, f"all 60 writes landed and are readable cross-process ({final})")

    db.close_conn()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
