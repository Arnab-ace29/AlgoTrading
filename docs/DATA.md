# DATA — Sources, Schema, Pipeline

> All data sources, SQLite table definitions, and the data pipeline for live + historical data.

---

## Data Sources

### Primary Sources

| Source | Module | Data | Cost | Rate Limit |
|---|---|---|---|---|
| Upstox REST API | `data/upstox_history.py` | Historical OHLCV (1min to 1day), last 2 years | Free with account | 1000 req/day |
| Upstox WebSocket | `data/upstox_feed.py` | Live ticks (LTP, bid, ask, volume), L2 depth | Free with account | 100 symbols |
| nsepython | `data/nse_data.py` | Option chain, PCR, OI, indices | Free (scraping NSE) | ~10 req/min |
| NSE website | `signals/news/nse_announcements.py` | Corporate events, announcements | Free | Low |

### Secondary/Phase 3+ Sources

| Source | Module | Data | Cost |
|---|---|---|---|
| Google News RSS | `signals/news/finbert_sentiment.py` | Financial news headlines | Free |
| MoneyControl RSS | `signals/news/finbert_sentiment.py` | Stock news | Free |
| HuggingFace Hub | `signals/news/finbert_sentiment.py` | FinBERT model weights (one-time download ~400MB) | Free |
| OpenAI API | `signals/llm/` | LLM agent calls | ~$0.01-0.05/trade |
| Ollama (local) | `signals/llm/` | Local LLM inference | Free |

### Backup / Validation Sources

| Source | Use | Notes |
|---|---|---|
| yfinance | EOD price validation | Free, NSE ticker format: `RELIANCE.NS` |
| aeron7/nifty-banknifty-intraday-data | Historical 1-min NIFTY/BankNIFTY | Free GitHub repo, use for backtest warmup |

---

## Upstox API Key Information

### Getting Access Token (daily refresh required)
```python
# Upstox uses OAuth2 — token expires daily
# 1. Generate auth URL
from upstox_client import Configuration, ApiClient, LoginApi
config = Configuration()
config.access_token = ""
login_api = LoginApi(ApiClient(config))
# 2. User logs in via browser (once per day)
# 3. Exchange auth_code for access_token
# Store in .env as UPSTOX_ACCESS_TOKEN
```

**Automating daily token refresh:**
- Use Upstox's TOTP-based login automation (upstox-python-sdk supports this)
- Or schedule a pre-market cron job at 8:45 IST to refresh token

### Instrument Keys (NSE format)
```
NSE equity:    "NSE_EQ|{ISIN}"
  RELIANCE:    "NSE_EQ|INE002A01018"
  TCS:         "NSE_EQ|INE467B01029"
  INFY:        "NSE_EQ|INE009A01021"
  HDFCBANK:    "NSE_EQ|INE040A01034"
  ICICIBANK:   "NSE_EQ|INE090A01021"
  SBIN:        "NSE_EQ|INE062A01020"

NSE F&O index: "NSE_FO|{token}"
  NIFTY CE/PE: format varies by strike/expiry

NSE Currency:  "NSE_CUR|{token}"
  USDINR:      "NSE_CUR|..."
```

---

## SQLite Schema

**Database file:** `data/algo_trading.sqlite` — **SQLite in WAL mode** is the operational store (LIVE-06). WAL allows concurrent cross-process readers alongside a single writer, so the live runner and the dashboard can share the DB at once. Connections are thread-local (`journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`). DuckDB is optional, for heavy ad-hoc analytics only.

> **Canonical schema:** `data/schema.sql`. SQLite uses a small dynamic type set, so in the actual DDL the types below map as: `TIMESTAMPTZ`/`DATE` → `TEXT` (ISO-8601, lexicographically comparable), `DECIMAL(…)` → `REAL`, `BIGINT` → `INTEGER`, `VARCHAR(n)` → `TEXT`, `BOOLEAN` → `INTEGER` (0/1). The blocks below show the **logical** schema (column names, keys, indexes are exact); read `data/schema.sql` for the literal SQLite DDL.

### Table: `ticks`
```sql
CREATE TABLE IF NOT EXISTS ticks (
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(30) NOT NULL,
    ltp             DECIMAL(12,2),
    open_price      DECIMAL(12,2),
    high_price      DECIMAL(12,2),
    low_price       DECIMAL(12,2),
    close_price     DECIMAL(12,2),
    volume          BIGINT,
    buy_qty         BIGINT,
    sell_qty        BIGINT,
    bid_price       DECIMAL(12,2),
    bid_qty         BIGINT,
    ask_price       DECIMAL(12,2),
    ask_qty         BIGINT,
    avg_price       DECIMAL(12,2),
    oi              BIGINT,        -- open interest (F&O only)
    instrument_type VARCHAR(10),   -- EQ / FUT / CE / PE / CUR
    PRIMARY KEY (timestamp, symbol)
);
CREATE INDEX idx_ticks_symbol_time ON ticks(symbol, timestamp);
```

