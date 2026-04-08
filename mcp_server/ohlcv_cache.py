"""
OHLCV Cache — PostgreSQL persistence layer for market data.

Eliminates duplicate API calls for the same ticker+interval+period.
SaaS-ready with tenant_id column for future multi-tenant support.

Usage:
    from mcp_server.ohlcv_cache import check_cache, store_cache
    df = check_cache("NSE:RELIANCE", "1y", "1d", session)
    if df is None:
        df = fetch_from_api(...)
        store_cache("NSE:RELIANCE", "1d", df, "yfinance", session)
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from mcp_server.models import OHLCVCache

logger = logging.getLogger(__name__)

# ── In-memory hit/miss counters ──────────────────────────────

_cache_hits = 0
_cache_misses = 0

# ── Period → lookback days ───────────────────────────────────

_PERIOD_TO_DAYS: dict[str, int] = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}

# ── Daily intervals (staleness uses market-open logic) ───────

_DAILY_INTERVALS = {"1d", "1wk", "1mo", "day", "week", "month"}


def check_cache(
    ticker: str,
    period: str,
    interval: str,
    session: Session,
) -> pd.DataFrame | None:
    """
    Query ohlcv_cache for cached bars.

    Returns DataFrame with [open, high, low, close, volume] if cache is
    fresh, None if stale or missing.
    """
    global _cache_hits, _cache_misses

    days = _PERIOD_TO_DAYS.get(period)
    if days is None:
        _cache_misses += 1
        return None

    cutoff = datetime.now() - timedelta(days=days)
    exchange = ticker.split(":")[0] if ":" in ticker else "NSE"

    # MCX/NFO must NEVER be served from yfinance cache — those rows were
    # stored back when resolve_yf_symbol() mapped CRUDEOIL→CL=F (NYMEX WTI,
    # USD/barrel) etc., and the prices are globally-denominated garbage
    # for MCX FUTCOM lookups. Reject them here so a re-fetch hits real
    # broker sources.
    source_filter = None
    if exchange in ("MCX", "NFO"):
        source_filter = OHLCVCache.source != "yfinance"

    query = session.query(OHLCVCache).filter(
        OHLCVCache.ticker == ticker,
        OHLCVCache.interval == interval,
        OHLCVCache.bar_date >= cutoff,
    )
    if source_filter is not None:
        query = query.filter(source_filter)
    rows = query.order_by(OHLCVCache.bar_date).all()

    if not rows:
        _cache_misses += 1
        return None

    # Check staleness of most recent row
    latest = rows[-1]
    if not _is_cache_fresh(latest.fetched_at, interval, exchange):
        _cache_misses += 1
        return None

    # Minimum bar count check — require at least 60% of expected bars
    expected_bars = max(1, days * 0.6) if interval in _DAILY_INTERVALS else max(1, days * 0.3)
    if len(rows) < expected_bars:
        _cache_misses += 1
        return None

    # Build DataFrame
    data = {
        "open": [float(r.open) for r in rows],
        "high": [float(r.high) for r in rows],
        "low": [float(r.low) for r in rows],
        "close": [float(r.close) for r in rows],
        "volume": [float(r.volume) for r in rows],
    }
    index = [r.bar_date for r in rows]
    df = pd.DataFrame(data, index=pd.DatetimeIndex(index))

    _cache_hits += 1
    logger.info(
        "Cache HIT: %s %s %s — %d bars",
        ticker, interval, period, len(df),
    )
    return df


def store_cache(
    ticker: str,
    interval: str,
    df: pd.DataFrame,
    source: str,
    session: Session,
) -> int:
    """
    Bulk upsert OHLCV bars into the cache.

    Uses PostgreSQL INSERT ON CONFLICT for bulk speed.
    Falls back to per-row merge for SQLite (tests).

    Returns number of rows upserted.
    """
    if df is None or df.empty:
        return 0

    exchange = ticker.split(":")[0] if ":" in ticker else "NSE"
    now = datetime.now()
    dialect = session.bind.dialect.name if session.bind else "sqlite"

    count = 0

    if dialect == "postgresql":
        count = _store_pg(ticker, exchange, interval, df, source, now, session)
    else:
        count = _store_sqlite(ticker, exchange, interval, df, source, now, session)

    session.commit()
    logger.info(
        "Cache STORE: %s %s — %d bars (%s, %s)",
        ticker, interval, count, source, dialect,
    )
    return count


def _store_pg(
    ticker: str,
    exchange: str,
    interval: str,
    df: pd.DataFrame,
    source: str,
    now: datetime,
    session: Session,
) -> int:
    """PostgreSQL bulk upsert using INSERT ON CONFLICT."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    rows_to_insert = []
    for idx, row in df.iterrows():
        bar_date = _normalize_bar_date(idx)
        rows_to_insert.append({
            "ticker": ticker,
            "exchange": exchange,
            "interval": interval,
            "bar_date": bar_date,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "source": source,
            "fetched_at": now,
        })

    # Batch in chunks of 500
    count = 0
    for i in range(0, len(rows_to_insert), 500):
        batch = rows_to_insert[i:i + 500]
        stmt = pg_insert(OHLCVCache).values(batch)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ohlcv_ticker_interval_bardate",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "source": stmt.excluded.source,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        session.execute(stmt)
        count += len(batch)

    return count


