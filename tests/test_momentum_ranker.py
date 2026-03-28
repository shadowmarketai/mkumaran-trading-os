"""Tests for momentum_ranker.py — score calculation, ranking, rebalance signals, persistence."""

import json
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime

from mcp_server.momentum_ranker import (
    calculate_momentum_score,
    _min_max_normalize,
    rank_universe,
    generate_rebalance_signals,
    get_momentum_portfolio,
    save_momentum_portfolio,
    MomentumStock,
    RebalanceSignal,
    MomentumPortfolio,
    PORTFOLIO_FILE,
)


# ── Helpers ─────────────────────────────────────────────────

def _make_ohlcv(n_days: int = 252, start_price: float = 100.0, trend: float = 0.001) -> pd.DataFrame:
    """Create synthetic OHLCV DataFrame with controlled trend."""
    dates = pd.date_range(end=datetime.now(), periods=n_days, freq="B")
    np.random.seed(42)
    close = [start_price]
    for _ in range(n_days - 1):
        close.append(close[-1] * (1 + trend + np.random.normal(0, 0.015)))
    close = np.array(close)
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": np.random.randint(100000, 1000000, size=n_days),
    }, index=dates)


# ── Min-Max Normalize ───────────────────────────────────────

class TestMinMaxNormalize:
    def test_basic_normalize(self):
        result = _min_max_normalize([10, 20, 30])
        assert result == [0.0, 0.5, 1.0]

    def test_constant_values(self):
        result = _min_max_normalize([5, 5, 5])
        assert result == [0.0, 0.0, 0.0]

    def test_empty_list(self):
        assert _min_max_normalize([]) == []

    def test_two_values(self):
        result = _min_max_normalize([0, 100])
        assert result == [0.0, 1.0]


# ── Score Calculation ───────────────────────────────────────

class TestCalculateMomentumScore:
    @patch("mcp_server.momentum_ranker.get_stock_data")
    def test_valid_stock(self, mock_get_data):
        mock_get_data.return_value = _make_ohlcv(252, start_price=100, trend=0.002)
        result = calculate_momentum_score("RELIANCE")
        assert result is not None
        assert result["ticker"] == "RELIANCE"
        assert "ret_3m" in result
        assert "ret_6m" in result
        assert "ret_12m" in result
        assert "volatility" in result
        assert result["volatility"] > 0

    @patch("mcp_server.momentum_ranker.get_stock_data")
    def test_insufficient_data(self, mock_get_data):
        mock_get_data.return_value = _make_ohlcv(30)  # too few bars
        result = calculate_momentum_score("SMALLCO")
        assert result is None

    @patch("mcp_server.momentum_ranker.get_stock_data")
    def test_empty_data(self, mock_get_data):
        mock_get_data.return_value = pd.DataFrame()
        result = calculate_momentum_score("NODATA")
        assert result is None

    @patch("mcp_server.momentum_ranker.get_stock_data")
    def test_positive_trend_returns(self, mock_get_data):
        mock_get_data.return_value = _make_ohlcv(252, start_price=100, trend=0.003)
        result = calculate_momentum_score("UPMOVER")
        assert result is not None
        assert result["ret_12m"] > 0
        assert result["ret_6m"] > 0
        assert result["ret_3m"] > 0


# ── Rank Universe ───────────────────────────────────────────

