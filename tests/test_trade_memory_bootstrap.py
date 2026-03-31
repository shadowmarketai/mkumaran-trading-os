"""Tests for trade memory bootstrap — seed trades, BM25 cold start."""

import os
import json
import tempfile
import pytest

from mcp_server.trade_memory import (
    TradeMemory,
    TradeRecord,
    _generate_seed_trades,
)


@pytest.fixture
def temp_memory():
    """TradeMemory with a temp file."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # Start with no file
    mem = TradeMemory(filepath=path)
    yield mem
    # Cleanup
    if os.path.exists(path):
        os.unlink(path)


# ── Seed Trade Generation ────────────────────────────────────

class TestSeedTradeGeneration:
    def test_generates_50_trades(self):
        seeds = _generate_seed_trades()
        assert len(seeds) == 50

    def test_all_have_outcomes(self):
        seeds = _generate_seed_trades()
        for trade in seeds:
            assert trade.outcome in ("WIN", "LOSS", "BREAKEVEN")

    def test_all_have_lessons(self):
        seeds = _generate_seed_trades()
        for trade in seeds:
            assert len(trade.lesson) > 10

    def test_all_reflected(self):
        seeds = _generate_seed_trades()
        for trade in seeds:
            assert trade.reflected is True

    def test_realistic_win_rate(self):
        seeds = _generate_seed_trades()
        wins = sum(1 for t in seeds if t.outcome == "WIN")
        breakevens = sum(1 for t in seeds if t.outcome == "BREAKEVEN")
        # Expect roughly 55-65% wins
        win_rate = wins / len(seeds) * 100
        assert 50 <= win_rate <= 70, f"Win rate {win_rate}% out of expected range"
        assert breakevens >= 3  # At least a few breakevens

    def test_diverse_exchanges(self):
        seeds = _generate_seed_trades()
        exchanges = set(t.exchange for t in seeds)
        assert "NSE" in exchanges
        assert "MCX" in exchanges
        assert "CDS" in exchanges
        assert "NFO" in exchanges

    def test_diverse_patterns(self):
        seeds = _generate_seed_trades()
        patterns = set(t.pattern for t in seeds)
        assert len(patterns) >= 8  # At least 8 different patterns

    def test_diverse_directions(self):
        seeds = _generate_seed_trades()
        longs = sum(1 for t in seeds if t.direction == "BUY")
        shorts = sum(1 for t in seeds if t.direction == "SELL")
        assert longs >= 30  # Majority longs (realistic for Indian market)
        assert shorts >= 5  # Some shorts

    def test_confidence_range(self):
        seeds = _generate_seed_trades()
        confs = [t.confidence for t in seeds]
        assert min(confs) >= 50
        assert max(confs) <= 85

    def test_unique_signal_ids(self):
        seeds = _generate_seed_trades()
        ids = [t.signal_id for t in seeds]
        assert len(ids) == len(set(ids))  # All unique


# ── Bootstrap Function ───────────────────────────────────────

class TestBootstrap:
    def test_bootstrap_on_empty_memory(self, temp_memory):
        count = temp_memory.bootstrap_seed_trades()
        assert count == 50
        assert len(temp_memory._records) == 50

    def test_bootstrap_skips_if_already_populated(self, temp_memory):
        # Add 10 dummy records
        for i in range(10):
            temp_memory.add_record(TradeRecord(
                signal_id=f"EXISTING-{i}",
                ticker=f"NSE:TEST{i}",
                direction="BUY",
                pattern="test",
                entry_price=100,
                stop_loss=90,
                target=130,
                rrr=3.0,
                confidence=60,
                recommendation="WATCHLIST",
            ))
        count = temp_memory.bootstrap_seed_trades()
        assert count == 0  # Should skip
        assert len(temp_memory._records) == 10  # No seeds added

    def test_bootstrap_persists_to_file(self, temp_memory):
        temp_memory.bootstrap_seed_trades()
        # Verify file was written
        assert os.path.exists(temp_memory._filepath)
        with open(temp_memory._filepath) as f:
            data = json.load(f)
        assert len(data) == 50

    def test_bm25_works_after_bootstrap(self, temp_memory):
        temp_memory.bootstrap_seed_trades()
        # Search for similar trades
        results = temp_memory.find_similar_for_signal(
            ticker="NSE:RELIANCE",
            direction="BUY",
            pattern="breakout_volume",
            rrr=3.0,
            confidence=70,
            exchange="NSE",
        )
        assert len(results) > 0
        # First result should be RELIANCE breakout (exact match)
        assert results[0]["ticker"] == "NSE:RELIANCE"

    def test_bm25_finds_pattern_matches(self, temp_memory):
        temp_memory.bootstrap_seed_trades()
        results = temp_memory.find_similar_for_signal(
            ticker="NSE:SUNPHARMA",
            direction="BUY",
            pattern="harmonic_bat",
            rrr=3.0,
            confidence=65,
            exchange="NSE",
        )
        assert len(results) > 0
        # Should find harmonic pattern trades
        patterns = [r["pattern"] for r in results]
        assert any("harmonic" in p for p in patterns)

    def test_bm25_finds_mcx_trades(self, temp_memory):
        temp_memory.bootstrap_seed_trades()
        results = temp_memory.find_similar_for_signal(
            ticker="MCX:SILVER",
            direction="BUY",
            pattern="smc_bos",
            rrr=2.5,
            confidence=65,
            exchange="MCX",
        )
        assert len(results) > 0

    def test_stats_after_bootstrap(self, temp_memory):
        temp_memory.bootstrap_seed_trades()
        stats = temp_memory.get_stats()
        assert stats["total"] == 50
        assert stats["with_outcome"] == 50  # All seeds have outcomes
        assert stats["reflected"] == 50  # All seeds are reflected
        assert stats["win_rate"] > 0
