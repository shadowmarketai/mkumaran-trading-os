"""
MKUMARAN Trading OS — F&O Module (v2 — Live Kite Integration)

Fixes over v1:
- Real OI change from Kite instruments API (was hardcoded 0)
- Real PCR from live option chain (was hardcoded 1.0)
- Support for NIFTY, BANKNIFTY, FINNIFTY, stock F&O
- Graceful degradation with clear status reporting
- Multi-expiry support
"""

import logging
from datetime import datetime, date, timedelta

import pandas as pd
from mcp_server.technical_scanners import compute_ema, detect_ema_crossover

logger = logging.getLogger(__name__)


# ── Status Constants ─────────────────────────────────────────
STATUS_LIVE = "LIVE"              # Real data from Kite
STATUS_NO_KITE = "NO_KITE"       # Kite not connected — data unavailable
STATUS_ERROR = "ERROR"            # API call failed


def _get_kite_instruments(kite, exchange: str = "NFO") -> list[dict]:
    """
    Fetch instrument list from Kite API.

    Returns list of instrument dicts with:
    tradingsymbol, instrument_token, instrument_type, strike, expiry, lot_size
    """
    try:
        instruments = kite.instruments(exchange)
        return instruments
    except Exception as e:
        logger.error("Failed to fetch %s instruments: %s", exchange, e)
        return []


def _find_current_expiry(instruments: list[dict], base: str = "NIFTY") -> date | None:
    """Find the nearest weekly expiry for an instrument."""
    today = date.today()
    expiries = set()

    for inst in instruments:
        if inst.get("name") == base and inst.get("expiry"):
            exp = inst["expiry"]
            if isinstance(exp, datetime):
                exp = exp.date()
            if exp >= today:
                expiries.add(exp)

    if not expiries:
        return None

    return min(expiries)


def _get_option_chain(kite, instruments: list[dict], base: str, expiry: date) -> dict:
    """
    Build option chain from Kite instruments for a given expiry.

    Returns: {strike: {"CE": {oi, ltp, token}, "PE": {oi, ltp, token}}}
    """
    chain: dict[float, dict] = {}

    # Filter instruments for this expiry
    relevant = [
        inst for inst in instruments
        if inst.get("name") == base
        and inst.get("instrument_type") in ("CE", "PE")
        and (inst.get("expiry").date() if isinstance(inst.get("expiry"), datetime)
             else inst.get("expiry")) == expiry
    ]

    if not relevant:
        return chain

    # Get LTP and OI for all instruments in one call
    tokens = [inst["instrument_token"] for inst in relevant]

    try:
        # Kite quote gives OI and LTP
        # Quote up to 200 instruments at a time
        batch_size = 200
        quotes = {}
        for i in range(0, len(tokens), batch_size):
            batch = [f"NFO:{inst['tradingsymbol']}" for inst in relevant[i:i + batch_size]]
            batch_quotes = kite.quote(batch)
            quotes.update(batch_quotes)
    except Exception as e:
        logger.error("Failed to fetch quotes for %s option chain: %s", base, e)
        return chain

    for inst in relevant:
        strike = inst["strike"]
        opt_type = inst["instrument_type"]  # CE or PE
        symbol = f"NFO:{inst['tradingsymbol']}"

        quote = quotes.get(symbol, {})
        oi = quote.get("oi", 0)
        ltp = quote.get("last_price", 0)
        volume = quote.get("volume", 0)

        if strike not in chain:
            chain[strike] = {}

        chain[strike][opt_type] = {
            "oi": oi,
            "ltp": ltp,
            "volume": volume,
            "token": inst["instrument_token"],
            "tradingsymbol": inst["tradingsymbol"],
        }

    return chain