class TestRankUniverse:
    @patch("mcp_server.momentum_ranker.get_momentum_portfolio")
    @patch("mcp_server.momentum_ranker.get_stock_data")
    @patch("mcp_server.momentum_ranker._get_nse_universe")
    def test_ranking_order(self, mock_universe, mock_get_data, mock_portfolio):
        """Top-scoring stock should rank #1."""
        mock_universe.return_value = ["FAST", "SLOW", "MID"]
        mock_portfolio.return_value = None

        # FAST: highest returns, SLOW: lowest, MID: middle
        def side_effect(ticker, **kwargs):
            if ticker == "FAST":
                return _make_ohlcv(252, start_price=100, trend=0.004)
            elif ticker == "SLOW":
                return _make_ohlcv(252, start_price=100, trend=0.0005)
            else:
                return _make_ohlcv(252, start_price=100, trend=0.002)

        mock_get_data.side_effect = side_effect
        result = rank_universe(top_n=3)
        assert len(result) == 3
        assert result[0].rank == 1
        assert result[0].ticker == "FAST"
        assert result[2].ticker == "SLOW"
        assert result[0].score >= result[1].score >= result[2].score

    @patch("mcp_server.momentum_ranker.get_momentum_portfolio")
    @patch("mcp_server.momentum_ranker.get_stock_data")
    @patch("mcp_server.momentum_ranker._get_nse_universe")
    def test_top_n_limit(self, mock_universe, mock_get_data, mock_portfolio):
        mock_universe.return_value = ["A", "B", "C", "D", "E"]
        mock_portfolio.return_value = None
        mock_get_data.return_value = _make_ohlcv(252)
        result = rank_universe(top_n=2)
        assert len(result) == 2

    @patch("mcp_server.momentum_ranker.get_momentum_portfolio")
    @patch("mcp_server.momentum_ranker.get_stock_data")
    @patch("mcp_server.momentum_ranker._get_nse_universe")
    def test_all_failures_returns_empty(self, mock_universe, mock_get_data, mock_portfolio):
        mock_universe.return_value = ["FAIL1", "FAIL2"]
        mock_portfolio.return_value = None
        mock_get_data.return_value = pd.DataFrame()
        result = rank_universe(top_n=10)
        assert result == []


# ── Rebalance Signals ───────────────────────────────────────

class TestRebalanceSignals:
    def test_buy_and_sell(self):
        rankings = [
            MomentumStock(rank=1, ticker="NEW1", sector="IT", score=0.9, ret_3m=10, ret_6m=20, ret_12m=30, volatility=20),
            MomentumStock(rank=2, ticker="KEEP", sector="ENERGY", score=0.8, ret_3m=8, ret_6m=15, ret_12m=25, volatility=22),
        ]
        current = ["KEEP", "OLD1"]
        signals = generate_rebalance_signals(current, rankings, top_n=2)

        actions = {s.ticker: s.action for s in signals}
        assert actions["NEW1"] == "BUY"
        assert actions["OLD1"] == "SELL"
        assert "KEEP" not in actions  # retained, no signal

    def test_no_changes(self):
        rankings = [
            MomentumStock(rank=1, ticker="A", sector="IT", score=0.9, ret_3m=10, ret_6m=20, ret_12m=30, volatility=20),
            MomentumStock(rank=2, ticker="B", sector="ENERGY", score=0.8, ret_3m=8, ret_6m=15, ret_12m=25, volatility=22),
        ]
        current = ["A", "B"]
        signals = generate_rebalance_signals(current, rankings, top_n=2)
        assert signals == []

    def test_empty_portfolio_all_buys(self):
        rankings = [
            MomentumStock(rank=1, ticker="X", sector="IT", score=0.9, ret_3m=10, ret_6m=20, ret_12m=30, volatility=20),
            MomentumStock(rank=2, ticker="Y", sector="PHARMA", score=0.8, ret_3m=8, ret_6m=15, ret_12m=25, volatility=22),
        ]
        signals = generate_rebalance_signals([], rankings, top_n=2)
        assert len(signals) == 2
        assert all(s.action == "BUY" for s in signals)


# ── Portfolio Persistence ───────────────────────────────────

class TestPortfolioPersistence:
    def test_save_and_load(self, tmp_path):
        test_file = tmp_path / "momentum_portfolio.json"
        rankings = [
            MomentumStock(rank=1, ticker="TCS", sector="IT", score=0.95, ret_3m=12, ret_6m=25, ret_12m=50, volatility=18),
        ]
        signals = [
            RebalanceSignal(ticker="TCS", sector="IT", action="BUY", score=0.95, reason="Entered top 10 at rank #1"),
        ]

        with patch("mcp_server.momentum_ranker.PORTFOLIO_FILE", test_file), \
             patch("mcp_server.momentum_ranker.DATA_DIR", tmp_path):
            payload = save_momentum_portfolio(rankings, signals, top_n=10)
            assert "ranked_at" in payload
            assert payload["holdings"] == ["TCS"]

            loaded = get_momentum_portfolio()
            assert loaded is not None
            assert loaded["holdings"] == ["TCS"]
            assert len(loaded["rankings"]) == 1
            assert len(loaded["signals"]) == 1

    def test_load_missing_file(self, tmp_path):
        test_file = tmp_path / "nonexistent.json"
        with patch("mcp_server.momentum_ranker.PORTFOLIO_FILE", test_file):
            result = get_momentum_portfolio()
            assert result is None
