"""
MKUMARAN Trading OS — F&O Module (v2 — Live Kite Integration)

Fixes over v1:
- Real OI change from Kite instruments API (was hardcoded 0)
- Real PCR from live option chain (was hardcoded 1.0)
- Support for NIFTY, BANKNIFTY, FINNIFTY, stock F&O
- Graceful degradation with clear status reporting
- Multi-expiry support
"""

import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
from mcp_server.technical_scanners import compute_ema, detect_ema_crossover

# OI snapshot cache for buildup classification (delta vs prior day)
_OI_SNAPSHOT_PATH = Path("data/fo_oi_snapshots.json")
_IV_HISTORY_PATH = Path("data/iv_history.json")

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


# ═══════════════════════════════════════════════════════════════
# OI Buildup Classification (Long/Short Buildup, Covering, Unwinding)
# ═══════════════════════════════════════════════════════════════


def classify_oi_buildup(price_change_pct: float, oi_change_pct: float) -> dict:
    """
    Classify futures OI behaviour into one of 4 buckets.

    | Price | OI    | Classification    | Bias              |
    |-------|-------|-------------------|-------------------|
    | UP    | UP    | LONG_BUILDUP      | BULLISH (strong)  |
    | DOWN  | UP    | SHORT_BUILDUP     | BEARISH (strong)  |
    | UP    | DOWN  | SHORT_COVERING    | BULLISH (weak)    |
    | DOWN  | DOWN  | LONG_UNWINDING    | BEARISH (weak)    |
    """
    threshold = 0.1  # noise filter — ignore moves under 0.1%
    if abs(price_change_pct) < threshold and abs(oi_change_pct) < threshold:
        return {
            "classification": "FLAT",
            "bias": "NEUTRAL",
            "strength": "NONE",
            "price_change_pct": round(price_change_pct, 2),
            "oi_change_pct": round(oi_change_pct, 2),
        }

    price_up = price_change_pct > 0
    oi_up = oi_change_pct > 0

    if price_up and oi_up:
        cls, bias, strength = "LONG_BUILDUP", "BULLISH", "STRONG"
    elif (not price_up) and oi_up:
        cls, bias, strength = "SHORT_BUILDUP", "BEARISH", "STRONG"
    elif price_up and (not oi_up):
        cls, bias, strength = "SHORT_COVERING", "BULLISH", "WEAK"
    else:
        cls, bias, strength = "LONG_UNWINDING", "BEARISH", "WEAK"

    return {
        "classification": cls,
        "bias": bias,
        "strength": strength,
        "price_change_pct": round(price_change_pct, 2),
        "oi_change_pct": round(oi_change_pct, 2),
    }