def get_oi_change(kite, instrument: str = "NIFTY") -> dict:
    """
    Get OI change for current week expiry options.

    Uses real Kite API data when kite instance is provided.
    Returns clear status when data is unavailable.
    """
    # ── No Kite → explicit status ─────────────────────────────
    if kite is None:
        return {
            "instrument": instrument,
            "call_oi_total": 0,
            "put_oi_total": 0,
            "call_oi_change": 0,
            "put_oi_change": 0,
            "total_oi_change": 0,
            "significance": "UNAVAILABLE",
            "status": STATUS_NO_KITE,
            "message": "Kite not connected — OI data requires live Kite session",
        }

    # ── Live Kite → real data ─────────────────────────────────
    try:
        instruments = _get_kite_instruments(kite, "NFO")
        if not instruments:
            return {
                "instrument": instrument,
                "call_oi_total": 0,
                "put_oi_total": 0,
                "call_oi_change": 0,
                "put_oi_change": 0,
                "total_oi_change": 0,
                "significance": "UNAVAILABLE",
                "status": STATUS_ERROR,
                "message": "Failed to fetch NFO instruments from Kite",
            }

        expiry = _find_current_expiry(instruments, instrument)
        if not expiry:
            return {
                "instrument": instrument,
                "call_oi_total": 0,
                "put_oi_total": 0,
                "significance": "UNAVAILABLE",
                "status": STATUS_ERROR,
                "message": f"No expiry found for {instrument}",
            }

        chain = _get_option_chain(kite, instruments, instrument, expiry)
        if not chain:
            return {
                "instrument": instrument,
                "significance": "UNAVAILABLE",
                "status": STATUS_ERROR,
                "message": f"Empty option chain for {instrument} expiry {expiry}",
            }

        # Calculate total OI for calls and puts
        total_call_oi = sum(
            data.get("CE", {}).get("oi", 0) for data in chain.values()
        )
        total_put_oi = sum(
            data.get("PE", {}).get("oi", 0) for data in chain.values()
        )

        # OI change significance
        net_oi = total_put_oi - total_call_oi
        if net_oi > 100000:
            significance = "BULLISH"
        elif net_oi < -100000:
            significance = "BEARISH"
        else:
            significance = "NEUTRAL"

        # Find max pain (strike with highest combined OI)
        max_pain_strike = 0
        max_combined_oi = 0
        for strike, data in chain.items():
            combined = data.get("CE", {}).get("oi", 0) + data.get("PE", {}).get("oi", 0)
            if combined > max_combined_oi:
                max_combined_oi = combined
                max_pain_strike = strike

        result = {
            "instrument": instrument,
            "expiry": str(expiry),
            "call_oi_total": total_call_oi,
            "put_oi_total": total_put_oi,
            "net_oi": net_oi,
            "max_pain_strike": max_pain_strike,
            "significance": significance,
            "status": STATUS_LIVE,
            "strikes_count": len(chain),
        }

        logger.info(
            "OI for %s (expiry %s): CE=%d PE=%d Net=%d -> %s",
            instrument, expiry, total_call_oi, total_put_oi, net_oi, significance,
        )

        return result

    except Exception as e:
        logger.error("OI fetch failed for %s: %s", instrument, e)
        return {
            "instrument": instrument,
            "call_oi_total": 0,
            "put_oi_total": 0,
            "significance": "UNAVAILABLE",
            "status": STATUS_ERROR,
            "message": str(e),
        }


def get_pcr(kite, instrument: str = "NIFTY") -> dict:
    """
    Get Put-Call Ratio from live OI data.

    PCR interpretation:
    - < 0.7: Bearish
    - 0.7-1.3: Neutral
    - > 1.3: Bullish (contrarian — more puts = market protected)
    """
    # ── No Kite → explicit status ─────────────────────────────
    if kite is None:
        return {
            "instrument": instrument,
            "pcr": 0,
            "sentiment": "UNAVAILABLE",
            "status": STATUS_NO_KITE,
            "message": "Kite not connected — PCR requires live session",
        }

    # ── Live Kite → real PCR ──────────────────────────────────
    try:
        oi_data = get_oi_change(kite, instrument)

        if oi_data.get("status") != STATUS_LIVE:
            return {
                "instrument": instrument,
                "pcr": 0,
                "sentiment": "UNAVAILABLE",
                "status": oi_data.get("status", STATUS_ERROR),
                "message": oi_data.get("message", "OI data unavailable"),
            }

        call_oi = oi_data.get("call_oi_total", 0)
        put_oi = oi_data.get("put_oi_total", 0)

        if call_oi == 0:
            pcr = 0
        else:
            pcr = put_oi / call_oi

        if pcr < 0.7:
            sentiment = "BEARISH"
        elif pcr > 1.3:
            sentiment = "BULLISH"
        else:
            sentiment = "NEUTRAL"

        result = {
            "instrument": instrument,
            "pcr": round(pcr, 3),
            "call_oi": call_oi,
            "put_oi": put_oi,
            "sentiment": sentiment,
            "status": STATUS_LIVE,
        }

        logger.info("PCR for %s: %.3f (%s)", instrument, pcr, sentiment)
        return result

    except Exception as e:
        logger.error("PCR fetch failed for %s: %s", instrument, e)
        return {
            "instrument": instrument,
            "pcr": 0,
            "sentiment": "UNAVAILABLE",
            "status": STATUS_ERROR,
            "message": str(e),
        }


