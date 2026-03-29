"""
Tests for OHLCV Cache Layer.

Covers: check_cache, store_cache, _is_cache_fresh, purge_old_data,
invalidate_ticker, get_cache_stats, dialect detection, and
get_stock_data cache integration.
"""

import os
import pytest
from datetime import datetime, timedelta, time
from unittest.mock import patch, MagicMock

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use SQLite for tests
os.environ["DATABASE_URL"] = "sqlite:///test_trading.db"

from mcp_server.db import Base  # noqa: E402
from mcp_server.models import OHLCVCache  # noqa: E402
from mcp_server.ohlcv_cache import (  # noqa: E402
    check_cache,
    store_cache,
    _is_cache_fresh,
    _normalize_bar_date,
    purge_old_data,
    invalidate_ticker,
    get_cache_stats,
    reset_counters,
    _DAILY_INTERVALS,
)

TEST_DB_URL = "sqlite:///test_ohlcv_cache.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_ohlcv_db():
    """Create tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    reset_counters()
    yield
    Base.metadata.drop_all(bind=engine, checkfirst=True)


@pytest.fixture
def db():
    """Provide a test session."""
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def _make_df(bars: int = 250, start_date: str = "2025-04-01") -> pd.DataFrame:
    """Create a sample OHLCV DataFrame."""
    dates = pd.date_range(start=start_date, periods=bars, freq="B")
    return pd.DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(bars)],
            "high": [101.0 + i * 0.1 for i in range(bars)],
            "low": [99.0 + i * 0.1 for i in range(bars)],
            "close": [100.5 + i * 0.1 for i in range(bars)],
            "volume": [1000000 + i * 100 for i in range(bars)],
        },
        index=dates,
    )


# ── store_cache tests ────────────────────────────────────────


def test_store_cache_basic(db):
    """Store a DataFrame and verify row count."""
    df = _make_df(bars=10)
    count = store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)
    assert count == 10

    rows = db.query(OHLCVCache).all()
    assert len(rows) == 10


def test_store_cache_empty_df(db):
    """Storing empty DataFrame returns 0."""
    count = store_cache("NSE:RELIANCE", "1d", pd.DataFrame(), "yfinance", db)
    assert count == 0


def test_store_cache_none_df(db):
    """Storing None returns 0."""
    count = store_cache("NSE:RELIANCE", "1d", None, "yfinance", db)
    assert count == 0


def test_store_cache_upsert(db):
    """Storing same ticker+interval+bar_date updates rather than duplicating."""
    df = _make_df(bars=5)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)

    # Modify close prices and re-store
    df["close"] = df["close"] + 10.0
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)

    rows = db.query(OHLCVCache).all()
    assert len(rows) == 5  # No duplicates
    # Verify updated values
    assert float(rows[0].close) == pytest.approx(110.5, abs=0.1)


def test_store_cache_sets_exchange(db):
    """Exchange is extracted from ticker prefix."""
    df = _make_df(bars=3)
    store_cache("MCX:GOLD", "1d", df, "yfinance", db)

    row = db.query(OHLCVCache).first()
    assert row.exchange == "MCX"
    assert row.ticker == "MCX:GOLD"


def test_store_cache_sets_source(db):
    """Source field is correctly stored."""
    df = _make_df(bars=3)
    store_cache("NSE:TCS", "1d", df, "kite", db)

    row = db.query(OHLCVCache).first()
    assert row.source == "kite"


def test_store_cache_different_intervals(db):
    """Different intervals for same ticker create separate rows."""
    df = _make_df(bars=5)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)
    store_cache("NSE:RELIANCE", "1h", df, "yfinance", db)

    total = db.query(OHLCVCache).count()
    assert total == 10


# ── check_cache tests ────────────────────────────────────────


def test_check_cache_miss_empty(db):
    """Cache miss on empty DB returns None."""
    result = check_cache("NSE:RELIANCE", "1y", "1d", db)
    assert result is None


def test_check_cache_hit(db):
    """Cache hit returns DataFrame with correct shape."""
    df = _make_df(bars=250)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)

    # Patch freshness to always return True
    with patch("mcp_server.ohlcv_cache._is_cache_fresh", return_value=True):
        result = check_cache("NSE:RELIANCE", "1y", "1d", db)

    assert result is not None
    assert len(result) == 250
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]


def test_check_cache_stale_returns_none(db):
    """Stale cache returns None."""
    df = _make_df(bars=250)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)

    with patch("mcp_server.ohlcv_cache._is_cache_fresh", return_value=False):
        result = check_cache("NSE:RELIANCE", "1y", "1d", db)

    assert result is None


def test_check_cache_wrong_ticker(db):
    """Different ticker returns None."""
    df = _make_df(bars=250)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)

    with patch("mcp_server.ohlcv_cache._is_cache_fresh", return_value=True):
        result = check_cache("NSE:TCS", "1y", "1d", db)

    assert result is None


def test_check_cache_wrong_interval(db):
    """Different interval returns None."""
    df = _make_df(bars=250)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)

    with patch("mcp_server.ohlcv_cache._is_cache_fresh", return_value=True):
        result = check_cache("NSE:RELIANCE", "1y", "1h", db)

    assert result is None


def test_check_cache_too_few_bars(db):
    """Insufficient bar count returns None (60% threshold for daily)."""
    df = _make_df(bars=50)  # < 60% of 365
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)

    with patch("mcp_server.ohlcv_cache._is_cache_fresh", return_value=True):
        result = check_cache("NSE:RELIANCE", "1y", "1d", db)

    assert result is None


def test_check_cache_unsupported_period(db):
    """Unsupported period returns None."""
    result = check_cache("NSE:RELIANCE", "10y", "1d", db)
    assert result is None


# ── _is_cache_fresh tests ────────────────────────────────────


def test_is_cache_fresh_none_fetched_at():
    """None fetched_at is never fresh."""
    assert _is_cache_fresh(None, "1d", "NSE") is False


def test_is_cache_fresh_daily_recent():
    """Daily data fetched recently within TTL is fresh."""
    with patch("mcp_server.config.settings.OHLCV_CACHE_DAILY_TTL_HOURS", 12):
        fetched = datetime.now() - timedelta(hours=2)
        assert _is_cache_fresh(fetched, "1d", "NSE") is True


def test_is_cache_fresh_daily_stale():
    """Daily data fetched long ago is stale."""
    with patch("mcp_server.config.settings.OHLCV_CACHE_DAILY_TTL_HOURS", 12):
        fetched = datetime.now() - timedelta(hours=24)
        assert _is_cache_fresh(fetched, "1d", "NSE") is False


def test_is_cache_fresh_intraday_recent():
    """Intraday data fetched within TTL is fresh."""
    with patch("mcp_server.config.settings.OHLCV_CACHE_INTRADAY_TTL_MINUTES", 5):
        fetched = datetime.now() - timedelta(minutes=2)
        assert _is_cache_fresh(fetched, "15m", "NSE") is True


def test_is_cache_fresh_intraday_stale():
    """Intraday data fetched beyond TTL is stale."""
    with patch("mcp_server.config.settings.OHLCV_CACHE_INTRADAY_TTL_MINUTES", 5):
        fetched = datetime.now() - timedelta(minutes=10)
        assert _is_cache_fresh(fetched, "15m", "NSE") is False


# ── _normalize_bar_date tests ────────────────────────────────


def test_normalize_tz_aware_timestamp():
    """Timezone-aware Timestamp is converted to naive datetime."""
    ts = pd.Timestamp("2025-06-15 09:15:00", tz="Asia/Kolkata")
    result = _normalize_bar_date(ts)
    assert result.tzinfo is None
    assert result.year == 2025


def test_normalize_naive_datetime():
    """Naive datetime passes through."""
    dt = datetime(2025, 6, 15, 9, 15)
    result = _normalize_bar_date(dt)
    assert result == dt
    assert result.tzinfo is None


def test_normalize_naive_timestamp():
    """Naive pandas Timestamp is converted."""
    ts = pd.Timestamp("2025-06-15")
    result = _normalize_bar_date(ts)
    assert isinstance(result, datetime)
    assert result.tzinfo is None


# ── purge_old_data tests ─────────────────────────────────────


def test_purge_old_data(db):
    """Purge removes bars older than cutoff."""
    # Insert old bars
    old_date = datetime.now() - timedelta(days=2000)
    db.add(OHLCVCache(
        ticker="NSE:OLD", exchange="NSE", interval="1d",
        bar_date=old_date, open=100, high=101, low=99, close=100.5,
        volume=1000000, source="yfinance", fetched_at=old_date,
    ))
    # Insert recent bar
    db.add(OHLCVCache(
        ticker="NSE:NEW", exchange="NSE", interval="1d",
        bar_date=datetime.now() - timedelta(days=10),
        open=200, high=201, low=199, close=200.5,
        volume=2000000, source="yfinance", fetched_at=datetime.now(),
    ))
    db.commit()

    deleted = purge_old_data(db, days_to_keep=1825)
    assert deleted == 1

    remaining = db.query(OHLCVCache).count()
    assert remaining == 1


def test_purge_nothing_to_delete(db):
    """Purge on empty table returns 0."""
    deleted = purge_old_data(db, days_to_keep=1825)
    assert deleted == 0


# ── invalidate_ticker tests ──────────────────────────────────


def test_invalidate_ticker_all_intervals(db):
    """Invalidate removes all intervals for a ticker."""
    df = _make_df(bars=5)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)
    store_cache("NSE:RELIANCE", "1h", df, "yfinance", db)

    deleted = invalidate_ticker(db, "NSE:RELIANCE")
    assert deleted == 10

    remaining = db.query(OHLCVCache).count()
    assert remaining == 0


def test_invalidate_ticker_specific_interval(db):
    """Invalidate with interval only removes that interval."""
    df = _make_df(bars=5)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)
    store_cache("NSE:RELIANCE", "1h", df, "yfinance", db)

    deleted = invalidate_ticker(db, "NSE:RELIANCE", interval="1d")
    assert deleted == 5

    remaining = db.query(OHLCVCache).count()
    assert remaining == 5


def test_invalidate_nonexistent_ticker(db):
    """Invalidating a ticker not in cache returns 0."""
    deleted = invalidate_ticker(db, "NSE:GHOST")
    assert deleted == 0


# ── get_cache_stats tests ────────────────────────────────────


def test_cache_stats_empty(db):
    """Stats on empty cache."""
    reset_counters()
    stats = get_cache_stats(db)
    assert stats["total_rows"] == 0
    assert stats["unique_tickers"] == 0
    assert stats["hit_rate_pct"] == 0.0


def test_cache_stats_populated(db):
    """Stats reflect stored data."""
    df = _make_df(bars=10)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)
    store_cache("NSE:TCS", "1d", df, "kite", db)

    stats = get_cache_stats(db)
    assert stats["total_rows"] == 20
    assert stats["unique_tickers"] == 2
    assert "1d" in stats["intervals"]


def test_cache_stats_hit_rate(db):
    """Hit rate tracks hits and misses."""
    reset_counters()
    df = _make_df(bars=250)
    store_cache("NSE:RELIANCE", "1d", df, "yfinance", db)

    # Generate a miss
    check_cache("NSE:TCS", "1y", "1d", db)

    # Generate a hit
    with patch("mcp_server.ohlcv_cache._is_cache_fresh", return_value=True):
        check_cache("NSE:RELIANCE", "1y", "1d", db)

    stats = get_cache_stats(db)
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 1
    assert stats["hit_rate_pct"] == 50.0


# ── Daily intervals constant test ────────────────────────────


def test_daily_intervals_set():
    """Verify the daily intervals set contains expected values."""
    assert "1d" in _DAILY_INTERVALS
    assert "1wk" in _DAILY_INTERVALS
    assert "1mo" in _DAILY_INTERVALS
    assert "15m" not in _DAILY_INTERVALS


# ── OHLCVCache model tests ───────────────────────────────────


def test_ohlcv_model_repr(db):
    """Model __repr__ works."""
    row = OHLCVCache(
        ticker="NSE:RELIANCE", exchange="NSE", interval="1d",
        bar_date=datetime(2025, 6, 15), open=100, high=101,
        low=99, close=100.5, volume=1000000, source="yfinance",
        fetched_at=datetime.now(),
    )
    db.add(row)
    db.commit()

    result = repr(row)
    assert "NSE:RELIANCE" in result
    assert "1d" in result
