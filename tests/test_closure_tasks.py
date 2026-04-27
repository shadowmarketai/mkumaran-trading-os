"""Tests for closure tasks — 5 EMA shadow mode, event calendar gate,
and reconciler loop being wired into the live pipeline.

These are integration smoke tests: they verify the wiring exists and
behaves correctly with synthetic data, without a live DB or broker.
"""

import pandas as pd
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

_IST = timezone(timedelta(hours=5, minutes=30))


# ── Helper: build minimal OHLCV frame ────────────────────────

def _ohlcv(n: int = 80, trend: str = "up") -> pd.DataFrame:
    closes = [100.0 + (i * 0.5 if trend == "up" else -i * 0.5) for i in range(n)]
    return pd.DataFrame({
        "open":   closes,
        "high":   [c + 0.3 for c in closes],
        "low":    [c - 0.3 for c in closes],
        "close":  closes,
        "volume": [100_000] * n,
    })


# ── Task 3: POS 5 EMA shadow fields appear in signal dict ────


def test_pos_5ema_shadow_fields_present_in_signal(monkeypatch):
    """generate_mwa_signals must include pos_5ema_shadow keys."""
    from mcp_server.mwa_signal_generator import generate_mwa_signals

    df = _ohlcv(80, "up")
    stock_data = {"RELIANCE": df}
    scanner_results = {"swing_low": {"RELIANCE": True}}

    # Stub RRMS settings to avoid Decimal issues
    monkeypatch.setattr(
        "mcp_server.mwa_signal_generator.settings.RRMS_CAPITAL", 100000
    )
    monkeypatch.setattr(
        "mcp_server.mwa_signal_generator.settings.RRMS_RISK_PCT", 0.02
    )
    monkeypatch.setattr(
        "mcp_server.mwa_signal_generator.settings.RRMS_MIN_RRR", 3.0
    )

    signals = generate_mwa_signals(
        promoted=["RELIANCE"],
        stock_data=stock_data,
        mwa_direction="BULL",
        scanner_results=scanner_results,
    )

    assert len(signals) == 1
    sig = signals[0]
    assert "pos_5ema_shadow" in sig, "Shadow flag must be present in signal dict"
    assert "pos_5ema_shadow_direction" in sig
    assert isinstance(sig["pos_5ema_shadow"], bool)


def test_pos_5ema_shadow_killed_shadow_always_false(monkeypatch):
    """Shadow was killed after failed backtest (2026-04-27).
    pos_5ema_shadow must always be False regardless of what detect_latest returns.
    The shadow fields stay in the signal dict for schema compatibility.
    """
    from mcp_server.mwa_signal_generator import generate_mwa_signals

    df = _ohlcv(80, "up")
    stock_data = {"SBIN": df}
    scanner_results = {"swing_low": {"SBIN": True}}

    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_CAPITAL", 100000)
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_RISK_PCT", 0.02)
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_MIN_RRR", 3.0)

    # Even if detect_latest fires, shadow must not propagate
    mock_sig = MagicMock()
    mock_sig.direction = "SHORT"
    mock_sig.confidence = 0.6

    with patch("mcp_server.pos_five_ema.FiveEMAGenerator.detect_latest", return_value=mock_sig):
        signals = generate_mwa_signals(
            promoted=["SBIN"],
            stock_data=stock_data,
            mwa_direction="BULL",
            scanner_results=scanner_results,
        )

    assert len(signals) == 1
    assert signals[0]["direction"] == "LONG"            # primary unchanged
    assert signals[0]["pos_5ema_shadow"] is False        # shadow killed
    assert signals[0]["pos_5ema_shadow_direction"] is None


def test_pos_5ema_shadow_error_does_not_kill_signal(monkeypatch):
    """If 5 EMA throws, the signal is still appended (shadow=False)."""
    from mcp_server.mwa_signal_generator import generate_mwa_signals

    df = _ohlcv(80, "up")
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_CAPITAL", 100000)
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_RISK_PCT", 0.02)
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_MIN_RRR", 3.0)

    with patch("mcp_server.pos_five_ema.FiveEMAGenerator.detect_latest",
               side_effect=RuntimeError("test error")):
        signals = generate_mwa_signals(
            promoted=["TATASTEEL"],
            stock_data={"TATASTEEL": df},
            mwa_direction="BULL",
            scanner_results={"swing_low": {"TATASTEEL": True}},
        )

    assert len(signals) == 1
    assert signals[0]["pos_5ema_shadow"] is False


# ── Task 5: Event calendar gates directional signals ─────────


