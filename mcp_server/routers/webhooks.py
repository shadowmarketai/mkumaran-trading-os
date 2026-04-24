"""Webhook receivers — TradingView alerts + Telegram message ingress.

Extracted from mcp_server.mcp_server in Phase 1b of the router split.
Both handlers moved verbatim. Rate-limiting via the shared `limiter`
singleton (mcp_server.routers.deps).
"""
from datetime import date

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import desc

from mcp_server.asset_registry import get_asset_class
from mcp_server.config import settings
from mcp_server.db import SessionLocal
from mcp_server.models import MWAScore
from mcp_server.routers.deps import limiter

import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


# ── Telegram webhook (n8n forwards Telegram messages here) ──────────


@router.post("/api/telegram_webhook")
async def api_telegram_webhook(payload: dict):
    """
    Webhook for Telegram messages (alternative to polling).

    n8n can forward Telegram messages here for processing.
    """
    from mcp_server.telegram_receiver import parse_signal_message, record_signal_to_sheets

    text = payload.get("message", {}).get("text", "")
    if not text:
        text = payload.get("text", "")

    signal = parse_signal_message(text)
    if signal is None:
        return {"parsed": False, "message": "Not a valid signal"}

    from dataclasses import asdict
    result = record_signal_to_sheets(asdict(signal))
    return {"parsed": True, **result}


# ── TradingView webhook (Pine Script RRMS alerts) ───────────────────


class TVWebhookPayload(BaseModel):
    ticker: str
    direction: str = "LONG"
    entry: float = 0
    sl: float = 0
    target: float = 0
    rrr: float = 0
    qty: int = 0
    timeframe: str = "1D"
    source: str = "tradingview"