### Table: `minute_candles`
```sql
CREATE TABLE IF NOT EXISTS minute_candles (
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(30) NOT NULL,
    timeframe       VARCHAR(5)  NOT NULL,  -- '1min', '5min', '15min', '1hr', '1day'
    open            DECIMAL(12,2),
    high            DECIMAL(12,2),
    low             DECIMAL(12,2),
    close           DECIMAL(12,2),
    volume          BIGINT,
    vwap            DECIMAL(12,2),
    oi              BIGINT,
    source          VARCHAR(10),  -- 'upstox_live' / 'upstox_hist' / 'yfinance'
    PRIMARY KEY (timestamp, symbol, timeframe)
);
CREATE INDEX idx_candles_symbol_tf_time ON minute_candles(symbol, timeframe, timestamp DESC);
```

### Table: `option_chain`
```sql
CREATE TABLE IF NOT EXISTS option_chain (
    timestamp       TIMESTAMPTZ NOT NULL,
    underlying      VARCHAR(20) NOT NULL,  -- NIFTY, BANKNIFTY, RELIANCE, etc.
    expiry          DATE        NOT NULL,
    strike          DECIMAL(10,2) NOT NULL,
    option_type     VARCHAR(2)  NOT NULL,  -- CE / PE
    ltp             DECIMAL(10,2),
    bid             DECIMAL(10,2),
    ask             DECIMAL(10,2),
    oi              BIGINT,
    oi_change       BIGINT,
    volume          BIGINT,
    iv              DECIMAL(8,4),          -- Implied Volatility (%)
    delta           DECIMAL(8,6),
    gamma           DECIMAL(10,8),
    theta           DECIMAL(10,6),
    vega            DECIMAL(10,6),
    is_atm          BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (timestamp, underlying, expiry, strike, option_type)
);
```

### Table: `trade_log`
```sql
CREATE TABLE IF NOT EXISTS trade_log (
    trade_id        VARCHAR(36) PRIMARY KEY,  -- UUID
    entry_time      TIMESTAMPTZ NOT NULL,
    exit_time       TIMESTAMPTZ,
    symbol          VARCHAR(30) NOT NULL,
    exchange        VARCHAR(10) DEFAULT 'NSE',
    instrument_type VARCHAR(10),  -- EQ / FUT / CE / PE
    side            VARCHAR(5)  NOT NULL,  -- BUY / SELL
    qty             INTEGER     NOT NULL,
    lot_size        INTEGER     DEFAULT 1,
    entry_price     DECIMAL(12,2) NOT NULL,
    exit_price      DECIMAL(12,2),
    sl_price        DECIMAL(12,2),
    target_price    DECIMAL(12,2),
    gross_pnl       DECIMAL(12,2),
    stt             DECIMAL(10,2),   -- Securities Transaction Tax
    brokerage       DECIMAL(10,2),
    stamp_duty      DECIMAL(10,2),
    net_pnl         DECIMAL(12,2),
    pnl_pct         DECIMAL(8,4),    -- % return on capital used
    -- Signal information
    composite_score DECIMAL(6,4),    -- final score at entry
    signal_scores   JSON,            -- {"vwap_breakout": 0.71, "rsi_momentum": 0.65, ...}
    strategy_name   VARCHAR(50),     -- primary contributing strategy
    regime          VARCHAR(20),     -- TRENDING_UP / TRENDING_DOWN / MEAN_REVERTING / CHOPPY
    -- Exit information
    exit_reason     VARCHAR(30),     -- SL_HIT / TARGET_HIT / TRAILING_SL / RL_EXIT / MANUAL / EOD_CLOSE / CIRCUIT_BREAKER
    duration_mins   INTEGER,         -- minutes in trade
    -- ML metadata
    macro_prob      DECIMAL(6,4),    -- macro model bullish probability at entry
    micro_score     DECIMAL(6,4),    -- micro model score at entry
    outcome_prob    DECIMAL(6,4),    -- strategy outcome model WIN probability at entry
    -- Session metadata
    openalgo_order_id VARCHAR(50),   -- OpenAlgo order ID for reconciliation
    is_paper_trade  BOOLEAN DEFAULT FALSE,
    risk_profile    VARCHAR(10),     -- LOW / MEDIUM / HIGH
    notes           TEXT             -- manual notes
);
CREATE INDEX idx_trades_entry_time ON trade_log(entry_time DESC);
CREATE INDEX idx_trades_symbol ON trade_log(symbol, entry_time DESC);
CREATE INDEX idx_trades_strategy ON trade_log(strategy_name, entry_time DESC);
```

