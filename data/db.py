"""
SQLite data layer (WAL mode).

All reads and writes go through this module — never import sqlite3 elsewhere.

Why SQLite + WAL: the runner (writer) and the dashboard (readers) are separate
processes. DuckDB allows only ONE read-write process per file, so they couldn't
share a DB (issue LIVE-06). SQLite in WAL mode supports concurrent multi-process
readers + a writer, which is exactly what this system needs. For heavy historical
analytics, DuckDB can ATTACH this SQLite file later (it has a sqlite scanner) — so
we keep SQLite's concurrency for live use and DuckDB's speed available for research.

Timestamps are stored as ISO-8601 TEXT and compare correctly lexicographically.
Public functions return pandas DataFrames so callers are unchanged.
"""

from __future__ import annotations
import math
import sqlite3
import threading
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

from config.settings import DB_PATH


def to_records(df: Optional[pd.DataFrame]) -> list[dict]:
    """
    DataFrame → JSON-safe list of dicts. Replaces NaN/Inf with None so the FastAPI
    JSON renderer (which rejects non-finite floats) doesn't 500 on NULL columns.
    """
    if df is None or len(df) == 0:
        return []
    records = df.to_dict(orient="records")
    for row in records:
        for k, v in row.items():
            if isinstance(v, float) and not math.isfinite(v):
                row[k] = None
    return records


# ── Connection management (thread-local; WAL handles cross-process) ────────────
_local = threading.local()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")     # concurrent readers + a writer
    conn.execute("PRAGMA synchronous=NORMAL")   # fast + safe under WAL
    conn.execute("PRAGMA busy_timeout=5000")    # wait, don't error, on a busy writer
    return conn


def get_conn() -> sqlite3.Connection:
    """Return this thread's SQLite connection (one per thread; WAL is multi-conn safe)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


def close_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


# ── Value helpers ──────────────────────────────────────────────────────────────
def _iso(v) -> Optional[str]:
    """Datetime-like → ISO TEXT ('YYYY-MM-DD HH:MM:SS'); None/NaT → None."""
    if v is None:
        return None
    try:
        ts = pd.Timestamp(v)
        if pd.isna(ts):
            return None
        return ts.isoformat(sep=" ")
    except (ValueError, TypeError):
        return str(v)


def _now_iso() -> str:
    """Local wall-clock now as ISO TEXT (so date(entry_time) matches date.today())."""
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _clean(v, is_ts: bool = False):
    """Coerce a DataFrame cell to a SQLite-bindable value (NaN→None, numpy→native)."""
    if is_ts:
        return _iso(v)
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "item"):          # numpy scalar → python scalar
        try:
            return v.item()
        except (ValueError, AttributeError):
            return v
    return v


def _rows(df: pd.DataFrame, cols: list[str], ts_cols: tuple = ()) -> list[tuple]:
    out: list[tuple] = []
    for _, r in df.iterrows():
        out.append(tuple(_clean(r[c] if c in df.columns else None, c in ts_cols) for c in cols))
    return out


# ── Schema init ───────────────────────────────────────────────────────────────
def init_db() -> None:
    """Create all tables from schema.sql if they don't exist."""
    sql = (Path(__file__).parent / "schema.sql").read_text()
    conn = get_conn()
    conn.executescript(sql)          # SQLite runs multi-statement scripts directly
    _run_migrations(conn)
    conn.commit()
    logger.info(f"SQLite schema initialised (WAL): {DB_PATH}")


