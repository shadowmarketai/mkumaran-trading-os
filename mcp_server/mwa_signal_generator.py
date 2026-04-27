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
    NFO_INDEX_UNIVERSE,
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
    if t in NFO_INDEX_UNIVERSE:
        return Exchange.NFO.value
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


def _scanners_flagging(ticker: str, scanner_results: dict) -> list[str]:
    """Return the list of scanner keys that flagged this ticker."""
    flagged: list[str] = []
    for key, result in scanner_results.items():
        stocks = result if isinstance(result, list) else []
        if ticker in stocks:
            flagged.append(key)
    return flagged


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

        # On-the-fly fetch for promoted stocks not in stock_data
        if df is None or df.empty or len(df) < 15:
            try:
                from mcp_server.nse_scanner import get_stock_data as _get_stock
                exchange = _resolve_exchange(ticker)
                prefix = f"{exchange}:" if exchange != "NSE" else ""
                fetched = _get_stock(f"{prefix}{ticker}", period="6mo", interval="1d")
                if fetched is not None and not fetched.empty and len(fetched) >= 15:
                    df = fetched
                    stock_data[ticker] = df
                    logger.info("On-the-fly fetch OK for %s: %d bars", ticker, len(df))
            except Exception as e:
                logger.debug("On-the-fly fetch failed for %s: %s", ticker, e)

        if df is None or df.empty or len(df) < 15:
            logger.info("Skipping %s: insufficient OHLCV data", ticker)
            continue

        atr = _compute_atr(df, period=14)
        if atr <= 0:
            logger.debug("Skipping %s: ATR is zero", ticker)
            continue

        entry = float(df["close"].iloc[-1])
        bull_count, bear_count = _count_bull_bear(ticker, scanner_results)
        scanner_count = bull_count + bear_count
        scanner_list = _scanners_flagging(ticker, scanner_results)

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

        # RRMS position sizing — settings are Decimal (money zone); cast to
        # float here because `risk` was computed from ATR/float OHLCV and this
        # function is in the analysis zone.
        risk_amt = float(settings.RRMS_CAPITAL * settings.RRMS_RISK_PCT)
        qty = floor(risk_amt / risk)
        if qty <= 0:
            qty = 1

        exchange = _resolve_exchange(ticker)
        asset_class = _resolve_asset_class(exchange)

        # ── Options Enrichment for ANY eligible ticker ──
        # Attach concrete option contract recommendation (strike, expiry,
        # premium, Greeks, option-level SL/TGT) so users can act directly.
        # Most F&O stocks trade on NSE as equity AND on NFO for derivatives.
        # We check is_eligible (covers all ~220 F&O underlyings) rather than
        # gating on asset_class==FNO, because asset_class is almost always
        # EQUITY for stock signals — the FNO classification only triggers for
        # index futures (NIFTY/BANKNIFTY) which are rarely in promoted.
        # Fails open: any error leaves the signal as equity-only.
        option_fields: dict = {}
        try:
            from mcp_server.options_selector import (
                build_option_recommendation,
                is_eligible,
            )
            if is_eligible(ticker):
                from mcp_server.mcp_server import _get_kite_for_fo
                kite = _get_kite_for_fo()
                logger.info("Option enrichment: attempting for %s (eligible)", ticker)
                rec = build_option_recommendation(
                    symbol=ticker,
                    direction=direction,
                    spot=entry,
                    underlying_sl=sl,
                    underlying_target=target,
                    kite=kite,
                )
                if rec:
                    option_fields = rec
                    logger.info(
                        "Option enrichment: %s → %s %s",
                        ticker, rec.get("option_tradingsymbol"), rec.get("option_strategy"),
                    )
                else:
                    logger.debug("Option enrichment: %s → no recommendation returned", ticker)
        except Exception as opt_err:  # noqa: BLE001
            logger.debug("Option enrichment failed for %s: %s", ticker, opt_err)

        # POS 5 EMA shadow — KILLED 2026-04-27 after backtest validation.
        # 15m data: HDFCBANK 56 trades 32% WR Sharpe -0.99;
        #           SBIN     57 trades 36.8% WR Sharpe -0.96.
        # All gates failed. Shadow fields kept for schema compat only.
        pos_5ema_fired: bool = False
        pos_5ema_direction: str | None = None

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
            "scanner_list": scanner_list,
            "ohlcv_df": df,  # pass through for downstream feature extraction
            "exchange": exchange,
            "asset_class": asset_class,
            "timeframe": "day",
            "pos_5ema_shadow": pos_5ema_fired,
            "pos_5ema_shadow_direction": pos_5ema_direction,
            **option_fields,  # merges option_* keys (empty dict if no enrichment)
        })

    logger.info("Generated %d MWA signals from %d promoted stocks", len(signals), len(promoted))
    return signals
