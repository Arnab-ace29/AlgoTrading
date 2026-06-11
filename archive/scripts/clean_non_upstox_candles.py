"""
One-time cleanup: delete all candle rows that are NOT from the Upstox backfill.

Sources to remove:
  - 'seed'    : synthetic demo data (scripts/seed_demo_data.py)
  - 'yfinance': yfinance fallback data (unreliable, not used for training)

Safe to run any time. Run BEFORE the full --force backfill so the DB starts clean.

Usage:
    python scripts/clean_non_upstox_candles.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlite3
from config.settings import DB_PATH

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

cur.execute("SELECT source, COUNT(*) FROM minute_candles GROUP BY source ORDER BY COUNT(*) DESC")
rows = cur.fetchall()
print("Sources currently in minute_candles:")
for source, count in rows:
    print(f"  {source or '(null)':<20} {count:>10,} rows")

UPSTOX_SOURCES = {"upstox_hist", "replay_fetch"}   # both are real Upstox data
to_delete = [r[0] for r in rows if r[0] not in UPSTOX_SOURCES]
if not to_delete:
    print("\nNothing to delete — only upstox_hist data present.")
    conn.close()
    sys.exit(0)

print(f"\nDeleting sources: {to_delete}")
cur.execute(
    f"DELETE FROM minute_candles WHERE source IN ({','.join('?' * len(to_delete))})",
    to_delete,
)
deleted = cur.rowcount
conn.commit()

cur.execute("SELECT source, COUNT(*) FROM minute_candles GROUP BY source")
remaining = cur.fetchall()
print(f"\nDeleted {deleted:,} rows.")
print("Remaining:")
for source, count in remaining:
    print(f"  {source or '(null)':<20} {count:>10,} rows")

conn.close()
print("\nDone. DB now contains only upstox_hist candles.")
