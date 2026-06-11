# Upstox API Reference (Condensed)
> Sourced from official docs + SDK README — last updated 2026-06-08

---

## Authentication

### OAuth Flow (LIVE apps only)
1. Open browser to:
   ```
   https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id=<API_KEY>&redirect_uri=<REDIRECT_URI>
   ```
2. User logs in → redirected to `<REDIRECT_URI>?code=<AUTH_CODE>`
3. Exchange code for token:
   ```
   POST https://api.upstox.com/v2/login/authorization/token
   Body (form-urlencoded): code=<CODE>&client_id=<KEY>&client_secret=<SECRET>&redirect_uri=<URI>&grant_type=authorization_code
   ```
4. Response: `{ "access_token": "..." }` — valid until midnight IST each day

### Sandbox Token (SANDBOX apps only)
- Go to `account.upstox.com/developer/apps` → Sandbox app → **Generate** button
- Token valid **30 days**. No OAuth needed.
- **Sandbox tokens ONLY work for Order APIs** (Place/Modify/Cancel).
- Historical data, market quotes, WebSocket → use **live OAuth token**.
- Sandbox order URL: `https://sandbox.upstox.com/v2/order/place` (NOT api.upstox.com)

### SDK Sandbox Mode
```python
configuration = upstox_client.Configuration(sandbox=True)
configuration.access_token = 'SANDBOX_ACCESS_TOKEN'
```

### Analytics Token ⭐ (READ-ONLY, 1-YEAR LIFETIME)
**This is the best token for unattended scripts (backfill, screener) — no daily re-auth.**
- Generate: `account.upstox.com/developer/apps` → **Analytics** tab → **Generate Token**
- Expires in **1 year** (not midnight IST like daily OAuth token)
- Only **one** analytics token allowed per account at a time
- Strictly **read-only** — no order placement allowed
- Supports: Historical Data, Market Quote, WebSocket, Portfolio (read-only), Charges, Margins, Option Chain, Fundamentals, News
- Account & Funds (read-only) only from a **registered static IP**
- Store as `ANALYTICS_TOKEN` in `.env` — use for all backfill/screener scripts

```bash
# Use like a regular bearer token:
curl -H 'Authorization: Bearer {analytics_token}' https://api.upstox.com/v3/historical-candle/...
```

---

## Base URLs
| Purpose | URL |
|---|---|
| REST API (all) | `https://api.upstox.com` |
| Order placement (HFT) | `https://api-hft.upstox.com` |
| Sandbox order testing | `https://sandbox.upstox.com` |
| WebSocket market feed V3 | `wss://api.upstox.com/v3/feed/market-data-feed` |

---

## Historical Data

### V3 API ✅ (USE THIS — supports all intervals)
```
GET https://api.upstox.com/v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}
```
- **unit**: `minutes` | `hours` | `days` | `weeks` | `months`
- **interval**: any integer `1`–`300` (for minutes; `1`–`5` for hours)
- **Examples**: `minutes/1`, `minutes/5`, `minutes/15`, `minutes/30`, `hours/1`, `hours/4`, `days/1`, `weeks/1`, `months/1`
- **instrument_key**: `NSE_EQ|INE002A01018` (pipe URL-encoded as `%7C` in curl; SDK handles automatically)
- **Date format**: `YYYY-MM-DD` for both `to_date` and `from_date`
- **Response candle format**: `[timestamp_IST, open, high, low, close, volume, open_interest]`
- **New instruments supported in V3**: India VIX (`NSE_INDEX|India VIX`), GIFT NIFTY, Dow Jones, S&P 500, FTSE 100, USD/INR, Oil (Brent/WTI) — keys from global.json.gz

#### SDK
```python
api = upstox_client.HistoryV3Api(upstox_client.ApiClient(config))
resp = api.get_historical_candle_data1(
    instrument_key='NSE_EQ|INE002A01018',
    unit='minutes',
    interval='5',
    to_date='2026-06-05',
    from_date='2026-06-01',
)
candles = resp.data.candles  # list of [timestamp, open, high, low, close, volume, oi]
```

#### ⚠️ Known error codes
| Error | Cause |
|---|---|
| Invalid `to_date` | Date in future or wrong format |
| Invalid `from_date` | Earlier than exchange data availability |
| Invalid `unit` | Must be exactly `minutes`/`hours`/`days`/`weeks`/`months` |
| Invalid `interval` | Must be integer 1–300 for minutes |

### V2 API ⚠️ DEPRECATED — limited intervals only
- Supports ONLY: `1minute`, `30minute`, `day`, `week`, `month`
- Do NOT use for 5min/15min — use V3 instead.

