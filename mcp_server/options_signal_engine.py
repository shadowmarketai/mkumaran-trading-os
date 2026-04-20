"""
MKUMARAN Trading OS — Pure Options Signal Engine

Standalone options strategies that fire independently of equity MWA signals.
These are NOT "option enrichment on top of a stock signal" — they are
pure F&O plays based on IV, OI, PCR, max-pain, and expiry dynamics.

Strategies:

  1. IV Crush Play — sell premium when IV rank > 70 (pre-event spike)
  2. Cheap Premium Buy — buy options when IV rank < 25 (historically cheap)
  3. OI Buildup Directional — high OI buildup at a strike = wall = direction
  4. PCR Extreme Reversal — PCR > 1.5 (too bullish) or < 0.5 (too bearish)
  5. Expiry Day Straddle Sell — sell ATM straddle on expiry morning (theta decay)
  6. Max Pain Magnet — price far from max pain → mean-reversion toward it

Runs as a background loop every 10 minutes during F&O hours (9:15-15:30).
Targets NIFTY, BANKNIFTY + top F&O stocks. Uses Dhan option chain as
primary data source (Kite fallback).

Gated by settings.OPTION_SIGNALS_ENABLED (already true).
"""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Any

from mcp_server.config import settings
from mcp_server.market_calendar import is_market_open, now_ist

logger = logging.getLogger(__name__)

# Indices to scan for pure options plays — all tradeable index options
INDEX_UNIVERSE = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
# Top liquid F&O stocks for options signals
STOCK_UNIVERSE = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "BAJFINANCE", "TATAMOTORS", "LT", "AXISBANK",
    "KOTAKBANK", "MARUTI", "HINDUNILVR", "BHARTIARTL", "SUNPHARMA",
]

# VIX thresholds for strategy selection
VIX_HIGH = 20.0   # Above this → sell premium (expensive options)
VIX_LOW = 13.0    # Below this → buy premium (cheap options)
VIX_SPIKE = 8.0   # % change → VIX spike alert (intraday opportunity)


def _get_chain_and_data(symbol: str) -> dict[str, Any] | None:
    """Fetch option chain + IV rank + PCR + spot for a symbol.

    Tries Dhan first, then Kite. Returns None if both fail.
    """
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()

        # Spot price
        quote = provider.get_quote(symbol, exchange="NSE")
        spot = quote.get("ltp", 0) if quote else 0
        if not spot:
            return None

        # Option chain from Dhan
        chain: dict = {}
        expiry_str: str = ""
        dhan = provider.dhan
        if dhan and dhan.logged_in:
            expiry_list = dhan.get_expiry_list(symbol, exchange="NSE")
            today_str = str(date.today())
            valid = sorted([e for e in expiry_list if e >= today_str])
            if valid:
                expiry_str = valid[0]
                chain = dhan.get_option_chain(symbol, expiry_str, exchange="NSE")

        # Fallback to Kite
        if not chain:
            try:
                from mcp_server.fo_module import (
                    _find_current_expiry,
                    _get_kite_instruments,
                    _get_option_chain,
                )
                from mcp_server.mcp_server import _get_kite_for_fo
                kite = _get_kite_for_fo()
                if kite:
                    instruments = _get_kite_instruments(kite, "NFO")
                    expiry = _find_current_expiry(instruments, symbol)
                    if expiry:
                        chain = _get_option_chain(kite, instruments, symbol, expiry)
                        expiry_str = str(expiry)
            except Exception:
                pass

        if not chain:
            return None

        # Compute PCR from chain
        total_call_oi = sum(v.get("CE", {}).get("oi", 0) for v in chain.values())
        total_put_oi = sum(v.get("PE", {}).get("oi", 0) for v in chain.values())
        pcr = round(total_put_oi / max(total_call_oi, 1), 2)

        # Max pain: strike where total option buyers lose the most
        max_pain_strike = _calc_max_pain(chain, spot)

        # ATM IV from chain
        atm_strike = min(chain.keys(), key=lambda s: abs(s - spot))
        atm_data = chain.get(atm_strike, {})
        atm_iv = (
            atm_data.get("CE", {}).get("iv", 0) + atm_data.get("PE", {}).get("iv", 0)
        ) / 2

        # ATM premium
        atm_ce_ltp = atm_data.get("CE", {}).get("ltp", 0)
        atm_pe_ltp = atm_data.get("PE", {}).get("ltp", 0)

        # Expiry check
        is_expiry_day = expiry_str == str(date.today())
        days_to_expiry = 0
        if expiry_str:
            try:
                days_to_expiry = (date.fromisoformat(expiry_str) - date.today()).days
            except Exception:
                pass

        return {
            "symbol": symbol,
            "spot": spot,
            "chain": chain,
            "expiry": expiry_str,
            "pcr": pcr,
            "max_pain": max_pain_strike,
            "atm_iv": atm_iv,
            "atm_strike": atm_strike,
            "atm_ce_ltp": atm_ce_ltp,
            "atm_pe_ltp": atm_pe_ltp,
            "is_expiry_day": is_expiry_day,
            "days_to_expiry": days_to_expiry,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
        }
    except Exception as e:
        logger.debug("Options data failed for %s: %s", symbol, e)
        return None


