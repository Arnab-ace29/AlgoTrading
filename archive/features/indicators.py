"""
Feature engineering engine — computes all 80 features from OHLCV candle data.

Input:  pandas DataFrame with columns [open, high, low, close, volume]
        Indexed by timestamp (DatetimeIndex), sorted ascending.
Output: Same DataFrame with 80 additional feature columns appended.

All features are computed WITHOUT lookahead bias (only data up to and including
the current bar is used). Safe for both live trading and backtesting.

Usage:
    from features.indicators import compute_all_features
    df_with_features = compute_all_features(raw_ohlcv_df)
"""

from __future__ import annotations
import warnings
import numpy as np
import pandas as pd

# Use the 'ta' library (pip install ta) — no C++ compiler needed
from ta.momentum import RSIIndicator, StochasticOscillator, WilliamsRIndicator, ROCIndicator
from ta.trend    import MACD, EMAIndicator, ADXIndicator, PSARIndicator
from ta.volatility import AverageTrueRange, BollingerBands, KeltnerChannel
from ta.volume   import OnBalanceVolumeIndicator, ChaikinMoneyFlowIndicator, AccDistIndexIndicator, MFIIndicator

warnings.filterwarnings("ignore", category=RuntimeWarning)

# Minimum bars required before features are meaningful
MIN_BARS_REQUIRED = 60


def _ist_index(index):
    """
    Best-effort IST (Asia/Kolkata) view of a candle index, for session-relative
    features. Candles are STORED in UTC (upstox_history uses utc=True, the live feed
    stamps datetime.now(timezone.utc)), but the trading session and every
    session-relative feature — time_norm, session-open detection, day-of-week,
    expiry proximity — are defined in IST (NSE 09:15–15:30). Computing hour/minute on
    a UTC index made time_norm span only ~0.0–0.12 and detected the "session open" at
    14:45 IST. tz-naive indices are assumed UTC (how this system stores), tz-aware are
    converted. Returns the index unchanged if it carries no timestamps.
    """
    if not isinstance(index, pd.DatetimeIndex):
        return index
    try:
        if index.tz is None:
            return index.tz_localize("UTC").tz_convert("Asia/Kolkata")
        return index.tz_convert("Asia/Kolkata")
    except (TypeError, ValueError):
        return index


