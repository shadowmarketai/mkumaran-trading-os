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


# ── Advanced Strategy Presets ───────────────────────────────────


def short_straddle(
    strike: float,
    call_premium: float,
    put_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Short Straddle: Sell call + sell put at same strike.

    Profile  : Limited profit (net credit), unlimited loss
    Bias     : Neutral, expect spot to stay near strike
    Best when: IV rank > 80 (vol crush play)
    Greeks   : Negative gamma, positive theta, negative vega
    Risk     : UNLIMITED on both sides — use only with margin + stop loss
    """
    return [
        OptionLeg(strike=strike, premium=call_premium, qty=qty, option_type="CE", action="SELL"),
        OptionLeg(strike=strike, premium=put_premium, qty=qty, option_type="PE", action="SELL"),
    ]


def short_strangle(
    call_strike: float,
    put_strike: float,
    call_premium: float,
    put_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Short Strangle: Sell OTM call + sell OTM put.

    Profile  : Wider profit zone than short straddle, smaller credit
    Bias     : Neutral, range-bound expectation
    Best when: IV rank > 70, expecting consolidation
    Risk     : UNLIMITED — typically used with delta-hedging or stop loss
    """
    return [
        OptionLeg(strike=call_strike, premium=call_premium, qty=qty, option_type="CE", action="SELL"),
        OptionLeg(strike=put_strike, premium=put_premium, qty=qty, option_type="PE", action="SELL"),
    ]


def bull_put_spread(
    sell_strike: float,
    buy_strike: float,
    sell_premium: float,
    buy_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Bull Put Spread (credit spread): Sell higher PE + buy lower PE.

    Profile  : Net credit, capped profit (the credit), capped loss
    Bias     : Bullish to neutral
    Best when: You expect spot to stay above sell_strike at expiry
    Max profit: net credit received
    Max loss : (sell_strike - buy_strike) - net_credit
    """
    return [
        OptionLeg(strike=sell_strike, premium=sell_premium, qty=qty, option_type="PE", action="SELL"),
        OptionLeg(strike=buy_strike, premium=buy_premium, qty=qty, option_type="PE", action="BUY"),
    ]


def bear_call_spread(
    sell_strike: float,
    buy_strike: float,
    sell_premium: float,
    buy_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Bear Call Spread (credit spread): Sell lower CE + buy higher CE.

    Profile  : Net credit, capped profit, capped loss
    Bias     : Bearish to neutral
    Best when: You expect spot to stay below sell_strike at expiry
    Max profit: net credit received
    Max loss : (buy_strike - sell_strike) - net_credit
    """
    return [
        OptionLeg(strike=sell_strike, premium=sell_premium, qty=qty, option_type="CE", action="SELL"),
        OptionLeg(strike=buy_strike, premium=buy_premium, qty=qty, option_type="CE", action="BUY"),
    ]


def iron_butterfly(
    atm_strike: float,
    wing_distance: float,
    atm_call_premium: float,
    atm_put_premium: float,
    upper_call_premium: float,
    lower_put_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Iron Butterfly: Sell ATM straddle + buy OTM wings.

    Profile  : Net credit, maximum profit at exact ATM, defined risk
    Bias     : Neutral, very narrow profit zone (vs iron condor)
    Best when: IV rank > 80 AND you expect spot to pin to a specific level
    Difference from iron condor: same middle strike (not split)
    """
    return [
        OptionLeg(strike=atm_strike - wing_distance, premium=lower_put_premium, qty=qty, option_type="PE", action="BUY"),
        OptionLeg(strike=atm_strike, premium=atm_put_premium, qty=qty, option_type="PE", action="SELL"),
        OptionLeg(strike=atm_strike, premium=atm_call_premium, qty=qty, option_type="CE", action="SELL"),
        OptionLeg(strike=atm_strike + wing_distance, premium=upper_call_premium, qty=qty, option_type="CE", action="BUY"),
    ]


def jade_lizard(
    put_sell_strike: float,
    call_sell_strike: float,
    call_buy_strike: float,
    put_sell_premium: float,
    call_sell_premium: float,
    call_buy_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Jade Lizard: Short put + short call spread.

    Profile  : Net credit, NO upside risk if credit > call spread width
    Bias     : Bullish to neutral
    Best when: IV rank > 60, you're OK owning stock at put_sell_strike
    Key rule : Total credit MUST exceed (call_buy - call_sell) for zero upside risk
    Downside : Limited only by put strike (you may be assigned)
    """
    return [
        OptionLeg(strike=put_sell_strike, premium=put_sell_premium, qty=qty, option_type="PE", action="SELL"),
        OptionLeg(strike=call_sell_strike, premium=call_sell_premium, qty=qty, option_type="CE", action="SELL"),
        OptionLeg(strike=call_buy_strike, premium=call_buy_premium, qty=qty, option_type="CE", action="BUY"),
    ]


def call_ratio_spread(
    buy_strike: float,
    sell_strike: float,
    buy_premium: float,
    sell_premium: float,
    qty: int = 1,
    ratio: int = 2,
) -> list[OptionLeg]:
    """
    Call Ratio Spread (1xN): Buy 1 lower call, sell N higher calls.

    Profile  : Small debit/credit, capped upside, UNLIMITED loss above sell strike
    Bias     : Mildly bullish (you want spot to land NEAR sell_strike at expiry)
    Best when: You expect a controlled move up but not a runaway rally
    Sweet spot: spot ends exactly at sell_strike at expiry
    Risk     : Each extra naked short call adds unlimited risk
    """
    return [
        OptionLeg(strike=buy_strike, premium=buy_premium, qty=qty, option_type="CE", action="BUY"),
        OptionLeg(strike=sell_strike, premium=sell_premium, qty=qty * ratio, option_type="CE", action="SELL"),
    ]


def put_ratio_spread(
    buy_strike: float,
    sell_strike: float,
    buy_premium: float,
    sell_premium: float,
    qty: int = 1,
    ratio: int = 2,
) -> list[OptionLeg]:
    """
    Put Ratio Spread (1xN): Buy 1 higher put, sell N lower puts.

    Profile  : Small credit, capped downside, UNLIMITED loss below sell strike
    Bias     : Mildly bearish
    Sweet spot: spot ends exactly at sell_strike at expiry
    """
    return [
        OptionLeg(strike=buy_strike, premium=buy_premium, qty=qty, option_type="PE", action="BUY"),
        OptionLeg(strike=sell_strike, premium=sell_premium, qty=qty * ratio, option_type="PE", action="SELL"),
    ]


def call_backspread(
    sell_strike: float,
    buy_strike: float,
    sell_premium: float,
    buy_premium: float,
    qty: int = 1,
    ratio: int = 2,
) -> list[OptionLeg]:
    """
    Call Backspread (Nx1): Sell 1 lower call, buy N higher calls.

    Profile  : Small credit/debit, UNLIMITED upside, defined risk
    Bias     : Strongly bullish (volatility expansion play)
    Best when: You expect a sharp move up + IV expansion
    Loss zone : between strikes (max loss at buy_strike at expiry)
    """
    return [
        OptionLeg(strike=sell_strike, premium=sell_premium, qty=qty, option_type="CE", action="SELL"),
        OptionLeg(strike=buy_strike, premium=buy_premium, qty=qty * ratio, option_type="CE", action="BUY"),
    ]


def put_backspread(
    sell_strike: float,
    buy_strike: float,
    sell_premium: float,
    buy_premium: float,
    qty: int = 1,
    ratio: int = 2,
) -> list[OptionLeg]:
    """
    Put Backspread (Nx1): Sell 1 higher put, buy N lower puts.

    Profile  : Small credit/debit, large downside profit, defined risk
    Bias     : Strongly bearish
    Best when: Crash hedge or strong bearish conviction
    """
    return [
        OptionLeg(strike=sell_strike, premium=sell_premium, qty=qty, option_type="PE", action="SELL"),
        OptionLeg(strike=buy_strike, premium=buy_premium, qty=qty * ratio, option_type="PE", action="BUY"),
    ]


def synthetic_long(
    strike: float,
    call_premium: float,
    put_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Synthetic Long Stock: Buy call + sell put at same strike.

    Profile  : Identical P&L to owning the underlying (delta = 1.0)
    Use case : Replicate stock exposure with less capital + leverage
    Risk     : Same as long stock (unlimited downside)
    """
    return [
        OptionLeg(strike=strike, premium=call_premium, qty=qty, option_type="CE", action="BUY"),
        OptionLeg(strike=strike, premium=put_premium, qty=qty, option_type="PE", action="SELL"),
    ]


def synthetic_short(
    strike: float,
    call_premium: float,
    put_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Synthetic Short Stock: Sell call + buy put at same strike.

    Profile  : Identical to short selling the underlying (delta = -1.0)
    Use case : Bearish bet without borrowing stock
    Risk     : Unlimited upside risk (just like short stock)
    """
    return [
        OptionLeg(strike=strike, premium=call_premium, qty=qty, option_type="CE", action="SELL"),
        OptionLeg(strike=strike, premium=put_premium, qty=qty, option_type="PE", action="BUY"),
    ]


def collar(
    stock_entry: float,
    put_strike: float,
    call_strike: float,
    put_premium: float,
    call_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Collar: Long stock + protective long put + short call.

    NOTE: This preset only returns the OPTION legs (put + call).
    Add the stock leg manually if you want full P&L vs entry.

    Profile  : Caps both upside and downside (cheap or zero-cost hedge)
    Use case : Protect a long stock position during uncertain periods
    Best when: Worried about a drop but want to stay long for dividends/ownership
    """
    _ = stock_entry  # placeholder — stock leg is implicit, P&L tracked externally
    return [
        OptionLeg(strike=put_strike, premium=put_premium, qty=qty, option_type="PE", action="BUY"),
        OptionLeg(strike=call_strike, premium=call_premium, qty=qty, option_type="CE", action="SELL"),
    ]


def broken_wing_butterfly_call(
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    lower_premium: float,
    middle_premium: float,
    upper_premium: float,
    qty: int = 1,
) -> list[OptionLeg]:
    """
    Broken Wing Butterfly (call): Asymmetric butterfly with wider upper wing.

    Profile  : Often a net credit (vs debit for symmetric butterfly)
    Bias     : Mildly bullish, no risk on the downside if structured right
    Best when: You want the butterfly profit zone but skewed to one side
    Construction: |middle - lower| < |upper - middle|
    """
    return [
        OptionLeg(strike=lower_strike, premium=lower_premium, qty=qty, option_type="CE", action="BUY"),
        OptionLeg(strike=middle_strike, premium=middle_premium, qty=qty * 2, option_type="CE", action="SELL"),
        OptionLeg(strike=upper_strike, premium=upper_premium, qty=qty, option_type="CE", action="BUY"),
    ]
