"""
OpenAlgo REST API client.
Thin wrapper that routes orders to OpenAlgo (localhost:3000).
OpenAlgo then forwards to Upstox with SEBI Algo ID tagging.

All trading logic lives in our system. OpenAlgo is purely an order router.

Docs: https://docs.openalgo.in/
"""

from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger

from config.settings import OPENALGO_HOST, OPENALGO_API_KEY, PAPER_TRADE

# Keys we must never persist into OrderResult.raw_response / logs (SEC-02).
_SENSITIVE_KEYS = {"apikey", "api_key", "x-api-key", "secret", "access_token"}

# Terminal order states (lower-cased) — once an order reaches one of these, polling
# stops. "open"/"trigger pending"/"pending"/"modified" are NON-terminal.
_TERMINAL_FILLED   = {"complete", "filled", "completed", "executed"}
_TERMINAL_DEAD     = {"rejected", "cancelled", "canceled", "expired"}
_TERMINAL_STATES   = _TERMINAL_FILLED | _TERMINAL_DEAD


def _redact(d):
    """Shallow copy of a dict with secrets removed — safe to store/return (SEC-02)."""
    if not isinstance(d, dict):
        return d
    return {k: ("***REDACTED***" if k.lower() in _SENSITIVE_KEYS else v) for k, v in d.items()}


@dataclass
class OrderResult:
    success:      bool
    order_id:     str = ""
    filled_qty:   int = 0          # quantity the broker confirms filled (LIVE-03)
    avg_price:    float = 0.0      # average fill price the broker reports (0 if unknown)
    status:       str = ""         # terminal order status (complete/rejected/...)
    raw_response: dict = None
    error:        str = ""


