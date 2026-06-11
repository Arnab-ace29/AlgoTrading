-- AlgoTrading SQLite Schema (WAL).
-- SQLite is the operational store: it supports concurrent multi-process readers +
-- a writer (WAL), so the runner and dashboard can share it (fixes LIVE-06). DuckDB
-- can later ATTACH this file for heavy analytics. Run via data/db.py:init_db().
-- Timestamps are stored as ISO-8601 TEXT ('YYYY-MM-DD HH:MM:SS[.ffffff]').

-- ── Raw tick data (live feed) ─────────────────────────────────────────────────
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

-- ── Option chain snapshots ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS option_chain (
    timestamp        TEXT NOT NULL,
    underlying       TEXT NOT NULL,
    expiry           TEXT NOT NULL,
    strike           REAL NOT NULL,
    option_type      TEXT NOT NULL,
    ltp              REAL,
    bid              REAL,
    ask              REAL,
    oi               INTEGER,
    oi_change        INTEGER,
    volume           INTEGER,
    iv               REAL,
    delta            REAL,
    gamma            REAL,
    theta            REAL,
    vega             REAL,
    PRIMARY KEY (timestamp, underlying, expiry, strike, option_type)
);

-- ── Trade log ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trade_log (
    trade_id             TEXT PRIMARY KEY,
    symbol               TEXT NOT NULL,
    strategy             TEXT NOT NULL,
    side                 TEXT NOT NULL,
    product_type         TEXT NOT NULL,
    qty                  INTEGER NOT NULL,
    entry_time           TEXT NOT NULL,
    entry_price          REAL,
    exit_time            TEXT,
    exit_price           REAL,
    sl_price             REAL,
    target_price         REAL,
    trailing_sl_price    REAL,
    pnl                  REAL,           -- GROSS realised pnl (exit-entry)*qty*side
    cost                 REAL,           -- round-trip transaction cost (analytics.costs)
    net_pnl              REAL,           -- pnl - cost (what actually hits the account)
    pnl_pct              REAL,
    exit_reason          TEXT,
    entry_score          REAL,
    regime_at_entry      TEXT,
    openalgo_order_id    TEXT,
    exchange_order_id    TEXT,
    status               TEXT DEFAULT 'OPEN',
    mode                 TEXT DEFAULT 'PAPER',   -- PAPER (virtual) | LIVE (real money)
    notes                TEXT
);
CREATE INDEX IF NOT EXISTS idx_trade_symbol_time ON trade_log(symbol, entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_trade_strategy     ON trade_log(strategy);
CREATE INDEX IF NOT EXISTS idx_trade_status        ON trade_log(status);

-- ── Daily performance ─────────────────────────────────────────────────────────
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

-- ── Equity curve (for dashboard chart) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS equity_curve (
    timestamp    TEXT PRIMARY KEY,
    capital      REAL NOT NULL,
    daily_pnl    REAL,
    drawdown_pct REAL
);

-- ── Computed features snapshot (for ML training + audit) ─────────────────────
CREATE TABLE IF NOT EXISTS features_snapshot (
    timestamp     TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    features_json TEXT,
    PRIMARY KEY (timestamp, symbol)
);

-- ── Backtest run registry ─────────────────────────────────────────────────────
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

-- ── Model training log ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS model_training_log (
    run_id       TEXT PRIMARY KEY,
    run_time     TEXT NOT NULL,
    model_name   TEXT,
    train_auc    REAL,
    val_auc      REAL,
    n_samples    INTEGER,
    features_used INTEGER,
    params_json  TEXT,
    model_path   TEXT
);

-- ── Sentiment cache (Phase 3) ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentiment_cache (
    symbol      TEXT NOT NULL,
    source      TEXT NOT NULL,
    fetch_time  TEXT NOT NULL,
    headline    TEXT,
    sentiment   REAL,
    positive    REAL,
    negative    REAL,
    neutral     REAL,
    PRIMARY KEY (symbol, source, fetch_time)
);
