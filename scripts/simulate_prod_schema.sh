#!/usr/bin/env bash
# Schema consolidation — Phase 2 simulation helper.
#
# Reproduces an approximation of prod DB state locally so we can
# autogenerate the reconciling Alembic migration.
#
# Uses ports 5434 / 5435 to avoid colliding with any host postgres on 5432.
#
# Requires Docker Desktop running.

set -euo pipefail

SNAP_DIR="docs/schema_snapshots"
mkdir -p "$SNAP_DIR"

PROD_SIM_CONTAINER="trading_os_prod_sim"
ALEMBIC_CONTAINER="trading_os_alembic_only"

echo "[1/9] Cleaning up any leftover sim containers..."
docker rm -f "$PROD_SIM_CONTAINER" "$ALEMBIC_CONTAINER" 2>/dev/null || true

echo "[2/9] Starting prod-sim postgres on :5434..."
docker run -d --name "$PROD_SIM_CONTAINER" \
  -e POSTGRES_USER=trading \
  -e POSTGRES_PASSWORD=trading_pass \
  -e POSTGRES_DB=trading_os \
  -v "$(pwd -W 2>/dev/null || pwd)/schema.sql":/docker-entrypoint-initdb.d/01-schema.sql:ro \
  -p 5434:5432 \
  postgres:16-alpine >/dev/null

echo "[3/9] Waiting for :5434 healthcheck..."
for i in $(seq 1 60); do
  if docker exec "$PROD_SIM_CONTAINER" pg_isready -U trading -d trading_os >/dev/null 2>&1; then
    echo "    ready"
    break
  fi
  sleep 1
done

echo "[4/9] Running init_db() against :5434 (create_all + _add_missing_columns)..."
DATABASE_URL="postgresql://trading:trading_pass@localhost:5434/trading_os" \
  python -c "
from mcp_server.db import init_db
init_db()
print('init_db complete')
"

echo "[5/9] Simulating auth_providers.py lazy CREATE TABLE (app_users)..."
DATABASE_URL="postgresql://trading:trading_pass@localhost:5434/trading_os" \
  python -c "
from mcp_server.db import SessionLocal
db = SessionLocal()
try:
    from mcp_server.auth_providers import _ensure_table
    _ensure_table(db)
    print('app_users ensured')
except Exception as e:
    print(f'app_users ensure skipped: {e}')
finally:
    db.close()
" || echo "(app_users ensure raised — skipping, will show in diff)"

echo "[6/9] Simulating tier_guard.py lazy CREATE TABLE (usage_logs)..."
DATABASE_URL="postgresql://trading:trading_pass@localhost:5434/trading_os" \
  python -c "
from sqlalchemy import text
from mcp_server.db import SessionLocal
db = SessionLocal()
try:
    db.execute(text('''
        CREATE TABLE IF NOT EXISTS usage_logs (
            id SERIAL PRIMARY KEY,
            feature VARCHAR(100) NOT NULL,
            count INTEGER DEFAULT 1,
            period_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    '''))
    db.commit()
    print('usage_logs ensured')
finally:
    db.close()
"

echo "[7/9] Dumping prod-sim schema → $SNAP_DIR/prod_sim_schema.sql"
docker exec "$PROD_SIM_CONTAINER" \
  pg_dump --schema-only --no-owner --no-privileges -U trading trading_os > "$SNAP_DIR/prod_sim_schema.sql"

echo "[8/9] Starting alembic-only postgres on :5435..."
docker run -d --name "$ALEMBIC_CONTAINER" \
  -e POSTGRES_USER=trading \
  -e POSTGRES_PASSWORD=trading_pass \
  -e POSTGRES_DB=trading_os \
  -p 5435:5432 \
  postgres:16-alpine >/dev/null

for i in $(seq 1 60); do
  if docker exec "$ALEMBIC_CONTAINER" pg_isready -U trading -d trading_os >/dev/null 2>&1; then
    echo "    :5435 ready"
    break
  fi
  sleep 1
done

echo "    Running alembic upgrade head against :5435..."
DATABASE_URL="postgresql://trading:trading_pass@localhost:5435/trading_os" \
  alembic upgrade head

echo "    Dumping alembic-only schema → $SNAP_DIR/alembic_only_schema.sql"
docker exec "$ALEMBIC_CONTAINER" \
  pg_dump --schema-only --no-owner --no-privileges -U trading trading_os > "$SNAP_DIR/alembic_only_schema.sql"

echo ""
echo "[9/9] ======================================================================"
echo " Diff (alembic-only → prod-sim): what the reconciling migration must add"
echo "======================================================================"
diff -u "$SNAP_DIR/alembic_only_schema.sql" "$SNAP_DIR/prod_sim_schema.sql" > "$SNAP_DIR/drift.diff" || true
cat "$SNAP_DIR/drift.diff" | head -400

echo ""
echo "Saved artifacts:"
echo "  $SNAP_DIR/prod_sim_schema.sql       (the drifted state)"
echo "  $SNAP_DIR/alembic_only_schema.sql   (pure Alembic state)"
echo "  $SNAP_DIR/drift.diff                 (what we need to reconcile)"
echo ""
echo "Cleanup: docker rm -f $PROD_SIM_CONTAINER $ALEMBIC_CONTAINER"