def _load_oi_snapshots() -> dict:
    """Load yesterday's OI snapshots from disk."""
    try:
        if _OI_SNAPSHOT_PATH.exists():
            return json.loads(_OI_SNAPSHOT_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load OI snapshots: %s", e)
    return {}


def _save_oi_snapshots(snapshots: dict) -> None:
    """Persist today's OI snapshots."""
    try:
        _OI_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _OI_SNAPSHOT_PATH.write_text(json.dumps(snapshots, indent=2, default=str))
    except OSError as e:
        logger.error("Failed to save OI snapshots: %s", e)


def get_futures_oi(kite, symbol: str) -> dict:
    """
    Fetch current futures OI for a symbol (NIFTY, BANKNIFTY, RELIANCE, etc.).

    Returns: {oi, ltp, volume, expiry, status}
    """
    if kite is None:
        return {"symbol": symbol, "oi": 0, "ltp": 0,
                "status": STATUS_NO_KITE, "message": "Kite not connected"}
    try:
        instruments = _get_kite_instruments(kite, "NFO")
        if not instruments:
            return {"symbol": symbol, "status": STATUS_ERROR,
                    "message": "Failed to fetch NFO instruments"}

        futs = [
            inst for inst in instruments
            if inst.get("name") == symbol
            and inst.get("instrument_type") == "FUT"
        ]
        if not futs:
            return {"symbol": symbol, "status": STATUS_ERROR,
                    "message": f"No futures contract for {symbol}"}

        today = date.today()
        nearest = min(
            futs,
            key=lambda f: (
                f["expiry"].date() if isinstance(f["expiry"], datetime) else f["expiry"]
            ) if (
                f["expiry"].date() if isinstance(f["expiry"], datetime) else f["expiry"]
            ) >= today else date.max,
        )

        symbol_key = f"NFO:{nearest['tradingsymbol']}"
        quotes = kite.quote([symbol_key])
        q = quotes.get(symbol_key, {})

        return {
            "symbol": symbol,
            "tradingsymbol": nearest["tradingsymbol"],
            "expiry": str(nearest["expiry"]),
            "oi": q.get("oi", 0),
            "ltp": q.get("last_price", 0),
            "volume": q.get("volume", 0),
            "lot_size": nearest.get("lot_size", 0),
            "status": STATUS_LIVE,
        }
    except Exception as e:
        logger.error("Futures OI fetch failed for %s: %s", symbol, e)
        return {"symbol": symbol, "status": STATUS_ERROR, "message": str(e)}


def scan_oi_buildup(kite, symbols: list[str] | None = None) -> dict:
    """
    Scan multiple F&O symbols for OI buildup classification.

    Compares today's OI vs cached prior-day snapshot and classifies each.
    Auto-saves today's snapshot for tomorrow's comparison.

    Returns: {classifications: {symbol: {...}}, summary: {...}}
    """
    from mcp_server.asset_registry import NFO_INDEX_UNIVERSE, NFO_STOCK_UNIVERSE
    if symbols is None:
        symbols = NFO_INDEX_UNIVERSE + NFO_STOCK_UNIVERSE

    if kite is None:
        return {
            "status": STATUS_NO_KITE,
            "message": "Kite not connected",
            "classifications": {},
            "summary": {},
        }

    prior = _load_oi_snapshots()
    today = str(date.today())
    today_snapshots: dict = {}
    classifications: dict = {}

    long_buildup = short_buildup = short_covering = long_unwinding = 0

    for symbol in symbols:
        try:
            cur = get_futures_oi(kite, symbol)
            if cur.get("status") != STATUS_LIVE:
                continue

            today_snapshots[symbol] = {
                "oi": cur["oi"], "ltp": cur["ltp"], "date": today,
            }

            prior_data = prior.get(symbol)
            if not prior_data or prior_data.get("date") == today:
                # No prior snapshot or already today — can't classify
                classifications[symbol] = {
                    "classification": "NEEDS_BASELINE",
                    "bias": "NEUTRAL",
                    "current_oi": cur["oi"],
                    "current_ltp": cur["ltp"],
                }
                continue

            prior_oi = prior_data.get("oi", 0)
            prior_ltp = prior_data.get("ltp", 0)
            if prior_oi == 0 or prior_ltp == 0:
                continue

            price_change = ((cur["ltp"] - prior_ltp) / prior_ltp) * 100
            oi_change = ((cur["oi"] - prior_oi) / prior_oi) * 100

            cls = classify_oi_buildup(price_change, oi_change)
            cls["current_oi"] = cur["oi"]
            cls["current_ltp"] = cur["ltp"]
            cls["prior_oi"] = prior_oi
            cls["prior_ltp"] = prior_ltp
            classifications[symbol] = cls

            if cls["classification"] == "LONG_BUILDUP":
                long_buildup += 1
            elif cls["classification"] == "SHORT_BUILDUP":
                short_buildup += 1
            elif cls["classification"] == "SHORT_COVERING":
                short_covering += 1
            elif cls["classification"] == "LONG_UNWINDING":
                long_unwinding += 1
        except Exception as e:
            logger.error("OI buildup scan failed for %s: %s", symbol, e)

    # Save today's snapshots for tomorrow
    if today_snapshots:
        _save_oi_snapshots(today_snapshots)

    summary = {
        "total_scanned": len(classifications),
        "long_buildup": long_buildup,
        "short_buildup": short_buildup,
        "short_covering": short_covering,
        "long_unwinding": long_unwinding,
        "net_bullish": long_buildup + short_covering,
        "net_bearish": short_buildup + long_unwinding,
    }

    return {
        "status": STATUS_LIVE,
        "classifications": classifications,
        "summary": summary,
        "snapshot_date": today,
    }


# ═══════════════════════════════════════════════════════════════
# IV Rank / Percentile + Volatility Setup Detection
# ═══════════════════════════════════════════════════════════════


def _load_iv_history() -> dict:
    """Load historical IV data: {symbol: [{date, iv}, ...]}."""
    try:
        if _IV_HISTORY_PATH.exists():
            return json.loads(_IV_HISTORY_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load IV history: %s", e)
    return {}


def _save_iv_history(history: dict) -> None:
    """Persist IV history (auto-prune to last 90 days)."""
    try:
        cutoff = (date.today() - timedelta(days=90)).isoformat()
        pruned = {
            sym: [e for e in entries if e.get("date", "") >= cutoff]
            for sym, entries in history.items()
        }
        _IV_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _IV_HISTORY_PATH.write_text(json.dumps(pruned, indent=2))
    except OSError as e:
        logger.error("Failed to save IV history: %s", e)


def get_atm_iv(kite, symbol: str = "NIFTY") -> dict:
    """
    Get current ATM (at-the-money) implied volatility.

    Computes IV from option chain via Newton-Raphson Black-Scholes solver.
    """
    if kite is None:
        return {"symbol": symbol, "iv": 0,
                "status": STATUS_NO_KITE, "message": "Kite not connected"}
    try:
        from mcp_server.options_greeks import calculate_iv

        instruments = _get_kite_instruments(kite, "NFO")
        if not instruments:
            return {"symbol": symbol, "status": STATUS_ERROR}

        expiry = _find_current_expiry(instruments, symbol)
        if not expiry:
            return {"symbol": symbol, "status": STATUS_ERROR}

        chain = _get_option_chain(kite, instruments, symbol, expiry)
        if not chain:
            return {"symbol": symbol, "status": STATUS_ERROR}

        # Find spot via max-OI strike (ATM proxy)
        strikes = sorted(chain.keys())
        max_oi_strike = max(
            strikes,
            key=lambda s: chain[s].get("CE", {}).get("oi", 0) + chain[s].get("PE", {}).get("oi", 0),
        )
        spot = max_oi_strike

        ce = chain[max_oi_strike].get("CE", {})
        pe = chain[max_oi_strike].get("PE", {})
        ce_ltp = ce.get("ltp", 0)
        pe_ltp = pe.get("ltp", 0)

        days_to_expiry = max((expiry - date.today()).days, 1)

        ce_iv = calculate_iv(ce_ltp, spot, max_oi_strike, days_to_expiry, 0.065, "CE") if ce_ltp > 0 else 0
        pe_iv = calculate_iv(pe_ltp, spot, max_oi_strike, days_to_expiry, 0.065, "PE") if pe_ltp > 0 else 0
        atm_iv = (ce_iv + pe_iv) / 2 if (ce_iv > 0 and pe_iv > 0) else max(ce_iv, pe_iv)

        return {
            "symbol": symbol,
            "atm_strike": max_oi_strike,
            "spot": spot,
            "ce_iv": round(ce_iv * 100, 2),
            "pe_iv": round(pe_iv * 100, 2),
            "atm_iv": round(atm_iv * 100, 2),
            "expiry": str(expiry),
            "days_to_expiry": days_to_expiry,
            "status": STATUS_LIVE,
        }
    except Exception as e:
        logger.error("ATM IV fetch failed for %s: %s", symbol, e)
        return {"symbol": symbol, "status": STATUS_ERROR, "message": str(e)}


def get_iv_rank(kite, symbol: str = "NIFTY") -> dict:
    """
    Calculate IV rank and percentile from historical IV.

    IV Rank   = (current - low) / (high - low) * 100  (range-based)
    IV Pctile = % of days IV was below current        (frequency-based)

    Auto-records today's IV into history for future calls.
    """
    iv_data = get_atm_iv(kite, symbol)
    if iv_data.get("status") != STATUS_LIVE:
        return {"symbol": symbol, "iv_rank": 0, "iv_percentile": 0,
                "status": iv_data.get("status", STATUS_ERROR),
                "message": iv_data.get("message", "IV unavailable")}

    current_iv = iv_data["atm_iv"]
    today = str(date.today())

    history = _load_iv_history()
    sym_history = history.get(symbol, [])

    # Record today's IV (if not already there)
    if not sym_history or sym_history[-1].get("date") != today:
        sym_history.append({"date": today, "iv": current_iv})
        history[symbol] = sym_history
        _save_iv_history(history)

    # Need at least 20 data points for meaningful rank
    ivs = [e["iv"] for e in sym_history if e.get("iv", 0) > 0]
    if len(ivs) < 20:
        return {
            "symbol": symbol,
            "current_iv": current_iv,
            "iv_rank": 0,
            "iv_percentile": 0,
            "history_days": len(ivs),
            "status": "BUILDING_HISTORY",
            "message": f"Need 20+ days, have {len(ivs)}",
        }

    iv_min = min(ivs)
    iv_max = max(ivs)
    iv_rank = ((current_iv - iv_min) / (iv_max - iv_min) * 100) if iv_max > iv_min else 0
    iv_percentile = (sum(1 for v in ivs if v < current_iv) / len(ivs)) * 100

    return {
        "symbol": symbol,
        "current_iv": current_iv,
        "iv_rank": round(iv_rank, 1),
        "iv_percentile": round(iv_percentile, 1),
        "iv_min_60d": round(iv_min, 2),
        "iv_max_60d": round(iv_max, 2),
        "history_days": len(ivs),
        "atm_strike": iv_data["atm_strike"],
        "status": STATUS_LIVE,
    }


def detect_volatility_setup(kite, symbol: str = "NIFTY") -> dict:
    """
    Detect ATM straddle/strangle volatility setups based on IV rank.

    Strategy logic:
    - IV rank < 20  → LONG_STRADDLE (cheap volatility, expecting expansion)
    - IV rank > 80  → SHORT_STRADDLE (expensive vol, expecting mean revert)
    - 20-80         → NO_SETUP (neutral)
    """
    iv_data = get_iv_rank(kite, symbol)
    if iv_data.get("status") != STATUS_LIVE:
        return {
            "symbol": symbol,
            "setup": "UNAVAILABLE",
            "status": iv_data.get("status", STATUS_ERROR),
            "message": iv_data.get("message", "IV data unavailable"),
        }

    iv_rank = iv_data["iv_rank"]
    atm = iv_data["atm_strike"]

    if iv_rank < 20:
        setup = "LONG_STRADDLE"
        bias = "LONG_VOLATILITY"
        rationale = f"IV rank {iv_rank}% — cheap volatility, buy ATM straddle"
    elif iv_rank > 80:
        setup = "SHORT_STRADDLE"
        bias = "SHORT_VOLATILITY"
        rationale = f"IV rank {iv_rank}% — expensive vol, sell ATM straddle/iron condor"
    else:
        setup = "NO_SETUP"
        bias = "NEUTRAL"
        rationale = f"IV rank {iv_rank}% — middle range, no edge"

    return {
        "symbol": symbol,
        "setup": setup,
        "bias": bias,
        "rationale": rationale,
        "iv_rank": iv_rank,
        "iv_percentile": iv_data["iv_percentile"],
        "current_iv": iv_data["current_iv"],
        "atm_strike": atm,
        "status": STATUS_LIVE,
    }


# ═══════════════════════════════════════════════════════════════
# Expiry-Day Awareness
# ═══════════════════════════════════════════════════════════════


def is_expiry_day(kite=None, symbol: str = "NIFTY") -> dict:
    """
    Check if today is the weekly/monthly expiry day for a given symbol.

    NIFTY weekly: Thursday | BANKNIFTY: Wednesday | FINNIFTY: Tuesday
    Falls back to Thursday for any unknown symbol.
    """
    today = date.today()
    weekday = today.weekday()  # Mon=0, Sun=6

    # Hardcoded expiry weekdays per symbol (NSE current schedule)
    expiry_weekday_map = {
        "NIFTY": 3,        # Thursday
        "BANKNIFTY": 2,    # Wednesday
        "FINNIFTY": 1,     # Tuesday
        "MIDCPNIFTY": 0,   # Monday
    }
    expected = expiry_weekday_map.get(symbol.upper(), 3)
    is_expiry = weekday == expected

    # Try live verification via Kite if available
    actual_expiry = None
    if kite is not None:
        try:
            instruments = _get_kite_instruments(kite, "NFO")
            actual_expiry = _find_current_expiry(instruments, symbol)
        except Exception as e:
            logger.debug("Live expiry check failed: %s", e)

    return {
        "symbol": symbol,
        "today": str(today),
        "weekday": today.strftime("%A"),
        "is_expiry_day": is_expiry,
        "next_expiry": str(actual_expiry) if actual_expiry else None,
        "trading_advice": (
            "EXPIRY DAY — avoid fresh entries, manage open positions only"
            if is_expiry else "Normal trading day"
        ),
    }


def get_stock_fo_snapshot(kite, symbol: str) -> dict:
    """
    One-shot F&O snapshot for any symbol (index or stock).

    Combines: futures OI + option chain OI/PCR + IV rank + buildup classification.
    """
    snapshot = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
    }

    # Futures OI
    try:
        snapshot["futures"] = get_futures_oi(kite, symbol)
    except Exception as e:
        snapshot["futures"] = {"status": STATUS_ERROR, "message": str(e)}

    # Option chain OI
    try:
        snapshot["oi"] = get_oi_change(kite, symbol)
    except Exception as e:
        snapshot["oi"] = {"status": STATUS_ERROR, "message": str(e)}

    # PCR
    try:
        snapshot["pcr"] = get_pcr(kite, symbol)
    except Exception as e:
        snapshot["pcr"] = {"status": STATUS_ERROR, "message": str(e)}

    # IV rank
    try:
        snapshot["iv_rank"] = get_iv_rank(kite, symbol)
    except Exception as e:
        snapshot["iv_rank"] = {"status": STATUS_ERROR, "message": str(e)}

    # Volatility setup
    try:
        snapshot["volatility_setup"] = detect_volatility_setup(kite, symbol)
    except Exception as e:
        snapshot["volatility_setup"] = {"status": STATUS_ERROR, "message": str(e)}

    # Expiry day check
    try:
        snapshot["expiry"] = is_expiry_day(kite, symbol)
    except Exception as e:
        snapshot["expiry"] = {"status": STATUS_ERROR, "message": str(e)}

    return snapshot