def _run_migrations(conn) -> None:
    """Idempotent column additions for DBs created before a column existed."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(trade_log)").fetchall()}
    if "mode" not in cols:
        try:
            conn.execute("ALTER TABLE trade_log ADD COLUMN mode TEXT DEFAULT 'PAPER'")
        except Exception as e:
            logger.debug(f"migration skipped (add mode): {e}")
    # PnL-NET: store per-trade transaction cost + net pnl so win/loss, Kelly and
    # the daily-loss rail are computed on what actually hits the account, not gross.
    for col in ("cost", "net_pnl"):
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE trade_log ADD COLUMN {col} REAL")
            except Exception as e:
                logger.debug(f"migration skipped (add {col}): {e}")


# ── Candle helpers ────────────────────────────────────────────────────────────
_CANDLE_COLS = ["timestamp", "symbol", "timeframe", "open", "high", "low",
                "close", "volume", "vwap", "oi", "source"]


def write_candles(df: pd.DataFrame, source: str = "upstox_hist") -> int:
    """Insert-or-replace candle rows into minute_candles. Returns rows written."""
    if df is None or df.empty:
        return 0
    df = df.copy()
    df["source"] = source
    if "vwap" not in df.columns:
        df["vwap"] = None
    if "oi" not in df.columns:
        df["oi"] = None

    conn = get_conn()
    conn.executemany(
        f"INSERT OR REPLACE INTO minute_candles ({', '.join(_CANDLE_COLS)}) "
        f"VALUES ({', '.join('?' * len(_CANDLE_COLS))})",
        _rows(df, _CANDLE_COLS, ts_cols=("timestamp",)),
    )
    conn.commit()
    return len(df)


def read_candles(
    symbol: str,
    timeframe: str = "5min",
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Read candles for a symbol/timeframe, sorted by timestamp ASC (parsed to datetime)."""
    conn = get_conn()
    where = ["symbol = ? AND timeframe = ?"]
    params: list = [symbol, timeframe]
    if from_dt is not None:
        where.append("timestamp >= ?"); params.append(_iso(from_dt))
    if to_dt is not None:
        where.append("timestamp <= ?"); params.append(_iso(to_dt))
    limit_sql = f"LIMIT {int(limit)}" if limit else ""

    query = f"""
        SELECT timestamp, symbol, timeframe, open, high, low, close, volume, vwap, oi
        FROM minute_candles
        WHERE {' AND '.join(where)}
        ORDER BY timestamp ASC
        {limit_sql}
    """
    df = pd.read_sql_query(query, conn, params=params)
    if not df.empty:
        # Parse as UTC so a column that MIXES tz-aware (real backfill, '+00:00') and
        # naive (demo seed) ISO strings doesn't crash format inference (DB-TZ). All
        # candles are stored in UTC; naive strings are assumed UTC. Downstream session
        # features convert to IST (features.indicators._ist_index).
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True)
    return df


def get_latest_candle_time(symbol: str, timeframe: str = "5min") -> Optional[datetime]:
    """Return the timestamp of the most recent candle for a symbol, as a datetime."""
    row = get_conn().execute(
        "SELECT MAX(timestamp) FROM minute_candles WHERE symbol = ? AND timeframe = ?",
        [symbol, timeframe],
    ).fetchone()
    if row and row[0]:
        try:
            return pd.to_datetime(row[0]).to_pydatetime()
        except (ValueError, TypeError):
            return None
    return None


# ── Tick helpers ──────────────────────────────────────────────────────────────
_TICK_COLS = ["timestamp", "symbol", "ltp", "open_price", "high_price", "low_price",
              "close_price", "volume", "buy_qty", "sell_qty", "bid_price", "bid_qty",
              "ask_price", "ask_qty", "avg_price", "oi", "instrument_type"]


def upsert_ticks(df: pd.DataFrame) -> int:
    """Insert live ticks. Silently ignores duplicates (same timestamp+symbol)."""
    if df is None or df.empty:
        return 0
    conn = get_conn()
    conn.executemany(
        f"INSERT OR IGNORE INTO ticks ({', '.join(_TICK_COLS)}) "
        f"VALUES ({', '.join('?' * len(_TICK_COLS))})",
        _rows(df, _TICK_COLS, ts_cols=("timestamp",)),
    )
    conn.commit()
    return len(df)


def read_recent_ticks(symbol: str, minutes: int = 5) -> pd.DataFrame:
    """Read ticks for a symbol in the last N minutes (timestamps stored as local ISO)."""
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM ticks WHERE symbol = ? "
        "AND timestamp >= datetime('now', 'localtime', ?) ORDER BY timestamp ASC",
        conn, params=[symbol, f"-{int(minutes)} minutes"],
    )
    return df


# ── Trade log helpers ─────────────────────────────────────────────────────────
def log_trade_open(
    symbol: str,
    strategy: str,
    side: str,
    product_type: str,
    qty: int,
    entry_price: float,
    sl_price: float,
    target_price: float,
    entry_score: float,
    regime: str = "",
    openalgo_order_id: str = "",
    mode: str = "PAPER",
) -> str:
    """Insert a new open trade. Returns trade_id (UUID). `mode` = PAPER | LIVE."""
    trade_id = str(uuid.uuid4())
    conn = get_conn()
    conn.execute("""
        INSERT INTO trade_log
            (trade_id, symbol, strategy, side, product_type, qty,
             entry_time, entry_price, sl_price, target_price,
             entry_score, regime_at_entry, openalgo_order_id, status, mode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
    """, [trade_id, symbol, strategy, side, product_type, int(qty), _now_iso(),
          float(entry_price), float(sl_price), float(target_price),
          float(entry_score), regime, openalgo_order_id, mode])
    conn.commit()
    return trade_id


