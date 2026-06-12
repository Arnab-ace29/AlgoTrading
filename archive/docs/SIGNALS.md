# SIGNALS — Every Signal, Formula, Parameters & Features

> Complete reference for all signals across all phases.
> Add notes as you test and tune each signal.

---

## Signal Interface

Every signal extends `BaseSignal`:

```python
class BaseSignal(ABC):
    name: str = ""           # unique identifier, used as dict key in settings
    weight: float = 0.0      # default weight in ensemble (configurable via dashboard)
    phase: int = 1           # phase in which this signal was added

    @abstractmethod
    def compute(self, df: pd.DataFrame, symbol: str) -> float:
        """Returns score in [-1.0, +1.0].
        -1.0 = strong short (sell signal)
         0.0 = neutral / no clear signal
        +1.0 = strong long (buy signal)
        Positive = bullish, Negative = bearish.
        """

    def is_ready(self, df: pd.DataFrame) -> bool:
        return len(df) >= 50  # Minimum bars needed for reliable computation
```

---

## Complete 80-Feature List

All features computed by `features/indicators.py → compute_all_features(df)`.

### Category 1: Momentum (8 features)

| Feature | Formula | Notes |
|---|---|---|
| `rsi_14` | RSI(14) on close | 0–100 scale |
| `macd` | EMA12 - EMA26 on close | Centered at 0 |
| `macd_signal` | EMA9 of MACD | |
| `macd_hist` | MACD - MACD_signal | Histogram |
| `stoch_rsi` | RSI of RSI(14), K=3,D=3 | 0–1 scale |
| `williams_r` | Williams %R(14) | -100 to 0 |
| `roc_10` | (close - close[10]) / close[10] × 100 | % rate of change |
| `roc_20` | (close - close[20]) / close[20] × 100 | |

### Category 2: Trend (9 features)

| Feature | Formula | Notes |
|---|---|---|
| `ema_9` | EMA(9) on close | |
| `ema_20` | EMA(20) on close | |
| `ema_50` | EMA(50) on close | |
| `sma_200` | SMA(200) on close | Daily trend context |
| `vwap` | Cumulative(price×vol) / Cumulative(vol) | Resets at 9:15 IST |
| `vwap_dist_pct` | (close - vwap) / vwap × 100 | % deviation from VWAP |
| `adx` | ADX(14) | > 25 = trending |
| `di_plus` | +DI(14) | Bullish directional |
| `di_minus` | -DI(14) | Bearish directional |

### Category 3: Volatility (6 features)

| Feature | Formula | Notes |
|---|---|---|
| `atr_14` | ATR(14) on OHLC | Absolute volatility |
| `bb_upper` | SMA(20) + 2 × StdDev(20) | Bollinger upper |
| `bb_lower` | SMA(20) - 2 × StdDev(20) | Bollinger lower |
| `bb_pct_b` | (close - bb_lower) / (bb_upper - bb_lower) | 0=at lower, 1=at upper |
| `vol_20` | Realized vol = StdDev of log returns × √252 over 20 bars | Annualized |
| `vol_60` | Same over 60 bars | Longer-term vol |

### Category 4: Volume (5 features)

| Feature | Formula | Notes |
|---|---|---|
| `obv_slope` | Slope of OBV over last 10 bars | Rising OBV = accumulation |
| `mfi_14` | Money Flow Index(14) | 0–100 |
| `volume_ratio` | volume / SMA(volume, 20) | > 1.5 = volume spike |
| `volume_delta` | buy_vol - sell_vol (from tick data) | Signed volume pressure |
| `volume_spike` | 1 if volume_ratio > 2.0, else 0 | Binary flag |

### Category 5: Multi-Timeframe (8 features)

| Feature | Formula | Notes |
|---|---|---|
| `rsi_14_5m` | RSI(14) on 5-min close | Computed on 5-min aggregated data |
| `rsi_14_15m` | RSI(14) on 15-min close | |
| `ema_20_5m` | EMA(20) on 5-min close | |
| `ema_20_15m` | EMA(20) on 15-min close | |
| `macd_5m` | MACD on 5-min close | |
| `vwap_5m` | VWAP on 5-min bars | Micro-VWAP |
| `vwap_15m` | VWAP on 15-min bars | |
| `atr_15m` | ATR(14) on 15-min OHLC | Wider range context |