### Table: `daily_performance`
```sql
CREATE TABLE IF NOT EXISTS daily_performance (
    date            DATE PRIMARY KEY,
    total_trades    INTEGER   DEFAULT 0,
    winning_trades  INTEGER   DEFAULT 0,
    losing_trades   INTEGER   DEFAULT 0,
    win_rate        DECIMAL(6,4),
    gross_pnl       DECIMAL(12,2) DEFAULT 0,
    fees_total      DECIMAL(10,2) DEFAULT 0,
    net_pnl         DECIMAL(12,2) DEFAULT 0,
    max_intraday_drawdown  DECIMAL(12,2),
    max_intraday_gain      DECIMAL(12,2),
    avg_trade_pnl   DECIMAL(10,2),
    avg_win_pnl     DECIMAL(10,2),
    avg_loss_pnl    DECIMAL(10,2),
    profit_factor   DECIMAL(8,4),    -- gross_profit / gross_loss
    -- By strategy breakdown (JSON)
    pnl_by_strategy JSON,            -- {"vwap_breakout": 1200, "rsi_momentum": -400}
    trades_by_strategy JSON,         -- {"vwap_breakout": 5, "rsi_momentum": 3}
    -- Session info
    market_regime   VARCHAR(20),     -- dominant regime of the day
    vix_open        DECIMAL(8,4),
    vix_close       DECIMAL(8,4),
    nifty_return_pct DECIMAL(8,4),   -- benchmark comparison
    is_expiry_day   BOOLEAN DEFAULT FALSE
);
```

### Table: `features_snapshot`
```sql
CREATE TABLE IF NOT EXISTS features_snapshot (
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(30) NOT NULL,
    timeframe       VARCHAR(5)  NOT NULL,
    -- All 80 features stored for ML training
    rsi_14          DECIMAL(8,4),
    macd            DECIMAL(12,6),
    macd_signal     DECIMAL(12,6),
    macd_hist       DECIMAL(12,6),
    stoch_rsi       DECIMAL(8,4),
    williams_r      DECIMAL(8,4),
    roc_10          DECIMAL(8,4),
    roc_20          DECIMAL(8,4),
    ema_9           DECIMAL(12,2),
    ema_20          DECIMAL(12,2),
    ema_50          DECIMAL(12,2),
    sma_200         DECIMAL(12,2),
    vwap            DECIMAL(12,2),
    vwap_dist_pct   DECIMAL(8,4),
    adx             DECIMAL(8,4),
    di_plus         DECIMAL(8,4),
    di_minus        DECIMAL(8,4),
    atr_14          DECIMAL(10,4),
    bb_upper        DECIMAL(12,2),
    bb_lower        DECIMAL(12,2),
    bb_pct_b        DECIMAL(8,4),
    vol_20          DECIMAL(10,4),
    vol_60          DECIMAL(10,4),
    obv_slope       DECIMAL(12,4),
    mfi_14          DECIMAL(8,4),
    volume_ratio    DECIMAL(8,4),
    volume_delta    BIGINT,
    volume_spike    BOOLEAN,
    pcr             DECIMAL(8,4),
    oi_change_pct   DECIMAL(8,4),
    iv_atm          DECIMAL(8,4),
    delta_atm       DECIMAL(8,6),
    gamma_atm       DECIMAL(10,8),
    theta_pressure  DECIMAL(10,6),
    days_to_expiry  INTEGER,
    session_progress DECIMAL(6,4),
    is_first_hour   BOOLEAN,
    is_last_hour    BOOLEAN,
    day_of_week     INTEGER,
    -- Full 80 columns... (abbreviated here for brevity, see SIGNALS.md for complete list)
    PRIMARY KEY (timestamp, symbol, timeframe)
);
```

### Table: `model_training_log`
```sql
CREATE TABLE IF NOT EXISTS model_training_log (
    log_id          VARCHAR(36) PRIMARY KEY,
    trained_at      TIMESTAMPTZ NOT NULL,
    model_name      VARCHAR(50) NOT NULL,   -- macro_model, micro_model, rl_exit, etc.
    training_samples INTEGER,
    auc_score       DECIMAL(8,6),           -- walk-forward AUC
    accuracy        DECIMAL(8,6),
    precision_score DECIMAL(8,6),
    recall_score    DECIMAL(8,6),
    train_date_from DATE,
    train_date_to   DATE,
    model_file_path TEXT,
    top_features    JSON,                   -- top 10 features + importances
    notes           TEXT
);
```