def _calc_max_pain(chain: dict, spot: float) -> float:
    """Find the strike where total option-buyer losses are maximized."""
    if not chain:
        return spot
    strikes = sorted(chain.keys())
    min_pain = float("inf")
    max_pain_strike = spot
    for test_strike in strikes:
        pain = 0.0
        for strike, data in chain.items():
            ce_oi = data.get("CE", {}).get("oi", 0)
            pe_oi = data.get("PE", {}).get("oi", 0)
            if test_strike > strike:
                pain += ce_oi * (test_strike - strike)
            if test_strike < strike:
                pain += pe_oi * (strike - test_strike)
        if pain < min_pain:
            min_pain = pain
            max_pain_strike = test_strike
    return max_pain_strike


# ── Strategy scanners ──────────────────────────────────────────


def strategy_iv_crush(data: dict) -> dict[str, Any] | None:
    """IV rank > 70 → sell premium (credit strategy). IV will contract."""
    if data["atm_iv"] < 20:  # Need meaningful IV data
        return None
    # Simple heuristic: if ATM IV > 25% for indices or > 40% for stocks
    threshold = 25 if data["symbol"] in INDEX_UNIVERSE else 40
    if data["atm_iv"] < threshold:
        return None
    straddle_premium = data["atm_ce_ltp"] + data["atm_pe_ltp"]
    if straddle_premium <= 0:
        return None
    return {
        "symbol": data["symbol"],
        "strategy": "SHORT STRADDLE" if data["symbol"] in INDEX_UNIVERSE else "SHORT STRANGLE",
        "direction": "NEUTRAL",
        "strike": data["atm_strike"],
        "premium_collected": round(straddle_premium, 1),
        "sl_premium": round(straddle_premium * 1.5, 1),
        "target_premium": round(straddle_premium * 0.3, 1),
        "iv": round(data["atm_iv"], 1),
        "rationale": f"IV at {data['atm_iv']:.0f}% (high) — sell premium, expect IV crush",
        "pattern": "IV crush play",
        "expiry": data["expiry"],
        "days_to_expiry": data["days_to_expiry"],
    }


def strategy_cheap_premium(data: dict) -> dict[str, Any] | None:
    """IV rank < 25 → buy options cheap. Expect volatility expansion."""
    threshold = 15 if data["symbol"] in INDEX_UNIVERSE else 25
    if data["atm_iv"] > threshold or data["atm_iv"] <= 0:
        return None
    # Buy ATM CE or PE based on PCR sentiment
    if data["pcr"] > 1.0:
        opt_type = "CE"
        direction = "LONG"
        premium = data["atm_ce_ltp"]
    else:
        opt_type = "PE"
        direction = "SHORT"
        premium = data["atm_pe_ltp"]
    if premium <= 0:
        return None
    return {
        "symbol": data["symbol"],
        "strategy": f"BUY ATM {opt_type}",
        "direction": direction,
        "strike": data["atm_strike"],
        "premium_paid": round(premium, 1),
        "sl_premium": round(premium * 0.5, 1),
        "target_premium": round(premium * 2.0, 1),
        "iv": round(data["atm_iv"], 1),
        "rationale": f"IV at {data['atm_iv']:.0f}% (cheap) — buy {opt_type}, expect vol expansion",
        "pattern": "Cheap premium buy",
        "expiry": data["expiry"],
        "days_to_expiry": data["days_to_expiry"],
    }


