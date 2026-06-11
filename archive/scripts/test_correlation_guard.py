"""
EDGE-03 — correlation / sector exposure guard.

    .venv/bin/python scripts/test_correlation_guard.py
    pytest scripts/test_correlation_guard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from risk.correlation_guard import CorrelationGuard, correlation, SECTOR_MAP

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def test_sector_map():
    print("sectors:")
    g = CorrelationGuard()
    for s in ("HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"):
        check(g.sector_of(s) == "BANK", f"{s} → BANK")
    check(g.sector_of("TCS") == "IT" and g.sector_of("INFY") == "IT", "TCS/INFY → IT")
    check(g.sector_of("RELIANCE") == "ENERGY", "RELIANCE → ENERGY")
    # Unknown symbol gets its own unique sector (never grouped).
    check(g.sector_of("UNKNOWNXYZ").startswith("_"), "unknown symbol → unique sector")
    check(g.sector_of("AAA") != g.sector_of("BBB"), "two unknowns are NOT grouped together")


def test_sector_cap():
    print("sector cap (the ICICIBANK+SBIN case):")
    g = CorrelationGuard(max_per_sector=2)
    # Two banks already open → a third bank is blocked.
    ok, reason = g.allow("AXISBANK", ["HDFCBANK", "ICICIBANK"])
    check(not ok and "SECTOR_CAP" in reason, f"3rd bank blocked ({reason})")
    # A non-bank is fine alongside two banks.
    ok, _ = g.allow("TCS", ["HDFCBANK", "ICICIBANK"])
    check(ok, "different sector (IT) allowed alongside two banks")
    # One bank open → a second is allowed (cap is 2).
    ok, _ = g.allow("SBIN", ["HDFCBANK"])
    check(ok, "second bank allowed (under the cap)")
    # No open positions → always allowed.
    check(g.allow("SBIN", [])[0], "first position always allowed")


def test_disabled():
    print("disabled guard is a no-op:")
    g = CorrelationGuard(max_per_sector=1, enabled=False)
    check(g.allow("SBIN", ["HDFCBANK", "ICICIBANK"])[0], "disabled → always allowed")


def test_correlation_check():
    print("optional correlation cap:")
    rng = np.random.default_rng(0)
    base = 100 + np.cumsum(rng.normal(0, 1, 120))
    series = {
        "A": base,
        "B": base + rng.normal(0, 0.05, 120),   # nearly identical → high ρ
        "C": 100 + np.cumsum(rng.normal(0, 1, 120)),  # independent → low ρ
    }
    g = CorrelationGuard(max_per_sector=99, max_correlation=0.8)  # isolate the corr check
    prov = lambda s: series[s]
    ok, reason = g.allow("A", ["B"], price_provider=prov)
    check(not ok and "CORRELATED" in reason, f"near-identical names blocked ({reason})")
    ok, _ = g.allow("A", ["C"], price_provider=prov)
    check(ok, "independent names allowed")
    # correlation() sanity
    check(correlation(base, base) > 0.99, "a series correlates ~1.0 with itself")


def main() -> int:
    print("=" * 60); print("CORRELATION / SECTOR GUARD TESTS (EDGE-03)"); print("=" * 60)
    test_sector_map()
    test_sector_cap()
    test_disabled()
    test_correlation_check()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
