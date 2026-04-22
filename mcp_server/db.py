import os
import logging
from pathlib import Path

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:pass@localhost:5432/trading_os"
)
# Coolify/Heroku use postgres:// but SQLAlchemy requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns():
    """Add columns that exist in models but not in the database."""
    insp = inspect(engine)

    # Postgres supports JSONB, sqlite falls back to TEXT
    is_pg = engine.dialect.name in ("postgresql", "postgres")
    jsonb = "JSONB" if is_pg else "TEXT"

    migrations = {
        "signals": {
            "timeframe": "VARCHAR(10) DEFAULT '1D'",
            "tier": "INTEGER",
            "source": "VARCHAR(20)",
            "exchange": "VARCHAR(10) DEFAULT 'NSE'",
            "asset_class": "VARCHAR(15) DEFAULT 'EQUITY'",
            # Phase 1: self-development / RCA fields
            "entry_rsi": "NUMERIC(6,2)",
            "entry_adx": "NUMERIC(6,2)",
            "entry_atr_pct": "NUMERIC(6,3)",
            "entry_volume_ratio": "NUMERIC(7,3)",
            "entry_vwap_dev": "NUMERIC(7,3)",
            "entry_momentum": "NUMERIC(7,3)",
            "entry_macd_hist": "NUMERIC(10,4)",
            "entry_bb_width": "NUMERIC(7,3)",
            "entry_regime": "VARCHAR(20)",
            "entry_mwa_bull_pct": "NUMERIC(5,1)",
            "entry_mwa_bear_pct": "NUMERIC(5,1)",
            "scanner_list": jsonb,
            "feature_vector": jsonb,
            "loss_probability": "NUMERIC(5,3)",
            "predictor_version": "VARCHAR(20)",
            "suppressed": "BOOLEAN DEFAULT FALSE",
            "suppression_reason": "TEXT",
            "rca_json": jsonb,
            # Phase 2: Options enrichment fields (for FNO signals)
            "option_strategy": "VARCHAR(30)",
            "option_tradingsymbol": "VARCHAR(50)",
            "option_strike": "NUMERIC(12,2)",
            "option_expiry": "DATE",
            "option_type": "VARCHAR(2)",
            "option_premium": "NUMERIC(10,2)",
            "option_premium_sl": "NUMERIC(10,2)",
            "option_premium_target": "NUMERIC(10,2)",
            "option_lot_size": "INTEGER",
            "option_contracts": "INTEGER DEFAULT 1",
            "option_iv_rank": "NUMERIC(5,1)",
            "option_delta": "NUMERIC(6,4)",
            "option_gamma": "NUMERIC(8,6)",
            "option_theta": "NUMERIC(8,2)",
            "option_vega": "NUMERIC(8,2)",
            "option_iv": "NUMERIC(6,4)",
            "option_is_spread": "BOOLEAN DEFAULT FALSE",
            "option_net_premium": "NUMERIC(10,2)",
            "option_legs": jsonb,
        },
        "outcomes": {
            "exit_reason_detail": "TEXT",
            "pattern_invalidated": "BOOLEAN",
            "invalidation_reason": "VARCHAR(100)",
            "max_adverse_excursion": "NUMERIC(7,3)",
            "max_favorable_excursion": "NUMERIC(7,3)",
            # Phase 2: Option exit tracking
            "option_exit_premium": "NUMERIC(10,2)",
            "option_pnl_per_lot": "NUMERIC(12,2)",
            "option_pnl_pct": "NUMERIC(7,2)",
        },
        "active_trades": {
            "timeframe": "VARCHAR(10) DEFAULT '1D'",
            "alert_sent": "BOOLEAN DEFAULT FALSE",
            "exchange": "VARCHAR(10) DEFAULT 'NSE'",
            "asset_class": "VARCHAR(15) DEFAULT 'EQUITY'",
        },
        "watchlist": {
            "exchange": "VARCHAR(10) DEFAULT 'NSE'",
            "asset_class": "VARCHAR(15) DEFAULT 'EQUITY'",
        },
        "ohlcv_cache": {
            "tenant_id": "VARCHAR(36)",
        },
    }

    with engine.begin() as conn:
        for table_name, columns in migrations.items():
            if not insp.has_table(table_name):
                continue
            existing = {c["name"] for c in insp.get_columns(table_name)}
            for col_name, col_type in columns.items():
                if col_name not in existing:
                    stmt = f'ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}'
                    conn.execute(text(stmt))
                    logger.info("Added column %s.%s", table_name, col_name)


def _should_stamp_head(conn) -> str | None:
    """Detect an existing DB that's never had Alembic applied.

    Returns the rev to stamp (current head) if:
      - Core tables exist (this is a real production DB, not fresh)
      - AND alembic_version table is missing / empty

    Returns None otherwise (fresh DB → let upgrade create everything; or
    already-stamped DB → nothing to do).
    """
    insp = inspect(conn)
    has_alembic_version = insp.has_table("alembic_version")
    has_core_tables = insp.has_table("signals") and insp.has_table("watchlist")

    if not has_core_tables:
        return None  # Fresh DB — let upgrade create everything

    if has_alembic_version:
        # Check if the table has any rows
        row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
        if row:
            return None  # Already stamped — upgrade will no-op or advance

    # Production DB that pre-dates Alembic wiring. Stamp at the most
    # recent revision so upgrade() doesn't try to re-CREATE the tables
    # that already exist. The schema consolidation migration (future
    # Phase 2) will advance the head from here.
    return "c3d4e5f6a7b8"  # current head as of 2026-04-22


def run_alembic_upgrade() -> None:
    """Run `alembic upgrade head` programmatically, non-fatally.

    Called from the backend lifespan BEFORE init_db(). If Alembic fails
    for any reason, we log ERROR and continue boot — trading must not
    halt because of a migration hiccup. Phase 1 of the schema
    consolidation plan (docs/SCHEMA_CONSOLIDATION_PLAN.md).
    """
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        logger.warning("Alembic not installed — skipping upgrade")
        return

    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not alembic_ini.exists():
        logger.warning("alembic.ini not found at %s — skipping upgrade", alembic_ini)
        return

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

    # Check if we need to stamp an existing DB before upgrading.
    try:
        with engine.connect() as conn:
            stamp_target = _should_stamp_head(conn)
        if stamp_target:
            logger.info(
                "Existing DB detected without alembic_version — stamping at %s",
                stamp_target,
            )
            command.stamp(cfg, stamp_target)
    except Exception as stamp_err:
        logger.error("Alembic stamp detection failed: %s", stamp_err)
        # Continue to upgrade anyway; it may still succeed or no-op safely.

    try:
        logger.info("Running alembic upgrade head...")
        command.upgrade(cfg, "head")
        logger.info("Alembic upgrade complete")
    except Exception as upgrade_err:
        # Non-fatal. Log loudly so it's visible in structured logs +
        # any alert pipeline, but do NOT crash the backend boot.
        logger.error(
            "Alembic upgrade FAILED — continuing boot without migration. "
            "Schema may drift from models.py. Error: %s",
            upgrade_err,
        )


def init_db():
    from mcp_server import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    try:
        _add_missing_columns()
    except Exception as e:
        logger.warning("Column migration check failed: %s", e)
