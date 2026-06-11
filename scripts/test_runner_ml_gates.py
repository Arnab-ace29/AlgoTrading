"""
Integration test for the LiveRunner Phase 2 ML gates.

Verifies (no broker/WebSocket needed):
  - Gates are permissive when models are untrained/unreliable.
  - Macro directional gate blocks a LONG when P(bull) is low.
  - Micro and outcome gates block when their models say "don't enter".
  - _build_entry_state produces a valid EntryState.
"""

from __future__ import annotations
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from live.runner import LiveRunner
from features.indicators import compute_all_features
from signals.base import Direction
from signals.ml.macro_model import MacroXGBoostModel, MacroModelResult
from signals.ml.micro_model import MicroXGBoostModel, MicroModelResult
from signals.ml.strategy_outcomes import StrategyOutcomeModels, OutcomeResult
from models.rl_entry_agent import RLEntryAgent, EntryState


def _make_feature_df(trend_up: bool = True, n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    drift = 0.6 if trend_up else -0.6
    close = 1000 + np.cumsum(rng.normal(drift, 2, n))
    df = pd.DataFrame({
        "open": close - rng.normal(0, 1, n),
        "high": close + np.abs(rng.normal(0, 2, n)),
        "low": close - np.abs(rng.normal(0, 2, n)),
        "close": close,
        "volume": rng.integers(100_000, 500_000, n).astype(float),
    }, index=pd.date_range("2024-06-03 09:15", periods=n, freq="5min", tz="Asia/Kolkata"))
    return compute_all_features(df)


# ── Lightweight stubs that mimic the model predict() contracts ────────────────
class _MacroStub:
    def __init__(self, prob, reliable=True):
        self._p, self._r = prob, reliable
    def predict(self, df):
        return MacroModelResult(prediction=self._p, confidence=abs(self._p - 0.5) + 0.5,
                                feature_importance={}, is_reliable=self._r)


class _MicroStub:
    def __init__(self, enter, reliable=True):
        self._e, self._r = enter, reliable
    def predict(self, df):
        return MicroModelResult(prediction=0.6 if self._e else 0.3,
                                confidence=0.6, should_enter=self._e, is_reliable=self._r)


class _OutcomeStub:
    def __init__(self, enter, reliable=True):
        self._e, self._r = enter, reliable
    def predict(self, strategy, df):
        return OutcomeResult(strategy=strategy, win_probability=0.6 if self._e else 0.3,
                             should_enter=self._e, is_reliable=self._r)


def _fresh_runner() -> LiveRunner:
    runner = LiveRunner(paper=True, use_ml_gates=True)
    # Replace singletons with untrained, isolated instances (gates open).
    tmp = Path(tempfile.mkdtemp())
    runner.macro_model = MacroXGBoostModel(model_path=tmp / "m.pkl")
    runner.micro_model = MicroXGBoostModel(model_path=tmp / "mi.pkl")
    runner.outcome_models = StrategyOutcomeModels(model_path=tmp / "o.pkl")
    runner.rl_entry = RLEntryAgent(model_path=tmp / "e.pkl")
    return runner


def test_gates_open_when_untrained() -> bool:
    print("Testing gates open when models untrained...")
    runner = _fresh_runner()
    df = _make_feature_df(trend_up=True)
    result = runner.aggregator.compute(df, "TEST")
    passed, reason = runner._passes_ml_gates("TEST", df, result, prev_score=result.composite_score)
    assert passed, f"expected open gates, blocked: {reason}"
    print(f"  Open gates: {reason}")
    return True


def test_macro_blocks_long() -> bool:
    print("Testing macro gate blocks a LONG on low P(bull)...")
    runner = _fresh_runner()
    df = _make_feature_df(trend_up=True)
    result = runner.aggregator.compute(df, "TEST")
    # Force a LONG result and a bearish macro prediction.
    result.direction = Direction.LONG
    runner.macro_model = _MacroStub(prob=0.2, reliable=True)
    passed, reason = runner._passes_ml_gates("TEST", df, result, prev_score=0.0)
    assert not passed and "macro" in reason, reason
    print(f"  Blocked: {reason}")
    return True


def test_micro_and_outcome_block() -> bool:
    print("Testing micro + outcome gates block...")
    runner = _fresh_runner()
    df = _make_feature_df(trend_up=True)
    result = runner.aggregator.compute(df, "TEST")
    result.direction = Direction.LONG
    runner.macro_model = _MacroStub(prob=0.8, reliable=True)  # macro allows LONG

    runner.micro_model = _MicroStub(enter=False, reliable=True)
    passed, reason = runner._passes_ml_gates("TEST", df, result, prev_score=0.0)
    assert not passed and "micro" in reason, reason
    print(f"  Micro blocked: {reason}")

    runner.micro_model = _MicroStub(enter=True, reliable=True)
    runner.outcome_models = _OutcomeStub(enter=False, reliable=True)
    passed, reason = runner._passes_ml_gates("TEST", df, result, prev_score=0.0)
    assert not passed and "outcome" in reason, reason
    print(f"  Outcome blocked: {reason}")
    return True


def test_build_entry_state() -> bool:
    print("Testing _build_entry_state...")
    runner = _fresh_runner()
    df = _make_feature_df(trend_up=True)
    result = runner.aggregator.compute(df, "TEST")
    state = runner._build_entry_state("TEST", df, result, prev_score=0.1, macro_prob=0.7)
    assert isinstance(state, EntryState)
    assert 0 <= state.regime_encoded <= 3
    assert 0.0 <= state.time_of_day <= 1.0
    assert state.macro_model_prob == 0.7
    print(f"  EntryState OK: regime={state.regime_encoded} tod={state.time_of_day:.2f} "
          f"volr={state.volume_ratio:.2f}")
    return True


if __name__ == "__main__":
    print("LiveRunner ML Gates Test\n" + "=" * 40)
    try:
        test_gates_open_when_untrained()
        test_macro_blocks_long()
        test_micro_and_outcome_block()
        test_build_entry_state()
        print("\nAll runner ML-gate tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