### Intraday (current day only) V3
```
GET https://api.upstox.com/v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}
```
- No date params — returns current trading day candles up to now
- Supported units: `minutes`, `hours`, `days`
- Useful for live bar aggregation without WebSocket

---

## Market Quotes
> All quote endpoints require LIVE token (or Analytics Token) — sandbox token returns 401.
> All support up to **500 instruments** per call via comma-separated `instrument_key` param.

### Full Market Quote
```
GET https://api.upstox.com/v2/market-quote/quotes?instrument_key=NSE_EQ|INE002A01018,NSE_EQ|INE467B01029
```
Returns: OHLC, LTP, volume, bid-ask 5-level depth, 52w high/low, circuit limits.

### LTP V3 ✅ (bulk, up to 500 instruments)
```
GET https://api.upstox.com/v3/market-quote/ltp?instrument_key=NSE_EQ|INE002A01018,...
```

### OHLC V3 ✅ (bulk, up to 500 instruments)
```
GET https://api.upstox.com/v3/market-quote/ohlc?instrument_key=NSE_EQ|INE002A01018,...
```

### LTP V2 (legacy)
```
GET https://api.upstox.com/v2/market-quote/ltp?instrument_key=...
```

### Option Greeks
```
GET https://api.upstox.com/v2/market-quote/option-greek?instrument_key=...
```
Returns: delta, gamma, theta, vega, implied volatility.

---

## WebSocket — Market Data Feed V3

### SDK Usage (correct pattern)
```python
import upstox_client

configuration = upstox_client.Configuration()
configuration.access_token = '<LIVE_OAUTH_TOKEN>'   # must be live token, NOT sandbox

streamer = upstox_client.MarketDataStreamerV3(
    upstox_client.ApiClient(configuration),
    ["NSE_EQ|INE002A01018", "NSE_INDEX|Nifty 50"],  # optional at init
    "full"   # mode: ltpc | full | option_greeks | full_d30
)

def on_open():
    streamer.subscribe(["NSE_EQ|INE002A01018"], "ltpc")

def on_message(message):
    print(message)

def on_error(error):
    print("Error:", error)

streamer.on("open", on_open)
streamer.on("message", on_message)
streamer.on("error", on_error)
streamer.connect()
```

### Modes
| Mode | Data included |
|---|---|
| `ltpc` | Last trade price, time, qty, prev close |
| `full` | OHLC + D5 depth + 1min/30min/day candles |
| `option_greeks` | Greeks only |
| `full_d30` | full + 30-level market depth |

### Methods
- `connect()` — establish connection
- `subscribe(keys, mode)` — subscribe instruments (both params required)
- `unsubscribe(keys)` — remove instruments
- `change_mode(keys, mode)` — switch mode for subscribed instruments
- `disconnect()` — close connection
- `auto_reconnect(enable, interval_sec, retry_count)` — configure reconnect

### Events: `open`, `close`, `message`, `error`, `reconnecting`, `autoReconnectStopped`

### ⚠️ Sandbox limitation
WebSocket requires a **live OAuth token**. Sandbox-generated tokens are rejected at WS handshake.

---

## Orders

### Place Order V3 ✅ (Sandbox Enabled)
```
POST https://api-hft.upstox.com/v3/order/place
Headers: Authorization: Bearer <token>, Content-Type: application/json
```
```json
{
  "quantity": 1,
  "product": "D",
  "validity": "DAY",
  "price": 0,
  "instrument_token": "NSE_EQ|INE669E01016",
  "order_type": "MARKET",
  "transaction_type": "BUY",
  "disclosed_quantity": 0,
  "trigger_price": 0,
  "is_amo": false,
  "slice": true
}
```
- `product`: `I` (intraday) | `D` (delivery) | `MTF`
- `order_type`: `MARKET` | `LIMIT` | `SL` | `SL-M`
- `slice: true` → auto-splits orders exceeding exchange freeze quantity
- Response: `{ "data": { "order_ids": ["..."] } }`

### SDK (V3, Sandbox mode)
```python
configuration = upstox_client.Configuration(sandbox=True)
configuration.access_token = 'SANDBOX_ACCESS_TOKEN'
api = upstox_client.OrderApiV3(upstox_client.ApiClient(configuration))
body = upstox_client.PlaceOrderV3Request(
    quantity=1, product="D", validity="DAY", price=0,
    instrument_token="NSE_EQ|INE669E01016",
    order_type="MARKET", transaction_type="BUY",
    disclosed_quantity=0, trigger_price=0, is_amo=False, slice=True
)
resp = api.place_order(body)
# With algo name (SEBI compliance):
resp = api.place_order(body, algo_name="your-registered-algo-name")
```

### Sandbox-enabled Order APIs
- Place Order (v2 + v3)
- Place Multi Order
- Modify Order (v2 + v3)
- Cancel Order (v2 + v3)

