"""
Tests for Options Greeks Calculator (Feature 2)

Validates:
- Black-Scholes: call/put price, put-call parity, deep ITM/OTM, zero expiry
- Greeks: delta bounds, ATM delta ~0.5, gamma positive, theta negative, vega positive
- IV: recovery (price -> IV -> recover vol), convergence, edge cases
- Chain: all strikes returned, IV computed when market prices provided
"""

import math

from mcp_server.options_greeks import (
    _norm_cdf,
    _norm_pdf,
    bs_price,
    calculate_greeks,
    calculate_iv,
    build_greeks_chain,
)


# ── Normal CDF/PDF ──────────────────────────────────────────────


def test_norm_cdf_zero():
    """N(0) should be 0.5."""
    assert abs(_norm_cdf(0) - 0.5) < 1e-6


def test_norm_cdf_extremes():
    """N(large) ≈ 1, N(-large) ≈ 0."""
    assert _norm_cdf(5.0) > 0.999999
    assert _norm_cdf(-5.0) < 0.000001


def test_norm_pdf_zero():
    """PDF at 0 should be 1/sqrt(2*pi)."""
    expected = 1.0 / math.sqrt(2 * math.pi)
    assert abs(_norm_pdf(0) - expected) < 1e-6


# ── Black-Scholes Pricing ───────────────────────────────────────


def test_bs_call_positive():
    """Call price should be positive for ATM option."""
    price = bs_price(100, 100, 30 / 365, 0.065, 0.20, "CE")
    assert price > 0


def test_bs_put_positive():
    """Put price should be positive for ATM option."""
    price = bs_price(100, 100, 30 / 365, 0.065, 0.20, "PE")
    assert price > 0


def test_bs_put_call_parity():
    """Put-call parity: C - P = S - K*exp(-rT)."""
    S, K, T, r, sigma = 100, 100, 30 / 365, 0.065, 0.20
    call = bs_price(S, K, T, r, sigma, "CE")
    put = bs_price(S, K, T, r, sigma, "PE")
    parity = S - K * math.exp(-r * T)
    assert abs((call - put) - parity) < 0.01


def test_bs_deep_itm_call():
    """Deep ITM call should be close to S - K*exp(-rT)."""
    S, K, T, r = 200, 100, 30 / 365, 0.065
    price = bs_price(S, K, T, r, 0.20, "CE")
    intrinsic = S - K * math.exp(-r * T)
    assert price > intrinsic - 1.0


def test_bs_deep_otm_call():
    """Deep OTM call should be close to zero."""
    price = bs_price(50, 200, 30 / 365, 0.065, 0.20, "CE")
    assert price < 0.01


def test_bs_zero_expiry_call():
    """At expiry, call = max(S-K, 0)."""
    assert bs_price(110, 100, 0, 0.065, 0.20, "CE") == 10.0
    assert bs_price(90, 100, 0, 0.065, 0.20, "CE") == 0.0


def test_bs_zero_expiry_put():
    """At expiry, put = max(K-S, 0)."""
    assert bs_price(90, 100, 0, 0.065, 0.20, "PE") == 10.0
    assert bs_price(110, 100, 0, 0.065, 0.20, "PE") == 0.0


# ── Greeks ───────────────────────────────────────────────────────


def test_call_delta_bounds():
    """Call delta should be between 0 and 1."""
    greeks = calculate_greeks(100, 100, 30, 0.065, 0.20, "CE")
    assert 0 <= greeks.delta <= 1


def test_put_delta_bounds():
    """Put delta should be between -1 and 0."""
    greeks = calculate_greeks(100, 100, 30, 0.065, 0.20, "PE")
    assert -1 <= greeks.delta <= 0


def test_atm_call_delta_near_half():
    """ATM call delta should be close to 0.5."""
    greeks = calculate_greeks(100, 100, 30, 0.065, 0.20, "CE")
    assert abs(greeks.delta - 0.5) < 0.1


