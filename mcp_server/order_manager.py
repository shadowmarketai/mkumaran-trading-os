"""
MKUMARAN Trading OS — Order Manager (Live Execution with Kill Switch)

Safety features:
- Max open positions limit (default 5)
- Daily loss limit / kill switch (default -3% of capital)
- Position size validation (max 10% per trade)
- Trailing stop loss with configurable trail percentage
- Partial profit booking (exit N% of position at milestones)
- Order confirmation flow
- Audit trail for all orders
- Emergency close-all function

Requires: Active Kite session with valid access token.
"""

import logging
from datetime import datetime, date
from dataclasses import dataclass, field

from mcp_server.market_calendar import validate_order_timing
from mcp_server.portfolio_risk import validate_portfolio_risk

logger = logging.getLogger(__name__)


# ── Safety Limits ────────────────────────────────────────────
MAX_OPEN_POSITIONS = 5                # Max concurrent trades
DAILY_LOSS_LIMIT_PCT = -0.03         # -3% of capital = kill switch
MAX_POSITION_SIZE_PCT = 0.10          # Max 10% capital per trade
MAX_ORDER_VALUE = 200000              # Max Rs.2L per order (safety cap)
ALLOWED_EXCHANGES = {"NSE", "BSE", "MCX", "NFO", "CDS"}
ALLOWED_ORDER_TYPES = {"MARKET", "LIMIT", "SL", "SL-M"}
ALLOWED_PRODUCTS = {"CNC", "MIS", "NRML"}

