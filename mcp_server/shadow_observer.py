"""
MKUMARAN Trading OS — Shadow Signal Observer

Records and resolves shadow-mode signal observations.

A shadow signal fires when a strategy runs at weight=0 — it would have
entered a trade but doesn't, because the strategy is in observation mode.
After firing, the observer tracks whether the shadow signal's SL or target
was hit, giving us an unbiased outcome estimate before the strategy goes live.

Two entry points
────────────────
  record_shadow_signal(engine, ticker, shadow_sig, primary_sig_dict, db)
    Called by mwa_signal_generator.py when a shadow engine fires.
    Writes one row to shadow_signal_observations.

  resolve_shadow_signals(db)
    Called by signal_monitor on each cycle (alongside the primary signal
    resolution). Checks current price against unresolved shadow SL/target
    and marks outcome. A 90-day timeout auto-expires if neither is hit.

Query for 30-day evaluation
───────────────────────────
  SELECT
    engine,
    COUNT(*) as total,
    AVG(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as win_rate,
    AVG(pnl_pct) as avg_pnl_pct,
    AVG(CASE WHEN agreed THEN 1 ELSE 0 END) as agreement_rate
  FROM shadow_signal_observations
  WHERE observed_at >= NOW() - INTERVAL '30 days'
    AND outcome IS NOT NULL
  GROUP BY engine;
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
_TIMEOUT_DAYS = 90   # expire unresolved observations after this many days


def _now() -> datetime:
    return datetime.now(_IST)


# ── Record ───────────────────────────────────────────────────


def record_shadow_signal(
    engine: str,
    ticker: str,
    direction: str,
    entry: float,
    sl: float,
    target: float,
    confidence: float,
    primary_direction: str,
    primary_entry: float,
    timeframe: str = "1D",
    exchange: str = "NSE",
    primary_signal_id: int | None = None,
    db=None,
) -> int | None:
    """Write one shadow observation row. Returns the new row id or None on error.

    Caller is responsible for opening and closing the DB session.
    If db is None, opens its own session.
    """
    from mcp_server.models import ShadowSignalObservation

    owns_db = db is None
    if owns_db:
        from mcp_server.db import SessionLocal
        db = SessionLocal()

    try:
        agreed = direction == primary_direction
        obs = ShadowSignalObservation(
            engine=engine,
            ticker=ticker,
            exchange=exchange,
            direction=direction,
            timeframe=timeframe,
            shadow_entry=round(entry, 2),
            shadow_sl=round(sl, 2),
            shadow_target=round(target, 2),
            shadow_confidence=round(confidence, 3),
            primary_direction=primary_direction,
            primary_entry=round(primary_entry, 2),
            agreed=agreed,
            primary_signal_id=primary_signal_id,
            observed_at=_now(),
        )
        db.add(obs)
        db.commit()
        db.refresh(obs)
        logger.info(
            "Shadow %s: %s %s entry=%.2f sl=%.2f tgt=%.2f agreed=%s",
            engine, ticker, direction, entry, sl, target, agreed,
        )
        return obs.id
    except Exception as e:
        logger.warning("Shadow observer record failed for %s %s: %s", engine, ticker, e)
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        if owns_db:
            db.close()


# ── Resolve ──────────────────────────────────────────────────


def resolve_shadow_signals(db=None) -> int:
    """Check all unresolved shadow observations and mark outcomes.

    Returns the number of observations resolved in this call.
    Designed to be called from signal_monitor.check_open_signals()
    on each monitoring cycle.
    """
    from mcp_server.models import ShadowSignalObservation
    from mcp_server.data_provider import get_provider
    from mcp_server.signal_monitor import _check_signal_hit
    from mcp_server.money import to_money

    owns_db = db is None
    if owns_db:
        from mcp_server.db import SessionLocal
        db = SessionLocal()

    resolved_count = 0
    try:
        unresolved = (
            db.query(ShadowSignalObservation)
            .filter(ShadowSignalObservation.resolved_at == None)  # noqa: E711
            .all()
        )
        if not unresolved:
            return 0

        provider = get_provider()
        now = _now()

        for obs in unresolved:
            try:
                # Auto-expire old observations
                age_days = (now - obs.observed_at.replace(tzinfo=_IST)).days
                if age_days > _TIMEOUT_DAYS:
                    obs.resolved_at = now
                    obs.outcome = "EXPIRED"
                    obs.resolution_reason = "TIMEOUT"
                    db.commit()
                    resolved_count += 1
                    continue

                # Fetch current price
                exchange = obs.exchange or "NSE"
                fetch_ticker = (
                    f"{exchange}:{obs.ticker}"
                    if ":" not in (obs.ticker or "")
                    else obs.ticker
                )
                ltp = provider.get_ltp(fetch_ticker)
                if not ltp or ltp <= 0:
                    continue   # no data yet — leave unresolved

                current = to_money(ltp)
                direction = obs.direction or "LONG"
                entry    = to_money(obs.shadow_entry or 0)
                sl       = to_money(obs.shadow_sl or 0)
                target   = to_money(obs.shadow_target or 0)

                if entry <= 0 or sl <= 0 or target <= 0:
                    continue

                hit = _check_signal_hit(direction, current, entry, sl, target)
                if hit is None:
                    continue  # still open

                # Compute pnl_pct
                if direction in ("LONG", "BUY"):
                    pnl_pct = float((current - entry) / entry * 100)
                else:
                    pnl_pct = float((entry - current) / entry * 100)

                obs.resolved_at      = now
                obs.outcome          = "WIN" if hit == "TARGET_HIT" else "LOSS"
                obs.exit_price       = float(current)
                obs.pnl_pct          = round(pnl_pct, 3)
                obs.resolution_reason = "TARGET" if hit == "TARGET_HIT" else "STOPLOSS"
                db.commit()
                resolved_count += 1

                logger.info(
                    "Shadow resolved: %s %s %s → %s pnl=%.2f%%",
                    obs.engine, obs.ticker, obs.direction, obs.outcome, pnl_pct,
                )
            except Exception as row_err:
                logger.debug("Shadow resolve error for obs.id=%s: %s", obs.id, row_err)
                try:
                    db.rollback()
                except Exception:
                    pass

        return resolved_count
    finally:
        if owns_db:
            db.close()