def log_trade_close(
    trade_id: str,
    exit_price: float,
    exit_reason: str,
    exchange_order_id: str = "",
) -> None:
    """Update a trade record with exit details and compute PnL."""
    conn = get_conn()
    row = conn.execute(
        "SELECT entry_price, qty, side FROM trade_log WHERE trade_id = ?", [trade_id]
    ).fetchone()
    if not row:
        logger.warning(f"log_trade_close: trade_id {trade_id} not found")
        return

    entry_price, qty, side = float(row[0]), float(row[1]), row[2]
    multiplier = 1 if side == "BUY" else -1
    pnl = multiplier * (exit_price - entry_price) * qty           # GROSS
    pnl_pct = multiplier * (exit_price - entry_price) / entry_price if entry_price else 0.0

    # Net of the full Indian intraday cost stack (PnL-NET): a trade that is
    # gross-positive but cost-negative must NOT count as a win downstream.
    from analytics.costs import round_trip_cost
    cost = round_trip_cost(entry_price, exit_price, qty)
    net_pnl = pnl - cost

    conn.execute("""
        UPDATE trade_log SET
            exit_time = ?, exit_price = ?, exit_reason = ?,
            pnl = ?, cost = ?, net_pnl = ?, pnl_pct = ?,
            exchange_order_id = ?, status = 'CLOSED'
        WHERE trade_id = ?
    """, [_now_iso(), float(exit_price), exit_reason,
          float(pnl), float(cost), float(net_pnl), float(pnl_pct),
          exchange_order_id, trade_id])
    conn.commit()


def get_open_trades() -> pd.DataFrame:
    """Return all currently open trades."""
    return pd.read_sql_query(
        "SELECT * FROM trade_log WHERE status = 'OPEN' ORDER BY entry_time ASC", get_conn()
    )


def get_trade_log(limit: int = 200, mode: Optional[str] = None) -> pd.DataFrame:
    """Return recent trades, optionally filtered by mode ('PAPER' | 'LIVE')."""
    conn = get_conn()
    if mode:
        return pd.read_sql_query(
            "SELECT * FROM trade_log WHERE mode = ? ORDER BY entry_time DESC LIMIT ?",
            conn, params=[mode.upper(), int(limit)])
    return pd.read_sql_query(
        "SELECT * FROM trade_log ORDER BY entry_time DESC LIMIT ?", conn, params=[int(limit)])


# ── Daily performance ─────────────────────────────────────────────────────────
def upsert_daily_performance(record: dict) -> None:
    """Insert or replace a daily performance record."""
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO daily_performance
            (date, total_trades, wins, losses, win_rate, gross_pnl, net_pnl,
             max_drawdown_pct, sharpe_rolling, capital_end, best_trade,
             worst_trade, avg_hold_minutes, regime_of_day)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        record.get("date"), record.get("total_trades"), record.get("wins"),
        record.get("losses"), record.get("win_rate"), record.get("gross_pnl"),
        record.get("net_pnl"), record.get("max_drawdown_pct"),
        record.get("sharpe_rolling"), record.get("capital_end"),
        record.get("best_trade"), record.get("worst_trade"),
        record.get("avg_hold_minutes"), record.get("regime_of_day"),
    ])
    conn.commit()


def get_equity_curve(days: int = 90) -> pd.DataFrame:
    """Equity curve for the dashboard chart, chronological, with an `equity` column (UI-03)."""
    return pd.read_sql_query("""
        SELECT date, equity, net_pnl FROM (
            SELECT date, capital_end AS equity, net_pnl
            FROM daily_performance
            ORDER BY date DESC
            LIMIT ?
        ) ORDER BY date ASC
    """, get_conn(), params=[int(days)])


def record_backtest_run(record: dict) -> None:
    """Persist a completed backtest into backtest_runs so /history populates (UI-02)."""
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO backtest_runs
            (run_id, run_time, strategy, symbols, from_date, to_date,
             sharpe, total_return, max_drawdown, win_rate, total_trades,
             params_json, result_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        record.get("run_id"), _now_iso(), record.get("strategy", ""), record.get("symbols", ""),
        record.get("from_date"), record.get("to_date"),
        record.get("sharpe"), record.get("total_return"), record.get("max_drawdown"),
        record.get("win_rate"), record.get("total_trades"),
        record.get("params_json", ""), record.get("result_path", ""),
    ])
    conn.commit()


# ── Utility ───────────────────────────────────────────────────────────────────
def execute_query(sql: str, params: Optional[list] = None) -> pd.DataFrame:
    """Run an arbitrary SELECT query and return a DataFrame."""
    return pd.read_sql_query(sql, get_conn(), params=params or [])


def get_candle_count(symbol: str, timeframe: str = "5min") -> int:
    """Quick row count — useful for health checks."""
    row = get_conn().execute(
        "SELECT COUNT(*) FROM minute_candles WHERE symbol = ? AND timeframe = ?",
        [symbol, timeframe],
    ).fetchone()
    return int(row[0]) if row else 0
