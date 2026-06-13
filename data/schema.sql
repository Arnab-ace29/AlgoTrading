-- AlgoTrading SQLite Schema (WAL).
-- Init via data/db.py:init_db().  Timestamps stored as ISO-8601 TEXT.
-- WAL mode: concurrent multi-process readers + a writer (runner + dashboard).

-- ── Live tick feed ─────────────────────────────────────────────────────────────
-- Written by the live WebSocket feed; used for real-time candle aggregation.
CREATE TABLE IF NOT EXISTS ticks (
    timestamp        TEXT    NOT NULL,
    symbol           TEXT    NOT NULL,
    ltp              REAL,
    open_price       REAL,
    high_price       REAL,
    low_price        REAL,
    close_price      REAL,
    volume           INTEGER,
    buy_qty          INTEGER,
    sell_qty         INTEGER,
    bid_price        REAL,
    bid_qty          INTEGER,
    ask_price        REAL,
    ask_qty          INTEGER,
    avg_price        REAL,
    oi               INTEGER,
    instrument_type  TEXT,
    PRIMARY KEY (timestamp, symbol)
);
CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks(symbol, timestamp);

-- ── OHLCV candles (all timeframes) ───────────────────────────────────────────
-- Primary historical store.  timeframe IN ('5min', '1day').
-- Also stores index/macro data (INDIAVIX, NIFTYBANK, SP500, etc.) as '1day'.
CREATE TABLE IF NOT EXISTS minute_candles (
    timestamp   TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      INTEGER,
    vwap        REAL,
    oi          INTEGER,
    source      TEXT,
    PRIMARY KEY (timestamp, symbol, timeframe)
);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf_time
    ON minute_candles(symbol, timeframe, timestamp DESC);

-- ── Trade log ─────────────────────────────────────────────────────────────────
-- One row per trade (open + close).  mode = 'PAPER' | 'LIVE'.
CREATE TABLE IF NOT EXISTS trade_log (
    trade_id             TEXT PRIMARY KEY,
    symbol               TEXT NOT NULL,
    strategy             TEXT NOT NULL,
    side                 TEXT NOT NULL,       -- BUY | SELL
    product_type         TEXT NOT NULL,       -- MIS (intraday)
    qty                  INTEGER NOT NULL,
    entry_time           TEXT NOT NULL,
    entry_price          REAL,
    exit_time            TEXT,
    exit_price           REAL,
    sl_price             REAL,
    target_price         REAL,
    trailing_sl_price    REAL,
    pnl                  REAL,               -- gross: (exit-entry)*qty*side
    cost                 REAL,               -- round-trip transaction cost
    net_pnl              REAL,               -- pnl - cost
    pnl_pct              REAL,
    exit_reason          TEXT,
    entry_score          REAL,
    regime_at_entry      TEXT,
    openalgo_order_id    TEXT,
    exchange_order_id    TEXT,
    status               TEXT DEFAULT 'OPEN',
    mode                 TEXT DEFAULT 'PAPER'
);
CREATE INDEX IF NOT EXISTS idx_trade_symbol_time ON trade_log(symbol, entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_trade_strategy     ON trade_log(strategy);
CREATE INDEX IF NOT EXISTS idx_trade_status        ON trade_log(status);

-- ── Daily performance ─────────────────────────────────────────────────────────
-- End-of-day summary aggregated from trade_log.  Equity curve is derived here.
CREATE TABLE IF NOT EXISTS daily_performance (
    date             TEXT PRIMARY KEY,
    total_trades     INTEGER,
    wins             INTEGER,
    losses           INTEGER,
    win_rate         REAL,
    gross_pnl        REAL,
    net_pnl          REAL,
    max_drawdown_pct REAL,
    sharpe_rolling   REAL,
    capital_end      REAL,
    best_trade       REAL,
    worst_trade      REAL,
    avg_hold_minutes REAL,
    regime_of_day    TEXT
);

-- ── Backtest run registry ─────────────────────────────────────────────────────
-- One row per completed backtest run; used by the dashboard /history page.
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id       TEXT PRIMARY KEY,
    run_time     TEXT NOT NULL,
    strategy     TEXT,
    symbols      TEXT,
    from_date    TEXT,
    to_date      TEXT,
    sharpe       REAL,
    total_return REAL,
    max_drawdown REAL,
    win_rate     REAL,
    total_trades INTEGER,
    params_json  TEXT,
    result_path  TEXT
);
