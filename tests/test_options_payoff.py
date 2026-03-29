"""
Tests for Options Payoff Calculator (Feature 4)

Validates:
- Single leg: buy/sell call/put ITM/OTM P&L
- Multi-leg: bull call spread max profit/loss/breakeven, iron condor, straddle, butterfly
- Payoff calculation: auto range, breakeven detection, net premium
- Presets: each returns correct number of legs
"""

import pytest

from mcp_server.options_payoff import (
    OptionLeg,
    _single_leg_payoff,
    calculate_payoff,
    bull_call_spread,
    bear_put_spread,
    long_straddle,
    long_strangle,
    iron_condor,
    butterfly_spread,
)


# ── Single Leg P&L ──────────────────────────────────────────────


def test_buy_call_itm():
    """Buy call ITM: profit = intrinsic - premium."""
    leg = OptionLeg(strike=100, premium=10, qty=1, option_type="CE", action="BUY")
    pnl = _single_leg_payoff(leg, spot=120)
    assert pnl == (120 - 100 - 10) * 1  # +10


def test_buy_call_otm():
    """Buy call OTM: loss = premium paid."""
    leg = OptionLeg(strike=100, premium=10, qty=1, option_type="CE", action="BUY")
    pnl = _single_leg_payoff(leg, spot=80)
    assert pnl == -10


def test_sell_call_otm():
    """Sell call OTM: profit = premium received."""
    leg = OptionLeg(strike=100, premium=10, qty=1, option_type="CE", action="SELL")
    pnl = _single_leg_payoff(leg, spot=80)
    assert pnl == 10


def test_sell_call_itm():
    """Sell call ITM: loss = intrinsic - premium."""
    leg = OptionLeg(strike=100, premium=10, qty=1, option_type="CE", action="SELL")
    pnl = _single_leg_payoff(leg, spot=120)
    assert pnl == (10 - 20) * 1  # -10


def test_buy_put_itm():
    """Buy put ITM: profit = intrinsic - premium."""
    leg = OptionLeg(strike=100, premium=10, qty=1, option_type="PE", action="BUY")
    pnl = _single_leg_payoff(leg, spot=80)
    assert pnl == (100 - 80 - 10) * 1  # +10


def test_buy_put_otm():
    """Buy put OTM: loss = premium paid."""
    leg = OptionLeg(strike=100, premium=10, qty=1, option_type="PE", action="BUY")
    pnl = _single_leg_payoff(leg, spot=120)
    assert pnl == -10


def test_qty_multiplier():
    """P&L should be multiplied by quantity."""
    leg = OptionLeg(strike=100, premium=10, qty=5, option_type="CE", action="BUY")
    pnl = _single_leg_payoff(leg, spot=120)
    assert pnl == (120 - 100 - 10) * 5  # +50


# ── Bull Call Spread ────────────────────────────────────────────


def test_bull_call_spread_max_profit():
    """Bull call spread max profit = upper - lower - net debit."""
    legs = bull_call_spread(100, 110, lower_premium=8, upper_premium=3)
    result = calculate_payoff(legs)
    # Max profit at spot >= 110: (110-100) - (8-3) = 5
    assert abs(result.max_profit - 5.0) < 0.5


def test_bull_call_spread_max_loss():
    """Bull call spread max loss = net debit."""
    legs = bull_call_spread(100, 110, lower_premium=8, upper_premium=3)
    result = calculate_payoff(legs)
    # Max loss = 8 - 3 = 5 (net debit)
    assert abs(result.max_loss - (-5.0)) < 0.5


def test_bull_call_spread_has_breakeven():
    """Bull call spread should have one breakeven."""
    legs = bull_call_spread(100, 110, lower_premium=8, upper_premium=3)
    result = calculate_payoff(legs)
    assert len(result.breakevens) == 1
    # Breakeven = lower_strike + net_debit = 100 + 5 = 105
    assert abs(result.breakevens[0] - 105) < 1


# ── Iron Condor ─────────────────────────────────────────────────


def test_iron_condor_legs():
    """Iron condor preset should return 4 legs."""
    legs = iron_condor(90, 95, 105, 110, 1, 3, 3, 1)
    assert len(legs) == 4


def test_iron_condor_max_profit():
    """Iron condor max profit = net credit."""
    legs = iron_condor(90, 95, 105, 110, 1, 3, 3, 1)
    result = calculate_payoff(legs)
    # Net credit = (3+3) - (1+1) = 4
    assert abs(result.max_profit - 4.0) < 0.5


def test_iron_condor_two_breakevens():
    """Iron condor should have 2 breakevens."""
    legs = iron_condor(90, 95, 105, 110, 1, 3, 3, 1)
    # Use wider spot range to ensure breakevens are captured
    result = calculate_payoff(legs, spot_min=70, spot_max=130)
    assert len(result.breakevens) == 2


# ── Straddle ────────────────────────────────────────────────────


def test_straddle_legs():
    """Long straddle should return 2 legs."""
    legs = long_straddle(100, call_premium=5, put_premium=4)
    assert len(legs) == 2


def test_straddle_max_loss_at_strike():
    """Straddle max loss at strike = total premium paid."""
    legs = long_straddle(100, call_premium=5, put_premium=4)
    # P&L at spot=100: -5 + -4 = -9
    total_pnl = sum(_single_leg_payoff(leg, 100) for leg in legs)
    assert total_pnl == -9


def test_straddle_two_breakevens():
    """Long straddle should have 2 breakevens."""
    legs = long_straddle(100, call_premium=5, put_premium=4)
    result = calculate_payoff(legs)
    assert len(result.breakevens) == 2


# ── Strangle ────────────────────────────────────────────────────


def test_strangle_legs():
    """Long strangle should return 2 legs."""
    legs = long_strangle(110, 90, call_premium=3, put_premium=3)
    assert len(legs) == 2


# ── Butterfly ───────────────────────────────────────────────────


def test_butterfly_legs():
    """Butterfly spread should return 3 legs (with middle qty=2)."""
    legs = butterfly_spread(90, 100, 110, lower_premium=12, middle_premium=6, upper_premium=2)
    assert len(legs) == 3
    # Middle leg has qty * 2
    assert legs[1].qty == 2


# ── Payoff Calculation ──────────────────────────────────────────


def test_payoff_auto_range():
    """calculate_payoff should auto-determine spot range from strikes."""
    legs = [OptionLeg(strike=100, premium=5, qty=1, option_type="CE", action="BUY")]
    result = calculate_payoff(legs)
    assert len(result.points) == 200
    assert result.points[0].spot < 100
    assert result.points[-1].spot > 100


def test_payoff_empty_legs():
    """Empty legs should return empty result."""
    result = calculate_payoff([])
    assert len(result.points) == 0
    assert result.max_profit == 0
    assert result.max_loss == 0


def test_payoff_net_premium_buy():
    """Net premium for a buy should be negative (debit)."""
    legs = [OptionLeg(strike=100, premium=10, qty=1, option_type="CE", action="BUY")]
    result = calculate_payoff(legs)
    assert result.net_premium == -10


def test_payoff_net_premium_sell():
    """Net premium for a sell should be positive (credit)."""
    legs = [OptionLeg(strike=100, premium=10, qty=1, option_type="CE", action="SELL")]
    result = calculate_payoff(legs)
    assert result.net_premium == 10
