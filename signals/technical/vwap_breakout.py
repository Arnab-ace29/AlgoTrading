"""
Signal 1: VWAP Momentum Breakout
Weight: 0.40 in Phase 1 ensemble

Logic:
  LONG  when: price breaks above VWAP + price above key EMAs + volume surge + ADX trend
  SHORT when: price breaks below VWAP + price below key EMAs + volume surge + ADX trend

Score formula (long side example):
  base = avg(vwap_long, ema_bull, volume_bull)
  bonus += adx_bonus + macd_bonus + rsi_bonus
  score = clip(base + bonus, 0, 1.0)
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from signals.base import BaseSignal, SignalResult, Regime, feat


class VWAPBreakoutSignal(BaseSignal):

    name = "vwap_breakout"
    regime_affinity = [Regime.TRENDING_UP, Regime.TRENDING_DOWN]

    def _compute(self, df: pd.DataFrame, symbol: str) -> SignalResult:
        row = df.iloc[-1]    # current bar
        prev = df.iloc[-2]   # previous bar (for crossover detection)

        # ── Core VWAP condition ───────────────────────────────────────────────
        vwap_dist = feat(row, "vwap_dist_pct", 0.0)

        # VWAP cross: price moved from below to above VWAP (bullish cross)
        prev_vwap_dist   = feat(prev, "vwap_dist_pct", 0.0)
        vwap_cross_long  = prev_vwap_dist < 0 and vwap_dist > 0
        vwap_cross_short = prev_vwap_dist > 0 and vwap_dist < 0

        # Price position relative to VWAP
        vwap_long_score  =  min(1.0, max(0.0, vwap_dist  /  0.005))   # full score at +0.5% above
        vwap_short_score =  min(1.0, max(0.0, -vwap_dist /  0.005))   # full score at -0.5% below

        # ── EMA alignment ─────────────────────────────────────────────────────
        p_ema9  = feat(row, "price_vs_ema9",  0.0)
        p_ema20 = feat(row, "price_vs_ema20", 0.0)

        ema_bull  = float(p_ema9 > 0 and p_ema20 > 0)
        ema_bear  = float(p_ema9 < 0 and p_ema20 < 0)

        # ── Volume confirmation ───────────────────────────────────────────────
        vol_ratio = feat(row, "volume_ratio", 1.0)
        vol_score = min(1.0, (vol_ratio - 1.0) / 1.0)   # 0 at avg, 1.0 at 2×avg

        # ── ADX trend strength ────────────────────────────────────────────────
        adx = feat(row, "adx_14", 15.0)
        adx_score = min(1.0, max(0.0, (adx - 15.0) / 25.0))   # 0 at ADX<15, 1 at ADX>40

        # ── MACD confirmation ─────────────────────────────────────────────────
        macd_hist = feat(row, "macd_hist", 0.0)
        macd_bull = float(macd_hist > 0)
        macd_bear = float(macd_hist < 0)

        # ── RSI filter: avoid overbought entries ──────────────────────────────
        rsi = feat(row, "rsi_14", 50.0)
        rsi_long_ok  = float(rsi < 75)    # don't go long if already overbought
        rsi_short_ok = float(rsi > 25)    # don't go short if already oversold

        # ── Compose scores ────────────────────────────────────────────────────
        if vwap_dist >= 0:
            # Long candidate
            base = (vwap_long_score * 0.40 + ema_bull * 0.30 + vol_score * 0.30)
            bonus = adx_score * 0.10 + macd_bull * 0.05
            score = (base + bonus) * rsi_long_ok
            # Reduce if no actual VWAP cross (just floating above)
            if not vwap_cross_long:
                score *= 0.70
        else:
            # Short candidate
            base = (vwap_short_score * 0.40 + ema_bear * 0.30 + vol_score * 0.30)
            bonus = adx_score * 0.10 + macd_bear * 0.05
            score = -(base + bonus) * rsi_short_ok
            if not vwap_cross_short:
                score *= 0.70

        score = float(np.clip(score, -1.0, 1.0))

        components = {
            "vwap_dist_pct":   round(vwap_dist, 5),
            "vwap_cross":      vwap_cross_long or vwap_cross_short,
            "ema_bull":        bool(ema_bull),
            "vol_ratio":       round(vol_ratio, 2),
            "adx":             round(adx, 1),
            "macd_hist":       round(macd_hist, 4),
            "rsi_14":          round(rsi, 1),
        }

        regime = Regime.TRENDING_UP if score > 0 else (
                 Regime.TRENDING_DOWN if score < 0 else Regime.UNKNOWN)

        return self._result(symbol, score, components, regime)
