"""
MKUMARAN Trading OS — Options Enrichment / Contract Selector

Wires together the futures signal pipeline with the existing options engine
(fo_module, options_greeks) to attach a concrete option contract recommendation
(strike, expiry, premium, lot size, Greeks, option-level SL/TGT) to every
eligible F&O futures signal.

Strike selection is IV-aware hybrid:
    IV rank < 40  → DEBIT (buy 1-strike ITM CE/PE, ~0.60 delta)
    40 <= IVR <= 60 → ATM DEBIT (buy ATM CE/PE, ~0.50 delta)
    IV rank > 60  → CREDIT SPREAD (bull put / bear call, 2-strike width)

This module does NOT reimplement any of the heavy lifting — it reuses:
    - fo_module._get_kite_instruments
    - fo_module._find_current_expiry
    - fo_module._get_option_chain
    - fo_module.get_iv_rank
    - options_greeks.calculate_greeks
    - options_greeks.calculate_iv
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from mcp_server.config import settings

logger = logging.getLogger(__name__)


# ── Eligibility Universe ──────────────────────────────────────
# 4 indices + curated top-liquidity F&O stocks. When
# `OPTION_UNIVERSE_ALL_FNO=true` the `is_eligible` check also
# accepts any symbol present in the Kite NFO instruments dump,
# which covers all ~220 F&O-eligible NSE stocks without
# hardcoding each name.
OPTION_INDEX_UNIVERSE: list[str] = [
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
]
OPTION_STOCK_UNIVERSE: list[str] = [
    # Mega-caps
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "AXISBANK", "KOTAKBANK", "LT", "ITC",
    "HINDUNILVR", "BHARTIARTL", "MARUTI", "TATAMOTORS", "TATASTEEL",
    "M&M", "BAJFINANCE", "HCLTECH", "WIPRO", "ADANIENT",
    # Large-caps frequently signaled by MWA
    "HAL", "DIVISLAB", "ALKEM", "INDIGO", "TATAELXSI",
    "SCHAEFFLER", "DATAPATTNS", "LTTS", "ESCORTS", "MRF",
    "ASIANPAINT", "SRF", "NESTLEIND", "ULTRACEMCO", "TITAN",
    "POWERGRID", "NTPC", "ONGC", "COALINDIA", "BPCL",
    "IOC", "GAIL", "HINDALCO", "JSWSTEEL", "SHREECEM",
    "BAJAJFINSV", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "ASHOKLEY",
    "SUNPHARMA", "DRREDDY", "CIPLA", "APOLLOHOSP", "LUPIN",
    "BIOCON", "AUROPHARMA", "CADILAHC", "TORNTPHARM", "GLENMARK",
    "ADANIPORTS", "ADANIPOWER", "ADANIGREEN", "VEDL", "HINDPETRO",
    "DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "SOBHA",
    "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "PNB", "BANKBARODA",
    "IDEA", "TATACOMM", "IRCTC", "INDIGO", "GRASIM",
    "DABUR", "GODREJCP", "MARICO", "COLPAL", "BRITANNIA",
    "PIDILITIND", "BERGEPAINT", "HAVELLS", "VOLTAS", "BLUESTARCO",
    "PAGEIND", "TRENT", "DMART", "NAUKRI", "ZOMATO",
    "PAYTM", "NYKAA", "POLICYBZR", "DIXON", "PERSISTENT",
    "COFORGE", "MPHASIS", "MINDTREE", "LTI", "TECHM",
    "SIEMENS", "ABB", "HONAUT", "CUMMINSIND", "BHEL",
    "PIIND", "UPL", "CHAMBLFERT", "COROMANDEL", "FACT",
    "RAMCOCEM", "ACC", "AMBUJACEM", "DALBHARAT", "JKCEMENT",
]
OPTION_UNIVERSE: set[str] = set(OPTION_INDEX_UNIVERSE + OPTION_STOCK_UNIVERSE)


# Dynamic F&O universe loaded from Kite NFO instruments (populated on
# first call, refreshed daily). Used when OPTION_UNIVERSE_ALL_FNO=true
# so eligibility is data-driven rather than a hardcoded list.
_dynamic_fno_universe: set[str] = set()
_dynamic_fno_universe_date: str | None = None


def _load_dynamic_fno_universe() -> set[str]:
    """Populate the F&O universe from Kite's NFO instrument dump (daily cache).

    Each option contract has a `name` field equal to the underlying symbol
    (e.g. "RELIANCE", "NIFTY"). Deduping those names gives the full set of
    F&O-eligible underlyings without hardcoding.
    """
    global _dynamic_fno_universe, _dynamic_fno_universe_date
    today_key = date.today().isoformat()
    if _dynamic_fno_universe_date == today_key and _dynamic_fno_universe:
        return _dynamic_fno_universe
    try:
        from mcp_server.kite_auth import get_authenticated_kite
        kite = get_authenticated_kite()
        instruments = kite.instruments("NFO") or []
        names = {
            (inst.get("name") or "").upper()
            for inst in instruments
            if inst.get("instrument_type") in ("CE", "PE", "FUT")
        }
        names.discard("")
        if names:
            _dynamic_fno_universe = names
            _dynamic_fno_universe_date = today_key
            logger.info("Dynamic F&O universe loaded: %d underlyings", len(names))
    except Exception as exc:
        logger.debug("Dynamic F&O universe load failed: %s", exc)
    return _dynamic_fno_universe


# ── Lot Size Fallback Map ─────────────────────────────────────
# Used only if the Kite instrument list does not return lot_size.
# Values as of 2025 SEBI schedule; stocks default to 0 → single contract fallback.
INDEX_LOT_SIZE_FALLBACK: dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 15,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 75,
}


# ── Eligibility Check ─────────────────────────────────────────
def is_eligible(ticker: str) -> bool:
    """
    Check if a ticker qualifies for option enrichment.

    Gated by:
      - settings.OPTION_SIGNALS_ENABLED feature flag (default true)
      - Either membership in the curated OPTION_UNIVERSE, OR — when
        OPTION_UNIVERSE_ALL_FNO=true — membership in the dynamic set
        loaded from Kite's NFO instrument dump.
    """
    if not getattr(settings, "OPTION_SIGNALS_ENABLED", True):
        return False
    t = (ticker or "").upper()
    if t in OPTION_UNIVERSE:
        return True
    if getattr(settings, "OPTION_UNIVERSE_ALL_FNO", True):
        dynamic = _load_dynamic_fno_universe()
        if t in dynamic:
            return True
    return False


# ── Expiry Selection ──────────────────────────────────────────
def select_expiry(instruments: list[dict], symbol: str) -> date | None:
    """
    Pick the nearest weekly expiry ≥ MIN_DAYS_TO_EXPIRY (default 2).

    If the nearest expiry is less than 2 days away (same-day / next-day gamma
    trap), skip to the next available expiry.
    """
    min_days = int(getattr(settings, "OPTION_MIN_DAYS_TO_EXPIRY", 2))
    today = date.today()

    expiries: set[date] = set()
    for inst in instruments:
        if inst.get("name") != symbol:
            continue
        exp = inst.get("expiry")
        if not exp:
            continue
        if isinstance(exp, datetime):
            exp = exp.date()
        if exp >= today:
            expiries.add(exp)

    if not expiries:
        return None

    sorted_exp = sorted(expiries)
    for exp in sorted_exp:
        if (exp - today).days >= min_days:
            return exp

    # All remaining expiries are inside the min_days window — return None
    return None


# ── Strike Selection (IV-Aware Hybrid) ────────────────────────
def _strike_step(strikes: list[float]) -> float:
    """Estimate strike increment (e.g., 50 for NIFTY, 100 for BANKNIFTY)."""
    if len(strikes) < 2:
        return 50.0
    diffs = [strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1)]
    # Use the smallest non-zero diff as the grid step
    nonzero = [d for d in diffs if d > 0]
    if not nonzero:
        return 50.0
    return float(min(nonzero))


def _nearest_strike(strikes: list[float], target: float) -> float:
    """Find the strike in `strikes` closest to `target`."""
    return min(strikes, key=lambda s: abs(s - target))


def _leg(
    action: str,
    strike: float,
    option_type: str,
    chain_slot: dict,
) -> dict:
    """Build a single leg dict from a chain slot entry."""
    return {
        "action": action,  # BUY / SELL
        "strike": float(strike),
        "option_type": option_type,  # CE / PE
        "tradingsymbol": chain_slot.get("tradingsymbol", ""),
        "premium": float(chain_slot.get("ltp", 0) or 0),
        "token": int(chain_slot.get("token", 0) or 0),
    }


def select_strike_iv_aware(
    spot: float,
    direction: str,
    iv_rank: float,
    chain: dict,
) -> dict | None:
    """
    IV-aware hybrid strike picker.

    Returns a dict describing the chosen strategy + leg(s), or None if the
    chain is too sparse to build any position.

    Regime logic:
      iv_rank <  40            → DEBIT, buy 1-strike ITM (~0.60 delta)
      40 <= iv_rank <= 60      → ATM DEBIT (~0.50 delta)
      iv_rank >  60            → CREDIT SPREAD (bull put / bear call, 2-wide)
    """
    if not chain:
        return None

    strikes = sorted(chain.keys())
    if not strikes:
        return None

    direction = (direction or "LONG").upper()
    is_long = direction in ("LONG", "BUY")

    # Find ATM
    atm = _nearest_strike(strikes, spot)
    atm_idx = strikes.index(atm)
    step = _strike_step(strikes)

    iv_debit_max = float(getattr(settings, "OPTION_IV_DEBIT_MAX", 40.0))
    iv_credit_min = float(getattr(settings, "OPTION_IV_CREDIT_MIN", 60.0))

    # ── Regime 1: Low IV → slightly ITM debit ─────────────────
    if iv_rank < iv_debit_max:
        if is_long:
            # Bullish → buy 1-strike ITM CE (strike < spot)
            target_strike = atm - step
            if atm_idx - 1 >= 0:
                target_strike = strikes[atm_idx - 1]
            opt_type = "CE"
            strategy = "LONG_CALL_ITM"
        else:
            # Bearish → buy 1-strike ITM PE (strike > spot)
            target_strike = atm + step
            if atm_idx + 1 < len(strikes):
                target_strike = strikes[atm_idx + 1]
            opt_type = "PE"
            strategy = "LONG_PUT_ITM"

        slot = chain.get(target_strike, {}).get(opt_type)
        if not slot or float(slot.get("ltp", 0) or 0) <= 0:
            # Fall back to ATM
            return select_strike_iv_aware(
                spot, direction, 50.0, chain  # force ATM regime
            )

        leg = _leg("BUY", target_strike, opt_type, slot)
        return {
            "strategy": strategy,
            "legs": [leg],
            "primary_strike": float(target_strike),
            "primary_type": opt_type,
            "primary_tradingsymbol": leg["tradingsymbol"],
            "primary_token": leg["token"],
            "is_spread": False,
            "net_premium": leg["premium"],
        }

    # ── Regime 2: Moderate IV → ATM debit ─────────────────────
    if iv_rank <= iv_credit_min:
        opt_type = "CE" if is_long else "PE"
        strategy = "LONG_CALL_ATM" if is_long else "LONG_PUT_ATM"
        slot = chain.get(atm, {}).get(opt_type)
        if not slot or float(slot.get("ltp", 0) or 0) <= 0:
            return None
        leg = _leg("BUY", atm, opt_type, slot)
        return {
            "strategy": strategy,
            "legs": [leg],
            "primary_strike": float(atm),
            "primary_type": opt_type,
            "primary_tradingsymbol": leg["tradingsymbol"],
            "primary_token": leg["token"],
            "is_spread": False,
            "net_premium": leg["premium"],
        }

    # ── Regime 3: High IV → credit spread ─────────────────────
    # LONG underlying bias  → Bull Put Spread (sell ATM PE, buy OTM PE below)
    # SHORT underlying bias → Bear Call Spread (sell ATM CE, buy OTM CE above)
    if is_long:
        short_type = "PE"
        short_strike = atm
        long_idx = atm_idx - 2
        if long_idx < 0:
            long_idx = 0
        long_strike = strikes[long_idx]
        strategy = "BULL_PUT_SPREAD"
        primary_type = "PE"
    else:
        short_type = "CE"
        short_strike = atm
        long_idx = atm_idx + 2
        if long_idx >= len(strikes):
            long_idx = len(strikes) - 1
        long_strike = strikes[long_idx]
        strategy = "BEAR_CALL_SPREAD"
        primary_type = "CE"

    # If we can't build a true spread (only one strike), fall back to ATM debit
    if long_strike == short_strike:
        return select_strike_iv_aware(spot, direction, 50.0, chain)

    short_slot = chain.get(short_strike, {}).get(short_type)
    long_slot = chain.get(long_strike, {}).get(short_type)
    if not short_slot or not long_slot:
        return select_strike_iv_aware(spot, direction, 50.0, chain)

    short_prem = float(short_slot.get("ltp", 0) or 0)
    long_prem = float(long_slot.get("ltp", 0) or 0)
    if short_prem <= 0 or long_prem <= 0:
        return select_strike_iv_aware(spot, direction, 50.0, chain)

    net_credit = short_prem - long_prem
    if net_credit <= 0:
        # Not a viable credit spread — fall back
        return select_strike_iv_aware(spot, direction, 50.0, chain)

    sell_leg = _leg("SELL", short_strike, short_type, short_slot)
    buy_leg = _leg("BUY", long_strike, short_type, long_slot)

    return {
        "strategy": strategy,
        "legs": [sell_leg, buy_leg],
        "primary_strike": float(short_strike),
        "primary_type": primary_type,
        "primary_tradingsymbol": sell_leg["tradingsymbol"],
        "primary_token": sell_leg["token"],
        "is_spread": True,
        "net_premium": round(net_credit, 2),
        "spread_width": abs(float(short_strike) - float(long_strike)),
    }


# ── Option-Level SL / TGT Derivation ──────────────────────────
def compute_option_trade_plan(
    *,
    primary_premium: float,
    primary_delta: float,
    spot: float,
    underlying_sl: float,
    underlying_target: float,
    is_spread: bool,
    net_premium: float,
    lot_size: int,
    spread_width: float = 0.0,
) -> dict:
    """
    Derive option-level entry / SL / target from underlying levels and delta.

    Single-leg debit:
        points_to_sl  = |spot - underlying_sl|
        points_to_tgt = |underlying_target - spot|
        premium_sl    = max(premium - delta * points_to_sl, premium * 0.5)
        premium_tgt   = premium + delta * points_to_tgt

    Credit spread (trader BUYS BACK to close):
        entry       = net credit received
        premium_sl  = 2 × net_premium   (buyback cost threshold)
        premium_tgt = 0.5 × net_premium (take 50% profit)
        max_loss    = (spread_width - net_premium) × lot_size
    """
    lot_size = max(int(lot_size or 1), 1)

    if is_spread:
        entry = float(net_premium)
        sl = round(2.0 * entry, 2)
        tgt = round(0.5 * entry, 2)
        max_loss = round(max(spread_width - entry, 0.0) * lot_size, 2)
        # For spreads, P&L scales with credit: target P&L ≈ 50% of credit
        risk_per_lot = max_loss if max_loss > 0 else round((entry * 1.0) * lot_size, 2)
        reward_per_lot = round((entry - tgt) * lot_size, 2)  # half-credit capture
        option_rrr = round(reward_per_lot / risk_per_lot, 2) if risk_per_lot > 0 else 0.0
        return {
            "entry_premium": round(entry, 2),
            "premium_sl": sl,
            "premium_target": tgt,
            "risk_per_lot": risk_per_lot,
            "reward_per_lot": reward_per_lot,
            "option_rrr": option_rrr,
        }

    # Single-leg debit path
    premium = float(primary_premium or 0)
    delta = abs(float(primary_delta or 0.5))
    if delta <= 0:
        delta = 0.5
    if premium <= 0:
        # Can't build a meaningful plan — return premium floor
        return {
            "entry_premium": round(premium, 2),
            "premium_sl": round(premium * 0.5, 2),
            "premium_target": round(premium * 2.0, 2),
            "risk_per_lot": round(premium * 0.5 * lot_size, 2),
            "reward_per_lot": round(premium * 1.0 * lot_size, 2),
            "option_rrr": 2.0,
        }

    pts_to_sl = abs(float(spot) - float(underlying_sl))
    pts_to_tgt = abs(float(underlying_target) - float(spot))

    # Premium SL floor at 50% of entry (gamma cushion against large underlying moves)
    premium_sl = max(premium - (delta * pts_to_sl), premium * 0.5)
    premium_tgt = premium + (delta * pts_to_tgt)

    risk_per_lot = round((premium - premium_sl) * lot_size, 2)
    reward_per_lot = round((premium_tgt - premium) * lot_size, 2)
    option_rrr = round(reward_per_lot / risk_per_lot, 2) if risk_per_lot > 0 else 0.0

    return {
        "entry_premium": round(premium, 2),
        "premium_sl": round(premium_sl, 2),
        "premium_target": round(premium_tgt, 2),
        "risk_per_lot": risk_per_lot,
        "reward_per_lot": reward_per_lot,
        "option_rrr": option_rrr,
    }


# ── Main Entry Point ──────────────────────────────────────────
def build_option_recommendation(
    *,
    symbol: str,
    direction: str,
    spot: float,
    underlying_sl: float,
    underlying_target: float,
    kite: Any,
) -> dict | None:
    """
    Build a full option contract recommendation for an eligible F&O signal.

    Returns a dict with all `option_*` fields ready to merge into a signal
    dict, or None on any failure (caller falls back to futures-only).
    """
    symbol = (symbol or "").upper()

    # 1) Eligibility
    if not is_eligible(symbol):
        return None
    if not kite:
        logger.debug("Option enrichment skipped for %s: Kite not connected", symbol)
        return None
    if not spot or spot <= 0:
        logger.debug("Option enrichment skipped for %s: invalid spot %s", symbol, spot)
        return None

    try:
        from mcp_server.fo_module import (
            _get_kite_instruments,
            _get_option_chain,
            get_iv_rank,
        )
        from mcp_server.options_greeks import calculate_greeks, calculate_iv
    except Exception as imp_err:
        logger.debug("Option enrichment skipped for %s: import failed (%s)", symbol, imp_err)
        return None

    # 2) Instruments
    instruments = _get_kite_instruments(kite, "NFO")
    if not instruments:
        logger.debug("No NFO instruments for %s", symbol)
        return None

    # 3) Expiry
    expiry = select_expiry(instruments, symbol)
    if not expiry:
        logger.debug("No eligible expiry for %s", symbol)
        return None

    # 4) Option chain
    chain = _get_option_chain(kite, instruments, symbol, expiry)
    if not chain:
        logger.debug("Empty option chain for %s expiry %s", symbol, expiry)
        return None

    # 5) IV rank (fail-safe: default 50 → ATM regime)
    iv_rank_val = 50.0
    try:
        iv_data = get_iv_rank(kite, symbol)
        if iv_data and iv_data.get("iv_rank") is not None:
            ivr = float(iv_data.get("iv_rank") or 0)
            if ivr > 0:
                iv_rank_val = ivr
    except Exception as iv_err:
        logger.debug("IV rank fetch failed for %s, using 50 default: %s", symbol, iv_err)

    # 6) Strike + strategy
    rec = select_strike_iv_aware(
        spot=float(spot),
        direction=direction,
        iv_rank=iv_rank_val,
        chain=chain,
    )
    if not rec:
        logger.debug("No viable strike for %s at spot %s", symbol, spot)
        return None

    if float(rec.get("net_premium", 0) or 0) <= 0:
        logger.debug("Invalid net premium for %s", symbol)
        return None

    # 7) Lot size (from instrument list) — fallback to hardcoded index map
    lot_size = 0
    primary_ts = rec.get("primary_tradingsymbol", "")
    for inst in instruments:
        if inst.get("tradingsymbol") == primary_ts:
            lot_size = int(inst.get("lot_size", 0) or 0)
            break
    if lot_size <= 0:
        lot_size = INDEX_LOT_SIZE_FALLBACK.get(symbol, 0)
    if lot_size <= 0:
        # Stock without clean lot_size — fall back to 1 so downstream math stays valid
        lot_size = 1

    # 8) Greeks on primary leg
    days_to_expiry = max((expiry - date.today()).days, 1)
    primary_strike = float(rec["primary_strike"])
    primary_type = rec["primary_type"]
    primary_premium = 0.0
    for leg in rec["legs"]:
        if leg["strike"] == primary_strike and leg["option_type"] == primary_type:
            primary_premium = float(leg["premium"])
            break
    if primary_premium <= 0:
        primary_premium = float(rec.get("net_premium", 0) or 0)

    # IV back-solve from market price (safer than guessing)
    iv_pct = 0.0
    try:
        implied = calculate_iv(
            primary_premium,
            float(spot),
            primary_strike,
            days_to_expiry,
            0.065,
            primary_type,
        )
        if implied > 0:
            iv_pct = implied
    except Exception as iv_err:
        logger.debug("IV solve failed for %s: %s", symbol, iv_err)

    # Greeks with solved IV (or 20% default)
    vol_for_greeks = iv_pct if iv_pct > 0 else 0.20
    greeks = None
    try:
        greeks = calculate_greeks(
            spot=float(spot),
            strike=primary_strike,
            expiry_days=days_to_expiry,
            rate=0.065,
            volatility=vol_for_greeks,
            option_type=primary_type,
        )
    except Exception as gk_err:
        logger.debug("Greeks calc failed for %s: %s", symbol, gk_err)

    delta = float(greeks.delta) if greeks else 0.5
    gamma = float(greeks.gamma) if greeks else 0.0
    theta = float(greeks.theta) if greeks else 0.0
    vega = float(greeks.vega) if greeks else 0.0

    # 9) Option-level SL / TGT
    plan = compute_option_trade_plan(
        primary_premium=primary_premium,
        primary_delta=delta,
        spot=float(spot),
        underlying_sl=float(underlying_sl),
        underlying_target=float(underlying_target),
        is_spread=bool(rec.get("is_spread", False)),
        net_premium=float(rec.get("net_premium", 0) or 0),
        lot_size=lot_size,
        spread_width=float(rec.get("spread_width", 0) or 0),
    )

    # 10) Assemble return dict (matches Signal DB column names)
    return {
        "option_strategy": rec["strategy"],
        "option_tradingsymbol": rec.get("primary_tradingsymbol", ""),
        "option_strike": primary_strike,
        "option_expiry": expiry,
        "option_type": primary_type,
        "option_premium": plan["entry_premium"],
        "option_premium_sl": plan["premium_sl"],
        "option_premium_target": plan["premium_target"],
        "option_lot_size": lot_size,
        "option_contracts": 1,
        "option_iv_rank": round(iv_rank_val, 1),
        "option_delta": round(delta, 4),
        "option_gamma": round(gamma, 6),
        "option_theta": round(theta, 2),
        "option_vega": round(vega, 2),
        "option_iv": round(iv_pct, 4),
        "option_is_spread": bool(rec.get("is_spread", False)),
        "option_net_premium": round(float(rec.get("net_premium", 0) or 0), 2),
        "option_legs": rec["legs"],
        "option_risk_per_lot": plan.get("risk_per_lot", 0),
        "option_reward_per_lot": plan.get("reward_per_lot", 0),
        "option_rrr": plan.get("option_rrr", 0),
    }
