"""
Tests for the RL agent fixes (RL-01..04).

Pure numpy + the journey builder — no xgboost needed:
    .venv/bin/python scripts/test_rl_agents.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from models.rl_exit_agent import RLExitAgent, ExitState
from models.rl_entry_agent import RLEntryAgent, EntryState
from models.train_rl_on_journeys import _build_journey, HOLD, EXIT_NOW, TIGHTEN_SL

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def _journey(direction: str, n: int = 12):
    """Build a clean winning/losing long journey from a monotonic price path."""
    entry = 100.0
    if direction == "win":
        closes = np.linspace(100, 110, n)
    else:
        closes = np.linspace(100, 90, n)
    highs = closes * 1.002
    lows = closes * 0.998
    vols = np.full(n, 1000.0)
    final = (closes[-1] - entry) / entry * 100.0
    return _build_journey(closes, highs, lows, vols, entry, 95.0, 105.0, 0.7, 0, True, final)


def _train_exit(journey, sweeps=1500):
    a = RLExitAgent()
    for _ in range(sweeps):
        a.train_on_episode(journey)
    return a


def test_rl01_td_backup():
    print("RL-01 — terminal reward propagates (TD backup):")
    win = _journey("win")
    a = _train_exit(win)
    s0 = win[0]["state"]                       # HOLD transition at bar 0
    q0 = a.q_table[a._discretize_state(s0)]
    check(q0[HOLD] > 0.5, f"winning trade → early HOLD value is positive ({q0[HOLD]:.2f})")

    loss = _journey("loss")
    b = _train_exit(loss)
    ls0 = loss[0]["state"]
    lq0 = b.q_table[b._discretize_state(ls0)]
    check(lq0[EXIT_NOW] > lq0[HOLD], f"losing trade → EXIT-now beats HOLD early (cut losers) "
                                     f"(exit={lq0[EXIT_NOW]:.2f} hold={lq0[HOLD]:.2f})")


def test_rl02_all_actions_trained():
    print("RL-02 — EXIT and TIGHTEN actions are actually trained:")
    a = _train_exit(_journey("win"))
    exit_trained = sum(1 for v in a.q_table.values() if abs(v[EXIT_NOW]) > 1e-6)
    tighten_trained = sum(1 for v in a.q_table.values() if abs(v[TIGHTEN_SL]) > 1e-6)
    check(exit_trained > 0, f"EXIT_NOW has learned Q-values in {exit_trained} states")
    check(tighten_trained > 0, f"TIGHTEN_SL has learned Q-values in {tighten_trained} states")


def test_rl04_bin_clamp():
    print("RL-04 — out-of-range values clamp (no -1 wrap):")
    a = RLExitAgent()
    lo = a._discretize_state(ExitState(0.0, -999, -999, -999, -5, -5, 0, 0.0))
    hi = a._discretize_state(ExitState(2.0, 999, 999, 999, 5, 5, 3, 2.0))
    check(all(i >= 0 for i in lo), "below-range state bins are all >= 0 (not -1)")
    check(lo[1] == 0, "very negative pnl clamps to bin 0")
    check(hi[1] == len(a.state_bins['pnl_pct']) - 1, "very positive pnl clamps to top bin")


def _estate(**kw):
    base = dict(composite_score=0.7, regime_encoded=0, time_of_day=0.5, vix_normalized=0.5,
                session_pnl_normalized=0.0, open_positions_count=0, volume_ratio=1.0,
                score_momentum=0.0, macro_model_prob=0.5, recent_win_rate=0.5)
    base.update(kw)
    return EntryState(**base)


def test_rl03_entry_state_key():
    print("RL-03 — entry state keys only on reliably-populated dims:")
    a = RLEntryAgent()
    k = a._discretize_state(_estate())
    check(len(k) == 7, f"state key has 7 dims (dropped vix/macro/score_momentum) — got {len(k)}")

    # differing ONLY in non-key dims → same cell (train/live consistency)
    same = a._discretize_state(_estate(vix_normalized=0.9, macro_model_prob=0.9, score_momentum=0.4))
    check(same == k, "vix/macro/score_momentum do NOT change the Q-table key")

    # differing in a reconstructed key dim → different cell
    diff = a._discretize_state(_estate(recent_win_rate=0.95))
    check(diff != k, "recent_win_rate DOES change the key (reconstructed dim is used)")


def test_rl03_activation_gate():
    print("RL-03 — synthetic data doesn't trip the activation gate:")
    synth = [{"state": _estate(composite_score=0.8), "action": 1, "reward": 1.0} for _ in range(60)]
    a = RLEntryAgent(n_episodes=50)
    a.train_on_decisions(synth, count_for_activation=False)
    check(a.is_trained and not a.is_active(), "trained on synthetic but NOT active (gate not tripped)")

    b = RLEntryAgent(n_episodes=50)
    b.train_on_decisions(synth, count_for_activation=True)
    check(b.is_active(), "real decisions (>=50) DO activate the agent")


def test_rl_entry_permissive_unseen():
    print("RL entry — activated agent is PERMISSIVE on unseen / unlearned cells (P0):")
    # Train on a handful of REAL winning ENTER decisions in ONE narrow context.
    ctx = dict(composite_score=0.72, regime_encoded=0, time_of_day=0.5,
               volume_ratio=1.0, session_pnl_normalized=0.0,
               open_positions_count=0, recent_win_rate=0.6)
    winners = [{"state": _estate(**ctx), "action": 1, "reward": 2.0} for _ in range(60)]
    a = RLEntryAgent(n_episodes=300, epsilon=0.0)
    a.train_on_decisions(winners, count_for_activation=True)
    check(a.is_active(), "agent activates on 60 real ENTER decisions")

    # A completely different (never-seen) live state must NOT be vetoed.
    n_seen, n_enter = 0, 0
    rng = np.random.default_rng(0)
    for _ in range(500):
        s = _estate(composite_score=float(rng.uniform(0.55, 1.0)),
                    regime_encoded=int(rng.integers(0, 4)),
                    time_of_day=float(rng.uniform(0, 1)),
                    volume_ratio=float(rng.uniform(0, 3)),
                    recent_win_rate=float(rng.uniform(0, 1)))
        if a.should_enter(s):
            n_enter += 1
    check(n_enter >= 490, f"unseen live states overwhelmingly ENTER (rule-based fallback): {n_enter}/500")

    # A LEARNED losing context IS vetoed (the agent still adds value).
    loser_ctx = dict(ctx); loser_ctx["composite_score"] = 0.66
    losers = [{"state": _estate(**loser_ctx), "action": 1, "reward": -3.0} for _ in range(60)]
    a.train_on_decisions(losers, count_for_activation=True)
    check(not a.should_enter(_estate(**loser_ctx)), "a context learned to be a loser IS vetoed")
    check(a.should_enter(_estate(**ctx)), "the winning context still ENTERs")


def main() -> int:
    print("=" * 60); print("RL AGENT TESTS"); print("=" * 60)
    test_rl01_td_backup()
    test_rl02_all_actions_trained()
    test_rl04_bin_clamp()
    test_rl03_entry_state_key()
    test_rl03_activation_gate()
    test_rl_entry_permissive_unseen()
    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
