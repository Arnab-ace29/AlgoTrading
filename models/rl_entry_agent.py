"""
RL Entry Agent - Phase 2
Q-learning agent for entry decisions (SKIP vs ENTER) at signal-fire time.

State space (10 features, extended from the exit agent):
    composite_score        - ensemble score at signal fire
    regime_encoded         - current regime (0-3)
    time_of_day_normalized - 0.0=9:15, 1.0=15:30
    vix_normalized         - India VIX / 52-week high
    session_pnl_normalized - today PnL / daily loss limit
    open_positions_count   - how many positions already open
    volume_ratio           - current vol vs 20-day avg
    score_momentum         - score now - score 5 bars ago
    macro_model_prob       - P(bullish) from XGBoost macro model
    recent_win_rate        - last 10 trades win rate

Actions: SKIP (0), ENTER (1)
Reward:  realised PnL of the resulting trade (0 if skipped)
Activation: only after >= 50 entry decisions logged. Before that, all
            threshold-crossing signals auto-enter (handled by the caller).
"""

from __future__ import annotations
import pickle
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

import numpy as np
from loguru import logger


@dataclass
class EntryState:
    composite_score: float
    regime_encoded: int
    time_of_day: float
    vix_normalized: float
    session_pnl_normalized: float
    open_positions_count: int
    volume_ratio: float
    score_momentum: float
    macro_model_prob: float
    recent_win_rate: float


@dataclass
class EntryAction:
    action: int        # 0 = SKIP, 1 = ENTER
    confidence: float