def _store_sqlite(
    ticker: str,
    exchange: str,
    interval: str,
    df: pd.DataFrame,
    source: str,
    now: datetime,
    session: Session,
) -> int:
    """SQLite per-row select-then-update-or-insert (test-only path)."""
    count = 0
    for idx, row in df.iterrows():
        bar_date = _normalize_bar_date(idx)
        existing = (
            session.query(OHLCVCache)
            .filter(
                OHLCVCache.ticker == ticker,
                OHLCVCache.interval == interval,
                OHLCVCache.bar_date == bar_date,
            )
            .first()
        )

        if existing:
            existing.open = float(row["open"])
            existing.high = float(row["high"])
            existing.low = float(row["low"])
            existing.close = float(row["close"])
            existing.volume = float(row["volume"])
            existing.source = source
            existing.fetched_at = now
        else:
            session.add(OHLCVCache(
                ticker=ticker,
                exchange=exchange,
                interval=interval,
                bar_date=bar_date,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                source=source,
                fetched_at=now,
            ))
        count += 1

    return count


def _normalize_bar_date(idx) -> datetime:
    """Strip timezone from bar_date (yfinance returns tz-aware, Kite returns naive)."""
    if isinstance(idx, pd.Timestamp):
        return idx.to_pydatetime().replace(tzinfo=None)
    if isinstance(idx, datetime):
        return idx.replace(tzinfo=None)
    return datetime.fromisoformat(str(idx)).replace(tzinfo=None)


def _is_cache_fresh(
    fetched_at: datetime,
    interval: str,
    exchange: str,
) -> bool:
    """
    Determine if cached data is still fresh.

    Daily bars: fresh if fetched after today's market open (9:15 IST for NSE).
    On weekends/holidays: use TTL-based check.
    Intraday bars: fresh if fetched within TTL minutes of now.
    """
    from mcp_server.config import settings

    now = datetime.now()

    if fetched_at is None:
        return False

    if interval in _DAILY_INTERVALS:
        # Import market calendar for smart staleness
        try:
            from mcp_server.market_calendar import is_market_open, EXCHANGE_HOURS

            hours = EXCHANGE_HOURS.get(exchange.upper(), EXCHANGE_HOURS.get("NSE"))
            if hours:
                market_open_time = hours[0]
                today_open = datetime.combine(now.date(), market_open_time)

                # If market is currently open or was open today, require fetch after today's open
                if is_market_open(exchange, now) or now > today_open:
                    return fetched_at >= today_open

            # Weekend/holiday: use TTL
        except Exception:
            pass

        ttl_hours = settings.OHLCV_CACHE_DAILY_TTL_HOURS
        return (now - fetched_at).total_seconds() < ttl_hours * 3600

    else:
        # Intraday: TTL-based
        ttl_minutes = settings.OHLCV_CACHE_INTRADAY_TTL_MINUTES
        return (now - fetched_at).total_seconds() < ttl_minutes * 60


def purge_old_data(session: Session, days_to_keep: int = 1825) -> int:
    """Delete cached bars older than days_to_keep (default 5 years)."""
    cutoff = datetime.now() - timedelta(days=days_to_keep)
    result = session.execute(
        delete(OHLCVCache).where(OHLCVCache.bar_date < cutoff)
    )
    session.commit()
    count = result.rowcount
    logger.info("Cache PURGE: deleted %d rows older than %s", count, cutoff.date())
    return count


def invalidate_ticker(
    session: Session,
    ticker: str,
    interval: str | None = None,
) -> int:
    """Delete cached data for a specific ticker (optionally specific interval)."""
    stmt = delete(OHLCVCache).where(OHLCVCache.ticker == ticker)
    if interval:
        stmt = stmt.where(OHLCVCache.interval == interval)

    result = session.execute(stmt)
    session.commit()
    count = result.rowcount
    logger.info("Cache INVALIDATE: %s %s — %d rows deleted", ticker, interval or "*", count)
    return count


def purge_yfinance_mcx_nfo(session: Session) -> int:
    """One-shot cleanup: drop all yfinance-sourced MCX/NFO rows.

    These rows hold global proxy prices (CL=F for CRUDEOIL, GC=F for GOLD,
    etc.) instead of real MCX FUTCOM INR prices. After this purge, the
    next data fetch will hit broker sources (gwc/angel/kite) and store
    correct values. Safe to call repeatedly on startup.
    """
    result = session.execute(
        delete(OHLCVCache).where(
            OHLCVCache.exchange.in_(["MCX", "NFO"]),
            OHLCVCache.source == "yfinance",
        )
    )
    session.commit()
    count = result.rowcount or 0
    if count:
        logger.info(
            "Cache PURGE yfinance MCX/NFO: deleted %d stale rows", count,
        )
    return count


def get_cache_stats(session: Session) -> dict:
    """Return cache statistics: total rows, unique tickers, hit rate, etc."""
    global _cache_hits, _cache_misses

    total_rows = session.query(func.count(OHLCVCache.id)).scalar() or 0
    unique_tickers = session.query(func.count(func.distinct(OHLCVCache.ticker))).scalar() or 0

    # Interval breakdown
    interval_counts = (
        session.query(OHLCVCache.interval, func.count(OHLCVCache.id))
        .group_by(OHLCVCache.interval)
        .all()
    )

    # Oldest / newest bar
    oldest = session.query(func.min(OHLCVCache.bar_date)).scalar()
    newest = session.query(func.max(OHLCVCache.bar_date)).scalar()

    total_requests = _cache_hits + _cache_misses
    hit_rate = round(_cache_hits / total_requests * 100, 1) if total_requests > 0 else 0.0

    return {
        "total_rows": total_rows,
        "unique_tickers": unique_tickers,
        "intervals": {iv: cnt for iv, cnt in interval_counts},
        "oldest_bar": str(oldest) if oldest else None,
        "newest_bar": str(newest) if newest else None,
        "cache_hits": _cache_hits,
        "cache_misses": _cache_misses,
        "hit_rate_pct": hit_rate,
    }


def reset_counters() -> None:
    """Reset hit/miss counters (used in tests)."""
    global _cache_hits, _cache_misses
    _cache_hits = 0
    _cache_misses = 0