def strategy_pcr_extreme(data: dict) -> dict[str, Any] | None:
    """PCR extreme → contrarian reversal."""
    pcr = data["pcr"]
    if 0.5 <= pcr <= 1.5:
        return None  # Normal range, no signal
    if pcr > 1.5:
        # Too many puts — crowd is too bearish → contrarian BULL
        direction = "LONG"
        opt_type = "CE"
        premium = data["atm_ce_ltp"]
        rationale = f"PCR {pcr:.2f} (extreme bearish) — contrarian BULL, buy CE"
    else:
        # Too many calls — crowd is too bullish → contrarian BEAR
        direction = "SHORT"
        opt_type = "PE"
        premium = data["atm_pe_ltp"]
        rationale = f"PCR {pcr:.2f} (extreme bullish) — contrarian BEAR, buy PE"
    if premium <= 0:
        return None
    return {
        "symbol": data["symbol"],
        "strategy": f"BUY {opt_type} (PCR contrarian)",
        "direction": direction,
        "strike": data["atm_strike"],
        "premium_paid": round(premium, 1),
        "sl_premium": round(premium * 0.5, 1),
        "target_premium": round(premium * 2.0, 1),
        "pcr": pcr,
        "rationale": rationale,
        "pattern": "PCR extreme reversal",
        "expiry": data["expiry"],
        "days_to_expiry": data["days_to_expiry"],
    }


def strategy_expiry_day(data: dict) -> dict[str, Any] | None:
    """Expiry day theta decay play — sell ATM straddle in the morning."""
    if not data["is_expiry_day"]:
        return None
    # Only fire before 11 AM — theta decay is fastest in morning
    if now_ist().time() > time(11, 0):
        return None
    straddle = data["atm_ce_ltp"] + data["atm_pe_ltp"]
    if straddle <= 0:
        return None
    return {
        "symbol": data["symbol"],
        "strategy": "EXPIRY SHORT STRADDLE",
        "direction": "NEUTRAL",
        "strike": data["atm_strike"],
        "premium_collected": round(straddle, 1),
        "sl_premium": round(straddle * 1.3, 1),
        "target_premium": round(straddle * 0.2, 1),
        "rationale": f"Expiry day — theta decay accelerates. Sell ATM straddle at {data['atm_strike']}",
        "pattern": "Expiry day straddle sell",
        "expiry": data["expiry"],
        "days_to_expiry": 0,
    }


def strategy_max_pain_magnet(data: dict) -> dict[str, Any] | None:
    """Price far from max pain → expect mean-reversion toward it."""
    spot = data["spot"]
    max_pain = data["max_pain"]
    if not max_pain or max_pain <= 0:
        return None
    distance_pct = abs(spot - max_pain) / spot * 100
    if distance_pct < 1.0:
        return None  # Already near max pain
    if distance_pct > 5.0:
        return None  # Too far — max pain may not hold

    if spot > max_pain:
        # Spot above max pain → expect pull down
        direction = "SHORT"
        opt_type = "PE"
        premium = data["atm_pe_ltp"]
        rationale = f"Spot {spot:.0f} is {distance_pct:.1f}% above max pain {max_pain:.0f} — expect pull down"
    else:
        direction = "LONG"
        opt_type = "CE"
        premium = data["atm_ce_ltp"]
        rationale = f"Spot {spot:.0f} is {distance_pct:.1f}% below max pain {max_pain:.0f} — expect pull up"
    if premium <= 0:
        return None
    return {
        "symbol": data["symbol"],
        "strategy": f"BUY {opt_type} (max pain magnet)",
        "direction": direction,
        "strike": data["atm_strike"],
        "premium_paid": round(premium, 1),
        "sl_premium": round(premium * 0.5, 1),
        "target_premium": round(premium * 1.8, 1),
        "max_pain": max_pain,
        "distance_pct": round(distance_pct, 1),
        "rationale": rationale,
        "pattern": "Max pain magnet",
        "expiry": data["expiry"],
        "days_to_expiry": data["days_to_expiry"],
    }


