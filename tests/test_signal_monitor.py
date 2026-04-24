"""Tests for Signal Auto-Monitor — SL/TGT hit detection and P&L calculation."""

from decimal import Decimal

from mcp_server.signal_monitor import _check_signal_hit, _calc_pnl


# ── SL/TGT hit detection ────────────────────────────────────


class TestCheckSignalHit:
    def test_long_target_hit(self):
        result = _check_signal_hit("BUY", 110.0, 100.0, 95.0, 110.0)
        assert result == "TARGET_HIT"

    def test_long_sl_hit(self):
        result = _check_signal_hit("BUY", 94.0, 100.0, 95.0, 110.0)
        assert result == "SL_HIT"

    def test_long_no_hit(self):
        result = _check_signal_hit("BUY", 102.0, 100.0, 95.0, 110.0)
        assert result is None

    def test_long_exact_target(self):
        result = _check_signal_hit("LONG", 110.0, 100.0, 95.0, 110.0)
        assert result == "TARGET_HIT"

    def test_long_exact_sl(self):
        result = _check_signal_hit("LONG", 95.0, 100.0, 95.0, 110.0)
        assert result == "SL_HIT"

    def test_short_target_hit(self):
        result = _check_signal_hit("SELL", 88.0, 100.0, 105.0, 90.0)
        assert result == "TARGET_HIT"

    def test_short_sl_hit(self):
        result = _check_signal_hit("SELL", 106.0, 100.0, 105.0, 90.0)
        assert result == "SL_HIT"

    def test_short_no_hit(self):
        result = _check_signal_hit("SHORT", 98.0, 100.0, 105.0, 90.0)
        assert result is None

    def test_short_exact_target(self):
        result = _check_signal_hit("SHORT", 90.0, 100.0, 105.0, 90.0)
        assert result == "TARGET_HIT"

    def test_short_exact_sl(self):
        result = _check_signal_hit("SHORT", 105.0, 100.0, 105.0, 90.0)
        assert result == "SL_HIT"


# ── P&L calculation ─────────────────────────────────────────


class TestCalcPnl:
    def test_long_win(self):
        pnl_pct, pnl_rs = _calc_pnl("BUY", 100.0, 110.0)
        assert pnl_pct == 10.0
        assert pnl_rs == 10.0

    def test_long_loss(self):
        pnl_pct, pnl_rs = _calc_pnl("BUY", 100.0, 95.0)
        assert pnl_pct == -5.0
        assert pnl_rs == -5.0

    def test_short_win(self):
        pnl_pct, pnl_rs = _calc_pnl("SELL", 100.0, 90.0)
        assert pnl_pct == 10.0
        assert pnl_rs == 10.0

    def test_short_loss(self):
        pnl_pct, pnl_rs = _calc_pnl("SHORT", 100.0, 106.0)
        assert pnl_pct == -6.0
        assert pnl_rs == -6.0

    def test_zero_entry(self):
        pnl_pct, pnl_rs = _calc_pnl("BUY", 0, 100.0)
        assert pnl_pct == 0.0
        assert pnl_rs == 0.0

    def test_breakeven(self):
        pnl_pct, pnl_rs = _calc_pnl("BUY", 100.0, 100.0)
        assert pnl_pct == 0.0
        assert pnl_rs == 0.0

    def test_pnl_returns_decimal_types(self):
        # Plan invariant: P&L math lives in the Decimal zone — calling code
        # that multiplies pnl_rs by qty to write outcomes.pnl_amount must
        # stay exact. A silent float regression shows up here.
        pnl_pct, pnl_rs = _calc_pnl("BUY", 100.0, 110.0)
        assert isinstance(pnl_pct, Decimal)
        assert isinstance(pnl_rs, Decimal)

    def test_pnl_preserves_inexact_float_precision(self):
        # The classic 0.1 + 0.2 hazard: entry 100.10, exit 100.30 should be
        # pnl_rs == +0.20 exactly, not 0.19999999...
        pnl_pct, pnl_rs = _calc_pnl("BUY", 100.10, 100.30)
        assert pnl_rs == Decimal("0.20")
        # 0.2 / 100.10 * 100 = 0.1998... → rounds to 0.20 via round_paise.
        assert pnl_pct == Decimal("0.20")

    def test_pnl_accepts_decimal_inputs(self):
        # Entry/exit coming from Signal ORM columns arrive as Decimal.
        pnl_pct, pnl_rs = _calc_pnl(
            "LONG", Decimal("100.00"), Decimal("110.00"),
        )
        assert pnl_pct == Decimal("10.00")
        assert pnl_rs == Decimal("10.00")
