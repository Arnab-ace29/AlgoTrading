"""
Training script for RL Exit Agent
Trains Q-learning agent on historical trade journeys.

Usage:
    python models/train_rl_on_journeys.py
"""

from __future__ import annotations
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from loguru import logger
from models.rl_exit_agent import RLExitAgent, ExitState
from data.db import get_trade_log, read_candles


# Map regime strings (regime_at_entry) to the encoded ints the agent expects.
_REGIME_ENCODING = {
    "TRENDING_UP": 0,
    "TRENDING_DOWN": 1,
    "MEAN_REVERTING": 2,
    "CHOPPY": 3,
}


# Exit actions and the counterfactual tighten model.
HOLD, EXIT_NOW, TIGHTEN_SL = 0, 1, 2
TIGHTEN_FRAC = 0.003     # tightening moves the stop to ~0.3% below (long) / above (short) price
HOLD_STEP_REWARD = 0.0   # intermediate HOLD reward; terminal value flows in via the TD backup


def _rollout_tighten(closes, highs, lows, entry_price, is_long, i, final_pnl_pct) -> float:
    """
    Counterfactual realised pnl% if you TIGHTEN the stop at bar i: move the stop
    just behind the current price and ride the actual candle path. If a later bar
    pierces the tightened stop you exit there; otherwise you reach the final close.
    """
    def pnl(price):
        return ((price - entry_price) if is_long else (entry_price - price)) / entry_price * 100.0

    n = len(closes)
    if i >= n - 1:
        return pnl(closes[i])   # no future → equivalent to exiting now
    cur = closes[i]
    if is_long:
        new_sl = cur * (1 - TIGHTEN_FRAC)
        for j in range(i + 1, n):
            if lows[j] <= new_sl:
                return pnl(new_sl)
    else:
        new_sl = cur * (1 + TIGHTEN_FRAC)
        for j in range(i + 1, n):
            if highs[j] >= new_sl:
                return pnl(new_sl)
    return final_pnl_pct


def _build_journey(closes, highs, lows, volumes, entry_price, sl, target,
                   entry_score, regime_enc, is_long, final_pnl_pct) -> list[dict]:
    """
    Build a training journey for ONE trade as off-policy transitions.

    Per bar we emit three transitions so Q-learning sees every action (RL-02):
      • HOLD  — continue to the NEXT bar's state (TD backup, RL-01); the last bar's
                HOLD is the forced close with the realised pnl as terminal reward.
      • EXIT_NOW — terminal, reward = pnl locked in at this bar's close.
      • TIGHTEN_SL — terminal, reward = counterfactual tighten rollout on the path.
    """
    n = len(closes)

    def pnl_at(price):
        return ((price - entry_price) if is_long else (entry_price - price)) / entry_price * 100.0

    states: list[ExitState] = []
    for i in range(n):
        p = closes[i]
        if is_long:
            sl_dist = (p - sl) / entry_price * 100.0
            tgt_dist = (target - p) / entry_price * 100.0
        else:
            sl_dist = (sl - p) / entry_price * 100.0
            tgt_dist = (p - target) / entry_price * 100.0
        momentum = float(np.sign(closes[i] - closes[i - 1])) if i > 0 else 0.0
        vol_trend = 0.0
        if i > 0 and volumes[i - 1] > 0:
            vol_trend = float(np.clip((volumes[i] - volumes[i - 1]) / volumes[i - 1], -1, 1))
        states.append(ExitState(
            time_in_trade=i / max(n - 1, 1),
            pnl_pct=pnl_at(p),
            sl_distance_pct=sl_dist,
            target_distance_pct=tgt_dist,
            momentum_score=momentum,
            volume_trend=vol_trend,
            regime_encoded=regime_enc,
            score_at_entry=entry_score,
        ))

    journey: list[dict] = []
    for i in range(n):
        s = states[i]
        # HOLD → next bar (terminal forced-close at the last bar)
        if i < n - 1:
            journey.append({"state": s, "action": HOLD, "reward": HOLD_STEP_REWARD,
                            "next_state": states[i + 1]})
        else:
            journey.append({"state": s, "action": HOLD, "reward": final_pnl_pct, "next_state": None})
        # EXIT_NOW → lock in current pnl (terminal)
        journey.append({"state": s, "action": EXIT_NOW, "reward": pnl_at(closes[i]), "next_state": None})
        # TIGHTEN_SL → counterfactual tightened-stop outcome (terminal)
        journey.append({"state": s, "action": TIGHTEN_SL,
                        "reward": _rollout_tighten(closes, highs, lows, entry_price, is_long, i, final_pnl_pct),
                        "next_state": None})
    return journey