def strategy_oi_wall(data: dict) -> dict[str, Any] | None:
    """Highest OI strike acts as support/resistance → directional bias."""
    chain = data["chain"]
    if not chain:
        return None
    spot = data["spot"]

    # Find strike with highest call OI (resistance) and put OI (support)
    max_call_oi = 0
    max_call_strike = 0
    max_put_oi = 0
    max_put_strike = 0
    for strike, sdata in chain.items():
        ce_oi = sdata.get("CE", {}).get("oi", 0)
        pe_oi = sdata.get("PE", {}).get("oi", 0)
        if ce_oi > max_call_oi:
            max_call_oi = ce_oi
            max_call_strike = strike
        if pe_oi > max_put_oi:
            max_put_oi = pe_oi
            max_put_strike = strike

    if max_call_oi == 0 or max_put_oi == 0:
        return None

    # If spot is between the two walls, trade toward the closer wall
    if max_put_strike < spot < max_call_strike:
        dist_to_support = spot - max_put_strike
        dist_to_resistance = max_call_strike - spot
        if dist_to_resistance < dist_to_support * 0.5:
            # Very close to resistance — bearish
            return {
                "symbol": data["symbol"],
                "strategy": f"BUY PE (OI resistance at {max_call_strike:.0f})",
                "direction": "SHORT",
                "strike": data["atm_strike"],
                "premium_paid": round(data["atm_pe_ltp"], 1),
                "sl_premium": round(data["atm_pe_ltp"] * 0.5, 1),
                "target_premium": round(data["atm_pe_ltp"] * 2.0, 1),
                "oi_resistance": max_call_strike,
                "oi_support": max_put_strike,
                "rationale": f"OI wall: {max_call_oi:,} calls at {max_call_strike:.0f} = resistance. Spot near wall.",
                "pattern": "OI wall resistance",
                "expiry": data["expiry"],
                "days_to_expiry": data["days_to_expiry"],
            }
        if dist_to_support < dist_to_resistance * 0.5:
            # Very close to support — bullish
            return {
                "symbol": data["symbol"],
                "strategy": f"BUY CE (OI support at {max_put_strike:.0f})",
                "direction": "LONG",
                "strike": data["atm_strike"],
                "premium_paid": round(data["atm_ce_ltp"], 1),
                "sl_premium": round(data["atm_ce_ltp"] * 0.5, 1),
                "target_premium": round(data["atm_ce_ltp"] * 2.0, 1),
                "oi_resistance": max_call_strike,
                "oi_support": max_put_strike,
                "rationale": f"OI wall: {max_put_oi:,} puts at {max_put_strike:.0f} = support. Spot near wall.",
                "pattern": "OI wall support",
                "expiry": data["expiry"],
                "days_to_expiry": data["days_to_expiry"],
            }
    return None


def _get_vix_data() -> dict[str, float] | None:
    """Fetch India VIX current value + % change."""
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        # Try NSE India source for VIX
        try:
            quote = provider.nse.get_quote("INDIA VIX")
            if quote and quote.get("ltp"):
                return {
                    "vix": float(quote["ltp"]),
                    "pct_change": float(quote.get("pct_change", 0)),
                }
        except Exception:
            pass
        # Fallback: yfinance ^INDIAVIX
        try:
            import yfinance as yf
            data = yf.download("^INDIAVIX", period="2d", progress=False)
            if not data.empty:
                vix = float(data["Close"].iloc[-1])
                prev = float(data["Close"].iloc[-2]) if len(data) > 1 else vix
                pct = ((vix - prev) / prev * 100) if prev else 0
                return {"vix": vix, "pct_change": pct}
        except Exception:
            pass
    except Exception:
        pass
    return None


def strategy_vix_spike(data: dict, vix_data: dict | None = None) -> dict[str, Any] | None:
    """VIX spike → sell premium on NIFTY/BANKNIFTY. High VIX = expensive options."""
    if not vix_data or data["symbol"] not in INDEX_UNIVERSE:
        return None
    vix = vix_data.get("vix", 0)
    vix_chg = vix_data.get("pct_change", 0)

    # VIX spike (>8% jump) → premium is inflated, sell it
    if vix_chg >= VIX_SPIKE and vix >= VIX_HIGH:
        straddle = data["atm_ce_ltp"] + data["atm_pe_ltp"]
        if straddle <= 0:
            return None
        return {
            "symbol": data["symbol"],
            "strategy": f"SHORT STRADDLE (VIX spike {vix:.1f})",
            "direction": "NEUTRAL",
            "strike": data["atm_strike"],
            "premium_collected": round(straddle, 1),
            "sl_premium": round(straddle * 1.3, 1),
            "target_premium": round(straddle * 0.4, 1),
            "iv": round(data["atm_iv"], 1),
            "vix": round(vix, 2),
            "vix_change": round(vix_chg, 1),
            "rationale": (
                f"India VIX spiked +{vix_chg:.1f}% to {vix:.1f} — "
                f"options are expensive. Sell ATM straddle, target 60% decay."
            ),
            "pattern": "VIX spike premium sell",
            "expiry": data["expiry"],
            "days_to_expiry": data["days_to_expiry"],
        }

    # VIX very low → premiums cheap, buy straddle for breakout
    if vix <= VIX_LOW and data["days_to_expiry"] >= 3:
        straddle = data["atm_ce_ltp"] + data["atm_pe_ltp"]
        if straddle <= 0:
            return None
        return {
            "symbol": data["symbol"],
            "strategy": f"LONG STRADDLE (VIX low {vix:.1f})",
            "direction": "NEUTRAL",
            "strike": data["atm_strike"],
            "premium_paid": round(straddle, 1),
            "sl_premium": round(straddle * 0.5, 1),
            "target_premium": round(straddle * 2.0, 1),
            "iv": round(data["atm_iv"], 1),
            "vix": round(vix, 2),
            "vix_change": round(vix_chg, 1),
            "rationale": (
                f"India VIX at {vix:.1f} (low) — options are cheap. "
                f"Buy ATM straddle, expect volatility expansion."
            ),
            "pattern": "VIX low straddle buy",
            "expiry": data["expiry"],
            "days_to_expiry": data["days_to_expiry"],
        }
    return None


