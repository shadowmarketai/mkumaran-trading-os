"""Tests for BM25 Trade Memory — trade_memory.py"""

import json
import os


from mcp_server.trade_memory import TradeRecord, TradeMemory


# ── TradeRecord ─────────────────────────────────────────────────


def test_trade_record_defaults():
    r = TradeRecord(
        signal_id="S001", ticker="NSE:RELIANCE", direction="BUY",
        pattern="RRMS", entry_price=2500.0, stop_loss=2450.0,
        target=2600.0, rrr=2.0, confidence=65, recommendation="WATCHLIST",
    )
    assert r.signal_id == "S001"
    assert r.outcome == ""
    assert r.reflected is False
    assert r.timestamp != ""  # auto-filled by __post_init__


def test_trade_record_to_situation_text():
    r = TradeRecord(
        signal_id="S002", ticker="MCX:GOLD", direction="BUY",
        pattern="breakout", entry_price=60000, stop_loss=59500,
        target=61000, rrr=2.0, confidence=72, recommendation="ALERT",
        exchange="MCX", outcome="WIN", lesson="Trust breakout on MCX gold",
    )
    text = r.to_situation_text()
    assert "MCX:GOLD" in text
    assert "BUY" in text
    assert "breakout" in text
    assert "outcome_WIN" in text
    assert "Trust breakout" in text


def test_trade_record_situation_text_no_outcome():
    r = TradeRecord(
        signal_id="S003", ticker="NSE:TCS", direction="SELL",
        pattern="SMC", entry_price=3500, stop_loss=3550,
        target=3400, rrr=2.0, confidence=55, recommendation="WATCHLIST",
    )
    text = r.to_situation_text()
    assert "outcome_" not in text


# ── TradeMemory persistence ─────────────────────────────────────


def _make_memory(tmp_path):
    filepath = os.path.join(str(tmp_path), "test_memory.json")
    return TradeMemory(filepath=filepath), filepath


def _sample_record(sid="S001", ticker="NSE:RELIANCE", direction="BUY", confidence=65):
    return TradeRecord(
        signal_id=sid, ticker=ticker, direction=direction,
        pattern="RRMS", entry_price=2500, stop_loss=2450,
        target=2600, rrr=2.0, confidence=confidence,
        recommendation="WATCHLIST",
    )


def test_empty_memory_stats(tmp_path):
    mem, _ = _make_memory(tmp_path)
    stats = mem.get_stats()
    assert stats["total"] == 0
    assert stats["with_outcome"] == 0


def test_add_record_and_save(tmp_path):
    mem, filepath = _make_memory(tmp_path)
    mem.add_record(_sample_record())
    assert mem.get_stats()["total"] == 1

    # Verify JSON file was created
    assert os.path.exists(filepath)
    with open(filepath, "r") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["signal_id"] == "S001"


def test_load_existing(tmp_path):
    mem1, filepath = _make_memory(tmp_path)
    mem1.add_record(_sample_record("S001"))
    mem1.add_record(_sample_record("S002", ticker="NSE:TCS"))

    # Load fresh from same file
    mem2 = TradeMemory(filepath=filepath)
    assert mem2.get_stats()["total"] == 2


def test_update_outcome(tmp_path):
    mem, _ = _make_memory(tmp_path)
    mem.add_record(_sample_record())

    result = mem.update_outcome("S001", "WIN", exit_price=2590, pnl_pct=3.6, holding_days=5)
    assert result is True

    record = mem.get_record_by_id("S001")
    assert record.outcome == "WIN"
    assert record.exit_price == 2590
    assert record.pnl_pct == 3.6
    assert record.holding_days == 5


def test_update_outcome_not_found(tmp_path):
    mem, _ = _make_memory(tmp_path)
    mem.add_record(_sample_record())
    assert mem.update_outcome("NONEXIST", "LOSS") is False


def test_add_lesson(tmp_path):
    mem, _ = _make_memory(tmp_path)
    mem.add_record(_sample_record())

    result = mem.add_lesson("S001", "Trust RRMS on RELIANCE")
    assert result is True

    record = mem.get_record_by_id("S001")
    assert record.lesson == "Trust RRMS on RELIANCE"
    assert record.reflected is True


