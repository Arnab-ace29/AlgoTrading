"""
Shared entry-decision pipeline.

This module holds the *pure* decision logic that decides whether a candidate
signal becomes a trade — the Phase 2 ML gates and the EntryState builder. It is
deliberately stateless: every input it needs (model singletons, portfolio
context, session PnL) is passed in, so the SAME code path can be driven by

  • live/runner.py        — real time, against the live feed, and
  • replay/engine.py      — "Action Replay", against historical bars,

guaranteeing the replay reflects exactly what the live runner would have done.

Behaviour here is a verbatim extraction of LiveRunner._passes_ml_gates and
LiveRunner._build_entry_state (issue: full-fidelity replay). The runner now
delegates to these functions, so there is a single source of truth.
"""

from __future__ import annotations

import pandas as pd

from signals.base import Direction
from models.rl_entry_agent import EntryState

# Encode regimes to the ints the RL entry agent expects (mirrors runner).
REGIME_ENCODING: dict[str, int] = {
    "TRENDING_UP": 0,
    "TRENDING_DOWN": 1,
    "MEAN_REVERTING": 2,
    "CHOPPY": 3,
}


def build_entry_state(
    *,
    result,
    df: pd.DataFrame,
    prev_score: float,
    macro_prob: float,
    session_pnl: float,
    daily_loss_limit: float,
    open_count: int,
    recent_win_rate: float = 0.5,
) -> EntryState:
    """Assemble the EntryState feature vector for the RL entry agent.

    Pure version of LiveRunner._build_entry_state — identical maths, but the
    live-global session PnL / open-position count / win-rate are passed in.
    """
    last_bar = df.iloc[-1]

    # Time of day normalised 0.0 (9:15) .. 1.0 (15:30). Candles are stored UTC,
    # so convert to IST before the session-minute math (FEAT-TZ).
    idx = df.index[-1]
    if hasattr(idx, "hour"):
        ts = pd.Timestamp(idx)
        ts = ts.tz_localize("UTC") if ts.tz is None else ts
        ts = ts.tz_convert("Asia/Kolkata")
        mins = ts.hour * 60 + ts.minute - (9 * 60 + 15)
        time_of_day = float(min(max(mins / 375.0, 0.0), 1.0))
    else:
        time_of_day = 0.5

    session_pnl_norm = 0.0
    if daily_loss_limit > 0:
        session_pnl_norm = float(max(-1.0, min(1.0, session_pnl / daily_loss_limit)))

    return EntryState(
        composite_score=float(result.composite_score),
        regime_encoded=REGIME_ENCODING.get(result.regime.value, 3),
        time_of_day=time_of_day,
        vix_normalized=0.5,  # India VIX not wired into the feed yet
        session_pnl_normalized=session_pnl_norm,
        open_positions_count=open_count,
        volume_ratio=float(last_bar.get("volume_ratio", 1.0) or 1.0),
        score_momentum=float(result.composite_score - prev_score),
        macro_model_prob=float(macro_prob),
        recent_win_rate=recent_win_rate,
    )


def passes_ml_gates(
    *,
    symbol: str,
    df: pd.DataFrame,
    result,
    prev_score: float,
    macro_model,
    micro_model,
    outcome_models,
    rl_entry,
    strategy_tag: str,
    session_pnl: float,
    daily_loss_limit: float,
    open_count: int,
    recent_win_rate: float = 0.5,
) -> tuple[bool, str, float]:
    """
    Layer the Phase 2 ML models on top of the rule-based ensemble as veto gates.
    Every gate is permissive (allows entry) when its model is not yet
    trained/reliable, so the system keeps trading while data accumulates.

    Order: macro direction -> micro entry -> strategy outcome -> RL entry.

    Returns (passed, reason, macro_prob). macro_prob is surfaced so the caller can
    record it (and so the RL entry state matches the live runner exactly).
    """
    direction = result.direction

    # 1. Macro directional confirmation (P(bullish) over next ~15 min).
    macro_prob = 0.5
    macro_res = macro_model.predict(df)
    if macro_res.is_reliable:
        macro_prob = macro_res.prediction
        neutral = float(macro_res.base_rate)
        band = 0.02   # small deadband so a near-neutral prob doesn't veto either side
        if direction == Direction.LONG and macro_prob < neutral - band:
            return False, f"macro P(bull)={macro_prob:.2f} < base {neutral:.2f} for LONG", macro_prob
        if direction == Direction.SHORT and macro_prob > neutral + band:
            return False, f"macro P(bull)={macro_prob:.2f} > base {neutral:.2f} for SHORT", macro_prob

    # 2. Micro entry confirmation (short-term buying pressure gate).
    micro_res = micro_model.predict(df)
    if micro_res.is_reliable and not micro_res.should_enter:
        return False, f"micro gate blocked (p={micro_res.prediction:.2f})", macro_prob

    # 3. Strategy outcome gate (P(WIN) for this strategy at entry).
    outcome = outcome_models.predict(strategy_tag, df)
    if outcome.is_reliable and not outcome.should_enter:
        return False, f"outcome P(win)={outcome.win_probability:.2f} below threshold", macro_prob

    # 4. RL entry agent (only active after enough logged decisions).
    if rl_entry.is_active():
        state = build_entry_state(
            result=result, df=df, prev_score=prev_score, macro_prob=macro_prob,
            session_pnl=session_pnl, daily_loss_limit=daily_loss_limit,
            open_count=open_count, recent_win_rate=recent_win_rate,
        )
        if not rl_entry.should_enter(state):
            return False, "RL entry agent: SKIP", macro_prob

    return True, "ml gates passed", macro_prob
