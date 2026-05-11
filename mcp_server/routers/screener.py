"""
Nifty 500 Screener — FastAPI router

Integrated into the main app at /api/screener/*.
Background scanner runs every 5 minutes during market hours.
Results are cached in memory and served instantly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from fastapi import APIRouter

router = APIRouter(prefix="/api/screener", tags=["screener"])
logger = logging.getLogger("screener")

IST            = ZoneInfo("Asia/Kolkata")
SCAN_INTERVAL  = 300
RSI_PERIOD     = 14
VOL_WINDOW     = 20
VOL_THRESHOLD  = 2.0
RSI_THRESHOLD  = 50.0
TOP_N          = 20
FETCH_DAYS     = 30

NIFTY500_PATH = Path(__file__).parent.parent.parent / "data" / "nifty500.json"

_state: dict = {
    "results":    [],
    "last_scan":  None,
    "next_scan":  None,
    "scanning":   False,
    "scan_count": 0,
}
_scheduler_started = False


# ── Helpers ───────────────────────────────────────────────────────────────

def _is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    open_  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    close_ = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_ <= now <= close_


def _load_tickers() -> list[str]:
    raw = json.loads(NIFTY500_PATH.read_text())
    return raw["symbols"]


def _rsi(closes: pd.Series, period: int = RSI_PERIOD) -> float:
    delta    = closes.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=True).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=True).mean()
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    v   = rsi.iloc[-1]
    return float(v) if pd.notna(v) else float("nan")


def _fetch_pe(yf_sym: str) -> float | None:
    try:
        info = yf.Ticker(yf_sym).info
        pe = info.get("trailingPE") or info.get("forwardPE")
        return round(float(pe), 1) if pe else None
    except Exception:
        return None


def _run_scan_sync() -> list[dict]:
    tickers    = _load_tickers()
    yf_symbols = [t + ".NS" for t in tickers]

    logger.info("Screener: downloading OHLCV for %d tickers...", len(yf_symbols))
    try:
        raw = yf.download(
            yf_symbols,
            period=f"{FETCH_DAYS}d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.error("Screener: yfinance download failed: %s", e)
        return []

    if raw.empty:
        return []

    candidates: list[dict] = []

    for ticker, yf_sym in zip(tickers, yf_symbols):
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
            rsi_val   = _rsi(closes)

            if vol_ratio < VOL_THRESHOLD or rsi_val < RSI_THRESHOLD or pd.isna(rsi_val):
                continue

            candidates.append({
                "ticker":    ticker,
                "yf_sym":   yf_sym,
                "price":    round(price, 2),
                "vol_ratio": round(vol_ratio, 2),
                "rsi":      round(rsi_val, 1),
                "pe":       None,
            })
        except Exception:
            continue

    candidates.sort(key=lambda x: x["vol_ratio"], reverse=True)
    top = candidates[:TOP_N]

    logger.info("Screener: %d candidates → fetching P/E for top %d", len(candidates), len(top))
    for row in top:
        row["pe"] = _fetch_pe(row.pop("yf_sym"))

    logger.info("Screener: scan done — %d results", len(top))
    return top


async def _do_scan() -> None:
    if _state["scanning"]:
        return
    _state["scanning"] = True
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, _run_scan_sync)
        _state["results"]   = results
        _state["last_scan"] = datetime.now(IST).strftime("%H:%M:%S IST")
        _state["scan_count"] += 1
    except Exception as e:
        logger.error("Screener: scan error: %s", e)
    finally:
        _state["scanning"] = False
        _state["next_scan"] = SCAN_INTERVAL


async def _scheduler() -> None:
    await asyncio.sleep(3)
    while True:
        if _is_market_open():
            await _do_scan()
        else:
            logger.debug("Screener: market closed, skipping scan")
        _state["next_scan"] = SCAN_INTERVAL
        for _ in range(SCAN_INTERVAL):
            await asyncio.sleep(1)
            if _state["next_scan"] is not None:
                _state["next_scan"] = max(0, _state["next_scan"] - 1)


def start_scheduler() -> None:
    global _scheduler_started
    if not _scheduler_started:
        asyncio.create_task(_scheduler())
        _scheduler_started = True


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/status")
async def screener_status() -> dict:
    return {
        "market_open": _is_market_open(),
        "scanning":    _state["scanning"],
        "last_scan":   _state["last_scan"],
        "next_scan":   _state["next_scan"],
        "result_count": len(_state["results"]),
    }


@router.get("/results")
async def screener_results() -> dict:
    return {
        "market_open": _is_market_open(),
        "scanning":    _state["scanning"],
        "last_scan":   _state["last_scan"],
        "next_scan":   _state["next_scan"],
        "results":     _state["results"],
    }


@router.post("/scan")
async def screener_trigger() -> dict:
    if _state["scanning"]:
        return {"status": "already_scanning"}
    if not _is_market_open():
        return {"status": "market_closed"}
    asyncio.create_task(_do_scan())
    return {"status": "started"}