def build_journeys_from_trade_log(min_bars: int = 2) -> list[list[dict]]:
    """
    Reconstruct per-bar exit journeys from closed trades in the trade_log.

    For each closed trade we read the 5-min candles spanning entry->exit and emit
    HOLD/EXIT/TIGHTEN transitions per bar (see _build_journey). Returns an empty
    list if there are no usable closed trades.
    """
    trades = get_trade_log(limit=5000)
    if trades.empty:
        return []

    closed = trades[trades["status"] == "CLOSED"].copy()
    journeys: list[list[dict]] = []

    for _, t in closed.iterrows():
        entry_price = t.get("entry_price")
        exit_time = t.get("exit_time")
        entry_time = t.get("entry_time")
        if not entry_price or entry_time is None or exit_time is None:
            continue

        side = str(t.get("side", "BUY")).upper()
        is_long = side in ("BUY", "LONG")
        entry_price = float(entry_price)
        sl = float(t.get("sl_price") or entry_price)
        target = float(t.get("target_price") or entry_price)
        entry_score = float(t.get("entry_score") or 0.6)
        regime_enc = _REGIME_ENCODING.get(str(t.get("regime_at_entry", "")), 3)
        final_pnl_pct = float(t.get("pnl_pct") or 0.0) * 100.0  # stored as fraction

        candles = read_candles(t["symbol"], timeframe="5min", from_dt=entry_time, to_dt=exit_time)
        if candles.empty or len(candles) < min_bars:
            continue

        closes = candles["close"].to_numpy(dtype=float)
        highs = candles["high"].to_numpy(dtype=float)
        lows = candles["low"].to_numpy(dtype=float)
        volumes = candles["volume"].to_numpy(dtype=float)

        journey = _build_journey(closes, highs, lows, volumes, entry_price, sl, target,
                                 entry_score, regime_enc, is_long, final_pnl_pct)
        if journey:
            journeys.append(journey)

    logger.info(f"Reconstructed {len(journeys)} journeys from trade_log")
    return journeys


def create_synthetic_trade_journeys(n_journeys: int = 1000, seed: int = 13) -> list[list[dict]]:
    """
    Synthetic bootstrap journeys with a COHERENT simulated price path (random walk
    to a final outcome), built with the same HOLD/EXIT/TIGHTEN structure as the real
    ones — so the bootstrap teaches the right value structure, not random-action noise.
    """
    logger.info(f"Creating {n_journeys} synthetic trade journeys...")
    rng = np.random.default_rng(seed)
    journeys = []

    for _ in range(n_journeys):
        entry_price = 1000 + rng.standard_normal() * 100
        is_long = bool(rng.random() < 0.5)
        dur = int(rng.integers(5, 50))
        drift = rng.normal(0, 0.002)
        rets = rng.normal(drift, 0.004, dur)
        closes = entry_price * np.cumprod(1 + rets)
        highs = closes * (1 + np.abs(rng.normal(0, 0.0015, dur)))
        lows = closes * (1 - np.abs(rng.normal(0, 0.0015, dur)))
        volumes = rng.integers(1000, 9000, dur).astype(float)
        sl = entry_price * (0.99 if is_long else 1.01)
        target = entry_price * (1.02 if is_long else 0.98)
        entry_score = 0.6 + rng.random() * 0.3
        regime_enc = int(rng.integers(0, 4))
        final_pnl_pct = ((closes[-1] - entry_price) if is_long else (entry_price - closes[-1])) / entry_price * 100.0

        journeys.append(_build_journey(closes, highs, lows, volumes, entry_price, sl, target,
                                       entry_score, regime_enc, is_long, final_pnl_pct))

    logger.info(f"Created {len(journeys)} synthetic trade journeys")
    return journeys


def train_and_evaluate():
    """Main training and evaluation pipeline."""
    logger.info("Starting RL Exit Agent Training")
    
    try:
        # Reconstruct journeys from the real trade_log; fall back to synthetic
        # when there is not enough live trade history yet.
        MIN_REAL_JOURNEYS = 20
        try:
            journeys = build_journeys_from_trade_log()
        except Exception as e:
            logger.warning(f"Could not reconstruct journeys from trade_log: {e}")
            journeys = []

        if len(journeys) >= MIN_REAL_JOURNEYS:
            logger.info(f"Training on {len(journeys)} reconstructed trade journeys")
        else:
            logger.warning(
                f"Only {len(journeys)} real journeys (<{MIN_REAL_JOURNEYS}); "
                "using synthetic journeys for bootstrap training."
            )
            journeys = create_synthetic_trade_journeys(n_journeys=500)
        
        if not journeys:
            raise ValueError("No trade journeys available for training")
        
        # Create and train agent
        agent = RLExitAgent(n_episodes=1000)  # Reduced for testing
        metrics = agent.train_on_historical_trades(journeys)
        
        # Print results
        print("\n" + "="*60)
        print("RL EXIT AGENT TRAINING RESULTS")
        print("="*60)
        print(f"Total Episodes: {metrics['total_episodes']}")
        print(f"Average Reward: {metrics['avg_reward']:.4f}")
        print(f"Final Epsilon: {metrics['final_epsilon']:.4f}")
        print(f"Q-table Size: {metrics['q_table_size']} states")
        
        # Test agent on sample states
        print("\nTesting agent on sample states:")
        test_states = [
            ExitState(0.1, 0.5, 1.5, 2.5, 0.2, 0.1, 1, 0.7),  # Early trade, small profit
            ExitState(0.8, 1.2, 0.5, 1.0, 0.8, 0.3, 0, 0.8),  # Late trade, good profit
            ExitState(0.5, -0.8, 0.3, 2.0, -0.5, -0.2, 2, 0.6),  # Mid trade, loss
        ]
        
        action_names = {0: "HOLD", 1: "EXIT_NOW", 2: "TIGHTEN_SL"}
        
        for i, state in enumerate(test_states):
            action = agent.predict(state)
            print(f"  Test {i+1}: {action_names[action.action]} (confidence: {action.confidence:.3f})")
        
        # Save agent
        agent.save_model()
        print("\nRL exit agent saved successfully!")
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        raise


if __name__ == "__main__":
    # Configure logging
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    
    try:
        train_and_evaluate()
        print("\n✅ RL exit agent training completed successfully!")
    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