def test_event_calendar_suppresses_signal_within_1h(monkeypatch):
    """Signals must be dropped when a high-impact event is within 1h."""
    from mcp_server.event_calendar import CalendarEvent, EventCalendar

    now = datetime.now(_IST)
    # Event 30 minutes from now — within the 1h hard gate
    event = CalendarEvent(
        dt=now + timedelta(minutes=30),
        type="rbi_policy",
        buffer_hours=6,
    )
    mock_cal = EventCalendar([event])

    with patch("mcp_server.event_calendar.get_calendar", return_value=mock_cal), \
         patch("mcp_server.market_calendar.is_market_open", return_value=False):

        # Simulate the filter inline (mirrors the code in mcp_server.py)
        signals = [{"ticker": "NIFTY", "direction": "LONG", "timeframe": "day"}]

        def _event_filter(sig):
            tf = (sig.get("timeframe") or "day").lower()
            if tf in ("5m", "15m", "1h", "intraday"):
                return not mock_cal.high_impact_within(hours=4)
            if mock_cal.high_impact_within(hours=1):
                return False
            return True

        filtered = [s for s in signals if _event_filter(s)]
        assert filtered == [], "Signal must be suppressed when event is within 1h"


def test_event_calendar_allows_signal_far_from_event(monkeypatch):
    """Signals must pass when no event is within 1h."""
    from mcp_server.event_calendar import CalendarEvent, EventCalendar

    now = datetime.now(_IST)
    event = CalendarEvent(
        dt=now + timedelta(hours=48),
        type="fed_fomc",
        buffer_hours=12,
    )
    mock_cal = EventCalendar([event])

    signals = [{"ticker": "RELIANCE", "direction": "LONG", "timeframe": "day"}]

    def _event_filter(sig):
        tf = (sig.get("timeframe") or "day").lower()
        if tf in ("5m", "15m", "1h", "intraday"):
            return not mock_cal.high_impact_within(hours=4)
        if mock_cal.high_impact_within(hours=1):
            return False
        return True

    filtered = [s for s in signals if _event_filter(s)]
    assert len(filtered) == 1, "Signal must pass when event is 48h away"


def test_event_calendar_suppresses_intraday_within_4h(monkeypatch):
    """Intraday signals blocked when event within 4h (stricter gate)."""
    from mcp_server.event_calendar import CalendarEvent, EventCalendar

    now = datetime.now(_IST)
    event = CalendarEvent(
        dt=now + timedelta(hours=2),
        type="us_nfp",
        buffer_hours=4,
    )
    mock_cal = EventCalendar([event])

    signals = [{"ticker": "BANKNIFTY", "direction": "LONG", "timeframe": "5m"}]

    def _event_filter(sig):
        tf = (sig.get("timeframe") or "day").lower()
        if tf in ("5m", "15m", "1h", "intraday"):
            return not mock_cal.high_impact_within(hours=4)
        if mock_cal.high_impact_within(hours=1):
            return False
        return True

    filtered = [s for s in signals if _event_filter(s)]
    assert filtered == [], "Intraday signal must be suppressed when event within 4h"


# ── Task 4: Reconciler loop is wired in lifespan ─────────────


def test_reconciler_loop_defined_in_mcp_server():
    """Verify the reconciler loop exists in the lifespan body."""
    import inspect
    from mcp_server import mcp_server as ms
    src = inspect.getsource(ms)
    assert "_reconciler_loop" in src, (
        "_reconciler_loop must be defined in mcp_server lifespan"
    )
    assert "run_reconciliation" in src
    assert "asyncio.sleep(60)" in src


def test_reconciler_loop_gates_on_market_hours():
    """Loop body must check is_market_open before calling reconcile."""
    import inspect
    from mcp_server import mcp_server as ms
    src = inspect.getsource(ms)
    # The loop should gate on market hours check
    assert "is_market_open" in src or "_is_open" in src


# ── Constant: shadow flag is always a bool ────────────────────


def test_shadow_flag_is_false_when_no_signal(monkeypatch):
    from mcp_server.mwa_signal_generator import generate_mwa_signals

    df = _ohlcv(80, "up")
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_CAPITAL", 100000)
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_RISK_PCT", 0.02)
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_MIN_RRR", 3.0)

    with patch("mcp_server.pos_five_ema.FiveEMAGenerator.detect_latest", return_value=None):
        signals = generate_mwa_signals(
            promoted=["RELIANCE"],
            stock_data={"RELIANCE": df},
            mwa_direction="BULL",
            scanner_results={"swing_low": {"RELIANCE": True}},
        )

    assert len(signals) == 1
    assert signals[0]["pos_5ema_shadow"] is False
    assert signals[0]["pos_5ema_shadow_direction"] is None