---

## Charges & Margin

### Margin Details — `POST /v2/charges/margin` ⚠️ SINGLE INSTRUMENT ONLY
```
POST https://api.upstox.com/v2/charges/margin
Headers: Authorization: Bearer <live_or_analytics_token>, Content-Type: application/json
```
```json
{
  "instruments": [
    {
      "instrument_key": "NSE_EQ|INE669E01016",
      "quantity": 1,
      "transaction_type": "BUY",
      "product": "I"
    }
  ]
}
```
- **`product`**: `I` (intraday/MIS) | `D` (delivery) | `CO` | `MTF`
- **`transaction_type`**: `BUY` | `SELL`
- **⚠️ CRITICAL: Only 1 instrument per request.** Sending >1 raises `UDAPI1102: instrument limit exceeded`. This is a pre-trade margin calculator, NOT a bulk API.
- Requires **live OAuth token** or **Analytics Token** — sandbox token → 401.

#### Response (EQ example)
```json
{
  "status": "success",
  "data": {
    "margins": [
      {
        "span_margin": 0,
        "exposure_margin": 0,
        "equity_margin": 33.6,
        "net_buy_premium": 0,
        "additional_margin": 0,
        "total_margin": 33.6,
        "tender_margin": 0
      }
    ],
    "required_margin": 33.6,
    "final_margin": 33.6
  }
}
```
- `equity_margin` = actual margin blocked for intraday equity (MIS)
- `total_margin` = same as `equity_margin` for EQ; differs for F&O
- MIS multiplier = `(price × qty) / total_margin`

#### SDK usage (in data/margin.py)
```python
api = upstox_client.ChargeApi(get_api_client())
body = upstox_client.MarginRequest(instruments=[
    upstox_client.Instrument(
        instrument_key=ikey, quantity=1,
        product="I", transaction_type="BUY", price=1000.0
    )
])
resp = api.post_margin(body)
total = resp.data.margins[0].total_margin
multiplier = 1000.0 / total   # e.g. 200 margin → 5× multiplier
```

#### Practical notes for `fetch_margin_multipliers.py`
- Use `_BATCH_SIZE = 1` and `_REQUEST_DELAY = 0.25s` → ~3 min for 750 symbols
- Margin % is **price-invariant** for equity MIS — any round reference price gives the same ratio
- Margins change with SEBI VAR cycles (volatility-based) — refresh weekly
- Error `UDAPI1102` = sent more than 1 instrument; reduce batch size
- Alternative: download `NSE_MIS.json.gz` to first filter which symbols even support MIS, then only call margin API for those

### Brokerage Details — `GET /v2/charges/brokerage`
```
GET https://api.upstox.com/v2/charges/brokerage?instrument_token=NSE_EQ|...&quantity=10&product=I&transaction_type=BUY&price=500
```
Returns itemised brokerage + taxes. Useful for cost-effective trade filtering.

---

## Portfolio

### Positions
```
GET https://api.upstox.com/v2/portfolio/short-term-positions
```
Returns current day open positions with real-time P&L, qty, margin details.

### Holdings (long-term)
```
GET https://api.upstox.com/v2/portfolio/long-term-holdings
```
Delivery holdings from previous sessions. Also works with Analytics Token.

### MTF Positions
```
GET https://api.upstox.com/v2/portfolio/mtf-positions
```

### Convert Position
```
PUT https://api.upstox.com/v2/portfolio/convert-position
```
Switches open position between product types (I ↔ D ↔ MTF).

---

## Instruments (legacy section — key formats)

### Instrument Key format
```
{EXCHANGE}|{ISIN_or_TOKEN}
Examples:
  NSE_EQ|INE002A01018     ← RELIANCE equity
  NSE_INDEX|Nifty 50      ← Nifty 50 index
  NSE_INDEX|India VIX     ← India VIX
  NSE_FO|43919            ← F&O by numeric token
```

### Known correct ISINs (verified against V3 API)
| Symbol | Instrument Key |
|---|---|
| RELIANCE | `NSE_EQ\|INE002A01018` |
| TCS | `NSE_EQ\|INE467B01029` |
| INFY | `NSE_EQ\|INE009A01021` |
| HDFCBANK | `NSE_EQ\|INE040A01034` |
| ICICIBANK | `NSE_EQ\|INE090A01021` |
| SBIN | `NSE_EQ\|INE062A01020` |
| AXISBANK | `NSE_EQ\|INE238A01034` |
| WIPRO | `NSE_EQ\|INE075A01022` |
| HINDUNILVR | `NSE_EQ\|INE030A01027` |
| BAJFINANCE | `NSE_EQ\|INE296A01032` ← corrected (not INE296A01024) |
| NIFTY50 | `NSE_INDEX\|Nifty 50` |
| INDIAVIX | `NSE_INDEX\|India VIX` |

