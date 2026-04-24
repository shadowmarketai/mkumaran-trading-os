"""Money helpers — the Decimal zone entry points.

Phase 1 of docs/DECIMAL_ENFORCEMENT_PLAN.md. Adds the module only; no
callers are migrated in this commit. Follow-up PRs migrate rrms_engine,
signal_cards, signal_monitor, portfolio_risk to use these helpers.

CLAUDE.md invariant #2: "All P&L, stop-loss, target computations use
Decimal, not float".

Per-exchange precision (operator decision, 2026-04-22):
  NSE / BSE / NFO / MCX → 2dp  (paise)
  CDS (currency pairs)  → 4dp  (USDINR quotes to 83.1234 level)

Usage pattern:

    from mcp_server.money import to_money, round_tick, pnl

    entry = to_money(ltp_from_broker)        # str/float/int/Decimal → Decimal
    sl = to_money("1234.56")
    risk_per_share = entry - sl              # Decimal - Decimal
    qty = 100
    realised_pnl = pnl(entry, exit_price, qty, exchange="NSE")
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

Numeric = Union[int, float, str, Decimal]

# ── Per-exchange rounding quanta ──────────────────────────────────
# Keyed by the prefix used in watchlist tickers (NSE:RELIANCE → "NSE").
PAISE = Decimal("0.01")      # equity / F&O / commodity: 2dp money math
PAISA_FRAC = Decimal("0.0001")  # currency: 4dp (USDINR = 83.1234)

EXCHANGE_QUANTUM: dict[str, Decimal] = {
    "NSE": PAISE,
    "BSE": PAISE,
    "NFO": PAISE,       # index + equity F&O premiums round to paise
    "MCX": PAISE,       # commodity contracts: tick varies per contract
                         # (Gold 1.00, NatGas 0.10, Copper 0.05) but
                         # money math aggregates at 2dp regardless
    "CDS": PAISA_FRAC,  # currency pairs: 4dp
}

# Default when exchange is unknown or missing — safer to over-preserve
# precision than to silently truncate.
DEFAULT_QUANTUM = PAISA_FRAC


def to_money(x: Numeric) -> Decimal:
    """Coerce anything numeric to Decimal without binary-float artefacts.

    Key trick: float → str → Decimal, NOT float → Decimal directly.
    Going directly through Decimal(float_value) preserves the IEEE-754
    binary representation, so e.g. Decimal(0.1) == Decimal("0.1000...55")
    (18 digits of noise). Decimal(str(0.1)) == Decimal("0.1") exactly.
    """
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    # int and str both construct cleanly via Decimal.__init__.
    return Decimal(x)


def quantum_for(exchange: str | None) -> Decimal:
    """Resolve the rounding quantum for an exchange code.

    Accepts either a bare code ("NSE") or a prefixed ticker ("NSE:RELIANCE").
    Unknown / None → DEFAULT_QUANTUM (the finest-grain we know of).
    """
    if not exchange:
        return DEFAULT_QUANTUM
    # Strip ticker suffix if caller passed a full symbol.
    code = exchange.split(":", 1)[0].upper().strip()
    return EXCHANGE_QUANTUM.get(code, DEFAULT_QUANTUM)


def round_tick(x: Decimal, exchange: str | None = None) -> Decimal:
    """Quantize `x` to the precision of `exchange` (half-up rounding).

    Banker's-round would bias totals on even/odd boundary cases;
    half-up matches broker confirmation statements.
    """
    return x.quantize(quantum_for(exchange), rounding=ROUND_HALF_UP)


def round_paise(x: Decimal) -> Decimal:
    """Round to 2dp — shorthand for exchanges that use paise precision.

    Equivalent to `round_tick(x, "NSE")`. Kept as a convenience for
    call sites that are unambiguously equity/F&O/commodity.
    """
    return x.quantize(PAISE, rounding=ROUND_HALF_UP)


def pnl(
    entry: Numeric,
    exit_price: Numeric,
    qty: int,
    exchange: str | None = None,
) -> Decimal:
    """Realised P&L for `qty` shares/lots/contracts: (exit - entry) * qty.

    Rounded to the tick of `exchange`. When `exchange` is None, falls
    back to 4dp (finest-grain we know of) so no precision is lost by
    accident.

    Accepts any Numeric for entry/exit so callers at the broker boundary
    can pass floats without a separate wrapping step.
    """
    raw = (to_money(exit_price) - to_money(entry)) * Decimal(qty)
    return round_tick(raw, exchange)


def pct_return(
    entry: Numeric,
    exit_price: Numeric,
    exchange: str | None = None,
) -> Decimal:
    """Percentage return, rounded to 2dp. Positive for long winners.

    Percent is dimensionless — we always round to 2dp regardless of
    `exchange`, but `exchange` is kept in the signature for call-site
    symmetry with `pnl()`.
    """
    del exchange  # intentionally unused — % is always 2dp
    e = to_money(entry)
    x = to_money(exit_price)
    if e == 0:
        return Decimal("0.00")
    return round_paise((x - e) / e * Decimal(100))