class RLEntryAgent:
    """Tabular Q-learning agent that decides whether to act on a signal."""

    MIN_DECISIONS_TO_ACTIVATE = 50

    def __init__(self,
                 model_path: Optional[Path] = None,
                 learning_rate: float = 0.1,
                 discount_factor: float = 0.95,
                 epsilon: float = 0.1,
                 n_episodes: int = 1000):
        self.model_path = model_path or Path("models/saved/rl_entry_agent.pkl")
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.epsilon = epsilon
        self.n_episodes = n_episodes

        # Q-table: discrete state -> action values (2 actions)
        self.q_table: Dict[Tuple[int, ...], np.ndarray] = defaultdict(lambda: np.zeros(2))

        # How many real entry decisions have been logged (gates activation)
        self.decisions_logged = 0
        self.is_trained = False

        self.state_bins = {
            'composite_score': np.linspace(0.5, 1.0, 10),
            'regime': np.array([0, 1, 2, 3]),
            'time_of_day': np.linspace(0, 1, 10),
            'vix': np.linspace(0, 1, 5),
            'session_pnl': np.linspace(-1, 1, 10),
            'open_positions': np.array([0, 1, 2, 3, 4, 5]),
            'volume_ratio': np.linspace(0, 3, 10),
            'score_momentum': np.linspace(-0.5, 0.5, 10),
            'macro_prob': np.linspace(0, 1, 10),
            'win_rate': np.linspace(0, 1, 5),
        }

        if self.model_path.exists():
            self.load_model()

    # ── State handling ────────────────────────────────────────────────────
    @staticmethod
    def _bin(x: float, bins: np.ndarray) -> int:
        """Bin index clamped to [0, len(bins)-1] — never -1 (avoids wrap, RL-04)."""
        return int(np.clip(np.digitize(x, bins) - 1, 0, len(bins) - 1))

    def _discretize_state(self, state: EntryState) -> Tuple[int, ...]:
        """
        The Q-table key uses only the dimensions that are reliably populated in BOTH
        training (reconstructable from the trade log) AND live. vix / macro_model_prob
        / score_momentum can't be reconstructed post-hoc, so training would always bin
        them to a constant while live varies them — keying into different cells and
        making the learned table useless live (RL-03). They are therefore excluded.
        """
        b = self.state_bins
        return (
            self._bin(state.composite_score,        b['composite_score']),
            int(np.clip(state.regime_encoded, 0, 3)),
            self._bin(state.time_of_day,            b['time_of_day']),
            self._bin(state.volume_ratio,           b['volume_ratio']),
            self._bin(state.session_pnl_normalized, b['session_pnl']),
            int(np.clip(state.open_positions_count, 0, 5)),
            self._bin(state.recent_win_rate,        b['win_rate']),
        )

    def choose_action(self, state: EntryState, training: bool = True) -> EntryAction:
        discrete = self._discretize_state(state)
        if training and random.random() < self.epsilon:
            action = random.randint(0, 1)
            confidence = 0.5
        else:
            q_values = self.q_table[discrete]
            action = int(np.argmax(q_values))
            denom = float(np.sum(np.abs(q_values)) + 1e-8)
            confidence = float(np.max(q_values) / denom)
        return EntryAction(action=action, confidence=confidence)

    def update_q_value(self, state: EntryState, action: int, reward: float,
                       next_state: Optional[EntryState]) -> None:
        discrete = self._discretize_state(state)
        current_q = self.q_table[discrete][action]
        if next_state is None:
            max_next_q = 0.0
        else:
            max_next_q = float(np.max(self.q_table[self._discretize_state(next_state)]))
        self.q_table[discrete][action] = current_q + self.learning_rate * (
            reward + self.discount_factor * max_next_q - current_q
        )

    # ── Training ──────────────────────────────────────────────────────────
    def train_on_decisions(self, decisions: List[Dict[str, Any]],
                           count_for_activation: bool = True) -> Dict[str, Any]:
        """
        Train on logged entry decisions.

        Each decision dict: {state: EntryState, action: int, reward: float}.
        Entry decisions are single-step episodes (terminal), so next_state=None.

        count_for_activation: only REAL decisions should count toward the
        activation gate. Synthetic bootstrap data must pass False so it can't trip
        the agent live before enough real decisions exist (RL-03).
        """
        if not decisions:
            raise ValueError("No entry decisions to train on")

        logger.info(f"Training RL entry agent on {len(decisions)} decisions...")
        rewards: List[float] = []

        for episode in range(self.n_episodes):
            d = random.choice(decisions)
            self.update_q_value(d['state'], d['action'], d['reward'], None)
            rewards.append(d['reward'])
            if (episode + 1) % 200 == 0:
                logger.info(f"Episode {episode + 1}/{self.n_episodes}, "
                            f"avg reward (last 200): {np.mean(rewards[-200:]):.3f}")

        if count_for_activation:
            # Gate activation on real ENTER decisions (≈ real trades), NOT on the
            # raw decision-dict count. build_entry_decisions emits an ENTER plus a
            # counterfactual SKIP per closed trade, so counting all dicts halved the
            # effective trade bar (50 dicts == 25 trades). Counting action==1 keeps
            # MIN_DECISIONS_TO_ACTIVATE meaning "this many real trades".
            real_entries = sum(1 for d in decisions if int(d.get("action", 0)) == 1)
            self.decisions_logged = max(self.decisions_logged, real_entries)
        self.epsilon = max(self.epsilon * 0.99, 0.01)
        self.is_trained = True

        metrics = {
            'total_episodes': self.n_episodes,
            'avg_reward': float(np.mean(rewards)),
            'final_epsilon': self.epsilon,
            'q_table_size': len(self.q_table),
            'decisions_logged': self.decisions_logged,
        }
        logger.info(f"RL entry agent trained. Avg reward: {metrics['avg_reward']:.3f}")
        return metrics

    # ── Inference ─────────────────────────────────────────────────────────
    def is_active(self) -> bool:
        """Agent only overrides auto-enter once enough decisions are logged."""
        return self.is_trained and self.decisions_logged >= self.MIN_DECISIONS_TO_ACTIVATE

    def should_enter(self, state: EntryState) -> bool:
        """
        Decide whether to ENTER. Permissive by construction so the agent can only
        ever *veto contexts it has actually learned are bad* — it can never silently
        halt trading on states it has never seen.

        Two layers of permissiveness:
          1. Before activation (< MIN_DECISIONS_TO_ACTIVATE real ENTER decisions),
             always ENTER and let the rule-based system trade + accumulate data.
          2. After activation, a state cell that was NEVER visited in training (or
             whose Q-values are still all-zero, i.e. never updated) falls back to
             ENTER. A tabular Q-table over a large state space will, by definition,
             have unseen cells for most live states; an all-zero cell argmaxes to
             SKIP, so the naive `argmax==ENTER` test would veto ~100% of live
             signals the moment the agent activates. We therefore only SKIP when the
             agent has a *learned* preference for SKIP over ENTER in this exact cell.
        """
        if not self.is_active():
            return True
        discrete = self._discretize_state(state)
        q = self.q_table.get(discrete)          # .get() does NOT materialise a default
        if q is None or float(np.sum(np.abs(q))) < 1e-9:
            return True                          # never-learned cell → trust the rules
        # Learned cell: ENTER unless SKIP is strictly preferred (ties favour ENTER).
        return float(q[1]) >= float(q[0])

    def learned_cells(self) -> int:
        """Number of state cells with at least one non-zero (learned) Q-value."""
        return sum(1 for v in self.q_table.values() if float(np.sum(np.abs(v))) > 1e-9)

    def predict(self, state: EntryState) -> EntryAction:
        return self.choose_action(state, training=False)

    # ── Persistence ───────────────────────────────────────────────────────
    def save_model(self) -> None:
        if self.is_trained:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.model_path, 'wb') as f:
                pickle.dump({
                    'q_table': dict(self.q_table),
                    'state_bins': self.state_bins,
                    'epsilon': self.epsilon,
                    'is_trained': self.is_trained,
                    'decisions_logged': self.decisions_logged,
                }, f)
            logger.info(f"RL entry agent saved to {self.model_path}")

    def load_model(self) -> None:
        if self.model_path.exists():
            with open(self.model_path, 'rb') as f:
                data = pickle.load(f)
            self.q_table = defaultdict(lambda: np.zeros(2), data['q_table'])
            self.state_bins = data['state_bins']
            self.epsilon = data['epsilon']
            self.is_trained = data['is_trained']
            self.decisions_logged = data.get('decisions_logged', 0)
            logger.info(f"RL entry agent loaded from {self.model_path}")
        else:
            logger.warning(f"No RL entry agent found at {self.model_path}")


# Global agent instance (singleton)
_rl_entry_agent: Optional[RLEntryAgent] = None


def get_rl_entry_agent() -> RLEntryAgent:
    global _rl_entry_agent
    if _rl_entry_agent is None:
        _rl_entry_agent = RLEntryAgent()
    return _rl_entry_agent
