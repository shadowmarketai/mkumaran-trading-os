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
from datetime import date
from decimal import Decimal

from mcp_server.config import settings
from mcp_server.market_calendar import now_ist
from mcp_server.money import Numeric, round_paise, to_money

logger = logging.getLogger(__name__)

# Poll interval in seconds (5 minutes)
MONITOR_INTERVAL = 300


def _check_signal_hit(
    direction: str,
    current_price: Numeric,
    entry_price: Numeric,
    stop_loss: Numeric,
    target: Numeric,
) -> str | None:
    """
    Check if a signal's SL or TGT has been hit.

    Accepts any Numeric (Decimal from the DB, float from live LTP feeds).
    Pure comparison — no arithmetic — so internal conversion is optional,
    but we do it to keep types predictable for future refactors.

    Returns: "TARGET_HIT", "SL_HIT", or None.
    """
    current = to_money(current_price)
    sl = to_money(stop_loss)
    tgt = to_money(target)
    if direction in ("BUY", "LONG"):
        if current >= tgt:
            return "TARGET_HIT"
        if current <= sl:
            return "SL_HIT"
    elif direction in ("SELL", "SHORT"):
        if current <= tgt:
            return "TARGET_HIT"
        if current >= sl:
            return "SL_HIT"
    return None


def _calc_pnl(
    direction: str, entry_price: Numeric, exit_price: Numeric,
) -> tuple[Decimal, Decimal]:
    """Calculate P&L percentage and absolute amount per share.

    Returns (pnl_pct, pnl_rs) both as Decimal. The caller multiplies
    pnl_rs by qty to get the absolute currency P&L that lands in
    outcomes.pnl_amount (a Numeric column).
    """
    entry = to_money(entry_price)
    exit_p = to_money(exit_price)
    zero = Decimal("0")
    if entry <= 0:
        return zero, zero
    if direction in ("BUY", "LONG"):
        pnl_pct = (exit_p - entry) / entry * 100
        pnl_rs = exit_p - entry
    else:
        pnl_pct = (entry - exit_p) / entry * 100
        pnl_rs = entry - exit_p
    return round_paise(pnl_pct), round_paise(pnl_rs)


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

        # Track tickers already closed THIS cycle to avoid sending
        # duplicate SL/TGT alerts for the same ticker (happens when
        # multiple Signal records exist for the same stock from earlier
        # duplicate generation bugs).
        closed_this_cycle: set[str] = set()

        for sig in open_signals:
            try:
                ticker_raw = sig.ticker or ""
                exchange = sig.exchange or "NSE"

                # Skip if we already closed this ticker this cycle
                dedup_key = f"{ticker_raw}:{sig.direction}"
                if dedup_key in closed_this_cycle:
                    # Silently close the duplicate without sending another alert
                    sig.status = "EXPIRED"
                    session.commit()
                    continue

                # Build fetch ticker with exchange prefix if not present
                if ":" in ticker_raw:
                    fetch_ticker = ticker_raw
                else:
                    fetch_ticker = f"{exchange}:{ticker_raw}"

                # Try live LTP first (Goodwill → NSE → Angel), fall back to OHLCV.
                # Live-feed prices arrive as float; cross into the money zone
                # at the ORM boundary so all downstream math is exact.
                ltp = provider.get_ltp(fetch_ticker)
                if ltp and ltp > 0:
                    current_price = to_money(ltp)
                else:
                    df = get_stock_data(fetch_ticker, period="1d", interval="1d", force_refresh=True)
                    if df is None or df.empty:
                        logger.debug("Monitor: no data for %s", fetch_ticker)
                        continue
                    current_price = to_money(df["close"].iloc[-1])
                entry_price = to_money(sig.entry_price or 0)
                stop_loss = to_money(sig.stop_loss or 0)
                target = to_money(sig.target or 0)
                direction = sig.direction or "BUY"

                if entry_price <= 0 or stop_loss <= 0 or target <= 0:
                    continue

                hit = _check_signal_hit(direction, current_price, entry_price, stop_loss, target)
                if hit is None:
                    # Update ActiveTrade current price (Numeric column, accepts Decimal)
                    active = session.query(ActiveTrade).filter(
                        ActiveTrade.signal_id == sig.id
                    ).first()
                    if active:
                        active.current_price = current_price
                        active.last_updated = now_ist()
                    continue

                # ── Signal hit! Update everything ──
                closed_this_cycle.add(dedup_key)
                pnl_pct, pnl_rs = _calc_pnl(direction, entry_price, current_price)
                outcome_str = "WIN" if hit == "TARGET_HIT" else "LOSS"
                exit_reason = "TARGET" if hit == "TARGET_HIT" else "STOPLOSS"

                # 1) Update Signal status in DB
                sig.status = hit
                logger.info(
                    "Signal %s (%s) %s at ₹%.2f | P&L: %.2f%%",
                    sig.ticker, direction, hit, current_price, pnl_pct,
                )

                # 2) Create Outcome record — pnl_amount is Numeric(10,2),
                # stays exact when we feed a Decimal straight through.
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

                # 2b) For option-enriched signals, re-fetch option LTP for exit P&L.
                # Premium × lot × contracts is money — plan §4 explicitly keeps
                # that aggregation in the Decimal zone while Greeks stay float.
                if getattr(sig, "option_tradingsymbol", None):
                    try:
                        from mcp_server.mcp_server import _get_kite_for_fo
                        kite_client = _get_kite_for_fo()
                        if kite_client:
                            ts = sig.option_tradingsymbol
                            key = f"NFO:{ts}"
                            quote = kite_client.quote([key])
                            exit_premium = to_money(
                                quote.get(key, {}).get("last_price", 0) or 0
                            )
                            if exit_premium > 0:
                                outcome_rec.option_exit_premium = exit_premium
                                entry_prem = to_money(sig.option_premium or 0)
                                lot = int(sig.option_lot_size or 1)
                                if entry_prem > 0:
                                    pnl_per_lot = (exit_premium - entry_prem) * lot
                                    # Credit spreads / SHORT direction = inverted
                                    if getattr(sig, "option_is_spread", False):
                                        pnl_per_lot = -pnl_per_lot
                                    elif direction in ("SELL", "SHORT"):
                                        pnl_per_lot = -pnl_per_lot
                                    outcome_rec.option_pnl_per_lot = round_paise(pnl_per_lot)
                                    outcome_rec.option_pnl_pct = round_paise(
                                        (exit_premium - entry_prem) / entry_prem * 100
                                    )
                    except Exception as opt_err:
                        logger.debug(
                            "Option exit fetch failed for %s: %s", sig.ticker, opt_err
                        )

                # 3) Remove from ActiveTrade
                active = session.query(ActiveTrade).filter(
                    ActiveTrade.signal_id == sig.id
                ).first()
                if active:
                    session.delete(active)

                # 4) Update Google Sheets — match by ticker+date+direction
                # (DB integer `id` does not match sheet's "SIG-YYYYMMDDHHMMSS"
                # string id written by record_signal_to_sheets).
                try:
                    from mcp_server.telegram_receiver import get_sheets_tracker
                    tracker = get_sheets_tracker()
                    signal_date_str = (
                        sig.signal_date.isoformat()
                        if sig.signal_date
                        else date.today().isoformat()
                    )
                    # Sheet layer (gspread) json-serialises values; cast at
                    # the boundary since gspread/google-api-python-client does
                    # not know how to encode Decimal.
                    tracker.update_signal_status_by_match(
                        ticker=sig.ticker,
                        signal_date=signal_date_str,
                        direction=direction,
                        exchange=sig.exchange or "NSE",
                        status=hit,
                        exit_price=float(current_price),
                        notes=f"Auto-closed by monitor | P&L: {pnl_pct}%",
                    )
                except Exception as sheets_err:
                    logger.warning("Sheets update failed for %s: %s", sig.ticker, sheets_err)

                # 5) Update sheets_sync accuracy tab. Cast Decimal→float at the
                # gspread boundary (same reason as update_signal_status_by_match).
                try:
                    from mcp_server.sheets_sync import update_accuracy
                    update_accuracy([{
                        "signal_id": sig.id,
                        "ticker": sig.ticker,
                        "exchange": sig.exchange,
                        "asset_class": sig.asset_class,
                        "direction": direction,
                        "entry_price": float(entry_price),
                        "exit_price": float(current_price),
                        "outcome": outcome_str,
                        "pnl_amount": float(round_paise(pnl_rs * (sig.qty or 1))),
                        "days_held": days_held,
                        "exit_reason": exit_reason,
                    }])
                except Exception as acc_err:
                    logger.debug("Accuracy update skipped: %s", acc_err)

                # 6) Feed outcome to self-learning skill agents
                try:
                    from mcp_server.skill_agents import record_outcome
                    record_outcome(
                        signal_id=sig.id,
                        outcome=outcome_str,
                        scanner_count=sig.scanner_count or 0,
                        confidence=sig.ai_confidence or 0,
                    )
                except Exception as learn_err:
                    logger.debug("Agent learning skipped: %s", learn_err)

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

                # 7) Self-development: run postmortem RCA automatically
                try:
                    from mcp_server.signal_postmortem import run_postmortem
                    pm_result = run_postmortem(sig.id)
                    logger.info(
                        "Postmortem %s for %s: %s",
                        pm_result.get("status"), sig.ticker, pm_result.get("root_cause", "")[:80],
                    )
                except Exception as pm_err:
                    logger.debug("Postmortem skipped for %s: %s", sig.ticker, pm_err)

                # 8) Feed outcome to NeuroLinked brain. The brain HTTP bridge
                # serialises to JSON with fire-and-forget semantics; Decimal →
                # float casts keep the wire payload plain and predictable even
                # if jsonable_encoder is bypassed by a lower-level call.
                try:
                    from mcp_server.brain_bridge import observe_outcome, observe_postmortem
                    observe_outcome(
                        ticker=sig.ticker, direction=direction,
                        outcome=outcome_str, entry=float(entry_price),
                        exit_price=float(current_price), pnl_pct=float(pnl_pct),
                        days_held=days_held, reason=exit_reason,
                    )
                    if pm_result and pm_result.get("root_cause"):
                        observe_postmortem(sig.ticker, outcome_str, pm_result["root_cause"])
                except Exception:
                    pass

                # 9) Invalidate similarity cache so the new trade appears
                try:
                    from mcp_server.signal_similarity import invalidate_cache
                    invalidate_cache()
                except Exception:
                    pass

                # Commit immediately so the next cycle won't re-process
                session.commit()

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
                try:
                    session.rollback()
                except Exception:
                    pass

    except Exception as e:
        logger.error("Signal monitor failed: %s", e)
        session.rollback()
    finally:
        session.close()

    # Resolve shadow-mode observations (runs after primary resolution so
    # the same price-fetch infrastructure is fresh; fail-safe on any error).
    try:
        from mcp_server.shadow_observer import resolve_shadow_signals
        resolved = resolve_shadow_signals()
        if resolved:
            logger.info("Shadow observer: resolved %d observations this cycle", resolved)
    except Exception as shadow_err:
        logger.debug("Shadow observer resolution skipped: %s", shadow_err)

    return results


