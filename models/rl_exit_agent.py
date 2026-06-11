"""
RL Exit Agent - Phase 2
Q-learning agent for optimal position exit decisions.

State space (8 features, all trade-relative):
- time_in_trade_normalized: 0.0 = just entered, 1.0 = EOD
- pnl_pct: current unrealized PnL as %
- sl_distance_pct: distance to SL as % of entry
- target_distance_pct: distance to target as % of entry
- momentum_score: current composite momentum score
- volume_trend: volume rising/falling
- regime_encoded: 0-3 for 4 regimes
- score_at_entry: original entry score

Actions: HOLD (0), EXIT_NOW (1), TIGHTEN_SL (2)
Reward: Realized PnL at episode end (when position closes)

STATUS — TRAINED BUT NOT LIVE (read before assuming RL manages exits):
    scripts/retrain_daily.py trains and persists this agent every day, but
    live/runner.py does NOT consult it — live exits are purely rule-based
    (trailing SL + SL_HIT/TARGET_HIT in runner._check_all_positions). Wiring it in
    is deferred ON PURPOSE: a tabular Q-table over this state space has many unseen
    cells, and an under-trained agent that acts on every position would mis-exit
    (the exact failure mode fixed for the ENTRY agent — see rl_entry_agent.should_enter).
    Before activating, give predict() the same guards: an is_active()/coverage gate
    and a permissive unseen-cell fallback (default HOLD), with train↔live state
    reconstruction parity. The daily retrain is kept only to warm the model.
"""

from __future__ import annotations
import pickle
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass
from collections import defaultdict
import random
from loguru import logger


@dataclass
class ExitState:
    time_in_trade: float      # 0.0 to 1.0 (normalized to session)
    pnl_pct: float           # Current PnL as percentage
    sl_distance_pct: float   # Distance to stop loss as % of entry
    target_distance_pct: float # Distance to target as % of entry
    momentum_score: float    # Current momentum score (-1 to 1)
    volume_trend: float      # Volume trend (-1 to 1)
    regime_encoded: int      # 0-3 for regimes
    score_at_entry: float    # Original entry score


@dataclass
class ExitAction:
    action: int  # 0=HOLD, 1=EXIT_NOW, 2=TIGHTEN_SL
    confidence: float  # Action confidence


