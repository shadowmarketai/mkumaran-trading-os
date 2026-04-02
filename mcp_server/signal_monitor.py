"""
Signal Auto-Monitor — background task for open MWA signal cards.

Periodically checks live prices against Entry/SL/TGT for all OPEN signals.
When SL or TGT is hit:
  1. Updates Signal status in DB (OPEN → TARGET_HIT / SL_HIT)
  2. Creates Outcome record in DB
  3. Updates Google Sheets via update_signal_status()
  4. Sends Telegram alert

Runs every 5 minutes during market hours, skips when market is closed.
"""

import asyncio
import logging
from datetime import date, datetime

from mcp_server.config import settings

logger = logging.getLogger(__name__)

# Poll interval in seconds (5 minutes)
MONITOR_INTERVAL = 300


def _check_signal_hit(
    direction: str,
    current_price: float,
    entry_price: float,
    stop_loss: float,
    target: float,
) -> str | None:
    """
    Check if a signal's SL or TGT has been hit.

    Returns: "TARGET_HIT", "SL_HIT", or None.
    """
    if direction in ("BUY", "LONG"):
        if current_price >= target:
            return "TARGET_HIT"
        if current_price <= stop_loss:
            return "SL_HIT"
    elif direction in ("SELL", "SHORT"):
        if current_price <= target:
            return "TARGET_HIT"
        if current_price >= stop_loss:
            return "SL_HIT"
    return None


def _calc_pnl(direction: str, entry_price: float, exit_price: float) -> tuple[float, float]:
    """Calculate P&L percentage and absolute amount."""
    if entry_price <= 0:
        return 0.0, 0.0
    if direction in ("BUY", "LONG"):
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        pnl_rs = exit_price - entry_price
    else:
        pnl_pct = (entry_price - exit_price) / entry_price * 100
        pnl_rs = entry_price - exit_price
    return round(pnl_pct, 2), round(pnl_rs, 2)


def monitor_open_signals() -> list[dict]:
    """
    Check all OPEN signals in DB for SL/TGT hit. Returns list of closed signals.

    This is the synchronous core — called by the async loop and also usable
    from the manual /tools/check_signals endpoint.
    """
    from mcp_server.db import SessionLocal
    from mcp_server.models import Signal, Outcome, ActiveTrade

    results: list[dict] = []
    session = SessionLocal()

    try:
        open_signals = session.query(Signal).filter(Signal.status == "OPEN").all()
        if not open_signals:
            return results

        # Fetch live prices for each signal
        from mcp_server.data_provider import get_provider, get_stock_data

        provider = get_provider()

        for sig in open_signals:
            try:
                ticker_raw = sig.ticker or ""
                exchange = sig.exchange or "NSE"

                # Build fetch ticker with exchange prefix if not present
                if ":" in ticker_raw:
                    fetch_ticker = ticker_raw
                else:
                    fetch_ticker = f"{exchange}:{ticker_raw}"

                # Try live LTP first (Goodwill → NSE → Angel), fall back to OHLCV
                ltp = provider.get_ltp(fetch_ticker)
                if ltp and ltp > 0:
                    current_price = ltp
                else:
                    df = get_stock_data(fetch_ticker, period="1d", interval="1d", force_refresh=True)
                    if df is None or df.empty:
                        logger.debug("Monitor: no data for %s", fetch_ticker)
                        continue
                    current_price = float(df["close"].iloc[-1])
                entry_price = float(sig.entry_price or 0)
                stop_loss = float(sig.stop_loss or 0)
                target = float(sig.target or 0)
                direction = sig.direction or "BUY"

                if entry_price <= 0 or stop_loss <= 0 or target <= 0:
                    continue

                hit = _check_signal_hit(direction, current_price, entry_price, stop_loss, target)
                if hit is None:
                    # Update ActiveTrade current price
                    active = session.query(ActiveTrade).filter(
                        ActiveTrade.signal_id == sig.id
                    ).first()
                    if active:
                        active.current_price = current_price
                        active.last_updated = datetime.now()
                    continue

                # ── Signal hit! Update everything ──
                pnl_pct, pnl_rs = _calc_pnl(direction, entry_price, current_price)
                outcome_str = "WIN" if hit == "TARGET_HIT" else "LOSS"
                exit_reason = "TARGET" if hit == "TARGET_HIT" else "STOPLOSS"

                # 1) Update Signal status in DB
                sig.status = hit
                logger.info(
                    "Signal %s (%s) %s at ₹%.2f | P&L: %.2f%%",
                    sig.ticker, direction, hit, current_price, pnl_pct,
                )

                # 2) Create Outcome record
                days_held = (date.today() - sig.signal_date).days if sig.signal_date else 0
                outcome_rec = Outcome(
                    signal_id=sig.id,
                    exit_date=date.today(),
                    exit_price=current_price,
                    outcome=outcome_str,
                    pnl_amount=pnl_rs * (sig.qty or 1),
                    days_held=days_held,
                    exit_reason=exit_reason,
                )
                session.add(outcome_rec)

                # 3) Remove from ActiveTrade
                active = session.query(ActiveTrade).filter(
                    ActiveTrade.signal_id == sig.id
                ).first()
                if active:
                    session.delete(active)

                # 4) Update Google Sheets
                try:
                    from mcp_server.telegram_receiver import get_sheets_tracker
                    tracker = get_sheets_tracker()
                    sheet_signal_id = f"SIG-{sig.signal_date.strftime('%Y%m%d') if sig.signal_date else ''}*"
                    # Use the signal_id pattern or the actual ID
                    tracker.update_signal_status(
                        signal_id=sheet_signal_id,
                        status=hit,
                        exit_price=current_price,
                        notes=f"Auto-closed by monitor | P&L: {pnl_pct}%",
                    )
                except Exception as sheets_err:
                    logger.warning("Sheets update failed for %s: %s", sig.ticker, sheets_err)

                # 5) Update sheets_sync accuracy tab
                try:
                    from mcp_server.sheets_sync import update_accuracy
                    update_accuracy([{
                        "signal_id": sig.id,
                        "ticker": sig.ticker,
                        "exchange": sig.exchange,
                        "asset_class": sig.asset_class,
                        "direction": direction,
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "outcome": outcome_str,
                        "pnl_amount": round(pnl_rs * (sig.qty or 1), 2),
                        "days_held": days_held,
                        "exit_reason": exit_reason,
                    }])
                except Exception as acc_err:
                    logger.debug("Accuracy update skipped: %s", acc_err)

                # 6) Update trade memory
                try:
                    from mcp_server.trade_memory import TradeMemory
                    mem = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
                    mem.update_outcome(
                        signal_id=str(sig.id),
                        outcome=outcome_str,
                        exit_price=current_price,
                    )
                except Exception as mem_err:
                    logger.debug("Trade memory update skipped: %s", mem_err)

                results.append({
                    "signal_id": sig.id,
                    "ticker": sig.ticker,
                    "direction": direction,
                    "status": hit,
                    "entry": entry_price,
                    "exit": current_price,
                    "pnl_pct": pnl_pct,
                    "pnl_rs": pnl_rs,
                    "outcome": outcome_str,
                    "days_held": days_held,
                })

            except Exception as e:
                logger.error("Monitor error for signal %s: %s", sig.ticker, e)

        session.commit()

    except Exception as e:
        logger.error("Signal monitor failed: %s", e)
        session.rollback()
    finally:
        session.close()

    return results


