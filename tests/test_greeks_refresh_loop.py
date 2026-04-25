"""Tests for mcp_server.options_seller.greeks_refresh_loop — market hours gate,
one_refresh_cycle smoke, n8n reconciler patch verified."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from mcp_server.options_seller.greeks_refresh_loop import (
    REFRESH_INTERVAL_S,
    _is_market_hours,
    _get_open_instruments,
)

_IST = timezone(timedelta(hours=5, minutes=30))


# ── _is_market_hours ─────────────────────────────────────────


def _ist(hour: int, minute: int, weekday: int = 0) -> datetime:
    """Build an IST datetime for testing. weekday: 0=Mon … 6=Sun."""
    base = datetime(2026, 4, 20, hour, minute, 0, tzinfo=_IST)   # 2026-04-20 = Monday
    return base + timedelta(days=weekday)


def test_market_hours_open():
    with patch("mcp_server.options_seller.greeks_refresh_loop.datetime") as mock_dt:
        mock_dt.now.return_value = _ist(10, 0, weekday=0)   # Monday 10:00 IST
        assert _is_market_hours() is True


def test_market_hours_before_open():
    with patch("mcp_server.options_seller.greeks_refresh_loop.datetime") as mock_dt:
        mock_dt.now.return_value = _ist(9, 0, weekday=0)    # 09:00 — before 09:15
        assert _is_market_hours() is False


def test_market_hours_after_close():
    with patch("mcp_server.options_seller.greeks_refresh_loop.datetime") as mock_dt:
        mock_dt.now.return_value = _ist(15, 45, weekday=0)  # after 15:30
        assert _is_market_hours() is False


def test_market_hours_saturday():
    with patch("mcp_server.options_seller.greeks_refresh_loop.datetime") as mock_dt:
        mock_dt.now.return_value = _ist(11, 0, weekday=5)   # Saturday
        assert _is_market_hours() is False


def test_market_hours_sunday():
    with patch("mcp_server.options_seller.greeks_refresh_loop.datetime") as mock_dt:
        mock_dt.now.return_value = _ist(11, 0, weekday=6)   # Sunday
        assert _is_market_hours() is False


def test_market_hours_at_open():
    with patch("mcp_server.options_seller.greeks_refresh_loop.datetime") as mock_dt:
        mock_dt.now.return_value = _ist(9, 15, weekday=1)   # exactly 09:15
        assert _is_market_hours() is True


def test_market_hours_at_close():
    with patch("mcp_server.options_seller.greeks_refresh_loop.datetime") as mock_dt:
        mock_dt.now.return_value = _ist(15, 30, weekday=2)  # exactly 15:30
        assert _is_market_hours() is True


# ── _get_open_instruments ─────────────────────────────────────


def test_get_open_instruments_returns_empty_on_error(monkeypatch):
    """If DB is unreachable, returns [] gracefully."""
    def _raise():
        raise RuntimeError("DB unavailable")
    monkeypatch.setattr(
        "mcp_server.options_seller.greeks_refresh_loop._get_open_instruments",
        _raise,
    )
    # The function itself has a try/except that returns []
    # Test the raw function handles it
    from mcp_server.options_seller import position_manager as pm
    monkeypatch.setattr(pm, "_fetch_open_positions", lambda: (_ for _ in ()).throw(RuntimeError("err")))
    result = _get_open_instruments()
    assert result == []


def test_get_open_instruments_deduplicates(monkeypatch):
    """Two rows with same instrument → returned once."""
    from mcp_server.options_seller import position_manager as pm
    monkeypatch.setattr(
        pm, "_fetch_open_positions",
        lambda: [(1, "BANKNIFTY"), (2, "BANKNIFTY"), (3, "NIFTY")],
    )
    result = _get_open_instruments()
    assert sorted(result) == ["BANKNIFTY", "NIFTY"]


# ── REFRESH_INTERVAL_S constant ───────────────────────────────


def test_refresh_interval_default_is_5_minutes():
    assert REFRESH_INTERVAL_S == 300


# ── n8n workflow patch ────────────────────────────────────────


def test_market_monitor_has_reconcile_node():
    """Verify the 02_market_monitor.json now contains the Broker Reconcile node."""
    import json
    from pathlib import Path
    d = json.loads(Path("n8n_workflows/02_market_monitor.json").read_text(encoding="utf-8"))
    node_names = [n["name"] for n in d["nodes"]]
    assert "Broker Reconcile" in node_names


def test_market_monitor_reconcile_wired_to_holiday_check():
    """Broker Reconcile must be a target of Holiday Check."""
    import json
    from pathlib import Path
    d = json.loads(Path("n8n_workflows/02_market_monitor.json").read_text(encoding="utf-8"))
    targets = [
        e["node"]
        for branch in d["connections"].get("Holiday Check", {}).get("main", [[]])
        for e in branch
    ]
    assert "Broker Reconcile" in targets


def test_market_monitor_reconcile_posts_to_correct_url():
    import json
    from pathlib import Path
    d = json.loads(Path("n8n_workflows/02_market_monitor.json").read_text(encoding="utf-8"))
    node = next((n for n in d["nodes"] if n["name"] == "Broker Reconcile"), None)
    assert node is not None
    url = node["parameters"]["url"]
    assert "money.shadowmarket.ai" in url
    assert "reconcile/run" in url


# ── start_loop does not crash when loop disabled ──────────────


@pytest.mark.asyncio
async def test_start_loop_exits_immediately_when_disabled(monkeypatch):
    """When OPTIONS_GREEKS_LOOP_ENABLED=false, start_loop returns immediately."""
    from mcp_server.config import settings
    monkeypatch.setattr(settings, "OPTIONS_GREEKS_LOOP_ENABLED", "false")
    from mcp_server.options_seller.greeks_refresh_loop import start_loop
    # Should complete without hanging
    await start_loop()
