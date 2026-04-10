"""
MKUMARAN Trading OS — Kite Execution Engine

GTT orders, margin calculator, and order postback handling for Kite Connect v3.

Key features:
- place_gtt_with_entry(): Entry + GTT SL + GTT Target — survives VPS downtime
- check_margin(): Pre-order margin validation
- handle_order_postback(): Process order status updates from WebSocket
"""

import logging
from typing import Any


logger = logging.getLogger(__name__)


# ── Kite Client Helper ───────────────────────────────────────

def _get_kite():
    """Get active Kite Connect client."""
    try:
        from mcp_server.kite_auth import get_kite_client
        kite = get_kite_client()
        if kite is None:
            raise ConnectionError("Kite not connected — run /kitelogin first")
        return kite
    except ImportError:
        raise ConnectionError("kite_auth module not available")


# ── GTT Orders (Good Till Triggered) ─────────────────────────

def place_gtt_with_entry(
    symbol: str,
    exchange: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    target_price: float,
    qty: int,
    product: str = "CNC",
    order_type: str = "LIMIT",
) -> dict[str, Any]:
    """Place entry order + GTT SL + GTT Target simultaneously.

    GTT orders run on Zerodha's server — they survive VPS downtime.
    If your system goes down at 2 PM, your open trades are still protected.

    Args:
        symbol: Trading symbol (e.g., "RELIANCE")
        exchange: NSE, BSE, NFO, MCX, CDS
        direction: BUY or SELL
        entry_price: Limit entry price
        stop_loss: Stop loss trigger price
        target_price: Target trigger price
        qty: Number of shares/lots
        product: CNC (delivery), MIS (intraday), NRML (F&O)
        order_type: LIMIT or MARKET

    Returns:
        Dict with order_id, gtt_sl_id, gtt_target_id
    """
    kite = _get_kite()

    is_buy = direction.upper() in ("BUY", "LONG")
    entry_txn = kite.TRANSACTION_TYPE_BUY if is_buy else kite.TRANSACTION_TYPE_SELL
    exit_txn = kite.TRANSACTION_TYPE_SELL if is_buy else kite.TRANSACTION_TYPE_BUY

    product_map = {
        "CNC": kite.PRODUCT_CNC,
        "MIS": kite.PRODUCT_MIS,
        "NRML": kite.PRODUCT_NRML,
    }
    kite_product = product_map.get(product.upper(), kite.PRODUCT_CNC)

    # 1. Place entry order
    order_params = {
        "variety": kite.VARIETY_REGULAR,
        "exchange": exchange.upper(),
        "tradingsymbol": symbol,
        "transaction_type": entry_txn,
        "quantity": qty,
        "product": kite_product,
        "validity": kite.VALIDITY_DAY,
    }

    if order_type.upper() == "MARKET":
        order_params["order_type"] = kite.ORDER_TYPE_MARKET
    else:
        order_params["order_type"] = kite.ORDER_TYPE_LIMIT
        order_params["price"] = entry_price

    order_id = kite.place_order(**order_params)
    logger.info("Entry order placed: %s %s %s @ %.2f qty=%d → order_id=%s",
                direction, symbol, exchange, entry_price, qty, order_id)

    # 2. Place GTT Stop Loss
    gtt_sl = kite.place_gtt(
        trigger_type=kite.GTT_TYPE_SINGLE,
        tradingsymbol=symbol,
        exchange=exchange.upper(),
        trigger_values=[stop_loss],
        last_price=entry_price,
        orders=[{
            "transaction_type": exit_txn,
            "quantity": qty,
            "order_type": kite.ORDER_TYPE_MARKET,
            "product": kite_product,
            "price": 0,
        }],
    )
    gtt_sl_id = gtt_sl.get("trigger_id", "")
    logger.info("GTT SL placed: %s @ %.2f → trigger_id=%s", symbol, stop_loss, gtt_sl_id)

    # 3. Place GTT Target
    gtt_target = kite.place_gtt(
        trigger_type=kite.GTT_TYPE_SINGLE,
        tradingsymbol=symbol,
        exchange=exchange.upper(),
        trigger_values=[target_price],
        last_price=entry_price,
        orders=[{
            "transaction_type": exit_txn,
            "quantity": qty,
            "order_type": kite.ORDER_TYPE_LIMIT,
            "product": kite_product,
            "price": target_price,
        }],
    )
    gtt_target_id = gtt_target.get("trigger_id", "")
    logger.info("GTT Target placed: %s @ %.2f → trigger_id=%s", symbol, target_price, gtt_target_id)

    return {
        "status": "ok",
        "order_id": order_id,
        "gtt_sl_id": gtt_sl_id,
        "gtt_target_id": gtt_target_id,
        "symbol": symbol,
        "exchange": exchange,
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target": target_price,
        "qty": qty,
        "product": product,
    }


def cancel_gtt(trigger_id: int) -> dict:
    """Cancel a GTT order by trigger ID."""
    kite = _get_kite()
    kite.delete_gtt(trigger_id)
    logger.info("GTT cancelled: trigger_id=%s", trigger_id)
    return {"status": "cancelled", "trigger_id": trigger_id}


