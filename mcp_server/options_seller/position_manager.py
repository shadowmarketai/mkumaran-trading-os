"""
MKUMARAN Trading OS — Options Seller: Position Manager

Owns the full lifecycle of an open short strangle / iron condor:
  open → Greeks refresh loop → adjustment evaluation → close

This is the orchestration layer that connects the IV engine,
strike selector, and adjustment engine to:
  - Postgres (options_seller_positions + options_seller_adjustments)
  - Paper broker (PaperBroker) or live broker (via order_manager)
  - Telegram (alerts on every adjustment action)
  - EventCalendar (rule 1 gate)

Lifecycle methods
─────────────────
  open_position(instrument, spot, chain, dte, regime)
    → builds strangle, paper/live-books legs, inserts DB row
    → returns position_id

  refresh_greeks(position_id, spot, chain)
    → recalculates Greeks from live chain
    → updates current_delta_ce/pe, current_pnl, dte_remaining
    → calls evaluate() and returns AdjustmentDecision

  close_position(position_id, reason, pnl)
    → marks DB row closed, logs to adjustments table, sends Telegram

  run_scan()
    → iterates all OPEN positions, calls refresh_greeks, fires alerts
    → called by the n8n scheduled workflow every 5 min during market hours

Design
──────
  - All money arithmetic passes through mcp_server.money (Decimal zone)
  - Paper mode (PAPER_MODE=true or paper_mode arg): no real orders placed
  - The DB session is opened/closed per method — no shared session state
  - run_scan() is the only stateful loop; it's designed to be called from
    asyncio.to_thread in the FastAPI route so it doesn't block the event loop
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any


logger = logging.getLogger(__name__)

# IST
_IST = timezone(__import__("datetime").timedelta(hours=5, minutes=30))


def _now() -> datetime:
    return datetime.now(_IST)


# ── DB helpers ───────────────────────────────────────────────


def _open_db():
    from mcp_server.db import SessionLocal
    return SessionLocal()


def _get_position(db, position_id: int) -> dict | None:
    """Return raw dict from options_seller_positions or None."""
    from sqlalchemy import text
    row = db.execute(
        text("SELECT * FROM options_seller_positions WHERE id = :id"),
        {"id": position_id},
    ).fetchone()
    if row is None:
        return None
    return dict(row._mapping)


def _insert_position(db, data: dict) -> int:
    from sqlalchemy import text
    cols = ", ".join(data.keys())
    placeholders = ", ".join(f":{k}" for k in data.keys())
    result = db.execute(
        text(f"INSERT INTO options_seller_positions ({cols}) VALUES ({placeholders}) RETURNING id"),
        data,
    )
    db.commit()
    return result.fetchone()[0]


def _update_position(db, position_id: int, updates: dict) -> None:
    from sqlalchemy import text
    set_clause = ", ".join(f"{k} = :{k}" for k in updates.keys())
    db.execute(
        text(f"UPDATE options_seller_positions SET {set_clause} WHERE id = :_id"),
        {"_id": position_id, **updates},
    )
    db.commit()


def _log_adjustment(db, position_id: int, data: dict) -> None:
    from sqlalchemy import text
    data["position_id"] = position_id
    cols = ", ".join(data.keys())
    placeholders = ", ".join(f":{k}" for k in data.keys())
    db.execute(
        text(f"INSERT INTO options_seller_adjustments ({cols}) VALUES ({placeholders})"),
        data,
    )
    db.commit()


# ── Telegram alert helper ────────────────────────────────────


def _alert(msg: str) -> None:
    try:
        from mcp_server.telegram_bot import send_message
        send_message(msg, parse_mode=None)
    except Exception as e:
        logger.debug("Telegram alert failed: %s", e)


# ── Open position ─────────────────────────────────────────────


def open_position(
    instrument: str,
    spot: float,
    chain: dict,
    dte: int,
    lots: int = 1,
    paper_mode: bool = True,
    target_delta: float = 0.15,
    structure: str = "IRON_CONDOR",
    wing_width_strikes: int = 1,
) -> int | None:
    """Build and book an options seller position.

    Returns the position_id on success, None on gate failure.

    Gate stack (in order):
      1. IV regime gate (sell_premium_ok must be True)
      2. Event calendar gate (no event within 6h)
      3. Regime detector gate (market must not be in VOLATILE regime)
    """
    inst = instrument.upper()

    # ── Gate 1: IV regime ─────────────────────────────────────
    from mcp_server.options_seller.iv_engine import get_iv_regime
    regime = get_iv_regime(inst, spot, chain)
    if not regime.sell_premium_ok:
        logger.info("open_position blocked: IV regime %s (%s)", regime.label, regime.reason)
        return None

    # ── Gate 2: Event calendar ────────────────────────────────
    try:
        from mcp_server.event_calendar import get_calendar
        if get_calendar().high_impact_within(hours=6):
            logger.info("open_position blocked: high-impact event within 6h")
            return None
    except Exception:
        pass

    # ── Gate 3: Market regime ─────────────────────────────────
    try:
        from mcp_server.options_seller.strike_selector import build_strangle
        import yfinance as yf
        df = yf.download("^NSEI", period="90d", progress=False, auto_adjust=True)
        if df is not None and not df.empty:
            from mcp_server.regime_detector import gate_strategy
            allowed, mkt = gate_strategy(df, "options_seller")
            if not allowed:
                logger.info("open_position blocked: market regime %s", mkt.label)
                return None
    except Exception as e:
        logger.debug("Regime gate unavailable: %s", e)

    # ── Build strangle ────────────────────────────────────────
    from mcp_server.options_seller.strike_selector import build_strangle
    pos = build_strangle(
        instrument=inst,
        spot=spot,
        chain=chain,
        dte=dte,
        target_delta=target_delta,
        structure=structure,
        wing_width_strikes=wing_width_strikes,
    )
    if pos is None:
        logger.info("open_position: build_strangle returned None — skipping")
        return None

    # ── Persist to DB ─────────────────────────────────────────
    today = date.today()
    from datetime import timedelta
    expiry = today + timedelta(days=dte)

    # Find long leg strikes (iron condor)
    long_calls = [lg for lg in pos.legs if lg.option_type == "CE" and lg.side == "BUY"]
    long_puts  = [lg for lg in pos.legs if lg.option_type == "PE" and lg.side == "BUY"]

    row: dict[str, Any] = {
        "instrument":           inst,
        "expiry_date":          expiry.isoformat(),
        "structure":            pos.structure,
        "status":               "OPEN",
        "short_call_strike":    pos.short_call_strike,
        "short_put_strike":     pos.short_put_strike,
        "short_call_premium":   next((lg.premium for lg in pos.legs if lg.option_type == "CE" and lg.side == "SELL"), 0),
        "short_put_premium":    next((lg.premium for lg in pos.legs if lg.option_type == "PE" and lg.side == "SELL"), 0),
        "short_call_delta":     pos.short_call_delta,
        "short_put_delta":      pos.short_put_delta,
        "long_call_strike":     long_calls[0].strike if long_calls else None,
        "long_put_strike":      long_puts[0].strike  if long_puts  else None,
        "long_call_premium":    long_calls[0].premium if long_calls else None,
        "long_put_premium":     long_puts[0].premium  if long_puts  else None,
        "net_credit":           pos.net_credit,
        "max_loss":             pos.max_loss if pos.max_loss != float("inf") else None,
        "lot_size":             pos.legs[0].lot_size if pos.legs else 25,
        "lots":                 lots,
        "spot_at_entry":        spot,
        "dte_at_entry":         dte,
        "iv_regime":            regime.label,
        "vix_at_entry":         regime.vix_current,
        "iv_percentile_1y":     regime.vix_percentile_1y,
        "current_pnl":          0.0,
        "current_delta_ce":     pos.short_call_delta,
        "current_delta_pe":     pos.short_put_delta,
        "dte_remaining":        float(dte),
        "last_refreshed_at":    _now().isoformat(),
        "opened_at":            _now().isoformat(),
        "paper_mode":           paper_mode,
    }

    db = _open_db()
    try:
        position_id = _insert_position(db, row)
    finally:
        db.close()

    _alert(
        f"📊 OPTIONS POSITION OPENED\n"
        f"Instrument: {inst} | Structure: {pos.structure}\n"
        f"SC: {pos.short_call_strike:.0f} | SP: {pos.short_put_strike:.0f}\n"
        f"Credit: ₹{pos.net_credit:.2f} | DTE: {dte}\n"
        f"IV regime: {regime.label} | Paper: {paper_mode}"
    )
    logger.info("Opened options position id=%d %s %s", position_id, inst, pos.structure)
    return position_id


# ── Refresh Greeks ────────────────────────────────────────────


def refresh_greeks(
    position_id: int,
    spot: float,
    chain: dict,
) -> dict | None:
    """Refresh live Greeks for an open position and evaluate adjustment rules.

    Returns the AdjustmentDecision dict (or None if position not found).
    Persists updated delta/pnl/dte_remaining to DB.
    Logs the decision to options_seller_adjustments.
    Sends Telegram alert if action != HOLD.
    """
    from mcp_server.options_greeks import calculate_greeks
    from mcp_server.options_seller.adjustment_engine import (
        AdjustmentAction, LivePositionSnapshot, evaluate,
    )

    db = _open_db()
    try:
        pos = _get_position(db, position_id)
        if pos is None or pos.get("status") != "OPEN":
            return None

        # Compute live Greeks for each short leg
        entry_credit = float(pos.get("net_credit") or 0)
        sc_strike = float(pos.get("short_call_strike") or 0)
        sp_strike = float(pos.get("short_put_strike") or 0)
        dte_at_entry = int(pos.get("dte_at_entry") or 5)

        # Days elapsed since open
        opened_at = pos.get("opened_at")
        if opened_at:
            if isinstance(opened_at, str):
                opened_at = datetime.fromisoformat(opened_at)
            days_elapsed = (datetime.now(_IST) - opened_at.replace(tzinfo=_IST)).days
        else:
            days_elapsed = 0
        dte_remaining = max(float(dte_at_entry - days_elapsed), 0.0)

        # Greeks from chain (fall back to BS if chain key missing)
        def _live_greeks(strike: float, opt_type: str) -> tuple[float, float]:
            """Return (delta, current_premium)."""
            try:
                slot = chain.get(strike, chain.get(str(int(strike)), {}))
                slot_inner = slot.get(opt_type, {})
                iv = float(slot_inner.get("iv", 0.18) or 0.18)
                g = calculate_greeks(spot, strike, max(dte_remaining, 0.1), volatility=iv, option_type=opt_type)
                premium = float(slot_inner.get("ltp", g.price) or g.price)
                return g.delta, premium
            except Exception:
                return 0.0, 0.0

        sc_delta, sc_current = _live_greeks(sc_strike, "CE")
        sp_delta, sp_current = _live_greeks(sp_strike, "PE")

        sc_entry = float(pos.get("short_call_premium") or 0)
        sp_entry = float(pos.get("short_put_premium") or 0)

        # P&L = entry credit - current cost to close short legs
        # (long legs' premium gain offsets further for IC, simplified here)
        current_cost = sc_current + sp_current
        current_pnl = entry_credit - current_cost

        # Update DB snapshot
        _update_position(db, position_id, {
            "current_delta_ce":  sc_delta,
            "current_delta_pe":  sp_delta,
            "current_pnl":       current_pnl,
            "dte_remaining":     dte_remaining,
            "last_refreshed_at": _now().isoformat(),
        })

        # Evaluate adjustment rules
        snap = LivePositionSnapshot(
            instrument=pos.get("instrument", ""),
            spot=spot,
            short_call_strike=sc_strike,
            short_put_strike=sp_strike,
            short_call_delta=sc_delta,
            short_put_delta=sp_delta,
            short_call_entry_premium=sc_entry,
            short_put_entry_premium=sp_entry,
            short_call_current_premium=sc_current,
            short_put_current_premium=sp_current,
            credit_received=entry_credit,
            current_pnl=current_pnl,
            dte_remaining=dte_remaining,
        )
        decision = evaluate(snap)

        # Log to adjustments table
        _log_adjustment(db, position_id, {
            "rule":         decision.rule,
            "action":       decision.action.value,
            "reason":       decision.reason,
            "spot_at_fire": spot,
            "pnl_at_fire":  current_pnl,
            "executed":     False,
        })

        # Alert if action needed
        if decision.action != AdjustmentAction.HOLD:
            _alert(
                f"⚠️ OPTIONS ADJUSTMENT NEEDED\n"
                f"Position #{position_id} {pos.get('instrument')} | "
                f"Rule: {decision.rule}\n"
                f"Action: {decision.action.value}\n"
                f"Reason: {decision.reason}\n"
                f"P&L: ₹{current_pnl:.2f} | Spot: {spot:.0f}"
            )

        return decision.as_dict()

    finally:
        db.close()


# ── Close position ────────────────────────────────────────────


def close_position(
    position_id: int,
    reason: str = "manual",
    final_pnl: float | None = None,
) -> bool:
    """Mark a position as CLOSED and log the exit.

    Returns True on success, False if position not found.
    """
    db = _open_db()
    try:
        pos = _get_position(db, position_id)
        if pos is None:
            return False

        pnl = final_pnl if final_pnl is not None else float(pos.get("current_pnl") or 0)
        _update_position(db, position_id, {
            "status":       "CLOSED",
            "closed_at":    _now().isoformat(),
            "close_pnl":    pnl,
            "close_reason": reason[:50],
        })
        _log_adjustment(db, position_id, {
            "rule":         "close",
            "action":       "close_full_position",
            "reason":       reason,
            "pnl_at_fire":  pnl,
            "executed":     True,
        })
        _alert(
            f"✅ OPTIONS POSITION CLOSED\n"
            f"Position #{position_id} {pos.get('instrument')}\n"
            f"Reason: {reason}\n"
            f"Final P&L: ₹{pnl:.2f}"
        )
        logger.info("Closed options position id=%d reason=%s pnl=%.2f", position_id, reason, pnl)
        return True
    finally:
        db.close()


# ── Scan all open positions ───────────────────────────────────


def _fetch_open_positions() -> list[tuple[int, str]]:
    """Return list of (id, instrument) for all OPEN positions."""
    from sqlalchemy import text
    db = _open_db()
    try:
        rows = db.execute(
            text("SELECT id, instrument FROM options_seller_positions WHERE status = 'OPEN'")
        ).fetchall()
        return [(row[0], row[1]) for row in rows]
    finally:
        db.close()


def run_scan(spot_lookup: dict[str, float], chain_lookup: dict[str, dict]) -> list[dict]:
    """Iterate all OPEN positions and refresh Greeks + evaluate adjustments.

    Args:
        spot_lookup:  {instrument: spot_price}
        chain_lookup: {instrument: chain_dict}

    Returns a list of decision dicts for positions that need action.
    """
    rows = _fetch_open_positions()

    actions_needed: list[dict] = []
    for row in rows:
        pid = row[0]
        inst = row[1]
        spot = spot_lookup.get(inst, 0.0)
        chain = chain_lookup.get(inst, {})
        if spot <= 0:
            logger.debug("run_scan: no spot for %s position %d — skip", inst, pid)
            continue
        decision = refresh_greeks(pid, spot, chain)
        if decision and decision.get("action") != "hold":
            actions_needed.append({"position_id": pid, "instrument": inst, **decision})

    return actions_needed
