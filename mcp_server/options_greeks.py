"""
MKUMARAN Trading OS — Options Greeks Calculator (Black-Scholes)

Pure-Python Black-Scholes pricing, Greeks computation, and IV solver.
No scipy dependency — uses Abramowitz & Stegun CDF approximation.

Supports: Delta, Gamma, Theta, Vega, Rho + Implied Volatility via
Newton-Raphson with bisection fallback.
"""

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default risk-free rate (RBI repo rate ~6.5%)
DEFAULT_RISK_FREE_RATE = 0.065

# ── Normal CDF (Abramowitz & Stegun approximation) ─────────────


def _norm_cdf(x: float) -> float:
    """
    Cumulative standard normal distribution.
    Abramowitz & Stegun approximation (max error ~7.5e-8).
    """
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911

    sign = 1 if x >= 0 else -1
    x = abs(x) / math.sqrt(2.0)

    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)

    return 0.5 * (1.0 + sign * y)


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# ── Black-Scholes Pricing ───────────────────────────────────────


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate d1 for Black-Scholes formula."""
    if T <= 0 or sigma <= 0:
        return 0.0
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate d2 for Black-Scholes formula."""
    if T <= 0 or sigma <= 0:
        return 0.0
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "CE",
) -> float:
    """
    Black-Scholes European option price.

    Args:
        S: Spot/underlying price
        K: Strike price
        T: Time to expiry in years (e.g., 30/365 = 0.082)
        r: Risk-free rate (annualized, e.g., 0.065)
        sigma: Volatility (annualized, e.g., 0.20 for 20%)
        option_type: "CE" (call) or "PE" (put)

    Returns:
        Option price
    """
    if T <= 0:
        # At expiry
        if option_type.upper() == "CE":
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    if sigma <= 0:
        # Zero vol = intrinsic value discounted
        if option_type.upper() == "CE":
            return max(S - K * math.exp(-r * T), 0.0)
        return max(K * math.exp(-r * T) - S, 0.0)

    d1_val = _d1(S, K, T, r, sigma)
    d2_val = _d2(S, K, T, r, sigma)

    if option_type.upper() == "CE":
        return S * _norm_cdf(d1_val) - K * math.exp(-r * T) * _norm_cdf(d2_val)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2_val) - S * _norm_cdf(-d1_val)


# ── Greeks Calculator ───────────────────────────────────────────


@dataclass
class GreeksResult:
    """Container for option Greeks."""
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    iv: float = 0.0  # Populated when IV is computed


def calculate_greeks(
    spot: float,
    strike: float,
    expiry_days: float,
    rate: float = DEFAULT_RISK_FREE_RATE,
    volatility: float = 0.20,
    option_type: str = "CE",
) -> GreeksResult:
    """
    Calculate all option Greeks for a single option.

    Args:
        spot: Current underlying price
        strike: Option strike price
        expiry_days: Days to expiry
        rate: Risk-free rate (default 6.5%)
        volatility: Annualized volatility (e.g., 0.20 for 20%)
        option_type: "CE" (call) or "PE" (put)

    Returns:
        GreeksResult with price, delta, gamma, theta, vega, rho
    """
    T = expiry_days / 365.0
    is_call = option_type.upper() == "CE"

    price = bs_price(spot, strike, T, rate, volatility, option_type)

    if T <= 0 or volatility <= 0:
        # At expiry or zero vol — no time value
        intrinsic = max(spot - strike, 0) if is_call else max(strike - spot, 0)
        delta = 1.0 if (is_call and spot > strike) else (-1.0 if (not is_call and spot < strike) else 0.0)
        return GreeksResult(
            price=intrinsic, delta=delta,
            gamma=0.0, theta=0.0, vega=0.0, rho=0.0,
        )

    d1_val = _d1(spot, strike, T, rate, volatility)
    d2_val = _d2(spot, strike, T, rate, volatility)
    sqrt_T = math.sqrt(T)
    pdf_d1 = _norm_pdf(d1_val)

    # Delta
    if is_call:
        delta = _norm_cdf(d1_val)
    else:
        delta = _norm_cdf(d1_val) - 1.0

    # Gamma (same for call and put)
    gamma = pdf_d1 / (spot * volatility * sqrt_T)

    # Theta (per day)
    theta_common = -(spot * pdf_d1 * volatility) / (2.0 * sqrt_T)
    if is_call:
        theta = theta_common - rate * strike * math.exp(-rate * T) * _norm_cdf(d2_val)
    else:
        theta = theta_common + rate * strike * math.exp(-rate * T) * _norm_cdf(-d2_val)
    theta = theta / 365.0  # Per calendar day

    # Vega (per 1% move in vol)
    vega = spot * pdf_d1 * sqrt_T / 100.0

    # Rho (per 1% move in rate)
    if is_call:
        rho = strike * T * math.exp(-rate * T) * _norm_cdf(d2_val) / 100.0
    else:
        rho = -strike * T * math.exp(-rate * T) * _norm_cdf(-d2_val) / 100.0

    return GreeksResult(
        price=round(price, 2),
        delta=round(delta, 4),
        gamma=round(gamma, 6),
        theta=round(theta, 2),
        vega=round(vega, 2),
        rho=round(rho, 2),
    )