async def _send_close_alert(closed: dict) -> None:
    """Send Telegram alert for a closed signal."""
    from mcp_server.telegram_bot import send_telegram_message

    emoji = "\U0001f7e2" if closed["outcome"] == "WIN" else "\U0001f534"
    sign = "+" if closed["pnl_pct"] >= 0 else ""

    msg = (
        f"{emoji} Signal Closed — {closed['status'].replace('_', ' ')}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Ticker: {closed['ticker']}\n"
        f"Direction: {closed['direction']}\n"
        f"Entry: \u20b9{closed['entry']:.1f} → Exit: \u20b9{closed['exit']:.1f}\n"
        f"P&L: {sign}{closed['pnl_pct']:.1f}% (\u20b9{closed['pnl_rs']:.0f}/share)\n"
        f"Days Held: {closed['days_held']}\n"
        f"Result: {closed['outcome']}"
    )
    await send_telegram_message(msg, force=True)


async def signal_monitor_loop() -> None:
    """
    Background async loop — runs every MONITOR_INTERVAL seconds.
    Checks open signals for SL/TGT hit during market hours.
    """
    logger.info("Signal auto-monitor started (interval=%ds)", MONITOR_INTERVAL)

    while True:
        try:
            await asyncio.sleep(MONITOR_INTERVAL)

            # Only run during market hours
            try:
                from mcp_server.market_calendar import is_market_open
                if not is_market_open("NSE"):
                    logger.debug("Signal monitor: market closed, skipping cycle")
                    continue
            except Exception:
                pass  # If calendar check fails, run anyway

            logger.info("Signal monitor: checking open signals...")
            closed_signals = monitor_open_signals()

            if closed_signals:
                logger.info("Signal monitor: %d signals closed", len(closed_signals))
                for closed in closed_signals:
                    try:
                        await _send_close_alert(closed)
                    except Exception as tg_err:
                        logger.warning("Telegram close alert failed: %s", tg_err)
            else:
                logger.debug("Signal monitor: no signals hit SL/TGT")

        except asyncio.CancelledError:
            logger.info("Signal monitor stopped")
            break
        except Exception as e:
            logger.error("Signal monitor loop error: %s", e)
            # Don't crash the loop — wait and retry
            await asyncio.sleep(60)
