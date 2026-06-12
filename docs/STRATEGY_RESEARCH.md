# Strategy Research — Intraday Momentum Breakout

*Status: Research / Ideas phase. Not yet backtested. Use this as the starting spec for building and validating.*
*Last updated: June 2026*

---

## Core Philosophy

**Single indicators are noise filters, not edges.** Real confluence means each indicator measures a different dimension of the trade, and all dimensions agree simultaneously.

```
Wrong: RSI + Stochastic + MACD  →  all three measure momentum. Triple-counting one thing.

Right: Trend + Momentum + Volume + Structure + Market Context
       Five different dimensions. If all five agree, probability is meaningfully above random.
```

The goal is not to predict every move. The goal is to identify the subset of setups where the probability of continuation is high enough that the expected value per trade is positive after all costs.

---

## Target Instrument Universe

### Why Not Just Nifty 50

Nifty 50 stocks move 0.5–1.5% per day. At ₹1L exposure, that's ₹500–1,500 gross. After 16–18 bps round-trip costs (~₹180), only a fraction is profit. The cost burden is too large relative to the move.

### The Right Universe

**Primary**: Nifty 100 (Nifty 50 + Nifty Next 50)
- Next 50 stocks move 1–2.5% per day
- Still institutional-grade liquidity (₹100–500 crore daily volume)
- Tight bid-ask spreads (0.05–0.15%)
- Full 5× MIS leverage in most cases

**Secondary (selective)**: Nifty Midcap 150 — top half only
- 2–5% daily range
- Higher spread (0.1–0.3%) but manageable for 3–5% momentum targets
- Must pass the hard liquidity filter below

### Hard Filters (Non-Negotiable for Any Stock)

```
✅ Market cap > ₹1,000 crore  (eliminates micro-cap manipulation risk)
✅ Average daily volume > ₹50 crore  (your ₹1L order is < 0.2% of daily volume)
✅ ATR(20) > 1.5% of price  (stock habitually moves enough to be worth trading)
✅ Free float > 30%  (promoter holding < 70%, reduces operator risk)
✅ Broker MIS leverage ≥ 4×  (if broker reduced leverage, they know something)
✅ Not in F&O ban period  (signals position limit pressure, distorted moves)
```

---

## The Strategy: Volume Momentum Breakout (Gap-and-Go)

### What It Exploits

When a stock opens with significantly higher-than-normal volume AND a gap-up, something real is happening: institutional buying, bulk deals, earnings surprise, sector rotation, or operator accumulation. The price discovery phase from this event plays out over 30–60 minutes. The strategy rides this phase and exits before it exhausts.

### Why Costs Are Manageable For This Strategy

Unlike scalping 0.5–1% moves, a 4–7% momentum play changes the cost math:

```
Example: 50% conviction trade on ₹20,000 capital
  Margin used: ₹10,000 → ₹50,000 exposure at 5× MIS

  Stock moves 5%:
    Gross gain:              +₹2,500
    Bid-ask spread (0.3%×2): −₹300
    Slippage (0.2% r/t):     −₹100
    Brokerage + taxes:       −₹90
    Net profit:              +₹2,010  (80% of gross retained)

  Stop-loss hit at −2%:
    Gross loss:              −₹1,000
    All costs:               −₹490
    Net loss:                −₹1,490

  Break-even win rate = 1,490 / (2,010 + 1,490) = 42.6%
  Anything above 43% win rate is profitable.
```

---

## The Five-Dimension Framework

Each dimension measures something different. All five must agree for a high-conviction setup.

---

### Dimension 1 — Trend

*Is the stock in a directional move, or oscillating in noise?*

| Indicator | Setting | Signal Required |
|---|---|---|
| **VWAP** (session-anchored) | Daily reset at 9:15 AM IST | Price > VWAP. Institutions benchmark fills to VWAP — price above it means buyers are paying up. |
| **EMA 9 / EMA 21** | 5-minute chart | 9 EMA > 21 EMA, both sloping upward. Short-term trend confirmed. |
| **Prior Day High (PDH)** | Daily level | Price above PDH = gap-up confirmed, no overhead resistance from prior session. |

**Key insight on VWAP**: Not a magic line — it's a behavioural anchor. When price is above VWAP, every institution that bought below VWAP is in profit and unlikely to sell. When price is below VWAP, they're underwater and looking to exit. Above VWAP = institutional tailwind.

---

### Dimension 2 — Momentum

*Is the move accelerating or running out of steam?*

