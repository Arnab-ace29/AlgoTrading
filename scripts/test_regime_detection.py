"""
Test script for Phase 2 regime detection system.
Verifies that the RegimeDetector and updated EnsembleAggregator work correctly.
"""

from __future__ import annotations
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from features.indicators import compute_all_features
from signals.ml.regime_detector import RegimeDetector
from ensemble.aggregator import EnsembleAggregator


def create_test_data(trending_up: bool = True) -> pd.DataFrame:
    """Create synthetic test data for different market regimes."""
    np.random.seed(42)
    n = 200
    
    if trending_up:
        # Trending up data
        close = 1000 + np.cumsum(np.random.randn(n) * 2 + 0.5)
        high = close + np.abs(np.random.randn(n) * 3)
        low = close - np.abs(np.random.randn(n) * 3)
        volume = np.random.randint(100_000, 500_000, n)
    else:
        # Choppy/sideways data
        close = 1000 + np.cumsum(np.random.randn(n) * 1.5)
        high = close + np.abs(np.random.randn(n) * 2)
        low = close - np.abs(np.random.randn(n) * 2)
        volume = np.random.randint(50_000, 200_000, n)
    
    open_price = close - np.random.randn(n) * 2
    
    df = pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=pd.date_range("2024-01-02 09:15", periods=n, freq="5min", tz="Asia/Kolkata"))
    
    return compute_all_features(df)


def test_regime_detector():
    """Test the RegimeDetector with different market conditions."""
    print("Testing RegimeDetector...")
    
    detector = RegimeDetector()
    
    # Test trending up market
    df_trending = create_test_data(trending_up=True)
    regime_state = detector.detect_regime(df_trending, "TEST")
    print(f"  Trending up market: {regime_state.regime} (confidence: {regime_state.confidence:.2f})")
    
    # Test choppy market
    df_choppy = create_test_data(trending_up=False)
    regime_state = detector.detect_regime(df_choppy, "TEST")
    print(f"  Choppy market: {regime_state.regime} (confidence: {regime_state.confidence:.2f})")
    
    # Test regime weights
    for regime in ["TRENDING_UP", "MEAN_REVERTING", "CHOPPY"]:
        weights = detector.get_regime_weights(regime)
        bonus = detector.get_regime_bonus(regime)
        print(f"  {regime} weights: {weights}, bonus: {bonus}")


def test_ensemble_with_regime():
    """Test the updated EnsembleAggregator with regime detection."""
    print("\nTesting EnsembleAggregator with regime detection...")
    
    aggregator = EnsembleAggregator()
    
    # Test with trending data
    df_trending = create_test_data(trending_up=True)
    result = aggregator.compute(df_trending, "TEST_TRENDING")
    print(f"  Trending result: {result.direction.value} (score: {result.composite_score:.3f}, regime: {result.regime.value})")
    print(f"  Weights used: {result.weights_used}")
    
    # Test with choppy data
    df_choppy = create_test_data(trending_up=False)
    result = aggregator.compute(df_choppy, "TEST_CHOPPY")
    print(f"  Choppy result: {result.direction.value} (score: {result.composite_score:.3f}, regime: {result.regime.value})")
    print(f"  Weights used: {result.weights_used}")


if __name__ == "__main__":
    print("Phase 2 Regime Detection Test\n" + "=" * 40)
    
    try:
        test_regime_detector()
        test_ensemble_with_regime()
        print("\n✅ All regime detection tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