@router.post("/api/tv_webhook")
@limiter.limit("60/minute")
async def api_tv_webhook(request: Request, payload: TVWebhookPayload):
    """
    TradingView webhook receiver.

    Pine Script sends alerts here when RRMS conditions trigger.
    Flow: TV Alert -> Validate -> Record -> Telegram notification
    """
    # Normalize ticker format
    ticker = payload.ticker
    if ":" not in ticker:
        ticker = f"NSE:{ticker}"

    direction = "LONG" if payload.direction.upper() in ("LONG", "BUY") else "SHORT"

    # Auto-calculate RRR if not provided but entry/sl/target are
    rrr = payload.rrr
    if rrr == 0 and payload.entry > 0 and payload.sl > 0 and payload.target > 0:
        risk = abs(payload.entry - payload.sl)
        reward = abs(payload.target - payload.entry)
        rrr = round(reward / risk, 2) if risk > 0 else 0

    # Step 0: Gather live market context for validation
    mwa_direction = "UNKNOWN"
    scanner_count = 0
    fii_net = 0.0
    sector_strength = "NEUTRAL"
    delivery_pct = 0.0
    confidence_boosts = ["TV Signal (+5%)"]
    pre_confidence = 55

    try:
        db_session = SessionLocal()
        latest_mwa = db_session.query(MWAScore).order_by(desc(MWAScore.score_date)).first()
        if latest_mwa:
            mwa_direction = latest_mwa.direction or "UNKNOWN"
            fii_net = float(latest_mwa.fii_net or 0)
            scanner_results = latest_mwa.scanner_results or {}
            plain_ticker = ticker.split(":")[-1] if ":" in ticker else ticker
            scanner_count = sum(
                1 for v in scanner_results.values()
                if isinstance(v, list) and plain_ticker in v
            )
            if mwa_direction in ("BULL", "MILD_BULL") and direction == "LONG":
                confidence_boosts.append(f"MWA {mwa_direction} (+10%)")
                pre_confidence += 10
            elif mwa_direction in ("BEAR", "MILD_BEAR") and direction == "SHORT":
                confidence_boosts.append(f"MWA {mwa_direction} (+10%)")
                pre_confidence += 10
            if scanner_count >= 3:
                confidence_boosts.append(f"Scanner hits: {scanner_count} (+5%)")
                pre_confidence += 5
        db_session.close()
    except Exception as e:
        logger.debug("TV webhook context fetch skipped: %s", e)

    # Step 0.5: BM25 memory lookup (0 API calls)
    similar_trades = []
    try:
        from mcp_server.trade_memory import TradeMemory
        _tv_memory = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
        similar_trades = _tv_memory.find_similar_for_signal(
            ticker=ticker, direction=direction, pattern="RRMS",
            rrr=rrr, confidence=pre_confidence,
            exchange=ticker.split(":")[0] if ":" in ticker else "NSE",
            top_k=settings.MEMORY_TOP_K,
        )
    except Exception as e:
        logger.debug("Trade memory lookup skipped: %s", e)

    # Step 1: Validate signal via debate validator (auto-triages debate vs single-pass)
    validation = {}
    try:
        from mcp_server.debate_validator import run_debate
        debate_result = run_debate(
            ticker=ticker,
            direction=direction,
            pattern="RRMS",
            rrr=rrr,
            entry_price=payload.entry,
            stop_loss=payload.sl,
            target=payload.target,
            mwa_direction=mwa_direction,
            scanner_count=scanner_count,
            tv_confirmed=True,
            sector_strength=sector_strength,
            fii_net=fii_net,
            delivery_pct=delivery_pct,
            confidence_boosts=confidence_boosts,
            pre_confidence=pre_confidence,
            similar_trades=similar_trades,
        )
        validation = {
            "confidence": debate_result.final_confidence,
            "recommendation": debate_result.recommendation,
            "reasoning": debate_result.reasoning,
            "validation_status": debate_result.validation_status,
            "method": debate_result.method,
            "api_calls_used": debate_result.api_calls_used,
            "risk_assessment": debate_result.risk_assessment,
            "boosts": debate_result.boosts,
        }
    except Exception as e:
        logger.error("TV webhook validation failed: %s", e)
        validation = {"recommendation": "SKIP", "confidence": 0, "reasoning": str(e)}

    confidence = validation.get("confidence", 0)
    recommendation = validation.get("recommendation", "SKIP")

    # Step 2: Record signal
    exchange_str = ticker.split(":")[0] if ":" in ticker else "NSE"
    asset_class_str = get_asset_class(ticker).value
    signal_data = {
        "ticker": ticker,
        "direction": direction,
        "entry_price": payload.entry,
        "stop_loss": payload.sl,
        "target": payload.target,
        "rrr": rrr,
        "pattern": "RRMS (TradingView)",
        "confidence": confidence,
        "exchange": exchange_str,
        "asset_class": asset_class_str,
        "timeframe": payload.timeframe,
        "notes": f"TV Alert | {recommendation} | Qty: {payload.qty}",
    }

    from mcp_server.telegram_receiver import record_signal_to_sheets
    record_result = record_signal_to_sheets(signal_data)

    # Step 2.5: Store in trade memory for future BM25 lookups
    try:
        from mcp_server.trade_memory import TradeMemory, TradeRecord
        _tv_memory_store = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
        _tv_memory_store.add_record(TradeRecord(
            signal_id=record_result.get("signal_id", f"tv_{ticker}_{date.today().isoformat()}"),
            ticker=ticker,
            direction=direction,
            pattern="RRMS (TradingView)",
            entry_price=payload.entry,
            stop_loss=payload.sl,
            target=payload.target,
            rrr=rrr,
            confidence=confidence,
            recommendation=recommendation,
            exchange=ticker.split(":")[0] if ":" in ticker else "NSE",
        ))
    except Exception as e:
        logger.debug("Trade memory store skipped: %s", e)

    # Step 3: Send Telegram notification (only for signals with >50% confidence)
    if confidence > 50:
        try:
            from mcp_server.telegram_bot import send_telegram_message
            emoji = "\U0001f7e2" if recommendation == "ALERT" else "\U0001f7e1" if recommendation == "WATCHLIST" else "\U0001f534"
            exchange_str = ticker.split(":")[0] if ":" in ticker else "NSE"
            asset_class_str = get_asset_class(ticker).value

            segment_map = {
                "NSE": "NSE Equity", "BSE": "BSE Equity",
                "MCX": "Commodity", "NFO": "F&O", "CDS": "Forex",
            }
            segment_label = segment_map.get(exchange_str, exchange_str)

            tf = payload.timeframe
            tf_category_map = {
                "5m": "Intraday", "15m": "Intraday", "30m": "Intraday", "1H": "Intraday",
                "4H": "Swing", "1D": "Swing", "day": "Swing",
                "1W": "Positional", "week": "Positional", "1M": "Positional",
            }
            tf_category = tf_category_map.get(tf, "Swing")

            msg = (
                f"{emoji} TradingView Signal\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Ticker: {ticker}\n"
                f"Segment: {segment_label} | {asset_class_str}\n"
                f"Timeframe: {tf} ({tf_category})\n"
                f"Direction: {direction}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Entry: ₹{payload.entry} | SL: ₹{payload.sl} | TGT: ₹{payload.target}\n"
                f"RRR: {rrr} | Qty: {payload.qty}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"AI Confidence: {confidence}% ({recommendation})\n"
                f"Signal ID: {record_result.get('signal_id', 'N/A')}"
            )
            await send_telegram_message(msg, exchange=exchange_str, force=True)
        except Exception as e:
            logger.debug("Telegram notification skipped: %s", e)
    else:
        logger.info("Telegram skipped for %s — confidence %d%% below 50%% threshold", ticker, confidence)

    return {
        "status": "ok",
        "source": "tradingview",
        "ticker": ticker,
        "direction": direction,
        "ai_confidence": confidence,
        "recommendation": recommendation,
        "signal_id": record_result.get("signal_id", ""),
        "recorded": record_result.get("recorded", False),
    }
