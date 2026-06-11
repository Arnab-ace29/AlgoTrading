"""
RL exit agent — correctness test (TEST-01).

Rewritten from a smoke-print script into real assertions: state discretization
shape, valid action selection, a deterministic Q-update that provably moves the
value toward the reward, training that populates the Q-table, valid post-train
predictions, and a disk round-trip (temp model path so the live agent isn't
clobbered). No xgboost needed — this is a pure-numpy Q-learner.

    .venv/bin/python scripts/test_rl_exit_agent.py
Also pytest-collectable: `pytest scripts/test_rl_exit_agent.py`.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from models.rl_exit_agent import RLExitAgent, ExitState

VALID_ACTIONS = {0, 1, 2}   # HOLD / EXIT_NOW / TIGHTEN_SL


def _journeys(n: int = 12):
    """Synthetic trade journeys: HOLD until the last bar, then EXIT at the running PnL."""
    out = []
    for _ in range(n):
        dur = 5
        j = []
        for step in range(dur):
            st = ExitState(
                time_in_trade=step / dur, pnl_pct=step * 0.2,
                sl_distance_pct=2.0 - step * 0.2, target_distance_pct=3.0 - step * 0.3,
                momentum_score=0.1, volume_trend=0.0, regime_encoded=1, score_at_entry=0.7,
            )
            terminal = step == dur - 1
            j.append({
                "state": st,
                "action": 1 if terminal else 0,
                "reward": (step * 0.2) if terminal else 0.1,
                "next_state": None if terminal else st,
            })
        out.append(j)
    return out


def test_discretize_shape():
    agent = RLExitAgent(n_episodes=50)
    st = ExitState(0.5, 1.2, 1.5, 2.0, 0.3, 0.1, 1, 0.7)
    d = agent._discretize_state(st)
    assert isinstance(d, tuple), "discretized state should be a tuple (hashable Q-key)"
    assert len(d) == len(agent.state_bins), f"state dims {len(d)} != bins {len(agent.state_bins)}"


def test_action_selection_valid():
    agent = RLExitAgent(n_episodes=50)
    st = ExitState(0.5, 1.2, 1.5, 2.0, 0.3, 0.1, 1, 0.7)
    for training in (True, False):
        a = agent.choose_action(st, training=training)
        assert a.action in VALID_ACTIONS, f"invalid action {a.action}"
        assert 0.0 <= a.confidence <= 1.0, f"confidence out of range: {a.confidence}"


def test_q_update_moves_toward_reward():
    agent = RLExitAgent(n_episodes=50)
    st = ExitState(0.5, 1.2, 1.5, 2.0, 0.3, 0.1, 1, 0.7)
    d = agent._discretize_state(st)
    old_q = float(agent.q_table[d][1])
    agent.update_q_value(st, action=1, reward=1.0, next_state=None)   # terminal positive reward
    new_q = float(agent.q_table[d][1])
    assert new_q > old_q, f"Q-value should rise toward a +1 reward ({old_q} → {new_q})"
    # ...and fall toward a negative reward from a fresh agent.
    agent2 = RLExitAgent(n_episodes=50)
    agent2.update_q_value(st, action=1, reward=-1.0, next_state=None)
    assert agent2.q_table[agent2._discretize_state(st)][1] < 0, "Q-value should fall toward a -1 reward"


def test_training_populates_qtable():
    with tempfile.TemporaryDirectory() as t:
        agent = RLExitAgent(model_path=Path(t) / "rl.pkl", n_episodes=200)
        m = agent.train_on_historical_trades(_journeys(12))
        assert m["total_episodes"] == 200, f"unexpected episode count: {m['total_episodes']}"
        assert m["q_table_size"] > 0, "training learned nothing (empty Q-table)"
        assert np.isfinite(m["avg_reward"]), f"avg_reward not finite: {m['avg_reward']}"
        assert agent.is_trained, "agent should report trained"


def test_predictions_valid_after_training():
    with tempfile.TemporaryDirectory() as t:
        agent = RLExitAgent(model_path=Path(t) / "rl.pkl", n_episodes=200)
        agent.train_on_historical_trades(_journeys(12))
        states = [
            ExitState(0.1, 0.5, 1.5, 2.5, 0.2, 0.1, 1, 0.7),
            ExitState(0.8, 1.2, 0.5, 1.0, 0.8, 0.3, 0, 0.8),
            ExitState(0.5, -0.8, 0.3, 2.0, -0.5, -0.2, 2, 0.6),
        ]
        for st in states:
            a = agent.predict(st)
            assert a.action in VALID_ACTIONS, f"invalid predicted action {a.action}"
            assert 0.0 <= a.confidence <= 1.0, f"confidence out of range: {a.confidence}"


def test_persistence_roundtrip():
    with tempfile.TemporaryDirectory() as t:
        agent = RLExitAgent(model_path=Path(t) / "rl.pkl", n_episodes=200)
        agent.train_on_historical_trades(_journeys(12))
        # Capture size BEFORE any predict() — predict reads the defaultdict Q-table
        # and would insert a fresh zero-entry for an unseen state, inflating the count.
        qsize = len(agent.q_table)
        agent.save_model()
        assert (Path(t) / "rl.pkl").exists(), "model file not written"

        reloaded = RLExitAgent(model_path=Path(t) / "rl.pkl")
        assert reloaded.is_trained, "reloaded agent should report trained"
        assert len(reloaded.q_table) == qsize, f"Q-table size changed across save/load ({qsize} → {len(reloaded.q_table)})"

        # Same trained Q-table → same greedy action for any state.
        st = ExitState(0.8, 1.2, 0.5, 1.0, 0.8, 0.3, 0, 0.8)
        assert reloaded.predict(st).action == agent.predict(st).action, "reloaded agent predicts a different action"


def main() -> int:
    print("=" * 60); print("TEST-01 — RL exit agent correctness"); print("=" * 60)
    tests = [test_discretize_shape, test_action_selection_valid,
             test_q_update_moves_toward_reward, test_training_populates_qtable,
             test_predictions_valid_after_training, test_persistence_roundtrip]
    p = f = 0
    for fn in tests:
        try:
            fn(); p += 1; print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            f += 1; print(f"  ✗ {fn.__name__}: {e}")
    print("=" * 60); print(f"PASS={p}  FAIL={f}"); print("=" * 60)
    return 1 if f else 0


if __name__ == "__main__":
    raise SystemExit(main())
