"""
Training script for Macro XGBoost Model
Loads historical data, trains model, and evaluates performance.

Usage:
    python models/train_macro.py
"""

from __future__ import annotations
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from signals.ml.macro_model import MacroXGBoostModel
from models._data_loader import load_candles_with_features
from config.settings import INSTRUMENTS


def train_and_evaluate():
    """Main training and evaluation pipeline."""
    logger.info("Starting Macro XGBoost Model Training")
    
    # Symbols to train on (Nifty 50 watchlist from settings)
    symbols = INSTRUMENTS
    
    try:
        # Load 5-min candles + features per symbol from SQLite
        features_df = load_candles_with_features(symbols, timeframe="5min", days=180)
        logger.info(f"Total feature rows: {len(features_df)}")
        
        # Train model (groups by 'symbol' internally to avoid leakage)
        model = MacroXGBoostModel()
        metrics = model.train(features_df)
        
        # Print results
        print("\n" + "="*60)
        print("MACRO XGBOOST MODEL TRAINING RESULTS")
        print("="*60)
        print(f"AUC Score: {metrics['auc']:.4f}")
        print(f"Accuracy: {metrics['accuracy']:.4f}")
        print(f"Training Samples: {metrics['train_samples']:,}")
        print(f"Validation Samples: {metrics['val_samples']:,}")
        
        print("\nTop 10 Features:")
        for i, (feature, importance) in enumerate(metrics['top_features'].items(), 1):
            print(f"  {i:2d}. {feature:<20} {importance:.4f}")
        
        # Save model
        model.save_model()
        print("\nModel saved successfully!")
        
        # Test prediction on latest data (pass full history per symbol)
        print("\nTesting prediction on latest data:")
        for symbol in symbols[:3]:  # Test first 3 symbols
            symbol_data = features_df[features_df['symbol'] == symbol]
            if not symbol_data.empty:
                result = model.predict(symbol_data)
                print(f"  {symbol}: {result.prediction:.3f} (confidence: {result.confidence:.3f})")
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        raise


if __name__ == "__main__":
    # Configure logging
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    
    try:
        train_and_evaluate()
        print("\n✅ Macro model training completed successfully!")
    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