def test_add_lesson_not_found(tmp_path):
    mem, _ = _make_memory(tmp_path)
    assert mem.add_lesson("NONEXIST", "lesson") is False


# ── BM25 search ─────────────────────────────────────────────────


def test_find_similar_empty(tmp_path):
    mem, _ = _make_memory(tmp_path)
    results = mem.find_similar_for_signal(
        ticker="NSE:RELIANCE", direction="BUY", pattern="RRMS",
        rrr=2.0, confidence=65,
    )
    assert results == []


def test_find_similar_returns_results(tmp_path):
    mem, _ = _make_memory(tmp_path)
    # Add several trades with different tickers/directions
    mem.add_record(_sample_record("S001", "NSE:RELIANCE", "BUY", 70))
    mem.add_record(_sample_record("S002", "NSE:TCS", "SELL", 45))
    mem.add_record(_sample_record("S003", "NSE:RELIANCE", "BUY", 60))
    mem.add_record(_sample_record("S004", "MCX:GOLD", "BUY", 80))

    # Search for something similar to RELIANCE BUY
    results = mem.find_similar_for_signal(
        ticker="NSE:RELIANCE", direction="BUY", pattern="RRMS",
        rrr=2.0, confidence=65, top_k=4,
    )
    # Should return at least some results (BM25 scores > 0)
    assert len(results) > 0
    # All results should have the expected fields
    for r in results:
        assert "signal_id" in r
        assert "ticker" in r
        assert "similarity" in r


def test_find_similar_respects_top_k(tmp_path):
    mem, _ = _make_memory(tmp_path)
    for i in range(10):
        mem.add_record(_sample_record(f"S{i:03d}", "NSE:RELIANCE", "BUY", 50 + i))

    results = mem.find_similar_for_signal(
        ticker="NSE:RELIANCE", direction="BUY", pattern="RRMS",
        rrr=2.0, top_k=3,
    )
    assert len(results) <= 3


# ── Stats ────────────────────────────────────────────────────────


def test_stats_with_outcomes(tmp_path):
    mem, _ = _make_memory(tmp_path)
    mem.add_record(_sample_record("S001"))
    mem.add_record(_sample_record("S002"))
    mem.add_record(_sample_record("S003"))

    mem.update_outcome("S001", "WIN", pnl_pct=5.0)
    mem.update_outcome("S002", "LOSS", pnl_pct=-2.0)

    stats = mem.get_stats()
    assert stats["total"] == 3
    assert stats["with_outcome"] == 2
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["win_rate"] == 50.0


def test_get_unreflected_trades(tmp_path):
    mem, _ = _make_memory(tmp_path)
    mem.add_record(_sample_record("S001"))
    mem.add_record(_sample_record("S002"))
    mem.update_outcome("S001", "WIN")
    mem.update_outcome("S002", "LOSS")
    mem.add_lesson("S001", "some lesson")  # S001 is now reflected

    unreflected = mem.get_unreflected_trades()
    assert len(unreflected) == 1
    assert unreflected[0].signal_id == "S002"


def test_get_record_by_id(tmp_path):
    mem, _ = _make_memory(tmp_path)
    mem.add_record(_sample_record("S001"))
    assert mem.get_record_by_id("S001") is not None
    assert mem.get_record_by_id("NONEXIST") is None


# ── BM25 missing fallback ───────────────────────────────────────


def test_bm25_missing_fallback(tmp_path, monkeypatch):
    """When BM25 is not available, search returns empty list."""
    import mcp_server.trade_memory as tm_module
    monkeypatch.setattr(tm_module, "_HAS_BM25", False)

    mem, _ = _make_memory(tmp_path)
    mem.add_record(_sample_record("S001"))

    results = mem.find_similar_for_signal(
        ticker="NSE:RELIANCE", direction="BUY", pattern="RRMS", rrr=2.0,
    )
    assert results == []
