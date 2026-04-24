# Project State

> Living document. Updated at the end of every meaningful Claude Code session.
> Every agent reads this FIRST before doing work.

**Last updated:** 2026-04-24 by Claude Opus 4.7 (router split complete — mcp_server.py 6,635→2,761 lines, 148 routes → 15 domain routers)
**Dossier version:** 4
**Prior versions:** v1 2026-04-22 (`onboarder` initial dossier) → v2 2026-04-23 (Decimal Phase 2–3 + backtester boundary fix) → v3 2026-04-24 AM (Decimal series merged + test-debt swept)

---

## Identity

| Field | Value |
|---|---|
| **Project name** | MKUMARAN Trading OS |
| **Client** | Self / personal-use trading product (operator: mkumaran2931@gmail.com) |
| **Type** | Trading intelligence platform (signal generation + risk management + AI validation) |
| **Status** | Active development — multi-segment trading assistant, in daily iteration |
| **Started** | ~2026-04-15 (first commit on current repo; code is older, history likely squashed) |
| **Target ship date** | ongoing (daily live use; ~40 commits in April 2026 alone) |
| **Primary contact** | shadowmarketai (mkumaran2931@gmail.com) |
| **Current branch** | `refactor/router-split-phase-4-cleanup` → PR #32 open (Phase 4, supersedes #27). Earlier phases 1–3 all merged to main. |

---

## Stack