# ── Trailing SL Defaults ────────────────────────────────────
DEFAULT_TRAIL_PCT = 0.02              # 2% trailing distance
DEFAULT_TRAIL_ACTIVATION_PCT = 0.03   # Activate trailing after 3% profit


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

    def __init__(self, kite=None, broker=None, capital: float = 100000, paper_mode: bool = False):
        self.kite = kite
        self.broker = broker  # Angel or other broker with place_order/cancel_order
        self.capital = capital
        self.paper_mode = paper_mode
        self.kill_switch = KillSwitchState(starting_capital=capital)
        self.open_positions: list[dict] = []
        self.order_history: list[OrderResult] = []
        self._paper_order_counter: int = 0

        if self.paper_mode:
            logger.info("OrderManager initialized in PAPER MODE (capital=%.0f)", capital)

    def _validate_broker(self) -> str | None:
        """Check if any broker (Kite or Angel) is connected. Returns error message or None."""
        if self.paper_mode:
            return None
        if self.kite is not None:
            return None
        if self.broker is not None:
            return None
        return "No broker connected — live trading requires active Kite or Angel session"

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

        # Market hours validation
        timing_error = validate_order_timing(exchange)
        if timing_error:
            return timing_error

        # Portfolio risk check (sector + asset class concentration)
        order_value = qty * price if price > 0 else 0
        if order_value > 0:
            risk_error = validate_portfolio_risk(
                self.open_positions, ticker, order_value, self.capital,
            )
            if risk_error:
                return risk_error

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

        # ── Validate broker connection ────────────────────────
        kite_error = self._validate_broker()
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

        # ── Paper mode: simulate order ──────────────────────
        if self.paper_mode:
            self._paper_order_counter += 1
            order_id = f"PAPER-{self._paper_order_counter:06d}"

            self.open_positions.append({
                "order_id": order_id,
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
                order_id=order_id,
                message=f"[PAPER] Order placed: {direction} {qty}x {ticker} @ {price}",
                ticker=ticker,
                direction=direction,
                qty=qty,
                price=price,
                order_type=order_type,
                timestamp=timestamp,
            )

            logger.info(
                "PAPER ORDER: %s %d x %s @ %.2f (ID: %s)",
                direction, qty, ticker, price, order_id,
            )

            self.order_history.append(result)
            return result

        # ── Place order via Angel (if Angel broker attached) ──
        exchange = ticker.split(":")[0] if ":" in ticker else "NSE"
        symbol = ticker.split(":")[-1] if ":" in ticker else ticker

        if self.broker is not None and self.kite is None:
            try:
                trigger = stop_loss if order_type in ("SL", "SL-M") else 0
                resp = self.broker.place_order(
                    exchange=exchange,
                    symbol=symbol,
                    action=direction,
                    qty=qty,
                    price=price,
                    order_type=order_type,
                    product=product,
                    trigger_price=trigger,
                )

                if resp.get("success"):
                    angel_order_id = str(resp.get("order_id", ""))
                    self.open_positions.append({
                        "order_id": angel_order_id,
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
                        order_id=angel_order_id,
                        message=f"Order placed via Angel: {direction} {qty}x {ticker} @ {price}",
                        ticker=ticker,
                        direction=direction,
                        qty=qty,
                        price=price,
                        order_type=order_type,
                        timestamp=timestamp,
                    )
                    logger.info(
                        "ANGEL ORDER PLACED: %s %d x %s @ %.2f (ID: %s)",
                        direction, qty, ticker, price, angel_order_id,
                    )
                    self.order_history.append(result)
                    return result
                else:
                    result = OrderResult(
                        success=False,
                        message=resp.get("message", "Angel order failed"),
                        ticker=ticker,
                        direction=direction,
                        qty=qty,
                        price=price,
                        timestamp=timestamp,
                    )
                    self.order_history.append(result)
                    return result

            except Exception as e:
                result = OrderResult(
                    success=False,
                    message=f"Angel order failed: {e}",
                    ticker=ticker,
                    direction=direction,
                    qty=qty,
                    price=price,
                    timestamp=timestamp,
                )
                logger.error("ANGEL ORDER FAILED for %s: %s", ticker, e)
                self.order_history.append(result)
                return result

        # ── Place order via Kite ──────────────────────────────
        try:
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

        # Paper mode: just remove from positions
        if self.paper_mode:
            before = len(self.open_positions)
            self.open_positions = [
                p for p in self.open_positions if p["order_id"] != order_id
            ]
            if len(self.open_positions) == before:
                return OrderResult(
                    success=False, message=f"Paper order {order_id} not found",
                    order_id=order_id, timestamp=timestamp,
                )
            result = OrderResult(
                success=True, order_id=order_id,
                message=f"[PAPER] Order {order_id} cancelled", timestamp=timestamp,
            )
            logger.info("PAPER ORDER CANCELLED: %s", order_id)
            self.order_history.append(result)
            return result

        broker_error = self._validate_broker()
        if broker_error:
            return OrderResult(success=False, message=broker_error, timestamp=timestamp)

        # ── Cancel via Angel ──────────────────────────────────
        if self.broker is not None and self.kite is None:
            try:
                resp = self.broker.cancel_order(order_id)
                if resp.get("success"):
                    self.open_positions = [
                        p for p in self.open_positions if p["order_id"] != order_id
                    ]
                    result = OrderResult(
                        success=True, order_id=order_id,
                        message=f"Angel order {order_id} cancelled", timestamp=timestamp,
                    )
                    logger.info("ANGEL ORDER CANCELLED: %s", order_id)
                    self.order_history.append(result)
                    return result
                return OrderResult(
                    success=False, message=resp.get("message", "Angel cancel failed"),
                    order_id=order_id, timestamp=timestamp,
                )
            except Exception as e:
                return OrderResult(
                    success=False, message=f"Angel cancel failed: {e}",
                    order_id=order_id, timestamp=timestamp,
                )

        # ── Cancel via Kite ───────────────────────────────────
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

    # ── Trailing Stop Loss ──────────────────────────────────────

    def update_trailing_sl(
        self,
        ticker: str,
        current_price: float,
        trail_pct: float = DEFAULT_TRAIL_PCT,
        activation_pct: float = DEFAULT_TRAIL_ACTIVATION_PCT,
    ) -> dict:
        """
        Update trailing stop loss for an open position.

        The trailing SL activates only after the position reaches
        activation_pct profit. Once active, the SL moves up (for LONG)
        or down (for SHORT) as price moves favorably, but never moves
        against the favorable direction.

        Returns dict with: updated (bool), new_sl, old_sl, triggered (bool)
        """
        matching = [p for p in self.open_positions if p["ticker"] == ticker]
        if not matching:
            return {"updated": False, "message": f"No open position for {ticker}"}

        pos = matching[-1]
        entry = pos["entry_price"]
        old_sl = pos.get("stop_loss", 0)
        direction = pos["direction"]
        is_long = direction == "BUY"

        # Calculate profit percentage
        if entry <= 0:
            return {"updated": False, "message": "Invalid entry price"}

        if is_long:
            profit_pct = (current_price - entry) / entry
        else:
            profit_pct = (entry - current_price) / entry

        # Check if trailing SL should activate
        if profit_pct < activation_pct:
            return {
                "updated": False,
                "message": f"Trail not active yet — profit {profit_pct:.1%} < activation {activation_pct:.1%}",
                "profit_pct": round(profit_pct * 100, 2),
                "old_sl": old_sl,
            }

        # Calculate new trailing SL
        if is_long:
            new_sl = current_price * (1 - trail_pct)
            # Only move SL up, never down
            if new_sl > old_sl:
                pos["stop_loss"] = round(new_sl, 2)
                pos["trail_active"] = True
                logger.info(
                    "TRAILING SL updated for %s: %.2f → %.2f (price=%.2f, profit=%.1f%%)",
                    ticker, old_sl, new_sl, current_price, profit_pct * 100,
                )
                return {
                    "updated": True,
                    "old_sl": old_sl,
                    "new_sl": round(new_sl, 2),
                    "profit_pct": round(profit_pct * 100, 2),
                    "triggered": False,
                }
        else:
            new_sl = current_price * (1 + trail_pct)
            # Only move SL down for SHORT, never up
            if old_sl == 0 or new_sl < old_sl:
                pos["stop_loss"] = round(new_sl, 2)
                pos["trail_active"] = True
                logger.info(
                    "TRAILING SL updated for %s (SHORT): %.2f → %.2f (price=%.2f, profit=%.1f%%)",
                    ticker, old_sl, new_sl, current_price, profit_pct * 100,
                )
                return {
                    "updated": True,
                    "old_sl": old_sl,
                    "new_sl": round(new_sl, 2),
                    "profit_pct": round(profit_pct * 100, 2),
                    "triggered": False,
                }

        return {
            "updated": False,
            "message": "Trail SL not moved — current SL already tighter",
            "old_sl": old_sl,
            "new_sl": round(new_sl, 2) if 'new_sl' in dir() else old_sl,
            "profit_pct": round(profit_pct * 100, 2),
        }

    def check_sl_hit(self, ticker: str, current_price: float) -> dict:
        """
        Check if stop loss has been hit for a position.

        Returns dict with: hit (bool), action (CLOSE/HOLD), details
        """
        matching = [p for p in self.open_positions if p["ticker"] == ticker]
        if not matching:
            return {"hit": False, "message": f"No open position for {ticker}"}

        pos = matching[-1]
        sl = pos.get("stop_loss", 0)
        if sl <= 0:
            return {"hit": False, "message": "No stop loss set"}

        is_long = pos["direction"] == "BUY"

        if is_long and current_price <= sl:
            return {
                "hit": True,
                "action": "CLOSE",
                "ticker": ticker,
                "sl": sl,
                "current_price": current_price,
                "trail_active": pos.get("trail_active", False),
            }
        elif not is_long and current_price >= sl:
            return {
                "hit": True,
                "action": "CLOSE",
                "ticker": ticker,
                "sl": sl,
                "current_price": current_price,
                "trail_active": pos.get("trail_active", False),
            }

        return {"hit": False, "action": "HOLD", "sl": sl, "current_price": current_price}

    # ── Partial Profit Booking ───────────────────────────────

    def partial_exit(
        self,
        ticker: str,
        exit_pct: float = 0.50,
    ) -> OrderResult:
        """
        Exit a percentage of an open position for partial profit booking.

        Args:
            ticker: EXCHANGE:SYMBOL format
            exit_pct: Fraction to exit (0.25 = 25%, 0.50 = 50%)

        Returns OrderResult for the partial exit order.
        """
        if exit_pct <= 0 or exit_pct >= 1.0:
            return OrderResult(
                success=False,
                message=f"exit_pct must be between 0 and 1, got {exit_pct}",
                ticker=ticker,
                timestamp=datetime.now().isoformat(),
            )

        matching = [p for p in self.open_positions if p["ticker"] == ticker]
        if not matching:
            return OrderResult(
                success=False,
                message=f"No open position for {ticker}",
                ticker=ticker,
                timestamp=datetime.now().isoformat(),
            )

        pos = matching[-1]
        original_qty = pos["qty"]
        exit_qty = max(1, int(original_qty * exit_pct))

        if exit_qty >= original_qty:
            # Don't allow full exit via partial — use close_position instead
            return OrderResult(
                success=False,
                message=f"Partial exit qty ({exit_qty}) >= total ({original_qty}). Use close_position instead.",
                ticker=ticker,
                timestamp=datetime.now().isoformat(),
            )

        close_direction = "SELL" if pos["direction"] == "BUY" else "BUY"

        result = self.place_order(
            ticker=ticker,
            direction=close_direction,
            qty=exit_qty,
            order_type="MARKET",
            product="CNC",
            tag="partial",
        )

        if result.success:
            # Reduce position qty
            pos["qty"] = original_qty - exit_qty
            pos["partial_exits"] = pos.get("partial_exits", 0) + 1
            logger.info(
                "PARTIAL EXIT: %s — sold %d of %d (%.0f%%), remaining %d",
                ticker, exit_qty, original_qty, exit_pct * 100, pos["qty"],
            )

        return result

    # ── Smart Exit Strategy ──────────────────────────────────

    def evaluate_exit_strategy(
        self,
        ticker: str,
        current_price: float,
    ) -> dict:
        """
        Evaluate whether to take partial profit, trail SL, or hold.

        Returns recommended action based on profit milestones:
        - 0-3%: HOLD (let trail activate)
        - 3-5%: TRAIL active, consider 25% partial at +5%
        - 5-8%: Book 50% profit, trail rest
        - 8%+: Book 25% more, tight trail on remainder
        """
        matching = [p for p in self.open_positions if p["ticker"] == ticker]
        if not matching:
            return {"action": "NONE", "message": f"No position for {ticker}"}

        pos = matching[-1]
        entry = pos["entry_price"]
        if entry <= 0:
            return {"action": "HOLD", "message": "Invalid entry price"}

        is_long = pos["direction"] == "BUY"
        if is_long:
            profit_pct = (current_price - entry) / entry * 100
        else:
            profit_pct = (entry - current_price) / entry * 100

        partials_done = pos.get("partial_exits", 0)

        if profit_pct < 0:
            return {
                "action": "HOLD",
                "profit_pct": round(profit_pct, 2),
                "message": "Position in loss — hold, SL protects",
            }
        elif profit_pct < 3:
            return {
                "action": "HOLD",
                "profit_pct": round(profit_pct, 2),
                "message": "Below trail activation — hold",
            }
        elif profit_pct < 5:
            return {
                "action": "TRAIL",
                "profit_pct": round(profit_pct, 2),
                "suggested_trail_pct": 0.02,
                "message": "Trail activated — tighten SL",
            }
        elif profit_pct < 8 and partials_done == 0:
            return {
                "action": "PARTIAL_50",
                "profit_pct": round(profit_pct, 2),
                "suggested_exit_pct": 0.50,
                "message": "Book 50% profit, trail remainder with 1.5% trail",
                "suggested_trail_pct": 0.015,
            }
        elif profit_pct >= 8 and partials_done <= 1:
            return {
                "action": "PARTIAL_25",
                "profit_pct": round(profit_pct, 2),
                "suggested_exit_pct": 0.25 if partials_done == 1 else 0.50,
                "message": "Book more profit, tight 1% trail on remainder",
                "suggested_trail_pct": 0.01,
            }
        else:
            return {
                "action": "TRAIL_TIGHT",
                "profit_pct": round(profit_pct, 2),
                "suggested_trail_pct": 0.01,
                "message": f"Profit {profit_pct:.1f}% — tight trail, let it run",
            }

    # ── Status ───────────────────────────────────────────────

    def get_status(self) -> dict:
        """Get current order manager status."""
        return {
            "paper_mode": self.paper_mode,
            "open_positions": len(self.open_positions),
            "max_positions": MAX_OPEN_POSITIONS,
            "kill_switch_active": self.kill_switch.is_triggered,
            "kill_switch_reason": self.kill_switch.trigger_reason or "N/A",
            "daily_pnl": round(self.kill_switch.realized_pnl, 2),
            "daily_loss_limit": f"{DAILY_LOSS_LIMIT_PCT:.1%}",
            "capital": self.capital,
            "kite_connected": self.kite is not None,
            "angel_connected": self.broker is not None,
            "orders_today": len([
                o for o in self.order_history
                if o.timestamp.startswith(str(date.today()))
            ]),
            "positions": [
                {
                    "order_id": p.get("order_id", ""),
                    "ticker": p["ticker"],
                    "direction": p["direction"],
                    "qty": p["qty"],
                    "entry_price": p["entry_price"],
                    "stop_loss": p.get("stop_loss", 0),
                    "trail_active": p.get("trail_active", False),
                    "partial_exits": p.get("partial_exits", 0),
                }
                for p in self.open_positions
            ],
        }
