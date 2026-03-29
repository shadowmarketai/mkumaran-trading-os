import os
import logging

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
    migrations = {
        "signals": {
            "timeframe": "VARCHAR(10) DEFAULT '1D'",
            "tier": "INTEGER",
            "source": "VARCHAR(20)",
            "exchange": "VARCHAR(10) DEFAULT 'NSE'",
            "asset_class": "VARCHAR(15) DEFAULT 'EQUITY'",
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


def init_db():
    from mcp_server import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    try:
        _add_missing_columns()
    except Exception as e:
        logger.warning("Column migration check failed: %s", e)