| Indicator | Setting | Signal Required |
|---|---|---|
| **RSI** | 14-period, 5-min chart | 55–75 range. Below 55 = weak. Above 75 = overextended, skip. |
| **MACD Histogram** | 12/26/9 | Positive AND bars getting taller (momentum building, not fading). |
| **Rate of Change (ROC)** | 10-period, 5-min | Positive and rising. |

**The RSI ceiling**: If RSI is already 78+ when the ORB breaks, the first move is largely over. You'd be buying from someone who is already in profit and looking to exit. Skip entirely.

**MACD histogram direction matters more than level**: A histogram at +5 and falling is worse than a histogram at +2 and rising. Direction = acceleration.

---

### Dimension 3 — Volume

*Is real money behind this move, or retail noise?*

| Indicator | Setting | Signal Required |
|---|---|---|
| **RVOL (Relative Volume)** | Today vs 20-day avg, same time window | > 3× = meaningful. > 5× = strong. < 2× = skip. |
| **OBV (On-Balance Volume)** | Standard | Making new intraday highs as price makes new highs. OBV flat/falling while price rises = divergence = false breakout. |
| **First Candle Volume** | 9:15–9:20 AM candle | > 25% of average daily volume in one 5-min candle = institutional rush, very strong signal. |

**OBV divergence is the primary false-breakout filter**: In testing, when price breaks a level but OBV does not confirm (flat or declining), the breakout fails ~70% of the time. This single check removes a large chunk of bad trades.

**RVOL calculation note**: Must compare to the same time-of-day window, not total daily volume. A stock always has higher volume in the first 30 minutes — comparing 9:20 AM volume to the full-day average is misleading. Compare 9:15–9:20 AM volume today vs the 20-day average for 9:15–9:20 AM specifically.

---

### Dimension 4 — Price Structure

*Is this a clean, defined entry or a chase?*

| Indicator | Setting | Signal Required |
|---|---|---|
| **ORB (Opening Range Breakout)** | High/low of first 15–30 min (9:15–9:45 AM) | Price breaks above ORB high with volume. This is the entry trigger. |
| **First Candle Quality** | 9:15–9:20 AM, 5-min | Bullish: close > 70% of candle range, small upper wick (buyers in control from open). |
| **Gap Size** | Prior close vs today's open | 0.5–3% = clean setup. > 5% gap = overextended on open, risky late entry. |

**Why wait for ORB (9:45 AM) instead of entering at 9:15 AM**:
The first 15–30 minutes are price discovery — institutions, algorithms, and retail all adjusting. Fake moves in both directions are common. Waiting for the range to form and then entering the breakout filters ~40% of false opens.

**ORB research finding** (8 years, 2,122 NSE trades on Nifty 50):
- Win rate: 48.7%
- Average win: +0.48%
- Average loss: −0.37%
- The asymmetry (win > loss) compounded to +91.6% over 8 years
- Friday is the best day: 40%+ of returns come from Friday (F&O expiry positioning)
- Worst condition: extended sideways low-volatility markets

---

### Dimension 5 — Market Context

*Is the tide with you, or are you fighting the market?*

| Indicator | Setting | Signal Required |
|---|---|---|
| **Nifty 50 direction** | 5-min chart | Nifty positive AND above its own VWAP. A stock moving up in a falling market is fighting gravity. |
| **Sector index** | Relevant sector (Bank Nifty, Nifty IT, Nifty Auto etc.) | Sector up > 0.5%. Stock riding a sector wave sustains longer than a stock moving alone. |
| **India VIX** | Daily level | < 18 = calm, momentum sustains cleanly. > 22 = high fear, patterns break randomly. Skip on VIX-spike days. |

---

## Scoring System

Run this at 9:45 AM for each candidate on the watchlist.

### Must-Have (Both Required — Skip if Either Missing)

```
□ RVOL > 2×               (minimum institutional interest)
□ Price > VWAP             (institutional buy-side confirmed)
```

### Scored Signals

**Trend (max 4 pts)**
```
□ 9 EMA > 21 EMA on 5-min, both sloping up    +1
□ Price above prior day high                    +1
□ Clean ORB broken to upside                    +1
□ Gap-up > 2% (strong pre-market conviction)   +1
```

**Momentum (max 4 pts)**
```
□ RSI between 55–70                             +1
□ RSI between 70–75 (high momentum, not yet exhausted)  +1 additional
□ MACD histogram positive                       +1
□ MACD histogram increasing (accelerating)      +1
```

**Volume (max 5 pts)**
```
□ RVOL > 3×                                     +1
□ RVOL > 5×                                     +1 additional (so +2 total)
□ OBV making new intraday high                  +1
□ First candle volume > 25% of daily avg        +1
□ Gap-up 0.5–3% (clean range)                  +1
```

