"""Tests for Trade Reflector — trade_reflector.py"""

import os
from unittest.mock import patch


from mcp_server.trade_memory import TradeRecord, TradeMemory
from mcp_server.trade_reflector import TradeReflector


# ── Helpers ──────────────────────────────────────────────────────


def _make_memory(tmp_path):
    filepath = os.path.join(str(tmp_path), "test_memory.json")
    return TradeMemory(filepath=filepath)


def _sample_record(sid="S001", ticker="NSE:RELIANCE", confidence=70, outcome="", pnl_pct=0.0):
    return TradeRecord(
        signal_id=sid, ticker=ticker, direction="BUY",
        pattern="RRMS", entry_price=2500, stop_loss=2450,
        target=2600, rrr=2.0, confidence=confidence,
        recommendation="ALERT" if confidence >= 70 else "WATCHLIST",
        outcome=outcome, pnl_pct=pnl_pct, exit_price=2590 if outcome else 0.0,
        holding_days=5 if outcome else 0,
    )


# ── Offline lesson generation (4 quadrants) ─────────────────────


def test_offline_lesson_high_conf_win(tmp_path):
    """High confidence + WIN = trust the pattern."""
    mem = _make_memory(tmp_path)
    mem.add_record(_sample_record("S001", confidence=75, outcome="WIN", pnl_pct=5.2))
    reflector = TradeReflector(mem)

    with patch("mcp_server.trade_reflector.settings") as mock_s:
        mock_s.ANTHROPIC_API_KEY = ""  # Force offline
        result = reflector.reflect_on_trade("S001")

    assert result["success"] is True
    assert result["method"] == "offline"
    assert "Trust" in result["lesson"]


def test_offline_lesson_high_conf_loss(tmp_path):
    """High confidence + LOSS = overconfidence warning."""
    mem = _make_memory(tmp_path)
    mem.add_record(_sample_record("S002", confidence=80, outcome="LOSS", pnl_pct=-3.5))
    reflector = TradeReflector(mem)

    with patch("mcp_server.trade_reflector.settings") as mock_s:
        mock_s.ANTHROPIC_API_KEY = ""
        result = reflector.reflect_on_trade("S002")

    assert result["success"] is True
    assert "Overconfidence" in result["lesson"]


def test_offline_lesson_low_conf_win(tmp_path):
    """Low confidence + WIN = unexpected, consider upgrading."""
    mem = _make_memory(tmp_path)
    mem.add_record(_sample_record("S003", confidence=45, outcome="WIN", pnl_pct=4.0))
    reflector = TradeReflector(mem)

    with patch("mcp_server.trade_reflector.settings") as mock_s:
        mock_s.ANTHROPIC_API_KEY = ""
        result = reflector.reflect_on_trade("S003")

    assert result["success"] is True
    assert "under-scored" in result["lesson"] or "upgrading" in result["lesson"]


def test_offline_lesson_low_conf_loss(tmp_path):
    """Low confidence + LOSS = system correctly flagged."""
    mem = _make_memory(tmp_path)
    mem.add_record(_sample_record("S004", confidence=35, outcome="LOSS", pnl_pct=-2.1))
    reflector = TradeReflector(mem)

    with patch("mcp_server.trade_reflector.settings") as mock_s:
        mock_s.ANTHROPIC_API_KEY = ""
        result = reflector.reflect_on_trade("S004")

    assert result["success"] is True
    assert "correctly" in result["lesson"]


def test_offline_lesson_breakeven(tmp_path):
    """BREAKEVEN trade gets tighter exit rule suggestion."""
    mem = _make_memory(tmp_path)
    r = _sample_record("S005", confidence=60, outcome="BREAKEVEN", pnl_pct=0.0)
    mem.add_record(r)
    reflector = TradeReflector(mem)

    with patch("mcp_server.trade_reflector.settings") as mock_s:
        mock_s.ANTHROPIC_API_KEY = ""
        result = reflector.reflect_on_trade("S005")

    assert result["success"] is True
    assert "breakeven" in result["lesson"].lower() or "exit" in result["lesson"].lower()


# ── Online reflection (mocked API) ──────────────────────────────


