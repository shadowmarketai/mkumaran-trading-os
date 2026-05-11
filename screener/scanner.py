"""
Nifty 500 Stock Screener — Scanner Engine

Fetches OHLCV for all 500 tickers in one batch, calculates RSI and
volume ratio, filters candidates, then fetches P/E only for survivors
to stay within yfinance rate limits.

Filters:
  - Volume ratio ≥ 2× (current day vs 20-day average)
  - RSI (14-period) ≥ 50

Ranked by volume ratio descending. Top 20 returned.
P/E shown as display column (not a filter).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

logger = logging.getLogger("screener.scanner")

IST = ZoneInfo("Asia/Kolkata")
NIFTY500_PATH = Path(__file__).parent.parent / "data" / "nifty500.json"

RSI_PERIOD     = 14
VOL_WINDOW     = 20
VOL_THRESHOLD  = 2.0
RSI_THRESHOLD  = 50.0
TOP_N          = 20
FETCH_DAYS     = 30   # extra buffer for RSI warmup


def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def load_tickers() -> list[str]:
    raw = json.loads(NIFTY500_PATH.read_text())
    return raw["symbols"]


def _yf_symbol(ticker: str) -> str:
    return ticker + ".NS"


def _calculate_rsi(closes: pd.Series, period: int = RSI_PERIOD) -> float:
    delta = closes.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=True).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=True).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else float("nan")


def _fetch_pe(yf_ticker: str) -> float | None:
    try:
        info = yf.Ticker(yf_ticker).info
        pe = info.get("trailingPE") or info.get("forwardPE")
        return round(float(pe), 1) if pe else None
    except Exception:
        return None


def run_scan() -> list[dict]:
    tickers = load_tickers()
    yf_tickers = [_yf_symbol(t) for t in tickers]

    logger.info("Downloading OHLCV for %d tickers...", len(yf_tickers))

    try:
        raw = yf.download(
            yf_tickers,
            period=f"{FETCH_DAYS}d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.error("yfinance batch download failed: %s", e)
        return []

    if raw.empty:
        logger.warning("yfinance returned empty DataFrame")
        return []

    # yfinance returns MultiIndex columns (Field, Ticker) for multi-ticker download
    candidates: list[dict] = []

    for ticker, yf_sym in zip(tickers, yf_tickers):
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if yf_sym not in raw.columns.get_level_values(1):
                    continue
                closes  = raw["Close"][yf_sym].dropna()
                volumes = raw["Volume"][yf_sym].dropna()
            else:
                closes  = raw["Close"].dropna()
                volumes = raw["Volume"].dropna()

            if len(closes) < VOL_WINDOW + 2:
                continue

            price     = float(closes.iloc[-1])
            vol_today = float(volumes.iloc[-1])
            vol_avg   = float(volumes.iloc[-(VOL_WINDOW + 1):-1].mean())

            if vol_avg <= 0:
                continue

            vol_ratio = vol_today / vol_avg
            rsi       = _calculate_rsi(closes)

            if vol_ratio < VOL_THRESHOLD or rsi < RSI_THRESHOLD:
                continue
            if pd.isna(rsi):
                continue

            candidates.append({
                "ticker":    ticker,
                "yf_sym":   yf_sym,
                "price":    round(price, 2),
                "vol_ratio": round(vol_ratio, 2),
                "rsi":      round(rsi, 1),
                "pe":       None,
            })

        except Exception as e:
            logger.debug("Skip %s: %s", ticker, e)
            continue

    # Rank by volume ratio
    candidates.sort(key=lambda x: x["vol_ratio"], reverse=True)
    top = candidates[:TOP_N]

    logger.info("%d candidates after filter → fetching P/E for top %d",
                len(candidates), len(top))

    for row in top:
        row["pe"] = _fetch_pe(row.pop("yf_sym"))

    logger.info("Scan complete — %d results", len(top))
    return top
