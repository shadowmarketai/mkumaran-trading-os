# Schema Consolidation Plan

> Plan only — no code changes in this commit. Approve before execution.
>
> **Goal:** reduce schema-of-truth from 5 sources to 1 (Alembic), without downtime and without losing any production data.
>
> **Status:** DRAFT — awaiting operator review
> **Author:** `onboarder` → plan handoff
> **Last updated:** 2026-04-22

---

## 1. Current state — five schema sources

Discovered during audit. **All five are live in production.** Any one of them can silently add a table or column that the others don't know about.

| # | Source | What it does | When it runs | Coverage |
|---|---|---|---|---|
| **1** | `schema.sql` (190 lines) | `CREATE TABLE IF NOT EXISTS` for 5 core tables + seed data (29 NSE stocks + 9 MCX + 4 CDS + 4 NFO) | Once, on first postgres container boot (mounted at `/docker-entrypoint-initdb.d/`) | Only fires for a **fresh** postgres volume. No-op thereafter. |
| **2** | `alembic/versions/` (3 files) | Formal migrations | Manually via `alembic upgrade head` (but **never called automatically** — not in Dockerfile or lifespan) | Partial — only 6 tables + a broken `users` ALTER |
| **3** | `Base.metadata.create_all(bind=engine)` in `db.py:130` | ORM-driven table creation | Every backend boot, inside `init_db()` | Creates any `models.py` table not yet in DB — **currently the only creator of `postmortems`, `adaptive_rules`, `scanner_reviews`** |
| **4** | `_add_missing_columns()` in `db.py:34–135` | Runtime `ALTER TABLE ADD COLUMN` with ~60 hardcoded column definitions | Every backend boot, after `create_all()` | Adds columns that `schema.sql` + `create_all` missed. Ignores type changes, never removes. |
| **5** | Raw `CREATE TABLE IF NOT EXISTS` in Python modules | `auth_providers.py:210` creates `app_users` (+ 3 indexes); `tier_guard.py:151` creates `usage_logs` | Lazily — on first auth / first feature use | Completely outside Alembic. Overlaps with `alembic/versions/c3d4e5f6a7b8` which ALSO creates `app_users` with a different column set. |

### What tables exist where

Legend: ✅ declared, ❌ absent, ⚠ partial/conflicting.