### Category 6: Options (8 features)

| Feature | Source | Notes |
|---|---|---|
| `pcr` | nsepython option chain | Put-Call Ratio by OI. > 1.5 = oversold, < 0.5 = overbought |
| `oi_change_pct` | nsepython option chain | % change in OI from previous snapshot |
| `iv_atm` | nsepython option chain | ATM implied volatility % |
| `delta_atm` | nsepython option chain | ATM option delta |
| `gamma_atm` | nsepython option chain | ATM option gamma |
| `theta_pressure` | Computed from theta/premium | How much time decay per day |
| `days_to_expiry` | Calendar from expiry date | 0 = expiry day (avoid trading) |
| `oi_ratio` | CE OI / PE OI | > 1 = more calls written (bearish pressure) |

### Category 7: Session (6 features)

| Feature | Formula | Notes |
|---|---|---|
| `mins_since_open` | (current_time - 09:15).minutes | 0 at open, 375 at close |
| `session_progress` | mins_since_open / 375 | 0.0 to 1.0 |
| `is_first_hour` | 1 if time ≤ 10:15 | High volatility window |
| `is_last_hour` | 1 if time ≥ 14:30 | Closing volatility |
| `is_power_hour` | 1 if 9:15 ≤ time ≤ 10:30 OR 14:00 ≤ time ≤ 15:30 | |
| `day_of_week` | 0=Mon, 1=Tue, ..., 4=Fri | Monday/Friday effects |

### Category 8: Microstructure (5 features, tick-level)

| Feature | Formula | Notes |
|---|---|---|
| `bid_ask_spread` | (ask - bid) / mid_price × 10000 | In basis points |
| `order_imbalance` | (bid_qty - ask_qty) / (bid_qty + ask_qty) | -1 to +1 |
| `trade_size_spike` | avg_trade_size / 20-bar avg_trade_size | > 2.0 = large trade |
| `volume_burst` | 1 if volume in last 10 ticks > 3× baseline | Binary |
| `tick_momentum` | net signed ticks (upticks - downticks) / total ticks | -1 to +1 |

### Category 9: Derived Features (25+ features)

| Feature | Formula | Notes |
|---|---|---|
| `rsi_divergence` | Price making new high but RSI not → bearish divergence | +1/-1 flag |
| `macd_hist_slope` | macd_hist[0] - macd_hist[3] | Histogram momentum |
| `vwap_std_dev` | Rolling StdDev of (close - vwap) over 20 bars | VWAP tightness |
| `price_to_ema9` | (close - ema_9) / ema_9 × 100 | % distance |
| `price_to_ema20` | (close - ema_20) / ema_20 × 100 | |
| `price_to_ema50` | (close - ema_50) / ema_50 × 100 | |
| `ema9_slope` | (ema_9 - ema_9[5]) / ema_9[5] × 100 | Trend acceleration |
| `ema20_slope` | (ema_20 - ema_20[5]) / ema_20[5] × 100 | |
| `bb_squeeze` | 1 if (bb_upper - bb_lower) < 20-day avg bandwidth × 0.5 | Pre-breakout |
| `vol_ratio` | vol_20 / vol_60 | Volatility regime |
| `corr_nifty_5d` | Pearson corr of stock vs NIFTY over 5 days | Beta-like metric |
| `high_of_day` | max(high since 9:15) | Resistance level |
| `low_of_day` | min(low since 9:15) | Support level |
| `price_to_hod_pct` | (close - high_of_day) / high_of_day × 100 | Distance from day high |
| `price_to_lod_pct` | (close - low_of_day) / low_of_day × 100 | Distance from day low |
| `open_gap_pct` | (open[today] - close[yesterday]) / close[yesterday] × 100 | Gap up/down |
| `session_range` | high_of_day - low_of_day | Intraday range so far |
| `range_utilization` | session_range / atr_14 | How much of ATR used |
| ... | (extend as needed) | |

---

## Phase 1: Technical Signals

### Signal 1: VWAP Momentum Breakout