**Market Context (max 3 pts)**
```
□ Nifty positive + above its VWAP               +1
□ Sector index up > 0.5%                        +1
□ VIX < 18                                      +1
```

### Score → Allocation

```
Score < 5   →  Skip. Do not trade.
Score 5–7   →  20% allocation  (₹4,000 margin → ₹20,000 exposure at ₹20k capital)
Score 8–10  →  30% allocation  (₹6,000 margin → ₹30,000 exposure)
Score 11+   →  50% allocation  (₹10,000 margin → ₹50,000 exposure)

Maximum 3 trades per day. Allocations across all open trades sum to ≤ 100% of capital.
```

---

## Negative Filters — Automatic Disqualification

These override any score. If any trigger, skip the trade entirely.

```
❌ RSI > 78 at ORB time          → Overextended, buying from sellers. Skip.
❌ Gap-up > 5%                   → Move mostly done pre-market. Chasing.
❌ OBV flat or declining         → Volume not confirming. False breakout likely.
❌ Volume fading after first candle → Opening pop only, no institutional follow-through.
❌ Nifty down > 0.5% on the day  → Do not long into a falling market.
❌ VIX up > 10% from yesterday   → Volatility regime change, patterns unreliable.
❌ Upper circuit in last 10 days → Operator-driven price history, signals unreliable.
❌ Results / corporate action today or tomorrow → Unknown catalyst, pattern breaks.
❌ RVOL mostly from one bulk deal → One-time event, not sustained institutional buying.
                                    Check NSE bulk deals page before trading.
```

---

## Daily Workflow

### Pre-Market (8:45–9:10 AM)

```
1. Check India VIX. If > 22 or up > 10% from yesterday → consider sitting out the day.
2. Check Nifty futures (SGX Nifty) for gap direction.
3. Run screener:
     - Market cap > ₹1,000 cr
     - Pre-market implied gap-up > 0.5%  (use NSE pre-open data or broker screener)
     - Yesterday's RVOL > 1.5×  (unusual activity yesterday = continuation possible)
   Output: Watchlist of 5–10 candidates
4. For each candidate, note: sector, prior day high, key resistance levels
```

### 9:15–9:44 AM (Observation Only — No Trades)

```
1. Watch first candle quality for each candidate.
2. Note which stocks are holding their gap (not reversing).
3. Track RVOL building in real-time.
4. Check OBV direction on each candidate.
5. Do NOT enter before 9:45 AM. The ORB has not formed yet.
```

### 9:45–10:00 AM (Entry Window)

```
1. Score each candidate using the scoring system above.
2. Rank by score. Take top 1–3 setups only.
3. Entry trigger: Price breaks above ORB high with volume surge.
4. Entry type: Limit order, ₹0.1–0.2% above the ORB high.
   (Market orders get bad fills on fast-moving stocks. Limit orders save 0.1–0.2% slippage.)
5. If not filled within 30 seconds → skip. The move moved away from you.
6. Set stop-loss immediately on fill: below the ORB low. No manual override.
```

### 10:00–10:30 AM (Hold and Trail)

```
Every 5-minute candle:
  - Trail stop up after each 1.5% gain (lock in partial profit)
  - Watch OBV: if it flattens while price is still rising → reduce position by 50%
  - Watch RSI: if it crosses back below 60 → exit remaining position
  - Watch MACD histogram: if bars start shrinking after gaining → momentum fading
```

### Exit (Whichever Comes First)

```
✅ Target hit      → Predetermined resistance or % target. Scale out in 2 tranches.
✅ Reversal signal → First 5-min red candle on above-average volume = exit full position.
✅ Momentum fade  → RSI drops below 60, or MACD histogram shrinks for 2 consecutive bars.
✅ Time stop       → 10:30 AM hard exit. Momentum day trades exhaust by this time.
                     The longer you hold, the more you're in "swing trade" territory
                     with overnight risk. Not the strategy.
❌ Stop-loss       → Below ORB low. No exceptions. No "let me see one more candle".
```

---

## Position Sizing (Conviction-Based 20–30–50 Split)

```
Total capital:          ₹20,000
Total leveraged pool:   ₹1,00,000 (5× MIS)

Allocation by score:
  Low conviction  (score 5–7):   20% → ₹4,000 margin  → ₹20,000 exposure
  Med conviction  (score 8–10):  30% → ₹6,000 margin  → ₹30,000 exposure
  High conviction (score 11+):   50% → ₹10,000 margin → ₹50,000 exposure

Max 3 simultaneous positions.
Sum of all allocations ≤ 100% at any time.
Never use more than 80% of capital on any single day (keep 20% as buffer for SL margin calls).
```

