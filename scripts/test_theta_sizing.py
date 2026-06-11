"""
THETA-02 regression: WeeklyStraddleStrategy.vix_to_lots must be driven by the
configured VIX bounds, not hardcoded 11/14/18/20.

Before: the method hardcoded the thresholds, so constructing the strategy with
different vix_floor/full_size/ceiling/panic had no effect on sizing.

    .venv/bin/python scripts/test_theta_sizing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signals.theta.weekly_straddle import WeeklyStraddleStrategy

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def main() -> int:
    print("=" * 60); print("THETA-02 — vix_to_lots is config-driven"); print("=" * 60)

    # ── Defaults (11 / 14 / 18 / 20) must reproduce the original bands ─────────
    d = WeeklyStraddleStrategy()
    default_cases = [(10.0, 0), (11.0, 1), (13.99, 1), (14.0, 2),
                     (17.99, 2), (18.0, 1), (19.99, 1), (20.0, 0), (25.0, 0)]
    for vix, want in default_cases:
        check(d.vix_to_lots(vix) == want, f"default: VIX {vix} → {want} lot(s) (got {d.vix_to_lots(vix)})")

    # ── Custom bounds must SHIFT the bands (proves it reads config) ───────────
    c = WeeklyStraddleStrategy(vix_floor=12, vix_full_size=15, vix_ceiling=20, vix_panic=24)
    custom_cases = [(11.0, 0), (12.0, 1), (14.99, 1), (15.0, 2),
                    (19.99, 2), (20.0, 1), (23.99, 1), (24.0, 0)]
    for vix, want in custom_cases:
        check(c.vix_to_lots(vix) == want, f"custom:  VIX {vix} → {want} lot(s) (got {c.vix_to_lots(vix)})")

    # Same VIX, different config → different size (the bug: this used to be identical).
    check(d.vix_to_lots(19.0) == 1 and c.vix_to_lots(19.0) == 2,
          f"VIX 19 sizes by config (default={d.vix_to_lots(19.0)}, custom={c.vix_to_lots(19.0)})")

    # ── full_size clamp keeps bands ordered even if mis-configured ────────────
    hi = WeeklyStraddleStrategy(vix_full_size=99.0)   # clamped down to the ceiling (18)
    check(hi.vix_full_size == hi.vix_ceiling, f"full_size clamped to ceiling ({hi.vix_full_size})")
    check(hi.vix_to_lots(16.0) == 1, "full_size≥ceiling → no 2-lot band (16 → 1 lot)")

    lo = WeeklyStraddleStrategy(vix_full_size=5.0)    # clamped up to the floor (11)
    check(lo.vix_full_size == lo.vix_floor, f"full_size clamped to floor ({lo.vix_full_size})")
    check(lo.vix_to_lots(12.0) == 2, "full_size≤floor → full size from the floor up (12 → 2 lots)")

    # Panic bound is config-driven too.
    p = WeeklyStraddleStrategy(vix_panic=30.0)
    check(p.vix_to_lots(25.0) == 1, "raising vix_panic lets 25 still trade (→ 1 lot in elevated band)")
    check(d.vix_to_lots(25.0) == 0, "default panic=20 blocks 25 (→ 0 lots)")

    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
