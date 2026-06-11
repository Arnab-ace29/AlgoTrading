"""
Tests for the pairs/theta strategy books + THETA-01 hedge sizing.

Pure numpy/pandas (pairs imports without statsmodels now):
    .venv/bin/python scripts/test_books.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from signals.theta.hedge_manager import DeltaHedgeManager
from signals.theta.theta_book import ThetaBook
from signals.theta.weekly_straddle import StraddlePosition, StraddleLeg
from signals.pairs.pairs_signal import PairsSignal
from signals.pairs.pairs_book import PairsBook

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def test_theta01_hedge_sizing():
    print("THETA-01 — delta-hedge lot sizing:")
    h = DeltaHedgeManager()   # trigger 0.20, min 0.15
    check(h.compute_hedge(0.10, 4).action == "NONE", "delta 0.10 within tolerance → NONE")
    check(h.compute_hedge(0.18, 4).action == "NONE", "delta 0.18 below trigger → NONE")

    a = h.compute_hedge(0.25, 1)
    check(a.action == "NONE" and a.futures_lots == 0,
          "delta 0.25 on 1 lot → 0 futures (sub-lot, not hedgeable) — old bug returned 1")

    b = h.compute_hedge(0.25, 4)
    check(b.action == "HEDGE_SELL" and b.futures_lots == 1, "delta 0.25 on 4 lots → SELL 1 future")

    c = h.compute_hedge(-0.30, 4)
    check(c.action == "HEDGE_BUY" and c.futures_lots == 1, "delta -0.30 on 4 lots → BUY 1 future")

    d = h.compute_hedge(0.55, 4)
    check(d.action == "HEDGE_SELL" and d.futures_lots == 2, "delta 0.55 on 4 lots → SELL 2 futures")


def _straddle(entry=200.0, current=180.0, net_delta=0.30, dte=3, lots=4):
    legs = [StraddleLeg("CE", 22000, "SELL", lots), StraddleLeg("PE", 22000, "SELL", lots)]
    return StraddlePosition(legs=legs, entry_premium=entry, current_premium=current,
                            net_delta=net_delta, days_to_expiry=dte)


def test_theta_book_entry():
    print("ThetaBook — risk-gated entry (wires theta_risk):")
    book = ThetaBook(total_capital=1_000_000)   # book cap = 200k, max 1 straddle

    ok = book.evaluate_entry(india_vix=15, nifty_spot=22000, days_to_expiry=4,
                             is_event_week=False, open_straddles=0,
                             current_book_capital=0, new_position_capital=50_000)
    check(ok.action == "ENTER" and ok.lots == 2 and len(ok.legs) == 2, "clean conditions → ENTER 2 lots")

    conc = book.evaluate_entry(15, 22000, 4, False, open_straddles=1,
                               current_book_capital=0, new_position_capital=50_000)
    check(conc.action == "HOLD" and "risk" in conc.reason, "concurrency cap → HOLD (risk)")

    cap = book.evaluate_entry(15, 22000, 4, False, open_straddles=0,
                              current_book_capital=0, new_position_capital=300_000)
    check(cap.action == "HOLD" and "cap" in cap.reason.lower(), "book-capital cap → HOLD (risk)")

    panic = book.evaluate_entry(21, 22000, 4, False, 0, 0, 50_000)
    check(panic.action == "HOLD" and "VIX" in panic.reason, "VIX panic → HOLD (risk)")

    ev = book.evaluate_entry(15, 22000, 4, True, 0, 0, 50_000)
    check(ev.action == "HOLD" and "event" in ev.reason.lower(), "event week → HOLD (strategy)")


def test_theta_book_open():
    print("ThetaBook — open-position management:")
    book = ThetaBook(total_capital=1_000_000)

    panic = book.evaluate_open(_straddle(), india_vix=21)
    check(panic.action == "EXIT" and "risk" in panic.reason, "VIX panic → forced EXIT")

    loss = book.evaluate_open(_straddle(entry=200, current=400), india_vix=15)  # pnl_pct = -1.0
    check(loss.action == "EXIT" and "risk" in loss.reason, "hard loss (-100% premium) → forced EXIT")

    hold = book.evaluate_open(_straddle(net_delta=0.30, lots=4), india_vix=15)
    check(hold.action == "HOLD" and hold.hedge is not None and hold.hedge.action == "HEDGE_SELL"
          and hold.hedge.futures_lots == 1, "holding with delta drift → HOLD + 1-lot hedge")

    flat = book.evaluate_open(_straddle(net_delta=0.05, lots=4), india_vix=15)
    check(flat.action == "HOLD" and flat.hedge is None, "small delta → HOLD, no hedge")


def _spike_series(n=30, spike=120.0, seed=3):
    rng = np.random.default_rng(seed)
    a = 100 + rng.normal(0, 0.1, n)
    a[-1] = spike
    b = np.full(n, 100.0)
    idx = pd.RangeIndex(n)
    return pd.Series(a, index=idx), pd.Series(b, index=idx)


def test_pairs_book():
    print("PairsBook — health-gated entries (wires pairs_risk):")
    pair = ("X", "Y")
    sig = PairsSignal(pair=pair, hedge_ratio=1.0, window=20, entry_z=2.0, exit_z=0.5, stop_z=3.5)
    book = PairsBook([sig])
    a, b = _spike_series()

    enter = book.evaluate(pair, a, b, in_position=False, open_pairs_count=0)
    check(enter.action == "ENTER" and enter.leg_a_direction == "SHORT" and enter.leg_b_direction == "LONG",
          "wide spread, healthy, under cap → ENTER (short A / long B)")

    stop = book.evaluate(pair, a, b, in_position=True, open_pairs_count=0)
    check(stop.action == "STOP", "in-position diverging spread → STOP passes through (not blocked)")

    book.health._halted.add(book.health._key(*pair))
    halted = book.evaluate(pair, a, b, in_position=False, open_pairs_count=0)
    check(halted.action == "HOLD" and "halt" in halted.notes.lower(), "halted pair → ENTER suppressed to HOLD")
    book.health._halted.discard(book.health._key(*pair))

    capped = book.evaluate(pair, a, b, in_position=False, open_pairs_count=3)
    check(capped.action == "HOLD" and "max concurrent" in capped.notes.lower(),
          "at concurrent-pairs cap → ENTER suppressed to HOLD")


def main() -> int:
    print("=" * 60); print("PAIRS / THETA BOOK TESTS"); print("=" * 60)
    test_theta01_hedge_sizing()
    test_theta_book_entry()
    test_theta_book_open()
    test_pairs_book()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
