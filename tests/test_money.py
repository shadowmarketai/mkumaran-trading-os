"""Tests for mcp_server.money — the Decimal-zone entry points."""
from __future__ import annotations

from decimal import Decimal

import pytest

from mcp_server.money import (
    DEFAULT_QUANTUM,
    EXCHANGE_QUANTUM,
    PAISA_FRAC,
    PAISE,
    pct_return,
    pnl,
    quantum_for,
    round_paise,
    round_tick,
    to_money,
)


# ── to_money ────────────────────────────────────────────────────────

class TestToMoney:
    def test_string_roundtrip(self):
        assert to_money("123.45") == Decimal("123.45")

    def test_int_is_exact(self):
        assert to_money(100) == Decimal("100")

    def test_float_goes_via_str_no_binary_artefact(self):
        # Decimal(0.1) == Decimal('0.1000000000000000055511151231257827021181583404541015625')
        # Decimal(str(0.1)) == Decimal('0.1')
        # This is the whole point of the helper.
        assert to_money(0.1) == Decimal("0.1")
        assert to_money(0.1) != Decimal(0.1)

    def test_float_addition_is_clean(self):
        # Classic 0.1 + 0.2 == 0.30000000000000004 problem must not leak.
        result = to_money(0.1) + to_money(0.2)
        assert result == Decimal("0.3")

    def test_decimal_passthrough(self):
        d = Decimal("42.00")
        # Same identity — we don't copy unnecessarily.
        assert to_money(d) is d

    def test_rejects_none(self):
        with pytest.raises((TypeError, ValueError)):
            to_money(None)  # type: ignore[arg-type]


# ── round_paise ─────────────────────────────────────────────────────

class TestRoundPaise:
    def test_rounds_to_two_dp(self):
        assert round_paise(Decimal("1.234")) == Decimal("1.23")
        assert round_paise(Decimal("1.235")) == Decimal("1.24")
        assert round_paise(Decimal("1.2399999")) == Decimal("1.24")

    def test_half_up_not_banker(self):
        # Banker's rounding would round 0.005 → 0.00 (to even).
        # We want 0.01. Same for 0.015 → 0.02.
        assert round_paise(Decimal("0.005")) == Decimal("0.01")
        assert round_paise(Decimal("0.015")) == Decimal("0.02")
        assert round_paise(Decimal("0.025")) == Decimal("0.03")

    def test_negative_half_up(self):
        # ROUND_HALF_UP rounds away from zero for half-values.
        assert round_paise(Decimal("-0.005")) == Decimal("-0.01")

    def test_already_2dp_unchanged(self):
        assert round_paise(Decimal("1234.56")) == Decimal("1234.56")

    def test_paise_constant(self):
        assert PAISE == Decimal("0.01")


# ── quantum_for / round_tick ────────────────────────────────────────

class TestQuantumFor:
    def test_nse_2dp(self):
        assert quantum_for("NSE") == PAISE

    def test_bse_2dp(self):
        assert quantum_for("BSE") == PAISE

    def test_nfo_2dp(self):
        assert quantum_for("NFO") == PAISE

    def test_mcx_2dp(self):
        # Commodity tick varies per contract but money math is 2dp.
        assert quantum_for("MCX") == PAISE

    def test_cds_4dp(self):
        # USDINR/EURINR quote to 4dp.
        assert quantum_for("CDS") == PAISA_FRAC

    def test_accepts_prefixed_ticker(self):
        # "NSE:RELIANCE" works the same as bare "NSE".
        assert quantum_for("NSE:RELIANCE") == PAISE
        assert quantum_for("CDS:USDINR") == PAISA_FRAC

    def test_lowercase_normalised(self):
        assert quantum_for("nse") == PAISE

    def test_unknown_exchange_falls_back_to_default(self):
        # Over-preserve precision rather than silently truncate.
        assert quantum_for("MYSTERY") == DEFAULT_QUANTUM

    def test_none_and_empty(self):
        assert quantum_for(None) == DEFAULT_QUANTUM
        assert quantum_for("") == DEFAULT_QUANTUM

    def test_exchange_map_has_expected_codes(self):
        assert set(EXCHANGE_QUANTUM.keys()) == {"NSE", "BSE", "NFO", "MCX", "CDS"}


