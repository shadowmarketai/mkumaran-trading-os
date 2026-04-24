import os
import logging
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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
    """Create tables from SQLAlchemy models as a safety net.

    After schema consolidation (Phase 3 of docs/SCHEMA_CONSOLIDATION_PLAN.md),
    Alembic is the authoritative schema source — run_alembic_upgrade()
    runs first in the lifespan. This function remains as belt-and-suspenders:
    if Alembic fails for any reason, create_all still creates any missing
    tables so the app can boot in a degraded-but-functional state.

    The `_add_missing_columns()` runtime escape hatch was removed in the
    same phase — its logic now lives in Alembic migration d3b488d0416d.
    """
    from mcp_server import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