ALL_STRATEGIES = [
    strategy_iv_crush,
    strategy_cheap_premium,
    strategy_pcr_extreme,
    strategy_expiry_day,
    strategy_max_pain_magnet,
    strategy_oi_wall,
    strategy_vix_spike,
]


# ── Main scan ──────────────────────────────────────────────────

def run_options_scan() -> list[dict[str, Any]]:
    """Scan all symbols for pure options signals. Returns list of strategy dicts."""
    if not getattr(settings, "OPTION_SIGNALS_ENABLED", True):
        return []
    if not is_market_open("NSE"):
        return []
    mkt_time = now_ist().time()
    if not (time(9, 15) <= mkt_time <= time(15, 15)):
        return []

    universe = INDEX_UNIVERSE + STOCK_UNIVERSE
    signals: list[dict[str, Any]] = []

    # Fetch India VIX once per scan — shared across all strategies
    vix_data = _get_vix_data()
    if vix_data:
        logger.info(
            "[OPTIONS] India VIX: %.2f (%+.1f%%)",
            vix_data.get("vix", 0), vix_data.get("pct_change", 0),
        )

    for symbol in universe:
        data = _get_chain_and_data(symbol)
        if not data:
            continue

        for strategy_fn in ALL_STRATEGIES:
            try:
                result = strategy_fn(data, vix_data=vix_data)
            except TypeError:
                # Strategies that don't accept vix_data kwarg
                try:
                    result = strategy_fn(data)
                except Exception:
                    result = None
            except Exception as e:
                logger.debug("Options strategy %s failed for %s: %s", strategy_fn.__name__, symbol, e)
                result = None
            if result:
                # Attach VIX to every signal for the card
                if vix_data:
                    result.setdefault("vix", vix_data.get("vix"))
                    result.setdefault("vix_change", vix_data.get("pct_change"))
                signals.append(result)

    logger.info("[OPTIONS] %d pure option signals from %d symbols", len(signals), len(universe))
    return signals


def format_option_signal_card(sig: dict) -> str:
    """Format a pure options signal for Telegram."""
    sep = "\u2501" * 24
    premium_key = "premium_collected" if "premium_collected" in sig else "premium_paid"
    action = "SELL" if "collected" in premium_key else "BUY"
    premium = sig.get(premium_key, 0)

    lines = [
        "\U0001f3af OPTIONS Signal",
        sep,
        f"Symbol: {sig['symbol']}",
        f"Strategy: {sig['strategy']}",
        f"Direction: {sig['direction']}",
        sep,
        f"Strike: {sig.get('strike', 'ATM')}",
        f"{action}: \u20b9{premium:.1f}",
        f"SL: \u20b9{sig.get('sl_premium', 0):.1f} | TGT: \u20b9{sig.get('target_premium', 0):.1f}",
        sep,
    ]

    if sig.get("vix"):
        vix_chg = sig.get("vix_change", 0)
        vix_arrow = "\u2191" if vix_chg > 0 else "\u2193" if vix_chg < 0 else ""
        lines.append(f"India VIX: {sig['vix']:.2f} ({vix_arrow}{vix_chg:+.1f}%)")
    if sig.get("iv"):
        lines.append(f"IV: {sig['iv']:.0f}%")
    if sig.get("pcr"):
        lines.append(f"PCR: {sig['pcr']:.2f}")
    if sig.get("max_pain"):
        lines.append(f"Max Pain: {sig['max_pain']:.0f}")
    if sig.get("oi_resistance"):
        lines.append(f"OI Wall: Support {sig['oi_support']:.0f} | Resistance {sig['oi_resistance']:.0f}")

    lines.append(f"Expiry: {sig.get('expiry', '?')} ({sig.get('days_to_expiry', '?')}d)")
    lines.append(sep)
    lines.append(sig.get("rationale", ""))

    return "\n".join(lines)