---

## Rate Limits
| API Category | Limit |
|---|---|
| **Order APIs** (Place/Modify/Cancel/GTT) — Regular Algo | No algo registration needed; standard per-second cap |
| **Order APIs** — SEBI-Registered Algo | Higher rate; algo registration required |
| **Standard APIs** (historical, quotes, holdings, margin) | Standard per-second / per-minute limits |
| **Payout APIs** — Standard (Get Payouts/Modes/Payins) | Standard access |
| **Payout APIs** — Restricted (Request/Modify/Cancel Payout) | Restricted access |

- Exceeding limits → **temporary suspension** of access
- For backfill of 750 symbols at 5min: add ~0.25s delay between requests to stay safe
- Margin API (`POST /v2/charges/margin`): treat as Standard API; 1 instrument per call (see Charges section)

---

## Sandbox — What Works vs What Doesn't
| API | Sandbox Token | Live OAuth Token | Analytics Token |
|---|---|---|---|
| Place / Modify / Cancel Order (v2+v3) | ✅ | ✅ | ❌ (read-only) |
| Historical Candle Data V2/V3 | ✅ (auth not strictly checked) | ✅ | ✅ |
| LTP / Full Market Quote | ❌ 401 | ✅ | ✅ |
| WebSocket Market Feed | ❌ rejected at handshake | ✅ | ✅ |
| User Profile | ❌ 401 | ✅ | ✅ (read-only) |
| Portfolio / Holdings | ❌ | ✅ | ✅ (read-only, static IP for account APIs) |
| Charges / Margin API | ❌ | ✅ | ✅ |

---

## SDK Key Classes
```python
upstox_client.Configuration(sandbox=True/False)
upstox_client.ApiClient(configuration)

# Historical
upstox_client.HistoryV3Api       # V3 — use this (5min/15min/1hr supported)
upstox_client.HistoryApi         # V2 — deprecated, 1min/30min/day only

# Orders
upstox_client.OrderApiV3         # V3 — use this (slicing, algo name)
upstox_client.OrderApi           # V2 — deprecated

# Market Data
upstox_client.MarketDataStreamerV3   # WebSocket live feed — use this
upstox_client.PortfolioDataStreamer  # Order/position/holding updates

# User / Account
upstox_client.UserApi            # Profile (live/analytics token)
upstox_client.ChargeApi          # Brokerage + Margin (live/analytics token)

# Portfolio
upstox_client.PortfolioApi       # Positions, holdings (live/analytics token)
```

---

## Instruments

### Static JSON.gz files (download once; refresh daily/weekly)
| File | URL |
|---|---|
| All exchanges (complete) | `https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz` |
| NSE only | `https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz` |
| BSE only | `https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz` |
| MCX only | `https://assets.upstox.com/market-quote/instruments/exchange/MCX.json.gz` |
| **NSE MIS eligible** | `https://assets.upstox.com/market-quote/instruments/exchange/NSE_MIS.json.gz` |
| **BSE MIS eligible** | `https://assets.upstox.com/market-quote/instruments/exchange/BSE_MIS.json.gz` |
| MTF eligible | `https://assets.upstox.com/market-quote/instruments/exchange/MTF.json.gz` |
| Global indices/indicators | `https://assets.upstox.com/market-quote/instruments/exchange/global.json.gz` |
| Suspended | `https://assets.upstox.com/market-quote/instruments/exchange/suspended-instrument.json.gz` |
| Mutual funds | `https://assets.upstox.com/market-quote/instruments/exchange/mf-instruments.json.gz` |

> ⭐ **NSE_MIS.json.gz** — download this to know which symbols support intraday (MIS) leverage WITHOUT calling the margin API per symbol. Saves API calls in `fetch_margin_multipliers.py`.

### EQ Instrument JSON structure
```json
{
  "segment": "NSE_EQ",
  "name": "JOCIL LIMITED",
  "exchange": "NSE",
  "isin": "INE839G01010",
  "instrument_type": "EQ",
  "instrument_key": "NSE_EQ|INE839G01010",
  "lot_size": 1,
  "freeze_quantity": 100000.0,
  "exchange_token": "16927",
  "tick_size": 5.0,
  "trading_symbol": "JOCIL",
  "short_name": "JOCIL",
  "security_type": "NORMAL"
}
```
Filter by `segment=NSE_EQ` and `instrument_type=EQ` to get all NSE equities.

### Instrument Search API (no download needed)
```
GET https://api.upstox.com/v2/instruments/search?query=RELIANCE&filter=NSE_EQ
```
Response shape matches BOD instrument files. Supports pagination and segment filters.