def list_gtt_orders() -> list[dict]:
    """List all active GTT orders."""
    kite = _get_kite()
    gtts = kite.get_gtts()
    return [
        {
            "id": g["id"],
            "symbol": g["condition"]["tradingsymbol"],
            "exchange": g["condition"]["exchange"],
            "trigger_values": g["condition"]["trigger_values"],
            "status": g["status"],
            "created_at": g["created_at"],
            "orders": g["orders"],
        }
        for g in gtts
    ]


# ── Margin Calculator ────────────────────────────────────────

def check_margin(
    symbol: str,
    exchange: str,
    direction: str,
    qty: int,
    price: float,
    product: str = "CNC",
) -> dict[str, Any]:
    """Check if sufficient margin exists before placing an order.

    Returns:
        Dict with sufficient (bool), required, available, shortfall
    """
    kite = _get_kite()

    is_buy = direction.upper() in ("BUY", "LONG")
    txn_type = "BUY" if is_buy else "SELL"

    # Get order margin requirement
    margin_response = kite.order_margins([{
        "exchange": exchange.upper(),
        "tradingsymbol": symbol,
        "transaction_type": txn_type,
        "variety": "regular",
        "product": product.upper(),
        "order_type": "LIMIT",
        "quantity": qty,
        "price": price,
    }])

    required = margin_response[0]["total"]["total"] if margin_response else 0

    # Get available balance
    margins = kite.margins()
    segment = "commodity" if exchange.upper() == "MCX" else "equity"
    available = margins.get(segment, {}).get("available", {}).get("live_balance", 0)

    shortfall = max(0, required - available)
    sufficient = available >= required

    result = {
        "sufficient": sufficient,
        "required": round(required, 2),
        "available": round(available, 2),
        "shortfall": round(shortfall, 2),
        "symbol": symbol,
        "exchange": exchange,
        "qty": qty,
        "price": price,
        "product": product,
    }

    if not sufficient:
        logger.warning("Insufficient margin for %s %s: need ₹%.2f, have ₹%.2f (short ₹%.2f)",
                       direction, symbol, required, available, shortfall)

    return result


# ── Order Postback Handler ───────────────────────────────────

async def handle_order_postback(order_data: dict) -> dict:
    """Process order status update from Kite WebSocket postback.

    Called when the WebSocket receives a text message with type="order".
    Sends Telegram notification and updates internal state.

    Args:
        order_data: Order dict from Kite postback

    Returns:
        Dict with action taken
    """
    status = order_data.get("status", "")
    symbol = order_data.get("tradingsymbol", "")
    exchange = order_data.get("exchange", "")
    qty = order_data.get("quantity", 0)
    avg_price = order_data.get("average_price", 0)
    txn_type = order_data.get("transaction_type", "")
    order_id = order_data.get("order_id", "")
    status_msg = order_data.get("status_message", "")

    logger.info("Order postback: %s %s %s qty=%d price=%.2f status=%s",
                txn_type, symbol, exchange, qty, avg_price, status)

    # Build Telegram notification
    msg = ""
    if status == "COMPLETE":
        emoji = "\u2705"
        msg = (
            f"{emoji} ORDER FILLED\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"{txn_type} {symbol} ({exchange})\n"
            f"Qty: {qty} @ \u20b9{avg_price:,.2f}\n"
            f"Order ID: {order_id}"
        )
    elif status == "REJECTED":
        emoji = "\u274c"
        msg = (
            f"{emoji} ORDER REJECTED\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"{txn_type} {symbol} ({exchange})\n"
            f"Qty: {qty} @ \u20b9{avg_price:,.2f}\n"
            f"Reason: {status_msg}\n"
            f"Order ID: {order_id}"
        )
    elif status == "CANCELLED":
        msg = (
            f"\u26a0\ufe0f ORDER CANCELLED\n"
            f"{txn_type} {symbol} qty={qty}\n"
            f"Order ID: {order_id}"
        )

    # Send Telegram alert
    if msg:
        try:
            from mcp_server.telegram_bot import send_telegram_message
            import asyncio
            asyncio.ensure_future(send_telegram_message(msg, exchange=exchange, force=True))
        except Exception as e:
            logger.warning("Failed to send order postback to Telegram: %s", e)

    return {
        "processed": True,
        "status": status,
        "symbol": symbol,
        "order_id": order_id,
    }


# ── Safe Order Placement (Margin Check + GTT) ────────────────

def place_safe_order(
    symbol: str,
    exchange: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    target_price: float,
    qty: int,
    product: str = "CNC",
) -> dict[str, Any]:
    """Place order with margin check + GTT protection.

    This is the recommended way to execute trades:
    1. Check margin
    2. Place entry order
    3. Place GTT SL + Target

    Returns error if insufficient margin.
    """
    # Step 1: Margin check
    margin = check_margin(symbol, exchange, direction, qty, entry_price, product)
    if not margin["sufficient"]:
        return {
            "status": "error",
            "reason": "insufficient_margin",
            "required": margin["required"],
            "available": margin["available"],
            "shortfall": margin["shortfall"],
        }

    # Step 2: Place entry + GTT
    try:
        result = place_gtt_with_entry(
            symbol=symbol,
            exchange=exchange,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            qty=qty,
            product=product,
        )
        result["margin_used"] = margin["required"]
        result["margin_remaining"] = margin["available"] - margin["required"]
        return result
    except Exception as e:
        logger.error("Order placement failed: %s", e)
        return {"status": "error", "reason": str(e)}