### Table: `sentiment_cache`
```sql
CREATE TABLE IF NOT EXISTS sentiment_cache (
    cache_id        VARCHAR(36) PRIMARY KEY,
    computed_at     TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(30) NOT NULL,
    source          VARCHAR(30),   -- 'google_news', 'moneycontrol', 'nse_announcement'
    headline        TEXT,
    sentiment_score DECIMAL(8,6),  -- [-1, +1]
    positive_prob   DECIMAL(8,6),
    negative_prob   DECIMAL(8,6),
    neutral_prob    DECIMAL(8,6),
    expires_at      TIMESTAMPTZ    -- don't re-run sentiment after this time
);
CREATE INDEX idx_sentiment_symbol ON sentiment_cache(symbol, computed_at DESC);
```

### Table: `backtest_runs`
```sql
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id          VARCHAR(36) PRIMARY KEY,
    run_at          TIMESTAMPTZ NOT NULL,
    instruments     JSON,          -- ["RELIANCE", "TCS", ...]
    date_from       DATE,
    date_to         DATE,
    timeframe       VARCHAR(5),
    strategy_names  JSON,          -- signals used
    risk_profile    VARCHAR(10),
    slippage_pct    DECIMAL(6,4),
    -- Results
    total_return_pct DECIMAL(10,4),
    annualized_return DECIMAL(10,4),
    sharpe_ratio    DECIMAL(8,4),
    sortino_ratio   DECIMAL(8,4),
    max_drawdown_pct DECIMAL(8,4),
    win_rate        DECIMAL(6,4),
    total_trades    INTEGER,
    profit_factor   DECIMAL(8,4),
    expectancy      DECIMAL(10,2),
    -- Storage
    equity_curve_json JSON,        -- [[timestamp, cumulative_pnl], ...]
    monthly_returns_json JSON,
    walk_forward_results JSON,
    result_file_path TEXT          -- path to HTML tearsheet
);
```

---

## Data Pipeline — Live Trading

### Startup Sequence
```
1. init_db() — create tables if not exist
2. upstox_history.py — backfill any gaps since last session
3. upstox_feed.py — connect WebSocket, subscribe to instruments
4. nse_data.py — fetch initial option chain snapshot
5. live/runner.py — start main loop
```

### WebSocket Message Handler
```python
def on_message(message):
    # Parse Upstox WebSocket feed_response
    for tick in message.feeds:
        upsert_tick(db, tick)
        # Aggregate into minute candle if minute boundary crossed
        if new_minute_boundary(tick.timestamp):
            build_candle_from_ticks(db, tick.symbol, last_minute)
```

### Historical Data Backfill
```python
# data/upstox_history.py
def backfill_gaps(symbol: str, timeframe: str, days: int = 365):
    # Find last available timestamp in SQLite
    last_ts = db.execute_query(
        "SELECT MAX(timestamp) AS ts FROM minute_candles WHERE symbol=? AND timeframe=?",
        [symbol, timeframe]
    ).iloc[0]["ts"]
    # Fetch from Upstox REST API from last_ts to today
    # Insert new candles into SQLite (write_candles → INSERT OR REPLACE)
```

---

## Data Volume Estimates

| Table | Rows/day | 1-year size | Notes |
|---|---|---|---|
| ticks | ~50,000 per symbol × 50 symbols = 2.5M | ~150 GB | Store only for F&O instruments (much lower volume) |
| minute_candles (1min) | 375 bars × 50 symbols = 18,750 | ~1 GB | Primary historical data |
| minute_candles (5min) | 75 bars × 50 symbols = 3,750 | ~200 MB | Most used |
| option_chain | 48 snapshots × 200 strikes = 9,600 | ~400 MB | 30-min snapshots |
| trade_log | ~10 trades/day | ~4 MB/year | Very small |
| features_snapshot | Same as minute_candles | ~5 GB | Only store for training windows |

**Recommendation:** Only store raw ticks for F&O underlyings (NIFTY, BankNIFTY). For equities, aggregate to 1-min candles immediately and discard sub-minute ticks.

---

## Data Quality Checks

Run `scripts/validate_data.py` before each backtest:

```python
checks = [
    # 1. No gap longer than 5 bars during market hours
    "Check for candle gaps > 5 bars (9:15–15:30)",
    # 2. No OHLCV where low > high or close outside high/low
    "Check OHLC integrity (low <= open,close <= high)",
    # 3. No duplicate timestamps
    "Check no duplicate (symbol, timestamp, timeframe)",
    # 4. Volume should be > 0 for liquid stocks
    "Check volume > 0 for Nifty 50 during market hours",
    # 5. Price continuity (no >10% gap between consecutive bars)
    "Check no >10% bar-to-bar price gap",
]
```

---

## NSE Exchange Holidays (2026)

Add blackout dates to `config/settings.py`:
```python
NSE_HOLIDAYS_2026 = [
    "2026-01-26",  # Republic Day
    "2026-02-26",  # Mahashivratri
    "2026-03-25",  # Holi
    "2026-04-02",  # Ram Navami
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-10-02",  # Gandhi Jayanti
    # Add rest from NSE official calendar
]
```