---

## News API
```
GET https://api.upstox.com/v2/news
```
**Query params:**
- `category`: `instrument_keys` | `positions` | `holdings`
- `instrument_keys`: comma-separated, up to **30** instrument keys (when `category=instrument_keys`)
- Pagination: page 1–100, page_size default 10

**Response:** keyed by instrument_key → list of `{heading, summary, thumbnail, article_link, published_time}`

```bash
# News for specific stocks
curl 'https://api.upstox.com/v2/news?category=instrument_keys&instrument_keys=NSE_EQ%7CINE002A01018,NSE_EQ%7CINE467B01029' \
  -H 'Authorization: Bearer {token}'

# News for your current positions (no instrument_keys needed)
curl 'https://api.upstox.com/v2/news?category=positions' -H 'Authorization: Bearer {token}'
```

> **Use cases in this project**: catalyst detector (`screener/catalyst_detector.py`), pre-market news sentiment scoring for daily screener ranking.

---

## Fundamentals API
> All keyed by **ISIN** (e.g. `INE002A01018`). Works with Analytics Token. Supports `annual`/`quarterly` and `consolidated`/`standalone` where applicable.

### Company Profile
```
GET https://api.upstox.com/v2/fundamentals/{isin}/profile
```
Returns: `company_profile` (description), `sector`, `sector_market_cap_inr`, `sector_market_cap_usd`

### Balance Sheet
```
GET https://api.upstox.com/v2/fundamentals/{isin}/balance-sheet?period=annual&type=consolidated
```
Returns: total assets, liabilities, equity, debt, cash — annual or quarterly

### Income Statement
```
GET https://api.upstox.com/v2/fundamentals/{isin}/income-statement?period=annual&type=consolidated
```
Returns: revenue, operating profit, EBITDA, net profit — annual or quarterly

### Cash Flow
```
GET https://api.upstox.com/v2/fundamentals/{isin}/cash-flow?period=annual&type=consolidated
```
Returns: operating, investing, financing cash flows

### Share Holdings
```
GET https://api.upstox.com/v2/fundamentals/{isin}/share-holdings
```
Returns quarterly snapshots of: `promoter_%`, `fii_%`, `dii_%`, `public_%` — track smart money flow

### Key Ratios ⭐
```
GET https://api.upstox.com/v2/fundamentals/{isin}/ratios
```
Returns: **P/E, P/B, ROA, ROE, ROCE, EV/EBITDA** — benchmarked against sector competitors

### Corporate Actions
```
GET https://api.upstox.com/v2/fundamentals/{isin}/corporate-actions
```
Returns: dividends, bonus issues, stock splits, rights issues with dates and ratios

### Competitors
```
GET https://api.upstox.com/v2/fundamentals/{isin}/competitors
```
Returns list of competitor instrument_keys → feed into market-quote or historical data calls

> **Use cases**: fundamental filters in screener (ROE > X, P/E < Y), corporate action calendar for event-driven signals, promoter holding trend for conviction scoring.

---

## Market Information API
> These endpoints expose institutional flow, OI structure, and exchange-level data. All require live/analytics token.

### FII & DII Activity ⭐
```
GET https://api.upstox.com/v2/market/fii?segment=<seg>&interval=<interval>
GET https://api.upstox.com/v2/market/dii?interval=<interval>
```
- FII: buy/sell contracts, amounts, open interest, net position — by segment and interval
- DII: NSE Cash market buy/sell amounts, contracts, OI — by interval
- **Use case**: macro regime signal — net FII selling → TRENDING_DOWN bias

### Open Interest (OI)
```
GET https://api.upstox.com/v2/market/oi?instrument_key=NSE_INDEX|Nifty 50&expiry=2026-06-26
```
Returns OI per strike price for calls and puts.

### Change in OI
```
GET https://api.upstox.com/v2/market/change-oi?instrument_key=...&expiry=...&interval=...
```
Compare call/put OI shifts — useful for identifying accumulation at strikes.

### Max Pain
```
GET https://api.upstox.com/v2/market/max-pain?instrument_key=...
```
Returns intraday max pain levels and spot price. Useful for identifying option expiry gravity zones.

### Put-Call Ratio (PCR)
```
GET https://api.upstox.com/v2/market/pcr?instrument_key=...
```
Returns intraday PCR with spot price by bucket interval. PCR > 1 = bearish sentiment, < 1 = bullish.

### Smartlists
```
GET https://api.upstox.com/v2/market/smartlist/options?asset_type=INDEX&category=...  (paginated)
GET https://api.upstox.com/v2/market/smartlist/futures?asset_type=STOCK&category=...  (paginated)
GET https://api.upstox.com/v2/market/smartlist/mtf                                    (paginated, up to 50/page)
```
Ranked lists of active options/futures/MTF stocks with live LTP data.

