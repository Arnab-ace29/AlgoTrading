"""
Training script for the RL Entry Agent - Phase 2 (Task 7.3)

Builds entry-decision episodes from the trade_log. Every logged trade is an
ENTER decision whose reward is the realised pnl_pct. To give the agent
contrast (what SKIP would have yielded), we add a counterfactual SKIP decision
(reward 0) for the same state. The agent thus learns to ENTER only when the
expected ENTER reward beats 0.

Falls back to synthetic decisions until enough live trades accumulate.

Usage:
    python models/train_rl_entry.py
"""

from __future__ import annotations
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from loguru import logger

from data.db import get_trade_log, read_candles
from models.rl_entry_agent import RLEntryAgent, EntryState
from models.train_rl_on_journeys import _REGIME_ENCODING
from config.settings import TRADING_CAPITAL
from config.risk_profiles import ACTIVE as RISK


def _time_of_day_norm(ts: pd.Timestamp) -> float:
    """Normalise an IST timestamp to 0.0 (9:15) .. 1.0 (15:30)."""
    minutes = ts.hour * 60 + ts.minute - (9 * 60 + 15)
    return float(np.clip(minutes / 375.0, 0.0, 1.0))


def build_entry_decisions() -> list[dict]:
    """
    Reconstruct entry decisions from closed trades.

    For each trade we build an EntryState and emit two decisions: ENTER (reward =
    realised pnl_pct) and a counterfactual SKIP (reward 0) for the same state.

    The context dims that the entry agent actually keys on are reconstructed from
    the trade log so they VARY across decisions (RL-03):
      • recent_win_rate       — win rate of the last 10 trades closed before entry
      • session_pnl_normalized — same-day realised PnL before entry / daily-loss limit
      • open_positions_count   — trades open concurrently at entry time
    (vix / macro_prob / score_momentum aren't reconstructable post-hoc and are not
    part of the agent's state key, so they're left neutral.)
    """
    trades = get_trade_log(limit=5000)
    if trades.empty:
        return []

    closed = trades[trades["status"] == "CLOSED"].copy()
    if closed.empty:
        return []
    closed["entry_time"] = pd.to_datetime(closed["entry_time"])
    closed["exit_time"] = pd.to_datetime(closed["exit_time"])
    closed["pnl"] = pd.to_numeric(closed["pnl"], errors="coerce").fillna(0.0)
    closed = closed.sort_values("entry_time").reset_index(drop=True)

    daily_loss_limit = TRADING_CAPITAL * RISK.max_daily_loss_pct / 100.0
    decisions: list[dict] = []

    for _, t in closed.iterrows():
        e = t["entry_time"]
        if pd.isna(e):
            continue

        entry_score = float(t.get("entry_score") or 0.6)
        regime_enc = _REGIME_ENCODING.get(str(t.get("regime_at_entry", "")), 3)
        pnl_pct = float(t.get("pnl_pct") or 0.0) * 100.0  # stored as fraction

        # recent win rate: last 10 trades that CLOSED before this entry
        prev_closed = closed[closed["exit_time"] < e]
        recent_wr = float((prev_closed.sort_values("exit_time").tail(10)["pnl"] > 0).mean()) \
            if len(prev_closed) else 0.5
        # session PnL realised earlier the same day, normalised by the daily loss limit
        same_day = closed[(closed["entry_time"].dt.date == e.date()) & (closed["exit_time"] < e)]
        session_pnl_norm = float(np.clip(same_day["pnl"].sum() / daily_loss_limit, -1, 1)) \
            if daily_loss_limit > 0 else 0.0
        # positions open concurrently at this entry
        open_cnt = int(((closed["entry_time"] < e) & (closed["exit_time"] > e)).sum())

        # Volume ratio at entry (current vol vs 20-bar avg), best-effort.
        vol_ratio = 1.0
        candles = read_candles(t["symbol"], timeframe="5min",
                               from_dt=e - timedelta(days=5), to_dt=e)
        if not candles.empty and len(candles) >= 20:
            v = candles["volume"].astype(float)
            avg20 = v.tail(20).mean()
            if avg20 > 0:
                vol_ratio = float(v.iloc[-1] / avg20)

        state = EntryState(
            composite_score=entry_score,
            regime_encoded=regime_enc,
            time_of_day=_time_of_day_norm(e),
            vix_normalized=0.5,                      # not in the state key
            session_pnl_normalized=session_pnl_norm,
            open_positions_count=min(open_cnt, 5),
            volume_ratio=vol_ratio,
            score_momentum=0.0,                      # not in the state key
            macro_model_prob=0.5,                    # not in the state key
            recent_win_rate=recent_wr,
        )

        decisions.append({"state": state, "action": 1, "reward": pnl_pct})
        # Counterfactual: skipping this setup would have yielded 0.
        decisions.append({"state": state, "action": 0, "reward": 0.0})

    logger.info(f"Built {len(decisions)} entry decisions from {len(closed)} closed trades")
    return decisions


