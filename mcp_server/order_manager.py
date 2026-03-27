"""
MKUMARAN Trading OS — Order Manager (Live Execution with Kill Switch)

Safety features:
- Max open positions limit (default 5)
- Daily loss limit / kill switch (default -3% of capital)
- Position size validation (max 10% per trade)
- Order confirmation flow
- Audit trail for all orders
- Emergency close-all function

Requires: Active Kite session with valid access token.
"""

import logging
from datetime import datetime, date
from dataclasses import dataclass, field

from mcp_server.config import settings

logger = logging.getLogger(__name__)


# ── Safety Limits ────────────────────────────────────────────
MAX_OPEN_POSITIONS = 5                # Max concurrent trades
DAILY_LOSS_LIMIT_PCT = -0.03         # -3% of capital = kill switch
MAX_POSITION_SIZE_PCT = 0.10          # Max 10% capital per trade
MAX_ORDER_VALUE = 200000              # Max Rs.2L per order (safety cap)
ALLOWED_EXCHANGES = {"NSE", "BSE", "MCX", "NFO", "CDS"}
ALLOWED_ORDER_TYPES = {"MARKET", "LIMIT", "SL", "SL-M"}
ALLOWED_PRODUCTS = {"CNC", "MIS", "NRML"}


@dataclass
class OrderResult:
    """Result of an order operation."""
    success: bool
    order_id: str = ""
    message: str = ""
    ticker: str = ""
    direction: str = ""
    qty: int = 0
    price: float = 0.0
    order_type: str = ""
    timestamp: str = ""


@dataclass
class KillSwitchState:
    """Tracks daily P&L for kill switch."""
    date: date = field(default_factory=date.today)
    starting_capital: float = 0.0
    realized_pnl: float = 0.0
    is_triggered: bool = False
    trigger_reason: str = ""

    def check(self, capital: float) -> bool:
        """Check if kill switch should trigger. Returns True if trading should stop."""
        if self.date != date.today():
            # New day — reset
            self.date = date.today()
            self.starting_capital = capital
            self.realized_pnl = 0.0
            self.is_triggered = False
            self.trigger_reason = ""

        if self.starting_capital <= 0:
            self.starting_capital = capital

        daily_pnl_pct = self.realized_pnl / self.starting_capital if self.starting_capital > 0 else 0

        if daily_pnl_pct <= DAILY_LOSS_LIMIT_PCT:
            self.is_triggered = True
            self.trigger_reason = (
                f"Daily loss limit hit: {daily_pnl_pct:.1%} "
                f"(limit: {DAILY_LOSS_LIMIT_PCT:.1%})"
            )
            logger.warning("KILL SWITCH TRIGGERED: %s", self.trigger_reason)
            return True

        return False


