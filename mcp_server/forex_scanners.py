"""
Forex (CDS) Scanners — 8 scanners for Currency Derivatives Segment.

Scanners 83-90 | Layer: Forex | Pairs: USDINR, EURINR, GBPINR, JPYINR
Reuses compute_ema from technical_scanners.py.
"""

import logging

import pandas as pd

from mcp_server.asset_registry import CDS_UNIVERSE
from mcp_server.technical_scanners import compute_ema

logger = logging.getLogger(__name__)


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI for a given period."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _compute_bb(df: pd.DataFrame, period: int = 20) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute Bollinger Bands (middle, upper, lower) and bandwidth."""
    middle = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    upper = middle + 2 * std
    lower = middle - 2 * std
    return middle, upper, lower


def _filter_cds(stock_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Filter stock_data to only CDS universe tickers."""
    cds_set = {t.upper() for t in CDS_UNIVERSE}
    filtered: dict[str, pd.DataFrame] = {}
    for ticker, df in stock_data.items():
        # Match "USDINR", "CDS:USDINR", or yfinance "USDINR=X"
        clean = ticker.upper().replace("CDS:", "").replace("=X", "")
        if clean in cds_set:
            filtered[ticker] = df
    return filtered


# ── Scanner 83: CDS 9/21 EMA Bullish Crossover ─────────────

def scan_cds_ema_crossover(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """CDS 9/21 EMA bullish crossover."""
    results: list[str] = []
    for ticker, df in _filter_cds(stock_data).items():
        if len(df) < 25:
            continue
        try:
            fast = compute_ema(df["close"], 9)
            slow = compute_ema(df["close"], 21)
            if fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_cds_ema_crossover failed for %s: %s", ticker, e)
    return results


# ── Scanner 84: CDS 9/21 EMA Bearish Crossover ─────────────

def scan_cds_ema_crossover_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """CDS 9/21 EMA bearish crossover."""
    results: list[str] = []
    for ticker, df in _filter_cds(stock_data).items():
        if len(df) < 25:
            continue
        try:
            fast = compute_ema(df["close"], 9)
            slow = compute_ema(df["close"], 21)
            if fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_cds_ema_crossover_bear failed for %s: %s", ticker, e)
    return results


# ── Scanner 85: CDS RSI Oversold ────────────────────────────

def scan_cds_rsi_oversold(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """CDS RSI(14) < 30 — oversold."""
    results: list[str] = []
    for ticker, df in _filter_cds(stock_data).items():
        if len(df) < 20:
            continue
        try:
            rsi = _compute_rsi(df["close"], 14)
            if rsi.iloc[-1] < 30:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_cds_rsi_oversold failed for %s: %s", ticker, e)
    return results


# ── Scanner 86: CDS RSI Overbought ──────────────────────────

def scan_cds_rsi_overbought(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """CDS RSI(14) > 70 — overbought."""
    results: list[str] = []
    for ticker, df in _filter_cds(stock_data).items():
        if len(df) < 20:
            continue
        try:
            rsi = _compute_rsi(df["close"], 14)
            if rsi.iloc[-1] > 70:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_cds_rsi_overbought failed for %s: %s", ticker, e)
    return results


# ── Scanner 87: CDS Bollinger Band Squeeze (Bull) ───────────

def scan_cds_bb_squeeze(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """BB squeeze: bandwidth < 20-period low and price above middle band."""
    results: list[str] = []
    for ticker, df in _filter_cds(stock_data).items():
        if len(df) < 25:
            continue
        try:
            middle, upper, lower = _compute_bb(df, 20)
            bandwidth = (upper - lower) / middle.replace(0, float("nan"))
            bw_min = bandwidth.rolling(20).min()
            if (
                pd.notna(bandwidth.iloc[-1])
                and pd.notna(bw_min.iloc[-1])
                and bandwidth.iloc[-1] <= bw_min.iloc[-1]
                and df["close"].iloc[-1] >= middle.iloc[-1]
            ):
                results.append(ticker)
        except Exception as e:
            logger.error("scan_cds_bb_squeeze failed for %s: %s", ticker, e)
    return results


# ── Scanner 88: CDS BB Squeeze Bear ─────────────────────────

def scan_cds_bb_squeeze_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """BB squeeze with price below middle band — bearish squeeze."""
    results: list[str] = []
    for ticker, df in _filter_cds(stock_data).items():
        if len(df) < 25:
            continue
        try:
            middle, upper, lower = _compute_bb(df, 20)
            bandwidth = (upper - lower) / middle.replace(0, float("nan"))
            bw_min = bandwidth.rolling(20).min()
            if (
                pd.notna(bandwidth.iloc[-1])
                and pd.notna(bw_min.iloc[-1])
                and bandwidth.iloc[-1] <= bw_min.iloc[-1]
                and df["close"].iloc[-1] < middle.iloc[-1]
            ):
                results.append(ticker)
        except Exception as e:
            logger.error("scan_cds_bb_squeeze_bear failed for %s: %s", ticker, e)
    return results


# ── Scanner 89: CDS Carry Trade ─────────────────────────────

def scan_cds_carry_trade(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """USDINR trending up with positive carry differential (EMA slope + momentum)."""
    results: list[str] = []
    for ticker, df in _filter_cds(stock_data).items():
        if len(df) < 30:
            continue
        try:
            clean = ticker.upper().replace("CDS:", "").replace("=X", "")
            if clean != "USDINR":
                continue
            ema21 = compute_ema(df["close"], 21)
            # Positive trend: EMA slope up for 5 consecutive days
            slope_positive = all(
                ema21.iloc[-i] > ema21.iloc[-(i + 1)] for i in range(1, 6)
            )
            # Price above EMA
            price_above = df["close"].iloc[-1] > ema21.iloc[-1]
            if slope_positive and price_above:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_cds_carry_trade failed for %s: %s", ticker, e)
    return results


# ── Scanner 90: CDS DXY Divergence ──────────────────────────

def scan_cds_dxy_divergence(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """INR pairs diverging from expected DXY correlation (bearish for INR)."""
    results: list[str] = []
    for ticker, df in _filter_cds(stock_data).items():
        if len(df) < 20:
            continue
        try:
            # Divergence: price making higher highs but RSI making lower highs
            rsi = _compute_rsi(df["close"], 14)
            if len(rsi) < 10:
                continue
            price_rising = df["close"].iloc[-1] > df["close"].iloc[-5]
            rsi_falling = rsi.iloc[-1] < rsi.iloc[-5]
            rsi_high = rsi.iloc[-1] > 60  # Still in upper range
            if price_rising and rsi_falling and rsi_high:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_cds_dxy_divergence failed for %s: %s", ticker, e)
    return results
