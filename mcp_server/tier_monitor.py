import logging
from datetime import datetime
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def tier2_monitor(db: Session) -> list[dict]:
    """
    Tier 2: Real-time watchlist monitoring (9:15-3:30).

    Checks for:
    - S&R breach
    - Within-2% LTRP entry zone
    - PRRR-CRRR decay
    """
    from mcp_server.models import Watchlist
    from mcp_server.nse_scanner import get_stock_data
    from mcp_server.rrms_engine import RRMSEngine

    engine = RRMSEngine()
    alerts: list[dict] = []

    # Get active Tier 2 watchlist items
    items = db.query(Watchlist).filter(
        Watchlist.tier == 2,
        Watchlist.active.is_(True),
    ).all()

    for item in items:
        try:
            ticker = item.ticker.replace("NSE:", "")
            data = get_stock_data(ticker, period="5d", interval="15m")

            if data.empty:
                continue

            cmp = float(data['close'].iloc[-1])
            ltrp = float(item.ltrp) if item.ltrp else 0
            pivot = float(item.pivot_high) if item.pivot_high else 0

            if ltrp <= 0 or pivot <= 0:
                continue

            # Check within-2% LTRP entry zone
            entry_zone = ltrp * 1.02
            if ltrp <= cmp <= entry_zone:
                result = engine.calculate(item.ticker, cmp, ltrp, pivot)
                if result.is_valid:
                    alerts.append({
                        "type": "ENTRY_ZONE",
                        "ticker": item.ticker,
                        "cmp": cmp,
                        "ltrp": ltrp,
                        "rrr": result.rrr,
                        "qty": result.qty,
                        "timestamp": datetime.now().isoformat(),
                    })

            # Check S&R breach
            if cmp > pivot:
                alerts.append({
                    "type": "RESISTANCE_BREAK",
                    "ticker": item.ticker,
                    "cmp": cmp,
                    "pivot_high": pivot,
                    "timestamp": datetime.now().isoformat(),
                })
            elif cmp < ltrp:
                alerts.append({
                    "type": "SUPPORT_BREAK",
                    "ticker": item.ticker,
                    "cmp": cmp,
                    "ltrp": ltrp,
                    "timestamp": datetime.now().isoformat(),
                })

        except Exception as e:
            logger.error("Tier 2 monitor error for %s: %s", item.ticker, e)

    logger.info("Tier 2 monitor: %d alerts from %d items", len(alerts), len(items))
    return alerts


def tier3_monitor(db: Session) -> list[dict]:
    """
    Tier 3: Active trade monitoring (every 1 min).

    Checks for:
    - Target hit
    - Stop loss hit
    - CRRR deterioration (CRRR < PRRR * 0.5)
    """
    from mcp_server.models import ActiveTrade
    from mcp_server.nse_scanner import get_stock_data

    alerts: list[dict] = []

    trades = db.query(ActiveTrade).all()

    for trade in trades:
        try:
            ticker = trade.ticker.replace("NSE:", "")
            data = get_stock_data(ticker, period="1d", interval="1m")

            if data.empty:
                continue

            cmp = float(data['close'].iloc[-1])

            # Update current price
            trade.current_price = cmp
            trade.last_updated = datetime.now()

            # Calculate current RRR
            risk = cmp - float(trade.stop_loss) if cmp > float(trade.stop_loss) else 0
            reward = float(trade.target) - cmp if cmp < float(trade.target) else 0
            crrr = reward / risk if risk > 0 else 0
            trade.crrr = round(crrr, 2)

            # Check target hit
            if cmp >= float(trade.target):
                alerts.append({
                    "type": "TARGET_HIT",
                    "ticker": trade.ticker,
                    "cmp": cmp,
                    "target": float(trade.target),
                    "pnl_pct": round((cmp - float(trade.entry_price)) / float(trade.entry_price) * 100, 2),
                    "timestamp": datetime.now().isoformat(),
                })

            # Check stop loss hit
            elif cmp <= float(trade.stop_loss):
                alerts.append({
                    "type": "STOPLOSS_HIT",
                    "ticker": trade.ticker,
                    "cmp": cmp,
                    "stop_loss": float(trade.stop_loss),
                    "pnl_pct": round((cmp - float(trade.entry_price)) / float(trade.entry_price) * 100, 2),
                    "timestamp": datetime.now().isoformat(),
                })

            # Check CRRR deterioration
            elif float(trade.prrr) > 0 and crrr < float(trade.prrr) * 0.5:
                if not trade.alert_sent:
                    alerts.append({
                        "type": "DETERIORATING",
                        "ticker": trade.ticker,
                        "cmp": cmp,
                        "prrr": float(trade.prrr),
                        "crrr": round(crrr, 2),
                        "timestamp": datetime.now().isoformat(),
                    })
                    trade.alert_sent = True

        except Exception as e:
            logger.error("Tier 3 monitor error for %s: %s", trade.ticker, e)

    db.commit()
    logger.info("Tier 3 monitor: %d alerts from %d trades", len(alerts), len(trades))
    return alerts


def auto_promote(
    stocks: list[str],
    db: Session,
    source: str = "tier1",
) -> int:
    """
    Auto-promote stocks from Tier 1 scan to Tier 2 watchlist.
    """
    from mcp_server.models import Watchlist

    promoted = 0

    for stock in stocks:
        ticker = f"NSE:{stock}" if not stock.startswith("NSE:") else stock

        # Check if already in watchlist
        existing = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
        if existing:
            continue

        # Add to watchlist as Tier 2
        new_item = Watchlist(
            ticker=ticker,
            tier=2,
            active=True,
            source=source,
            added_by="system",
        )
        db.add(new_item)
        promoted += 1

    if promoted > 0:
        db.commit()
        logger.info("Auto-promoted %d stocks to Tier 2 from %s", promoted, source)

    return promoted
