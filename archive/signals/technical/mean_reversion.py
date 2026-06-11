"""
Signal 3: Mean Reversion
Weight: 0.25 in Phase 1 ensemble

Logic:
  LONG  when: price at/below Bollinger lower band + RSI oversold + VWAP stretched low
  SHORT when: price at/above Bollinger upper band + RSI overbought + VWAP stretched high

Score formula:
  strength = how extreme the stretch is (how far outside bands, how oversold RSI)
  confirmation = volume confirmation + candle reversal pattern
  score = strength × confirmation
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from signals.base import BaseSignal, SignalResult, Regime, feat


class MeanReversionSignal(BaseSignal):

    name = "mean_reversion"
    regime_affinity = [Regime.MEAN_REVERTING]

    # Mean reversion is a RARE signal — it must only fire at genuine extremes,
    # not anywhere price is merely off the band midpoint (issue SIG-01).
    LONG_BB   = 0.20   # at/below lower fifth of the band
    LONG_RSI  = 35.0   # oversold
    LONG_Z    = -2.0   # ≥2σ below mean
    SHORT_BB  = 0.80
    SHORT_RSI = 65.0
    SHORT_Z   = 2.0

    def _compute(self, df: pd.DataFrame, symbol: str) -> SignalResult:
        row  = df.iloc[-1]

        # Core mean-reversion indicators (NaN-safe reads)
        bb_pct_b      = feat(row, "bb_pct_b",       0.5)
        rsi_14        = feat(row, "rsi_14",         50.0)
        vwap_dist     = feat(row, "vwap_dist_pct",   0.0)
        close_zscore  = feat(row, "close_zscore",    0.0)
        adx           = feat(row, "adx_14",         15.0)
        vol_ratio     = feat(row, "volume_ratio",    1.0)
        oversold_cnt  = int(feat(row, "oversold_count",    0))
        overbought_cnt= int(feat(row, "overbought_count",  0))

        # Lower wick: candle reversal signal at bottom (lower wick > upper wick)
        lower_wick    = feat(row, "lower_wick_ratio", 0.0)
        upper_wick    = feat(row, "upper_wick_ratio", 0.0)
        reversal_candle_bull  = lower_wick > upper_wick + 0.15  # hammer-type candle
        reversal_candle_bear  = upper_wick > lower_wick + 0.15  # shooting-star type

        # Avoid mean reversion in strong trends (fade in a trending market = dangerous)
        no_strong_trend = adx < 25

        # Only fire at genuine extremes; otherwise this signal stays silent.
        long_extreme  = (bb_pct_b <= self.LONG_BB)  or (rsi_14 <= self.LONG_RSI)  or (close_zscore <= self.LONG_Z)
        short_extreme = (bb_pct_b >= self.SHORT_BB) or (rsi_14 >= self.SHORT_RSI) or (close_zscore >= self.SHORT_Z)

        # ── LONG setup: price deeply oversold / below lower BB ────────────────
        if long_extreme and bb_pct_b < 0.5:
            # Stretch score: how extreme is the oversold condition?
            bb_stretch   = max(0.0, (0.2 - bb_pct_b) / 0.2)     # max at bb_pct_b=0
            rsi_stretch  = max(0.0, (40 - rsi_14) / 40)          # max at rsi_14=0
            vwap_stretch = max(0.0, (-vwap_dist - 0.005) / 0.01) # max at -1.5% below VWAP
            z_stretch    = max(0.0, (-close_zscore - 1.0) / 2.0) # max at z=-3

            stretch_score = (
                bb_stretch   * 0.35 +
                rsi_stretch  * 0.30 +
                vwap_stretch * 0.20 +
                z_stretch    * 0.15
            )

            # Confirmation: oversold indicator count + volume + reversal candle
            confirmation = min(1.0, (
                (oversold_cnt / 5.0) * 0.40 +
                float(reversal_candle_bull) * 0.35 +
                min(1.0, vol_ratio - 0.8) * 0.25
            ))

            score = stretch_score * (0.6 + 0.4 * confirmation) * float(no_strong_trend)

        # ── SHORT setup: price deeply overbought / above upper BB ─────────────
        elif short_extreme and bb_pct_b > 0.5:
            bb_stretch   = max(0.0, (bb_pct_b - 0.8) / 0.2)
            rsi_stretch  = max(0.0, (rsi_14 - 60) / 40)
            vwap_stretch = max(0.0, (vwap_dist - 0.005) / 0.01)
            z_stretch    = max(0.0, (close_zscore - 1.0) / 2.0)

            stretch_score = (
                bb_stretch   * 0.35 +
                rsi_stretch  * 0.30 +
                vwap_stretch * 0.20 +
                z_stretch    * 0.15
            )

            confirmation = min(1.0, (
                (overbought_cnt / 5.0) * 0.40 +
                float(reversal_candle_bear) * 0.35 +
                min(1.0, vol_ratio - 0.8) * 0.25
            ))

            score = -(stretch_score * (0.6 + 0.4 * confirmation) * float(no_strong_trend))

        else:
            score = 0.0

        score = float(np.clip(score, -1.0, 1.0))

        components = {
            "bb_pct_b":       round(bb_pct_b, 3),
            "rsi_14":         round(rsi_14, 1),
            "vwap_dist_pct":  round(vwap_dist, 5),
            "close_zscore":   round(close_zscore, 2),
            "adx":            round(adx, 1),
            "oversold_cnt":   oversold_cnt,
            "overbought_cnt": overbought_cnt,
            "reversal_candle": reversal_candle_bull or reversal_candle_bear,
        }

        return self._result(symbol, score, components, Regime.MEAN_REVERTING)
