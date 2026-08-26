"""
One-time fix: unknown Alembic revision 0b963b963e05

The DB's alembic_version table contains revision '0b963b963e05' which has
no corresponding migration file (was applied directly on the server).
Alembic can't upgrade because it can't resolve the dependency chain.

This script:
  1. Shows the current DB revision state
  2. Adds the human_decision column to signals (IF NOT EXISTS — safe to re-run)
  3. Replaces the unknown revision in alembic_version with d4e5f6a7b8c9 (merge head)

Run once on the server:
    python scripts/fix_alembic_state.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from mcp_server.db import engine

MERGE_HEAD = "d4e5f6a7b8c9"

with engine.begin() as conn:
    # Step 1 — show current state
    rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    print(f"Current alembic_version: {[r[0] for r in rows]}")

    # Step 2 — add human_decision column (IF NOT EXISTS is safe to run twice)
    conn.execute(text(
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS human_decision VARCHAR(10)"
    ))
    print("Column human_decision: ensured on signals table")

    # Step 3 — replace unknown revision with our merge head
    conn.execute(text("DELETE FROM alembic_version"))
    conn.execute(text(
        "INSERT INTO alembic_version (version_num) VALUES (:rev)"
    ), {"rev": MERGE_HEAD})
    print(f"alembic_version stamped at {MERGE_HEAD} (merge head)")

print()
print("Done. Run 'alembic upgrade head' to confirm — it should say 'already at head'.")