def test_atm_put_delta_near_minus_half():
    """ATM put delta should be close to -0.5."""
    greeks = calculate_greeks(100, 100, 30, 0.065, 0.20, "PE")
    assert abs(greeks.delta + 0.5) < 0.1


def test_gamma_positive():
    """Gamma should be positive for both calls and puts."""
    ce = calculate_greeks(100, 100, 30, 0.065, 0.20, "CE")
    pe = calculate_greeks(100, 100, 30, 0.065, 0.20, "PE")
    assert ce.gamma > 0
    assert pe.gamma > 0


def test_gamma_same_for_call_put():
    """Gamma should be the same for call and put at same strike."""
    ce = calculate_greeks(100, 100, 30, 0.065, 0.20, "CE")
    pe = calculate_greeks(100, 100, 30, 0.065, 0.20, "PE")
    assert abs(ce.gamma - pe.gamma) < 1e-6


def test_theta_negative():
    """Theta should be negative (time decay)."""
    ce = calculate_greeks(100, 100, 30, 0.065, 0.20, "CE")
    assert ce.theta < 0


def test_vega_positive():
    """Vega should be positive for long options."""
    ce = calculate_greeks(100, 100, 30, 0.065, 0.20, "CE")
    assert ce.vega > 0


def test_greeks_at_expiry():
    """At expiry, greeks should be minimal except delta."""
    ce = calculate_greeks(110, 100, 0, 0.065, 0.20, "CE")
    assert ce.delta == 1.0
    assert ce.gamma == 0.0
    assert ce.theta == 0.0


# ── Implied Volatility ──────────────────────────────────────────


def test_iv_recovery():
    """Price -> IV -> should recover the original volatility."""
    original_vol = 0.25
    price = bs_price(100, 100, 30 / 365, 0.065, original_vol, "CE")
    recovered_iv = calculate_iv(price, 100, 100, 30, 0.065, "CE")
    assert abs(recovered_iv - original_vol) < 0.001


def test_iv_recovery_put():
    """IV recovery should also work for puts."""
    original_vol = 0.30
    price = bs_price(100, 100, 60 / 365, 0.065, original_vol, "PE")
    recovered_iv = calculate_iv(price, 100, 100, 60, 0.065, "PE")
    assert abs(recovered_iv - original_vol) < 0.001


def test_iv_zero_price():
    """IV for zero price should be 0."""
    iv = calculate_iv(0, 100, 100, 30, 0.065, "CE")
    assert iv == 0.0


def test_iv_zero_expiry():
    """IV with zero expiry should be 0."""
    iv = calculate_iv(5, 100, 100, 0, 0.065, "CE")
    assert iv == 0.0


# ── Chain Builder ────────────────────────────────────────────────


def test_chain_returns_all_strikes():
    """Chain should return one entry per strike."""
    strikes = [22000, 22500, 23000, 23500, 24000]
    chain = build_greeks_chain(23000, strikes, 30)
    assert len(chain) == 5


def test_chain_sorted_by_strike():
    """Chain should be sorted by strike price."""
    strikes = [24000, 22000, 23000, 23500, 22500]
    chain = build_greeks_chain(23000, strikes, 30)
    for i in range(1, len(chain)):
        assert chain[i]["strike"] > chain[i - 1]["strike"]


def test_chain_has_ce_and_pe():
    """Each chain entry should have CE and PE sections."""
    chain = build_greeks_chain(23000, [23000], 30)
    entry = chain[0]
    assert "ce" in entry
    assert "pe" in entry
    assert "delta" in entry["ce"]
    assert "delta" in entry["pe"]


def test_chain_atm_flag():
    """ATM strike should be flagged."""
    strikes = [22500, 23000, 23500]
    chain = build_greeks_chain(23000, strikes, 30)
    atm_entries = [e for e in chain if e["is_atm"]]
    assert len(atm_entries) >= 1
    assert atm_entries[0]["strike"] == 23000