class TestRoundTick:
    def test_nse_rounds_to_2dp(self):
        assert round_tick(Decimal("1.234"), "NSE") == Decimal("1.23")
        assert round_tick(Decimal("1.235"), "NSE") == Decimal("1.24")

    def test_cds_rounds_to_4dp(self):
        # USDINR 83.12345 → 83.1235 (half-up, not banker's)
        assert round_tick(Decimal("83.12345"), "CDS") == Decimal("83.1235")
        assert round_tick(Decimal("83.12344"), "CDS") == Decimal("83.1234")

    def test_mcx_2dp(self):
        # Gold contract value rounds to paise even though tick is 1.00.
        assert round_tick(Decimal("72345.678"), "MCX") == Decimal("72345.68")

    def test_half_up_negatives(self):
        assert round_tick(Decimal("-0.005"), "NSE") == Decimal("-0.01")
        assert round_tick(Decimal("-0.00005"), "CDS") == Decimal("-0.0001")


# ── pnl ─────────────────────────────────────────────────────────────

class TestPnL:
    def test_long_winner(self):
        # Buy 100 @ 1000, sell @ 1050 → +5000
        assert pnl(1000, 1050, 100, "NSE") == Decimal("5000.00")

    def test_long_loser(self):
        assert pnl(1000, 950, 100, "NSE") == Decimal("-5000.00")

    def test_accepts_float_inputs(self):
        # Boundary helper: caller can forward broker-API floats without
        # wrapping each one.
        assert pnl(100.50, 101.25, 200, "NSE") == Decimal("150.00")

    def test_accepts_string_inputs(self):
        assert pnl("100.50", "101.25", 200, "NSE") == Decimal("150.00")

    def test_mixes_types_safely(self):
        assert pnl(Decimal("100.50"), 101.25, 200, "NSE") == Decimal("150.00")

    def test_result_is_exactly_2dp_on_nse(self):
        # Tricky case: 0.1 * 3 in float = 0.30000000000000004.
        # 0.1 * 3 quantity should be exactly 0.30.
        result = pnl(0, 0.1, 3, "NSE")
        assert result == Decimal("0.30")
        # And exactly 2dp precision in the representation.
        assert result.as_tuple().exponent == -2

    def test_zero_qty_is_zero(self):
        assert pnl(1000, 1050, 0, "NSE") == Decimal("0.00")

    def test_cds_pnl_preserves_4dp(self):
        # 10,000 USDINR lots at entry 83.1234 → exit 83.5678 = +4440.0000 INR
        # (premium per unit is 4dp, lot multiplier handled upstream).
        result = pnl("83.1234", "83.5678", 10_000, "CDS")
        assert result == Decimal("4444.0000")
        # Exactly 4dp — no silent truncation.
        assert result.as_tuple().exponent == -4

    def test_defaults_to_finest_precision_when_exchange_missing(self):
        # Without an exchange, falls through to DEFAULT_QUANTUM = 4dp.
        # 0.1 + 0.2 × 10 should land exactly on 3.0000, not 3.00.
        result = pnl(0, Decimal("0.3"), 10)
        assert result == Decimal("3.0000")


# ── pct_return ──────────────────────────────────────────────────────

class TestPctReturn:
    def test_long_winner_percent(self):
        # 1000 → 1050 == +5.00%
        assert pct_return(1000, 1050) == Decimal("5.00")

    def test_long_loser_percent(self):
        assert pct_return(1000, 950) == Decimal("-5.00")

    def test_zero_entry_returns_zero_not_error(self):
        # Avoid ZeroDivisionError at the boundary — calling code may
        # pass 0 for a freshly-opened position that hasn't moved.
        assert pct_return(0, 100) == Decimal("0.00")

    def test_rounds_to_2dp(self):
        # 1/3 → 33.333... → 33.33
        assert pct_return(300, 400) == Decimal("33.33")

    def test_accepts_mixed_numerics(self):
        assert pct_return("100", 105.0) == Decimal("5.00")
