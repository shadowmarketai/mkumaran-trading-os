"""Options — Greeks, chain, payoff, strategies, recommendation.

Extracted from mcp_server.mcp_server in Phase 2a of the router split.
Per operator decision §9.3 of docs/MCP_SERVER_ROUTER_SPLIT_PLAN.md,
options/ splits from fno/ into its own router.

8 routes migrated:
  - Options math (Greeks, chain, payoff, strategies) — all pure-python,
    no broker dependency.
  - Option recommendation — needs Kite (uses deferred _get_kite_for_fo).

The strategy preset catalog + payoff-request models move with these
routes because they have no other consumers. The option-recommendation
handler references mcp_server.settings.RRMS_MIN_RRR for target sizing.
"""
import asyncio
import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from mcp_server.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["options"])


# ── Request models ─────────────────────────────────────────────────


class GreeksRequest(BaseModel):
    spot: float
    strike: float
    expiry_days: float
    rate: float = 0.065
    volatility: float = 0.20
    option_type: str = "CE"


class OptionChainRequest(BaseModel):
    spot: float
    expiry_days: float
    strike_start: float = 0
    strike_end: float = 0
    strike_step: float = 50
    rate: float = 0.065


class PayoffLegInput(BaseModel):
    strike: float
    premium: float
    qty: int = 1
    option_type: str = "CE"
    action: str = "BUY"


class PayoffRequest(BaseModel):
    legs: list[PayoffLegInput]
    spot_min: float = 0
    spot_max: float = 0
    num_points: int = 200


class StrategyBuildRequest(BaseModel):
    name: str
    params: dict


# ── Strategy preset catalog ────────────────────────────────────────


