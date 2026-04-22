"""seed_watchlist

Seeds the default multi-asset watchlist (29 NSE equity + 9 MCX commodity +
4 CDS currency + 4 NFO index F&O = 46 rows).

Previously seeded by schema.sql which was mounted into the postgres
container's /docker-entrypoint-initdb.d/. That mechanism only fires on
FIRST boot of an empty postgres volume, making it invisible to Alembic
and impossible to re-apply.

This migration is idempotent — ON CONFLICT DO NOTHING means re-running
it never duplicates rows. The ticker column has no unique constraint
in models.py, so we key on the generated id + explicit ticker check.

Phase 4 of docs/SCHEMA_CONSOLIDATION_PLAN.md.

Revision ID: a5200d85c7ca
Revises: d3b488d0416d
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a5200d85c7ca"
down_revision: Union[str, Sequence[str], None] = "d3b488d0416d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Watchlist rows ─────────────────────────────────────────────────────────

# (ticker, name, exchange, asset_class, timeframe, tier, ltrp, pivot_high)

NSE_EQUITY: list[tuple] = [
    # Trending stocks with known LTRP (long-term retracement price) + pivot
    ("NSE:RELIANCE",   "Reliance Industries",  "NSE", "EQUITY", "day", 2, 1217.55,  1608.80),
    ("NSE:ACC",        "ACC Ltd",              "NSE", "EQUITY", "day", 2, 1903.05,  2844.45),
    ("NSE:SBIN",       "State Bank of India",  "NSE", "EQUITY", "day", 2,  720.55,   912.10),
    ("NSE:CDSL",       "CDSL",                 "NSE", "EQUITY", "day", 2, 1161.30,  1989.95),
    ("NSE:CENTURYTEX", "Century Textiles",     "NSE", "EQUITY", "day", 2, 1725.00,  3043.50),
    ("NSE:GUJGASLTD",  "Gujarat Gas",          "NSE", "EQUITY", "day", 2,  353.10,   750.50),
    ("NSE:JINDALSTEL", "Jindal Steel",         "NSE", "EQUITY", "day", 2,  592.40,  1097.90),
    ("NSE:BAJAJ-AUTO", "Bajaj Auto",           "NSE", "EQUITY", "day", 2, 8186.00, 12774.00),
    ("NSE:BHARATFORG", "Bharat Forge",         "NSE", "EQUITY", "day", 2, 1056.80,  1804.00),
    ("NSE:ECLERX",     "eClerx Services",      "NSE", "EQUITY", "day", 2, 2500.00,  3930.70),
    ("NSE:SHYAMMETL",  "Shyam Metalics",       "NSE", "EQUITY", "day", 2,  477.50,   960.45),
    ("NSE:TATASTEEL",  "Tata Steel",           "NSE", "EQUITY", "day", 2,  128.40,   184.60),
    ("NSE:ABCAPITAL",  "Aditya Birla Capital", "NSE", "EQUITY", "day", 2,  165.30,   250.90),
    ("NSE:ABFRL",      "Aditya Birla Fashion", "NSE", "EQUITY", "day", 2,  250.00,   349.30),
    ("NSE:CASTROLIND", "Castrol India",        "NSE", "EQUITY", "day", 2,  195.50,   284.40),
    ("NSE:GMRINFRA",   "GMR Infrastructure",   "NSE", "EQUITY", "day", 2,   71.00,    98.60),
    ("NSE:PEL",        "Piramal Enterprises",  "NSE", "EQUITY", "day", 2,  825.00,  1216.65),
    ("NSE:LICHSGFIN",  "LIC Housing Finance",  "NSE", "EQUITY", "day", 2,  545.00,   833.00),
    ("NSE:BEL",        "Bharat Electronics",   "NSE", "EQUITY", "day", 2,  260.00,   340.35),
    # Sideways/watch stocks — LTRP/pivot auto-detected via swing_detector.py
    ("NSE:TANLA",      "Tanla Platforms",      "NSE", "EQUITY", "day", 2, None, None),
    ("NSE:IRCTC",      "IRCTC",                "NSE", "EQUITY", "day", 2, None, None),
    ("NSE:IDEA",       "Vodafone Idea",        "NSE", "EQUITY", "day", 2, None, None),
    ("NSE:IRB",        "IRB Infrastructure",   "NSE", "EQUITY", "day", 2, None, None),
    ("NSE:NBCC",       "NBCC India",           "NSE", "EQUITY", "day", 2, None, None),
    ("NSE:CHENNPETRO", "Chennai Petroleum",    "NSE", "EQUITY", "day", 2, None, None),
    ("NSE:NFL",        "National Fertilizers", "NSE", "EQUITY", "day", 2, None, None),
    ("NSE:APLLTD",     "Alembic Pharma",       "NSE", "EQUITY", "day", 2, None, None),
    ("NSE:INDIACEM",   "India Cements",        "NSE", "EQUITY", "day", 2, None, None),
    ("NSE:LICI",       "LIC India",            "NSE", "EQUITY", "day", 2, None, None),
]

MCX_COMMODITY: list[tuple] = [
    ("MCX:GOLD",       "Gold",        "MCX", "COMMODITY", "day", 2, None, None),
    ("MCX:SILVER",     "Silver",      "MCX", "COMMODITY", "day", 2, None, None),
    ("MCX:CRUDEOIL",   "Crude Oil",   "MCX", "COMMODITY", "day", 2, None, None),
    ("MCX:NATURALGAS", "Natural Gas", "MCX", "COMMODITY", "day", 2, None, None),
    ("MCX:COPPER",     "Copper",      "MCX", "COMMODITY", "day", 2, None, None),
    ("MCX:ZINC",       "Zinc",        "MCX", "COMMODITY", "day", 3, None, None),
    ("MCX:ALUMINIUM",  "Aluminium",   "MCX", "COMMODITY", "day", 3, None, None),
    ("MCX:LEAD",       "Lead",        "MCX", "COMMODITY", "day", 3, None, None),
    ("MCX:NICKEL",     "Nickel",      "MCX", "COMMODITY", "day", 3, None, None),
]

CDS_CURRENCY: list[tuple] = [
    ("CDS:USDINR", "USD/INR", "CDS", "CURRENCY", "day", 2, None, None),
    ("CDS:EURINR", "EUR/INR", "CDS", "CURRENCY", "day", 2, None, None),
    ("CDS:GBPINR", "GBP/INR", "CDS", "CURRENCY", "day", 3, None, None),
    ("CDS:JPYINR", "JPY/INR", "CDS", "CURRENCY", "day", 3, None, None),
]

NFO_INDEX_FNO: list[tuple] = [
    ("NFO:NIFTY",      "Nifty 50 F&O",     "NFO", "FNO", "15m", 1, None, None),
    ("NFO:BANKNIFTY",  "Bank Nifty F&O",   "NFO", "FNO", "15m", 1, None, None),
    ("NFO:FINNIFTY",   "Fin Nifty F&O",    "NFO", "FNO", "15m", 2, None, None),
    ("NFO:MIDCPNIFTY", "Midcap Nifty F&O", "NFO", "FNO", "15m", 2, None, None),
]

ALL_ROWS = NSE_EQUITY + MCX_COMMODITY + CDS_CURRENCY + NFO_INDEX_FNO


def upgrade() -> None:
    """Insert seed rows. Skip any ticker that already exists."""
    bind = op.get_bind()

    insert_sql = sa.text("""
        INSERT INTO watchlist
          (ticker, name, exchange, asset_class, timeframe, tier,
           ltrp, pivot_high, active, source, added_by)
        SELECT :ticker, :name, :exchange, :asset_class, :timeframe, :tier,
               :ltrp, :pivot_high, TRUE, 'manual', 'system'
        WHERE NOT EXISTS (
            SELECT 1 FROM watchlist WHERE ticker = :ticker
        )
    """)

    for row in ALL_ROWS:
        ticker, name, exchange, asset_class, timeframe, tier, ltrp, pivot_high = row
        bind.execute(
            insert_sql,
            {
                "ticker": ticker,
                "name": name,
                "exchange": exchange,
                "asset_class": asset_class,
                "timeframe": timeframe,
                "tier": tier,
                "ltrp": ltrp,
                "pivot_high": pivot_high,
            },
        )


def downgrade() -> None:
    """Remove only the rows this migration inserted."""
    bind = op.get_bind()
    tickers = [row[0] for row in ALL_ROWS]
    bind.execute(
        sa.text("DELETE FROM watchlist WHERE ticker = ANY(:tickers) AND source = 'manual'"),
        {"tickers": tickers},
    )
