import logging

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Boolean,
    Date,
    Time,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship

try:
    from sqlalchemy.dialects.postgresql import JSONB, ARRAY
except ImportError:
    JSONB = JSON
    ARRAY = None

from mcp_server.db import Base

logger = logging.getLogger(__name__)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False, index=True)
    name = Column(String(50), nullable=True)
    exchange = Column(String(10), default="NSE", index=True)
    asset_class = Column(String(15), default="EQUITY")
    timeframe = Column(String(10), default="day")
    tier = Column(Integer, default=2)
    ltrp = Column(Numeric(10, 2), nullable=True)
    pivot_high = Column(Numeric(10, 2), nullable=True)
    active = Column(Boolean, default=True)
    source = Column(String(20), default="manual")
    added_at = Column(DateTime, server_default=func.now())
    added_by = Column(String(20), default="user")
    notes = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Watchlist(id={self.id}, ticker='{self.ticker}', "
            f"tier={self.tier}, active={self.active})>"
        )


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_date = Column(Date, nullable=False, index=True)
    signal_time = Column(Time, nullable=True)
    ticker = Column(String(20), index=True)
    exchange = Column(String(10), default="NSE")
    asset_class = Column(String(15), default="EQUITY")
    direction = Column(String(10))  # LONG / SHORT
    pattern = Column(String(50))
    entry_price = Column(Numeric(10, 2))
    stop_loss = Column(Numeric(10, 2))
    target = Column(Numeric(10, 2))
    rrr = Column(Numeric(5, 2))
    qty = Column(Integer)
    risk_amt = Column(Numeric(10, 2))
    ai_confidence = Column(Integer)
    tv_confirmed = Column(Boolean, default=False)
    mwa_score = Column(String(10))
    scanner_count = Column(Integer)
    tier = Column(Integer)
    source = Column(String(20))
    timeframe = Column(String(10), default="1D")
    status = Column(String(20), default="OPEN")

    def __repr__(self) -> str:
        return (
            f"<Signal(id={self.id}, ticker='{self.ticker}', "
            f"direction='{self.direction}', status='{self.status}')>"
        )


class Outcome(Base):
    __tablename__ = "outcomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"))
    exit_date = Column(Date)
    exit_price = Column(Numeric(10, 2))
    outcome = Column(String(10))  # WIN / LOSS
    pnl_amount = Column(Numeric(10, 2))
    days_held = Column(Integer)
    exit_reason = Column(String(20))  # TARGET / STOPLOSS / MANUAL

    signal = relationship("Signal", backref="outcome")

    def __repr__(self) -> str:
        return (
            f"<Outcome(id={self.id}, signal_id={self.signal_id}, "
            f"outcome='{self.outcome}', pnl={self.pnl_amount})>"
        )


class MWAScore(Base):
    __tablename__ = "mwa_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    score_date = Column(Date, unique=True, index=True)
    direction = Column(String(15))
    bull_score = Column(Numeric(5, 1))
    bear_score = Column(Numeric(5, 1))
    bull_pct = Column(Numeric(5, 1))
    bear_pct = Column(Numeric(5, 1))
    scanner_results = Column(JSONB().with_variant(JSON, "sqlite"))
    promoted_stocks = Column(
        ARRAY(String).with_variant(JSON, "sqlite") if ARRAY is not None else JSON
    )
    fii_net = Column(Numeric(12, 2))
    dii_net = Column(Numeric(12, 2))
    sector_strength = Column(JSON)

    def __repr__(self) -> str:
        return (
            f"<MWAScore(id={self.id}, date={self.score_date}, "
            f"direction='{self.direction}')>"
        )


class ActiveTrade(Base):
    __tablename__ = "active_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"))
    ticker = Column(String(20), index=True)
    exchange = Column(String(10), default="NSE")
    asset_class = Column(String(15), default="EQUITY")
    entry_price = Column(Numeric(10, 2))
    target = Column(Numeric(10, 2))
    stop_loss = Column(Numeric(10, 2))
    prrr = Column(Numeric(5, 2))
    current_price = Column(Numeric(10, 2))
    crrr = Column(Numeric(5, 2))
    last_updated = Column(DateTime)
    timeframe = Column(String(10), default="1D")
    alert_sent = Column(Boolean, default=False)

    signal = relationship("Signal")

    def __repr__(self) -> str:
        return (
            f"<ActiveTrade(id={self.id}, ticker='{self.ticker}', "
            f"entry={self.entry_price}, current={self.current_price})>"
        )


class OHLCVCache(Base):
    __tablename__ = "ohlcv_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(30), nullable=False)
    exchange = Column(String(10), nullable=False, default="NSE")
    interval = Column(String(10), nullable=False)
    bar_date = Column(DateTime, nullable=False)
    open = Column(Numeric(14, 4), nullable=False)
    high = Column(Numeric(14, 4), nullable=False)
    low = Column(Numeric(14, 4), nullable=False)
    close = Column(Numeric(14, 4), nullable=False)
    volume = Column(Numeric(18, 0), nullable=False)
    source = Column(String(10), nullable=False, default="yfinance")
    fetched_at = Column(DateTime, nullable=False, server_default=func.now())
    tenant_id = Column(String(36), nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("ticker", "interval", "bar_date", name="uq_ohlcv_ticker_interval_bardate"),
        Index("ix_ohlcv_lookup", "ticker", "interval", "bar_date"),
        Index("ix_ohlcv_staleness", "ticker", "interval", "fetched_at"),
        Index("ix_ohlcv_tenant", "tenant_id", "ticker", "interval"),
    )

    def __repr__(self) -> str:
        return (
            f"<OHLCVCache(ticker='{self.ticker}', interval='{self.interval}', "
            f"bar_date={self.bar_date}, close={self.close})>"
        )


class ScannerReview(Base):
    __tablename__ = "scanner_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_date = Column(Date, unique=True, index=True, nullable=False)
    market_direction = Column(String(15))
    overall_hit_rate = Column(Numeric(5, 1))
    scanner_hit_rates = Column(JSONB().with_variant(JSON, "sqlite"))
    missed_opportunities = Column(JSONB().with_variant(JSON, "sqlite"))
    false_positives = Column(JSONB().with_variant(JSON, "sqlite"))
    segment_performance = Column(JSONB().with_variant(JSON, "sqlite"))
    chain_accuracy = Column(JSONB().with_variant(JSON, "sqlite"))
    promoted_performance = Column(JSONB().with_variant(JSON, "sqlite"))
    best_scanners = Column(JSONB().with_variant(JSON, "sqlite"))
    worst_scanners = Column(JSONB().with_variant(JSON, "sqlite"))
    review_payload = Column(JSONB().with_variant(JSON, "sqlite"))
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<ScannerReview(id={self.id}, date={self.review_date}, "
            f"direction='{self.market_direction}', hit_rate={self.overall_hit_rate})>"
        )