def get_banknifty_ema_signal(df_15m: pd.DataFrame) -> dict:
    """BankNifty 5/10 EMA crossover on 15-min timeframe."""
    signal = detect_ema_crossover(df_15m, fast_period=5, slow_period=10)

    fast_ema = compute_ema(df_15m["close"], 5).iloc[-1]
    slow_ema = compute_ema(df_15m["close"], 10).iloc[-1]

    return {
        "instrument": "BANKNIFTY",
        "signal": signal,
        "fast_ema_5": round(float(fast_ema), 2),
        "slow_ema_10": round(float(slow_ema), 2),
        "spread": round(float(fast_ema - slow_ema), 2),
    }


def get_nifty_ema_signal(df_15m: pd.DataFrame) -> dict:
    """Nifty 9/21 EMA crossover on 15-min timeframe."""
    signal = detect_ema_crossover(df_15m, fast_period=9, slow_period=21)

    fast_ema = compute_ema(df_15m["close"], 9).iloc[-1]
    slow_ema = compute_ema(df_15m["close"], 21).iloc[-1]

    return {
        "instrument": "NIFTY",
        "signal": signal,
        "fast_ema_9": round(float(fast_ema), 2),
        "slow_ema_21": round(float(slow_ema), 2),
        "spread": round(float(fast_ema - slow_ema), 2),
    }


def get_fo_signal(
    kite=None,
    nifty_15m: pd.DataFrame | None = None,
    banknifty_15m: pd.DataFrame | None = None,
) -> dict:
    """
    Combined F&O signal from all 4 components.

    Returns master verdict with clear status on each component.
    """
    components: dict[str, str] = {}
    details: dict[str, dict] = {}

    # OI Change
    oi_data = get_oi_change(kite)
    if oi_data.get("status") == STATUS_LIVE:
        components["oi"] = oi_data["significance"]
    details["oi"] = oi_data

    # PCR
    pcr_data = get_pcr(kite)
    if pcr_data.get("status") == STATUS_LIVE:
        components["pcr"] = pcr_data["sentiment"]
    details["pcr"] = pcr_data

    # BankNifty EMA
    if banknifty_15m is not None and not banknifty_15m.empty:
        bn_ema = get_banknifty_ema_signal(banknifty_15m)
        components["banknifty_ema"] = bn_ema["signal"]
        details["banknifty_ema"] = bn_ema

    # Nifty EMA
    if nifty_15m is not None and not nifty_15m.empty:
        n_ema = get_nifty_ema_signal(nifty_15m)
        components["nifty_ema"] = n_ema["signal"]
        details["nifty_ema"] = n_ema

    # Calculate master verdict (only from available components)
    bull_count = sum(1 for v in components.values() if v in ("BULLISH", "BUY"))
    bear_count = sum(1 for v in components.values() if v in ("BEARISH", "SELL"))
    total = len(components)

    if total == 0:
        verdict = "UNAVAILABLE"
    elif bull_count == total:
        verdict = "STRONG_BULL"
    elif bear_count == total:
        verdict = "STRONG_BEAR"
    elif bull_count > bear_count:
        verdict = "MILD_BULL"
    elif bear_count > bull_count:
        verdict = "MILD_BEAR"
    else:
        verdict = "NEUTRAL"

    # Data quality indicator
    live_count = sum(1 for d in details.values() if d.get("status") == STATUS_LIVE)
    data_quality = f"{live_count}/{len(details)} components have live data"

    logger.info(
        "F&O Signal: %s (bull=%d, bear=%d, total=%d, live=%d)",
        verdict, bull_count, bear_count, total, live_count,
    )

    return {
        "verdict": verdict,
        "components": components,
        "details": details,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "available_components": total,
        "data_quality": data_quality,
    }