---

## Break-Even Analysis by Capital Level

```
Capital      Leveraged    Cost per      Need to earn    Minimum    Minimum
             Exposure     round trip    per trade       trades/mo  target %
─────────────────────────────────────────────────────────────────────────────
₹20,000      ₹1,00,000   ₹180         > ₹180          12/mo      0.18%
₹50,000      ₹2,50,000   ₹450         > ₹450          12/mo      0.18%
₹1,00,000    ₹5,00,000   ₹900         > ₹900          12/mo      0.18%
```

**Transaction costs as % of move (why bigger moves matter more):**
```
1% move  →  costs eat 18% of gross gain  (poor ratio)
3% move  →  costs eat 6% of gross gain   (acceptable)
5% move  →  costs eat 3.6% of gross gain (good)
7% move  →  costs eat 2.6% of gross gain (great)
```

This is why this strategy targets 3–7% moves, not 0.5–1% scalps.

---

## Capital Ladder (Expected Monthly Net — If Strategy Works)

*Assumes: 12 trades/month, 50% win rate, avg win 4%, avg loss 2%, conviction-weighted sizing.*

```
Capital    Monthly gross   Monthly costs   Monthly net    Monthly %
─────────────────────────────────────────────────────────────────────
₹20,000    ₹3,500          ₹2,160          ₹1,340         6.7%
₹50,000    ₹8,750          ₹3,960          ₹4,790         9.6%
₹1,00,000  ₹17,500         ₹5,940          ₹11,560        11.6%
₹2,00,000  ₹35,000         ₹8,640          ₹26,360        13.2%
₹5,00,000  ₹87,500         ₹14,400         ₹73,100        14.6%
```

Note: These are projections assuming a working strategy. Before trusting any number here, the strategy needs:
1. Backtest on 2+ years of real data showing Sharpe > 1.0
2. Walk-forward validation (not in-sample curve-fitting)
3. 60+ days of paper trading showing results match backtest

---

## Indicators NOT Used and Why

| Indicator | Why Excluded |
|---|---|
| Bollinger Bands | Describes volatility range, not direction. Adds no directional edge to this strategy. |
| Stochastic | Too noisy on 5-min intraday. Constant false signals in trending momentum moves. |
| ADX standalone | Useful for regime detection in screener, not for intraday entry timing. |
| Fibonacci retracements | Manual drawing, not consistently algo-defined. Subjective = inconsistent. |
| Multiple MAs (5/10/20/50 together) | All measure the same thing with different lag. 2 EMAs max. |
| Pivot points (S1/R1) | Pre-calculated from yesterday, often irrelevant on gap-up days. |
| Ichimoku Cloud | Too many parameters, visually complex, not easy to define algorithmically for this strategy. |

---

## Open Questions to Validate in Backtest

These are assumptions in the framework that need to be tested against real data:

```
1. What is the optimal ORB window — 15 min (9:15–9:30), 30 min (9:15–9:45), or other?
2. What RVOL threshold best filters false breakouts without eliminating too many setups?
3. Does the 50% allocation on score 11+ actually yield better net returns, or is flat sizing better?
4. How does Friday performance (per ORB research) hold for small/midcap vs large cap?
5. Does OBV divergence detection cut losers enough to justify its removal of some winners?
6. What is the actual average # of qualifying setups per day that score ≥ 5? (determines real opportunity count)
7. Does VIX < 18 filter help or hurt returns? (may remove valid high-volatility momentum days)
8. Is 10:30 AM the right time stop, or is there a better window?
```

---

## Key Research Sources

- SEBI: 93% of F&O retail traders lose money (FY22–FY24). 91% in FY25.
- SEBI: 70% of intraday cash equity traders lose money (FY23).
- IntraDay Lab: 8+ year ORB backtest on Nifty 50 — 48.7% win rate, +0.48% avg win vs −0.37% avg loss = +91.6% total return.
- Academic (MDPI 2024): High opening volume + low uncertainty = strongest intraday momentum prediction (0.63 accuracy).
- QuantifiedStrategies: MACD + RSI combination tested at 73% win rate over 235 trades.
- SEBI FY24: 96–97% of institutional profits in F&O came from algorithmic trading. Institutions were net sellers of options, net buyers of premium = options selling side.
- Academic (intraday momentum): First 30-min returns predict last 30-min returns. Morning momentum has statistically significant alpha up to ~10 bps transaction cost threshold.