async def _send_close_alert(closed: dict) -> None:
    """Send Telegram alert for a closed signal, with postmortem RCA if available."""
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

    # Attach option P&L + postmortem RCA if available
    try:
        from mcp_server.db import SessionLocal
        from mcp_server.models import Postmortem, Signal, Outcome
        session = SessionLocal()
        try:
            # Option P&L block — only if this signal was option-enriched
            sig_row = (
                session.query(Signal)
                .filter(Signal.id == closed["signal_id"])
                .first()
            )
            if sig_row and getattr(sig_row, "option_tradingsymbol", None):
                outcome_row = (
                    session.query(Outcome)
                    .filter(Outcome.signal_id == closed["signal_id"])
                    .first()
                )
                if outcome_row and outcome_row.option_exit_premium is not None:
                    entry_prem = float(sig_row.option_premium or 0)
                    exit_prem = float(outcome_row.option_exit_premium or 0)
                    opt_pnl_pct = float(outcome_row.option_pnl_pct or 0)
                    opt_pnl_lot = float(outcome_row.option_pnl_per_lot or 0)
                    pnl_sign = "+" if opt_pnl_pct >= 0 else ""
                    msg += (
                        f"\n\U0001f3af Option: {sig_row.option_tradingsymbol}\n"
                        f"   Entry: \u20b9{entry_prem:.1f} \u2192 Exit: \u20b9{exit_prem:.1f}\n"
                        f"   Option P&L: {pnl_sign}{opt_pnl_pct:.1f}% "
                        f"(\u20b9{opt_pnl_lot:,.0f}/lot)"
                    )

            pm = (
                session.query(Postmortem)
                .filter(Postmortem.signal_id == closed["signal_id"])
                .first()
            )
            if pm and pm.root_cause:
                msg += (
                    f"\n\U0001f50d RCA: {pm.root_cause}"
                )
                if pm.suggested_filter:
                    msg += f"\n\U0001f4a1 Filter: {pm.suggested_filter}"
                if pm.claude_narrative:
                    msg += f"\n\U0001f4dd {pm.claude_narrative[:280]}"
        finally:
            session.close()
    except Exception as e:
        logger.debug("RCA/option attach skipped: %s", e)

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

            # Only run if ANY market is open (NSE/BSE/NFO/MCX/CDS)
            # CDS hours are 09:00-17:00 IST, NSE only 09:15-15:30 — so we
            # cannot gate on NSE alone or forex SL/TP hits get missed.
            try:
                from mcp_server.market_calendar import is_market_open
                any_market_open = any(
                    is_market_open(seg) for seg in ("NSE", "MCX", "CDS")
                )
                if not any_market_open:
                    logger.debug("Signal monitor: all markets closed, skipping cycle")
                    continue
            except Exception:
                pass  # If calendar check fails, run anyway

            logger.info("Signal monitor: checking open signals...")
            # monitor_open_signals() does blocking DB + network calls;
            # run in a worker thread so the event loop stays responsive.
            closed_signals = await asyncio.to_thread(monitor_open_signals)

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
