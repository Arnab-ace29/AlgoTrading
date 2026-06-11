"""
Signal 2: RSI Momentum
Weight: 0.35 in Phase 1 ensemble

Logic:
  LONG  when: RSI crosses above 50 + MACD histogram positive + positive ROC
  SHORT when: RSI crosses below 50 + MACD histogram negative + negative ROC

Score formula:
  conditions_met / total_conditions × strength_multiplier
  Strength modifier: rsi > 60 boosts long, rsi < 40 boosts short
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from signals.base import BaseSignal, SignalResult, Regime, feat


class RSIMomentumSignal(BaseSignal):

    name = "rsi_momentum"
    regime_affinity = [Regime.TRENDING_UP, Regime.TRENDING_DOWN]

    def _compute(self, df: pd.DataFrame, symbol: str) -> SignalResult:
        row  = df.iloc[-1]
        prev = df.iloc[-2]

        rsi      = feat(row,  "rsi_14",        50.0)
        rsi_prev = feat(prev, "rsi_14",        50.0)
        rsi_7    = feat(row,  "rsi_7",         50.0)
        macd_h   = feat(row,  "macd_hist",      0.0)
        macd_sl  = feat(row,  "macd_hist_slope", 0.0)
        roc_10   = feat(row,  "roc_10",         0.0)
        adx      = feat(row,  "adx_14",        15.0)

        # ── Condition checks ──────────────────────────────────────────────────

        # RSI cross of 50 (most important condition)
        rsi_crossed_above_50 = (rsi_prev < 50) and (rsi >= 50)
        rsi_crossed_below_50 = (rsi_prev > 50) and (rsi <= 50)

        # RSI zone (above 50 = bullish territory, below 50 = bearish)
        rsi_above_50 = rsi > 50
        rsi_below_50 = rsi < 50

        # MACD confirmation
        macd_bull = macd_h > 0
        macd_bear = macd_h < 0

        # Rate of change
        roc_bull = roc_10 > 0
        roc_bear = roc_10 < 0

        # Avoid extreme zones (RSI above 70 for long, below 30 for short)
        not_overbought = rsi < 72
        not_oversold   = rsi > 28

        # ── Long score ────────────────────────────────────────────────────────
        if rsi_above_50:
            conditions = [
                rsi_above_50,
                macd_bull,
                roc_bull,
                rsi_7 > 50,
                macd_sl > 0,   # MACD histogram rising
            ]
            base_score = sum(conditions) / len(conditions)

            # Strength modifier: RSI far above 50 = stronger signal
            strength = min(1.0, (rsi - 50) / 25.0)   # max at RSI=75
            score = base_score * (0.7 + 0.3 * strength) * float(not_overbought)

            # Bonus for fresh RSI cross
            if rsi_crossed_above_50:
                score = min(1.0, score * 1.15)

            # Reduce if ADX shows truly no trend (cutoff at 12 for Indian 5min)
            if adx < 12:
                score *= 0.6

        # ── Short score ───────────────────────────────────────────────────────
        elif rsi_below_50:
            conditions = [
                rsi_below_50,
                macd_bear,
                roc_bear,
                rsi_7 < 50,
                macd_sl < 0,
            ]
            base_score = sum(conditions) / len(conditions)
            strength = min(1.0, (50 - rsi) / 25.0)
            score = -(base_score * (0.7 + 0.3 * strength) * float(not_oversold))

            if rsi_crossed_below_50:
                score = max(-1.0, score * 1.15)

            if adx < 12:
                score *= 0.6

        else:
            score = 0.0

        score = float(np.clip(score, -1.0, 1.0))

        components = {
            "rsi_14":             round(rsi, 1),
            "rsi_7":              round(rsi_7, 1),
            "rsi_crossed_50":     rsi_crossed_above_50 or rsi_crossed_below_50,
            "macd_hist":          round(macd_h, 4),
            "roc_10":             round(roc_10, 4),
            "adx":                round(adx, 1),
        }

        regime = Regime.TRENDING_UP   if score > 0 else (
                 Regime.TRENDING_DOWN if score < 0 else Regime.UNKNOWN)

        return self._result(symbol, score, components, regime)
