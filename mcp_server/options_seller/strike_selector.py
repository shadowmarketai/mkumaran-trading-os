"""
MKUMARAN Trading OS — Options Seller: Strangle / Iron Condor Strike Selector

Selects the call and put strikes for a short strangle or iron condor
entry based on a target-delta approach, consistent with the 6-instrument
universe:

  NSE NFO: BANKNIFTY, NIFTY, MIDCPNIFTY, FINNIFTY
  BSE BFO: SENSEX, BANKEX

Iron condor (default, recommended)
───────────────────────────────────
  Short call (delta ≈ +target)  +  Short put (delta ≈ −target)
  Long call  (short_strike + wing_width)
  Long put   (short_strike − wing_width)

  Max loss = wing_width − net_credit (defined, limited)
  Max gain = net_credit collected

Naked strangle (operator opt-in only)
──────────────────────────────────────
  Short call + short put at target delta — no protective wings.
  Margin is roughly 3× the iron condor; theoretically unlimited risk.
  Use only when capital and experience justify it.

All money values are float (analysis zone). The position_manager
converts to Decimal when persisting P&L.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Lot sizes per instrument ─────────────────────────────────
LOT_SIZES: dict[str, int] = {
    "BANKNIFTY":   15,
    "NIFTY":       25,
    "MIDCPNIFTY":  50,
    "FINNIFTY":    25,
    "SENSEX":      10,
    "BANKEX":      15,
}

DEFAULT_LOT_SIZE = 25  # fallback for unknown instruments


@dataclass
class StrangeLeg:
    """One leg of a strangle or condor."""
    strike: float
    option_type: str   # "CE" | "PE"
    side: str          # "SELL" | "BUY"
    delta: float
    premium: float
    lot_size: int


@dataclass
class StranglePosition:
    """Full strangle or iron condor structure."""
    instrument: str
    spot: float
    dte: int                              # days to expiry at entry
    structure: str                        # "IRON_CONDOR" | "NAKED_STRANGLE"
    legs: list[StrangeLeg] = field(default_factory=list)

    # Summary P&L metrics
    net_credit: float = 0.0
    max_loss: float = 0.0
    breakeven_upper: float = 0.0
    breakeven_lower: float = 0.0
    range_width_pct: float = 0.0

    # Short-leg deltas (for adjustment monitoring)
    short_call_strike: float = 0.0
    short_put_strike: float = 0.0
    short_call_delta: float = 0.0
    short_put_delta: float = 0.0

    def as_dict(self) -> dict:
        return {
            "instrument":        self.instrument,
            "spot":              self.spot,
            "dte":               self.dte,
            "structure":         self.structure,
            "net_credit":        round(self.net_credit, 2),
            "max_loss":          round(self.max_loss, 2),
            "breakeven_upper":   round(self.breakeven_upper, 2),
            "breakeven_lower":   round(self.breakeven_lower, 2),
            "range_width_pct":   round(self.range_width_pct, 2),
            "short_call_strike": self.short_call_strike,
            "short_put_strike":  self.short_put_strike,
            "short_call_delta":  round(self.short_call_delta, 3),
            "short_put_delta":   round(self.short_put_delta, 3),
            "legs": [
                {
                    "strike":      leg.strike,
                    "option_type": leg.option_type,
                    "side":        leg.side,
                    "delta":       round(leg.delta, 3),
                    "premium":     round(leg.premium, 2),
                    "lot_size":    leg.lot_size,
                }
                for leg in self.legs
            ],
        }


def _lot_size(instrument: str) -> int:
    return LOT_SIZES.get(instrument.upper(), DEFAULT_LOT_SIZE)


def _nearest_strike(strikes: list[float], target: float) -> float:
    return min(strikes, key=lambda s: abs(s - target))


def _build_chain_greeks(
    chain: dict,
    spot: float,
    dte: int,
) -> dict[float, dict]:
    """
    For each strike in the chain, compute live Greeks if not already present.
    Returns {strike: {"CE": GreeksResult, "PE": GreeksResult}}.
    """
    from mcp_server.options_greeks import calculate_greeks

    result: dict[float, dict] = {}
    for strike_raw, opts in chain.items():
        try:
            strike = float(strike_raw)
        except (ValueError, TypeError):
            continue

        row: dict = {}
        for opt_type in ("CE", "PE"):
            slot = opts.get(opt_type) or {}
            premium = float(slot.get("ltp", slot.get("lastPrice", 0)) or 0)
            iv      = float(slot.get("iv", slot.get("impliedVolatility", 0.18)) or 0.18)
            if iv < 0.01:
                iv = 0.18   # floor at 18% if chain has no IV
            greeks = calculate_greeks(
                spot=spot,
                strike=strike,
                expiry_days=max(dte, 0.1),
                volatility=iv,
                option_type=opt_type,
            )
            # Attach raw premium (may differ from BS price due to bid-ask)
            greeks.price = premium if premium > 0 else greeks.price
            row[opt_type] = greeks
        result[strike] = row
    return result


def _find_target_delta_strike(
    chain_greeks: dict[float, dict],
    opt_type: str,
    target_delta: float,
) -> tuple[float, float, float] | None:
    """Find the strike whose absolute delta is closest to target_delta.

    Returns (strike, delta, premium) or None if chain is empty.
    target_delta should be positive (0.15 for 15-delta).
    """
    best_strike = best_delta = best_premium = None
    best_dist = float("inf")

    for strike, row in chain_greeks.items():
        greeks = row.get(opt_type)
        if greeks is None:
            continue
        delta = abs(greeks.delta)
        dist  = abs(delta - target_delta)
        if dist < best_dist and greeks.price > 0:
            best_dist    = dist
            best_strike  = strike
            best_delta   = greeks.delta
            best_premium = greeks.price

    if best_strike is None:
        return None
    return best_strike, best_delta, best_premium


def build_strangle(
    instrument: str,
    spot: float,
    chain: dict,
    dte: int,
    target_delta: float = 0.15,
    min_premium: float = 30.0,
    structure: str = "IRON_CONDOR",
    wing_width_strikes: int = 1,
) -> StranglePosition | None:
    """Build a short strangle or iron condor from a live options chain.

    Args:
        instrument:          e.g. "BANKNIFTY"
        spot:                current underlying price
        chain:               {strike: {"CE": {ltp, iv, ...}, "PE": {...}}}
        dte:                 days to expiry
        target_delta:        absolute delta for short legs (default 0.15)
        min_premium:         minimum net credit in points to proceed
        structure:           "IRON_CONDOR" (default) or "NAKED_STRANGLE"
        wing_width_strikes:  number of strike steps for protective wings
                             (only used for IRON_CONDOR)

    Returns:
        StranglePosition or None if the chain is too sparse or premium
        is below min_premium.
    """
    inst = instrument.upper()
    lot  = _lot_size(inst)

    chain_greeks = _build_chain_greeks(chain, spot, dte)
    if not chain_greeks:
        logger.warning("strike_selector: empty chain for %s", inst)
        return None

    # ── Find short call (target positive delta ≈ target_delta) ──
    call_result = _find_target_delta_strike(chain_greeks, "CE", target_delta)
    put_result  = _find_target_delta_strike(chain_greeks, "PE", target_delta)

    if call_result is None or put_result is None:
        logger.warning("strike_selector: could not find target-delta strikes for %s", inst)
        return None

    sc_strike, sc_delta, sc_premium = call_result
    sp_strike, sp_delta, sp_premium = put_result

    if sc_strike <= sp_strike:
        logger.warning(
            "strike_selector: short-call strike (%.0f) ≤ put strike (%.0f) for %s — "
            "chain may be stale or spot is off",
            sc_strike, sp_strike, inst,
        )
        return None

    net_credit = sc_premium + sp_premium
    if net_credit < min_premium:
        logger.info(
            "strike_selector: net credit %.2f < min_premium %.2f for %s — skipping",
            net_credit, min_premium, inst,
        )
        return None

    legs: list[StrangeLeg] = [
        StrangeLeg(sc_strike, "CE", "SELL", sc_delta, sc_premium, lot),
        StrangeLeg(sp_strike, "PE", "SELL", sp_delta, sp_premium, lot),
    ]

    max_loss = float("inf")

    if structure == "IRON_CONDOR":
        # Add protective wings — strike_step × wing_width_strikes beyond short legs
        strikes = sorted(chain_greeks.keys())
        step = (strikes[1] - strikes[0]) if len(strikes) >= 2 else 50.0

        lc_strike = sc_strike + step * wing_width_strikes
        lp_strike = sp_strike - step * wing_width_strikes

        # Long call premium
        lc_row = chain_greeks.get(_nearest_strike(strikes, lc_strike), {})
        lc_greeks = lc_row.get("CE")
        lc_premium = float(lc_greeks.price) if lc_greeks else 0.0

        # Long put premium
        lp_row = chain_greeks.get(_nearest_strike(strikes, lp_strike), {})
        lp_greeks = lp_row.get("PE")
        lp_premium = float(lp_greeks.price) if lp_greeks else 0.0

        net_credit -= (lc_premium + lp_premium)
        max_loss = (step * wing_width_strikes) - net_credit

        legs.extend([
            StrangeLeg(lc_strike, "CE", "BUY",
                       lc_greeks.delta if lc_greeks else 0, lc_premium, lot),
            StrangeLeg(lp_strike, "PE", "BUY",
                       lp_greeks.delta if lp_greeks else 0, lp_premium, lot),
        ])

    breakeven_upper = sc_strike + net_credit
    breakeven_lower = sp_strike - net_credit
    range_width = (sc_strike - sp_strike) / spot * 100

    pos = StranglePosition(
        instrument=inst,
        spot=spot,
        dte=dte,
        structure=structure,
        legs=legs,
        net_credit=net_credit,
        max_loss=max_loss,
        breakeven_upper=breakeven_upper,
        breakeven_lower=breakeven_lower,
        range_width_pct=range_width,
        short_call_strike=sc_strike,
        short_put_strike=sp_strike,
        short_call_delta=sc_delta,
        short_put_delta=sp_delta,
    )

    logger.info(
        "strike_selector: %s %s — credit=%.2f BEU/BEL=%.0f/%.0f "
        "ΔC=%.2f ΔP=%.2f",
        inst, structure, net_credit,
        breakeven_upper, breakeven_lower,
        sc_delta, sp_delta,
    )
    return pos