### Market Holidays
```
GET https://api.upstox.com/v2/market/holidays
```
Current year holiday list for NSE/BSE/MCX. Use to skip non-trading days in backfill loops.

### Market Timings
```
GET https://api.upstox.com/v2/market/timings?date=2026-06-09
```
Returns session open/close times per exchange and segment for the given date.

### Exchange Status
```
GET https://api.upstox.com/v2/market/status?exchange=NSE
```
Returns current status: `open` | `closed` | `pre_open`. Use to gate live runner startup.

---

## Option Chain API

### Option Contracts
```
GET https://api.upstox.com/v2/option/contract?instrument_key=NSE_INDEX|Nifty 50
```
Returns active option contracts (all expiries + strikes) for an underlying.

### Put/Call Option Chain ⭐
```
GET https://api.upstox.com/v2/option/chain?instrument_key=NSE_INDEX|Nifty 50&expiry=2026-06-26
```
Returns strike-wise call and put data including **greeks** (delta, gamma, theta, vega) and premium values.

> **Use cases**: theta_book strategy (`signals/theta/theta_book.py`), OI-based support/resistance, hedge_manager for options leg hedging.

---

## Exit All Positions ⭐ (Emergency Square-off)
```
POST https://api.upstox.com/v2/order/positions/exit
Headers: Authorization: Bearer <live_token>, Content-Type: application/json
```
**Query params (all optional):**
- `segment`: `NSE_EQ` | `BSE_EQ` | `NSE_FO` | `BSE_FO` | `MCX_FO` | `NCD_FO` | `BCD_FO` | `NSE_COM` — omit to exit ALL segments
- `tag`: order tag filter — **only works for intraday positions** (carry-forward positions ignore tags)

**Execution order**: ALL BUY positions first → then all SELL positions.
**Auto-slicing**: auto-splits oversized positions using exchange freeze quantity.