**File:** `signals/technical/vwap_breakout.py`
**Phase:** 1
**Default weight:** 0.40
**Backtest WR (AI-trader):** 60–100% across profiles

**Long conditions (need ≥ 3 of 4):**
```
✓ close > vwap                        (price above intraday average)
✓ rsi_14 > 55                         (momentum not overbought yet)
✓ ema_20 > ema_50                     (short-term trend above medium-term)
✓ volume_spike OR volume_ratio > 1.5  (volume confirmation)
```

**Short conditions (need ≥ 3 of 4):**
```
✓ close < vwap
✓ rsi_14 < 45
✓ ema_20 < ema_50
✓ volume_spike OR volume_ratio > 1.5
```

**Score formula:**
```python
long_conditions = [close > vwap, rsi > 55, ema20 > ema50, volume_confirm]
score = sum(long_conditions) / 4.0   # 0.0 to 1.0
# or for short:
short_conditions = [close < vwap, rsi < 45, ema20 < ema50, volume_confirm]
score = -(sum(short_conditions) / 4.0)  # -1.0 to 0.0
```

**Regime affinity:** TRENDING_UP / TRENDING_DOWN
**Avoid in:** CHOPPY, MEAN_REVERTING

**Tuning notes:**
- RSI threshold: 55/45 is AI-trader proven. Can try 52/48 for more trades.
- Volume threshold: 1.5 is conservative. Can try 1.3 for more signals.
- Score threshold for entry: 0.65 minimum (= all 4 conditions met). Never go below 0.55.

---

### Signal 2: RSI Momentum

**File:** `signals/technical/rsi_momentum.py`
**Phase:** 1
**Default weight:** 0.35
**Best for:** Trend continuation entries after pullback

**Long conditions:**
```
✓ RSI crossed above 50 in last 3 bars (momentum shift)
✓ macd_hist > 0                        (MACD confirming)
✓ roc_10 > 0                           (positive 10-bar return)
```

**Short conditions:**
```
✓ RSI crossed below 50 in last 3 bars
✓ macd_hist < 0
✓ roc_10 < 0
```

**Score formula:**
```python
# Long
conditions_met = sum([rsi_crossed_above_50, macd_hist > 0, roc_10 > 0])
score = conditions_met / 3.0

# Add strength modifier:
if rsi_14 > 60: score *= 1.1          # stronger momentum
if macd_hist > macd_hist_peak * 0.7:  # histogram near peak → cautious
    score *= 0.9
```

**Regime affinity:** TRENDING_UP / TRENDING_DOWN
**Avoid in:** MEAN_REVERTING (RSI oscillates around 50 too often)

---

### Signal 3: Mean Reversion

**File:** `signals/technical/mean_reversion.py`
**Phase:** 1
**Default weight:** 0.25
**Backtest WR (AI-trader):** 78% when conditions align
**Note:** Rare signals — fires only in oversold/overbought extremes

**Long conditions (oversold bounce):**
```
✓ rsi_14 < 30                          (oversold)
✓ close ≤ bb_lower                     (at lower Bollinger Band)
✓ vwap_dist_pct < -0.3%               (extended below VWAP)
```

**Short conditions (overbought reversal):**
```
✓ rsi_14 > 70
✓ close ≥ bb_upper
✓ vwap_dist_pct > +0.3%
```

**Score formula:**
```python
long_conditions = [rsi < 30, close <= bb_lower, vwap_dist < -0.003]
score = sum(long_conditions) / 3.0
# Full score = 1.0 (all 3 met), partial score = 0.67 (2/3 met)
```

