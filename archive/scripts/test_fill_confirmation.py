"""
LIVE-03 regression: place_order must confirm fills, not treat "accepted" as filled.

Covers _parse_order_status (field/`data`-wrapper variants), _poll_until_terminal
(rejection, partial, complete, and an unreadable status endpoint), and the paper-mode
OrderResult fields. No network: get_order_status is stubbed.

    .venv/bin/python scripts/test_fill_confirmation.py
    pytest scripts/test_fill_confirmation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live.openalgo_client import OpenAlgoClient

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def _client():
    c = OpenAlgoClient(api_key="k", paper=False)
    c.FILL_POLL_INTERVAL = 0.0   # don't sleep in tests
    c.FILL_POLL_RETRIES = 3
    return c


def test_parse():
    print("LIVE-03 — _parse_order_status reads liberally:")
    c = _client()
    s, q, p = c._parse_order_status({"data": {"order_status": "complete",
                                              "filled_quantity": 5, "average_price": 101.5}})
    check((s, q, p) == ("complete", 5, 101.5), "data-wrapped complete fill parsed")
    s, q, p = c._parse_order_status({"orderstatus": "REJECTED"})
    check(s == "rejected" and q == 0, "top-level rejected parsed, qty 0")
    s, q, p = c._parse_order_status({"data": [{"status": "open", "quantity": 3}]})
    check(s == "open" and q == 3, "list-wrapped data parsed")
    check(c._parse_order_status("garbage") == ("", 0, 0.0), "non-dict yields empty")


def test_poll_rejection():
    print("LIVE-03 — a post-accept rejection is NOT a fill:")
    c = _client()
    c.get_order_status = lambda oid: {"data": {"order_status": "rejected"}}
    st, filled, px = c._poll_until_terminal("OID1", requested=10)
    check(st == "rejected" and filled == 0, f"rejected → 0 filled (got {st},{filled})")


def test_poll_partial_then_complete():
    print("LIVE-03 — partial then complete is followed to terminal:")
    c = _client()
    seq = [
        {"data": {"order_status": "open", "filled_quantity": 0}},
        {"data": {"order_status": "open", "filled_quantity": 4}},
        {"data": {"order_status": "complete", "filled_quantity": 10, "average_price": 100.0}},
    ]
    calls = {"i": 0}
    def fake(oid):
        r = seq[min(calls["i"], len(seq) - 1)]; calls["i"] += 1; return r
    c.get_order_status = fake
    st, filled, px = c._poll_until_terminal("OID2", requested=10)
    check(st == "complete" and filled == 10 and px == 100.0, f"followed to complete fill (got {st},{filled},{px})")


def test_poll_unreadable_falls_back():
    print("LIVE-03 — an unreadable status endpoint falls back to assume-filled (no stranded position):")
    c = _client()
    c.get_order_status = lambda oid: {}     # endpoint gives nothing usable
    st, filled, px = c._poll_until_terminal("OID3", requested=7)
    check(filled == 7, f"assume requested qty filled when status unknown (got {filled})")


def test_paper_fields():
    print("LIVE-03 — paper order reports a full fill:")
    c = OpenAlgoClient(api_key="k", paper=True)
    r = c.place_order("RELIANCE", action="BUY", quantity=3)
    check(r.success and r.filled_qty == 3 and r.status == "complete",
          f"paper fills full qty (success={r.success}, filled={r.filled_qty})")


def main() -> int:
    print("=" * 60); print("FILL-CONFIRMATION TESTS (LIVE-03)"); print("=" * 60)
    test_parse()
    test_poll_rejection()
    test_poll_partial_then_complete()
    test_poll_unreadable_falls_back()
    test_paper_fields()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
