"""
MKUMARAN Trading OS — Quad Confluence, Options Edition

Applies the 4-of-4 AND gate to index options.

DESIGN NOTE — where the conditions are computed
------------------------------------------------
The four conditions are computed on the UNDERLYING index bars (NIFTY spot /
futures), never on the option premium. RSI, Bollinger and pivots on a
decaying premium series are close to meaningless: theta drags the series
down independently of direction, so an RSI on premium measures decay as
much as momentum. The signal comes from the index; only the EXECUTION is
in the option.

Entry (all four true on the same closed index bar):
  1. SuperTrend(10,2)  close > ST line          -> buy CE
                       close < ST line          -> buy PE (bearish mirror)
  2. RSI(14) > 70 for CE   /  RSI(14) < 30 for PE
  3. close > R1 for CE     /  close < S1 for PE   (traditional pivots)
  4. close > upper BB      /  close < lower BB    (20,2)

Exit: SuperTrend flip on the index (the deck's trailing rule).

WHAT IS AND ISN'T VALIDATED
---------------------------
The underlying-move backtest (scripts/backtest_quad_options.py) measures
whether the INDEX moves favourably after a 4/4 trigger. It does NOT measure
option P&L, because option premium history is not in the OHLCV cache. This
matters, and the gap is not small:

  - A favourable index move can still lose money on the option if the move
    is slow (theta) or if IV contracts after entry (vega).
  - Today's India VIX is ~10.7, historically low. Long-premium strategies
    are structurally harder in low-IV regimes.
  - The deck's own examples are 3-minute charts. On 15m bars this is a
    different strategy with different trigger frequency.

Treat the underlying backtest as a NECESSARY-BUT-NOT-SUFFICIENT filter: if
the index doesn't move after 4/4, the option definitely loses. If it does
move, the option MIGHT profit — that still needs paper trading to confirm.

Default posture is PAPER. Do not size real capital off this module until
the paper record exists.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from mcp_server.quad_confluence import (
    BB_MULT,
    BB_PERIOD,
    RSI_MIN,
    _adx,
    _supertrend,
    _traditional_pivots,
    _wilder_atr,
    _wilder_rsi,
)

logger = logging.getLogger(__name__)

RSI_MAX_BEAR = 100.0 - RSI_MIN          # 30 when RSI_MIN is 70
QUAD_OPT_ADX_MIN = 0.0                  # OFF by default: the daily-bar test
                                        # showed ADX cut expectancy (0.78 -> 0.42)
STRIKE_STEPS = {                        # ATM rounding per index
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
}
MIN_DTE = 2          # avoid 0-1 DTE: gamma makes the premium stop meaningless
MAX_DTE = 45
SL_PREMIUM_PCT = 0.35    # stop at -35% of premium paid
TGT_PREMIUM_PCT = 0.70   # target at +70% of premium paid


def compute_index_conditions(df: pd.DataFrame) -> pd.DataFrame:
    """Attach bullish and bearish 4-condition gates to index OHLCV bars.

    All indicators use data at or before each bar's close; pivots use the
    prior bar explicitly. No look-ahead.
    """
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]

    st = _supertrend(out)
    piv = _traditional_pivots(out)
    sma = out["close"].rolling(BB_PERIOD).mean()
    std = out["close"].rolling(BB_PERIOD).std(ddof=0)   # population std

    out["st_line"] = st["st_line"]
    out["st_dir"] = st["st_dir"]
    out["rsi"] = _wilder_rsi(out["close"])
    out["r1"] = piv["r1"]
    out["s1"] = piv["s1"]
    out["bb_upper"] = sma + BB_MULT * std
    out["bb_lower"] = sma - BB_MULT * std
    out["adx"] = _adx(out)
    out["atr"] = _wilder_atr(out)

    adx_ok = out["adx"] >= QUAD_OPT_ADX_MIN if QUAD_OPT_ADX_MIN > 0 else True

    # Bullish -> buy CE
    out["ce_c1"] = (out["close"] > out["st_line"]) & (out["st_dir"] == 1)
    out["ce_c2"] = out["rsi"] > RSI_MIN
    out["ce_c3"] = out["close"] > out["r1"]
    out["ce_c4"] = out["close"] > out["bb_upper"]
    out["ce_count"] = out[["ce_c1", "ce_c2", "ce_c3", "ce_c4"]].sum(axis=1).astype(int)
    out["entry_ce"] = (out["ce_count"] == 4) & adx_ok

    # Bearish -> buy PE
    out["pe_c1"] = (out["close"] < out["st_line"]) & (out["st_dir"] == -1)
    out["pe_c2"] = out["rsi"] < RSI_MAX_BEAR
    out["pe_c3"] = out["close"] < out["s1"]
    out["pe_c4"] = out["close"] < out["bb_lower"]
    out["pe_count"] = out[["pe_c1", "pe_c2", "pe_c3", "pe_c4"]].sum(axis=1).astype(int)
    out["entry_pe"] = (out["pe_count"] == 4) & adx_ok

    return out


def atm_strike(spot: float, symbol: str) -> float:
    """Round spot to the nearest tradeable strike for this index."""
    step = STRIKE_STEPS.get(symbol, 50)
    return round(spot / step) * step


def strategy_quad_confluence(
    data: dict, index_bars: pd.DataFrame | None = None, **_kw: Any
) -> dict[str, Any] | None:
    """Options-engine strategy hook: emit a CE/PE buy on a 4/4 index trigger.

    `data` is the dict from _get_chain_and_data() (spot, atm_strike, expiry,
    days_to_expiry, atm_iv, atm_iv_is_proxy...). `index_bars` is recent
    intraday OHLCV for the underlying; without it the strategy cannot fire,
    and it returns None rather than guessing.
    """
    symbol = data.get("symbol", "")
    if symbol not in STRIKE_STEPS:
        return None                      # index options only

    if index_bars is None or len(index_bars) < BB_PERIOD + 15:
        logger.debug("[QUAD] %s: no index bars — cannot evaluate", symbol)
        return None

    dte = int(data.get("days_to_expiry", 0) or 0)
    if dte < MIN_DTE or dte > MAX_DTE:
        return None

    # A VIX-proxy IV means this instrument's own chain IV was never measured.
    # Long premium on a borrowed IV number is exactly the bug that produced
    # the 11%-vs-30% MIDCPNIFTY contradiction — refuse to fire.
    if data.get("atm_iv_is_proxy"):
        logger.debug("[QUAD] %s: atm_iv is a VIX proxy — skipping", symbol)
        return None

    cond = compute_index_conditions(index_bars)
    last = cond.iloc[-1]

    if bool(last["entry_ce"]):
        side, opt_type = "BULLISH", "CE"
    elif bool(last["entry_pe"]):
        side, opt_type = "BEARISH", "PE"
    else:
        return None

    spot = float(data.get("spot", 0) or 0)
    if spot <= 0:
        return None
    strike = atm_strike(spot, symbol)

    leg = (data.get("chain", {}) or {}).get(str(strike), {}).get(opt_type, {})
    premium = float(leg.get("ltp", 0) or 0)
    if premium <= 0:
        logger.debug("[QUAD] %s: no premium for %s %s", symbol, strike, opt_type)
        return None

    return {
        "symbol": symbol,
        "strategy": f"QUAD CONFLUENCE {opt_type}",
        "direction": side,
        "strike": strike,
        "option_type": opt_type,
        "premium": round(premium, 1),
        "sl_premium": round(premium * (1 - SL_PREMIUM_PCT), 1),
        "target_premium": round(premium * (1 + TGT_PREMIUM_PCT), 1),
        "spot_at_entry": round(spot, 2),
        "index_st_line": round(float(last["st_line"]), 2),
        "index_rsi": round(float(last["rsi"]), 1),
        "atm_iv": round(float(data.get("atm_iv", 0) or 0), 1),
        "rationale": (
            f"4/4 confluence on {symbol} index: SuperTrend + RSI "
            f"{float(last['rsi']):.0f} + pivot + BB all aligned {side.lower()}. "
            f"Exit on SuperTrend flip ({float(last['st_line']):.0f})."
        ),
        "pattern": "quad_confluence_4x_options",
        "expiry": data.get("expiry"),
        "days_to_expiry": dte,
        "paper_only": True,   # not validated on option P&L — see module docstring
    }