**Response:**
```json
{ "status": "success", "data": { "order_ids": ["1644490272000", "..."] }, "errors": null, "summary": { "total": 3, "success": 3, "error": 0 } }
```
- Status can be `success` | `partial_success` | `error`
- `UDAPI1111` = No open positions to exit
- `UDAPI1113` = Only accessible during market hours (can't use pre/post market)

> **Critical use case**: wire into `risk/circuit_breaker.py` — when daily loss limit hit, call this endpoint to flatten all positions instantly instead of placing individual cancel+sell orders.

---

## Place Multi Order ✅ (Sandbox Enabled)
Place multiple orders in a single API call.
```
POST https://api.upstox.com/v2/order/multi/place
Body: JSON array of order objects
```
```json
[
  {
    "correlation_id": "leg1",
    "quantity": 25,
    "product": "D",
    "validity": "DAY",
    "price": 0,
    "instrument_token": "NSE_FO|62864",
    "order_type": "MARKET",
    "transaction_type": "BUY",
    "disclosed_quantity": 0,
    "trigger_price": 0,
    "is_amo": false,
    "slice": false,
    "market_protection": 0
  }
]
```
- `correlation_id`: your own tag to match response order_ids back to your legs
- `is_amo` flag is **ignored** — system infers from current market session automatically
- **Execution order**: all BUY orders first → then all SELL orders
- `market_protection`: 1–25 (% slippage tolerance); `0` = disabled
- Sandbox-enabled (same as single Place Order)

> **Use case**: basket entry for pairs trading — buy leg A and sell leg B atomically.

---

## GTT Orders (Good Till Triggered)
GTT orders persist until the price trigger is hit — useful for placing SL/target orders that survive session end.

### Place GTT Order
```
POST https://api.upstox.com/v2/gtt/orders
Body: { trigger_type, instrument_token, transaction_type, quantity, product, trigger_price, limit_price, ... }
```

### Modify GTT Order
```
PUT https://api.upstox.com/v2/gtt/orders/{gtt_id}
```

### Cancel GTT Order
```
DELETE https://api.upstox.com/v2/gtt/orders/{gtt_id}
```

### Get GTT Order Details
```
GET https://api.upstox.com/v2/gtt/orders/{gtt_id}
```
Returns trigger conditions, execution status, and order parameters.

---

## Trade Profit & Loss API
> Historical trade-level P&L data. Works with Analytics Token. Useful for training the outcome model.

### Report Metadata
```
GET https://api.upstox.com/v2/trade/profit-loss/metadata?from_date=2026-01-01&to_date=2026-06-08&segment=EQ
```
Returns summary stats, total trade count, and aggregated P&L for the period.

### P&L Report (trade-by-trade)
```
GET https://api.upstox.com/v2/trade/profit-loss/data?from_date=2026-01-01&to_date=2026-06-08&segment=EQ&page_number=1&page_size=50
```
Returns per-trade: instrument, buy/sell price, qty, realized P&L, trade timestamp.

### Trade Charges
```
GET https://api.upstox.com/v2/trade/profit-loss/charges?trade_ids=id1,id2,...
```
Returns brokerage + tax breakdown per executed trade ID.

> **Use cases**: pull historical trade outcomes into SQLite to build the RL reward buffer; reconcile live P&L with broker records.

---

## User & Account API

### Get Profile
```
GET https://api.upstox.com/v2/user/profile
```
Returns: account details, enabled exchanges, order types, product configurations.

### Get Funds & Margin V3 ⭐
```
GET https://api.upstox.com/v3/user/get-funds-and-margin?segment=SEC
```
Returns detailed breakdown: cash, pledged margin, available-to-trade, unavailable-to-trade.
- `segment`: `SEC` (equity) | `COM` (commodity)

### Get Funds & Margin V2 (legacy)
```
GET https://api.upstox.com/v2/user/get-funds-and-margin?segment=SEC
```

### Kill Switch ⭐
```
PUT https://api.upstox.com/v2/user/trading-switch?segment=<seg>&enable=<true/false>
```
Enable/disable trading for specific segments: `NSE_EQ`, `BSE_EQ`, `NSE_FO`, `MCX_FO` etc.
- **Use case**: circuit breaker integration — auto-disable segment if daily loss limit exceeded.

### Kill Switch Status
```
GET https://api.upstox.com/v2/user/trading-switch
```
Returns current enable/disable status per segment.

### Static IPs
```
GET https://api.upstox.com/v2/user/ip      # Read registered IPs
PUT https://api.upstox.com/v2/user/ip      # Update primary/secondary IP (weekly limit; invalidates token)
```

---

## Expired Historical Candle Data (F&O)
For fetching OHLC data of **expired** futures/options contracts. Uses V2 API (not V3).
```
GET https://api.upstox.com/v2/expired-instruments/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}
```
- **`interval`**: `1minute` | `3minute` | `5minute` | `15minute` | `30minute` | `day` ← V2 format (NOT `minutes/5`)
- **`instrument_key`**: full key of the expired contract e.g. `NSE_FO|NIFTY22D0117800CE`
- **Date format**: `YYYY-MM-DD`
- Response format: same as V3 — `[timestamp, open, high, low, close, volume, oi]`

```bash
curl 'https://api.upstox.com/v2/expired-instruments/historical-candle/NSE_FO%7CNIFTY22D0117800CE/day/2022-11-30/2022-11-01' \
  -H 'Authorization: Bearer {token}'
```

> **Use case**: backtesting options strategies with `signals/theta/theta_book.py` — fetch historical IV, OI, premium decay for expired contract analysis.

---

## Webhook (Push Notifications)
Configure a webhook URL in your Upstox Developer App settings to receive **real-time POST notifications** for order and GTT order events — no polling needed.

### Order event payload
```json
{
  "update_type": "order",
  "instrument_key": "NSE_EQ|INE848E01016",
  "trading_symbol": "NHPC-EQ",
  "product": "D",
  "order_type": "MARKET",
  "transaction_type": "BUY",
  "quantity": 1,
  "status": "put order req received",
  "order_id": "240221025997024",
  "filled_quantity": 0,
  "average_price": 0,
  "order_timestamp": "2024-02-21 14:40:02"
}
```

### GTT Order event payload
```json
{
  "update_type": "gtt_order",
  "type": "MULTIPLE",
  "instrument_token": "NSE_EQ|INE806A01020",
  "gtt_order_id": "GTT-CU25270200024002",
  "rules": [
    { "strategy": "ENTRY",    "status": "FAILED",    "trigger_price": 7.7 },
    { "strategy": "STOPLOSS", "status": "CANCELLED", "trigger_price": 7.6 },
    { "strategy": "TARGET",   "status": "CANCELLED", "trigger_price": 7.64 }
  ]
}
```

**Setup**: provide your webhook URL when creating/editing the app in `account.upstox.com/developer/apps`. Must be a URL you control (not a public endpoint).

> **Use case**: wire into `dashboard/api/routes/system.py` — receive order fills and status changes via push instead of polling `/v2/order/list`. Also useful for GTT trigger alerts in `signals/theta/theta_book.py`.

---

## WebSocket — Portfolio Stream Feed
Separate from market data feed — streams real-time order and position updates.

```python
# Get authorized URL first
import upstox_client
api = upstox_client.WebsocketApi(upstox_client.ApiClient(config))
auth_url = api.get_portfolio_stream_feed_authorize()

# Then connect via SDK
streamer = upstox_client.PortfolioDataStreamer(upstox_client.ApiClient(config))
streamer.on("message", lambda msg: print(msg))
streamer.connect()
```
- Streams: order updates, position changes, holding updates
- Use for live P&L tracking without polling `GET /portfolio/short-term-positions`

### Market Data Feed Authorized URL (manual WS connection)
```
GET https://api.upstox.com/v3/feed/market-data-feed/authorize
```
Returns a one-time WS URL for direct (non-SDK) WebSocket connections.

---

## Complete API Endpoint Index

| Category | Method | Endpoint |
|---|---|---|
| **Auth** | POST | `/v2/login/authorization/token` |
| **User** | GET | `/v2/user/profile` |
| **User** | GET | `/v3/user/get-funds-and-margin` |
| **User** | PUT/GET | `/v2/user/trading-switch` (kill switch) |
| **User** | GET/PUT | `/v2/user/ip` (static IP) |
| **Historical** | GET | `/v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}` |
| **Intraday** | GET | `/v3/historical-candle/intraday/{key}/{unit}/{interval}` |
| **Quote** | GET | `/v2/market-quote/quotes` (full, up to 500) |
| **Quote V3** | GET | `/v3/market-quote/ltp` (bulk LTP, 500) |
| **Quote V3** | GET | `/v3/market-quote/ohlc` (bulk OHLC, 500) |
| **Quote** | GET | `/v2/market-quote/option-greek` |
| **Orders V3** | POST | `/v3/order/place` (HFT URL) |
| **Orders V3** | PUT | `/v3/order/modify/{id}` |
| **Orders V3** | DELETE | `/v3/order/cancel/{id}` |
| **Orders** | GET | `/v2/order/details`, `/v2/order/history`, `/v2/order/list` |
| **Multi Order** | POST | `/v2/order/multi/place` (sandbox enabled; BUY first then SELL) |
| **Exit All** | POST | `/v2/order/positions/exit` (emergency square-off; market hours only) |
| **GTT** | POST/PUT/DELETE/GET | `/v2/gtt/orders` |
| **Portfolio** | GET | `/v2/portfolio/short-term-positions` |
| **Portfolio** | GET | `/v2/portfolio/long-term-holdings` |
| **Portfolio** | PUT | `/v2/portfolio/convert-position` |
| **Trade P&L** | GET | `/v2/trade/profit-loss/metadata` |
| **Trade P&L** | GET | `/v2/trade/profit-loss/data` |
| **Trade P&L** | GET | `/v2/trade/profit-loss/charges` |
| **Charges** | POST | `/v2/charges/margin` (single instrument only!) |
| **Charges** | GET | `/v2/charges/brokerage` |
| **Market Info** | GET | `/v2/market/fii`, `/v2/market/dii` |
| **Market Info** | GET | `/v2/market/oi`, `/v2/market/change-oi` |
| **Market Info** | GET | `/v2/market/max-pain`, `/v2/market/pcr` |
| **Market Info** | GET | `/v2/market/smartlist/options`, `/futures`, `/mtf` |
| **Market Info** | GET | `/v2/market/holidays`, `/v2/market/timings`, `/v2/market/status` |
| **Option Chain** | GET | `/v2/option/contract` |
| **Option Chain** | GET | `/v2/option/chain` (with greeks) |
| **Fundamentals** | GET | `/v2/fundamentals/{isin}/profile` |
| **Fundamentals** | GET | `/v2/fundamentals/{isin}/balance-sheet` |
| **Fundamentals** | GET | `/v2/fundamentals/{isin}/income-statement` |
| **Fundamentals** | GET | `/v2/fundamentals/{isin}/cash-flow` |
| **Fundamentals** | GET | `/v2/fundamentals/{isin}/share-holdings` |
| **Fundamentals** | GET | `/v2/fundamentals/{isin}/ratios` |
| **Fundamentals** | GET | `/v2/fundamentals/{isin}/corporate-actions` |
| **Fundamentals** | GET | `/v2/fundamentals/{isin}/competitors` |
| **News** | GET | `/v2/news` (up to 30 keys / positions / holdings) |
| **Expired F&O** | GET | `/v2/expired-instruments/historical-candle/{key}/{interval}/{to}/{from}` |
| **WebSocket** | WS | `wss://api.upstox.com/v3/feed/market-data-feed` |
| **WS Auth** | GET | `/v3/feed/market-data-feed/authorize` |
| **Portfolio WS** | WS | Portfolio stream feed (via PortfolioDataStreamer SDK) |
| **Webhook** | PUSH | POST to your app URL — order + GTT order event notifications |
