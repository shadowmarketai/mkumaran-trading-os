"""Tests for Signal Auto-Monitor — SL/TGT hit detection and P&L calculation."""

from datetime import date
from decimal import Decimal

from mcp_server.models import Signal
from mcp_server.signal_monitor import _calc_pnl, _check_signal_hit

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


# ── Predictor suppression regression ────────────────────────
#
# Regression for: predictor-suppressed signals were being picked up by
# signal_monitor and "closed" with real P&L, because suppression only
# skipped ActiveTrade creation and left Signal.status = "OPEN". The fix
# now sets status = "SUPPRESSED" in the suppression block.


class TestSuppressedNotMonitored:
    """The OPEN-signals query used by signal_monitor must not surface
    predictor-suppressed rows — they represent signals we deliberately
    didn't take, so there's no position to close.
    """

    def _make_signal(self, session, *, status: str, suppressed: bool, ticker: str):
        sig = Signal(
            signal_date=date.today(),
            ticker=ticker,
            exchange="NSE",
            asset_class="EQUITY",
            direction="LONG",
            pattern="test",
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            target=Decimal("110"),
            rrr=2.0,
            qty=1,
            risk_amt=Decimal("5"),
            ai_confidence=80,
            scanner_count=1,
            source="test",
            timeframe="1D",
            status=status,
            suppressed=suppressed,
        )
        session.add(sig)
        session.commit()
        return sig

    def test_suppressed_signal_excluded_from_open_query(self, db_session):
        # Mirror what signal_monitor.monitor_open_signals() runs at line 107.
        self._make_signal(db_session, status="OPEN", suppressed=False, ticker="OPENSIG")
        self._make_signal(db_session, status="SUPPRESSED", suppressed=True, ticker="SUPPSIG")

        open_rows = db_session.query(Signal).filter(Signal.status == "OPEN").all()
        tickers = {s.ticker for s in open_rows}
        assert "OPENSIG" in tickers, "OPEN signal must still be picked up"
        assert "SUPPSIG" not in tickers, (
            "SUPPRESSED signal leaked into the monitor's OPEN query — "
            "the bug this test exists to prevent"
        )

    def test_suppressed_signal_still_counted_in_todays_total(self, db_session):
        # EOD report counts len(today_sigs) as "all generated today", which
        # SHOULD include suppressed ones — the signal did fire, we just
        # didn't act on it. Regression against over-fixing by hiding them.
        self._make_signal(db_session, status="OPEN", suppressed=False, ticker="OPENSIG")
        self._make_signal(db_session, status="SUPPRESSED", suppressed=True, ticker="SUPPSIG")

        today_sigs = db_session.query(Signal).filter(
            Signal.signal_date == date.today()
        ).all()
        assert len(today_sigs) == 2
        assert {s.ticker for s in today_sigs} == {"OPENSIG", "SUPPSIG"}

    def test_suppressed_count_queryable_separately(self, db_session):
        # routers/selfdev.py:61 counts suppressed via Signal.suppressed.is_(True).
        # Verify the flag round-trips correctly alongside the status change.
        self._make_signal(db_session, status="SUPPRESSED", suppressed=True, ticker="SUPPSIG")

        supp_count = db_session.query(Signal).filter(
            Signal.suppressed.is_(True)
        ).count()
        assert supp_count == 1
