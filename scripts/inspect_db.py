"""
Quick DB diagnostic — shows coverage for all universe symbols.
"""
import sqlite3, sys, json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.stdout.reconfigure(encoding="utf-8")

db = ROOT / "data" / "algo_trading.sqlite"
conn = sqlite3.connect(str(db), timeout=30)

with open(ROOT / "config" / "universes.json") as f:
    universes = json.load(f)

all_syms: set[str] = set()
for v in universes.values():
    all_syms.update(v)

n50  = set(universes.get("nifty50", []))
n100 = set(universes.get("nifty100", []))

# Row counts per timeframe
print("=== DB Summary ===")
for tf, label in [("5min", "5-min"), ("1day", "1-day")]:
    r = conn.execute(
        "SELECT COUNT(DISTINCT symbol), COUNT(*), MIN(timestamp), MAX(timestamp) "
        "FROM minute_candles WHERE timeframe=?", (tf,)
    ).fetchone()
    print(f"  {label}: {r[0]} symbols, {r[1]:,} rows  [{str(r[2])[:10]} → {str(r[3])[:10]}]")

# Coverage against universe
print(f"\n=== Universe Coverage ({len(all_syms)} symbols) ===")
for tf, label in [("5min", "5-min"), ("1day", "1-day")]:
    have = set(r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM minute_candles WHERE timeframe=?", (tf,)).fetchall())
    missing = sorted(all_syms - have)
    print(f"  {label}: {len(have & all_syms)}/{len(all_syms)} covered, {len(missing)} missing")
    for s in missing:
        print(f"    MISSING {tf}: {s}")

# Nifty 100 bar count distribution (5min)
print("\n=== Nifty 100 — 5-min bar distribution ===")
have_5m = set(r[0] for r in conn.execute(
    "SELECT DISTINCT symbol FROM minute_candles WHERE timeframe='5min'").fetchall())
covered = sorted(n100 & have_5m)
if covered:
    rows = conn.execute(
        f"SELECT symbol, COUNT(*) as bars FROM minute_candles "
        f"WHERE timeframe='5min' AND symbol IN ({','.join('?'*len(covered))}) "
        f"GROUP BY symbol ORDER BY bars", covered
    ).fetchall()
    bars_list = [r[1] for r in rows]
    avg = sum(bars_list) // len(bars_list)
    print(f"  Min: {rows[0][0]} = {rows[0][1]:,} bars ({rows[0][1]//75} days)")
    print(f"  Max: {rows[-1][0]} = {rows[-1][1]:,} bars ({rows[-1][1]//75} days)")
    print(f"  Avg: {avg:,} bars (~{avg//75} trading days)")
    thin = [(s, b) for s, b in rows if b < 15000]
    print(f"  Symbols < 200 trading days: {len(thin)}")
    for s, b in thin:
        print(f"    {s}: {b:,} ({b//75} days)")

# VIX / global indices
print("\n=== Index / Macro data ===")
for sym in ("INDIAVIX", "NIFTY50_YF", "SP500", "NASDAQ", "NIFTYBANK", "NIFTYIT", "NIFTYFMCG"):
    r = conn.execute(
        "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM minute_candles WHERE symbol=?", (sym,)
    ).fetchone()
    if r[0]:
        print(f"  {sym}: {r[0]} rows  [{str(r[1])[:10]} → {str(r[2])[:10]}]")
    else:
        print(f"  {sym}: NO DATA")

conn.close()