def create_synthetic_entry_decisions(n: int = 400) -> list[dict]:
    """Synthetic bootstrap decisions when there is no live trade history."""
    rng = np.random.default_rng(7)
    decisions: list[dict] = []
    for _ in range(n):
        score = rng.uniform(0.55, 0.95)
        win_rate = rng.uniform(0, 1)
        # 'good' depends only on dims in the agent's state key (score + recent win rate),
        # so the bootstrap teaches a pattern the live agent can actually key on.
        good = score > 0.7 and win_rate > 0.4
        state = EntryState(
            composite_score=score,
            regime_encoded=int(rng.integers(0, 4)),
            time_of_day=rng.uniform(0, 1),
            vix_normalized=rng.uniform(0, 1),
            session_pnl_normalized=rng.uniform(-1, 1),
            open_positions_count=int(rng.integers(0, 5)),
            volume_ratio=rng.uniform(0.5, 3.0),
            score_momentum=rng.uniform(-0.3, 0.3),
            macro_model_prob=rng.uniform(0.3, 0.9),
            recent_win_rate=win_rate,
        )
        enter_reward = 1.0 if good else -0.6
        decisions.append({"state": state, "action": 1, "reward": enter_reward})
        decisions.append({"state": state, "action": 0, "reward": 0.0})
    return decisions


def train_and_evaluate():
    logger.info("Starting RL Entry Agent training")

    MIN_REAL_DECISIONS = 50  # ~25 trades (2 decisions each)
    decisions = build_entry_decisions()
    used_synthetic = False

    if len(decisions) >= MIN_REAL_DECISIONS:
        logger.info(f"Training on {len(decisions)} real entry decisions")
    else:
        logger.warning(
            f"Only {len(decisions)} real decisions (<{MIN_REAL_DECISIONS}); "
            "bootstrapping with synthetic decisions."
        )
        decisions = create_synthetic_entry_decisions()
        used_synthetic = True

    agent = RLEntryAgent(n_episodes=1500)
    # Synthetic data must NOT count toward the activation gate (RL-03).
    metrics = agent.train_on_decisions(decisions, count_for_activation=not used_synthetic)

    print("\n" + "=" * 60)
    print("RL ENTRY AGENT TRAINING RESULTS")
    print("=" * 60)
    print(f"Total Episodes:   {metrics['total_episodes']}")
    print(f"Average Reward:   {metrics['avg_reward']:.4f}")
    print(f"Final Epsilon:    {metrics['final_epsilon']:.4f}")
    print(f"Q-table Size:     {metrics['q_table_size']} states")
    print(f"Decisions Logged: {metrics['decisions_logged']}")
    print(f"Agent Active:     {agent.is_active()}")

    agent.save_model()
    print("\nRL entry agent saved.")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    try:
        train_and_evaluate()
        print("\nRL entry training run complete.")
    except Exception as e:
        print(f"\nTraining failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