_STRATEGY_PRESETS = {
    # Basic
    "long_call":             {"legs": 1, "bias": "BULLISH",      "risk": "LIMITED",   "reward": "UNLIMITED", "iv_bias": "ANY"},
    "long_put":              {"legs": 1, "bias": "BEARISH",      "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "ANY"},
    "bull_call_spread":      {"legs": 2, "bias": "BULLISH",      "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "ANY"},
    "bear_put_spread":       {"legs": 2, "bias": "BEARISH",      "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "ANY"},
    "long_straddle":         {"legs": 2, "bias": "VOL_EXPAND",   "risk": "LIMITED",   "reward": "UNLIMITED", "iv_bias": "LOW_IV"},
    "long_strangle":         {"legs": 2, "bias": "VOL_EXPAND",   "risk": "LIMITED",   "reward": "UNLIMITED", "iv_bias": "LOW_IV"},
    "iron_condor":           {"legs": 4, "bias": "RANGE_BOUND",  "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    "butterfly_spread":      {"legs": 3, "bias": "PIN_RISK",     "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    # Advanced
    "short_straddle":        {"legs": 2, "bias": "RANGE_BOUND",  "risk": "UNLIMITED", "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    "short_strangle":        {"legs": 2, "bias": "RANGE_BOUND",  "risk": "UNLIMITED", "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    "bull_put_spread":       {"legs": 2, "bias": "BULLISH",      "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    "bear_call_spread":      {"legs": 2, "bias": "BEARISH",      "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    "iron_butterfly":        {"legs": 4, "bias": "PIN_RISK",     "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    "jade_lizard":           {"legs": 3, "bias": "BULLISH",      "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    "call_ratio_spread":     {"legs": 2, "bias": "MILD_BULLISH", "risk": "UNLIMITED", "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    "put_ratio_spread":      {"legs": 2, "bias": "MILD_BEARISH", "risk": "UNLIMITED", "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
    "call_backspread":       {"legs": 2, "bias": "STRONG_BULL",  "risk": "LIMITED",   "reward": "UNLIMITED", "iv_bias": "LOW_IV"},
    "put_backspread":        {"legs": 2, "bias": "STRONG_BEAR",  "risk": "LIMITED",   "reward": "UNLIMITED", "iv_bias": "LOW_IV"},
    "synthetic_long":        {"legs": 2, "bias": "BULLISH",      "risk": "UNLIMITED", "reward": "UNLIMITED", "iv_bias": "ANY"},
    "synthetic_short":       {"legs": 2, "bias": "BEARISH",      "risk": "UNLIMITED", "reward": "LIMITED",   "iv_bias": "ANY"},
    "collar":                {"legs": 2, "bias": "PROTECT_LONG", "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "ANY"},
    "broken_wing_butterfly": {"legs": 3, "bias": "MILD_BULLISH", "risk": "LIMITED",   "reward": "LIMITED",   "iv_bias": "HIGH_IV"},
}


# ── /api/fno/option_* (historical path; functionally belongs to options) ─────


@router.get("/api/fno/option_greeks")
async def api_option_greeks(
    symbol: str,
    strike: float,
    expiry_days: int,
    market_price: float,
    spot: float,
    option_type: str = "CE",
):
    """Compute full Greeks (delta/gamma/theta/vega/rho/IV) for a single option.

    Pure-Python Black-Scholes — no Kite needed.
    """
    from mcp_server.options_greeks import calculate_iv, calculate_greeks

    iv = calculate_iv(market_price, spot, strike, expiry_days, 0.065, option_type)
    greeks = calculate_greeks(spot, strike, expiry_days, 0.065, iv if iv > 0 else 0.20, option_type)
    return {
        "symbol": symbol,
        "strike": strike,
        "expiry_days": expiry_days,
        "spot": spot,
        "market_price": market_price,
        "option_type": option_type,
        "iv_pct": round(iv * 100, 2),
        "delta": greeks.delta,
        "gamma": greeks.gamma,
        "theta": greeks.theta,
        "vega": greeks.vega,
        "rho": greeks.rho,
        "fair_price": greeks.price,
    }


@router.get("/api/fno/option_universe")
async def api_option_universe():
    """Return the list of symbols eligible for option enrichment (4 indices + 20 stocks)."""
    from mcp_server.options_selector import (
        OPTION_INDEX_UNIVERSE,
        OPTION_STOCK_UNIVERSE,
        OPTION_UNIVERSE,
    )
    return {
        "count": len(OPTION_UNIVERSE),
        "indices": OPTION_INDEX_UNIVERSE,
        "stocks": OPTION_STOCK_UNIVERSE,
        "enabled": bool(getattr(settings, "OPTION_SIGNALS_ENABLED", True)),
    }


@router.get("/api/fno/option_recommendation/{symbol}")
async def api_option_recommendation(symbol: str, direction: str = "LONG"):
    """
    Standalone option picker for any eligible symbol.

    Fetches live spot + computes ATR-based SL/TGT, then returns the full
    option recommendation dict (same shape attached to MWA signals).
    """
    from mcp_server import mcp_server as _ms
    from mcp_server.mwa_signal_generator import _compute_atr
    from mcp_server.options_selector import (
        build_option_recommendation,
        is_eligible,
    )
    from mcp_server.nse_scanner import get_stock_data

    symbol_u = (symbol or "").upper()
    direction_u = (direction or "LONG").upper()

    if not is_eligible(symbol_u):
        return {
            "status": "skipped",
            "symbol": symbol_u,
            "message": f"{symbol_u} not in OPTION_UNIVERSE (or feature disabled)",
        }

    kite = _ms._get_kite_for_fo()
    if not kite:
        return {
            "status": "error",
            "symbol": symbol_u,
            "message": "Kite not connected — option recommendation requires live F&O session",
        }

    try:
        df = await asyncio.to_thread(get_stock_data, symbol_u, "3mo", "1d")
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "symbol": symbol_u, "message": f"OHLCV fetch failed: {e}"}

    if df is None or df.empty or len(df) < 15:
        return {
            "status": "error",
            "symbol": symbol_u,
            "message": "Insufficient OHLCV data for ATR computation",
        }

    spot = float(df["close"].iloc[-1])
    atr = _compute_atr(df, period=14)
    if atr <= 0 or spot <= 0:
        return {
            "status": "error",
            "symbol": symbol_u,
            "message": "ATR / spot computation failed",
        }

    atr_mult = 1.5
    rrr_mult = settings.RRMS_MIN_RRR
    if direction_u == "LONG":
        sl = spot - (atr_mult * atr)
        risk = spot - sl
        target = spot + (rrr_mult * risk)
    else:
        sl = spot + (atr_mult * atr)
        risk = sl - spot
        target = spot - (rrr_mult * risk)

    rec = await asyncio.to_thread(
        build_option_recommendation,
        symbol=symbol_u,
        direction=direction_u,
        spot=spot,
        underlying_sl=sl,
        underlying_target=target,
        kite=kite,
    )
    if not rec:
        return {
            "status": "no_recommendation",
            "symbol": symbol_u,
            "spot": round(spot, 2),
            "underlying_sl": round(sl, 2),
            "underlying_target": round(target, 2),
            "message": "Could not build option recommendation (see server logs)",
        }

    if hasattr(rec.get("option_expiry"), "isoformat"):
        rec["option_expiry"] = rec["option_expiry"].isoformat()

    return {
        "status": "ok",
        "symbol": symbol_u,
        "direction": direction_u,
        "spot": round(spot, 2),
        "underlying_sl": round(sl, 2),
        "underlying_target": round(target, 2),
        "atr": round(atr, 2),
        **rec,
    }


# ── /api/options/* (canonical options math endpoints) ──────────────


@router.post("/api/options/greeks")
async def api_options_greeks(req: GreeksRequest):
    """Calculate Greeks for a single option."""
    from mcp_server.options_greeks import calculate_greeks
    from dataclasses import asdict as _asdict

    result = calculate_greeks(
        spot=req.spot,
        strike=req.strike,
        expiry_days=req.expiry_days,
        rate=req.rate,
        volatility=req.volatility,
        option_type=req.option_type,
    )
    return {"status": "ok", **_asdict(result)}


@router.get("/api/options/chain")
async def api_options_chain(
    spot: float = Query(...),
    expiry_days: float = Query(default=30),
    strike_start: float = Query(default=0),
    strike_end: float = Query(default=0),
    strike_step: float = Query(default=50),
    rate: float = Query(default=0.065),
):
    """Build option chain with Greeks for all strikes."""
    from mcp_server.options_greeks import build_greeks_chain

    if strike_start <= 0:
        strike_start = spot * 0.90
    if strike_end <= 0:
        strike_end = spot * 1.10

    strike_start = round(strike_start / strike_step) * strike_step
    strike_end = round(strike_end / strike_step) * strike_step

    strikes = []
    s = strike_start
    while s <= strike_end:
        strikes.append(s)
        s += strike_step

    chain = build_greeks_chain(
        spot=spot,
        strikes=strikes,
        expiry_days=expiry_days,
        rate=rate,
    )

    atm_strike = min(strikes, key=lambda k: abs(k - spot)) if strikes else 0

    return {
        "status": "ok",
        "spot": spot,
        "expiry_days": expiry_days,
        "atm_strike": atm_strike,
        "strikes_count": len(strikes),
        "chain": chain,
    }


@router.post("/api/options/payoff")
async def api_options_payoff(req: PayoffRequest):
    """Calculate multi-leg options payoff curve."""
    from mcp_server.options_payoff import OptionLeg, calculate_payoff
    from dataclasses import asdict as _asdict

    legs = [
        OptionLeg(
            strike=leg.strike,
            premium=leg.premium,
            qty=leg.qty,
            option_type=leg.option_type,
            action=leg.action,
        )
        for leg in req.legs
    ]

    result = calculate_payoff(
        legs, spot_min=req.spot_min, spot_max=req.spot_max,
        num_points=req.num_points,
    )

    return {
        "status": "ok",
        "points": [_asdict(p) for p in result.points],
        "breakevens": result.breakevens,
        "max_profit": result.max_profit,
        "max_loss": result.max_loss,
        "net_premium": result.net_premium,
    }


@router.get("/api/options/strategies")
async def api_options_strategies():
    """List all available strategy presets with bias/risk/reward profile."""
    return {
        "status": "ok",
        "count": len(_STRATEGY_PRESETS),
        "strategies": _STRATEGY_PRESETS,
    }


@router.post("/api/options/strategy/build")
async def api_options_strategy_build(req: StrategyBuildRequest):
    """
    Build a preset strategy by name and compute its payoff.

    Pass `name` (e.g. "iron_butterfly") and `params` (kwargs for the preset
    function from options_payoff.py).
    """
    from mcp_server import options_payoff as op
    from dataclasses import asdict as _asdict

    builder = getattr(op, req.name, None)
    if not callable(builder) or req.name.startswith("_"):
        return {"status": "error", "error": f"unknown strategy: {req.name}"}

    try:
        legs = builder(**req.params)
    except TypeError as e:
        return {"status": "error", "error": f"bad params: {e}"}

    result = op.calculate_payoff(legs)
    return {
        "status": "ok",
        "strategy": req.name,
        "legs": [_asdict(leg) for leg in legs],
        "points": [_asdict(p) for p in result.points],
        "breakevens": result.breakevens,
        "max_profit": result.max_profit,
        "max_loss": result.max_loss,
        "net_premium": result.net_premium,
    }


# ── Options seller module ──────────────────────────────────────────


@router.get("/api/options-seller/iv-regime/{instrument}")
async def api_iv_regime(
    instrument: str,
    spot: float = 0.0,
    vix: float = 0.0,
):
    """Classify the current IV regime for an instrument.

    Returns regime label (CRUSHED/LOW/NORMAL/ELEVATED/EXTREME),
    VIX percentiles, sell_premium_ok gate, and suggested DTE + delta.

    Optional: pass ?vix=16.5 to supply India VIX manually when the live
    fetch fails (e.g. container network restrictions). Look up the current
    value at nseindia.com or your broker terminal.

    Example:
      GET /api/options-seller/iv-regime/BANKNIFTY?vix=16.5
    """
    import asyncio
    from mcp_server.options_seller.iv_engine import (
        classify_iv, _fetch_vix_history, _fetch_vix_current,
    )

    # Fetch VIX history (needed for percentile rank)
    vix_history = await asyncio.to_thread(_fetch_vix_history, 252)

    # Use manual vix if provided and live fetch returned 0
    vix_now = vix if vix > 0 else await asyncio.to_thread(_fetch_vix_current)

    if vix_now <= 0:
        return {
            "status": "error",
            "message": (
                "India VIX fetch returned 0. Pass ?vix=<current_value> manually. "
                "Current VIX is shown on nseindia.com or your broker terminal."
            ),
        }

    hist_90 = vix_history[-90:] if len(vix_history) >= 90 else vix_history
    hist_1y = vix_history[-252:] if len(vix_history) >= 252 else vix_history

    regime = classify_iv(
        instrument=instrument.upper(),
        vix_current=vix_now,
        vix_history_90d=hist_90,
        vix_history_1y=hist_1y,
    )
    return {"status": "ok", **regime.as_dict()}


@router.post("/api/options-seller/build-strangle")
async def api_build_strangle(
    instrument: str,
    spot: float,
    dte: int = 5,
    target_delta: float = 0.15,
    structure: str = "IRON_CONDOR",
    wing_width_strikes: int = 1,
    vix: float = 0.0,
    iv: float = 0.18,
    strike_step: float = 100.0,
):
    """Build an iron condor or naked strangle using a synthetic Black-Scholes chain.

    Uses Black-Scholes to price all strikes — no live broker chain required.
    Kite/Dhan chain fetching is not used (that function doesn't exist yet).

    Required params:
      instrument:        BANKNIFTY, NIFTY, MIDCPNIFTY, FINNIFTY, SENSEX, BANKEX
      spot:              Current underlying price (e.g. 56322)
      vix:               Current India VIX (e.g. 16.5) — from nseindia.com

    Optional params:
      dte:               Days to expiry (default 5)
      target_delta:      Absolute delta for short legs (default 0.15)
      structure:         IRON_CONDOR or NAKED_STRANGLE (default IRON_CONDOR)
      wing_width_strikes: Strike steps for wings (default 1)
      iv:                Implied volatility for pricing (default 0.18 = 18%)
      strike_step:       Points between strikes (default 100 for BANKNIFTY)

    Example:
      POST /api/options-seller/build-strangle?instrument=BANKNIFTY
        &spot=56322&dte=7&target_delta=0.12&structure=IRON_CONDOR
        &vix=16.5&iv=0.18&strike_step=100
    """
    import asyncio
    from mcp_server.options_seller.iv_engine import classify_iv, _fetch_vix_history
    from mcp_server.options_greeks import calculate_greeks
    from mcp_server.options_seller.strike_selector import build_strangle

    # Require manual VIX since live fetch is unreliable in container
    if vix <= 0:
        return {
            "status": "error",
            "reason": "Pass ?vix=<current_india_vix> (e.g. ?vix=16.5). "
                      "Check nseindia.com or your broker terminal for the current value.",
        }

    # IV regime gate
    vix_history = await asyncio.to_thread(_fetch_vix_history, 252)
    hist_90 = vix_history[-90:] if len(vix_history) >= 90 else vix_history
    hist_1y = vix_history[-252:] if len(vix_history) >= 252 else vix_history
    regime = classify_iv(instrument.upper(), vix, hist_90, hist_1y)

    if not regime.sell_premium_ok:
        return {
            "status": "blocked",
            "reason": f"IV regime {regime.label} — {regime.reason}",
            "regime": regime.as_dict(),
        }

    # Build synthetic chain using Black-Scholes
    # ±15 strikes around ATM at the given step
    chain: dict = {}
    atm = round(spot / strike_step) * strike_step
    for i in range(-15, 16):
        strike = atm + i * strike_step
        if strike <= 0:
            continue
        ce = calculate_greeks(spot, strike, max(dte, 0.1), volatility=iv, option_type="CE")
        pe = calculate_greeks(spot, strike, max(dte, 0.1), volatility=iv, option_type="PE")
        chain[float(strike)] = {
            "CE": {"ltp": max(ce.price, 0.5), "iv": iv},
            "PE": {"ltp": max(pe.price, 0.5), "iv": iv},
        }

    pos = build_strangle(
        instrument=instrument,
        spot=spot,
        chain=chain,
        dte=dte,
        target_delta=target_delta,
        structure=structure,
        wing_width_strikes=wing_width_strikes,
        min_premium=10.0,
    )

    if pos is None:
        return {
            "status": "error",
            "reason": "Could not build position — try lowering target_delta or adjusting strike_step",
        }

    return {
        "status": "ok",
        "chain_source": "synthetic_bs",
        "note": "Priced using Black-Scholes. Use these strikes as a starting point; verify actual premiums in your broker before placing.",
        "position": pos.as_dict(),
        "regime": regime.as_dict(),
    }


@router.post("/api/options-seller/evaluate-adjustment")
async def api_evaluate_adjustment(
    instrument: str,
    spot: float,
    short_call_strike: float,
    short_put_strike: float,
    short_call_delta: float,
    short_put_delta: float,
    short_call_entry_premium: float,
    short_put_entry_premium: float,
    short_call_current_premium: float,
    short_put_current_premium: float,
    credit_received: float,
    current_pnl: float,
    dte_remaining: float,
):
    """Evaluate an open position against the 5 adjustment rules.

    Returns action (hold / close / roll), which rule fired, and the
    human-readable reason. Front-end can display this live to the operator.
    """
    from mcp_server.options_seller.adjustment_engine import (
        LivePositionSnapshot, evaluate,
    )
    snap = LivePositionSnapshot(
        instrument=instrument,
        spot=spot,
        short_call_strike=short_call_strike,
        short_put_strike=short_put_strike,
        short_call_delta=short_call_delta,
        short_put_delta=short_put_delta,
        short_call_entry_premium=short_call_entry_premium,
        short_put_entry_premium=short_put_entry_premium,
        short_call_current_premium=short_call_current_premium,
        short_put_current_premium=short_put_current_premium,
        credit_received=credit_received,
        current_pnl=current_pnl,
        dte_remaining=dte_remaining,
    )
    decision = evaluate(snap)
    return {"status": "ok", "decision": decision.as_dict()}


@router.post("/api/options-seller/close/{position_id}")
async def api_close_position(position_id: int, reason: str = "manual"):
    """Close an open options seller position and log the exit."""
    import asyncio
    from mcp_server.options_seller.position_manager import close_position
    ok = await asyncio.to_thread(close_position, position_id, reason)
    if not ok:
        return {"status": "error", "reason": f"Position {position_id} not found or already closed"}
    return {"status": "ok", "position_id": position_id, "reason": reason}


@router.get("/api/options-seller/positions")
async def api_open_positions():
    """List all currently OPEN options seller positions."""
    from mcp_server.db import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT id, instrument, structure, status, net_credit, current_pnl, "
                "dte_remaining, iv_regime, opened_at, paper_mode "
                "FROM options_seller_positions WHERE status = 'OPEN' "
                "ORDER BY opened_at DESC"
            )
        ).fetchall()
        return {
            "status": "ok",
            "count": len(rows),
            "positions": [dict(r._mapping) for r in rows],
        }
    finally:
        db.close()


@router.get("/api/options-seller/debug-chain/{instrument}")
async def api_debug_chain(instrument: str):
    """Debug: show what Dhan returns for this instrument's option chain."""
    import asyncio
    from mcp_server.data_provider import get_provider
    inst = instrument.upper()
    provider = get_provider()
    dhan = provider.dhan
    result = {"logged_in": dhan.logged_in}
    if not dhan.logged_in:
        return result
    # Try all exchange variants
    for exch in ("NSE", "NFO", "BSE"):
        sid = dhan._resolve_security_id(inst, exch)
        result[f"security_id_{exch}"] = sid
        if sid:
            expiries = await asyncio.to_thread(dhan.get_expiry_list, inst, exch)
            result[f"expiries_{exch}"] = expiries[:5] if expiries else []
    return result


@router.get("/api/options-seller/strangle/{instrument}/{spot}/{vix}")
async def api_quick_strangle(
    instrument: str,
    spot: float,
    vix: float,
    dte: int = 7,
    wings: int = 3,
):
    """Short URL for building a BANKNIFTY/NIFTY iron condor — fits in one terminal line.

    Uses sensible defaults: target_delta=0.12, IRON_CONDOR, iv=0.18, strike_step=100.

    Example (fits in 80 chars):
      GET /api/options-seller/strangle/BANKNIFTY/56322/16.5
      GET /api/options-seller/strangle/BANKNIFTY/56322/16.5?dte=7&wings=3
    """
    from mcp_server.options_seller.iv_engine import classify_iv, _fetch_vix_history
    from mcp_server.options_greeks import calculate_greeks
    from mcp_server.options_seller.strike_selector import build_strangle
    import asyncio

    # Instrument defaults
    STEP_MAP = {
        "BANKNIFTY": 100.0, "NIFTY": 50.0, "MIDCPNIFTY": 25.0,
        "FINNIFTY": 50.0, "SENSEX": 100.0, "BANKEX": 100.0,
    }
    inst = instrument.upper()
    step = STEP_MAP.get(inst, 100.0)
    iv = 0.18

    # IV regime
    vix_history = await asyncio.to_thread(_fetch_vix_history, 252)
    hist_90 = vix_history[-90:] if len(vix_history) >= 90 else vix_history
    hist_1y = vix_history[-252:] if len(vix_history) >= 252 else vix_history
    regime = classify_iv(inst, vix, hist_90, hist_1y)

    if not regime.sell_premium_ok:
        return {
            "status": "blocked",
            "reason": f"IV regime {regime.label} — {regime.reason}",
            "regime": regime.as_dict(),
        }

    # Try Dhan live chain first — real premiums + IV
    chain: dict = {}
    chain_source = "synthetic_bs"
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        dhan = provider.dhan
        if dhan.logged_in:
            # Index option chains live in NFO, not NSE
            NFO_INSTRUMENTS = {"BANKNIFTY", "NIFTY", "MIDCPNIFTY", "FINNIFTY"}
            chain_exchange = "NFO" if inst in NFO_INSTRUMENTS else "NSE"
            expiries = await asyncio.to_thread(dhan.get_expiry_list, inst, chain_exchange)
            if expiries:
                # Pick the nearest expiry that's at least dte days away
                from datetime import date, timedelta
                min_date = (date.today() + timedelta(days=max(dte - 2, 1))).isoformat()
                valid = [e for e in sorted(expiries) if e >= min_date]
                expiry = valid[0] if valid else expiries[-1]
                live = await asyncio.to_thread(dhan.get_option_chain, inst, expiry, chain_exchange)
                if live and len(live) > 5:
                    chain = live
                    chain_source = f"dhan_live ({expiry})"
                    # Extract ATM IV from chain for better pricing
                    atm_strike = round(spot / step) * step
                    atm_data = chain.get(float(atm_strike), {})
                    atm_ce = atm_data.get("CE", {})
                    if atm_ce.get("iv", 0) > 0:
                        iv = float(atm_ce["iv"])
    except Exception as e:
        logger.debug("Dhan chain fetch failed, using synthetic: %s", e)

    # Fallback: synthetic Black-Scholes chain
    if not chain:
        atm = round(spot / step) * step
        for i in range(-15, 16):
            strike = atm + i * step
            if strike <= 0:
                continue
            ce = calculate_greeks(spot, strike, max(dte, 0.1), volatility=iv, option_type="CE")
            pe = calculate_greeks(spot, strike, max(dte, 0.1), volatility=iv, option_type="PE")
            chain[float(strike)] = {
                "CE": {"ltp": max(ce.price, 0.5), "iv": iv},
                "PE": {"ltp": max(pe.price, 0.5), "iv": iv},
            }

    pos = build_strangle(
        instrument=inst, spot=spot, chain=chain, dte=dte,
        target_delta=0.12, structure="IRON_CONDOR",
        wing_width_strikes=wings, min_premium=10.0,
    )

    if pos is None:
        return {"status": "error", "reason": "Could not build — try different wings or dte"}

    return {
        "status": "ok",
        "chain_source": chain_source,
        "note": "Priced from Dhan live chain." if "dhan" in chain_source else "Priced using Black-Scholes — verify actual premiums in broker.",
        "position": pos.as_dict(),
        "regime": regime.as_dict(),
    }