| Table | `schema.sql` | Alembic | `models.py` + `create_all` | `_add_missing_columns` | Raw SQL |
|---|---|---|---|---|---|
| `watchlist` | ✅ seed | ✅ initial | ✅ | ✅ 2 cols | — |
| `signals` | ✅ 21 cols | ✅ 20 cols | ✅ ~70 cols | ✅ **40+ cols** | — |
| `outcomes` | ✅ | ✅ | ✅ | ✅ 8 cols | — |
| `mwa_scores` | ✅ | ✅ | ✅ | — | — |
| `active_trades` | ✅ | ✅ | ✅ | ✅ 4 cols | — |
| `ohlcv_cache` | ❌ | ✅ (in initial) | ✅ | ✅ 1 col (`tenant_id`) | — |
| `postmortems` | ❌ | ❌ | ✅ only | — | — |
| `adaptive_rules` | ❌ | ❌ | ✅ only | — | — |
| `scanner_reviews` | ❌ | ❌ | ✅ only | — | — |
| `user_settings` | ❌ | ✅ (b2c3d4e5f6a7) | ❌ | — | — |
| `app_users` | ❌ | ⚠ (c3d4e5f6a7b8 — one schema) | ❌ | — | ⚠ `auth_providers.py` — different schema |
| `users` | ❌ | ⚠ (b2c3d4e5f6a7 ALTERs a non-existent table, try/except'd) | ❌ | — | ? (unknown origin) |
| `usage_logs` | ❌ | ❌ | ❌ | — | ✅ `tier_guard.py` |

### Known drift incidents (from the dossier audit)

1. **`app_users` schema conflict.** Alembic `c3d4e5f6a7b8` creates `app_users` with columns `{email, phone, password_hash, name, avatar_url, auth_provider, google_id, city, trading_experience, trading_segments, is_verified, is_active, role, last_login, created_at}`. `auth_providers.py:210` creates `app_users` with columns `{..., telegram_chat_id, alert_enabled, subscription_tier, daily_signal_count, last_signal_date, ...}` — three extra columns Alembic doesn't know about. Whichever runs first wins; the other is a no-op due to `IF NOT EXISTS`.
2. **`users` table phantom.** `b2c3d4e5f6a7_multi_auth_byok.py:22–30` tries to `ALTER TABLE users ADD COLUMN ...` wrapped in `try/except: pass`. No `users` model exists, no `schema.sql` entry, no other CREATE. **Either dead code or there's a deploy-time process that creates `users` outside the repo.** Must resolve during audit.
3. **`ohlcv_cache` bootstrap gap.** Fresh `docker compose up` runs `schema.sql` which lacks `ohlcv_cache`. The table gets created later by `create_all()`. Between container boot and first backend boot, any process expecting `ohlcv_cache` would fail — narrow window but possible.
4. **`postmortems` / `adaptive_rules` / `scanner_reviews` have zero Alembic coverage.** They exist only because `create_all()` runs at startup. If a team ever disables `create_all()` (standard practice in migration-managed projects), all three tables vanish on fresh deploys.
5. **`_add_missing_columns` can't drop or alter.** A column type widened in `models.py` (e.g. `Numeric(5,2) → Numeric(7,2)`) will silently NOT propagate to existing deploys. Only NEW columns get added.

---

## 2. Target state — one source of truth

```
┌──────────────────────────────────────────────────────────────┐
│                    Alembic (sole schema owner)                │
│                                                               │
│  alembic/versions/                                            │
│  ├── 44cb7fb01bfb  initial_schema           ← keep as-is     │
│  ├── b2c3d4e5f6a7  multi_auth_byok          ← keep as-is     │
│  ├── c3d4e5f6a7b8  users_registration       ← keep as-is     │
│  └── <new_rev>     consolidate_drifted_state  ← this PR       │
│     adds: all cols from _add_missing_columns                 │
│     adds: postmortems, adaptive_rules, scanner_reviews       │
│     adds: app_users extra cols (telegram_chat_id etc.)       │
│     adds: usage_logs                                         │
│     drops: phantom users-table ALTERs (if dead)              │
└──────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────┐
│  Backend lifespan:                                            │
│  1. alembic upgrade head    ← NEW, runs on every boot        │
│  2. init_db()                ← keep; create_all becomes no-op │
│                                  since Alembic owns schema    │
└──────────────────────────────────────────────────────────────┘
```

**Removed:**
- `schema.sql` seed-data portion → migrated to an Alembic data migration
- `schema.sql` file itself → deleted (docker-compose no longer mounts it)
- `_add_missing_columns()` → deleted
- `auth_providers.py:200–239` `_ensure_table` → deleted
- `tier_guard.py:148–158` inline CREATE TABLE → deleted
- `create_all(bind=engine)` → kept but becomes no-op in practice (safety net only)

---

## 3. Execution plan — phased, reversible

Each phase is its own commit so you can bail out between phases.

### Phase 0 — Pre-flight (no changes, gather truth)

- [ ] On production DB: `pg_dump --schema-only --no-owner --no-privileges trading_os > prod_schema_snapshot_2026-04-22.sql`. Stash in `docs/schema_snapshots/` (gitignored).
- [ ] Diff `prod_schema_snapshot` against a fresh `docker compose up` local DB to identify any prod-only columns not in the source tree. Flag surprises.
- [ ] Confirm the `users` table: does it exist in prod? If yes, dump its schema. If no, the `b2c3d4e5f6a7` ALTERs are officially dead code.
- [ ] Capture current Alembic head: `alembic current`. Should be `c3d4e5f6a7b8` on prod IF migrations have been run. **It may not have been — the lifespan never calls `alembic upgrade`.** If `alembic_version` table is empty/missing, we have to stamp it first.

**Output of Phase 0:** a plain-English status doc (≤1 page) confirming which tables/columns exist in prod, whether migrations have ever been applied, and whether the `users` phantom is real.

### Phase 1 — Wire Alembic into the boot path

Small change, low risk, high value.

**Diff:**
- `mcp_server/mcp_server.py` lifespan: `await asyncio.to_thread(run_alembic_upgrade)` before `init_db()`.
- `mcp_server/db.py`: new helper `run_alembic_upgrade()` that shells out to `alembic upgrade head` (or uses `alembic.command.upgrade(cfg, "head")` programmatically).
- Dev-compose: optional `alembic stamp head` step on first boot if `alembic_version` is empty AND tables already exist (i.e. this is an existing DB that never ran migrations).

**Test:**
- Fresh postgres volume → `docker compose up` → all tables present, `alembic current` = `c3d4e5f6a7b8`.
- Staging DB dump restored locally → `docker compose up` → Alembic stamps head if tables pre-exist, upgrade is idempotent.

**Rollback:** revert the lifespan line.

### Phase 2 — Generate the reconciling migration

Autogenerate + hand-edit. This is the heavy phase.

**Steps:**
1. On a local DB restored from the prod dump: `alembic revision --autogenerate -m "consolidate_drifted_state"`.
2. Review the autogenerated revision carefully. Autogenerate will:
   - Try to ADD every column from `models.py` that isn't in DB → good, keep.
   - Try to CREATE every table from `models.py` that isn't in DB (`postmortems`, `adaptive_rules`, `scanner_reviews` — **unless prod already has them from `create_all`**).
   - Try to DROP any DB columns not in `models.py` → **review each — some may be legitimate ops-added columns.**
3. Hand-edit to add:
   - The 3 extra `app_users` columns (`telegram_chat_id`, `alert_enabled`, `subscription_tier`, `daily_signal_count`, `last_signal_date`) — these aren't in any model.
   - `usage_logs` table from `tier_guard.py`.
4. Hand-edit to make every ADD/CREATE idempotent with `IF NOT EXISTS` semantics — use `op.execute()` with raw SQL where Alembic doesn't support it natively. Prod already has most of these columns; the migration must be a no-op for a prod DB and a full-create for a fresh dev DB.
5. Run Alembic against the local prod-replica → confirm `alembic current` advances and no tables are harmed.
6. Run Alembic against a fresh DB → confirm the full schema is created.

**Test matrix:**

| Starting state | Expected result |
|---|---|
| Fresh DB, Alembic upgrade | All tables + columns created, heads up |
| Prod dump, Alembic upgrade | No-op for existing; new tables/columns added; heads up |
| Prod dump with some runtime-added columns removed | Alembic re-adds them; heads up |
| Dev DB mid-migration (stamped but upgrade interrupted) | Alembic resumes from last applied rev |

**Rollback:** Alembic `downgrade -1`. The consolidating migration's `downgrade()` must be reviewed carefully — blind drops would destroy prod data.

**My strong recommendation:** the `downgrade()` for this revision should be a `raise NotImplementedError` with a clear message. Rolling back a consolidation is effectively restoring from backup, not running `downgrade`. Agreed before I do this?

### Phase 3 — Delete the runtime escape hatches

Once Phase 2 is proven safe in staging.

**Diff:**
- Delete `_add_missing_columns()` from `db.py` (125 lines)
- Delete `_ensure_table` CREATE TABLE from `auth_providers.py:200–239`
- Delete inline CREATE TABLE from `tier_guard.py:148–158`
- Update `.claude/project-state.md` → Known Issues section: mark schema drift as resolved

**Keep:**
- `Base.metadata.create_all(bind=engine)` — defensive safety net. With Alembic running first, this becomes a no-op 99% of the time. Deleting it removes the belt; we keep both belt and suspenders for now.

**Test:**
- Full test suite passes (`pytest`).
- Fresh `docker compose up` from clean volume → all tables present, no runtime ALTER warnings in logs.
- Staging DB upgrade → no new ALTERs logged.

**Rollback:** revert the 3 file changes. Runtime escape hatches are back.

### Phase 4 — Remove `schema.sql`

Only after Phase 3 has been running in prod for 1 week without incident.

**Diff:**
- Move the seed INSERT statements from `schema.sql` into a new Alembic data migration: `alembic revision -m "seed_watchlist"`. Use `op.bulk_insert` or raw `op.execute(text(...))`.
- Delete `schema.sql`.
- Remove the `- ./schema.sql:/docker-entrypoint-initdb.d/01-schema.sql` mount from `docker-compose.yml` and `docker-compose.dev.yml`.
- Update `README.md` "Quick Start" — seed data now comes from the data migration.

**Test:**
- Fresh `docker compose up` → postgres boots empty, backend boots → Alembic runs both structural + data migration → watchlist populated.
- Seed idempotency: data migration uses `INSERT ... ON CONFLICT DO NOTHING` (or equivalent) so re-running doesn't duplicate.

**Rollback:** restore `schema.sql`, restore compose mounts. Data migration stays in Alembic but becomes redundant; not harmful.

---

## 4. Risk register

| # | Risk | Likelihood | Blast radius | Mitigation |
|---|---|---|---|---|
| R1 | Phase 2 migration drops a prod column autogenerate didn't recognize as model-owned | Medium | **High** — data loss | Review every DROP line by line. Default to keeping columns; only drop after grep-confirming no usage. |
| R2 | Prod DB never had Alembic migrations applied; `alembic_version` table missing | High | Medium — migration won't run cleanly | Phase 1 detects this and runs `alembic stamp c3d4e5f6a7b8` before first upgrade. |
| R3 | The phantom `users` table actually exists in prod (created by some external process) | Medium | Low — just mysterious | Phase 0 pg_dump will reveal. If real, add explicit Alembic coverage before Phase 3. |
| R4 | `app_users` in prod has the `auth_providers.py` columns but Alembic's version doesn't — migration ADDs them as no-ops | Medium | Low | Desired outcome. `IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` handle it. |
| R5 | `docker-entrypoint-initdb.d` race: Phase 4 removes `schema.sql` but some dev workflow depended on it | Low | Low | Dev docs updated in same commit; `start.sh` smoke-test. |
| R6 | Alembic `upgrade head` fails on boot → backend crash-loops | Low | **High** — trading halts | Lifespan wraps upgrade in try/except; on failure, log ERROR + alert, continue boot without upgrade (don't crash). Alembic is non-fatal. |
| R7 | Rolling back Phase 3 after it ships requires re-implementing `_add_missing_columns` | Low | Medium | Keep the deleted code in git history; revert commit restores it. |

---

## 5. Timeline estimate

Assumes the prod DB is reachable and a pg_dump can be acquired.

| Phase | Work | Elapsed |
|---|---|---|
| 0 — Audit | pg_dump + diff + write Phase 0 status doc | 2 hr |
| 1 — Wire Alembic to boot | Code + tests + staging deploy + smoke | 3 hr |
| 2 — Consolidating migration | Autogenerate + hand-edit + test matrix + staging apply | 4 hr |
| 3 — Delete escape hatches | Delete code + full test suite + staging deploy + 1 day soak | 2 hr + 1 day soak |
| 4 — Delete `schema.sql` | Move seed to data migration + docs + fresh-compose test | 2 hr (but gated on 1-week prod soak after Phase 3) |

**Total dev work: ~13 hours across 3 PRs (P1 / P2+P3 / P4).** Total calendar: 1–2 weeks with appropriate soak periods.

---

## 6. Deliverables per phase

- **Phase 0** — `docs/schema_snapshots/2026-04-22_audit.md` (pg_dump findings). Not committed as a PR, just a working doc.
- **Phase 1** — PR: `feat(db): wire Alembic into backend lifespan`
- **Phase 2 + 3** — PR: `refactor(db): consolidate schema to single Alembic source of truth`
- **Phase 4** — PR: `chore(db): retire schema.sql in favor of data migration`

Each PR links to this plan and checks off the relevant phase.

---

## 7. Open questions for the operator

Answer these before I start Phase 0:

- [ ] **Prod DB access.** Can I have read-only access to run `pg_dump --schema-only`, or will you run it and paste the output? (I don't need data, just schema.)
- [ ] **Staging DB availability.** Is there a staging env, or do I run everything against a local dump? If local-only, I'll be explicit that production deploys carry Phase 1/2 risk we couldn't stage-test.
- [ ] **Downtime tolerance.** Phase 2 migration is designed to be zero-downtime (all `ADD COLUMN IF NOT EXISTS`, no locks that matter on small tables). Confirm you're OK with running it during market hours vs requiring a weekend window.
- [ ] **`users` table origin.** Any idea where it comes from? Search your ops scripts / Coolify config / any external SQL files.
- [ ] **Seed data authority.** When I move the watchlist seed from `schema.sql` to an Alembic data migration, should the data migration be authoritative going forward (anyone adding a new NSE stock edits the migration)? Or will you switch to managing watchlist purely via the dashboard?

Reply inline in the PR that adopts this plan, or amend this doc directly.

---

## 8. Explicitly OUT of scope

To keep the plan bounded:

- Changing any table's column types (widening, narrowing, re-indexing) — separate PRs per table as needed.
- Adding `Decimal` at the Python boundary — that's CLAUDE.md invariant #2, tracked separately.
- Splitting `mcp_server.py` into routers — unrelated.
- Adding a DB backup + restore playbook — assumed to exist; if not, that's a prerequisite not a deliverable.
- Migrating from Postgres to anything else — no.
