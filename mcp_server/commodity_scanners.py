"""
Commodity (MCX) Scanners — 8 scanners for Multi Commodity Exchange.

Scanners 91-98 | Layer: Commodity | Instruments: GOLD, SILVER, CRUDEOIL, NATURALGAS, etc.
Reuses compute_ema, compute_macd from technical_scanners.py.
"""

import logging

import pandas as pd

from mcp_server.asset_registry import MCX_UNIVERSE, MCX_YF_PROXY
from mcp_server.technical_scanners import compute_ema, compute_macd

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


def _filter_mcx(stock_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Filter stock_data to only MCX universe tickers."""
    mcx_set = {t.upper() for t in MCX_UNIVERSE}
    proxy_values = {v.upper() for v in MCX_YF_PROXY.values() if v}
    filtered: dict[str, pd.DataFrame] = {}
    for ticker, df in stock_data.items():
        clean = ticker.upper().replace("MCX:", "")
        if clean in mcx_set or clean in proxy_values:
            filtered[ticker] = df
    return filtered


def _find_ticker(stock_data: dict[str, pd.DataFrame], *names: str) -> tuple[str | None, pd.DataFrame | None]:
    """Find a ticker matching any of the given names."""
    for ticker, df in stock_data.items():
        clean = ticker.upper().replace("MCX:", "")
        for name in names:
            if clean == name.upper():
                return ticker, df
    return None, None


# ── Scanner 91: MCX 9/21 EMA Bullish Crossover ─────────────

def scan_mcx_ema_crossover(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """MCX 9/21 EMA bullish crossover on metals/energy."""
    results: list[str] = []
    for ticker, df in _filter_mcx(stock_data).items():
        if len(df) < 25:
            continue
        try:
            fast = compute_ema(df["close"], 9)
            slow = compute_ema(df["close"], 21)
            if fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_mcx_ema_crossover failed for %s: %s", ticker, e)
    return results


# ── Scanner 92: MCX 9/21 EMA Bearish Crossover ─────────────

def scan_mcx_ema_crossover_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """MCX 9/21 EMA bearish crossover."""
    results: list[str] = []
    for ticker, df in _filter_mcx(stock_data).items():
        if len(df) < 25:
            continue
        try:
            fast = compute_ema(df["close"], 9)
            slow = compute_ema(df["close"], 21)
            if fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_mcx_ema_crossover_bear failed for %s: %s", ticker, e)
    return results


# ── Scanner 93: MCX RSI Oversold ────────────────────────────

def scan_mcx_rsi_oversold(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """MCX RSI(14) < 30 — oversold commodities."""
    results: list[str] = []
    for ticker, df in _filter_mcx(stock_data).items():
        if len(df) < 20:
            continue
        try:
            rsi = _compute_rsi(df["close"], 14)
            if rsi.iloc[-1] < 30:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_mcx_rsi_oversold failed for %s: %s", ticker, e)
    return results


# ── Scanner 94: MCX RSI Overbought ──────────────────────────

def scan_mcx_rsi_overbought(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """MCX RSI(14) > 70 — overbought commodities."""
    results: list[str] = []
    for ticker, df in _filter_mcx(stock_data).items():
        if len(df) < 20:
            continue
        try:
            rsi = _compute_rsi(df["close"], 14)
            if rsi.iloc[-1] > 70:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_mcx_rsi_overbought failed for %s: %s", ticker, e)
    return results


# ── Scanner 95: Gold/Silver Ratio Mean-Reversion (Bull) ─────

def scan_mcx_gold_silver_ratio(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Gold/Silver ratio mean-reversion: ratio contracting toward mean (bullish silver)."""
    results: list[str] = []
    try:
        _, gold_df = _find_ticker(stock_data, "GOLD", "GOLDM", "GC=F")
        _, silver_df = _find_ticker(stock_data, "SILVER", "SILVERM", "SI=F")
        if gold_df is None or silver_df is None:
            return results
        if len(gold_df) < 30 or len(silver_df) < 30:
            return results

        # Align lengths
        min_len = min(len(gold_df), len(silver_df))
        g_close = gold_df["close"].iloc[-min_len:].reset_index(drop=True)
        s_close = silver_df["close"].iloc[-min_len:].reset_index(drop=True)

        ratio = g_close / s_close.replace(0, float("nan"))
        ratio_mean = ratio.rolling(20).mean()

        # Ratio contracting: current below mean and declining (bullish for metals)
        if (
            pd.notna(ratio.iloc[-1])
            and pd.notna(ratio_mean.iloc[-1])
            and ratio.iloc[-1] < ratio_mean.iloc[-1]
            and ratio.iloc[-1] < ratio.iloc[-5]
        ):
            # Return all matching metal tickers
            for ticker in _filter_mcx(stock_data):
                clean = ticker.upper().replace("MCX:", "")
                if clean in {"GOLD", "GOLDM", "SILVER", "SILVERM", "GC=F", "SI=F"}:
                    results.append(ticker)
    except Exception as e:
        logger.error("scan_mcx_gold_silver_ratio failed: %s", e)
    return results


# ── Scanner 96: Gold/Silver Ratio Expansion (Bear) ──────────

def scan_mcx_gold_silver_ratio_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Gold/Silver ratio expanding away from mean (bearish for silver)."""
    results: list[str] = []
    try:
        _, gold_df = _find_ticker(stock_data, "GOLD", "GOLDM", "GC=F")
        _, silver_df = _find_ticker(stock_data, "SILVER", "SILVERM", "SI=F")
        if gold_df is None or silver_df is None:
            return results
        if len(gold_df) < 30 or len(silver_df) < 30:
            return results

        min_len = min(len(gold_df), len(silver_df))
        g_close = gold_df["close"].iloc[-min_len:].reset_index(drop=True)
        s_close = silver_df["close"].iloc[-min_len:].reset_index(drop=True)

        ratio = g_close / s_close.replace(0, float("nan"))
        ratio_mean = ratio.rolling(20).mean()

        # Ratio expanding: current above mean and rising (bearish for metals)
        if (
            pd.notna(ratio.iloc[-1])
            and pd.notna(ratio_mean.iloc[-1])
            and ratio.iloc[-1] > ratio_mean.iloc[-1]
            and ratio.iloc[-1] > ratio.iloc[-5]
        ):
            for ticker in _filter_mcx(stock_data):
                clean = ticker.upper().replace("MCX:", "")
                if clean in {"SILVER", "SILVERM", "SI=F"}:
                    results.append(ticker)
    except Exception as e:
        logger.error("scan_mcx_gold_silver_ratio_bear failed: %s", e)
    return results


# ── Scanner 97: Crude Oil MACD + Volume Breakout ────────────

def scan_mcx_crude_momentum(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Crude oil MACD bullish crossover + volume breakout."""
    results: list[str] = []
    for ticker, df in _filter_mcx(stock_data).items():
        clean = ticker.upper().replace("MCX:", "")
        if clean not in {"CRUDEOIL", "CL=F", "NATURALGAS", "NG=F"}:
            continue
        if len(df) < 35:
            continue
        try:
            macd_line, signal_line, _ = compute_macd(df)
            # MACD bullish crossover
            curr_above = macd_line.iloc[-1] > signal_line.iloc[-1]
            prev_above = macd_line.iloc[-2] > signal_line.iloc[-2]
            if not (curr_above and not prev_above):
                continue
            # Volume above 20-day average
            vol_avg = df["volume"].rolling(20).mean().iloc[-1]
            if df["volume"].iloc[-1] > vol_avg:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_mcx_crude_momentum failed for %s: %s", ticker, e)
    return results


# ── Scanner 98: Multi-Metal Relative Strength ───────────────

def scan_mcx_metal_strength(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Multi-metal relative strength: metals outperforming their 20-day average return."""
    results: list[str] = []
    metals = {"GOLD", "GOLDM", "SILVER", "SILVERM", "COPPER", "ZINC", "ALUMINIUM",
              "GC=F", "SI=F", "HG=F"}
    for ticker, df in _filter_mcx(stock_data).items():
        clean = ticker.upper().replace("MCX:", "")
        if clean not in metals:
            continue
        if len(df) < 25:
            continue
        try:
            # 5-day return vs 20-day average return
            returns_5d = (df["close"].iloc[-1] / df["close"].iloc[-5] - 1) * 100
            returns_20d = (df["close"].pct_change(5).rolling(20).mean().iloc[-1]) * 100
            if pd.notna(returns_20d) and returns_5d > returns_20d and returns_5d > 0:
                results.append(ticker)
        except Exception as e:
            logger.error("scan_mcx_metal_strength failed for %s: %s", ticker, e)
    return results