# ── Implied Volatility Solver ───────────────────────────────────


def calculate_iv(
    market_price: float,
    spot: float,
    strike: float,
    expiry_days: float,
    rate: float = DEFAULT_RISK_FREE_RATE,
    option_type: str = "CE",
    max_iterations: int = 100,
    precision: float = 1e-6,
) -> float:
    """
    Calculate implied volatility using Newton-Raphson with bisection fallback.

    Args:
        market_price: Observed market price of the option
        spot: Underlying price
        strike: Strike price
        expiry_days: Days to expiry
        rate: Risk-free rate
        option_type: "CE" or "PE"
        max_iterations: Max iterations for solver
        precision: Convergence threshold

    Returns:
        Implied volatility (annualized, e.g., 0.25 = 25%)
    """
    T = expiry_days / 365.0

    if T <= 0 or market_price <= 0:
        return 0.0

    # Check intrinsic value bounds
    is_call = option_type.upper() == "CE"
    if is_call:
        intrinsic = max(spot - strike * math.exp(-rate * T), 0)
    else:
        intrinsic = max(strike * math.exp(-rate * T) - spot, 0)

    if market_price < intrinsic - precision:
        return 0.0  # Below intrinsic — no valid IV

    # Newton-Raphson starting guess
    sigma = 0.30  # Start at 30%

    for _ in range(max_iterations):
        price = bs_price(spot, strike, T, rate, sigma, option_type)
        diff = price - market_price

        if abs(diff) < precision:
            return round(sigma, 6)

        # Vega for Newton step
        d1_val = _d1(spot, strike, T, rate, sigma)
        vega = spot * _norm_pdf(d1_val) * math.sqrt(T)

        if vega < 1e-10:
            break  # Vega too small, switch to bisection

        sigma -= diff / vega

        if sigma <= 0.001:
            sigma = 0.001
        if sigma > 5.0:
            sigma = 5.0

    # Bisection fallback
    low, high = 0.001, 5.0
    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        price = bs_price(spot, strike, T, rate, mid, option_type)
        diff = price - market_price

        if abs(diff) < precision:
            return round(mid, 6)

        if diff > 0:
            high = mid
        else:
            low = mid

    return round((low + high) / 2.0, 6)


# ── Option Chain Builder ────────────────────────────────────────


def build_greeks_chain(
    spot: float,
    strikes: list[float],
    expiry_days: float,
    rate: float = DEFAULT_RISK_FREE_RATE,
    market_prices_ce: dict[float, float] | None = None,
    market_prices_pe: dict[float, float] | None = None,
) -> list[dict]:
    """
    Build a full option chain with Greeks for each strike.

    Args:
        spot: Underlying spot price
        strikes: List of strike prices
        expiry_days: Days to expiry
        rate: Risk-free rate
        market_prices_ce: Dict of {strike: market_price} for calls (for IV)
        market_prices_pe: Dict of {strike: market_price} for puts (for IV)

    Returns:
        List of dicts, one per strike, with CE and PE Greeks
    """
    if market_prices_ce is None:
        market_prices_ce = {}
    if market_prices_pe is None:
        market_prices_pe = {}

    chain: list[dict] = []

    for strike in sorted(strikes):
        # Estimate vol from IV if market price available, else use 20%
        ce_iv = 0.0
        pe_iv = 0.0
        ce_vol = 0.20
        pe_vol = 0.20

        if strike in market_prices_ce and market_prices_ce[strike] > 0:
            ce_iv = calculate_iv(market_prices_ce[strike], spot, strike, expiry_days, rate, "CE")
            if ce_iv > 0:
                ce_vol = ce_iv

        if strike in market_prices_pe and market_prices_pe[strike] > 0:
            pe_iv = calculate_iv(market_prices_pe[strike], spot, strike, expiry_days, rate, "PE")
            if pe_iv > 0:
                pe_vol = pe_iv

        ce_greeks = calculate_greeks(spot, strike, expiry_days, rate, ce_vol, "CE")
        pe_greeks = calculate_greeks(spot, strike, expiry_days, rate, pe_vol, "PE")
        ce_greeks.iv = round(ce_iv * 100, 2)  # As percentage
        pe_greeks.iv = round(pe_iv * 100, 2)

        is_atm = abs(strike - spot) <= (strikes[1] - strikes[0]) / 2 if len(strikes) > 1 else abs(strike - spot) < 50

        chain.append({
            "strike": strike,
            "is_atm": is_atm,
            "ce": {
                "price": ce_greeks.price,
                "delta": ce_greeks.delta,
                "gamma": ce_greeks.gamma,
                "theta": ce_greeks.theta,
                "vega": ce_greeks.vega,
                "rho": ce_greeks.rho,
                "iv": ce_greeks.iv,
                "market_price": market_prices_ce.get(strike, 0),
            },
            "pe": {
                "price": pe_greeks.price,
                "delta": pe_greeks.delta,
                "gamma": pe_greeks.gamma,
                "theta": pe_greeks.theta,
                "vega": pe_greeks.vega,
                "rho": pe_greeks.rho,
                "iv": pe_greeks.iv,
                "market_price": market_prices_pe.get(strike, 0),
            },
        })

    return chain
