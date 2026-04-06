"""
F&O (NFO) Scanners — 8 scanners for Futures & Options Segment.

Scanners 121-128 | Layer: FnO | Instruments: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY
Uses OHLCV data for index-level technical signals (OI/PCR from fo_module.py
are used at signal-generation time; these scanners detect price-action setups
specific to index derivatives trading).

Reuses compute_ema from technical_scanners.py.
"""

import logging

import pandas as pd

from mcp_server.asset_registry import NFO_INDEX_UNIVERSE
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


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high = df["high"] if "high" in df.columns else df["High"]
    low = df["low"] if "low" in df.columns else df["Low"]
    close = df["close"] if "close" in df.columns else df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _get_close(df: pd.DataFrame) -> pd.Series:
    """Get close column regardless of case."""
    return df["close"] if "close" in df.columns else df["Close"]


def _get_high(df: pd.DataFrame) -> pd.Series:
    return df["high"] if "high" in df.columns else df["High"]


def _get_low(df: pd.DataFrame) -> pd.Series:
    return df["low"] if "low" in df.columns else df["Low"]


def _get_volume(df: pd.DataFrame) -> pd.Series:
    return df["volume"] if "volume" in df.columns else df["Volume"]


def _filter_nfo(stock_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Filter stock_data to only NFO universe tickers."""
    nfo_set = {t.upper() for t in NFO_INDEX_UNIVERSE}
    filtered: dict[str, pd.DataFrame] = {}
    for ticker, df in stock_data.items():
        clean = ticker.upper().replace("NFO:", "").replace("NSE:", "")
        if clean in nfo_set:
            filtered[ticker] = df
    return filtered


# ── Scanner 121: NFO Index EMA Crossover Bull ────────────────

def scan_nfo_ema_crossover(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """NFO 9/21 EMA bullish crossover on index futures."""
    results: list[str] = []
    for ticker, df in _filter_nfo(stock_data).items():
        if len(df) < 25:
            continue
        try:
            close = _get_close(df)
            fast = compute_ema(close, 9)
            slow = compute_ema(close, 21)
            if fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_nfo_ema_crossover failed for %s: %s", ticker, e)
    return results


# ── Scanner 122: NFO Index EMA Crossover Bear ────────────────

def scan_nfo_ema_crossover_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """NFO 9/21 EMA bearish crossover on index futures."""
    results: list[str] = []
    for ticker, df in _filter_nfo(stock_data).items():
        if len(df) < 25:
            continue
        try:
            close = _get_close(df)
            fast = compute_ema(close, 9)
            slow = compute_ema(close, 21)
            if fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_nfo_ema_crossover_bear failed for %s: %s", ticker, e)
    return results


# ── Scanner 123: NFO RSI Oversold (Bull) ─────────────────────

def scan_nfo_rsi_oversold(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """NFO index RSI(14) < 30 — oversold, potential long entry."""
    results: list[str] = []
    for ticker, df in _filter_nfo(stock_data).items():
        if len(df) < 20:
            continue
        try:
            rsi = _compute_rsi(_get_close(df), 14)
            if rsi.iloc[-1] < 30:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_nfo_rsi_oversold failed for %s: %s", ticker, e)
    return results


# ── Scanner 124: NFO RSI Overbought (Bear) ───────────────────

def scan_nfo_rsi_overbought(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """NFO index RSI(14) > 70 — overbought, potential short entry."""
    results: list[str] = []
    for ticker, df in _filter_nfo(stock_data).items():
        if len(df) < 20:
            continue
        try:
            rsi = _compute_rsi(_get_close(df), 14)
            if rsi.iloc[-1] > 70:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_nfo_rsi_overbought failed for %s: %s", ticker, e)
    return results


# ── Scanner 125: NFO Volatility Squeeze (Bull) ───────────────

def scan_nfo_vol_squeeze_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """NFO index Bollinger Band squeeze with price above middle band.

    Low volatility (bandwidth at 20-period low) with bullish bias signals
    impending breakout — ideal for buying calls or bull spreads.
    """
    results: list[str] = []
    for ticker, df in _filter_nfo(stock_data).items():
        if len(df) < 25:
            continue
        try:
            close = _get_close(df)
            middle = close.rolling(20).mean()
            std = close.rolling(20).std()
            upper = middle + 2 * std
            lower = middle - 2 * std
            bandwidth = (upper - lower) / middle.replace(0, float("nan"))
            bw_min = bandwidth.rolling(20).min()
            if (
                pd.notna(bandwidth.iloc[-1])
                and pd.notna(bw_min.iloc[-1])
                and bandwidth.iloc[-1] <= bw_min.iloc[-1] * 1.05
                and close.iloc[-1] >= middle.iloc[-1]
            ):
                results.append(ticker)
        except Exception as e:
            logger.error("scan_nfo_vol_squeeze_bull failed for %s: %s", ticker, e)
    return results


# ── Scanner 126: NFO Volatility Squeeze (Bear) ───────────────

def scan_nfo_vol_squeeze_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """NFO index BB squeeze with price below middle band — bearish squeeze.

    Low volatility with bearish bias — ideal for buying puts or bear spreads.
    """
    results: list[str] = []
    for ticker, df in _filter_nfo(stock_data).items():
        if len(df) < 25:
            continue
        try:
            close = _get_close(df)
            middle = close.rolling(20).mean()
            std = close.rolling(20).std()
            upper = middle + 2 * std
            lower = middle - 2 * std
            bandwidth = (upper - lower) / middle.replace(0, float("nan"))
            bw_min = bandwidth.rolling(20).min()
            if (
                pd.notna(bandwidth.iloc[-1])
                and pd.notna(bw_min.iloc[-1])
                and bandwidth.iloc[-1] <= bw_min.iloc[-1] * 1.05
                and close.iloc[-1] < middle.iloc[-1]
            ):
                results.append(ticker)
        except Exception as e:
            logger.error("scan_nfo_vol_squeeze_bear failed for %s: %s", ticker, e)
    return results


# ── Scanner 127: NFO Range Breakout (Bull) ───────────────────

def scan_nfo_range_breakout_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """NFO index breakout above 20-day high with volume confirmation.

    Identifies high-probability breakout entries for index futures/options
    when price exceeds the 20-day high range with above-average volume.
    """
    results: list[str] = []
    for ticker, df in _filter_nfo(stock_data).items():
        if len(df) < 25:
            continue
        try:
            close = _get_close(df)
            high = _get_high(df)
            volume = _get_volume(df)

            # Price closed above 20-day high
            prev_high_20 = high.iloc[-21:-1].max()
            current_close = close.iloc[-1]

            # Volume above 20-day average
            vol_avg = volume.rolling(20).mean().iloc[-1]
            current_vol = volume.iloc[-1]

            if (
                pd.notna(prev_high_20)
                and current_close > prev_high_20
                and pd.notna(vol_avg)
                and current_vol > vol_avg
            ):
                results.append(ticker)
        except Exception as e:
            logger.error("scan_nfo_range_breakout_bull failed for %s: %s", ticker, e)
    return results


# ── Scanner 128: NFO Range Breakdown (Bear) ──────────────────

def scan_nfo_range_breakdown_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """NFO index breakdown below 20-day low with volume confirmation.

    Identifies breakdown entries for puts / bear spreads when price
    breaks below the 20-day low range with above-average volume.
    """
    results: list[str] = []
    for ticker, df in _filter_nfo(stock_data).items():
        if len(df) < 25:
            continue
        try:
            close = _get_close(df)
            low = _get_low(df)
            volume = _get_volume(df)

            # Price closed below 20-day low
            prev_low_20 = low.iloc[-21:-1].min()
            current_close = close.iloc[-1]

            # Volume above 20-day average
            vol_avg = volume.rolling(20).mean().iloc[-1]
            current_vol = volume.iloc[-1]

            if (
                pd.notna(prev_low_20)
                and current_close < prev_low_20
                and pd.notna(vol_avg)
                and current_vol > vol_avg
            ):
                results.append(ticker)
        except Exception as e:
            logger.error("scan_nfo_range_breakdown_bear failed for %s: %s", ticker, e)
    return results
