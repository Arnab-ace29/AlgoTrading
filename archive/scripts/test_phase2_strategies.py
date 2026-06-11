"""
Tests for Phase 2 strategy modules: RL entry agent, pairs trading, and
theta (options selling). Uses synthetic data so it runs without SQLite or a
live broker connection.
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tempfile
import numpy as np
import pandas as pd

from models.rl_entry_agent import RLEntryAgent, EntryState
from signals.pairs.pairs_signal import PairsSignal
from signals.theta.weekly_straddle import WeeklyStraddleStrategy, StraddlePosition
from signals.theta.hedge_manager import DeltaHedgeManager
from risk.theta_risk import ThetaRiskManager
from signals.ml.strategy_outcomes import StrategyOutcomeModels


def test_rl_entry_agent() -> bool:
    print("Testing RL Entry Agent...")
    # Use an isolated temp model path so the test is reproducible and does not
    # pick up a previously-persisted (active) agent.
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / "rl_entry_test.pkl"
    agent = RLEntryAgent(model_path=tmp_path, n_episodes=200)

    # Before activation, should default to ENTER (auto-enter).
    state = EntryState(0.7, 0, 0.3, 0.4, 0.1, 1, 1.2, 0.05, 0.6, 0.5)
    assert agent.should_enter(state) is True, "should auto-enter before activation"
    print("  Auto-enter before activation: OK")

    # Build synthetic decisions: high score + bullish macro -> good reward.
    decisions = []
    rng = np.random.default_rng(42)
    for _ in range(100):
        score = rng.uniform(0.55, 0.95)
        macro = rng.uniform(0.3, 0.9)
        action = 1 if (score > 0.7 and macro > 0.55) else rng.integers(0, 2)
        # Reward positive when entering good setups, negative for bad entries.
        if action == 1:
            reward = 1.0 if (score > 0.7 and macro > 0.55) else -0.5
        else:
            reward = 0.0
        decisions.append({
            'state': EntryState(score, int(rng.integers(0, 4)), rng.uniform(0, 1),
                                rng.uniform(0, 1), rng.uniform(-1, 1),
                                int(rng.integers(0, 5)), rng.uniform(0, 3),
                                rng.uniform(-0.3, 0.3), macro, rng.uniform(0, 1)),
            'action': int(action),
            'reward': float(reward),
        })

    metrics = agent.train_on_decisions(decisions)
    print(f"  Trained: avg_reward={metrics['avg_reward']:.3f}, q_states={metrics['q_table_size']}")

    # Force activation and check it returns a boolean decision.
    agent.decisions_logged = agent.MIN_DECISIONS_TO_ACTIVATE
    decision = agent.should_enter(state)
    assert isinstance(decision, bool)
    print(f"  Active decision for strong state: {'ENTER' if decision else 'SKIP'}")

    agent.save_model()
    reloaded = RLEntryAgent(model_path=tmp_path)
    assert reloaded.is_trained, "reloaded agent should be trained"
    print("  Persistence: OK")
    return True


def _cointegrated_series(n: int = 300, seed: int = 1) -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    common = np.cumsum(rng.normal(0, 1, n)) + 100
    a = common + rng.normal(0, 1, n)
    b = common * 0.8 + 20 + rng.normal(0, 1, n)
    return pd.Series(a, index=idx), pd.Series(b, index=idx)


def test_pairs_signal() -> bool:
    print("\nTesting Pairs Signal...")
    price_a, price_b = _cointegrated_series()

    sig = PairsSignal(("A", "B"), hedge_ratio=0.8, window=20,
                      entry_z=2.0, exit_z=0.5, stop_z=3.5)

    # Normal state
    res = sig.compute(price_a, price_b, in_position=False)
    print(f"  z={res.z_score:.2f} action={res.action} legs=({res.leg_a_direction},{res.leg_b_direction})")
    assert res.action in {"ENTER", "HOLD"}

    # Force a wide spread on the last bar -> expect ENTER short A / long B.
    pa = price_a.copy()
    pa.iloc[-1] = pa.iloc[-1] + 10 * pa.tail(20).std()
    res2 = sig.compute(pa, price_b, in_position=False)
    print(f"  forced wide: z={res2.z_score:.2f} action={res2.action} "
          f"legs=({res2.leg_a_direction},{res2.leg_b_direction})")
    assert res2.action == "ENTER" and res2.leg_a_direction == "SHORT"

    # In position with normalised spread -> EXIT.
    res3 = sig.compute(price_a, price_b, in_position=True)
    print(f"  in-position: action={res3.action}")
    assert res3.action in {"EXIT", "HOLD", "STOP"}
    return True


def test_theta_strategy() -> bool:
    print("\nTesting Weekly Straddle Strategy...")
    strat = WeeklyStraddleStrategy()

    # Entry gating
    ok, reason = strat.should_enter(india_vix=15, days_to_expiry=4, is_event_week=False)
    assert ok, f"expected entry allowed, got: {reason}"
    print(f"  VIX 15, 4d, non-event -> ENTER ({reason})")

    blocked, reason = strat.should_enter(india_vix=22, days_to_expiry=4, is_event_week=False)
    assert not blocked, "high VIX should block entry"
    print(f"  VIX 22 -> blocked ({reason})")

    # Build entry
    decision = strat.build_entry(nifty_spot=22480, india_vix=15,
                                 days_to_expiry=4, is_event_week=False)
    assert decision.action == "ENTER" and len(decision.legs) == 2
    print(f"  Entry: {decision.reason}; strikes={[l.strike for l in decision.legs]}")

    # Sizing band
    assert strat.vix_to_lots(12) == 1
    assert strat.vix_to_lots(16) == 2
    assert strat.vix_to_lots(25) == 0
    print("  VIX->lots sizing: OK")

    # Exit on profit target
    pos = StraddlePosition(
        legs=decision.legs, entry_premium=200.0, current_premium=90.0,
        net_delta=0.1, days_to_expiry=2,
    )
    exit_now, reason = strat.should_exit(pos, india_vix=15)
    assert exit_now, "should exit at >=50% profit"
    print(f"  Profit-target exit: {reason} (pnl={pos.pnl_pct:.0%})")

    # Exit on VIX spike
    pos2 = StraddlePosition(decision.legs, 200.0, 210.0, 0.1, 3)
    exit2, reason2 = strat.should_exit(pos2, india_vix=21)
    assert exit2, "VIX spike must force exit"
    print(f"  VIX-spike exit: {reason2}")
    return True


def test_hedge_and_risk() -> bool:
    print("\nTesting Hedge Manager + Theta Risk...")
    hedger = DeltaHedgeManager()

    # compute_hedge(net_delta, position_lots) — THETA-01: hedge size scales with
    # how many straddle lots are held (futures_lots = round(net_delta × position_lots)).
    assert hedger.compute_hedge(0.05, 10).action == "NONE"            # within tolerance
    assert hedger.compute_hedge(0.30, 10).action == "HEDGE_SELL"      # +0.30 × 10 → sell 3 fut
    assert hedger.compute_hedge(-0.30, 10).action == "HEDGE_BUY"      # -0.30 × 10 → buy 3 fut
    assert hedger.compute_hedge(0.30, 1).action == "NONE"            # 0.30 × 1 < 1 fut → not hedgeable
    print("  Hedge decisions: OK")

    risk = ThetaRiskManager(total_capital=1_000_000)
    ok, reason = risk.can_enter(india_vix=15, open_straddles=0,
                                current_book_capital=0, new_position_capital=100_000)
    assert ok, reason
    print(f"  Entry allowed within book cap: {reason}")

    blocked, reason = risk.can_enter(india_vix=15, open_straddles=0,
                                     current_book_capital=150_000,
                                     new_position_capital=100_000)
    assert not blocked, "should block when exceeding 20% book cap"
    print(f"  Book-cap guard: {reason}")

    force, reason = risk.must_force_exit(india_vix=21, position_pnl_pct=-0.2)
    assert force, "VIX panic must force exit"
    print(f"  Force-exit on VIX panic: {reason}")
    return True


def test_strategy_outcomes() -> bool:
    print("\nTesting Strategy Outcome Models...")
    rng = np.random.default_rng(11)
    n = 60
    # Synthetic: high rsi + positive macd_hist -> more likely WIN.
    rsi = rng.uniform(20, 80, n)
    macd = rng.normal(0, 0.5, n)
    win = ((rsi > 55) & (macd > 0)).astype(int)
    # Inject noise so both classes exist regardless of thresholds.
    flip = rng.random(n) < 0.15
    win = np.where(flip, 1 - win, win)
    df = pd.DataFrame({"rsi_14": rsi, "macd_hist": macd, "win": win})

    tmp = Path(tempfile.mkdtemp()) / "outcomes_test.pkl"
    models = StrategyOutcomeModels(model_path=tmp, win_threshold=0.55)

    # Below the minimum trade count -> gate stays open.
    small = df.head(10)
    res_skipped = models.train_strategy("vwap_breakout", small, ["rsi_14", "macd_hist"])
    assert res_skipped is None, "should skip training with <15 trades"
    open_gate = models.predict("vwap_breakout", df.tail(1))
    assert open_gate.should_enter and not open_gate.is_reliable
    print("  Gate open before model exists: OK")

    metrics = models.train_strategy("vwap_breakout", df, ["rsi_14", "macd_hist"])
    assert metrics is not None and metrics["n_trades"] == n
    print(f"  Trained outcome model: n={metrics['n_trades']} acc={metrics['accuracy']:.3f}")

    # A strong-looking setup should produce a reliable probability.
    strong = pd.DataFrame({"rsi_14": [70.0], "macd_hist": [0.4]})
    res = models.predict("vwap_breakout", strong)
    assert res.is_reliable and 0.0 <= res.win_probability <= 1.0
    print(f"  Reliable prediction: P(win)={res.win_probability:.3f} enter={res.should_enter}")

    models.save_model()
    reloaded = StrategyOutcomeModels(model_path=tmp)
    assert "vwap_breakout" in reloaded.models
    print("  Persistence: OK")
    return True


if __name__ == "__main__":
    print("Phase 2 Strategy Modules Test\n" + "=" * 40)
    try:
        test_rl_entry_agent()
        test_pairs_signal()
        test_theta_strategy()
        test_hedge_and_risk()
        test_strategy_outcomes()
        print("\nAll Phase 2 strategy tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
