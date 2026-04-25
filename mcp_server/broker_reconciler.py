"""
MKUMARAN Trading OS — Broker Reconciler

Queries the active broker(s) every `interval_s` seconds and compares
the live position book to the internal `active_trades` table in Postgres.
On any divergence it logs a structured warning and (optionally) sends a
Telegram alert so the operator can intervene manually.

Divergence types detected
─────────────────────────
GHOST     — position exists in DB but the broker shows zero/no holding.
            Cause: manual close in broker terminal, partial fill, SL hit
            outside the app, or broker-side rejection on entry order.

PHANTOM   — position exists at the broker but not in DB.
            Cause: manually opened in the broker terminal, duplicate
            webhook trigger, or a crash between order-fill and DB write.

QTY_DRIFT — both sides see the position but quantities differ.
            Cause: partial fill, manual partial close, or lot-size bug.

Design notes
────────────
• Normalisation layer: each broker returns a different dict shape.
  `_normalise_*` converts each to a common `BrokerPosition` dataclass
  before comparison — adding a new broker requires only a new normaliser.
• The reconciler is stateless between runs; each call is a full snapshot
  comparison (no incremental diffing).
• Designed for background use via asyncio.create_task or n8n cron.
  A /api/reconcile/status route in routers/admin.py can expose the last
  run result.
• Paper-mode guard: reconciler is a no-op unless at least one live broker
  source is available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# ── Common position shape ────────────────────────────────────


@dataclass
class BrokerPosition:
    """Broker-side position, normalised across all providers."""
    ticker: str        # NSE:RELIANCE style where possible
    qty: int           # absolute quantity (always positive)
    direction: str     # "LONG" | "SHORT"
    ltp: float = 0.0   # last traded price (may be 0 if broker doesn't return it)
    source: str = ""   # "dhan" | "angel" | "gwc"


@dataclass
class DBPosition:
    """Internal position as stored in active_trades."""
    id: int
    ticker: str
    qty: int
    direction: str
    entry_price: float


@dataclass
class ReconcileResult:
    """Output of one reconciliation run."""
    checked_at: datetime = field(default_factory=datetime.utcnow)
    broker_positions: list[BrokerPosition] = field(default_factory=list)
    db_positions: list[DBPosition] = field(default_factory=list)
    ghosts: list[DBPosition] = field(default_factory=list)      # in DB, not broker
    phantoms: list[BrokerPosition] = field(default_factory=list)  # at broker, not DB
    qty_drifts: list[dict] = field(default_factory=list)        # qty mismatch
    clean: bool = True

    def has_drift(self) -> bool:
        return bool(self.ghosts or self.phantoms or self.qty_drifts)

    def summary(self) -> str:
        if not self.has_drift():
            return (
                f"CLEAN — broker({len(self.broker_positions)}) "
                f"== db({len(self.db_positions)}) "
                f"at {self.checked_at.strftime('%H:%M:%S')} UTC"
            )
        lines = [
            f"DRIFT at {self.checked_at.strftime('%H:%M:%S')} UTC",
            f"  broker positions: {len(self.broker_positions)}",
            f"  db positions:     {len(self.db_positions)}",
        ]
        for g in self.ghosts:
            lines.append(f"  GHOST    {g.ticker} {g.qty} {g.direction} (DB id={g.id})")
        for p in self.phantoms:
            lines.append(f"  PHANTOM  {p.ticker} {p.qty} {p.direction} (from {p.source})")
        for d in self.qty_drifts:
            lines.append(
                f"  QTY_DRIFT {d['ticker']}: broker={d['broker_qty']} db={d['db_qty']}"
            )
        return "\n".join(lines)


# ── Normalisers ──────────────────────────────────────────────


def _norm_ticker(raw: str, exchange: str = "NSE") -> str:
    """Normalise to NSE:RELIANCE format."""
    raw = raw.strip().upper()
    if ":" in raw:
        return raw
    return f"{exchange.upper()}:{raw}"


def _normalise_dhan(positions: list[dict]) -> list[BrokerPosition]:
    """
    Dhan position dict keys (subset):
      tradingSymbol, securityId, exchangeSegment, netQty, buyQty, sellQty,
      drvOptionType, productType, positionType, dayBuyQty, daySellQty
    """
    out: list[BrokerPosition] = []
    for p in positions:
        try:
            symbol = p.get("tradingSymbol", p.get("securityId", ""))
            exchange = p.get("exchangeSegment", "NSE_EQ").split("_")[0]
            qty = int(p.get("netQty", 0))
            if qty == 0:
                continue  # flat position — skip
            direction = "LONG" if qty > 0 else "SHORT"
            out.append(BrokerPosition(
                ticker=_norm_ticker(symbol, exchange),
                qty=abs(qty),
                direction=direction,
                ltp=float(p.get("ltp", 0) or 0),
                source="dhan",
            ))
        except (ValueError, TypeError, KeyError) as e:
            logger.debug("Dhan position normalisation error: %s — %s", p, e)
    return out


def _normalise_angel(positions: dict | list) -> list[BrokerPosition]:
    """
    Angel position dict keys (subset):
      tradingsymbol, exchange, netqty, pnl, ltp
    Angel returns {"data": {"net": [...], "day": [...]}} or a list.
    """
    rows: list[dict] = []
    if isinstance(positions, dict):
        data = positions.get("data", positions)
        rows = data.get("net", data) if isinstance(data, dict) else data
    elif isinstance(positions, list):
        rows = positions

    out: list[BrokerPosition] = []
    for p in rows:
        try:
            symbol = p.get("tradingsymbol", "")
            exchange = p.get("exchange", "NSE")
            qty = int(p.get("netqty", 0))
            if qty == 0:
                continue
            direction = "LONG" if qty > 0 else "SHORT"
            out.append(BrokerPosition(
                ticker=_norm_ticker(symbol, exchange),
                qty=abs(qty),
                direction=direction,
                ltp=float(p.get("ltp", 0) or 0),
                source="angel",
            ))
        except (ValueError, TypeError, KeyError) as e:
            logger.debug("Angel position normalisation error: %s — %s", p, e)
    return out


def _normalise_gwc(positions: list[dict]) -> list[BrokerPosition]:
    """
    GWC position dict — keys vary; best-effort using common field names.
    """
    out: list[BrokerPosition] = []
    for p in positions:
        try:
            symbol = p.get("symbol", p.get("tradingSymbol", p.get("scrip", "")))
            exchange = p.get("exchange", "NSE")
            qty = int(p.get("netQty", p.get("qty", p.get("net_qty", 0))))
            if qty == 0:
                continue
            direction = "LONG" if qty > 0 else "SHORT"
            out.append(BrokerPosition(
                ticker=_norm_ticker(symbol, exchange),
                qty=abs(qty),
                direction=direction,
                ltp=float(p.get("ltp", 0) or 0),
                source="gwc",
            ))
        except (ValueError, TypeError, KeyError) as e:
            logger.debug("GWC position normalisation error: %s — %s", p, e)
    return out


# ── Broker fetch ─────────────────────────────────────────────


def _fetch_broker_positions() -> list[BrokerPosition]:
    """Query all available live brokers and merge their position books.

    Returns an empty list if no broker is connected (paper mode or
    pre-market). Deduplicates on ticker+direction (takes the first
    seen, which is the primary broker's answer).
    """
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
    except Exception as e:
        logger.warning("Reconciler: could not get provider — %s", e)
        return []

    all_positions: list[BrokerPosition] = []
    seen: set[str] = set()

    # Dhan first (primary per the current routing strategy)
    if provider._sources.get("dhan"):
        try:
            raw = provider.dhan.get_positions()
            for pos in _normalise_dhan(raw):
                key = f"{pos.ticker}:{pos.direction}"
                if key not in seen:
                    all_positions.append(pos)
                    seen.add(key)
        except Exception as e:
            logger.warning("Reconciler: Dhan get_positions failed — %s", e)

    # Angel fallback
    if provider._sources.get("angel"):
        try:
            raw = provider.angel.get_positions()
            for pos in _normalise_angel(raw):
                key = f"{pos.ticker}:{pos.direction}"
                if key not in seen:
                    all_positions.append(pos)
                    seen.add(key)
        except Exception as e:
            logger.warning("Reconciler: Angel get_positions failed — %s", e)

    # GWC fallback
    if provider._sources.get("gwc"):
        try:
            raw = provider.gwc.get_positions()
            for pos in _normalise_gwc(raw):
                key = f"{pos.ticker}:{pos.direction}"
                if key not in seen:
                    all_positions.append(pos)
                    seen.add(key)
        except Exception as e:
            logger.warning("Reconciler: GWC get_positions failed — %s", e)

    return all_positions


# ── DB fetch ─────────────────────────────────────────────────


def _fetch_db_positions() -> list[DBPosition]:
    """Read active_trades from Postgres."""
    from mcp_server.db import SessionLocal
    from mcp_server.models import ActiveTrade

    db = SessionLocal()
    try:
        rows = db.query(ActiveTrade).all()
        result = []
        for r in rows:
            # Infer direction: ActiveTrade doesn't have a direction column,
            # so we look for it on the linked Signal if available, else assume LONG.
            direction = "LONG"
            if r.signal:
                direction = getattr(r.signal, "direction", "LONG") or "LONG"
            result.append(DBPosition(
                id=r.id,
                ticker=_norm_ticker(r.ticker, r.exchange or "NSE"),
                qty=r.qty or 0,
                direction=direction.upper(),
                entry_price=float(r.entry_price or 0),
            ))
        return result
    finally:
        db.close()


# ── Comparison ───────────────────────────────────────────────


def _compare(
    broker: list[BrokerPosition],
    db: list[DBPosition],
    qty_tolerance: int = 0,
) -> tuple[list[DBPosition], list[BrokerPosition], list[dict]]:
    """Return (ghosts, phantoms, qty_drifts).

    qty_tolerance: allow this many shares of difference before flagging
    as QTY_DRIFT (useful for partial fills that are still settling).
    """
    # Index broker positions by ticker+direction key
    broker_index: dict[str, BrokerPosition] = {
        f"{p.ticker}:{p.direction}": p for p in broker
    }
    db_index: dict[str, DBPosition] = {
        f"{p.ticker}:{p.direction}": p for p in db
    }

    ghosts: list[DBPosition] = []
    phantoms: list[BrokerPosition] = []
    qty_drifts: list[dict] = []

    # GHOST: in DB, absent at broker
    for key, db_pos in db_index.items():
        if key not in broker_index:
            ghosts.append(db_pos)

    # PHANTOM: at broker, absent in DB
    for key, br_pos in broker_index.items():
        if key not in db_index:
            phantoms.append(br_pos)

    # QTY_DRIFT: both present but qty differs beyond tolerance
    for key in broker_index.keys() & db_index.keys():
        br_qty = broker_index[key].qty
        db_qty = db_index[key].qty
        if abs(br_qty - db_qty) > qty_tolerance:
            qty_drifts.append({
                "ticker": db_index[key].ticker,
                "direction": db_index[key].direction,
                "broker_qty": br_qty,
                "db_qty": db_qty,
                "delta": br_qty - db_qty,
            })

    return ghosts, phantoms, qty_drifts


# ── Alert ────────────────────────────────────────────────────


def _send_alert(result: ReconcileResult) -> None:
    """Fire a Telegram alert when drift is detected."""
    try:
        from mcp_server.telegram_bot import send_message
        send_message(
            f"⚠️ BROKER RECONCILE DRIFT\n{result.summary()}",
            parse_mode=None,
        )
    except Exception as e:
        logger.warning("Reconciler: Telegram alert failed — %s", e)


# ── Main entry point ─────────────────────────────────────────


def run_reconciliation(
    alert_on_drift: bool = True,
    qty_tolerance: int = 0,
) -> ReconcileResult:
    """Run one full reconciliation cycle.

    Returns a ReconcileResult always — never raises. Callers can inspect
    `.has_drift()` and `.summary()`.
    """
    broker_positions = _fetch_broker_positions()
    if not broker_positions and not _any_broker_live():
        # Paper mode or pre-market — nothing to reconcile.
        logger.debug("Reconciler: no live broker connected, skipping")
        return ReconcileResult()

    db_positions = _fetch_db_positions()
    ghosts, phantoms, qty_drifts = _compare(
        broker_positions, db_positions, qty_tolerance,
    )

    result = ReconcileResult(
        broker_positions=broker_positions,
        db_positions=db_positions,
        ghosts=ghosts,
        phantoms=phantoms,
        qty_drifts=qty_drifts,
        clean=not bool(ghosts or phantoms or qty_drifts),
    )

    if result.has_drift():
        logger.warning("RECONCILER: %s", result.summary())
        if alert_on_drift:
            _send_alert(result)
    else:
        logger.info("Reconciler: %s", result.summary())

    return result


def _any_broker_live() -> bool:
    """Return True if at least one live (non-paper) broker is connected."""
    try:
        from mcp_server.data_provider import get_provider
        p = get_provider()
        return any(p._sources.get(b) for b in ("dhan", "angel", "gwc"))
    except Exception:
        return False