def _session_vwap(price: pd.Series, volume: pd.Series, index) -> pd.Series:
    """
    Session-anchored VWAP (FEAT-01): cumulative(price·volume) / cumulative(volume),
    RESET at the start of each trading day, exactly as SIGNALS.md specifies. `price`
    is the typical price (H+L+C)/3.

    Grouping by calendar day works for NSE intraday data whether the index is IST or
    UTC, because a session (09:15–15:30 IST = 03:45–10:00 UTC) never crosses midnight
    in either zone. Falls back to a 78-bar rolling VWAP only when the index carries no
    timestamps (so session boundaries can't be identified).
    """
    volume = volume.fillna(0)
    pv = price * volume
    if isinstance(index, pd.DatetimeIndex) and len(index) == len(price):
        day = index.normalize()                       # day key (preserves tz)
        cum_pv = pv.groupby(day).cumsum()
        cum_v = volume.groupby(day).cumsum().replace(0, np.nan)
        return cum_pv / cum_v
    # No timestamps → can't session-anchor; approximate with a rolling window.
    return pv.rolling(78).sum() / volume.rolling(78).sum().replace(0, np.nan)


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all 80 features on the input OHLCV DataFrame.
    Returns the same df with feature columns appended in-place.
    NaN rows at the start (warm-up period) are normal and expected.
    """
    df = df.copy()
    _validate_input(df)

    _add_momentum_features(df)      # Features  1–14
    _add_trend_features(df)         # Features 15–27
    _add_volatility_features(df)    # Features 28–38
    _add_volume_features(df)        # Features 39–48
    _add_multi_timeframe(df)        # Features 49–55
    _add_session_features(df)       # Features 56–62
    _add_microstructure_features(df) # Features 63–68
    _add_derived_features(df)       # Features 69–80

    return df


def _validate_input(df: pd.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")
    if len(df) < MIN_BARS_REQUIRED:
        warnings.warn(f"Only {len(df)} bars — at least {MIN_BARS_REQUIRED} recommended for reliable features")


# ── 1. Momentum Features (14) ─────────────────────────────────────────────────

def _add_momentum_features(df: pd.DataFrame) -> None:
    c = df["close"]
    h = df["high"]
    l = df["low"]

    # 1. RSI 14
    df["rsi_14"] = RSIIndicator(c, window=14).rsi()

    # 2. RSI 7 (faster RSI for short-term momentum)
    df["rsi_7"] = RSIIndicator(c, window=7).rsi()

    # 3. RSI slope (momentum of RSI itself)
    df["rsi_slope"] = df["rsi_14"].diff(3)

    # 4. MACD histogram (12,26,9)
    _macd = MACD(c, window_slow=26, window_fast=12, window_sign=9)
    df["macd_hist"]       = _macd.macd_diff()
    df["macd_line"]       = _macd.macd()
    df["macd_signal"]     = _macd.macd_signal()

    # 5. MACD histogram slope
    df["macd_hist_slope"] = df["macd_hist"].diff(2)

    # 6-8. Rate of Change
    df["roc_5"]  = ROCIndicator(c, window=5).roc()
    df["roc_10"] = ROCIndicator(c, window=10).roc()
    df["roc_20"] = ROCIndicator(c, window=20).roc()

    # 9. Stochastic %K/%D (14,3)
    _stoch = StochasticOscillator(h, l, c, window=14, smooth_window=3)
    df["stoch_k"] = _stoch.stoch()
    df["stoch_d"] = _stoch.stoch_signal()

    # 10. Williams %R (14)
    df["williams_r"] = WilliamsRIndicator(h, l, c, lbp=14).williams_r()

    # 11. CCI (20) — manual: no CCI in ta library, compute directly
    typical = (h + l + c) / 3
    rolling_mean = typical.rolling(20).mean()
    rolling_mad  = typical.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    df["cci_20"] = (typical - rolling_mean) / (0.015 * rolling_mad.replace(0, np.nan))

    # 12. MFI — Money Flow Index (14)
    df["mfi_14"] = MFIIndicator(h, l, c, df["volume"], window=14).money_flow_index()

    # 13. Price momentum: (close - close_N) / close_N
    df["price_momentum_5"]  = (c - c.shift(5))  / c.shift(5).replace(0, np.nan)
    df["price_momentum_15"] = (c - c.shift(15)) / c.shift(15).replace(0, np.nan)


# ── 2. Trend Features (13) ────────────────────────────────────────────────────

def _add_trend_features(df: pd.DataFrame) -> None:
    c = df["close"]
    h = df["high"]
    l = df["low"]

    # 15. EMA 9
    df["ema_9"]  = EMAIndicator(c, window=9).ema_indicator()
    # 16. EMA 20
    df["ema_20"] = EMAIndicator(c, window=20).ema_indicator()
    # 17. EMA 50
    df["ema_50"] = EMAIndicator(c, window=50).ema_indicator()

    # 18. Price vs EMA9 (distance %)
    df["price_vs_ema9"]  = (c - df["ema_9"])  / df["ema_9"].replace(0, np.nan)
    # 19. Price vs EMA20
    df["price_vs_ema20"] = (c - df["ema_20"]) / df["ema_20"].replace(0, np.nan)
    # 20. Price vs EMA50
    df["price_vs_ema50"] = (c - df["ema_50"]) / df["ema_50"].replace(0, np.nan)

    # 21. EMA crossover flag: EMA9 vs EMA20 (positive = bullish cross)
    df["ema_cross_9_20"] = np.sign(df["ema_9"] - df["ema_20"])

    # 22. ADX (14) — trend strength (0-100)
    _adx = ADXIndicator(h, l, c, window=14)
    df["adx_14"] = _adx.adx()
    df["dmp_14"] = _adx.adx_pos()   # +DI
    df["dmn_14"] = _adx.adx_neg()   # -DI

    # 23. DI spread (+DI - -DI) — direction of trend
    df["di_spread"] = df["dmp_14"] - df["dmn_14"]

    # 24. Session-anchored VWAP + distance (resets each trading day at 9:15 — FEAT-01).
    typical = (h + l + c) / 3
    df["vwap_session"] = _session_vwap(typical, df["volume"], df.index)
    df["vwap_dist_pct"] = (c - df["vwap_session"]) / df["vwap_session"].replace(0, np.nan)

    # 25. Slope of EMA20 over last 5 bars (trend direction strength)
    df["ema20_slope"] = df["ema_20"].diff(5) / df["ema_20"].shift(5).replace(0, np.nan)

    # 26. Parabolic SAR signal (+1 = price above SAR = bullish)
    _psar = PSARIndicator(h, l, c)
    psar_vals = _psar.psar()
    # Simple approach: use the last values if lengths don't match
    if len(psar_vals) == len(df):
        df["psar_bull"] = (c > psar_vals).astype(float)
    else:
        # Skip PSAR feature if there's a length mismatch
        df["psar_bull"] = 0.5

    # 27. HMA (Hull Moving Average, 20) — manual: WMA(2*WMA(n/2) - WMA(n), sqrt(n))
    def _wma(s: pd.Series, w: int) -> pd.Series:
        weights = np.arange(1, w + 1)
        return s.rolling(w).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
    hma_n = 20
    df["hma_20"] = _wma(2 * _wma(c, hma_n // 2) - _wma(c, hma_n), int(np.sqrt(hma_n)))
    df["price_vs_hma20"] = (c - df["hma_20"]) / df["hma_20"].replace(0, np.nan)


# ── 3. Volatility Features (11) ──────────────────────────────────────────────

def _add_volatility_features(df: pd.DataFrame) -> None:
    c = df["close"]
    h = df["high"]
    l = df["low"]

    # 28. ATR 14 (Average True Range)
    df["atr_14"] = AverageTrueRange(h, l, c, window=14).average_true_range()

    # 29. ATR as % of price (normalised)
    df["atr_pct"] = df["atr_14"] / c.replace(0, np.nan)

    # 30. ATR percentile over 60-bar rolling window (0–1)
    df["atr_percentile"] = df["atr_14"].rolling(60).rank(pct=True)

    # 31-32. Bollinger Bands (20, 2σ)
    _bb = BollingerBands(c, window=20, window_dev=2)
    df["bb_upper"] = _bb.bollinger_hband()
    df["bb_lower"] = _bb.bollinger_lband()
    df["bb_mid"]   = _bb.bollinger_mavg()
    df["bb_width"] = _bb.bollinger_wband()
    df["bb_pct_b"] = _bb.bollinger_pband()

    # 33. BB squeeze: width percentile over 20 bars (low = compression, coming expansion)
    if "bb_width" in df.columns:
        df["bb_squeeze"] = df["bb_width"].rolling(20).rank(pct=True)

    # 34. Historical volatility: 5-bar std of log returns (annualised proxy)
    log_ret = np.log(c / c.shift(1))
    df["hist_vol_5"]  = log_ret.rolling(5).std()
    df["hist_vol_20"] = log_ret.rolling(20).std()

    # 35. Volatility ratio: short vol / long vol (>1 = vol expanding)
    df["vol_ratio"] = df["hist_vol_5"] / df["hist_vol_20"].replace(0, np.nan)

    # 36. Keltner channel width
    _kc = KeltnerChannel(h, l, c, window=20)
    df["kc_width"] = (_kc.keltner_channel_hband() - _kc.keltner_channel_lband()) / c.replace(0, np.nan)

    # 37. True Range (single bar)
    prev_close = c.shift(1)
    df["true_range"] = pd.concat([
        h - l,
        (h - prev_close).abs(),
        (l - prev_close).abs(),
    ], axis=1).max(axis=1)


# ── 4. Volume Features (10) ───────────────────────────────────────────────────

def _add_volume_features(df: pd.DataFrame) -> None:
    c = df["close"]
    v = df["volume"]

    # 38. Volume ratio: current / 20-bar average (surge detection)
    df["volume_ratio"] = v / v.rolling(20).mean().replace(0, np.nan)

    # 39. Volume spike: >2× average
    df["volume_spike"] = (df["volume_ratio"] > 2.0).astype(float)

    # 40. OBV (On-Balance Volume)
    df["obv"] = OnBalanceVolumeIndicator(c, v).on_balance_volume()

    # 41. OBV slope (momentum of OBV)
    df["obv_slope"] = df["obv"].diff(5)

    # 42. Volume trend
    df["volume_trend"] = v.rolling(5).mean() / v.rolling(20).mean().replace(0, np.nan)

    # 43. CMF — Chaikin Money Flow (20)
    df["cmf_20"] = ChaikinMoneyFlowIndicator(df["high"], df["low"], c, v, window=20).chaikin_money_flow()

    # 44. AD — Accumulation/Distribution Line
    df["ad_line"] = AccDistIndexIndicator(df["high"], df["low"], c, v).acc_dist_index()

    # 45. VWAP standard-deviation bands around the SESSION-anchored VWAP (FEAT-01).
    typical = (df["high"] + df["low"] + c) / 3
    session_vwap = _session_vwap(typical, v, df.index)
    # band width = rolling stdev of the price's distance from session VWAP
    dist = c - session_vwap
    band_std = dist.rolling(20).std()
    df["vwap_std_upper"] = session_vwap + 2 * band_std
    df["vwap_std_lower"] = session_vwap - 2 * band_std
    df["vwap_std_dist"]  = dist / band_std.replace(0, np.nan)

    # 46. Relative volume percentile (0–1) over 60 bars
    df["volume_percentile"] = v.rolling(60).rank(pct=True)


# ── 5. Multi-Timeframe Features (7) ──────────────────────────────────────────

def _add_multi_timeframe(df: pd.DataFrame) -> None:
    c = df["close"]

    # These approximate higher-timeframe values from the primary timeframe data.
    # For 5min primary: 15min ≈ 3 bars, 1hr ≈ 12 bars, 4hr ≈ 48 bars

    # 47. 15-min close (every 3 bars of 5-min)
    df["close_15m"] = c.rolling(3).mean()
    df["rsi_15m"]   = RSIIndicator(df["close_15m"].ffill(), window=14).rsi()

    # 48. 1-hour RSI proxy
    df["close_1h"] = c.rolling(12).mean()
    df["rsi_1h"]   = RSIIndicator(df["close_1h"].ffill(), window=14).rsi()

    # 49. Higher timeframe trend: slope of 12-bar EMA of close (≈ 1hr EMA)
    df["htf_ema_slope"] = df["close_1h"].diff(3) / df["close_1h"].shift(3).replace(0, np.nan)

    # 50. Daily range position: (close - rolling_low_78) / (rolling_high_78 - rolling_low_78)
    # 78 bars of 5min ≈ 1 trading day (6.5hrs × 12 bars/hr)
    bars_per_day = 78
    daily_high = df["high"].rolling(bars_per_day).max()
    daily_low  = df["low"].rolling(bars_per_day).min()
    df["day_range_position"] = (c - daily_low) / (daily_high - daily_low).replace(0, np.nan)

    # 51. Opening gap: (today open - yesterday close) / yesterday close
    # Session open = the 09:15 IST bar (the index is stored UTC → convert, FEAT-TZ).
    ist = _ist_index(df.index)
    if isinstance(ist, pd.DatetimeIndex):
        open_mask = (ist.hour == 9) & (ist.minute == 15)
    else:
        open_mask = np.zeros(len(df), dtype=bool)
    df["session_open"] = df["open"].where(pd.Series(open_mask, index=df.index), other=np.nan).ffill()
    df["gap_pct"] = (df["session_open"] - c.shift(bars_per_day)) / c.shift(bars_per_day).replace(0, np.nan)

    # 52. Multi-tf RSI alignment: sum of signs of (rsi_14, rsi_1h)
    df["mtf_rsi_align"] = (
        np.sign(df["rsi_14"] - 50).fillna(0) +
        np.sign(df["rsi_1h"] - 50).fillna(0)
    )


# ── 6. Session Features (7) ───────────────────────────────────────────────────

def _add_session_features(df: pd.DataFrame) -> None:
    c = df["close"]
    # All session-relative features key off IST, not the stored UTC index (see _ist_index).
    ist = _ist_index(df.index)

    # 53. Time of day normalized: 0.0 = 9:15 IST, 1.0 = 15:30 IST
    if isinstance(ist, pd.DatetimeIndex):
        session_minutes = pd.Series(
            (ist.hour * 60 + ist.minute) - (9 * 60 + 15),
            index=df.index,
        )
        df["time_norm"] = session_minutes.clip(0, 375) / 375.0
    else:
        df["time_norm"] = 0.5

    # 54. First 30-min range breakout flag
    # (price above open + 0.5×ATR from the first 6 bars = first 30 min)
    df["first_30m_high"] = df["high"].rolling(6).max().shift(6)
    df["first_30m_low"]  = df["low"].rolling(6).min().shift(6)
    df["orb_signal"] = np.where(
        c > df["first_30m_high"], 1.0,
        np.where(c < df["first_30m_low"], -1.0, 0.0)
    )

    # 55. Session cumulative return so far
    df["session_return"] = (c - df["session_open"]) / df["session_open"].replace(0, np.nan)

    # 56. Day of week (0=Mon, 4=Fri) — normalized 0–1 (IST calendar)
    if isinstance(ist, pd.DatetimeIndex):
        df["day_of_week"] = pd.Series(ist.dayofweek / 4.0, index=df.index)
    else:
        df["day_of_week"] = 0.5

    # 57. F&O expiry proximity (days to nearest Thursday, normalized 0–1, IST)
    if isinstance(ist, pd.DatetimeIndex):
        def days_to_thursday(d) -> float:
            day_num = d.weekday()  # 0=Mon, 3=Thu
            days_away = (3 - day_num) % 7
            return days_away / 7.0
        df["expiry_proximity"] = pd.Series(
            [days_to_thursday(t) for t in ist], index=df.index)
    else:
        df["expiry_proximity"] = 0.5


# ── 7. Microstructure Features (6) ────────────────────────────────────────────

def _add_microstructure_features(df: pd.DataFrame) -> None:
    c = df["close"]
    o = df["open"]
    h = df["high"]
    l = df["low"]

    # 58. Candle body size as % of ATR (how decisive is the move)
    df["body_pct_atr"] = (c - o).abs() / df["atr_14"].replace(0, np.nan)

    # 59. Upper wick ratio: how much of the bar range is upper wick
    bar_range = (h - l).replace(0, np.nan)
    upper_wick = h - np.maximum(o, c)
    lower_wick = np.minimum(o, c) - l
    df["upper_wick_ratio"] = upper_wick / bar_range
    df["lower_wick_ratio"] = lower_wick / bar_range

    # 60. Bar direction: +1 = bullish (close > open), -1 = bearish
    df["bar_direction"] = np.sign(c - o)

    # 61. Consecutive direction: how many bars in same direction
    direction = np.sign(c - c.shift(1))
    df["consec_direction"] = direction.groupby((direction != direction.shift()).cumsum()).cumcount() + 1
    df["consec_direction"] *= direction  # positive for up streak, negative for down streak

    # 62. High-Low range as % of price (single-bar volatility)
    df["hl_range_pct"] = (h - l) / c.replace(0, np.nan)


# ── 8. Derived / Composite Features (12) ─────────────────────────────────────

def _add_derived_features(df: pd.DataFrame) -> None:
    c = df["close"]

    # 63. Trend-momentum agreement: +1 if both EMA trend and RSI agree on direction
    ema_trend  = np.sign(df.get("ema20_slope", pd.Series(0, index=df.index)))
    rsi_signal = np.sign(df.get("rsi_14", pd.Series(50, index=df.index)) - 50)
    df["trend_momentum_agree"] = (ema_trend == rsi_signal).astype(float)

    # 64. Oversold score: how many indicators are in oversold zone
    df["oversold_count"] = (
        (df.get("rsi_14",   50) < 30).astype(int) +
        (df.get("stoch_k",  50) < 20).astype(int) +
        (df.get("bb_pct_b",  0.5) < 0.1).astype(int) +
        (df.get("williams_r", -50) < -80).astype(int) +
        (df.get("mfi_14",   50) < 20).astype(int)
    )

    # 65. Overbought score (mirror of oversold)
    df["overbought_count"] = (
        (df.get("rsi_14",   50) > 70).astype(int) +
        (df.get("stoch_k",  50) > 80).astype(int) +
        (df.get("bb_pct_b",  0.5) > 0.9).astype(int) +
        (df.get("williams_r", -50) > -20).astype(int) +
        (df.get("mfi_14",   50) > 80).astype(int)
    )

    # 66. Volume-confirmed breakout
    df["vol_confirmed_breakout"] = (
        (df.get("volume_ratio", 1.0) > 1.5) &
        (df.get("adx_14", 20) > 20) &
        (df.get("ema_cross_9_20", 0) == 1)
    ).astype(float)

    # 67. Mean reversion setup score
    df["mean_rev_setup"] = (
        (df.get("bb_pct_b", 0.5) < 0.15).astype(int) +   # at lower BB
        (df.get("rsi_14", 50)  < 35).astype(int) +         # RSI oversold
        (df.get("vwap_dist_pct", 0).abs() > 0.01).astype(int)  # stretched from VWAP
    )

    # 68. Momentum consistency: how many of last 3 bars are in same direction
    price_dir = np.sign(c.diff())
    df["momentum_consistency_3"] = (
        price_dir.rolling(3).apply(lambda x: (x == x[-1]).sum() / 3, raw=True)
    )

    # 69. Z-score of close relative to 20-bar rolling window
    rolling_mean = c.rolling(20).mean()
    rolling_std  = c.rolling(20).std()
    df["close_zscore"] = (c - rolling_mean) / rolling_std.replace(0, np.nan)

    # 70. Momentum quality: RSI slope × volume ratio (strong + confirmed)
    rsi_slope_s   = df["rsi_slope"]   if "rsi_slope"   in df.columns else pd.Series(0.0, index=df.index)
    vol_ratio_s   = df["volume_ratio"] if "volume_ratio" in df.columns else pd.Series(1.0, index=df.index)
    df["momentum_quality"] = (rsi_slope_s * vol_ratio_s).clip(-100, 100)

    # 71. Trend strength composite: ADX × DI spread
    adx  = df.get("adx_14",   pd.Series(20, index=df.index))
    di_s = df.get("di_spread", pd.Series(0,  index=df.index))
    df["trend_strength"] = (adx / 100.0) * np.sign(di_s)

    # 72. Breakout score: proximity to recent high/low
    df["high_20"]    = df["high"].rolling(20).max()
    df["low_20"]     = df["low"].rolling(20).min()
    df["pct_from_high"] = (df["high_20"] - c) / df["high_20"].replace(0, np.nan)
    df["pct_from_low"]  = (c - df["low_20"]) / df["low_20"].replace(0, np.nan)

    # 73. Score of bars where RSI diverges from price (hidden divergence flag)
    price_higher = (c.diff(5) > 0).astype(int)
    rsi_lower    = (df.get("rsi_14", pd.Series(50, index=df.index)).diff(5) < 0).astype(int)
    df["bearish_divergence"] = (price_higher & rsi_lower).astype(float)

    price_lower  = (c.diff(5) < 0).astype(int)
    rsi_higher   = (df.get("rsi_14", pd.Series(50, index=df.index)).diff(5) > 0).astype(int)
    df["bullish_divergence"] = (price_lower & rsi_higher).astype(float)


# ── Feature list ──────────────────────────────────────────────────────────────
FEATURE_COLUMNS: list[str] = [
    # Momentum (14)
    "rsi_14", "rsi_7", "rsi_slope", "macd_hist", "macd_line", "macd_signal",
    "macd_hist_slope", "roc_5", "roc_10", "roc_20",
    "stoch_k", "stoch_d", "williams_r", "cci_20", "mfi_14",
    "price_momentum_5", "price_momentum_15",
    # Trend (13)
    "ema_9", "ema_20", "ema_50",
    "price_vs_ema9", "price_vs_ema20", "price_vs_ema50",
    "ema_cross_9_20", "adx_14", "dmp_14", "dmn_14", "di_spread",
    "vwap_dist_pct", "ema20_slope", "psar_bull", "hma_20", "price_vs_hma20",
    # Volatility (11)
    "atr_14", "atr_pct", "atr_percentile",
    "bb_upper", "bb_lower", "bb_mid", "bb_width", "bb_pct_b", "bb_squeeze",
    "hist_vol_5", "hist_vol_20", "vol_ratio", "kc_width", "true_range",
    # Volume (10)
    "volume_ratio", "volume_spike", "obv", "obv_slope", "volume_trend",
    "cmf_20", "ad_line",
    "vwap_std_upper", "vwap_std_lower", "vwap_std_dist", "volume_percentile",
    # Multi-timeframe (7)
    "close_15m", "rsi_15m", "close_1h", "rsi_1h",
    "htf_ema_slope", "day_range_position", "gap_pct", "mtf_rsi_align",
    # Session (6)
    "time_norm", "orb_signal", "session_return",
    "day_of_week", "expiry_proximity",
    # Microstructure (6)
    "body_pct_atr", "upper_wick_ratio", "lower_wick_ratio",
    "bar_direction", "consec_direction", "hl_range_pct",
    # Derived (13)
    "trend_momentum_agree", "oversold_count", "overbought_count",
    "vol_confirmed_breakout", "mean_rev_setup", "momentum_consistency_3",
    "close_zscore", "momentum_quality", "trend_strength",
    "pct_from_high", "pct_from_low",
    "bearish_divergence", "bullish_divergence",
]
