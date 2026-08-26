"""Tests for SheetsTracker.get_accuracy_stats — DB-backed (Postgres reads).

The stats used to be read from Google Sheets, which showed zeros whenever
the sheet-write path was stale even though the DB had real data. The
rewrite queries Signal + Outcome directly (same source as tool_eod_summary
in routers/signals.py). These tests lock down the new source of truth.
"""

from datetime import date
from decimal import Decimal

from mcp_server.db import SessionLocal
from mcp_server.models import Outcome, Signal
from mcp_server.telegram_receiver import SheetsTracker


def _mk_signal(session, *, ticker: str, entry: float, qty: int, status: str = "OPEN",
               suppressed: bool = False) -> Signal:
    sig = Signal(
        signal_date=date.today(),
        ticker=ticker,
        exchange="NSE",
        asset_class="EQUITY",
        direction="LONG",
        pattern="test",
        entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(entry * 0.95)),
        target=Decimal(str(entry * 1.10)),
        rrr=2.0,
        qty=qty,
        risk_amt=Decimal(str(entry * 0.05 * qty)),
        ai_confidence=80,
        scanner_count=1,
        source="test",
        timeframe="1D",
        status=status,
        suppressed=suppressed,
    )
    session.add(sig)
    session.flush()
    return sig


def _mk_outcome(session, sig: Signal, *, outcome: str, exit_price: float, pnl_amount: float):
    out = Outcome(
        signal_id=sig.id,
        exit_date=date.today(),
        exit_price=Decimal(str(exit_price)),
        outcome=outcome,
        pnl_amount=Decimal(str(pnl_amount)),
        days_held=1,
        exit_reason="TARGET" if outcome == "WIN" else "STOPLOSS",
    )
    session.add(out)
    session.flush()


class TestGetAccuracyStats:
    """Uses conftest.py's setup_db autouse fixture (SQLite in tmpfile)."""

    def test_empty_db_returns_zero_shape(self, db_session):
        # Empty-DB response preserves the sheet-era shape so any caller
        # inspecting .get("total") / .get("message") still works.
        tracker = SheetsTracker()
        stats = tracker.get_accuracy_stats()
        assert stats == {"total": 0, "message": "No signals recorded"}

    def test_populated_db_computes_win_rate_and_pnl(self, db_session):
        # Session in conftest is separate from SessionLocal; get_accuracy_stats
        # opens its own SessionLocal → we must commit through the shared DB URL.
        s = SessionLocal()
        try:
            w1 = _mk_signal(s, ticker="WIN1", entry=100.0, qty=10, status="TARGET_HIT")
            _mk_outcome(s, w1, outcome="WIN", exit_price=110.0, pnl_amount=100.0)  # +10%

            l1 = _mk_signal(s, ticker="LOS1", entry=200.0, qty=5, status="SL_HIT")
            _mk_outcome(s, l1, outcome="LOSS", exit_price=190.0, pnl_amount=-50.0)  # -5%

            _mk_signal(s, ticker="OPEN1", entry=150.0, qty=8, status="OPEN")
            s.commit()
        finally:
            s.close()

        stats = SheetsTracker().get_accuracy_stats()

        assert stats["total_signals"] == 3
        assert stats["open"] == 1
        assert stats["closed"] == 2
        assert stats["wins"] == 1
        assert stats["losses"] == 1
        assert stats["win_rate"] == 50.0
        assert stats["total_pnl_rs"] == 50.0    # +100 + -50
        assert stats["avg_win_pct"] == 10.0     # (100/10)/100*100
        assert stats["avg_loss_pct"] == -5.0    # (-50/5)/200*100
        # expectancy = avg_win * (wins/closed) + avg_loss * (losses/closed)
        #            = 10 * 0.5 + (-5) * 0.5 = 2.5
        assert stats["expectancy"] == 2.5

    def test_suppressed_signals_count_in_total_but_not_open(self, db_session):
        # Regression: sits alongside the SUPPRESSED status fix in
        # mcp_server.py. Suppressed signals fired (belong in total_signals)
        # but were never acted on (excluded from open + closed).
        s = SessionLocal()
        try:
            _mk_signal(s, ticker="OPEN1", entry=100.0, qty=1, status="OPEN")
            _mk_signal(s, ticker="SUPP1", entry=100.0, qty=1,
                       status="SUPPRESSED", suppressed=True)
            s.commit()
        finally:
            s.close()

        stats = SheetsTracker().get_accuracy_stats()

        assert stats["total_signals"] == 2
        assert stats["open"] == 1        # only OPEN, not SUPPRESSED
        assert stats["closed"] == 0
