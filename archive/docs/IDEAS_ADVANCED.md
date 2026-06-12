# IDEAS_ADVANCED — What Else Can Make This Better

> A research-backed ideas bank. Not all of these will be implemented.
> The goal is to have them documented so we don't forget them.
> Sources: Reddit r/algotrading, r/quant, Twitter/X quant community, arXiv papers, production systems.
>
> Status tags:
> - 📋 Planned — already in roadmap
> - 💡 Idea — worth doing, not yet in roadmap
> - 🔬 Research — promising, needs validation
> - ⚡ High impact — do this soon
> - 🧪 Experimental — unproven, explore carefully

---

## Table of Contents

1. [RL Improvements](#1-rl-improvements)
2. [Signal & Alpha Ideas](#2-signal--alpha-ideas)
3. [Risk Management Upgrades](#3-risk-management-upgrades)
4. [Execution Quality](#4-execution-quality)
5. [Data & Alternative Data](#5-data--alternative-data)
6. [Regime & Market Structure](#6-regime--market-structure)
7. [Portfolio-Level Thinking](#7-portfolio-level-thinking)
8. [System Robustness](#8-system-robustness)
9. [Research Papers to Implement](#9-research-papers-to-implement)
10. [Ideas from Reddit / Twitter / Community](#10-ideas-from-reddit--twitter--community)

---

## 1. RL Improvements

### 1.1 RL Exit Agent — already planned 📋
See `SIGNALS.md` Signal 8.

### 1.2 RL Entry Agent — already planned 📋
See `SIGNALS.md` Signal 9.

### 1.3 RL Position Sizing Agent 💡 ⚡

**What it is:** Instead of fixed score-tiered lot sizes (1/2/3 lots), a third RL agent learns the optimal lot size for each entry.

**Why it's powerful:** Fixed sizing treats a 0.68 score in a calm trending market the same as a 0.68 score in a high-VIX choppy market. The RL agent can learn context-aware sizing.

**State space (extends entry agent):**
```python
state = [
    composite_score,
    regime_encoded,
    vix_normalized,
    session_pnl_normalized,       # how today is going so far
    recent_10_trade_win_rate,      # are we in a hot streak or cold streak?
    correlated_open_positions,     # how many similar positions already open?
    atr_percentile,                # current volatility vs historical
    time_of_day_normalized,
]
```

**Actions:** `[0.5 lot, 1 lot, 1.5 lots, 2 lots, 2.5 lots, 3 lots]` (fractional lots by trading equivalent qty)

**Reward:** Risk-adjusted PnL = net_pnl / (lots × ATR) — rewards finding the right size, not just big lots on winners

**Source:** arxiv.org/abs/2406.08013 — "Deep RL with Positional Context for Intraday Trading" (2024)

---

### 1.4 Hierarchical RL (HRL) — Two-Level Decision Making 🔬

**What it is:** Two RL agents at different time scales:
- **High-level agent** (15-min bar): decides overall stance for the next 15 minutes — AGGRESSIVE / NORMAL / DEFENSIVE
- **Low-level agent** (1-min bar): decides specific entries/exits within that stance

**Why:** Matches how professional traders think — first judge the macro session character, then execute within it.

**Source:** Pattern from AI hedge fund architectures. HRL is the state-of-the-art for sequential multi-scale decisions.

**Complexity:** High. Only attempt after both single-level RL agents are stable.

---

### 1.5 Reward Shaping for Better RL Learning 💡

The default reward (PnL at episode end) is sparse — the agent only learns after each trade closes. This is slow.

**Better reward shaping:**
```python
def shaped_reward(unrealized_pnl, step, max_steps, final_pnl=None):
    if final_pnl is not None:
        return final_pnl   # terminal: actual realized PnL
    # Intermediate rewards:
    time_penalty = -0.0005 * (step / max_steps)          # cost of holding time
    drawdown_penalty = min(0, unrealized_pnl) * 0.3      # penalize drawdowns during trade
    profit_lock_bonus = max(0, unrealized_pnl) * 0.05    # small bonus for staying in profit
    return time_penalty + drawdown_penalty + profit_lock_bonus
```

**Source:** Reddit r/algotrading — consensus that sparse reward is the #1 RL training failure for trading agents.

---

### 1.6 Multi-Asset RL Portfolio Agent 🔬

Instead of trading each symbol independently, one RL agent manages a portfolio of 5–10 symbols simultaneously.

**State:** Concatenation of individual symbol states + cross-asset correlations + portfolio-level features (current heat, sector concentration)

**Actions:** Weight vector for each symbol (long/flat/short + size)

**Why it matters:** Avoids the problem of entering 3 correlated Nifty 50 bank stocks simultaneously — current system has no cross-symbol awareness.

**Prerequisite:** Need single-symbol RL agents working well first.

---

## 2. Signal & Alpha Ideas

### 2.1 Opening Range Breakout (ORB) 💡 ⚡

**What it is:** The high/low established in the first 15 or 30 minutes of trading acts as a breakout level for the rest of the session.

**Why it works (Reddit consensus, backtested):**
> "In my experience, levels (daily pivots, weekly monthly HLC, pre-market pivots), patterns and volume are far more important than indicators." — r/algotrading top comment

**Logic:**
```python
# Compute at 9:30 IST (15 min after open):
orb_high = max(high_9:15_to_9:30)
orb_low  = min(low_9:15_to_9:30)

# After 9:30:
if close > orb_high and volume_ratio > 1.3:
    long_signal = True
if close < orb_low and volume_ratio > 1.3:
    short_signal = True
```

**Backtest result on NSE (community reports):** Win rate 55–65% when combined with volume confirmation, Sharpe ~1.1 on NIFTY 50 stocks.

**Add to:** `signals/technical/orb.py`
**Source:** Reddit r/algotrading 1.1k upvote thread on ORB, NSE India quant community on Twitter

---

### 2.2 Previous Day High/Low as Support/Resistance 💡 ⚡

**What it is:** Price levels from the previous day's high, low, and close act as key intraday levels.

**Logic:**
```python
pdh = prev_day_high    # previous day high — strong resistance
pdl = prev_day_low     # previous day low — strong support
pdc = prev_day_close   # previous day close — psychological pivot

# Use as:
# - Score boost if price bounces off PDL (long)
# - Score boost if price breaks PDH on volume (long)
# - Fade signal: short at PDH in ranging regime
```

**Also:** Weekly high/low and monthly high/low (institutional levels) are even more powerful for swing setups.

**Source:** Most-upvoted r/algotrading intraday strategy thread — "levels beat indicators every time"

---

### 2.3 FII/DII Net Flow Signal 💡

**What it is:** FIIs (Foreign Institutional Investors) and DIIs (Domestic Institutional Investors) publish their net buy/sell data on NSE daily. When FII net buy > ₹2,000 Cr, market has strong upward bias.

**Sources (all free):**
- NSE: https://www.nseindia.com/reports/fii-dii (daily publication, post-market)
- MoneyControl: https://www.moneycontrol.com/markets/fii-dii-data/ (same-day updates)
- Upstox FII/DII page: https://upstox.com/fii-dii-data/

**Logic:**
```python
# Computed once per day, before market open:
fii_net = fii_buy_value - fii_sell_value  # in Crores
dii_net = dii_buy_value - dii_sell_value

# Score modifier (not standalone signal):
if fii_net > 2000:
    session_bias = +0.05   # small bullish bias for the day
elif fii_net < -2000:
    session_bias = -0.05
```

**Limitation:** Only published after market close (for previous day). Use as a next-day session-level bias only.
**Enhancement:** Intraday FII F&O participant data (NSE OI participant-wise) is available during market hours.

---

### 2.4 NSE Participant-Wise OI (Intraday FII F&O Flow) 💡 ⚡

**What it is:** NSE publishes participant-wise OI data during market hours showing FII, DII, Client, and Proprietary positions in futures and options.

**URL:** https://www.nseindia.com/market-data/participant-wise-open-interest

**Why it's powerful:** FII futures OI build = institutional directional bet. Much more real-time than EOD FII cash data.

```python
# If FII is building LONG futures OI while retail is SHORT:
# → Institutional vs retail divergence → follow the FII
fii_futures_long_pct_change = ...   # % change in FII long futures OI from morning
if fii_futures_long_pct_change > 5:
    institutional_flow_bias = +0.08  # strong FII buying pressure
```

**Source:** Standard tool used by all Indian quant traders. Heavily discussed in NSE trading Twitter community.

---

### 2.5 Gamma Exposure (GEX) Signal 💡

**What it is:** Dealer gamma positioning at each strike price determines whether the market is in a "volatility suppressing" or "volatility amplifying" regime.

**Formula:**
```
Net GEX = Σ (call_OI - put_OI) × gamma × contract_size × spot_price²
```

- **Positive GEX** (dealers long gamma): dealers SELL rallies and BUY dips to hedge → market stays pinned → mean reversion
- **Negative GEX** (dealers short gamma): dealers BUY rallies and SELL dips to hedge → market trends/whips → momentum

**Practical use:**
```python
if net_gex > 0:
    activate_mean_reversion_signals()   # market is pinned, fade moves
    deactivate_momentum_signals()
else:
    activate_momentum_signals()         # market will trend/whip
    deactivate_mean_reversion_signals()
```

**Source:** SqueezeMetrics (invented GEX), widely discussed on Fintwit/X. Already partially in our system via OpenAlgo's GEX Dashboard (page 8 of dashboard). Add it as a proper regime input.

---

### 2.6 Market Profile / Volume Profile Levels 💡

**What it is:** Point of Control (POC), Value Area High (VAH), Value Area Low (VAL) from the previous session's volume distribution.

**Why:** These are the levels where the most volume traded — strong magnets for price.

```python
# Compute post-market:
poc = price_with_max_volume_yesterday
vah = upper_70pct_volume_boundary
val = lower_70pct_volume_boundary

# Use as dynamic S/R levels during next session
```

**Add to:** `features/indicators.py` as 3 new features: `poc_dist_pct`, `vah_dist_pct`, `val_dist_pct`

---

### 2.7 Insider / Bulk Deal / Block Deal Signal 💡

**What it is:** NSE publishes bulk deals (>0.5% of shares) and block deals daily. Promoter/insider buying is a strong bullish signal.

**Source:** https://www.nseindia.com/market-data/bulk-deal-archives

**Logic:**
```python
# Check bulk deals post-market for next day bias:
if bulk_deal.side == "BUY" and bulk_deal.entity_type in ["PROMOTER", "FII"]:
    add_bullish_bias(symbol, days=3, strength=0.1)
```

---

### 2.8 Tick Toxicity / VPIN Signal 🔬

**What it is:** Volume-Synchronized Probability of Informed Trading (VPIN). Measures the probability that a trade is from an informed (institutional) player vs noise trader.

**Why:** High VPIN → informed trading → price will move significantly → good for momentum. Low VPIN → noise → good for mean reversion.

```python
# Simplified VPIN proxy (no need for full Easley et al. formula):
buy_vol  = sum(volume where price_change >= 0 per last N ticks)
sell_vol = sum(volume where price_change < 0 per last N ticks)
vpin_proxy = abs(buy_vol - sell_vol) / (buy_vol + sell_vol)  # 0=balanced, 1=one-sided
```

**Source:** Easley, López de Prado & O'Hara 2012. "The Volume Clock: Insights into the High Frequency Paradigm."

---

### 2.9 Pre-Market / After-Hours Overnight Gap Strategy 💡

**What it is:** How the market opens relative to previous day close and the previous day's high/low is predictive of the first 30 minutes.

```python
gap_pct = (today_open - yesterday_close) / yesterday_close × 100

# Gap-and-go (trending): large gap up + opens above PDH → strong momentum
# Gap-fill (reverting): gap up + opens inside PDH/PDL range → likely fills gap
```

**Works well with ORB:** Combine gap analysis + ORB for first-hour strategy.

---

### 2.10 Earnings Drift + PEAD Cross-Sectional Strategy 🔬

Fully described in `SIGNALS.md` under Phase 3. But worth noting that cross-sectional PEAD (ranking stocks by earnings surprise and trading the top/bottom quintile) is a documented alpha source in Indian markets as well.

**Source:** Bernard & Thomas (1989) + 2024 replication on NSE by QuantInsti research.

---

## 3. Risk Management Upgrades

### 3.1 Adaptive Position Sizing (Kelly Criterion) 💡 ⚡

**What it is:** Kelly Criterion adjusts position size based on edge (win rate × avg win / avg loss ratio).

**Formula:**
```python
def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    b = avg_win / abs(avg_loss)   # reward:risk ratio
    f = (b * win_rate - (1 - win_rate)) / b
    return max(0, f)              # never negative (never short portfolio)

# Apply fractional Kelly (safer):
position_fraction = kelly_fraction(...) * 0.25   # quarter-Kelly is conservative
```

**Use it to:** Scale lot size up during hot streaks, reduce during cold streaks — mathematically optimal.

**Important caveat:** Kelly requires stable win rate estimates. Use rolling 20-trade estimates. With <20 trades, use fixed sizing.

**Source:** Kelly (1956), widely used in professional systematic trading.

---

### 3.2 Portfolio Heat Monitor 💡 ⚡

**What it is:** "Portfolio heat" = total current risk exposure as % of capital. Prevents over-concentration.

```python
def portfolio_heat(open_positions: list) -> float:
    total_risk = sum(
        abs(position.entry_price - position.sl_price) * position.qty
        for position in open_positions
    )
    return total_risk / total_capital * 100  # as % of capital

# Rule: Never let portfolio heat exceed 3% (LOW), 5% (MEDIUM), 7% (HIGH)
# Before every new entry: check if adding this position would breach heat limit
```

**Why it's better than max_concurrent_positions:** A max positions count doesn't account for SL width — you could have 3 positions with wide SLs and lose more than 5 with tight SLs.

---

### 3.3 Correlation-Based Position Limits 💡 ⚡

**What it is:** Limit total exposure to correlated stocks.

**Problem:** HDFCBANK, ICICIBANK, AXISBANK, SBIN are all banking stocks and move together (correlation 0.7–0.9). Entering all 4 simultaneously = 4× the effective risk of one position.

```python
SECTOR_MAP = {
    "FINANCIALS": ["HDFCBANK", "ICICIBANK", "AXISBANK", "SBIN", "BAJFINANCE"],
    "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
    "OIL_GAS": ["RELIANCE", "ONGC", "BPCL"],
}

MAX_SECTOR_POSITIONS = {
    "FINANCIALS": 2,   # max 2 bank stocks simultaneously
    "IT": 2,
}

# Before entry: check sector count for this symbol's sector
```

**Source:** Standard institutional risk practice, extensively discussed on r/quant.

---

### 3.4 Drawdown Recovery Mode 💡

**What it is:** When the system hits, say, 60% of daily loss limit, automatically switch to a conservative mode.

```python
DRAWDOWN_MODES = {
    "NORMAL": {
        "score_threshold": 0.65,
        "lot_multiplier": 1.0,
        "max_new_entries": 999,
    },
    "CAUTION": {  # triggered at 60% of daily loss limit
        "score_threshold": 0.72,   # higher bar to enter
        "lot_multiplier": 0.5,     # halve the lot size
        "max_new_entries": 3,
    },
    "DEFENSIVE": {  # triggered at 80% of daily loss limit
        "score_threshold": 0.80,
        "lot_multiplier": 0.0,     # no new entries
        "max_new_entries": 0,
    },
}
```

**Why:** After a string of losses, the natural urge is to "trade more to recover." This kills accounts. The system should do the opposite — trade less and at higher conviction only.

**Source:** Every professional PM rule book. r/algotrading consensus: "after a 2% drawdown day, take the afternoon off."

---

### 3.5 Time-Based Stop (Max Time in Trade) 💡

**What it is:** If a trade hasn't hit target OR SL within X minutes, exit regardless.

```python
MAX_TRADE_DURATION_MINUTES = {
    "TRENDING_UP": 90,
    "TRENDING_DOWN": 90,
    "MEAN_REVERTING": 45,   # mean reversion must resolve quickly
    "CHOPPY": 30,           # get out fast if choppy
}
```

**Why:** A trade that does nothing is still tying up margin and missing other opportunities. Exit reason `TIMEOUT` is a valid exit.

---

### 3.6 Equity Curve Trading (Meta-Strategy) 🔬

**What it is:** Treat the system's own equity curve as a signal. When the rolling Sharpe of the last 20 trades is falling, reduce risk. When it's rising, increase.

```python
rolling_sharpe = compute_rolling_sharpe(trade_log, window=20)
if rolling_sharpe < 0.5:
    lot_multiplier = 0.5   # system in drawdown, reduce size
elif rolling_sharpe > 1.5:
    lot_multiplier = 1.2   # system on a hot streak, slightly increase
```

**Source:** Widely discussed in professional systematic trading. The concept is that your system has regimes too — not just the market.

---

## 4. Execution Quality

### 4.1 Smart Order Routing — Limit vs Market 💡 ⚡

**Current plan:** Market orders always.

**Problem:** For illiquid stocks or options, market orders = terrible fills. Slippage of 0.1–0.3% per trade can wipe out edge entirely.

**Better:**
```python
def choose_order_type(symbol: str, urgency: str) -> str:
    spread_bps = get_current_spread_bps(symbol)
    if spread_bps > 10:         # spread > 10 bps = illiquid
        if urgency == "HIGH":   # SL exit → must use market
            return "MARKET"
        return "LIMIT"          # entry → use limit at mid-price
    return "MARKET"             # liquid → market is fine
```

**Limit entry with IOC (Immediate or Cancel):** Place limit at mid-price, if not filled in 2 bars → cancel and re-evaluate signal. Prevents chasing.

---

### 4.2 Slippage Model in Backtest 💡 ⚡

**Current plan:** Fixed 0.05% slippage.

**Better — volume-adjusted slippage model:**
```python
def estimate_slippage(symbol: str, qty: int, side: str) -> float:
    avg_daily_volume = get_adv(symbol)       # average daily volume
    participation_rate = qty / avg_daily_volume
    # Amihud illiquidity model:
    slippage = 0.01 + 0.05 * (participation_rate ** 0.5)
    # Small positions in liquid stocks: ~0.02%
    # Large positions in illiquid stocks: up to 0.15%
    return slippage
```

**Why:** Fixed slippage makes backtests unrealistic for small-cap or high-lot trades.

**Source:** Amihud (2002) illiquidity model, standard in institutional backtesting.

---

### 4.3 Execution Time Tracking 💡

Log: intended entry price (signal computed at T) vs actual fill price (T + latency). Track slippage per trade.

```python
# In trade_log table, add:
intended_entry_price  DECIMAL(12,2)  -- price at signal time
actual_entry_price    DECIMAL(12,2)  -- actual fill
entry_slippage_bps    DECIMAL(8,2)   -- (actual - intended) / intended × 10000
entry_latency_ms      INTEGER        -- ms from signal to fill confirmation
```

**Dashboard:** Show average execution slippage per day in `/trades` analytics. If slippage > 5 bps consistently, switch to limit orders.

---

## 5. Data & Alternative Data

### 5.1 Satellite / Alternative Data (Longer Term) 🧪

- **Satellite imagery:** Parking lot fill rates, factory smoke stacks, oil tanker locations (companies like Orbital Insight)
- **Credit card transaction data:** Consumer spending trends by sector
- **App download data:** Mobile app download trends as proxy for consumer demand

**Reality check:** These are expensive (₹10–50 Lakh/year enterprise licenses) and primarily useful for swing trading (days to weeks), not intraday. Not worth pursuing until Phase 4 and significant capital.

---

### 5.2 Earnings Call Transcript Sentiment 🔬

**What it is:** FinBERT or a fine-tuned model on NSE earnings call PDFs. Management tone → future guidance quality.

**Why useful:** Companies with positive management tone in Q4 call outperform over the next quarter.

**Source:** Loughran & McDonald (2011) financial word list → extended to NSE India context.

**Implementation:**
```python
# Download NSE earnings call transcripts from:
# https://www.bseindia.com/corporates/ann.html
# Run FinBERT on transcript text → positive/negative/neutral probabilities
# Store in sentiment_cache as a longer-lived signal (30-day horizon vs 30-min horizon)
```

---

### 5.3 Social Media Retail Sentiment (Cautious Use) 🧪

**What it is:** Retail trader sentiment from:
- Twitter/X: #NSE, #Nifty, cashtag mentions of stocks
- Reddit r/IndiaInvestments, r/DalalStreet
- StockTwits India

**Why cautious:** Retail sentiment is mostly a **contrarian** indicator for intraday (when retail is euphoric → fade). But identifying the signal vs noise ratio requires significant filtering.

**Tools:**
- Twitter v2 API (free tier: 500k tweets/month)
- PRAW (Python Reddit API)

**Source:** Multiple academic papers show retail social sentiment has 15–30 minute predictive power for stocks mentioned heavily. Effect is strongest for mid-cap stocks.

---

### 5.4 Economic Calendar Integration 💡

**What it is:** Know in advance when macro events will cause volatility:
- RBI monetary policy dates
- US Fed meeting dates
- India CPI/WPI data release
- GDP data
- Budget day (Feb 1)
- NSE F&O expiry (last Thursday of month)

**Implementation:**
```python
# Hardcode RBI dates for year, auto-fetch US Fed dates from FRED API
# Rules:
# - Suppress all signals 30 min before and 60 min after major macro event
# - F&O expiry day: reduce lot sizes by 50%, many whipsaws
# - Budget day: do NOT trade (extreme volatility, unpredictable)
```

**Source:** r/algotrading thread: "What I wish I knew — always blackout RBI policy days."

---

### 5.5 Corporate-Action Adjustment for Daily Factors 💡

**What it is:** Upstox historical candles are **unadjusted** — splits/bonuses show up as large single-day gaps (e.g. a 1:5 split = a fake -80% drop). This corrupts multi-day daily factors used by the screener (20-day return, momentum rank, ATR%, turnover medians).

**Why parked (for now):** Irrelevant to the intraday 5-min replay/live loop *within a day*. Only matters for the *daily ranking* and any future weekly/monthly trend layers. Decided to defer to reduce complexity while building the wider universe + daily backfill first.

**When to revisit:** Once the Nifty-500 universe + daily backfill are live and we want clean cross-sectional momentum ranking, or before backtesting selection quality on long history.

**Sourcing options (free):**
- **Upstox Fundamentals API** (`GET /v2/instruments/fundamentals/{isin}/corporate-actions`) — dividends, bonus, stock splits, rights by ISIN. Same provider as candles; no new dependency. Confirmed in Upstox API docs. Best option when un-parking.
- `nsepython` / `jugaad-data` — NSE corporate-action calendar as alternative.
- NSE archive CSVs — public but bot-blocked, messier to scrape.
- Heuristic auto-detect — flag any single-day daily gap > ~25% with no matching index move as a probable split/bonus (zero-dependency sanity check).

**Implementation sketch:**
```python
# New table: corporate_actions(symbol, ex_date, action_type, ratio)
# At factor-compute time, build adj_close by chaining adjustment factors
# backward from each ex_date, then compute returns/ATR on adj_close.
```

---

## 6. Regime & Market Structure

### 6.1 Multi-Timeframe Regime Consensus 💡 ⚡

**Current plan:** Regime detected on primary timeframe (5-min).

**Better:** Only trade when multiple timeframes agree on regime.

```python
regime_1min  = detect_regime(df_1min)
regime_5min  = detect_regime(df_5min)
regime_15min = detect_regime(df_15min)

# Only enter if 2 of 3 agree:
if [regime_1min, regime_5min, regime_15min].count(regime_5min) >= 2:
    use_regime = regime_5min
else:
    use_regime = "CHOPPY"  # disagreement = treat as choppy, reduce risk
```

---

### 6.2 Market Breadth as Regime Context 💡

**What it is:** Is the move in your target stock supported by the broader market?

```python
# From nsepython or Upstox:
advances = nse_market_breadth.advances       # stocks up > 0.5% today
declines = nse_market_breadth.declines

advance_decline_ratio = advances / (advances + declines)

# Use as session-level regime modifier:
if advance_decline_ratio > 0.65:
    session_breadth_bias = +0.05   # broad market rising → support momentum
elif advance_decline_ratio < 0.35:
    session_breadth_bias = -0.05   # broad market falling → support shorts
```

---

### 6.3 VIX Term Structure Signal 🔬

**What it is:** The shape of the VIX term structure (India VIX vs realized vol) tells you about fear premium.

```python
india_vix = get_india_vix()               # from NSE
nifty_realized_vol = compute_realized_vol(nifty_returns, window=10)

vol_risk_premium = india_vix - nifty_realized_vol

# High VRP (VIX >> realized): fear premium elevated → short vol strategies work
# Low VRP (VIX ≈ realized): fair pricing → trend strategies work
```

**Source:** VIX term structure as regime indicator — used by vol traders on Twitter/X extensively.

---

### 6.4 Expiry Week Effect 💡

**What it is:** NSE F&O weekly expiry (every Thursday) creates predictable gamma squeeze dynamics.

**Observations (NSE-specific, from quant community):**
- Monday–Tuesday before expiry: lower IV, good for mean reversion
- Wednesday afternoon + Thursday morning: gamma squeeze potential, higher directional moves
- Last hour of expiry Thursday: extreme volatility, avoid entirely

**Implementation:**
```python
def is_expiry_week() -> bool:
    return (next_thursday - today).days <= 3

def get_expiry_day_adjustment() -> dict:
    if today.weekday() == 3 and is_expiry_thursday():
        return {"lot_multiplier": 0.5, "score_threshold_boost": +0.05}
    if is_expiry_week() and today.weekday() in [1, 2]:  # Tue/Wed
        return {"momentum_boost": +0.03}   # momentum tends to persist pre-expiry
```

---

## 7. Portfolio-Level Thinking

### 7.1 Strategy Rotation Based on Market Regime 💡 ⚡

**Current plan:** All signals run simultaneously, weights change by regime.

**Stronger approach:** Completely switch signal sets by macro regime.

```python
STRATEGY_BOOKS = {
    "BULL_TRENDING": {
        "primary": ["vwap_breakout", "rsi_momentum", "orb"],
        "secondary": ["macro_xgboost"],
        "disabled": ["mean_reversion"],
    },
    "BEAR_TRENDING": {
        "primary": ["vwap_breakout", "rsi_momentum"],  # short side
        "disabled": ["mean_reversion", "orb"],
    },
    "HIGH_VIX_CHOPPY": {
        "primary": ["mean_reversion"],
        "secondary": ["options_flow"],
        "disabled": ["vwap_breakout", "rsi_momentum"],
    },
    "LOW_VIX_RANGING": {
        "primary": ["mean_reversion", "options_flow"],
        "disabled": ["vwap_breakout"],
    },
}
```

**Source:** Professional PM practice — "different books for different tapes."

---

### 7.2 Cross-Sectional Momentum (Ranking Approach) 🔬

**What it is:** Rank all Nifty 50 stocks by their 20-day return each morning. Go long the top 5, short the bottom 5.

**Different from time-series momentum:** This is relative — you're buying the strongest stocks and shorting the weakest, regardless of overall market direction.

**NSE-specific challenge:** Most retail F&O margin requirements make shorting equities expensive. Easier to implement in index futures or as a long-only tilt.

**Source:** Jegadeesh & Titman (1993) — the original momentum paper. Replicated on Indian data by multiple QuantInsti papers.

---

### 7.3 Pairs Trading / Statistical Arbitrage 🔬

**What it is:** Find pairs of historically co-integrated stocks (e.g., HDFCBANK/ICICIBANK, TCS/INFY). When the spread deviates, go long the underperformer and short the outperformer.

```python
# Cointegration test (Engle-Granger):
from statsmodels.tsa.stattools import coint
score, pvalue, _ = coint(price_series_A, price_series_B)
if pvalue < 0.05:  # cointegrated → pairs trade candidate

# Z-score of spread:
spread = price_A - hedge_ratio * price_B
zscore = (spread - spread.mean()) / spread.std()
if zscore > 2.0: short_A_long_B()
if zscore < -2.0: long_A_short_B()
```

**NSE pairs with strong historical cointegration:**
- HDFCBANK / ICICIBANK
- TCS / INFOSYS
- HINDUNILVR / DABUR
- RELIANCE / ONGC

**Source:** Standard textbook stat arb strategy. Active on r/algotrading regularly.

---

### 7.4 Sector Rotation Signal 💡

**What it is:** Track which sectors are leading vs lagging the broader NIFTY today. Rotate signal weights to favour leading sector stocks.

```python
# Compute at 10:00 IST (after opening volatility):
sector_returns_today = {
    "FINANCIALS": compute_sector_return(bank_stocks),
    "IT": compute_sector_return(it_stocks),
    "OIL_GAS": compute_sector_return(oil_stocks),
}

# Boost signal weights for stocks in leading sectors:
if sector_returns_today["IT"] > nifty_return + 0.3%:
    boost_weight_for_sector("IT", +0.1)
```

---

## 8. System Robustness

### 8.1 Online Learning — Continuous Model Updates 💡

**Current plan:** Retrain models nightly in batch.

**Better:** Incremental/online learning that updates after EVERY trade without full retraining.

```python
# XGBoost supports incremental learning:
model.fit(new_X, new_y,
          xgb_model=model,      # pass existing model → incremental update
          eval_set=[(val_X, val_y)])

# Run after every trade close (not just nightly):
# - New sample = the features at entry + label (WIN/LOSS)
# - 5-minute update cycle
```

**Trade-off:** Faster adaptation vs stability. Add a "staleness check" — only update if new sample is confident (model uncertainty is low).

---

### 8.2 Feature Drift Detection 💡 ⚡

**What it is:** Statistical test to detect when the live feature distribution has shifted significantly from the training distribution. When drift is detected, model confidence is reduced.

```python
from scipy.stats import ks_2samp

def detect_feature_drift(train_features: pd.DataFrame,
                          live_features: pd.DataFrame) -> dict:
    drift_report = {}
    for col in train_features.columns:
        stat, pvalue = ks_2samp(train_features[col], live_features[col])
        drift_report[col] = {"drifted": pvalue < 0.05, "pvalue": pvalue}
    pct_drifted = sum(v["drifted"] for v in drift_report.values()) / len(drift_report)
    return {"pct_drifted": pct_drifted, "features": drift_report}

# If pct_drifted > 30%: flag model as "DRIFT DETECTED", log warning, trigger retrain
```

**Dashboard:** Show feature drift % per model in `/models` page. Red badge if > 20%.

**Source:** Standard MLOps practice. Critical for any live ML system.

---

### 8.3 Shadow Mode — New Signals on Paper Before Live 💡 ⚡

**What it is:** When you add a new signal (say, FinBERT in Phase 3), run it in "shadow mode" for 2 weeks — it generates scores and logs what trades IT would have made, but does NOT actually affect the live ensemble.

```python
class BaseSignal:
    shadow_mode: bool = False   # if True, compute but don't contribute to ensemble

# After 2-week shadow period, review shadow PnL:
# If shadow_pnl > 0 and Sharpe > 0.5 → promote to live
# Otherwise → extend shadow period or discard
```

**Why:** Prevents untested signals from corrupting a live profitable system.

---

### 8.4 A/B Testing Framework for Signals 🔬

**What it is:** Instead of switching the full system to a new signal, run two versions simultaneously — A (current) and B (with new signal) — splitting trades between them.

**Implementation:** On every signal fire, coin flip → 50% go to system A, 50% to system B. After 100 trades per group → statistical test for difference.

**Challenge:** Requires double the trade volume to get statistical significance. Practical only if trading 15+ trades/day.

---

### 8.5 Monte Carlo Simulation for Risk 💡

**What it is:** Given your historical win rate and average trade P&L, simulate 10,000 possible 30-day outcomes to understand real downside risk.

```python
def monte_carlo_risk(win_rate, avg_win, avg_loss, trades_per_day, days=30, n_sims=10000):
    results = []
    for _ in range(n_sims):
        pnl = 0
        for day in range(days):
            for _ in range(trades_per_day):
                pnl += avg_win if random() < win_rate else avg_loss
        results.append(pnl)
    var_95 = np.percentile(results, 5)   # 5th percentile = 95% VaR
    max_drawdown_expected = min(results)
    return var_95, max_drawdown_expected
```

**Use it:** Before going live, run this to understand "in the worst 5% of scenarios, how much can I lose in a month?" This tells you what capital buffer you need.

---

## 9. Research Papers to Implement

| Paper | What It Suggests | Phase | Difficulty | Status |
|---|---|---|---|---|
| **Jegadeesh & Titman (1993)** — Momentum | Buy top 10th decile, short bottom 10th decile on 12-1 month return | 2 | Low | 🔲 |
| **Daniel & Moskowitz (2016)** — Momentum Crashes | Reduce momentum weight dramatically when market volatility is high (post-crash) | 2 | Medium | 🔲 |
| **Cont, Kukanov & Stoikov (2014)** — Order Flow Imbalance | Order imbalance in Level 2 data predicts short-term price moves with IC ~0.3 | 2 | Medium | 🔲 |
| **Easley et al. (2012)** — VPIN | Probability of informed trading → identifies stocks about to make large moves | 2 | High | 🔲 |
| **Bernard & Thomas (1989)** — PEAD | Post-earnings drift persists for 60 trading days — buy surprise ≥ 5% | 3 | Low | 🔲 |
| **Amihud (2002)** — Illiquidity | Better slippage model: slippage = f(trade_size / daily_volume) | 1 | Low | 🔲 |
| **Harvey et al. (2016)** — Factor Zoo Warning | Most discovered "factors" are just multiple testing artifacts — use t-stat ≥ 3 for any new factor | All | Conceptual | 🔲 |
| **Loughran & McDonald (2011)** — Financial Sentiment | Custom word list for financial text sentiment (more accurate than FinBERT for specific phrases) | 3 | Medium | 🔲 |
| **Arxiv 2406.08013 (2024)** — Deep RL with Positional Context | RL agent with explicit position context outperforms standard RL for intraday | 2 | High | 🔲 |
| **Arxiv 2411.07585 (2024)** — RL Framework for Quant Trading | Comparison of PPO/A2C/DQN for trading — PPO wins for continuous action spaces | 2 | High | 🔲 |
| **Arxiv 2512.02227 (2024)** — Orchestration Framework for Financial Agents | Multi-agent architecture for trading with plan-graph message schema | 4 | Very High | 🔲 |
| **Lopez de Prado (2018)** — Advances in Financial ML | Triple barrier labeling, fractionally differentiated features, combinatorial purged CV | 2 | High | 🔲 |

---

## 10. Ideas from Reddit / Twitter / Community

### From r/algotrading (high-upvote posts, June 2025)

**"Levels beat indicators every time"** (1.2k upvotes)
> "In my experience, levels (daily pivots, weekly monthly HLC, pre-market pivots), patterns and volume are far more important than indicators. Indicators can add value but don't make a strategy on their own."

→ **Add to our system:** Previous day high/low, weekly high/low, ORB levels as features (section 2.1, 2.2 above)

---

**"How to de-overfit a bursty intraday strategy"** (active June 2025 thread)
> "Walk-forward works but you also need out-of-sample regime testing. Run your backtest on 2008–2012 (crisis + recovery) and 2020 (COVID crash) data separately. If it only works 2021–2024 (pure bull market), you don't have alpha."

→ **Add to our backtest:** Test on NSE data across different regimes: 2020 COVID crash, 2022 Fed rate hike selloff, 2024 bull market. A strategy that works across all three is robust.

---

**"My reality of trading" post** (827 upvotes, important read)
> Key point: "The most important thing I learned is that your best trades come from moments of extreme market fear or greed — not from normal days. Build your system to recognize extremes."

→ **Add:** VIX spike detector (`india_vix > 20 → high_fear_regime`). Different signal weights in fear vs greed.

---

**Thread on Opening Range Backtest** (106 upvotes, verified ORB works on NSE)
> "ORB on 15-min timeframe with volume confirmation on NSE F&O stocks: 58% win rate, 1.8 reward:risk ratio over 2 years of backtesting. Skips the opening 15-minute noise."

→ Confirms: add ORB signal to Phase 1 or early Phase 2.

---

**"Salvaging algos" thread** (June 2025)
> "If your algo is 55% win rate in trending markets but 40% in ranging, you don't need a better algorithm — you need a better regime filter."

→ Confirms the importance of our regime detection. The regime filter IS the edge for many strategies.

---

### From Twitter/X Quant India Community

**@RajeshIndiaTrades type accounts (NSE quant twitter):**
> "FII net F&O participant OI data is the single most underused publicly available dataset for Indian algo traders. FIIs are almost always right directionally in index futures."

→ Confirms our section 2.4 (NSE Participant OI signal).

---

**General Fintwit consensus on GEX:**
> "When Nifty spot is near a high positive GEX strike, it acts like a magnet — price keeps gravitating toward it. These are your 'sticky levels' for the week."

→ Add GEX-based sticky levels to features. Our dashboard already has GEX from OpenAlgo — feed it into the signal layer.

---

**On LLMs for trading (skeptical Fintwit view):**
> "LLMs are amazing for generating trade ideas and analyzing news. They are terrible at predicting prices directly. Use them for context and reasoning, not for price targets."

→ Confirms our Phase 4 design: LLMs are analyst agents providing context, not price predictors.

---

**On RL for trading (balanced view from r/quant):**
> "RL works for trading but requires WAY more data than people think. 6 months of intraday data = maybe 5,000 bars = not enough. You need tick-level replay simulation or at least 2 years of data before RL generalizes."

→ **Important caution for our RL agents:** Start RL training only after 2+ years of historical data is available (or use simulated episodes via backtest replay). Don't activate RL in live until it has seen ≥ 500 training episodes.

---

## Priority Summary (What to Add First)

The following ideas are high-impact and relatively low-complexity. Consider adding them to the Phase 1–2 roadmap:

| Priority | Idea | Effort | Expected Impact |
|---|---|---|---|
| ⚡⚡⚡ | Opening Range Breakout signal | Low (1 day) | +5–8% win rate |
| ⚡⚡⚡ | Previous Day High/Low as features | Very low (2 hrs) | Better S/R awareness |
| ⚡⚡⚡ | Portfolio heat monitor | Low (1 day) | Critical risk control |
| ⚡⚡⚡ | Sector correlation limit | Low (half day) | Prevents over-concentration |
| ⚡⚡ | FII/DII net flow session bias | Low (1 day) | Better daily directional bias |
| ⚡⚡ | NSE participant OI signal | Medium (2 days) | Strong institutional flow signal |
| ⚡⚡ | Drawdown recovery mode | Low (half day) | Protects capital in bad streaks |
| ⚡⚡ | Multi-timeframe regime consensus | Low (1 day) | Fewer false regime classifications |
| ⚡⚡ | Feature drift detection | Medium (2 days) | Catches model degradation early |
| ⚡⚡ | Time-based stop (timeout) | Very low (1 hr) | Frees capital from stagnant trades |
| ⚡ | Kelly position sizing (rolling) | Medium (2 days) | Mathematically optimal sizing |
| ⚡ | RL position sizing agent | High (1 week) | Context-aware lot sizing |
| ⚡ | Shadow mode for new signals | Low (1 day) | Safe testing of new signals |
| 🔬 | Pairs trading / stat arb | High (2 weeks) | Market-neutral alpha |
| 🔬 | VIX term structure signal | Medium (3 days) | Better vol regime detection |
| 🔬 | Lopez de Prado triple-barrier labels | High (1 week) | Better ML training labels |

---

## 11. Engineering, Correctness & Execution Robustness (added from June 2026 audit)

> The sections above are alpha and risk *ideas*. This section is about making the *machine* trustworthy. These came out of the full code read-through. Bug-level detail (with `file:line`) lives in `KNOWN_ISSUES.md`; here we capture the forward-looking capabilities that would make the system materially better and safer. Several of these are higher-priority than any new alpha signal — a wrong number from a leaky backtest is worse than no number.

### 11.1 Broker-Side Bracket / OCO Orders ⚡⚡⚡

**What it is:** Instead of polling SL/target in our own process every second, place the stop-loss and target as a native **bracket order** (or OCO — one-cancels-other) at the exchange when entering.

**Why it's high impact:** Today SL/target only exist in `live/runner.py`'s monitor thread. If the runner crashes, the websocket dies, or the LTP feed goes stale, the position has **no protection at all** (this is the root of several P0s — see LIVE-01/02/04, FEED-02 in `KNOWN_ISSUES.md`). A broker-side bracket survives all of those failures because the exchange holds the stop.

**Implementation:** OpenAlgo / Upstox support cover and bracket orders. Place entry + SL + target as one bracket; keep the in-process monitor only for *trailing* logic and for tightening, not as the sole stop. Reconcile bracket legs into our book.

**Source:** Standard practice for any retail algo that can't guarantee 100% process uptime.

---

### 11.2 Probability Calibration of Model Outputs 💡 ⚡

**What it is:** XGBoost `predict_proba` is not a calibrated probability. Using a raw `0.45`/`0.55` gate threshold on an uncalibrated model means the gate is arbitrary.

```python
from sklearn.calibration import CalibratedClassifierCV
# Fit isotonic/Platt calibration on a held-out (forward) slice, never the train set:
calibrated = CalibratedClassifierCV(base_model, method="isotonic", cv="prefit")
calibrated.fit(X_holdout, y_holdout)
# Now predict_proba ≈ true P(win), so 0.55 actually means "55% of these win"
```

**Why:** Makes every probability-based gate (`micro < 0.45`, `outcome < 0.55`, macro score mapping) mean what it says. Also a prerequisite for Kelly sizing to be correct — Kelly needs a *true* win probability.

**Source:** Standard MLOps; Niculescu-Mizil & Caruana (2005) on calibration.

---

### 11.3 Volatility Targeting for Position Size 💡 ⚡

**What it is:** Size each position so that its *expected risk contribution* is constant, by scaling to a target portfolio volatility — distinct from (and complementary to) Kelly.

```python
target_daily_vol = 0.01            # want ~1% daily portfolio vol
position_vol = atr_pct * sqrt(holding_bars)   # estimated trade vol
size_multiplier = target_daily_vol / position_vol
```

**Why it's different from Kelly:** Kelly scales on edge (win rate × payoff); vol targeting scales on *risk* so a calm-tape trade and a high-VIX trade carry the same portfolio risk. The two stack: Kelly picks the edge multiplier, vol targeting normalizes risk. Fixes the current sizer's blindness to per-trade volatility (it sizes off score tier and ATR-stop only).

**Source:** Standard in CTAs / managed futures; Moskowitz, Ooi & Pedersen (2012) "Time Series Momentum" uses vol scaling throughout.

---

### 11.4 Backtest ↔ Live Parity Monitoring 💡 ⚡

**What it is:** For every live trade, log what the backtest engine *would* have done on the same bar (same features, same signal). Track the divergence.

```python
# Per trade, store: backtest_intended_score, live_score, backtest_fill, live_fill
# Daily: alert if |live_pnl - shadow_backtest_pnl| drifts beyond a band
```

**Why:** This is the single best detector of (a) a leaky/optimistic backtest, (b) execution slippage eating the edge, and (c) a live bug. If live consistently underperforms the backtest replay, the backtest is lying or execution is broken — either way you find out in days, not after a drawdown.

**Source:** Every serious systematic desk runs a "sim vs real" reconciliation. Related to but stronger than the equity-curve meta-strategy (§3.6).

---

### 11.5 Automated Leakage / Causality Test Harness 💡 ⚡

**What it is:** A test that *proves* no feature uses future data, run in CI.

```python
def assert_causal(compute_features, df):
    # Compute features on the full series, and on a truncated series.
    full = compute_features(df)
    for cut in [len(df)//2, 3*len(df)//4]:
        trunc = compute_features(df.iloc[:cut])
        # Every feature value at bar t must be identical whether or not
        # bars after t exist. If not, the feature peeks into the future.
        pd.testing.assert_frame_equal(full.iloc[:cut].tail(20), trunc.tail(20))
```

**Why:** The audit found `bfill()` in the ML feature path and features computed on train+test together (ML-03, BT-01). A leakage test would have caught both. Run it on `compute_all_features` and on each model's `prepare_features`.

**Source:** López de Prado (2018), *Advances in Financial Machine Learning* — leakage is the #1 reason backtests don't reproduce live.

---

### 11.6 Champion / Challenger Model Promotion 💡 ⚡

**What it is:** Never overwrite the live ("champion") model in place. Train a "challenger," evaluate it on a *forward, never-seen* slice, and promote only if it beats the champion by a margin.

```python
champion_auc  = evaluate(champion,  X_forward_oos, y_forward_oos)
challenger_auc = evaluate(challenger, X_forward_oos, y_forward_oos)
if challenger_auc > champion_auc + 0.01:
    atomic_swap(challenger)        # promote
    log("PROMOTED", champion_auc, challenger_auc)
else:
    log("KEPT_CHAMPION", champion_auc, challenger_auc)   # discard challenger
```

**Why:** `retrain_daily.py` currently overwrites the live model regardless of whether it got worse (RETRAIN-01), and "evaluates" on in-sample rows (RETRAIN-02). A degraded model silently goes to production. Champion/challenger + held-out gate + atomic swap + auto-rollback makes nightly retraining safe instead of dangerous.

**Source:** Standard ML deployment practice (A/B promotion, shadow deploys).

---

### 11.7 Meta-Labeling (Formalize the Outcome Gate) 🔬

**What it is:** The strategy-outcome models (`signals/ml/strategy_outcomes.py`) are already, informally, *meta-labeling* — a secondary model that decides whether to act on the primary signal. Frame them explicitly as López de Prado meta-labels: the primary model sets *direction*, the meta-model sets *size/confidence* (including "size 0" = skip).

**Why:** Meta-labeling is a proven way to raise precision (cut false positives) without touching recall of the primary signal. Doing it deliberately — with proper purged CV and the bet-sizing output feeding the position sizer — is stronger than the current bolt-on `> 0.55` gate.

**Source:** López de Prado (2018), Ch. 3 (meta-labeling).

---

### 11.8 Correlation / Sector Exposure Guard (close the documented gap) ⚡⚡

**What it is:** `ARCHITECTURE.md` lists `risk/correlation_guard.py` and §3.3 above describes sector position limits — but the file does not exist and the runner has **no cross-symbol awareness**. It can enter HDFCBANK, ICICIBANK, AXISBANK and SBIN simultaneously = 4× one effective bet.

**Why it's here:** Flagging that this is a *documented-but-unbuilt* risk control, not just an idea. Build `risk/correlation_guard.py` per §3.3 and wire it into the entry path alongside the circuit breaker.

---

### Priority within this section

| Priority | Item | Why first |
|---|---|---|
| ⚡⚡⚡ | 11.1 Broker-side bracket/OCO | Removes the "unprotected position on crash" class of P0 bugs |
| ⚡⚡⚡ | 11.5 Leakage test harness | Cheap; tells you whether any backtest/AUC is even real |
| ⚡⚡ | 11.6 Champion/challenger promotion | Stops nightly retrain from shipping worse models |
| ⚡⚡ | 11.4 Backtest↔live parity | Earliest warning that the edge isn't surviving execution |
| ⚡⚡ | 11.8 Correlation guard | Documented risk control that's simply missing |
| ⚡ | 11.2 Calibration · 11.3 Vol targeting · 11.7 Meta-labeling | Make sizing/gates principled once the above are solid |

---

## 12. Newly Discovered API Capabilities (from Jun 2026 Upstox API Audit)

> **Status: BACKBURNER** — these were discovered during the full Upstox API documentation review.
> They improve accuracy by incremental amounts (think: 5% win rate → 6%), not step-changes.
> **Do after the data backfill + model training track (ROADMAP Phase 0.E) is complete.**
>
> Each item replaces something currently missing or based on scraping/assumptions.

### 12.1 FII/DII from Upstox API (replaces NSE scraper) 💡
- **NOW**: `IDEAS_ADVANCED §2.3` assumes we scrape NSE website for FII/DII data
- **BETTER**: `GET /v2/market/fii` and `GET /v2/market/dii` → clean direct API, same token
- **Use**: Pre-market session bias modifier (+/- 0.05 score) for the day
- **File**: `screener/daily_screener.py` — fetch once at 9:00 IST before market open

### 12.2 Exchange Status + Market Holidays gating 💡
- `GET /v2/market/status?exchange=NSE` → gate live runner on actual exchange status, not time
- `GET /v2/market/holidays?exchange=NSE` → auto-skip holidays in backfill loop
- **Currently**: backfill hits empty responses on holidays and errors out
- **Files**: `live/runner.py`, `scripts/backfill_history.py`

### 12.3 Exit All Positions in Circuit Breaker ⚡
- `POST /v2/order/positions/exit` → single call flattens all open positions instantly
- **Currently**: `risk/circuit_breaker.py` flags halt but does not actually close positions
- **Wire in**: when `DAILY_LOSS_LIMIT` breach → call this endpoint, not individual cancel orders
- **Caveat**: only works during market hours (`UDAPI1113` error otherwise)

### 12.4 NSE_MIS.json.gz pre-filter for margin fetcher 💡
- Download MIS instrument file once → know which symbols support MIS before calling margin API
- **Currently**: `scripts/fetch_margin_multipliers.py` calls margin API for every symbol (~750 calls)
- **With pre-filter**: skip all non-MIS symbols upfront → cut API calls significantly
- **File**: `data/margin.py`

### 12.5 Fundamentals in screener ranking 💡
- `GET /v2/fundamentals/{isin}/ratios` → P/E, P/B, ROE, ROCE per stock
- `GET /v2/fundamentals/{isin}/share-holdings` → FII holding % QoQ change
- **Use**: Add to `screener/ranking_features.py` — FII increasing stake = institutional conviction signal
- **Impact**: Better stock selection pre-market → more quality signals

### 12.6 Corporate Actions calendar (trade avoidance) 💡
- `GET /v2/fundamentals/{isin}/corporate-actions` → ex-dividend, split, bonus dates
- **Problem**: On ex-dividend date, price drops mechanically = our system generates false short signal
- **Fix**: Suppress all signals for that symbol on ex-date
- **File**: `screener/catalyst_detector.py` or `live/runner.py` pre-filter

### 12.7 PCR as intraday regime modifier 💡 ⚡
- `GET /v2/market/pcr?instrument_key=NSE_INDEX|Nifty 50` → intraday Put-Call Ratio
- PCR > 1.3 = extreme fear → contrarian long bias | PCR < 0.7 = extreme greed → contrarian short
- **Not in any existing IDEAS section** — fully new
- **Use**: Session-level regime modifier in `ensemble/aggregator.py`

### 12.8 News API → catalyst_detector.py 💡
- `GET /v2/news?category=instrument_keys&instrument_keys=...` → up to 30 stocks at once
- `screener/catalyst_detector.py` currently has no live news feed
- Replace/augment with clean Upstox news API for pre-market catalyst scoring

### 12.9 Trade P&L API → RL reward buffer 💡
- `GET /v2/trade/profit-loss/data` (Analytics Token works) → actual per-trade P&L from broker
- **Use**: Supplement Action Replay trade history with real broker outcomes for RL training
- **File**: `scripts/train_rl_exit.py` / `scripts/train_rl_entry.py` — add this as a data source

### 12.10 Webhook for order fills → remove polling 💡
- Configure webhook URL in Upstox Developer App settings
- Upstox POSTs to your endpoint on every order status change (fills, rejections, GTT triggers)
- **Currently**: order status likely polled via `GET /v2/order/list` every few seconds
- **Replace with**: webhook handler in `dashboard/api/routes/system.py`
- **Impact**: Lower latency, fewer API calls, more reliable on spotty connections

### Priority within this section

| Priority | Item | Effort | Do when |
|---|---|---|---|
| ⚡⚡ | 12.3 Exit All in circuit breaker | 1 hr | After data backfill |
| ⚡⚡ | 12.6 Corporate Actions trade avoidance | 2 hrs | After data backfill |
| ⚡⚡ | 12.7 PCR as regime modifier | 1 day | After ML training validates |
| ⚡ | 12.1 FII/DII via API | half day | After data backfill |
| ⚡ | 12.2 Holidays gating | 2 hrs | During backfill script |
| ⚡ | 12.5 Fundamentals in screener | 1–2 days | After data backfill |
| 💡 | 12.4 MIS pre-filter | 2 hrs | Before next margin fetch |
| 💡 | 12.8 News API | 1 day | Phase 3 |
| 💡 | 12.9 Trade P&L for RL | half day | During RL training |
| 💡 | 12.10 Webhook | 1 day | Before live trading |