class RLExitAgent:
    """
    Q-learning agent for learning optimal exit strategies.
    Uses discrete state space with epsilon-greedy exploration.
    """
    
    def __init__(self, 
                 model_path: Optional[Path] = None,
                 learning_rate: float = 0.1,
                 discount_factor: float = 0.95,
                 epsilon: float = 0.1,
                 n_episodes: int = 1000):
        
        self.model_path = model_path or Path("models/saved/rl_exit_agent.pkl")
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.epsilon = epsilon
        self.n_episodes = n_episodes
        
        # Q-table: state -> action values
        self.q_table: Dict[Tuple[int, ...], np.ndarray] = defaultdict(lambda: np.zeros(3))
        
        # State discretization bins
        self.state_bins = {
            'time_in_trade': np.linspace(0, 1, 10),
            'pnl_pct': np.linspace(-5, 5, 20),  # -5% to +5%
            'sl_distance': np.linspace(0, 3, 10),  # 0% to 3%
            'target_distance': np.linspace(0, 5, 10),  # 0% to 5%
            'momentum': np.linspace(-1, 1, 10),
            'volume_trend': np.linspace(-1, 1, 5),
            'regime': np.array([0, 1, 2, 3]),
            'entry_score': np.linspace(0.5, 1.0, 10)
        }
        
        self.is_trained = False
        self.training_history: List[Dict[str, Any]] = []
        
        # Load existing model if available
        if self.model_path.exists():
            self.load_model()
    
    @staticmethod
    def _bin(x: float, bins: np.ndarray) -> int:
        """Bin index clamped to [0, len(bins)-1] — never -1 (which would wrap to the
        top bucket and mis-bin out-of-range values, issue RL-04)."""
        return int(np.clip(np.digitize(x, bins) - 1, 0, len(bins) - 1))

    def _discretize_state(self, state: ExitState) -> Tuple[int, ...]:
        """Convert continuous state to discrete tuple for Q-table indexing."""
        b = self.state_bins
        return (
            self._bin(state.time_in_trade,        b['time_in_trade']),
            self._bin(state.pnl_pct,              b['pnl_pct']),
            self._bin(state.sl_distance_pct,      b['sl_distance']),
            self._bin(state.target_distance_pct,  b['target_distance']),
            self._bin(state.momentum_score,       b['momentum']),
            self._bin(state.volume_trend,         b['volume_trend']),
            int(np.clip(state.regime_encoded, 0, 3)),
            self._bin(state.score_at_entry,       b['entry_score']),
        )
    
    def choose_action(self, state: ExitState, training: bool = True) -> ExitAction:
        """
        Choose action using epsilon-greedy policy.
        
        Args:
            state: Current exit state
            training: Whether to use exploration (epsilon-greedy)
            
        Returns:
            ExitAction with chosen action and confidence
        """
        discrete_state = self._discretize_state(state)
        
        if training and random.random() < self.epsilon:
            # Explore: random action
            action = random.randint(0, 2)
            confidence = 0.5
        else:
            # Exploit: best action from Q-table
            q_values = self.q_table[discrete_state]
            action = np.argmax(q_values)
            confidence = float(np.max(q_values) / (np.sum(np.abs(q_values)) + 1e-8))
        
        return ExitAction(action=action, confidence=confidence)
    
    def update_q_value(self, 
                      state: ExitState, 
                      action: int, 
                      reward: float, 
                      next_state: Optional[ExitState]) -> None:
        """
        Update Q-value using Q-learning update rule.
        
        Args:
            state: Current state
            action: Action taken
            reward: Reward received
            next_state: Next state (None if terminal)
        """
        discrete_state = self._discretize_state(state)
        current_q = self.q_table[discrete_state][action]
        
        if next_state is None:
            # Terminal state
            max_next_q = 0
        else:
            discrete_next_state = self._discretize_state(next_state)
            max_next_q = np.max(self.q_table[discrete_next_state])
        
        # Q-learning update: Q(s,a) = Q(s,a) + α * (r + γ * max(Q(s',a')) - Q(s,a))
        new_q = current_q + self.learning_rate * (reward + self.discount_factor * max_next_q - current_q)
        self.q_table[discrete_state][action] = new_q
    
    def train_on_episode(self, episode_data: List[Dict[str, Any]]) -> float:
        """
        Train agent on a single episode (trade journey).
        
        Args:
            episode_data: List of step data for one complete trade
            
        Returns:
            Total reward for the episode
        """
        total_reward = 0
        
        for i, step in enumerate(episode_data):
            state = step['state']
            action = step['action']
            reward = step['reward']
            
            # Get next state (None if terminal)
            next_state = step.get('next_state')
            
            # Update Q-value
            self.update_q_value(state, action, reward, next_state)
            total_reward += reward
        
        return total_reward
    
    def train_on_historical_trades(self, trade_journeys: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Train agent on historical trade journeys.
        
        Args:
            trade_journeys: List of trade episodes, each containing step-by-step data
            
        Returns:
            Training metrics
        """
        logger.info(f"Training RL exit agent on {len(trade_journeys)} trade journeys...")
        
        episode_rewards = []
        
        for episode in range(self.n_episodes):
            # Randomly sample a trade journey
            journey = random.choice(trade_journeys)
            
            # Train on this episode
            episode_reward = self.train_on_episode(journey)
            episode_rewards.append(episode_reward)
            
            if (episode + 1) % 100 == 0:
                avg_reward = np.mean(episode_rewards[-100:])
                logger.info(f"Episode {episode + 1}/{self.n_episodes}, Avg reward (last 100): {avg_reward:.3f}")
        
        # Decay epsilon for less exploration over time
        self.epsilon *= 0.99
        self.epsilon = max(self.epsilon, 0.01)  # Minimum exploration
        
        self.is_trained = True
        
        metrics = {
            'total_episodes': self.n_episodes,
            'avg_reward': np.mean(episode_rewards),
            'final_epsilon': self.epsilon,
            'q_table_size': len(self.q_table)
        }
        
        logger.info(f"RL exit agent training completed. Avg reward: {metrics['avg_reward']:.3f}")
        return metrics
    
    def predict(self, state: ExitState) -> ExitAction:
        """
        Predict best action for current state (no exploration).
        
        Args:
            state: Current exit state
            
        Returns:
            Best ExitAction for the state
        """
        return self.choose_action(state, training=False)
    
    def save_model(self) -> None:
        """Save the trained model to disk."""
        if self.is_trained:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.model_path, 'wb') as f:
                pickle.dump({
                    'q_table': dict(self.q_table),
                    'state_bins': self.state_bins,
                    'epsilon': self.epsilon,
                    'is_trained': self.is_trained,
                    'training_history': self.training_history
                }, f)
            logger.info(f"RL exit agent saved to {self.model_path}")
    
    def load_model(self) -> None:
        """Load a trained model from disk."""
        if self.model_path.exists():
            with open(self.model_path, 'rb') as f:
                data = pickle.load(f)
                self.q_table = defaultdict(lambda: np.zeros(3), data['q_table'])
                self.state_bins = data['state_bins']
                self.epsilon = data['epsilon']
                self.is_trained = data['is_trained']
                self.training_history = data.get('training_history', [])
            logger.info(f"RL exit agent loaded from {self.model_path}")
        else:
            logger.warning(f"No RL exit agent found at {self.model_path}")


# Global agent instance (singleton pattern)
_rl_exit_agent: Optional[RLExitAgent] = None


def get_rl_exit_agent() -> RLExitAgent:
    """Get or create the global RL exit agent instance."""
    global _rl_exit_agent
    if _rl_exit_agent is None:
        _rl_exit_agent = RLExitAgent()
    return _rl_exit_agent