**Regime constraint (enforced in aggregator):**
- **Only active in** MEAN_REVERTING or CHOPPY regime
- Weight dropped to 0.05 in TRENDING regimes (don't fight the trend)

---

## Phase 2: ML Signals

### Signal 4: Macro XGBoost (Directional Gate)

**File:** `signals/ml/macro_model.py`
**Phase:** 2
**Default weight:** 0.50 (dominant signal in Phase 2)
**Model:** XGBClassifier

**Label:** `y = 1` if `close[t + 15min] / close[t] >= 1.001` (≥0.1% rise), else `0`

**Features:** Top 50 from 80-feature set (selected by XGBoost feature importance, correlated features dropped)

**Output:** `predict_proba(X)[1]` → `P(bullish)` ∈ [0, 1]

**Score calculation:**
```python
prob = model.predict_proba(features)[1]
score = (prob - 0.5) * 2  # Map [0,1] → [-1, +1] centered at 0
# 0.5 prob = 0.0 score (neutral)
# 0.75 prob = 0.5 score (moderate long)
# 0.90 prob = 0.8 score (strong long)
```

**Training parameters:**
```python
XGBClassifier(
    n_estimators=500,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=10,    # prevent overfitting on small samples
    scale_pos_weight=1.0,   # adjust if class imbalance
    eval_metric='auc',
    early_stopping_rounds=30,
)
```

**Walk-forward scheme:**
- 5 folds minimum
- 120-day train window / 30-day test
- Retrain daily on rolling 180-day window

**Target AUC:** ≥ 0.58 (≥ 0.50 is better than random, ≥ 0.60 is excellent for intraday)

---

### Signal 5: Micro XGBoost (Entry Confirmation)

**File:** `signals/ml/micro_model.py`
**Phase:** 2
**Role:** Binary gate (not a weight contributor) — blocks entry if below 0.45

**Label:** `y = 1` if net buying pressure (uptick volume - downtick volume) in next 30 ticks > 0

**Features:** 5 microstructure features only:
- bid_ask_spread
- order_imbalance
- trade_size_spike
- volume_burst
- tick_momentum

**Output:** `predict_proba(X)[1]` → probability of net buying pressure

**Usage in runner:**
```python
if micro_model.predict_proba(tick_features)[1] < 0.45:
    skip_entry()  # Don't catch a falling knife
```

---

### Signal 6: Regime Detector

**File:** `signals/ml/regime_detector.py`
**Phase:** 2
**Role:** Not a score contributor — sets regime flag that adjusts weights

**Phase 2a (rule-based, build first):**
```python
def classify_regime(df) -> str:
    adx = df['adx'].iloc[-1]
    ema9 = df['ema_9'].iloc[-1]
    ema20 = df['ema_20'].iloc[-1]
    ema50 = df['ema_50'].iloc[-1]
    close = df['close'].iloc[-1]
    vol_ratio = df['vol_ratio'].iloc[-1]  # vol_20 / vol_60

    if adx > 25:
        if ema9 > ema20 > ema50 and close > ema20:
            return "TRENDING_UP"
        elif ema9 < ema20 < ema50 and close < ema20:
            return "TRENDING_DOWN"

    if adx < 20 and vol_ratio < 0.8:
        return "MEAN_REVERTING"

    return "CHOPPY"
```

**Phase 2b (upgrade to HMM later):**
```python
from hmmlearn import hmm
model = hmm.GaussianHMM(n_components=4, covariance_type="full")
# Features: returns, volatility, volume
# 4 states map to our 4 regime classes
```

---

### Signal 7: Strategy Outcome Models

**File:** `signals/ml/strategy_outcomes.py`
**Phase:** 2
**Role:** Final gate — block entry if WIN probability < 0.55
**One model per strategy** (3 models: vwap_breakout, rsi_momentum, mean_reversion)

**Label:** `y = 1` if trade PnL > 0 (WIN), from actual `trade_log`

**Features:** Same 50 features used by macro model (market state at entry)

**Usage:**
```python
outcome_prob = strategy_models[strategy_name].predict_proba(features)[1]
if outcome_prob < 0.55:
    log_blocked_trade(reason="OUTCOME_MODEL_GATE")
    return  # Skip entry
```

**Important:** Only activate after ≥ 15 labeled trades per strategy. Before that, skip this gate.

---

### Signal 8: RL Exit Agent (Q-Learning)

**File:** `models/rl_exit_agent.py`
**Phase:** 2
**Role:** Decides when to exit an open position. Replaces fixed SL/target rules over time.
**Learns from:** Every completed trade in `trade_log` — reward = realized PnL at episode end.

**State space (8 features, all trade-relative — no absolute prices):**
```python
state = [
    time_in_trade_normalized,   # 0.0 = just entered, 1.0 = market close
    unrealized_pnl_pct,         # current PnL as % of entry price
    sl_distance_pct,            # % distance between LTP and stop-loss
    target_distance_pct,        # % distance between LTP and target
    composite_score_now,        # current ensemble score for this symbol
    volume_trend,               # volume_ratio now vs volume_ratio at entry
    regime_encoded,             # 0=TRENDING_UP, 1=TRENDING_DOWN, 2=MEAN_REV, 3=CHOPPY
    score_at_entry,             # original score that triggered the entry
]
```

**Actions:**
- `0` = HOLD — do nothing this bar
- `1` = EXIT_NOW — market exit immediately
- `2` = TIGHTEN_SL — move SL to lock in partial profit

**Reward function:**
```python
# At episode end (when position closes, for any reason):
reward = net_pnl_pct  # realized net PnL as %
# During HOLD steps: small negative reward to discourage holding forever
step_penalty = -0.001 if action == HOLD else 0
```

**Training algorithm:** Q-learning with experience replay
```python
# Simple tabular Q-learning first → then DQN (PyTorch) if state space too large
# Each trade = 1 episode (sequence of states from entry to exit)
# Train every evening post-market on all trade journeys
# Rolling 90-day window of trades (older trades discarded)
```

**How it learns from mistakes:**
- Held too long, gave back profit → small positive reward (or negative if SL hit) → learns to EXIT sooner when score deteriorates
- Exited too early on a trending trade → small positive reward vs what it could have been → learns to HOLD longer in TRENDING regimes
- Tightened SL and got stopped out just before big move → negative reward vs HOLD → learns TIGHTEN is risky when momentum is strong
- After 50+ trades: RL agent meaningfully outperforms fixed SL/target rules for exit timing
- Visualization in dashboard `/models` page: Q-value heatmap (state → best action)

**Cold start:** For first 20 trades, fixed SL/target rules are used (RL has no data yet). RL gradually takes over as experience accumulates.

---

### Signal 9: RL Entry Agent (Q-Learning) — Phase 2b

**File:** `models/rl_entry_agent.py`
**Phase:** 2b (after RL exit agent is stable)
**Role:** Decides whether to ENTER or SKIP when the ensemble score crosses threshold.
**Purpose:** Learn market conditions when the ensemble score is misleading (e.g., score = 0.70 but market is about to reverse).

**State space (10 features):**
```python
state = [
    composite_score,            # ensemble score that triggered the signal
    regime_encoded,             # current regime
    time_of_day_normalized,     # 0.0 = 9:15, 1.0 = 15:30
    vix_normalized,             # VIX / 52-week-high-VIX
    session_pnl_normalized,     # today's PnL so far / daily loss limit
    open_positions_count,       # number of currently open positions
    volume_ratio,               # current volume vs 20-day avg
    score_momentum,             # score_now - score_5bars_ago (improving or declining?)
    macro_model_prob,           # XGBoost P(bullish) — Phase 2+
    recent_win_rate,            # last 10 trades win rate (is the system in drawdown?)
]
```

**Actions:**
- `0` = SKIP — don't enter this signal
- `1` = ENTER — proceed with entry (lot size still determined by score tier)

**Reward function:**
```python
# Reward assigned after the trade completes:
reward = net_pnl_pct if action == ENTER else 0
# If SKIP: reward = 0 (neutral — we don't know the counterfactual)
# Counterfactual tracking: log what WOULD have happened on SKIPs
#   → use these in batch training as negative examples
```

**How it learns from mistakes:**
- Entered on 0.68 score during CHOPPY regime → loss → learns to require higher threshold in CHOPPY
- Entered near EOD when session PnL was already positive → unnecessary risk → learns to reduce entries late in profitable sessions
- Skipped a 0.70 score that would have been a big win → adjusts SKIP threshold upward
- After 100+ trade decisions: entry agent meaningfully improves win rate vs raw threshold entry

**Activation threshold:** Only activate after ≥ 50 entry decisions logged. Before that, all signals above threshold auto-enter.

---

## Phase 3: News & Sentiment Signals

### Signal 8: NSE Announcement Filter

**File:** `signals/news/nse_announcements.py`
**Phase:** 3
**Role:** Suppression filter — sets all scores to 0 near events

**Events tracked:**
- Board meetings (earnings results)
- Dividend record dates
- Stock splits and bonus issues
- Promoter pledge changes
- Bulk deals / block deals

**Rules:**
```python
def is_event_window(symbol: str, timestamp: datetime) -> bool:
    events = get_upcoming_events(symbol, db)
    for event in events:
        if abs((event.date - timestamp.date()).days) == 0:
            # Same day as event
            if event.is_intraday_event:
                # Suppress 30 min before to 60 min after
                return is_within_minutes(timestamp, event.time, 30, 60)
    return False
```

**PEAD signal (Post-Earnings Announcement Drift):**
```python
# After earnings release:
if earnings_surprise_pct > 5:
    # Positive surprise → add bullish bias for 20 trading days
    pead_score = min(earnings_surprise_pct / 20, 0.3)  # max +0.3 boost
elif earnings_surprise_pct < -5:
    pead_score = max(earnings_surprise_pct / 20, -0.3)
```

---

### Signal 9: FinBERT News Sentiment

**File:** `signals/news/finbert_sentiment.py`
**Phase:** 3
**Default weight:** 0.15
**Model:** `ProsusAI/finbert` (HuggingFace)

**Score computation:**
```python
from transformers import pipeline
finbert = pipeline("sentiment-analysis", model="ProsusAI/finbert")

def compute_sentiment(headlines: list[str]) -> float:
    results = finbert(headlines)
    positive = sum(r['score'] for r in results if r['label'] == 'positive')
    negative = sum(r['score'] for r in results if r['label'] == 'negative')
    n = len(results)
    return (positive - negative) / n  # [-1, +1]
```

**Caching:** Store in `sentiment_cache` table. Expire after 30 minutes.

**Sources by priority:**
1. NSE corporate announcement text (highest signal quality)
2. MoneyControl stock-specific headlines
3. Google News top 5 results for `"{symbol} NSE"`

---

### Signal 10: Options Flow

**File:** `signals/options_flow/flow_signals.py`
**Phase:** 3
**Default weight:** 0.10

**Sub-signals:**
```python
def compute_pcr_signal(pcr: float) -> float:
    if pcr > 1.8: return +0.8    # extreme put buying = contrarian bullish
    if pcr > 1.5: return +0.4
    if pcr < 0.5: return -0.8    # extreme call buying = contrarian bearish
    if pcr < 0.7: return -0.4
    return 0.0

def compute_oi_momentum(oi_change_pct: float, side: str) -> float:
    # Large OI increase = conviction (smart money building position)
    if abs(oi_change_pct) > 5:
        return 0.3 * (1 if side == "long" else -1)
    return 0.0

def compute_iv_skew(call_iv: float, put_iv: float) -> float:
    skew = call_iv - put_iv
    if skew > 2: return +0.3   # calls more expensive = bullish demand
    if skew < -2: return -0.3
    return 0.0
```

---

## Phase 4: LLM Signals (Future)

### Signal 11: Technical Analyst Agent

**File:** `signals/llm/technical_agent.py`
**Phase:** 4

Prompt template:
```
You are a technical analyst. Given these indicator values for {symbol}:
RSI: {rsi}, MACD: {macd}, VWAP distance: {vwap_dist}%, ADX: {adx},
BB %B: {bb_pct_b}, Regime: {regime}

Rate the bullish/bearish bias on a scale of -1.0 (strongly bearish) to +1.0 (strongly bullish).
Reply with ONLY a JSON: {"score": float, "reasoning": "one sentence"}
```

### Signal 12: News Analyst Agent

**File:** `signals/llm/news_agent.py`
**Phase:** 4

Prompt template:
```
You are a financial news analyst for Indian markets.
Headlines for {symbol} in the last 30 minutes:
{headlines}

Rate the market impact on a scale of -1.0 (very negative) to +1.0 (very positive).
Reply with ONLY a JSON: {"score": float, "impact": "one sentence"}
```

### Signal 13: Risk Assessment Agent

**File:** `signals/llm/risk_agent.py`
**Phase:** 4

Inputs: current portfolio state, VIX, sector rotation, news sentiment aggregate
Output: risk multiplier [0.0, 1.0] applied to final position size

---

## Ensemble Formula — By Phase

### Phase 1 Formula
```
score = 0.40 × vwap_breakout.compute()
      + 0.35 × rsi_momentum.compute()
      + 0.25 × mean_reversion.compute()
      + regime_bonus
```

### Phase 2 Formula (AI-trader proven)
```
score = 0.50 × macro_xgboost.compute()
      + 0.30 × options_flow.compute()
      + 0.20 × technical_strength
      + regime_bonus

# technical_strength = weighted average of Phase 1 signals at reduced weights
# Entry gate: micro_model must confirm (≥ 0.45)
# Final gate: outcome_model must confirm (≥ 0.55) if ≥ 15 trades available
```

### Phase 3 Formula
```
score = 0.35 × macro_xgboost.compute()
      + 0.25 × options_flow.compute()
      + 0.15 × technical_strength
      + 0.15 × finbert_sentiment.compute()
      + 0.10 × options_flow.compute()   # enhanced
      + regime_bonus
```

### Phase 4 Formula
```
score = 0.30 × macro_xgboost.compute()
      + 0.20 × options_flow.compute()
      + 0.15 × technical_strength
      + 0.15 × finbert_sentiment.compute()
      + 0.10 × llm_technical_agent.compute()
      + 0.10 × llm_news_agent.compute()
      + regime_bonus
```
`× llm_risk_agent.multiplier` applied to final position size (not score)

---

## Position Sizing

### Score tier → conviction (SIZE-04)

The score tier sets a **conviction level**, not a literal share count:

| Score | Conviction | Regime override |
|---|---|---|
| 0.55–0.65 | Signal only (no trade) | |
| 0.65–0.70 | tier 1 (⅓ risk budget) | Stands down in CHOPPY |
| 0.70–0.75 | tier 2 (⅔ risk budget) | |
| ≥ 0.75 | tier 3 (full per-trade risk budget) | |

- **Cash equity (`lot_size == 1`):** position is **risk-based** — `shares = (per-trade
  risk budget × conviction) ÷ stop-distance`, where the per-trade budget =
  `max_daily_loss_pct/100 × capital ÷ max_trades_per_day`. This deploys real capital;
  the old "1/2/3 lots × lot_size=1" gave 1–3 *shares* (~1% of capital), so costs
  dominated and the strategy could not make money by construction.
- **F&O (`lot_size > 1`):** the tier is the lot count (1/2/3), capped by the profile.

> **Reality check (BT-EDGE, see KNOWN_ISSUES):** correct sizing exposed that the
> Phase-1 ensemble currently has **no gross edge net of costs** on the tested sample
> (~1 bp gross vs ~16 bps costs). Sizing is now right; the *edge* is the open problem.

### MIS Margin Leverage (margin-aware sizing)

When `USE_MARGIN=true` (in `.env` or via the **MIS Margin** toggle in Action Replay), the
sizer scales qty by substituting `effective_capital = capital × MIS_multiplier` for the
risk budget calculation. This lets a small account trade proportionally larger positions
using the broker's intraday (MIS) leverage.

**Example — ₹20,000 capital, stock @ ₹500, ATR = ₹10, sl_dist = ₹20 (LOW profile)**

| | Cash only | MIS ON (5×) |
|---|---|---|
| Effective capital | ₹20,000 | ₹1,00,000 |
| Per-trade risk budget (2% / 10 trades) | ₹40 | ₹200 |
| Qty (`risk_budget / sl_dist`) | **2 shares** | **10 shares** |
| Notional | ₹1,000 | ₹5,000 |
| Margin blocked with broker | ₹1,000 | ₹1,000 (broker holds only 1/5) |
| Max loss if SL hits | ₹40 | ₹200 (1% of ₹20k actual capital) |

**Safety guards:**
- `MAX_MIS_LEVERAGE` (default `5.0`, set in `.env`) caps the applied multiplier regardless of what the broker allows for any individual stock.
- Hard notional cap: one trade cannot exceed `effective_capital / 3`, so no single position can absorb all available margin.
- The SL-based risk budget still applies — leveraged sizing only helps when ATR / price is large enough that the risk budget would otherwise give < 1 share.

**Per-stock multipliers** come from `data/margin_multipliers.json`, fetched via Upstox
`ChargeApi.post_margin`. The formula is `multiplier = notional / total_margin_required`.
A stock needing 20% margin → 5× multiplier; one needing 50% → 2×.

**One-time setup:**
```bash
# Requires UPSTOX_MODE=live and a valid LIVE_ACCESS_TOKEN in .env
python scripts/fetch_margin_multipliers.py          # fetches all universe symbols → data/margin_multipliers.json
python scripts/fetch_margin_multipliers.py --show-cached --top 20   # verify cache

# Refresh weekly (SEBI VAR margins change with volatility cycles)
```

**Relevant code:**
- `data/margin.py` — `fetch_margin_multipliers()`, `load_margin_multipliers()`, `get_multiplier(symbol)`
- `ensemble/position_sizing.py` — `PositionSizer.size(margin_multiplier=...)` — `SizingResult.margin_multiplier`
- `config/settings.py` — `USE_MARGIN`, `MAX_MIS_LEVERAGE`
- `replay/engine.py` — per-symbol multiplier looked up from cache; `use_margin` toggle respected
- `live/runner.py` — cache loaded at startup; per-symbol multiplier passed to sizer

**Where it appears in the UI (Action Replay):**
- **MIS Mult.** column in the universe table — colour-coded (≥4× green / ≥2× yellow / <2× red); hover shows margin % of notional.
- Expanded trade row — "MIS Margin blocked: ₹X at Y× MIS leverage (Z% of notional)".
- Timeline event log — ENTRY events show `[4.5× MIS]` inline.

---

### Cost-aware entry filter (PnL-02)

After sizing, a trade is taken only if its **best-case (target) gross move clears
round-trip transaction costs by ≥ 2×** (`analytics.costs.is_cost_effective`). This is
the live counterpart to PnL being booked **net of the full Indian intraday cost stack**
(STT, brokerage, exchange, SEBI, stamp, GST, slippage) everywhere — win/loss, Kelly,
the win-rate metric, the daily-loss rail and the backtest all use **net** pnl, so a
gross-positive but cost-negative trade is correctly a loss. The same filter runs in the
backtest, so backtested edge is net of costs and of the filter.

### ATR-Based Stop Loss & Target

| Risk Profile | SL multiplier | Target multiplier | Reward:Risk |
|---|---|---|---|
| LOW | 1.5 × ATR | 2.5 × ATR | 1.67:1 |
| MEDIUM | 1.5 × ATR | 2.0 × ATR | 1.33:1 |
| HIGH | 1.2 × ATR | 1.8 × ATR | 1.5:1 |

### Trailing SL (from AI-trader — 96% profitability on these exits)

| Risk Profile | Activation | Lock-in |
|---|---|---|
| LOW | +1.2 × ATR | 0.8 × ATR |
| MEDIUM | +1.0 × ATR | 0.7 × ATR |
| HIGH | +0.8 × ATR | 0.5 × ATR |

---

## Anti-Patterns in Signal Design

| Anti-pattern | Consequence | How to avoid |
|---|---|---|
| Using future data in features | Look-ahead bias → backtest lies | Features computed only on `df.iloc[:-1]` (never include current bar's close at bar open) |
| Overfitting to training period | Model works in backtest, fails live | Walk-forward validation, min 5 folds |
| Adding too many correlated signals | Score double-counts same information | Drop features with Pearson > 0.85 |
| Training ML on < 500 samples | Spurious AUC, no generalization | Minimum 6 months daily data = ~500 samples |
| Signal fires during news blackout | Unexpected losses from event risk | The pre-market screener's catalyst detector suppresses event-risk names (e.g. board-meeting day → −0.3, now actually penalised after SCR-02). An intraday `nse_announcements.is_event_window()` gate is still a Phase-3 TODO (the module does not yet exist). |
| Not normalizing features | XGBoost handles raw features fine, but scaling needed for HMM/RL | Use StandardScaler for HMM and RL state features |
