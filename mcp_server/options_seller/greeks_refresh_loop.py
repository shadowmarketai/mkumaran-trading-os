"""
MKUMARAN Trading OS — Options Seller: Background Greeks Refresh Loop

Runs as an asyncio background task (via FastAPI lifespan) during market
hours. Every `interval_s` seconds it:

  1. Fetches the spot price for each instrument that has an OPEN position
  2. Fetches the live options chain for those instruments
  3. Calls position_manager.run_scan(spot_lookup, chain_lookup)
  4. Any non-HOLD decisions are logged (Telegram alert is sent from
     inside refresh_greeks — no duplicate alert here)

This removes the n8n dependency for intraday adjustment monitoring.
The n8n workflow (06_options_seller_monitor.json) continues to run for
the morning IV report and entry signals; this loop handles the
per-position Greeks refresh that must run every few minutes.

Design
──────
  - Runs only during NSE market hours (09:15–15:30 IST, Mon–Fri)
  - Skips when no OPEN positions exist (DB check before fetching quotes)
  - Catches and logs all exceptions — never kills the FastAPI process
  - Can be disabled via env: OPTIONS_GREEKS_LOOP_ENABLED=false

Usage (already wired in mcp_server.py lifespan if enabled):
  from mcp_server.options_seller.greeks_refresh_loop import start_loop
  task = asyncio.create_task(start_loop())
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from mcp_server.config import settings

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))

# Refresh interval during market hours (seconds)
REFRESH_INTERVAL_S = int(getattr(settings, "OPTIONS_GREEKS_INTERVAL_S", 300))  # 5 min default

# Market hours (IST)
_MARKET_OPEN  = (9, 15)
_MARKET_CLOSE = (15, 30)


def _is_market_hours() -> bool:
    now = datetime.now(_IST)
    if now.weekday() >= 5:   # Saturday, Sunday
        return False
    t = (now.hour, now.minute)
    return _MARKET_OPEN <= t <= _MARKET_CLOSE


def _fetch_spot(instrument: str) -> float:
    """Fetch current spot price for an index instrument via yfinance fallback."""
    yf_map = {
        "BANKNIFTY":  "^NSEBANK",
        "NIFTY":      "^NSEI",
        "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
        "FINNIFTY":   "NIFTY_FIN_SERVICE.NS",
        "SENSEX":     "^BSESN",
        "BANKEX":     "^BSE-BANKEX",
    }
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        quote = provider.nse.get_quote(instrument)
        if quote and isinstance(quote, dict):
            price = float(quote.get("lastPrice", quote.get("ltp", 0)) or 0)
            if price > 0:
                return price
    except Exception:
        pass

    try:
        import yfinance as yf
        ticker = yf_map.get(instrument.upper(), f"{instrument}.NS")
        df = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df is not None and not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.debug("yfinance spot fetch failed for %s: %s", instrument, e)

    return 0.0


def _fetch_chain(instrument: str) -> dict:
    """Fetch live options chain for an instrument."""
    try:
        from mcp_server.options_selector import get_options_chain
        return get_options_chain(instrument) or {}
    except Exception as e:
        logger.debug("Chain fetch failed for %s: %s", instrument, e)
        return {}


def _get_open_instruments() -> list[str]:
    """Return distinct instruments that have OPEN options seller positions."""
    try:
        from mcp_server.options_seller.position_manager import _fetch_open_positions
        rows = _fetch_open_positions()
        return list({inst for _, inst in rows})
    except Exception as e:
        logger.debug("Could not fetch open instruments: %s", e)
        return []


async def _one_refresh_cycle() -> None:
    """Run one Greeks refresh cycle for all open positions."""
    instruments = await asyncio.to_thread(_get_open_instruments)
    if not instruments:
        return   # nothing to refresh

    logger.info("Options Greeks refresh: %d instruments with open positions", len(instruments))

    # Fetch spots + chains concurrently
    spot_lookup: dict[str, float] = {}
    chain_lookup: dict[str, dict] = {}

    async def _fetch_one(inst: str) -> None:
        spot  = await asyncio.to_thread(_fetch_spot, inst)
        chain = await asyncio.to_thread(_fetch_chain, inst)
        spot_lookup[inst]  = spot
        chain_lookup[inst] = chain

    await asyncio.gather(*[_fetch_one(inst) for inst in instruments])

    from mcp_server.options_seller.position_manager import run_scan
    decisions = await asyncio.to_thread(run_scan, spot_lookup, chain_lookup)

    if decisions:
        logger.warning(
            "Options Greeks refresh: %d positions need action: %s",
            len(decisions),
            [f"{d['instrument']} → {d['action']}" for d in decisions],
        )


async def start_loop() -> None:
    """Background loop — runs while the FastAPI process is alive.

    Skips cycles outside market hours. Catches all exceptions.
    Call via asyncio.create_task(start_loop()) in the lifespan.
    """
    enabled = getattr(settings, "OPTIONS_GREEKS_LOOP_ENABLED", "true").lower() != "false"
    if not enabled:
        logger.info("Options Greeks refresh loop disabled (OPTIONS_GREEKS_LOOP_ENABLED=false)")
        return

    logger.info(
        "Options Greeks refresh loop started (interval=%ds, market hours only)",
        REFRESH_INTERVAL_S,
    )

    while True:
        try:
            if _is_market_hours():
                await _one_refresh_cycle()
        except Exception as e:
            logger.exception("Options Greeks refresh loop error: %s", e)

        await asyncio.sleep(REFRESH_INTERVAL_S)