class OpenAlgoClient:
    """
    Async-capable OpenAlgo REST client.
    Supports both paper mode (logs only) and live mode (actual orders).
    """

    BASE_URL = OPENALGO_HOST
    TIMEOUT  = 10   # seconds
    # Poll the broker this many times (× interval) for an order to reach a terminal
    # state before giving up and treating it as accepted-but-unconfirmed (LIVE-03).
    FILL_POLL_RETRIES  = 5
    FILL_POLL_INTERVAL = 0.4   # seconds

    def __init__(self, api_key: str = OPENALGO_API_KEY, paper: bool = PAPER_TRADE):
        self.api_key    = api_key
        self.paper_mode = paper
        # OpenAlgo authenticates via the `apikey` field in the JSON body, so the
        # key is sent there only — not also in an `x-api-key` header (SEC-02:
        # don't duplicate the secret across header + body).
        self._headers   = {"Content-Type": "application/json"}

    # ── Order placement ───────────────────────────────────────────────────────

    def place_order(
        self,
        symbol:       str,
        exchange:     str = "NSE",
        action:       str = "BUY",          # BUY / SELL
        quantity:     int = 1,
        order_type:   str = "MARKET",       # MARKET / LIMIT / SL / SL-M
        product:      str = "INTRADAY",     # INTRADAY / DELIVERY / CARRYFORWARD
        price:        float = 0.0,          # only for LIMIT orders
        trigger_price: float = 0.0,         # only for SL orders
        strategy_tag: str = "Phase1",       # SEBI Algo ID tag
    ) -> OrderResult:
        """Place an order via OpenAlgo."""

        payload = {
            "apikey":       self.api_key,
            "strategy":     strategy_tag,
            "symbol":       symbol,
            "action":       action,
            "exchange":     exchange,
            "pricetype":    order_type,
            "product":      product,
            "quantity":     str(quantity),
            "price":        str(price),
            "trigger_price": str(trigger_price),
            "disclosed_quantity": "0",
        }

        if self.paper_mode:
            logger.info(f"[PAPER] ORDER: {action} {quantity} {symbol} @ {order_type}")
            # Paper fills the full requested qty instantly; price is resolved by the
            # caller from the signal/monitor price. Redact apikey before return (SEC-02).
            return OrderResult(success=True, order_id="PAPER_" + symbol,
                               filled_qty=int(quantity), status="complete",
                               raw_response=_redact(payload))

        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                resp = client.post(
                    f"{self.BASE_URL}/api/v1/placeorder",
                    json=payload,
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") != "success":
                    error = data.get("message", "Unknown error")
                    logger.error(f"ORDER FAILED: {symbol} | {error}")
                    return OrderResult(success=False, error=error, raw_response=_redact(data))

                # status=="success" means ACCEPTED, not filled. Poll until the order
                # reaches a terminal state so a post-accept rejection or partial fill
                # is caught instead of being booked as a full fill (LIVE-03).
                order_id = data.get("orderid", "")
                st, filled, avg_px = self._poll_until_terminal(order_id, int(quantity))

                if st in _TERMINAL_DEAD or (st in _TERMINAL_FILLED and filled <= 0):
                    logger.error(f"ORDER {st.upper() or 'NOT FILLED'}: {symbol} (id {order_id})")
                    return OrderResult(success=False, order_id=order_id, status=st,
                                       filled_qty=0, error=f"order {st or 'unfilled'}",
                                       raw_response=_redact(data))

                logger.success(f"ORDER FILLED: {action} {filled}/{quantity} {symbol} "
                               f"@ {avg_px or '?'} | ID: {order_id} | status={st or 'unconfirmed'}")
                return OrderResult(success=True, order_id=order_id, filled_qty=filled,
                                   avg_price=avg_px, status=st, raw_response=_redact(data))

        except httpx.TimeoutException:
            logger.error(f"ORDER TIMEOUT: {symbol} — OpenAlgo not responding")
            return OrderResult(success=False, error="TIMEOUT")
        except Exception as e:
            logger.error(f"ORDER ERROR: {symbol} — {e}")
            return OrderResult(success=False, error=str(e))

    # ── Fill confirmation (LIVE-03) ───────────────────────────────────────────

    @staticmethod
    def _parse_order_status(resp: dict) -> tuple[str, int, float]:
        """
        Normalise an OpenAlgo order-status payload to (status, filled_qty, avg_price).
        OpenAlgo wraps the order under `data`; field names vary slightly by broker,
        so we read liberally. Unknown values come back as ("", 0, 0.0).
        """
        if not isinstance(resp, dict):
            return "", 0, 0.0
        d = resp.get("data", resp) or resp
        if isinstance(d, list):                     # some brokers return a list
            d = d[0] if d else {}
        if not isinstance(d, dict):
            return "", 0, 0.0

        def _first(*keys):
            for k in keys:
                if k in d and d[k] not in (None, ""):
                    return d[k]
            return None

        status = str(_first("order_status", "orderstatus", "status", "ordstatus") or "").strip().lower()
        fq = _first("filled_quantity", "filledqty", "filled_qty", "filledQuantity",
                    "cumulative_quantity", "filled", "quantity")
        ap = _first("average_price", "averageprice", "avgprice", "avg_price", "fill_price", "price")
        try:
            filled_qty = int(float(fq)) if fq is not None else 0
        except (TypeError, ValueError):
            filled_qty = 0
        try:
            avg_price = float(ap) if ap is not None else 0.0
            if avg_price < 0:
                avg_price = 0.0
        except (TypeError, ValueError):
            avg_price = 0.0
        return status, filled_qty, avg_price

    def _poll_until_terminal(self, order_id: str, requested: int) -> tuple[str, int, float]:
        """
        Poll get_order_status until the order is terminal (or retries exhausted).
        Returns (status, filled_qty, avg_price). If the broker never reports a fill
        qty but says complete, assume the full requested qty; if status can't be
        determined at all, fall back to assuming a full fill (legacy behaviour) so a
        flaky status endpoint can't strand a real position.
        """
        if not order_id:
            return "", requested, 0.0
        status, filled, avg_px = "", 0, 0.0
        for _ in range(self.FILL_POLL_RETRIES):
            s, fq, ap = self._parse_order_status(self.get_order_status(order_id) or {})
            if s:
                status = s
            if fq > filled:
                filled = fq
            if ap > 0:
                avg_px = ap
            if status in _TERMINAL_STATES:
                break
            time.sleep(self.FILL_POLL_INTERVAL)
        if status in _TERMINAL_FILLED and filled <= 0:
            filled = requested
        if not status:                              # endpoint gave us nothing usable
            filled = requested
        return status, filled, avg_px

    def close_position(
        self,
        symbol:   str,
        exchange: str = "NSE",
        quantity: int = 1,
        side:     str = "BUY",      # original entry side
        product:  str = "INTRADAY",
        strategy_tag: str = "Phase1",
    ) -> OrderResult:
        """Close an existing position (exit order)."""
        exit_action = "SELL" if side == "BUY" else "BUY"
        return self.place_order(
            symbol=symbol, exchange=exchange, action=exit_action,
            quantity=quantity, order_type="MARKET",
            product=product, strategy_tag=strategy_tag,
        )

    # ── Position and order status ─────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """Fetch current open positions from OpenAlgo."""
        if self.paper_mode:
            return []
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                resp = client.post(
                    f"{self.BASE_URL}/api/v1/positionbook",
                    json={"apikey": self.api_key},
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", [])
        except Exception as e:
            logger.error(f"get_positions failed: {e}")
            return []

    def get_funds(self) -> Optional[dict]:
        """
        Fetch broker funds/margin from OpenAlgo (`/api/v1/funds`). Returns a
        normalized dict ``{available, used, total, raw}`` or ``None`` when funds
        aren't available (paper mode, OpenAlgo down, or no live token). Never raises.
        """
        if self.paper_mode:
            return None
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                resp = client.post(
                    f"{self.BASE_URL}/api/v1/funds",
                    json={"apikey": self.api_key},
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()
            if data.get("status") != "success":
                return None
            d = data.get("data", {}) or {}
            # OpenAlgo funds fields vary slightly by broker; pick the common ones.
            def _num(*keys):
                for k in keys:
                    if k in d and d[k] not in (None, ""):
                        try:
                            return float(d[k])
                        except (TypeError, ValueError):
                            pass
                return None
            available = _num("availablecash", "available_cash", "availablemargin", "net")
            used      = _num("utiliseddebits", "utilised_debits", "used", "debits")
            total     = available + used if (available is not None and used is not None) else available
            return {"available": available, "used": used, "total": total, "raw": _redact(d)}
        except Exception as e:
            logger.debug(f"get_funds failed: {e}")
            return None

    def get_order_status(self, order_id: str) -> dict:
        """Get status of a specific order."""
        if self.paper_mode:
            return {"status": "complete", "orderid": order_id}
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                resp = client.post(
                    f"{self.BASE_URL}/api/v1/orderstatus",
                    json={"apikey": self.api_key, "orderid": order_id},
                    headers=self._headers,
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"get_order_status failed: {e}")
            return {}

    def close_all_positions(self, strategy_tag: str = "Phase1") -> list[OrderResult]:
        """Emergency close all open positions (EOD square-off or kill switch)."""
        positions = self.get_positions()
        results = []
        for pos in positions:
            symbol = pos.get("tradingsymbol", "")
            qty    = abs(int(pos.get("netqty", 0)))
            side   = "BUY" if int(pos.get("netqty", 0)) > 0 else "SELL"
            if qty > 0:
                r = self.close_position(symbol, quantity=qty, side=side, strategy_tag=strategy_tag)
                results.append(r)
                logger.info(f"EOD close: {symbol} × {qty}")
        return results

    def check_connection(self) -> bool:
        """Ping OpenAlgo to verify it's running."""
        if self.paper_mode:
            return True
        try:
            with httpx.Client(timeout=3) as client:
                resp = client.get(f"{self.BASE_URL}/")
                return resp.status_code == 200
        except Exception:
            return False
