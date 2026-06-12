import sqlite3, os, sys, json

sys.stdout.reconfigure(encoding='utf-8')
db = r'd:\Python_Codes\AlgoTrading\data\algo_trading.sqlite'
conn = sqlite3.connect(db, timeout=10)

# Load target universe
with open(r'd:\Python_Codes\AlgoTrading\archive\config\universes.json') as f:
    universes = json.load(f)

nifty100 = set(universes['nifty100'])
print(f"Nifty 100 symbols: {len(nifty100)}")

# Get all symbols with 5min data
all_syms = set(r[0] for r in conn.execute("SELECT DISTINCT symbol FROM minute_candles WHERE timeframe='5min'").fetchall())
print(f"Symbols with 5min data: {len(all_syms)}")

# Coverage check for Nifty 100
missing = nifty100 - all_syms
covered = nifty100 & all_syms
print(f"\nNifty 100 coverage: {len(covered)}/{len(nifty100)} symbols have 5min data")
if missing:
    print(f"Missing from DB: {sorted(missing)}")

# Daily candle coverage for Nifty 100
daily_syms = set(r[0] for r in conn.execute("SELECT DISTINCT symbol FROM minute_candles WHERE timeframe='1day'").fetchall())
daily_covered = nifty100 & daily_syms
print(f"\nNifty 100 daily candle coverage: {len(daily_covered)}/{len(nifty100)}")
daily_missing = nifty100 - daily_syms
if daily_missing:
    print(f"Missing daily candles: {sorted(daily_missing)}")

# Bar count distribution for Nifty 100 symbols (5min)
print("\n=== Bar count distribution (5min, Nifty 100) ===")
counts = []
for sym in sorted(covered):
    c = conn.execute("SELECT COUNT(*) FROM minute_candles WHERE symbol=? AND timeframe='5min'", (sym,)).fetchone()[0]
    counts.append((sym, c))
counts.sort(key=lambda x: x[1])
min_c, max_c = counts[0], counts[-1]
avg_c = sum(c for _, c in counts) // len(counts)
print(f"  Min: {min_c[0]} = {min_c[1]:,} bars")
print(f"  Max: {max_c[0]} = {max_c[1]:,} bars")
print(f"  Avg: {avg_c:,} bars  (~{avg_c//75} trading days)")
symbols_lt_200 = [(s, c) for s, c in counts if c < 15000]  # < ~200 days
print(f"  Symbols with < 200 trading days of data: {len(symbols_lt_200)}")
for s, c in symbols_lt_200:
    print(f"    {s}: {c:,} ({c//75} days)")

conn.close()
