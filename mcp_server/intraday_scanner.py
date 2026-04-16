"""
MKUMARAN Trading OS — Intraday Scanner

A parallel pipeline to the daily-swing MWA scan. Runs every 5 minutes
during NSE hours on a curated F&O watchlist, looking for intraday setups
that resolve within the same trading day — not swing entries.

Scanners (all operate on 5-minute OHLCV):

  ORB (Opening Range Breakout)
      Close breaks above/below the 9:15–9:30 range with volume >= 1.2×
      the first-15min average.

  VWAP reclaim / reject
      Price crosses back above VWAP after 3 bars below (reclaim → bull)
      or back below VWAP after 3 bars above (reject → bear).

  5m momentum
      3 consecutive bullish 5m bars with each volume > previous, or
      the bearish mirror — classic momentum ignition.

Signal shape: ticker, direction, entry, sl, target, rrr, pattern,
scanner_count. Matches the shape MWA produces so the Telegram card
builder in mcp_server can reuse the rendering path (with an
⚡ INTRADAY tag).

Gated by settings.INTRADAY_SIGNALS_ENABLED (default false).
"""

from __future__ import annotations

import logging
from datetime import time
from typing import Any

import numpy as np
import pandas as pd

from mcp_server.config import settings
from mcp_server.market_calendar import is_market_open, now_ist

logger = logging.getLogger(__name__)


# ── Default watchlist (30 liquid F&O large-caps) ────────────────
DEFAULT_WATCHLIST: list[str] = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "AXISBANK", "KOTAKBANK", "LT", "ITC",
    "HINDUNILVR", "BHARTIARTL", "MARUTI", "TATAMOTORS", "TATASTEEL",
    "BAJFINANCE", "HCLTECH", "WIPRO", "ADANIENT", "ADANIPORTS",
    "SUNPHARMA", "ASIANPAINT", "TITAN", "ULTRACEMCO", "POWERGRID",
    "NTPC", "ONGC", "JSWSTEEL", "HINDALCO", "VEDL",
]


def _watchlist() -> list[str]:
    """Resolve watchlist from env var (comma-separated) or default list."""
    raw = getattr(settings, "INTRADAY_WATCHLIST", "") or ""
    if raw.strip():
        return [s.strip().upper() for s in raw.split(",") if s.strip()]
    return DEFAULT_WATCHLIST


# ── Helpers ─────────────────────────────────────────────────────

def _require_5m_bars(df: pd.DataFrame | None, min_bars: int = 6) -> bool:
    """Return True when df has enough 5m bars and the expected columns."""
    if df is None or df.empty:
        return False
    needed = {"open", "high", "low", "close", "volume"}
    if not needed.issubset(set(df.columns.str.lower())):
        return False
    return len(df) >= min_bars


def _vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP on a 5m bar frame — cumulative over the day."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_pv = (typical * df["volume"]).cumsum()
    cum_v = df["volume"].cumsum().replace(0, np.nan)
    return cum_pv / cum_v


# ── Scanners ────────────────────────────────────────────────────

def scan_orb(df: pd.DataFrame) -> dict[str, Any] | None:
    """Opening Range Breakout on the first 15 min (bars 0-2)."""
    if not _require_5m_bars(df, 4):
        return None
    opening = df.iloc[:3]
    rest = df.iloc[3:]
    if rest.empty:
        return None
    or_high = opening["high"].max()
    or_low = opening["low"].min()
    avg_vol_opening = opening["volume"].mean() or 1.0
    last = rest.iloc[-1]
    if last["close"] > or_high and last["volume"] >= avg_vol_opening * 1.2:
        risk = max(last["close"] - or_low, last["close"] * 0.002)
        return {
            "direction": "LONG",
            "entry": float(last["close"]),
            "sl": float(or_low),
            "target": float(last["close"] + risk * 2),
            "pattern": "ORB breakout",
            "scanner": "orb",
        }
    if last["close"] < or_low and last["volume"] >= avg_vol_opening * 1.2:
        risk = max(or_high - last["close"], last["close"] * 0.002)
        return {
            "direction": "SHORT",
            "entry": float(last["close"]),
            "sl": float(or_high),
            "target": float(last["close"] - risk * 2),
            "pattern": "ORB breakdown",
            "scanner": "orb",
        }
    return None


def scan_vwap(df: pd.DataFrame) -> dict[str, Any] | None:
    """VWAP reclaim (bull) or reject (bear) — 3-bar state flip."""
    if not _require_5m_bars(df, 6):
        return None
    vwap = _vwap(df)
    last = df.iloc[-1]
    prev3 = df.iloc[-4:-1]
    # Bull reclaim: prior 3 bars below VWAP, now closes back above.
    if (prev3["close"].values < vwap.iloc[-4:-1].values).all() and last["close"] > vwap.iloc[-1]:
        sl = float(prev3["low"].min())
        risk = max(last["close"] - sl, last["close"] * 0.002)
        return {
            "direction": "LONG",
            "entry": float(last["close"]),
            "sl": sl,
            "target": float(last["close"] + risk * 2),
            "pattern": "VWAP reclaim",
            "scanner": "vwap",
        }
    # Bear reject: prior 3 bars above VWAP, now closes back below.
    if (prev3["close"].values > vwap.iloc[-4:-1].values).all() and last["close"] < vwap.iloc[-1]:
        sl = float(prev3["high"].max())
        risk = max(sl - last["close"], last["close"] * 0.002)
        return {
            "direction": "SHORT",
            "entry": float(last["close"]),
            "sl": sl,
            "target": float(last["close"] - risk * 2),
            "pattern": "VWAP reject",
            "scanner": "vwap",
        }
    return None


