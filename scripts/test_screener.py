"""
Tests for the pre-market screener.

The scoring core (ranking_features, universe, catalyst_detector) is pure
numpy/stdlib and is tested fully here. The DailyScreener orchestration test is
guarded — it runs only where pandas/sqlite/settings are importable.

    python scripts/test_screener.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from screener.ranking_features import compute_metrics, momentum_rank, screener_score, WEIGHTS, MIN_BARS
from screener.universe import get_universe, universe_for_strategy, STRATEGY_UNIVERSE
from screener.catalyst_detector import get_catalyst_score

PASS, FAIL = 0, 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ FAIL: {msg}")


def _series(n: int, start: date, *, trend: float, vol_spike_last: float = 1.0):
    """Deterministic daily OHLCV: linear close trend, ±1 wick, flat volume w/ optional last spike."""
    dates, o, h, l, c, v = [], [], [], [], [], []
    for i in range(n):
        close = 100.0 + trend * i
        dates.append(start + timedelta(days=i))
        o.append(close)
        h.append(close + 1.0)
        l.append(close - 1.0)
        c.append(close)
        v.append(1000.0)
    if v:
        v[-1] = 1000.0 * vol_spike_last
    return dates, o, h, l, c, v


def test_compute_metrics():
    print("compute_metrics:")
    start = date(2026, 1, 1)
    n = 60
    asof = start + timedelta(days=55)   # uses bars 0..54

    d, o, h, l, c, v = _series(n, start, trend=1.0, vol_spike_last=1.0)
    # vol spike on the last USED bar (index 54), not the array end:
    v[54] = 3000.0
    m = compute_metrics(d, o, h, l, c, v, asof)
    check(m is not None, "returns metrics for a sufficient uptrend series")
    check(m["ret_20d"] > 0, "20-day return positive in an uptrend")
    check(m["above_sma20"] is True, "close above SMA20 in an uptrend")
    check(m["technical_setup"] > 0.5, "technical_setup high near 20-day high")
    check(m["volume_surge"] > 0.0, "volume_surge > 0 when last bar volume spikes")

    short_d, short_o, short_h, short_l, short_c, short_v = _series(MIN_BARS - 1, start, trend=1.0)
    check(compute_metrics(short_d, short_o, short_h, short_l, short_c, short_v,
                          start + timedelta(days=MIN_BARS)) is None,
          "returns None when fewer than MIN_BARS usable bars")


def test_no_lookahead():
    print("no look-ahead:")
    start = date(2026, 1, 1)
    asof = start + timedelta(days=55)

    full = _series(60, start, trend=1.0)
    trunc = tuple(x[:55] for x in full)          # exactly the bars < asof
    extended = _series(70, start, trend=1.0)     # 10 extra FUTURE bars after asof

    m_full = compute_metrics(*full, asof)
    m_trunc = compute_metrics(*trunc, asof)
    m_ext = compute_metrics(*extended, asof)
    check(m_full == m_trunc, "metrics identical whether or not pre-asof bars are truncated")
    check(m_full == m_ext, "appending future bars does not change metrics (no look-ahead)")


def test_momentum_rank():
    print("momentum_rank:")
    r = momentum_rank([0.1, 0.2, 0.3])
    check(r[0] < r[1] < r[2], "ranks increase with value")
    check(abs(r[2] - (2 + 0.5) / 3) < 1e-9, "top value gets the highest mid-rank percentile")
    r2 = momentum_rank([0.5, None, 0.1])
    check(r2[1] is None, "None passes through")
    check(r2[0] > r2[2], "ranking ignores None entries")


def test_screener_score():
    print("screener_score:")
    check(abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "weights sum to 1.0")
    check(screener_score(1, 1, 1, 1, 1) == 1.0, "all-max inputs → 1.0")
    check(screener_score(0, 0, 0, 0, 0) == 0.0, "all-zero inputs → 0.0")
    only_mom = screener_score(0, 1, 0, 0, 0)
    check(abs(only_mom - WEIGHTS["momentum_rank"]) < 1e-9, "isolated momentum contributes its weight")

    # Event-risk suppression must actually rank a name BELOW a neutral one (catalyst
    # clamp fix): identical features, one with a -0.3 board-meeting catalyst.
    neutral = screener_score(0.6, 0.6, 0.6, 0.6, 0.0)
    event_risk = screener_score(0.6, 0.6, 0.6, 0.6, -0.3)
    check(event_risk < neutral, f"event-risk name ranks below neutral ({event_risk} < {neutral})")


def test_catalyst():
    print("catalyst_detector:")
    asof = date(2026, 6, 5)
    table = {
        "AAA": {"earnings_date": "2026-06-07"},
        "BBB": {"board_meeting_today": True},
        "CCC": {"bulk_deal_buy": True, "fii_net_buy_cr": 800},
    }
    s_a, _ = get_catalyst_score("AAA", asof, table)
    s_b, _ = get_catalyst_score("BBB", asof, table)
    s_c, _ = get_catalyst_score("CCC", asof, table)
    s_none, reasons = get_catalyst_score("ZZZ", asof, table)
    check(abs(s_a - 0.3) < 1e-9, "earnings within 3 days → +0.3")
    check(abs(s_b + 0.3) < 1e-9, "board meeting today → -0.3 (event risk)")
    check(abs(s_c - 0.4) < 1e-9, "bulk deal + FII buy → +0.4")
    check(s_none == 0.0 and reasons == [], "unknown symbol → neutral")


def test_metrics_guards():
    print("compute_metrics guards:")
    asof = date(2026, 6, 5)
    n = 30
    dates = [date(2026, 4, 1) + timedelta(days=i) for i in range(n)]
    o = [100.0] * n; h = [101.0] * n; l = [99.0] * n; c = [100.0] * n
    # Flat volume except a 5× spike on the LAST (most recent) bar.
    v = [1000.0] * n; v[-1] = 5000.0
    m = compute_metrics(dates, o, h, l, c, v, asof)
    # Baseline excludes the current bar → surge ≈ 5.0 (not the ~4.17 self-contaminated value).
    check(m is not None and abs(m["vol_surge"] - 5.0) < 1e-6,
          f"volume surge uses the prior-bar baseline (got {None if m is None else m['vol_surge']})")

    # A zero interior close must reject the symbol (no +inf return ranking top).
    c_bad = [100.0] * n; c_bad[-21] = 0.0
    check(compute_metrics(dates, o, h, l, c_bad, v, asof) is None,
          "a zero interior close is rejected (no inf return)")


def test_universe():
    print("universe:")
    n50 = get_universe("nifty50")
    check(len(n50) >= 40, "nifty50 has a real constituent list")
    check("RELIANCE" in n50 and "TCS" in n50, "contains expected large caps")
    check(len(get_universe("nifty100")) > len(n50), "nifty100 is a superset of nifty50")
    check(universe_for_strategy("momentum_vwap") == get_universe("nifty50"),
          "momentum_vwap maps to nifty50")
    check(set(STRATEGY_UNIVERSE) >= {"momentum_vwap", "rsi_momentum", "mean_reversion"},
          "strategy→universe map covers the core books")


def test_orchestrator_guarded():
    print("DailyScreener (guarded — needs pandas/settings):")
    try:
        from screener import daily_screener as ds
    except Exception as e:
        print(f"  ~ SKIP (deps unavailable: {type(e).__name__})")
        return

    start = date(2026, 1, 1)
    asof = start + timedelta(days=80)

    # Best = strong trend + big volume; Mid = mild trend; Flat = no trend; Short = insufficient.
    fixtures = {
        "BEST": _series(80, start, trend=2.0, vol_spike_last=4.0),
        "MID":  _series(80, start, trend=0.5, vol_spike_last=1.0),
        "FLAT": _series(80, start, trend=0.0, vol_spike_last=1.0),
        "SHORT": _series(5, start, trend=1.0),
    }

    def loader(symbol, _asof, _lookback):
        return fixtures.get(symbol)

    # Point the universe at our fixtures and writes at a temp dir.
    ds.universe_for_strategy = lambda strat: ["BEST", "MID", "FLAT", "SHORT"]
    with tempfile.TemporaryDirectory() as tmp:
        ds.DAILY_WATCHLIST_PATH = Path(tmp) / "daily_watchlist.json"
        ds._BREAKDOWN_PATH = Path(tmp) / "screener_breakdown.json"
        screener = ds.DailyScreener(top_n=3, loader=loader)
        watchlist, breakdown = screener.run(asof=asof, strategies=["momentum_vwap"])

        wl = watchlist["momentum_vwap"]
        check(len(wl) >= 2, "ranked at least 2 symbols")
        check(wl[0] == "BEST", "strongest trend + volume ranks first")
        check("SHORT" not in wl, "insufficient-data symbol excluded")
        check((Path(tmp) / "daily_watchlist.json").exists(), "watchlist file written")
        check(breakdown["momentum_vwap"][0]["score"] >= breakdown["momentum_vwap"][-1]["score"],
              "breakdown sorted by score desc")


def main() -> int:
    print("=" * 60)
    print("SCREENER TESTS")
    print("=" * 60)
    test_compute_metrics()
    test_no_lookahead()
    test_momentum_rank()
    test_screener_score()
    test_catalyst()
    test_metrics_guards()
    test_universe()
    test_orchestrator_guarded()
    print("=" * 60)
    print(f"PASS={PASS}  FAIL={FAIL}")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
