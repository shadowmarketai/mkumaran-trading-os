"""Tests for mcp_server.shadow_observer — record and resolve logic."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


_IST = timezone(timedelta(hours=5, minutes=30))


# ── record_shadow_signal ──────────────────────────────────────


def test_record_writes_row(monkeypatch):
    """record_shadow_signal writes an observation with agreed=True when directions match."""
    from mcp_server.shadow_observer import record_shadow_signal

    saved = {}

    class _FakeObs:
        id = 42

    class _FakeDB:
        def add(self, obj): saved["obj"] = obj
        def commit(self): pass
        def refresh(self, obj): obj.id = 42
        def rollback(self): pass
        def close(self): pass

    row_id = record_shadow_signal(
        engine="pos_5ema",
        ticker="RELIANCE",
        direction="LONG",
        entry=2800.0,
        sl=2750.0,
        target=2900.0,
        confidence=0.72,
        primary_direction="LONG",
        primary_entry=2800.0,
        db=_FakeDB(),
    )
    assert row_id == 42
    obs = saved["obj"]
    assert obs.engine == "pos_5ema"
    assert obs.ticker == "RELIANCE"
    assert obs.agreed is True    # directions match
    assert float(obs.shadow_entry) == 2800.0


def test_record_agreed_false_when_directions_differ(monkeypatch):
    """agreed=False when shadow direction ≠ primary direction."""
    from mcp_server.shadow_observer import record_shadow_signal

    saved = {}

    class _FakeDB:
        def add(self, obj): saved["obj"] = obj
        def commit(self): pass
        def refresh(self, obj): obj.id = 1
        def rollback(self): pass
        def close(self): pass

    record_shadow_signal(
        engine="pos_5ema", ticker="SBIN",
        direction="SHORT", entry=800.0, sl=820.0, target=760.0,
        confidence=0.6, primary_direction="LONG", primary_entry=800.0,
        db=_FakeDB(),
    )
    assert saved["obj"].agreed is False


def test_record_returns_none_on_db_error(monkeypatch):
    """Returns None without raising when DB fails."""
    from mcp_server.shadow_observer import record_shadow_signal

    class _FailDB:
        def add(self, obj): raise RuntimeError("db down")
        def commit(self): pass
        def refresh(self, obj): pass
        def rollback(self): pass
        def close(self): pass

    result = record_shadow_signal(
        engine="pos_5ema", ticker="TCS",
        direction="LONG", entry=3500.0, sl=3450.0, target=3600.0,
        confidence=0.5, primary_direction="LONG", primary_entry=3500.0,
        db=_FailDB(),
    )
    assert result is None


# ── resolve_shadow_signals ────────────────────────────────────


class _FakeObs:
    def __init__(self, direction="LONG", entry=1000.0, sl=950.0, target=1100.0,
                 days_old=1, ticker="RELIANCE", exchange="NSE"):
        self.id = 1
        self.direction = direction
        self.shadow_entry = entry
        self.shadow_sl = sl
        self.shadow_target = target
        self.ticker = ticker
        self.exchange = exchange
        self.engine = "pos_5ema"
        self.observed_at = datetime.now(_IST) - timedelta(days=days_old)
        # Outcome fields (filled by resolver)
        self.resolved_at = None
        self.outcome = None
        self.exit_price = None
        self.pnl_pct = None
        self.resolution_reason = None


def _fake_db(obs_list):
    class _Q:
        def filter(self, *a): return self
        def all(self): return obs_list
    class _DB:
        def query(self, _): return _Q()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass
    return _DB()


def test_resolve_marks_target_hit(monkeypatch):
    obs = _FakeObs(direction="LONG", entry=1000.0, sl=950.0, target=1100.0)
    db = _fake_db([obs])

    # LTP above target → WIN
    with patch("mcp_server.data_provider.get_provider",
               return_value=MagicMock(get_ltp=lambda t: 1110.0)):
        from mcp_server.shadow_observer import resolve_shadow_signals
        count = resolve_shadow_signals(db=db)
    assert count == 1
    assert obs.outcome == "WIN"
    assert obs.resolution_reason == "TARGET"
    assert obs.pnl_pct > 0


def test_resolve_marks_stoploss_hit(monkeypatch):
    obs = _FakeObs(direction="LONG", entry=1000.0, sl=950.0, target=1100.0)
    db = _fake_db([obs])

    with patch("mcp_server.data_provider.get_provider",
               return_value=MagicMock(get_ltp=lambda t: 940.0)):
        from mcp_server.shadow_observer import resolve_shadow_signals
        count = resolve_shadow_signals(db=db)
    assert count == 1
    assert obs.outcome == "LOSS"
    assert obs.resolution_reason == "STOPLOSS"
    assert obs.pnl_pct < 0


def test_resolve_still_open_returns_zero(monkeypatch):
    obs = _FakeObs(direction="LONG", entry=1000.0, sl=950.0, target=1100.0)
    db = _fake_db([obs])

    with patch("mcp_server.data_provider.get_provider",
               return_value=MagicMock(get_ltp=lambda t: 1020.0)):
        from mcp_server.shadow_observer import resolve_shadow_signals
        count = resolve_shadow_signals(db=db)
    assert count == 0
    assert obs.outcome is None


def test_resolve_expires_old_observation(monkeypatch):
    obs = _FakeObs(days_old=100)  # older than _TIMEOUT_DAYS=90
    db = _fake_db([obs])

    with patch("mcp_server.data_provider.get_provider",
               return_value=MagicMock(get_ltp=lambda t: 1000.0)):
        from mcp_server.shadow_observer import resolve_shadow_signals
        count = resolve_shadow_signals(db=db)
    assert count == 1
    assert obs.outcome == "EXPIRED"
    assert obs.resolution_reason == "TIMEOUT"


def test_resolve_empty_returns_zero():
    db = _fake_db([])
    from mcp_server.shadow_observer import resolve_shadow_signals
    count = resolve_shadow_signals(db=db)
    assert count == 0


def test_resolve_no_ltp_skips():
    obs = _FakeObs()
    db = _fake_db([obs])

    with patch("mcp_server.data_provider.get_provider",
               return_value=MagicMock(get_ltp=lambda t: 0)):
        from mcp_server.shadow_observer import resolve_shadow_signals
        count = resolve_shadow_signals(db=db)
    assert count == 0
    assert obs.outcome is None


# ── Shadow wired into mwa_signal_generator ───────────────────


def test_shadow_record_called_when_5ema_fires(monkeypatch):
    """When pos_5ema.detect_latest returns a signal, record_shadow_signal is called."""
    from mcp_server.mwa_signal_generator import generate_mwa_signals
    import pandas as pd

    n = 80
    closes = [100.0 + i * 0.5 for i in range(n)]
    df = pd.DataFrame({
        "open": closes, "high": [c + 0.3 for c in closes],
        "low": [c - 0.3 for c in closes], "close": closes,
        "volume": [100_000] * n,
    })

    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_CAPITAL", 100000)
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_RISK_PCT", 0.02)
    monkeypatch.setattr("mcp_server.mwa_signal_generator.settings.RRMS_MIN_RRR", 3.0)

    from decimal import Decimal
    mock_shadow = MagicMock()
    mock_shadow.direction = "LONG"
    mock_shadow.entry = Decimal("110.5")
    mock_shadow.stop_loss = Decimal("109.0")
    mock_shadow.target = Decimal("113.5")
    mock_shadow.confidence = 0.7

    recorded: list = []

    def _fake_record(**kwargs):
        recorded.append(kwargs)
        return 99

    with patch("mcp_server.pos_five_ema.FiveEMAGenerator.detect_latest", return_value=mock_shadow), \
         patch("mcp_server.shadow_observer.record_shadow_signal", side_effect=_fake_record):
        signals = generate_mwa_signals(
            promoted=["RELIANCE"],
            stock_data={"RELIANCE": df},
            mwa_direction="BULL",
            scanner_results={"swing_low": {"RELIANCE": True}},
        )

    assert len(signals) == 1
    assert signals[0]["pos_5ema_shadow"] is True
    assert len(recorded) == 1
    assert recorded[0]["engine"] == "pos_5ema"
    assert recorded[0]["ticker"] == "RELIANCE"


# ── resolve wired into signal_monitor ────────────────────────


def test_resolve_called_from_signal_monitor():
    """resolve_shadow_signals must be imported in signal_monitor source."""
    import inspect
    from mcp_server import signal_monitor
    src = inspect.getsource(signal_monitor)
    assert "resolve_shadow_signals" in src
    assert "shadow_observer" in src