def scan_momentum(df: pd.DataFrame) -> dict[str, Any] | None:
    """3 consecutive bars in the same direction with expanding volume."""
    if not _require_5m_bars(df, 4):
        return None
    recent = df.iloc[-3:]
    closes = recent["close"].values
    opens = recent["open"].values
    vols = recent["volume"].values
    bullish = bool((closes > opens).all() and vols[0] < vols[1] < vols[2])
    bearish = bool((closes < opens).all() and vols[0] < vols[1] < vols[2])
    last = recent.iloc[-1]
    if bullish:
        sl = float(recent["low"].min())
        risk = max(last["close"] - sl, last["close"] * 0.002)
        return {
            "direction": "LONG",
            "entry": float(last["close"]),
            "sl": sl,
            "target": float(last["close"] + risk * 2),
            "pattern": "5m momentum bull",
            "scanner": "momentum",
        }
    if bearish:
        sl = float(recent["high"].max())
        risk = max(sl - last["close"], last["close"] * 0.002)
        return {
            "direction": "SHORT",
            "entry": float(last["close"]),
            "sl": sl,
            "target": float(last["close"] - risk * 2),
            "pattern": "5m momentum bear",
            "scanner": "momentum",
        }
    return None


SCANNERS = (scan_orb, scan_vwap, scan_momentum)


# ── Intraday scan orchestrator ──────────────────────────────────

def run_scan() -> list[dict[str, Any]]:
    """Run every intraday scanner across the watchlist. Returns a list of
    candidate signal dicts (may be empty). Each entry has ticker, direction,
    entry, sl, target, rrr, pattern, scanner_count plus a timeframe tag.

    The RRR floor (settings.INTRADAY_RRR_FLOOR) and per-day cap
    (settings.INTRADAY_MAX_SIGNALS_PER_DAY) are enforced here — the caller
    still sees every hit for logging but only the top-N by scanner_count
    cross the cap. Dedup against OPEN intraday signals is the caller's job.
    """
    if not getattr(settings, "INTRADAY_SIGNALS_ENABLED", False):
        return []

    now = now_ist()
    market_time = now.time()
    if not (time(9, 15) <= market_time <= time(15, 15)):
        # Don't scan in the last 15 min — too close to close for intraday.
        return []
    if not is_market_open("NSE"):
        return []

    # Late imports so the module imports cleanly in tests where the data
    # provider / DB may be un-initialized.
    from mcp_server.data_provider import get_provider

    provider = get_provider()
    tickers = _watchlist()
    rrr_floor = float(getattr(settings, "INTRADAY_RRR_FLOOR", 2.0))
    max_per_day = int(getattr(settings, "INTRADAY_MAX_SIGNALS_PER_DAY", 5))

    candidates: list[dict[str, Any]] = []
    for ticker in tickers:
        try:
            df = provider.get_ohlcv(
                ticker, interval="5minute", days=1, exchange="NSE"
            )
        except Exception as fetch_err:
            logger.debug("Intraday fetch failed for %s: %s", ticker, fetch_err)
            continue
        if df is None or df.empty or len(df) < 4:
            continue

        # Normalize column case — different providers hand back mixed cases.
        df = df.rename(columns={c: c.lower() for c in df.columns})

        hits: list[dict[str, Any]] = []
        for scanner_fn in SCANNERS:
            try:
                hit = scanner_fn(df)
            except Exception as scan_err:
                logger.debug(
                    "Scanner %s failed for %s: %s",
                    scanner_fn.__name__, ticker, scan_err,
                )
                hit = None
            if hit:
                hits.append(hit)

        if not hits:
            continue

        # Prefer the hit whose direction matches the most scanners — if ORB
        # and momentum both fire LONG that's stronger than two conflicting
        # signals. Ties resolved by first hit (ORB > VWAP > momentum).
        long_hits = [h for h in hits if h["direction"] == "LONG"]
        short_hits = [h for h in hits if h["direction"] == "SHORT"]
        if len(long_hits) > len(short_hits):
            chosen = long_hits[0]
            scanner_count = len(long_hits)
        elif len(short_hits) > len(long_hits):
            chosen = short_hits[0]
            scanner_count = len(short_hits)
        else:
            # Conflicting signals → skip this ticker.
            continue

        entry = chosen["entry"]
        sl = chosen["sl"]
        target = chosen["target"]
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        rrr = round(abs(target - entry) / risk, 2)
        if rrr < rrr_floor:
            continue

        candidates.append({
            "ticker": ticker,
            "exchange": "NSE",
            "asset_class": "EQUITY",
            "direction": chosen["direction"],
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "target": round(target, 2),
            "rrr": rrr,
            "qty": 0,  # caller sizes via RRMS
            "pattern": chosen["pattern"],
            "scanner_count": scanner_count,
            "timeframe": "5m",
            "source": "intraday",
        })

    # Sort by scanner_count desc, then tighter SL first.
    candidates.sort(key=lambda c: (-c["scanner_count"], abs(c["entry"] - c["sl"])))
    logger.info(
        "[INTRADAY] %d candidates pass RRR>=%.1f (watchlist=%d)",
        len(candidates), rrr_floor, len(tickers),
    )
    return candidates[:max_per_day]


__all__ = ["run_scan", "DEFAULT_WATCHLIST", "scan_orb", "scan_vwap", "scan_momentum"]
