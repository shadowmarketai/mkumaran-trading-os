"""
MKUMARAN Trading OS — Options Payoff Calculator

Multi-leg options payoff computation with:
- Single and multi-leg P&L calculation
- Automatic breakeven detection via zero-crossing interpolation
- Max profit/loss computation
- Strategy presets (iron condor, straddle, etc.)
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Data Structures ─────────────────────────────────────────────


@dataclass
class OptionLeg:
    """Single option leg in a strategy."""
    strike: float
    premium: float
    qty: int = 1
    option_type: str = "CE"  # CE or PE
    action: str = "BUY"      # BUY or SELL


@dataclass
class PayoffPoint:
    """P&L at a specific spot price."""
    spot: float
    pnl: float


@dataclass
class PayoffResult:
    """Complete payoff analysis result."""
    points: list[PayoffPoint] = field(default_factory=list)
    breakevens: list[float] = field(default_factory=list)
    max_profit: float = 0.0
    max_loss: float = 0.0
    net_premium: float = 0.0


# ── Core Payoff Calculation ─────────────────────────────────────


def _single_leg_payoff(leg: OptionLeg, spot: float) -> float:
    """
    Calculate P&L for a single option leg at a given spot price.

    For BUY: P&L = intrinsic_value - premium_paid
    For SELL: P&L = premium_received - intrinsic_value
    """
    is_call = leg.option_type.upper() == "CE"

    if is_call:
        intrinsic = max(spot - leg.strike, 0.0)
    else:
        intrinsic = max(leg.strike - spot, 0.0)

    if leg.action.upper() == "BUY":
        pnl = (intrinsic - leg.premium) * leg.qty
    else:
        pnl = (leg.premium - intrinsic) * leg.qty

    return pnl


def calculate_payoff(
    legs: list[OptionLeg],
    spot_min: float = 0,
    spot_max: float = 0,
    num_points: int = 200,
) -> PayoffResult:
    """
    Calculate combined payoff for a multi-leg options strategy.

    Args:
        legs: List of OptionLeg objects
        spot_min: Minimum spot for the range (auto if 0)
        spot_max: Maximum spot for the range (auto if 0)
        num_points: Number of points in the payoff curve

    Returns:
        PayoffResult with points, breakevens, max profit/loss, net premium
    """
    if not legs:
        return PayoffResult()

    # Auto-calculate spot range based on strikes
    strikes = [leg.strike for leg in legs]
    min_strike = min(strikes)
    max_strike = max(strikes)
    spread = max_strike - min_strike if max_strike > min_strike else max_strike * 0.20

    if spot_min <= 0:
        spot_min = min_strike - spread * 0.5
        spot_min = max(spot_min, 0)  # Never negative
    if spot_max <= 0:
        spot_max = max_strike + spread * 0.5

    # Calculate net premium
    net_premium = 0.0
    for leg in legs:
        if leg.action.upper() == "BUY":
            net_premium -= leg.premium * leg.qty  # Paid
        else:
            net_premium += leg.premium * leg.qty  # Received

    # Generate payoff points
    step = (spot_max - spot_min) / max(num_points - 1, 1)
    points: list[PayoffPoint] = []
    all_pnl: list[float] = []

    for i in range(num_points):
        spot = spot_min + i * step
        total_pnl = sum(_single_leg_payoff(leg, spot) for leg in legs)
        points.append(PayoffPoint(spot=round(spot, 2), pnl=round(total_pnl, 2)))
        all_pnl.append(total_pnl)

    # Find breakevens (zero crossings)
    breakevens = calculate_breakevens_from_points(points)

    # Max profit and loss
    max_profit = max(all_pnl) if all_pnl else 0.0
    max_loss = min(all_pnl) if all_pnl else 0.0

    return PayoffResult(
        points=points,
        breakevens=[round(b, 2) for b in breakevens],
        max_profit=round(max_profit, 2),
        max_loss=round(max_loss, 2),
        net_premium=round(net_premium, 2),
    )


def calculate_breakevens_from_points(points: list[PayoffPoint]) -> list[float]:
    """
    Find breakeven prices by detecting zero crossings in the payoff curve.
    Uses linear interpolation between adjacent points.
    """
    breakevens: list[float] = []

    for i in range(1, len(points)):
        p1 = points[i - 1]
        p2 = points[i]

        # Check for sign change (zero crossing)
        if (p1.pnl > 0 and p2.pnl < 0) or (p1.pnl < 0 and p2.pnl > 0):
            # Linear interpolation
            denom = p1.pnl - p2.pnl
            if abs(denom) > 1e-10:
                breakeven = p1.spot + p1.pnl * (p2.spot - p1.spot) / denom
                breakevens.append(breakeven)
        elif abs(p1.pnl) < 1e-6:
            breakevens.append(p1.spot)

    return breakevens


# ── Strategy Presets ────────────────────────────────────────────


def bull_call_spread(
    lower_strike: float,
    upper_strike: float,
    lower_premium: float,
    upper_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """Buy lower strike call, sell upper strike call."""
    return [
        OptionLeg(strike=lower_strike, premium=lower_premium, qty=qty, option_type="CE", action="BUY"),
        OptionLeg(strike=upper_strike, premium=upper_premium, qty=qty, option_type="CE", action="SELL"),
    ]


def bear_put_spread(
    upper_strike: float,
    lower_strike: float,
    upper_premium: float,
    lower_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """Buy upper strike put, sell lower strike put."""
    return [
        OptionLeg(strike=upper_strike, premium=upper_premium, qty=qty, option_type="PE", action="BUY"),
        OptionLeg(strike=lower_strike, premium=lower_premium, qty=qty, option_type="PE", action="SELL"),
    ]


def long_straddle(
    strike: float,
    call_premium: float,
    put_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """Buy call and put at same strike."""
    return [
        OptionLeg(strike=strike, premium=call_premium, qty=qty, option_type="CE", action="BUY"),
        OptionLeg(strike=strike, premium=put_premium, qty=qty, option_type="PE", action="BUY"),
    ]


def long_strangle(
    call_strike: float,
    put_strike: float,
    call_premium: float,
    put_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """Buy OTM call and OTM put at different strikes."""
    return [
        OptionLeg(strike=call_strike, premium=call_premium, qty=qty, option_type="CE", action="BUY"),
        OptionLeg(strike=put_strike, premium=put_premium, qty=qty, option_type="PE", action="BUY"),
    ]


def iron_condor(
    put_buy_strike: float,
    put_sell_strike: float,
    call_sell_strike: float,
    call_buy_strike: float,
    put_buy_premium: float,
    put_sell_premium: float,
    call_sell_premium: float,
    call_buy_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Iron Condor: Buy OTM put, sell ATM put, sell ATM call, buy OTM call.
    4 legs total.
    """
    return [
        OptionLeg(strike=put_buy_strike, premium=put_buy_premium, qty=qty, option_type="PE", action="BUY"),
        OptionLeg(strike=put_sell_strike, premium=put_sell_premium, qty=qty, option_type="PE", action="SELL"),
        OptionLeg(strike=call_sell_strike, premium=call_sell_premium, qty=qty, option_type="CE", action="SELL"),
        OptionLeg(strike=call_buy_strike, premium=call_buy_premium, qty=qty, option_type="CE", action="BUY"),
    ]


def butterfly_spread(
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    lower_premium: float,
    middle_premium: float,
    upper_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Long Butterfly: Buy 1 lower call, sell 2 middle calls, buy 1 upper call.
    """
    return [
        OptionLeg(strike=lower_strike, premium=lower_premium, qty=qty, option_type="CE", action="BUY"),
        OptionLeg(strike=middle_strike, premium=middle_premium, qty=qty * 2, option_type="CE", action="SELL"),
        OptionLeg(strike=upper_strike, premium=upper_premium, qty=qty, option_type="CE", action="BUY"),
    ]