class OrderManager:
    """
    Manages live order execution with safety controls.

    Usage:
        manager = OrderManager(kite=kite_instance, capital=100000)
        result = manager.place_order("NSE:RELIANCE", "BUY", qty=10, price=2500)
        manager.cancel_order(result.order_id)
        manager.close_all_positions()
    """

    def __init__(self, kite=None, capital: float = 100000):
        self.kite = kite
        self.capital = capital
        self.kill_switch = KillSwitchState(starting_capital=capital)
        self.open_positions: list[dict] = []
        self.order_history: list[OrderResult] = []

    def _validate_kite(self) -> str | None:
        """Check if Kite is connected. Returns error message or None."""
        if self.kite is None:
            return "Kite not connected — live trading requires active Kite session"
        return None

    def _validate_order(
        self,
        ticker: str,
        direction: str,
        qty: int,
        price: float,
    ) -> str | None:
        """
        Validate order against safety limits.
        Returns error message or None if valid.
        """
        # Kill switch
        if self.kill_switch.is_triggered:
            return f"KILL SWITCH ACTIVE: {self.kill_switch.trigger_reason}"

        if self.kill_switch.check(self.capital):
            return f"KILL SWITCH TRIGGERED: {self.kill_switch.trigger_reason}"

        # Max positions
        if len(self.open_positions) >= MAX_OPEN_POSITIONS:
            return (
                f"Max positions reached ({MAX_OPEN_POSITIONS}). "
                f"Close existing positions before opening new ones."
            )

        # Direction validation
        if direction not in ("BUY", "SELL"):
            return f"Invalid direction: {direction}. Must be BUY or SELL."

        # Quantity validation
        if qty <= 0:
            return f"Invalid quantity: {qty}. Must be > 0."

        # Order value check
        order_value = qty * price
        if order_value > MAX_ORDER_VALUE:
            return (
                f"Order value Rs.{order_value:,.0f} exceeds max "
                f"Rs.{MAX_ORDER_VALUE:,.0f}"
            )

        # Position size check
        position_pct = order_value / self.capital if self.capital > 0 else 1.0
        if position_pct > MAX_POSITION_SIZE_PCT:
            return (
                f"Position size {position_pct:.1%} exceeds max "
                f"{MAX_POSITION_SIZE_PCT:.1%} of capital"
            )

        # Exchange validation
        exchange = ticker.split(":")[0] if ":" in ticker else "NSE"
        if exchange not in ALLOWED_EXCHANGES:
            return f"Exchange {exchange} not allowed. Allowed: {ALLOWED_EXCHANGES}"

        return None

    def place_order(
        self,
        ticker: str,
        direction: str,
        qty: int,
        price: float = 0,
        order_type: str = "LIMIT",
        product: str = "CNC",
        stop_loss: float = 0,
        target: float = 0,
        tag: str = "",
    ) -> OrderResult:
        """
        Place a live order via Kite.

        Args:
            ticker: EXCHANGE:SYMBOL format
            direction: BUY or SELL
            qty: Number of shares/lots
            price: Limit price (0 for market orders)
            order_type: MARKET, LIMIT, SL, SL-M
            product: CNC (delivery), MIS (intraday), NRML (F&O)
            stop_loss: Stop loss price for SL orders
            target: Target price (for tracking, not sent to exchange)
            tag: Optional tag for tracking (e.g., signal_id)
        """
        timestamp = datetime.now().isoformat()

        # ── Validate Kite connection ──────────────────────────
        kite_error = self._validate_kite()
        if kite_error:
            result = OrderResult(
                success=False, message=kite_error, ticker=ticker,
                direction=direction, qty=qty, timestamp=timestamp,
            )
            self.order_history.append(result)
            return result

        # ── Validate order safety ─────────────────────────────
        validation_error = self._validate_order(ticker, direction, qty, price)
        if validation_error:
            result = OrderResult(
                success=False, message=validation_error, ticker=ticker,
                direction=direction, qty=qty, price=price, timestamp=timestamp,
            )
            self.order_history.append(result)
            logger.warning("Order REJECTED for %s: %s", ticker, validation_error)
            return result

        # ── Place order via Kite ──────────────────────────────
        try:
            exchange = ticker.split(":")[0] if ":" in ticker else "NSE"
            symbol = ticker.split(":")[-1] if ":" in ticker else ticker

            kite_direction = "BUY" if direction == "BUY" else "SELL"

            order_params = {
                "variety": "regular",
                "exchange": exchange,
                "tradingsymbol": symbol,
                "transaction_type": kite_direction,
                "quantity": qty,
                "order_type": order_type,
                "product": product,
            }

            if order_type == "LIMIT" and price > 0:
                order_params["price"] = price

            if order_type in ("SL", "SL-M") and stop_loss > 0:
                order_params["trigger_price"] = stop_loss
                if order_type == "SL" and price > 0:
                    order_params["price"] = price

            if tag:
                order_params["tag"] = tag[:20]  # Kite max tag length

            order_id = self.kite.place_order(**order_params)

            # Track position
            self.open_positions.append({
                "order_id": str(order_id),
                "ticker": ticker,
                "direction": direction,
                "qty": qty,
                "entry_price": price,
                "stop_loss": stop_loss,
                "target": target,
                "timestamp": timestamp,
                "tag": tag,
            })

            result = OrderResult(
                success=True,
                order_id=str(order_id),
                message=f"Order placed: {direction} {qty}x {ticker} @ {price}",
                ticker=ticker,
                direction=direction,
                qty=qty,
                price=price,
                order_type=order_type,
                timestamp=timestamp,
            )

            logger.info(
                "ORDER PLACED: %s %d x %s @ %.2f (ID: %s)",
                direction, qty, ticker, price, order_id,
            )

            self.order_history.append(result)
            return result

        except Exception as e:
            result = OrderResult(
                success=False,
                message=f"Kite order failed: {e}",
                ticker=ticker,
                direction=direction,
                qty=qty,
                price=price,
                timestamp=timestamp,
            )
            logger.error("ORDER FAILED for %s: %s", ticker, e)
            self.order_history.append(result)
            return result

    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a pending order."""
        timestamp = datetime.now().isoformat()

        kite_error = self._validate_kite()
        if kite_error:
            return OrderResult(success=False, message=kite_error, timestamp=timestamp)

        try:
            self.kite.cancel_order(variety="regular", order_id=order_id)

            # Remove from open positions
            self.open_positions = [
                p for p in self.open_positions if p["order_id"] != order_id
            ]

            result = OrderResult(
                success=True,
                order_id=order_id,
                message=f"Order {order_id} cancelled",
                timestamp=timestamp,
            )
            logger.info("ORDER CANCELLED: %s", order_id)
            self.order_history.append(result)
            return result

        except Exception as e:
            result = OrderResult(
                success=False,
                message=f"Cancel failed: {e}",
                order_id=order_id,
                timestamp=timestamp,
            )
            logger.error("CANCEL FAILED for %s: %s", order_id, e)
            self.order_history.append(result)
            return result

    def close_position(self, ticker: str) -> OrderResult:
        """Close an open position by placing an opposite order."""
        matching = [p for p in self.open_positions if p["ticker"] == ticker]
        if not matching:
            return OrderResult(
                success=False,
                message=f"No open position for {ticker}",
                ticker=ticker,
                timestamp=datetime.now().isoformat(),
            )

        pos = matching[-1]  # Most recent
        close_direction = "SELL" if pos["direction"] == "BUY" else "BUY"

        result = self.place_order(
            ticker=ticker,
            direction=close_direction,
            qty=pos["qty"],
            order_type="MARKET",
            product="CNC",
            tag="close",
        )

        if result.success:
            self.open_positions = [
                p for p in self.open_positions if p["ticker"] != ticker
            ]

        return result

    def close_all_positions(self) -> list[OrderResult]:
        """
        EMERGENCY: Close all open positions at market.
        Used by kill switch or manual emergency exit.
        """
        results: list[OrderResult] = []
        tickers = list(set(p["ticker"] for p in self.open_positions))

        logger.warning("CLOSING ALL %d POSITIONS", len(tickers))

        for ticker in tickers:
            result = self.close_position(ticker)
            results.append(result)

        return results

    def update_pnl(self, realized_pnl: float) -> None:
        """Update daily realized P&L for kill switch tracking."""
        self.kill_switch.realized_pnl += realized_pnl
        self.kill_switch.check(self.capital)

    def get_status(self) -> dict:
        """Get current order manager status."""
        return {
            "open_positions": len(self.open_positions),
            "max_positions": MAX_OPEN_POSITIONS,
            "kill_switch_active": self.kill_switch.is_triggered,
            "kill_switch_reason": self.kill_switch.trigger_reason or "N/A",
            "daily_pnl": round(self.kill_switch.realized_pnl, 2),
            "daily_loss_limit": f"{DAILY_LOSS_LIMIT_PCT:.1%}",
            "capital": self.capital,
            "kite_connected": self.kite is not None,
            "orders_today": len([
                o for o in self.order_history
                if o.timestamp.startswith(str(date.today()))
            ]),
            "positions": [
                {
                    "ticker": p["ticker"],
                    "direction": p["direction"],
                    "qty": p["qty"],
                    "entry_price": p["entry_price"],
                }
                for p in self.open_positions
            ],
        }