def test_online_reflection(tmp_path):
    """With API key, uses Claude to generate lesson."""
    mem = _make_memory(tmp_path)
    mem.add_record(_sample_record("S006", confidence=70, outcome="WIN", pnl_pct=3.0))
    reflector = TradeReflector(mem)

    lesson_text = "RRMS breakout on RELIANCE rewarded patience. Repeat for similar setups."
    with patch.object(reflector, "_generate_lesson", return_value=lesson_text) as mock_gen, \
         patch("mcp_server.trade_reflector.settings") as mock_s:
        mock_s.ANTHROPIC_API_KEY = "sk-test-key-1234567890abcdef"
        result = reflector.reflect_on_trade("S006")

    assert result["success"] is True
    assert result["method"] == "online"
    assert "RELIANCE" in result["lesson"]
    mock_gen.assert_called_once()


def test_online_failure_falls_back_to_offline(tmp_path):
    """If API call fails, falls back to offline lesson."""
    mem = _make_memory(tmp_path)
    mem.add_record(_sample_record("S007", confidence=70, outcome="WIN", pnl_pct=4.0))
    reflector = TradeReflector(mem)

    with patch.object(reflector, "_generate_lesson", side_effect=Exception("API down")), \
         patch("mcp_server.trade_reflector.settings") as mock_s:
        mock_s.ANTHROPIC_API_KEY = "sk-test-key-1234567890abcdef"
        result = reflector.reflect_on_trade("S007")

    assert result["success"] is True
    assert result["method"] == "offline"


# ── Edge cases ───────────────────────────────────────────────────


def test_reflect_signal_not_found(tmp_path):
    mem = _make_memory(tmp_path)
    reflector = TradeReflector(mem)
    result = reflector.reflect_on_trade("NONEXIST")
    assert result["success"] is False
    assert "not found" in result["error"]


def test_reflect_open_trade_rejected(tmp_path):
    """Cannot reflect on a trade that hasn't closed yet."""
    mem = _make_memory(tmp_path)
    mem.add_record(_sample_record("S008", outcome=""))
    reflector = TradeReflector(mem)
    result = reflector.reflect_on_trade("S008")
    assert result["success"] is False
    assert "OPEN" in result["error"]


def test_already_reflected(tmp_path):
    """Reflecting on an already-reflected trade returns existing lesson."""
    mem = _make_memory(tmp_path)
    mem.add_record(_sample_record("S009", confidence=70, outcome="WIN", pnl_pct=3.0))
    mem.add_lesson("S009", "Previously learned lesson")
    reflector = TradeReflector(mem)

    result = reflector.reflect_on_trade("S009")
    assert result["success"] is True
    assert result["method"] == "already_reflected"
    assert result["lesson"] == "Previously learned lesson"


# ── Batch reflection ─────────────────────────────────────────────


def test_reflect_batch(tmp_path):
    """Batch reflects on multiple unreflected closed trades."""
    mem = _make_memory(tmp_path)
    # Add 3 closed trades, none reflected
    for i in range(3):
        mem.add_record(_sample_record(f"S{i:03d}", confidence=60, outcome="WIN", pnl_pct=2.0))
    reflector = TradeReflector(mem)

    with patch("mcp_server.trade_reflector.settings") as mock_s:
        mock_s.ANTHROPIC_API_KEY = ""  # Force offline
        result = reflector.reflect_batch(limit=10)

    assert result["reflected"] == 3
    assert result["total_candidates"] == 3


def test_reflect_batch_empty(tmp_path):
    """Batch with no unreflected trades returns zero."""
    mem = _make_memory(tmp_path)
    reflector = TradeReflector(mem)
    result = reflector.reflect_batch()
    assert result["reflected"] == 0


# ── Stats ────────────────────────────────────────────────────────


def test_reflection_stats(tmp_path):
    """Stats segmented by confidence level."""
    mem = _make_memory(tmp_path)
    # 2 high-conf trades: 1 WIN, 1 LOSS
    mem.add_record(_sample_record("S001", confidence=80, outcome="WIN", pnl_pct=5.0))
    mem.add_record(_sample_record("S002", confidence=75, outcome="LOSS", pnl_pct=-3.0))
    # 2 low-conf trades: 1 WIN, 1 LOSS
    mem.add_record(_sample_record("S003", confidence=55, outcome="WIN", pnl_pct=2.0))
    mem.add_record(_sample_record("S004", confidence=40, outcome="LOSS", pnl_pct=-1.5))

    reflector = TradeReflector(mem)
    stats = reflector.get_reflection_stats()

    assert stats["high_conf_trades"] == 2
    assert stats["high_conf_win_rate"] == 50.0
    assert stats["low_conf_trades"] == 2
    assert stats["low_conf_win_rate"] == 50.0
    assert stats["total"] == 4
