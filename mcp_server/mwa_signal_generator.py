"""
MWA Signal Generator — ATR-based trade levels for promoted stocks.

Takes top 10 promoted stocks from MWA scan and generates
Entry / SL / TGT levels using ATR(14), with RRMS position sizing.
"""

import logging
from math import floor

import pandas as pd

from mcp_server.asset_registry import (
    CDS_UNIVERSE,
    MCX_UNIVERSE,
    AssetClass,
    Exchange,
)
from mcp_server.config import settings
from mcp_server.mwa_scanner import SCANNERS

logger = logging.getLogger(__name__)


def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Compute ATR(period) from OHLCV DataFrame. Returns last ATR value."""
    if len(df) < period + 1:
        return 0.0
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    val = atr.iloc[-1]
    return float(val) if pd.notna(val) else 0.0


def _resolve_exchange(ticker: str) -> str:
    """Determine exchange for a promoted ticker."""
    t = ticker.upper()
    if t in MCX_UNIVERSE:
        return Exchange.MCX.value
    if t in CDS_UNIVERSE:
        return Exchange.CDS.value
    return Exchange.NSE.value


def _resolve_asset_class(exchange: str) -> str:
    """Map exchange to asset class."""
    mapping = {
        "MCX": AssetClass.COMMODITY.value,
        "CDS": AssetClass.CURRENCY.value,
        "NFO": AssetClass.FNO.value,
    }
    return mapping.get(exchange, AssetClass.EQUITY.value)


def _count_bull_bear(ticker: str, scanner_results: dict) -> tuple[int, int]:
    """Count how many bull vs bear scanners fired for a given ticker."""
    bull = 0
    bear = 0
    for key, result in scanner_results.items():
        cfg = SCANNERS.get(key, {})
        stype = cfg.get("type", "")

        stocks = result if isinstance(result, list) else []
        if ticker in stocks:
            if stype == "BULL":
                bull += 1
            elif stype == "BEAR":
                bear += 1
    return bull, bear


def generate_mwa_signals(
    promoted: list[str],
    stock_data: dict[str, pd.DataFrame],
    mwa_direction: str,
    scanner_results: dict,
) -> list[dict]:
    """
    Generate ATR-based trade signals for top promoted stocks.

    Args:
        promoted: Top N promoted tickers (already sliced by caller).
        stock_data: Dict of ticker → OHLCV DataFrame.
        mwa_direction: Overall MWA direction (BULL/MILD_BULL/BEAR/etc).
        scanner_results: Raw scanner results keyed by scanner name.

    Returns:
        List of signal dicts with entry/sl/target/rrr/qty/direction.
    """
    signals: list[dict] = []

    for ticker in promoted:
        df = stock_data.get(ticker)
        if df is None or df.empty or len(df) < 15:
            logger.debug("Skipping %s: insufficient OHLCV data", ticker)
            continue

        atr = _compute_atr(df, period=14)
        if atr <= 0:
            logger.debug("Skipping %s: ATR is zero", ticker)
            continue

        entry = float(df["close"].iloc[-1])
        bull_count, bear_count = _count_bull_bear(ticker, scanner_results)
        scanner_count = bull_count + bear_count

        # Direction: more bull scanners → LONG, more bear → SHORT
        if bull_count > bear_count:
            direction = "LONG"
        elif bear_count > bull_count:
            direction = "SHORT"
        elif mwa_direction in ("BULL", "MILD_BULL"):
            direction = "LONG"
        else:
            direction = "SHORT"

        # ATR-based levels
        atr_mult = 1.5
        rrr_mult = settings.RRMS_MIN_RRR

        if direction == "LONG":
            sl = entry - (atr_mult * atr)
            risk = entry - sl
            target = entry + (rrr_mult * risk)
        else:
            sl = entry + (atr_mult * atr)
            risk = sl - entry
            target = entry - (rrr_mult * risk)

        if risk <= 0:
            logger.debug("Skipping %s: zero risk", ticker)
            continue

        rrr = (abs(target - entry)) / risk

        # RRMS position sizing
        risk_amt = settings.RRMS_CAPITAL * settings.RRMS_RISK_PCT
        qty = floor(risk_amt / risk)
        if qty <= 0:
            qty = 1

        exchange = _resolve_exchange(ticker)
        asset_class = _resolve_asset_class(exchange)

        signals.append({
            "ticker": ticker,
            "direction": direction,
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "target": round(target, 2),
            "rrr": round(rrr, 1),
            "qty": qty,
            "scanner_count": scanner_count,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "exchange": exchange,
            "asset_class": asset_class,
            "timeframe": "day",
        })

    logger.info("Generated %d MWA signals from %d promoted stocks", len(signals), len(promoted))
    return signals