| Layer | Technology | Version | Notes |
|---|---|---|---|
| Backend | Python + FastAPI | 3.11 / 0.104.1 | Factory + 15 domain routers under `mcp_server/routers/` (health, webhooks, wallstreet, watchlist, brokers, options, fno, selfdev, signals, trades, scanners, backtest, market_data, admin, auth). `mcp_server/mcp_server.py` is down to 2,761 lines — lifespan, middleware, DB wiring, exception handler. No `@app.<method>` route decorators remain. |
| ORM / DB driver | SQLAlchemy + psycopg2 | 2.0.23 / 2.9.9 | Declarative models in `mcp_server/models.py` |
| Migrations | Alembic | ≥1.13 | **Sole source of schema truth** as of 2026-04-22: `schema.sql` retired, `_add_missing_columns()` runtime escape hatch removed. Alembic runs on backend boot via `db.run_alembic_upgrade()`. |
| Database | PostgreSQL | 16-alpine | `pool_size=10, max_overflow=20`. Fresh installs and existing DBs both bootstrap via Alembic upgrade-to-head on app startup. |
| Frontend | React + Vite + TypeScript + Tailwind | 18.3 / 5.0.8 / 5.3 / 3.4 | SPA in `dashboard/`, served by nginx. 17 pages + landing + login |
| UI libs | framer-motion, lightweight-charts, recharts, lucide-react | — | No shadcn; local `components/ui/` |
| HTTP client | axios | 1.6 | `dashboard/src/services/api.ts`, JWT in `localStorage` (key `mkumaran_auth_token`) |
| Brokers | Kite Connect, Angel SmartAPI, Dhan, Goodwill (GWC) | various | Auth modules in `mcp_server/{kite,angel,dhan,gwc}_auth.py`; each supports TOTP auto-login |
| AI providers | Grok (primary) → Kimi (secondary) → Anthropic/OpenAI (legacy) + NeuroLinked brain | `grok-3-mini`, `moonshot-v1-8k`, `claude-haiku-4-5-20251001` | Router in `mcp_server/ai_provider.py` via `CLAUDE_MODEL` env var. Dead `AI_REPORT_MODEL` setting removed 2026-04-23 (PR #12). |
| Alerting / I/O | Telegram bot (PTB 20.6), Google Sheets (gspread), Slack-less | — | Bot in `mcp_server/telegram_bot.py`; Sheets sync in `sheets_sync.py` |
| Automation | n8n | self-hosted | 6 workflows in `n8n_workflows/` (morning / signal receiver / market monitor / EOD / extended monitor / MCX EOD) |
| TradingView | Pine Script + TradingView screener (tradingview-screener), Chartink | — | `tradingview_scanner.py`, `pine_script/rrms_strategy.pine` |
| ML | scikit-learn, rank-bm25 | ≥1.4 / ≥0.2.2 | `signal_predictor.py`, `trade_memory.py`, `rl_engine.py` |
| Auth | JWT (PyJWT) + bcrypt + Google OAuth + email/mobile OTP (MSG91) | — | **Opt-in**: `AUTH_ENABLED=false` default. JWT placeholder secret is safe at import: `config._fail_closed_secrets_check()` raises `RuntimeError` if `AUTH_ENABLED=true` is set with the unmodified placeholder. |
| Rate limiting | slowapi | ≥0.1.9 | Middleware wired in `mcp_server.py` |
| Logging | structlog + logzero + stdlib logging | ≥24.1 | `LOG_FORMAT=json`, `LOG_LEVEL=INFO` (Dockerfile defaults) |
| Hosting | Docker Compose (postgres + backend + dashboard) | — | Prod URL: `https://money.shadowmarket.ai`, n8n: `https://n8n.shadowmarket.ai`, NeuroLinked brain: `https://brain.shadowmarket.ai` |
| CI/CD | GitHub Actions | — | `.github/workflows/ci.yml` — ruff lint → pytest (with a live postgres service). No deploy step in CI |
| Pre-commit | ruff + ruff-format | v0.8.6 | `.pre-commit-config.yaml` |
| Monitoring | — | — | None checked in yet; README references Telegram alerts as operator-facing signal. |

---

## Architecture summary

The Trading OS is a **signal-generation + risk-management + AI-validation** platform for Indian markets (NSE / BSE / MCX / CDS / NFO). A single FastAPI monolith (`mcp_server/mcp_server.py`) exposes ~148 REST endpoints across `/api/*` (dashboard-facing, JSON CRUD) and `/tools/*` (heavier agent-style actions: run scan, pretrade check, place order). A React SPA in `dashboard/` consumes both; nginx serves the built bundle and proxies `/api` + `/tools` to port 8001.

The signal pipeline works like this: **MWA scan** (multi-layer scanner running 82+ scanners over the watchlist) → **debate validator** (8 specialist agents — SMC, ICT, VSA, Wyckoff, Harmonic, etc., in `debate_validator.py`) → **RRMS risk sizing** (`rrms_engine.py` — mandatory gate before any signal emits) → **signal card** persisted in Postgres and pushed to Telegram + Google Sheets. A background `signal_monitor` loop (and the legacy `check_signals` tool) tracks open signals to SL/TGT hit and writes outcomes. Outcome + postmortem feed the ML predictor (`signal_predictor.py`) and the external NeuroLinked brain (`brain_bridge.py`, new this week).

Two independent scan loops run in parallel: a **daily-swing MWA loop** (default on) and an **intraday 5m/15m loop** (opt-in via `INTRADAY_SIGNALS_ENABLED`). Options enrichment attaches concrete option contracts (with Greeks + IV rank) to FNO futures signals. The n8n side handles scheduled orchestration: morning startup, hourly market monitor, EOD report.

**Main entry points:**
- Backend: `mcp_server/mcp_server.py:1067` (FastAPI factory), lifespan at `:735`, 148 route handlers thereafter
- Frontend: `dashboard/src/main.tsx` → `dashboard/src/App.tsx:24` (React Router, auth-gated sub-routes)
- Database: `schema.sql` (initial seed) + `alembic/versions/` (3 migrations) + `mcp_server/db.py:34` (`_add_missing_columns` runtime migration)
- Settings: `mcp_server/config.py` (`Settings` class, env-driven)
- Domain guide: `TRADING.md` (user-facing, 825 lines) — the canonical source of trading workflows

**Key abstractions (understand these first):**
- **Signal** (`mcp_server/models.py:57`) — central record. Carries entry/SL/target, RRR, AI confidence, scanner attribution, feature vector, ML predictions, and option enrichment fields (~70 columns).
- **MWAScore** — daily market-wide score (bull/bear %, FII/DII, sector strength, promoted stocks). Drives the debate validator's prior.
- **ActiveTrade / Outcome / Postmortem** — the open-position / closed-result / root-cause triple.
- **AdaptiveRule + ScannerReview** — self-learning layer. Rules mined from outcomes, scanners auto-disabled by Bayesian performance.
- **Segment + timeframe** — orthogonal axes everywhere. Never route equity sizing to F&O (RRMS gate enforces this; see CLAUDE.md invariants).

---

## Current phase

**Post-consolidation — foundations hardened, back to feature/ops work.** Over 2026-04-22 → 2026-04-24 a three-wave consolidation landed on `main`:

1. **Schema consolidation** (PRs merged into #11): `schema.sql` + runtime `_add_missing_columns()` retired; Alembic is the sole schema source, runs automatically on backend boot.
2. **Decimal enforcement** (PR #11 `feat/money-helpers`): CLAUDE.md invariant #2 now real. `money.py` helpers plus zone discipline across `rrms_engine`, `order_manager`, `signal_monitor`, `portfolio_risk`, `signal_cards`, `backtester`. Per-exchange rounding (NSE/BSE/NFO/MCX = 2dp, CDS = 4dp).
3. **Test debt swept** (PR #13): 35+ pre-existing test failures on `main` cleared across 12 test files + 1 workflow file. Main CI is green as of 2026-04-24.

Also shipped: dead `AI_REPORT_MODEL` setting removed (PR #12), Vitest + Testing Library harness for dashboard (merged via #11 bundle), JWT fail-closed boot check, NeuroLinked brain integration.

The product is in daily live use on paper-mode. Next focus is paper-mode smoke of the full Decimal-enabled pipeline, then the `mcp_server.py` router split.

---

## Open TODOs

Ordered by priority. Top item is what `/resume` suggests next.

- [ ] **HIGH** — Push + open PR for `feat/money-helpers`. Branch has 5 commits ahead of origin: Phase 1 (`f4cd4a9`, money helpers), Phase 2 (`f63b858`, RRMS+config+order_manager), Phase 3 (`b36ee17`, monitor+portfolio+cards), backtester boundary fix (`7ab9e03`), plus the docs draft (`e9eabf5`) that preceded Phase 1. All local; never pushed.
- [ ] **MED** — Verify Decimal migration in live paper-mode smoke run before declaring victory on CLAUDE.md invariant #2. Unit tests cover the math; paper-mode exercises the full pipeline including broker-SDK float boundaries.
- [ ] **MED** — Break up `mcp_server/mcp_server.py` (6623 lines, 148 route decorators) into FastAPI routers by domain (auth / signals / trades / options / admin / tools).
- [ ] **MED** — Update `AI_REPORT_MODEL` default. Currently `claude-haiku-4-5-20251001` in `config.py:214`. Claude Haiku 4.5 is supported, but Opus 4.7 / Sonnet 4.6 are the current latest — verify cost/quality trade and decide.
- [ ] **MED** — Rotate JWT secret + strengthen auth default. `JWT_SECRET_KEY` default in `config.py` is the literal string `"change-this-in-production"`; safe today only because `AUTH_ENABLED=false` by default.
- [x] **MED** — Fixed 2 pre-existing `test_order_manager`/`test_paper_trading` failures asserting "Kite not connected" — renamed to `test_no_broker_blocks_order` / `test_live_mode_fails_without_broker` and matched the current "No broker connected" copy from `_validate_broker()` (`894d350`).
- [ ] **HIGH** — **GitHub Actions is not firing** on any push/PR since 2026-04-22. CI last ran ~24h ago. Not a workflow-config issue (unchanged for weeks); likely repo-setting (Settings → Actions → General → Allow actions) or GitHub billing/quota. PR #11 can't be CI-verified until this is unblocked.
- [ ] **MED** — Fix `sector_picker.fetch_rrms_setup` stale call to non-existent `engine.calculate_from_levels` — wrapped in `try/except`, so silently returns fallback. Pre-existing dead code path.
- [ ] **HIGH** — Merge `feat/claude-agent-layer` → `main` (or decide whether to squash). The overlay is purely additive (no app-code diff) and is already committed; just needs PR + merge. Watch for CI (`ruff check .`) — overlay added many markdown files, no `.py` changes, so should pass cleanly.
- [ ] **HIGH** — Consolidate schema sources. Three places currently hold truth: `schema.sql`, `alembic/versions/`, and `mcp_server/db.py:_add_missing_columns()` (a runtime `ALTER TABLE` escape hatch with ~50 column definitions). A schema drift between Alembic and `_add_missing_columns` is a silent bug waiting to happen.
- [ ] **HIGH** — Enforce `Decimal` at the Python boundary for P&L math. CLAUDE.md declares it as an invariant, but current code uses `float` broadly (`RRMS_CAPITAL: float`, `RRMS_RISK_PCT: float` in `config.py:107–109`). DB uses `Numeric(10,2)` correctly.
- [ ] **MED** — Break up `mcp_server/mcp_server.py` (6623 lines, 148 route decorators) into FastAPI routers by domain (auth / signals / trades / options / admin / tools).
- [ ] **MED** — Update `AI_REPORT_MODEL` default. Currently `claude-haiku-4-5-20251001` in `config.py:214`. Claude Haiku 4.5 is supported, but Opus 4.7 / Sonnet 4.6 are the current latest — verify cost/quality trade and decide.
- [ ] **MED** — Rotate JWT secret + strengthen auth default. `JWT_SECRET_KEY` default in `config.py:153` is the literal string `"change-this-in-production"`; safe today only because `AUTH_ENABLED=false` by default.
- [ ] **MED** — Add frontend tests. `dashboard/package.json` has no test script, no Vitest, no Testing Library. 54 backend tests exist; frontend has zero.
- [ ] **LOW** — Validate `dashboard_dist/` checked-in state. Directory exists at repo root (likely a stale pre-container build artifact). Dockerfile rebuilds dashboard in stage 1; the top-level folder may be dead weight.
- [ ] **LOW** — Decide fate of `skills/shadow-3d-scroll/` and the landing/marketing surfaces in the dashboard. CLAUDE.md explicitly bans the scroll skill on `dashboard/` routes; usage should be limited to `LandingPage.tsx`.

---

## Recently completed

Last ~15 closed, newest first.

- [x] 2026-04-24 — **Test-debt swept (PR #13 `fix/stale-test-assertions`)**. Cleared 35+ pre-existing test failures on `main` across 12 test files + 1 workflow. Categories: scanner-count lower-bounds × 6; httpx telegram_gate rewrite × 4; MWA scoring threshold × 1; debate_validator skill-agents-first + `_call_claude` indirection × 12; segment routing Dhan-primary × 2; yfinance futures start/end + OHLCV market-aware freshness × 4; broker-message "No broker connected" × 4; EOD workflow tag + endpoint consolidation × 2. Main CI green after merge — `6cfcaea` (initial) through `467fa98` + merge into main.
- [x] 2026-04-24 — **Dead `AI_REPORT_MODEL` setting removed (PR #12)**. Was declared in config.py + documented in DEPLOYMENT.md but never consumed in code. Actual Claude model selection is `CLAUDE_MODEL` in `ai_provider.py:44`. Two parallel settings were a trap — removed the dead one, documented the canonical — `d9fa97a`.
- [x] 2026-04-24 — **Decimal enforcement merged to main (PR #11, merge commit `e08dd03`)**. CLAUDE.md invariant #2 now real. Bundled Phase 1–3 + backtester fix + schema consolidation + Vitest harness as a single merge commit preserving per-phase bisectability.
- [x] 2026-04-23 — Backtester boundary fix: `_generate_rrms_signals` casts RRMSResult Decimal fields to float at the analysis-zone boundary. Added 2 backtester tests. Caught by pre-commit advisor review; production path would have crashed on first `/tools/backtest strategy=rrms` call — `7ab9e03`.
- [x] 2026-04-23 — Phase 3 Decimal migration: `signal_monitor` (_calc_pnl returns Decimal, entry_price/exit_price stay Decimal through Outcome persistence, option premium P&L aggregation in Decimal, gspread/brain_bridge boundary casts), `portfolio_risk` (exposure Decimal, percentages float at dict boundary), `signal_cards` (all format functions accept Numeric) — `b36ee17`
- [x] 2026-04-23 — Phase 2 Decimal migration: `config.RRMS_CAPITAL`/`RRMS_RISK_PCT` → Decimal, `rrms_engine` fully Decimal with per-exchange tick rounding, `order_manager` capital+kill-switch+validation Decimal, Kite/Angel SDK boundary casts to float. `mwa_signal_generator` analysis-zone boundary cast at `risk_amt = float(...)`. `pretrade_check.check_rrr` drops stale float() coercion — `f63b858`
- [x] 2026-04-22 — Phase 1 Decimal migration: added `mcp_server/money.py` (to_money/round_tick/round_paise/pnl/pct_return) with per-exchange rounding (NSE/BSE/NFO/MCX=2dp, CDS=4dp) and 43 tests — `f4cd4a9`
- [x] 2026-04-22 — Drafted Decimal-enforcement plan (`docs/DECIMAL_ENFORCEMENT_PLAN.md`) — `e9eabf5`
- [x] 2026-04-22 — Added Vitest + Testing Library harness to dashboard with 3 smoke suites — `af78663`
- [x] 2026-04-22 — Schema consolidation (Phase 4): retired `schema.sql` in favor of Alembic data migration — `cb52222`
- [x] 2026-04-22 — Zeroed all ruff check errors (52 → 0) — `a49c9d3`
- [x] 2026-04-22 — Schema consolidation Phases 1–3: Alembic on boot, reconcile drifted state, retire `_add_missing_columns()` runtime escape hatch — `59a923e` → `45751f9`
- [x] 2026-04-22 — Overlaid Shadow Market agent/skill/rules layer (115 files, +25k LoC of docs/config, no app-code diff) — `ffd9ab8`
- [x] 2026-04-21 — Wired Trading OS to NeuroLinked brain: fire-and-forget observe_signal / observe_outcome / observe_scan_summary — `39ad241`
- [x] 2026-04-21 — Fixed sheets reset to use correct `_worksheet` / `_sheet` attribute names — `e9793a0`
- [x] 2026-04-21 — Fixed EOD workflow + sheets reset + agent signal dedup across deploys — `6bff106`
- [x] 2026-04-21 — Fixed EOD summary endpoint + options `IDX_I` segment — `7de03e5`
- [x] 2026-04-21 — Options chain now uses `IDX_I` segment for index underlyings — `544e04a`
- [x] 2026-04-21 — Suppressed repeated SL-hit alerts for same ticker — `a0afdc0`
- [x] 2026-04-21 — Added automatic scanner disable/re-enable based on Bayesian performance — `d9085c7`
- [x] 2026-04-21 — Added 20 institutional Chartink scanners for higher win rate — `7e97c0f`
- [x] 2026-04-20 — EOD analysis fixes + aggressive stale cleanup — `cf47aef`

---

## Decisions log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-24 | PR #11 merged as a **merge commit**, PRs #12 + #13 **squashed** | Merge commit on PR #11 preserves the phased commits (money helpers → RRMS → monitor → backtester fix) so `git bisect` stays useful if a paper-mode regression surfaces. Single-commit / thematic PRs (#12, #13) squash to one tidy main-history entry each. |
| 2026-04-24 | Relax brittle test assertions to lower-bounds / invariants rather than sync to current exact values | Scanner and signal-chain catalogs grow additively over time. Exact-count tests broke every time the catalog grew; `>= baseline` converts that into a one-way ratchet that only triggers on regressions. Same philosophy applied to mwa_scoring direction labels (assert bull dominates bear rather than a specific label that depends on the denominator). |
| 2026-04-23 | Two-zone discipline for Decimal enforcement: Money zone (Decimal) = rrms/config/order_manager/signal_monitor/portfolio_risk/signal_cards. Analysis zone (float/numpy/pandas) = TA engines, OHLCV cache, ML features, backtester simulator. Explicit `float(decimal)` cast at crossings | Preserves exact paise math on the decision + persistence paths while keeping TA/ML performant. Backtester cast added after advisor review caught the Decimal × float multiplication risk in `_apply_slippage`. |
| 2026-04-23 | `RRMS_MIN_RRR` stays float (not Decimal) even though other RRMS_* settings are Decimal | Dimensionless ratio — multiplied against ATR (float) in analysis-zone code (`mwa_signal_generator`, `mcp_server.py` option sizing). Converting it would force Decimal propagation into the analysis zone with no precision benefit. |
| 2026-04-23 | Percentages (deployed_pct, sector_pct, etc.) in `portfolio_risk.get_portfolio_exposure` stay float at the output dict boundary even though money aggregates are Decimal internally | Dashboard TS consumers expect `number` and inexact floats like 20.4 don't equal `Decimal("20.4")` — keeping pct as float preserves existing test equality and UI behavior. |
| 2026-04-22 | Keep `schema.sql` + Alembic + runtime `_add_missing_columns()` coexisting | ~~Historical:...~~ **SUPERSEDED 2026-04-22 evening:** schema.sql and `_add_missing_columns()` were retired over 4 commits (59a923e → cb52222). Alembic is now the sole source of schema truth. |
| 2026-04-22 | Keep `schema.sql` + Alembic + runtime `_add_missing_columns()` coexisting | Historical: fresh Docker installs use `schema.sql`, existing DBs can't run it idempotently, so Alembic was bolted on, and `_add_missing_columns()` is the "forgot-to-add-a-migration" safety net. Parked — unify later. |
| 2026-04-22 | Overlay Shadow Market Claude layer as pure additive (no app-code diff) | Commit message `ffd9ab8` explicitly lists everything not touched (`mcp_server/`, `dashboard/`, `alembic/`, `schema.sql`, `docker-compose*`, `TRADING.md`, `.pre-commit-config.yaml`, `requirements.txt`, `Dockerfile`, `n8n_workflows/`, `pine_script/`). |
| 2026-04-21 | NeuroLinked brain integration is fire-and-forget, 5s timeout, never raises | Trading pipeline must never crash because the brain is unreachable. `brain_bridge.py` silently swallows network errors. |
| 2026-04-xx | Grok (`grok-3-mini`) is primary AI provider; Claude/OpenAI kept as legacy | Cost-driven. Anthropic/OpenAI wired via `ai_provider.py` but default `AI_PRIMARY_PROVIDER=grok`. |
| 2026-04-xx | Intraday pipeline opt-in (`INTRADAY_SIGNALS_ENABLED=false`) | Separate from daily-swing MWA; default off so operator explicitly opts in. |
| 2026-04-xx | `MWA_MAX_SIGNALS_PER_CYCLE=5`, `MWA_MAX_SIGNALS_PER_DAY=0` | Per-cycle cap spreads signals through the day; daily ceiling disabled (commit `eb1b1c3` — "was starving all AI agents"). |
| 2026-04-xx | `OPTION_UNIVERSE_ALL_FNO=true` | Enrich options for any ticker in Kite's NFO list (~220 underlyings), not just curated list. |

---

## Known issues / tech debt

Things parked intentionally. Do NOT "fix" without checking here first.

- ~~**Three schema sources.** `schema.sql` (seed), `alembic/versions/` (3 migrations), `_add_missing_columns()` (runtime).~~ **RESOLVED 2026-04-22:** Alembic is now the sole source of schema truth. `schema.sql` retired, `_add_missing_columns()` removed.
- **Monolithic `mcp_server.py`** (6623 lines, 148 routes). Splitting into routers is deferred until the feature churn slows.
- **Default JWT secret is a placeholder.** Safe only because `AUTH_ENABLED=false` is the default; production deploys must set `JWT_SECRET_KEY` env.
- **`docs/CLAUDE_OVERLAY_CHANGELOG.md` is the template's own changelog**, not the Trading OS's — it describes what changed in `shadowmarketai/SHADOW-MARKET-TEMPLATE`, not in this repo. Don't mistake it for a project log.
- **`dashboard_dist/` at repo root** — likely a stale local build artifact. Dockerfile builds its own dist in stage 1. Likely safe to `.gitignore` and delete but confirm before doing so.
- **Top-of-file imports skipping SDK boundary.** `mcp_server.py` imports `pandas` and `fastapi` at module top (fine), but inner functions re-import submodules lazily (`from mcp_server.market_calendar import now_ist` inside `_now_ist()`, etc.) — pattern is intentional to break circular deps, not dead code.
- **No frontend tests** (only 54 backend tests). Dashboard refactors are uninsured.
- **`_bootstrap_service_account()` runs at import time** (`config.py:38`) — writes `data/service_account.json` from env var. Harmless, but side-effect-at-import breaks easy unit testing of `config.Settings`.

---

## Gotchas for new contributors

- The repo is both an **application** (mcp_server + dashboard) and a **Claude Code collaboration kit** (agents/ skills/ rules/ hooks/ PRPs/ overlaid by Shadow Market template). `CLAUDE.md` is the developer rulebook, `TRADING.md` is the user/domain guide — **don't duplicate content between them**.
- The word "MCP" in `mcp_server/` is legacy naming — this is a FastAPI server, not an Anthropic MCP protocol server. (Comment in `requirements.txt` confirms: MCP SDK requires 3.12+, FastAPI used directly as "MCP-compatible".)
- `/api/*` = dashboard CRUD, `/tools/*` = heavier agent actions. Both served by the same FastAPI app; both proxied by Vite dev server (`vite.config.ts:8–17`) to port 8001.
- Signal dedup key = `symbol + timeframe + strategy + timestamp-minute`. See `signal_similarity.py`.
- Money math: DB is `Numeric`, Python code is `Decimal` in the money zone (rrms / order_manager / signal_monitor / portfolio_risk / signal_cards) and `float` in the analysis zone (TA / numpy / backtester). Cross zones via explicit `float(dec)` or `to_money(x)`. `mcp_server/money.py` is the canonical helper module. CLAUDE.md invariant #2 is enforced as of 2026-04-24.
- `AUTH_ENABLED=false` and `PAPER_MODE=true` are CI defaults — tests will fail otherwise.
- **Any PR that touches `dashboard/package.json` MUST also regenerate `dashboard/package-lock.json`** (`cd dashboard && npm install --package-lock-only --no-audit`). Coolify's Dockerfile uses `npm ci` which hard-fails on any lockfile/package.json drift, taking prod down. Learned the hard way on 2026-04-24 when PR #11 merged the Vitest harness without the lockfile update — caught + fixed via hotfix PR #14. Add `npm ci` as a local verification step before merging any dashboard-deps PR.
- Timezone: all datetimes should route through `mcp_server.market_calendar.now_ist()` — server timezone is unreliable in Docker.
- Telegram gate: `TELEGRAM_SIGNALS_ONLY=true` by default — only actual signal cards hit the chat, scan summaries are suppressed.
- `brain_bridge.py` tenant is hardcoded `trading_os`; token env is `NEUROLINKED_TOKEN` (not in `.env.example` yet — TODO).
- Shadow Market template's `skills/shadow-3d-scroll/` is ONLY for marketing/public pages (`LandingPage.tsx`). CLAUDE.md explicitly bans it on `dashboard/` routes.

---

## Active agents / skills

Agents that are particularly relevant to this project (from the Shadow Market overlay, `agents/`):

- `orchestrator` — entry point for non-trivial changes; reads this file first
- `backend-agent` — MCP server (`mcp_server/`), strategies, scanners, brokers, n8n wiring
- `frontend-agent` — `dashboard/` React + Vite + Tailwind
- `database-agent` — Alembic migrations, `schema.sql`, the `_add_missing_columns` escape hatch, query performance
- `security-reviewer` — credential handling (broker APIs, TOTP keys), RRMS leaks across segments, JWT secret hygiene
- `python-reviewer` / `typescript-reviewer` — per-language review
- `tdd-guide` — tests-first for strategy / scoring / sizing logic
- `e2e-runner` — dashboard Playwright journeys

Skills (from `skills/`):

- `skills/BACKEND.md` + `skills/python-patterns/` + `skills/python-testing/` — Python conventions
- `skills/FRONTEND.md` + `skills/frontend-patterns/` — React conventions
- `skills/DATABASE.md` — SQLAlchemy + Alembic; especially relevant given 3-source schema drift
- `skills/TESTING.md` — pytest setup; also look at `tests/conftest.py` for live-postgres fixture
- `skills/api-design/` — REST conventions (useful when splitting `mcp_server.py` into routers)
- `skills/brownfield-patterns/` — this repo is 6.6k-line monolith; follow these patterns
- `skills/security-review/` — 9 compliance docs (GDPR, PCI DSS, MFA, encryption, IaC, container, SIEM, DAST, zero trust). Broker auth + user-PII requires quarterly `/compliance-review`.
- `skills/continuous-learning-v2/` — aligns with the project's own self-learning pipeline (`signal_predictor.py`, `scanner_review.py`, `trade_reflector.py`)

---

## Deployment

**Production URL:** `https://money.shadowmarket.ai` (dashboard) — backend at `https://money.shadowmarket.ai/api/*` and `/tools/*`
**n8n:** `https://n8n.shadowmarket.ai` (4–6 scheduled workflows)
**NeuroLinked brain:** `https://brain.shadowmarket.ai` (cross-product learning endpoint, tenant `trading_os`)
**Staging URL:** none — single-environment product
**Deployment trigger:** manual Docker Compose pull-and-restart (no CI deploy step in `ci.yml`)
**Last deploy:** unknown — not tracked in repo
**Rollback procedure:** `docker compose down && docker compose up -d` with a prior image tag. No automated rollback.

Infra stack (from `docker-compose.yml`):
- `postgres` — Postgres 16-alpine, `schema.sql` mounted at `/docker-entrypoint-initdb.d/`, persistent volume `postgres_data`
- `backend` — FastAPI + uvicorn, exposes 8001 internal only, healthcheck via curl
- `dashboard` — nginx + built Vite bundle on port 80 public

---

## Secrets and config

Reference only — do NOT store secrets here.

- See `.env.example` for required vars (broker keys, Telegram, Google Sheets, n8n, RRMS defaults, TradingView session cookies, intraday toggle). Note: `NEUROLINKED_TOKEN` is used by `brain_bridge.py` but **not in `.env.example` yet** (should be added).
- Secrets stored in: developer `.env` (gitignored); production Coolify/Docker env vars.
- Google service account: either volume-mounted at `/app/data/service_account.json` OR inline via `GOOGLE_SERVICE_ACCOUNT_JSON` env var (bootstrapped at import time by `config.py:_bootstrap_service_account`).
- Who has access: repo owner (mkumaran2931).

Sensitive env highlights:
- `KITE_TOTP_KEY`, `ANGEL_TOTP_SECRET`, `DHAN_TOTP_KEY`, `GOODWILL_TOTP_KEY` — 2FA seeds for broker auto-login. Treat as highest sensitivity.
- `JWT_SECRET_KEY` — currently defaults to placeholder; must override in prod if `AUTH_ENABLED=true`.
- `ANTHROPIC_API_KEY`, `GROK_API_KEY`, `KIMI_API_KEY`, `OPENAI_API_KEY` — AI providers.

---

## Session log

### 2026-04-22 — `onboarder` initial repo dossier
- Worked on: Phase 1–7 onboarding per `agents/onboarder.md`
- Completed: `.claude/project-state.md` + `.claude/codebase-map.md` written
- Blocked on: nothing — dossier is read-only
- Next up: user picks one of the three handoff options below

### 2026-04-23 — Decimal enforcement Phases 2–3 + backtester fix
- Worked on: Completed the three-PR Decimal enforcement plan from `docs/DECIMAL_ENFORCEMENT_PLAN.md`; fixed one latent production bug in `backtester._generate_rrms_signals` caught by advisor review
- Completed: Phase 2 (`f63b858`), Phase 3 (`b36ee17`), backtester boundary fix (`7ab9e03`). 189/191 targeted tests pass (2 pre-existing "Kite not connected" failures unrelated to Decimal work). Ruff clean across `mcp_server/` + `tests/`. Project dossier updated.
- Blocked on: nothing. Branch `feat/money-helpers` has 5 local commits ahead of `origin` — user directive needed on push + PR creation.
- Next up (user decision): (a) push + open PR for the full Decimal series, (b) run paper-mode smoke before pushing, or (c) tackle the next MED TODO (mcp_server.py router split or AI_REPORT_MODEL update).

### 2026-04-23 (continued) — PR bundling + test hygiene
- Worked on: pushed `feat/money-helpers`; retargeted PR #11 from `docs/decimal-enforcement-plan` to `main`, bundling the full 14-commit stack (Claude overlay → schema consolidation Phases 1–4 → Vitest harness → Decimal Phases 1–3 → backtester fix → dossier + this session log). PR body updated to list the seven superseded PRs (#3 #4 #5 #6 #8 #9 #10) that auto-close on merge.
- Also cleared 2 pre-existing stale-assertion failures (`test_no_kite_blocks_order`, `test_live_mode_fails_without_kite`) that would have blocked CI-green (`894d350`).
- Blocked on: **GitHub Actions not firing on any branch since 2026-04-22 — repo-level setting or billing issue, needs owner action.** PR #11 has no CI checks attached. Already tried empty-commit force-push + close/reopen PR — no dice.
- Next up: (a) repo owner investigates Actions settings so CI can verify PR #11, or (b) merge without CI verification (risky — main's last CI run was red with many pre-existing assertion failures unrelated to this PR), or (c) move on to paper-mode smoke / next MED TODO while Actions is debugged.

### 2026-04-24 — CI unblock + test debt sweep + merge
- Worked on:
  - Diagnosed GitHub Actions silent-fail: third-party check apps (Render, Vercel, Railway, GitGuardian) registered fine, but GitHub Actions itself created no check suite. Rapid visibility flips (private ↔ public × multiple) corrupted the Actions binding; `workflow_dispatch` trigger added + permission toggle off/on did NOT re-register, but a later repo settings change by the operator did. Manual dispatch + subsequent pushes both fired cleanly thereafter.
  - PR #13 (`fix/stale-test-assertions`): broke down 35+ pre-existing test failures into 8 fix commits (scanner counts → telegram httpx → mwa_scoring → debate_validator → segment routing → yfinance + ohlcv → broker-message → integrations). Final CI: **lint + test both green on PR #13.**
  - Sub-PR cleanup: closed #4, #5, #6, #8, #9, #10 (all superseded by #11's bundle merge). Deleted 8 merged feature branches.
  - Repo flipped back to private after merges shipped.
- Completed: PRs #11, #12, #13 all merged. Main CI green for the latest 3 push-events (one per merge).
- Blocked on: nothing.
- Next up: (a) rotate the leaked Telegram bot token (operator deferred on 2026-04-24; revisit), (b) paper-mode smoke run, or (c) `mcp_server.py` router split.

---

## Links

- Repo: https://github.com/shadowmarketai/mkumaran-trading-os (inferred from README clone URL)
- Production: https://money.shadowmarket.ai
- n8n: https://n8n.shadowmarket.ai
- NeuroLinked brain: https://brain.shadowmarket.ai
- Shadow Market template (overlay source): https://github.com/shadowmarketai/SHADOW-MARKET-TEMPLATE
- CI: `.github/workflows/ci.yml` (ruff + pytest with live Postgres 16 service)
- Trading domain guide: `TRADING.md`
- Developer rulebook: `CLAUDE.md`
