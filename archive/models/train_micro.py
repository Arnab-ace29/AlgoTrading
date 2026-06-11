"""
Training script for Micro XGBoost Model
Loads tick-level or 1-minute data, trains microstructure model.

Usage:
    python models/train_micro.py
"""

from __future__ import annotations
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from signals.ml.micro_model import MicroXGBoostModel
from models._data_loader import load_candles_with_features


def train_and_evaluate():
    """Main training and evaluation pipeline."""
    logger.info("Starting Micro XGBoost Model Training")
    
    # Symbols to train on (subset of liquid Nifty 50 stocks)
    symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
    
    try:
        # Load 1-min candles from SQLite. Micro model builds its own
        # microstructure features, so skip the heavy 80-feature compute.
        df = load_candles_with_features(symbols, timeframe="1min", days=30,
                                        compute_features=False)
        
        # Train model (groups by 'symbol' internally to avoid leakage)
        logger.info("Training microstructure model...")
        model = MicroXGBoostModel()
        metrics = model.train(df)
        
        # Print results
        print("\n" + "="*60)
        print("MICRO XGBOOST MODEL TRAINING RESULTS")
        print("="*60)
        print(f"AUC Score: {metrics['auc']:.4f}")
        print(f"Accuracy: {metrics['accuracy']:.4f}")
        print(f"Training Samples: {metrics['train_samples']:,}")
        print(f"Validation Samples: {metrics['val_samples']:,}")
        print(f"Entry Threshold: {model.entry_threshold}")
        
        print("\nFeature Importance:")
        for feature, importance in metrics['feature_importance'].items():
            print(f"  {feature:<20} {importance:.4f}")
        
        # Save model
        model.save_model()
        print("\nModel saved successfully!")
        
        # Test prediction on latest data (full history per symbol)
        print("\nTesting entry gate on latest data:")
        for symbol in symbols[:3]:  # Test first 3 symbols
            symbol_data = df[df['symbol'] == symbol]
            if not symbol_data.empty:
                result = model.predict(symbol_data)
                gate_status = "ALLOW" if result.should_enter else "BLOCK"
                print(f"  {symbol}: {result.prediction:.3f} (confidence: {result.confidence:.3f}) -> {gate_status}")
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        raise


if __name__ == "__main__":
    # Configure logging
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    
    try:
        train_and_evaluate()
        print("\n✅ Micro model training completed successfully!")
    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
