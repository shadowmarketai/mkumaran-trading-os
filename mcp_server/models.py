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

    # ── Entry context (captured at signal creation for RCA + ML) ──
    entry_rsi = Column(Numeric(6, 2), nullable=True)
    entry_adx = Column(Numeric(6, 2), nullable=True)
    entry_atr_pct = Column(Numeric(6, 3), nullable=True)
    entry_volume_ratio = Column(Numeric(7, 3), nullable=True)
    entry_vwap_dev = Column(Numeric(7, 3), nullable=True)
    entry_momentum = Column(Numeric(7, 3), nullable=True)
    entry_macd_hist = Column(Numeric(10, 4), nullable=True)
    entry_bb_width = Column(Numeric(7, 3), nullable=True)
    entry_regime = Column(String(20), nullable=True)  # TRENDING_UP/DOWN/RANGING/VOLATILE
    entry_mwa_bull_pct = Column(Numeric(5, 1), nullable=True)
    entry_mwa_bear_pct = Column(Numeric(5, 1), nullable=True)

    # Scanner attribution + ML output
    scanner_list = Column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    feature_vector = Column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    loss_probability = Column(Numeric(5, 3), nullable=True)  # 0.0-1.0 from predictor
    predictor_version = Column(String(20), nullable=True)
    suppressed = Column(Boolean, default=False)  # blocked by predictor
    suppression_reason = Column(Text, nullable=True)
    rca_json = Column(JSONB().with_variant(JSON, "sqlite"), nullable=True)  # postmortem

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

    # Extended exit context for postmortem RCA
    exit_reason_detail = Column(Text, nullable=True)
    pattern_invalidated = Column(Boolean, nullable=True)
    invalidation_reason = Column(String(100), nullable=True)
    max_adverse_excursion = Column(Numeric(7, 3), nullable=True)  # worst drawdown %
    max_favorable_excursion = Column(Numeric(7, 3), nullable=True)  # best run-up %

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


class Postmortem(Base):
    """Root-cause analysis for each closed losing (or winning) signal."""
    __tablename__ = "postmortems"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    outcome = Column(String(10))  # WIN / LOSS / BREAKEVEN
    root_cause = Column(Text)
    contributing_factors = Column(JSONB().with_variant(JSON, "sqlite"))
    rule_checks = Column(JSONB().with_variant(JSON, "sqlite"))  # list of rule -> pass/fail
    suggested_filter = Column(Text)
    similar_signals = Column(JSONB().with_variant(JSON, "sqlite"))  # top-k similar past trades
    claude_narrative = Column(Text)  # LLM-generated explanation
    confidence_score = Column(Numeric(5, 2))  # how confident the RCA is

    signal = relationship("Signal")

    def __repr__(self) -> str:
        return (
            f"<Postmortem(id={self.id}, signal_id={self.signal_id}, "
            f"outcome='{self.outcome}')>"
        )


class AdaptiveRule(Base):
    """Learned filter rules from rules-learning engine, applied at signal time."""
    __tablename__ = "adaptive_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_key = Column(String(100), unique=True, index=True)  # e.g. "skip_short_when_adx_lt_15"
    description = Column(Text)
    condition_json = Column(JSONB().with_variant(JSON, "sqlite"))  # structured condition
    action = Column(String(30))  # block / reduce_size / reduce_confidence
    action_params = Column(JSONB().with_variant(JSON, "sqlite"))

    # Back-test metrics
    sample_size = Column(Integer, default=0)
    historical_hit_rate_before = Column(Numeric(5, 2))
    historical_hit_rate_after = Column(Numeric(5, 2))
    estimated_losses_prevented = Column(Integer, default=0)
    estimated_wins_lost = Column(Integer, default=0)

    # Deployment state
    active = Column(Boolean, default=False)
    auto_generated = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    activated_at = Column(DateTime, nullable=True)
    last_fired_at = Column(DateTime, nullable=True)
    fire_count = Column(Integer, default=0)

    def __repr__(self) -> str:
        return (
            f"<AdaptiveRule(key='{self.rule_key}', active={self.active}, "
            f"sample={self.sample_size})>"
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
