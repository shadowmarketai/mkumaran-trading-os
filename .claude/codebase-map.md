# Codebase Map

> What lives where. Updated when structure changes significantly.

**Last updated:** 2026-04-22 by `onboarder`

---

## Navigation guide

For a new developer (or Claude session) joining this repo, read in this order:

1. This file
2. `.claude/project-state.md` — current state + open TODOs + decisions
3. `CLAUDE.md` — developer rulebook (forbidden patterns, invariants, agent coordination)
4. `TRADING.md` — user/domain guide (signal cards, RRMS, debate validator, workflows)
5. `README.md` — ops-facing quick-start
6. The entry point for the layer you're working on (see below)

---

## Directory tree (annotated)

```
mkumaran-trading-os-fresh/
├── mcp_server/                      # ★ Python backend (FastAPI monolith)
│   ├── mcp_server.py                # ★ 6623 lines, 148 routes. FastAPI factory @ :1067, lifespan @ :735
│   ├── config.py                    # ★ Settings class (env-driven). Broker keys, AI providers, RRMS defaults
│   ├── db.py                        # ★ SQLAlchemy engine + Session. Runtime _add_missing_columns() escape hatch @ :34
│   ├── models.py                    # ★ ORM: Watchlist, Signal (~70 cols), Outcome, MWAScore, ActiveTrade, Postmortem, AdaptiveRule, ScannerReview
│   ├── asset_registry.py            # Ticker parsing, exchange detection, FNO-eligible list
│   ├── market_calendar.py           # ★ IST timezone + is_market_open() — use this, never server TZ
│   │
│   ├── ── Data & brokers ─────────────────────────────────────────
│   ├── data_provider.py             # Kite primary → yfinance fallback
│   ├── ohlcv_cache.py               # Postgres-backed OHLCV cache with tenant_id
│   ├── realtime_engine.py           # WebSocket live feed (optional Redis tick cache)
│   ├── kite_auth.py / kite_execution.py
│   ├── angel_auth.py                # Angel One SmartAPI + TOTP auto-login
│   ├── dhan_auth.py                 # Dhan TOTP + PIN auto-login (retries respect 2-min rate limit)
│   ├── gwc_auth.py / auth_providers.py / auth.py  # Goodwill + local JWT/bcrypt + OAuth
│   │
│   ├── ── Scanners (signal sourcing) ─────────────────────────────
│   ├── mwa_scanner.py               # ★ 98-scanner multi-weighted-average engine (the primary source)
│   ├── mwa_scoring.py / mwa_signal_generator.py
│   ├── intraday_scanner.py          # Opt-in 5m/15m ORB + VWAP + momentum
│   ├── nse_scanner.py / nfo_scanners.py / commodity_scanners.py / forex_scanners.py
│   ├── technical_scanners.py / tradingview_scanner.py  # TV screener bridge
│   ├── scanner_bayesian.py          # Auto-disable/re-enable scanners by win rate
│   ├── scanner_review.py            # Daily scanner post-hoc review
│   │
│   ├── ── Analysis engines (the "6 engines") ─────────────────────
│   ├── pattern_engine.py            # Flags, triangles, wedges, H&S
│   ├── smc_engine.py / smart_money_concepts.py  # Order blocks, FVGs, BoS
│   ├── wyckoff_engine.py            # Accumulation/distribution phases
│   ├── vsa_engine.py                # Volume spread analysis
│   ├── harmonic_engine.py           # Gartley/Butterfly/Bat/Crab/ABCD
│   ├── rl_engine.py                 # Regime detection + VWAP dev + momentum
│   │
│   ├── ── Validation + risk + execution ──────────────────────────
│   ├── debate_validator.py          # ★ 8-specialist-agent debate → consensus confidence
│   ├── validator.py / signal_validator.py / signal_rules.py
│   ├── rrms_engine.py               # ★ MANDATORY risk gate. Capital × risk% × ATR sizing
│   ├── rules_engine.py              # Mined rules from postmortems
│   ├── pretrade_check.py            # Last-mile gate before order
│   ├── order_manager.py             # Kite live + paper mode
│   ├── portfolio_risk.py            # Portfolio-level exposure limits
│   │
│   ├── ── Monitoring + outcome + learning ────────────────────────
│   ├── signal_monitor.py            # ★ Background loop: tracks OPEN signals to SL/TGT hit. Writes outcomes. Brain bridge hook.
│   ├── signal_postmortem.py         # Claude-assisted RCA on closed trades
│   ├── signal_features.py / signal_similarity.py / signal_cards.py
│   ├── signal_predictor.py          # scikit-learn loss-probability classifier (retrains 4PM IST)
│   ├── trade_memory.py / trade_reflector.py  # BM25 memory + lessons
│   ├── tier_guard.py / tier_monitor.py
│   │
│   ├── ── Options ────────────────────────────────────────────────
│   ├── options_signal_engine.py     # 6 standalone F&O strategies
│   ├── options_selector.py          # Pick contract (ATM/OTM/ITM, IV rank, delta target)
│   ├── options_greeks.py            # Black-Scholes Greeks
│   ├── options_payoff.py            # Multi-leg payoff
│   ├── fno_analytics_monitor.py     # IV rank / PCR / OI / expiry alerts
│   ├── fo_module.py / volatility.py
│   │
│   ├── ── Integrations ───────────────────────────────────────────
│   ├── telegram_bot.py / telegram_receiver.py / telegram_saas.py
│   ├── sheets_sync.py               # gspread, handles _worksheet/_sheet attr rename (fix e9793a0)
│   ├── brain_bridge.py              # ★ NEW 2026-04-21. Fire-and-forget → brain.shadowmarket.ai
│   ├── news_monitor.py / earnings_calendar.py
│   ├── fii_dii_filter.py / sector_filter.py / sector_picker.py / delivery_filter.py
│   ├── momentum_ranker.py           # 12M/6M/3M returns + inverse vol rebalance
│   ├── wallstreet_tools.py          # Fundamental analysis (DCF, earnings briefs)
│   ├── stitch_mcp/ + stitch_sync.py # Stitch Data ETL → warehouse
│   │
│   ├── ── Core helpers ──────────────────────────────────────────
│   ├── ai_provider.py               # ★ Grok (primary) → Kimi → Claude → OpenAI routing
│   ├── prompts.py                   # All LLM system prompts
│   ├── backtester.py / backtest_validation.py
│   ├── logging_config.py
│   ├── skills/                      # (empty — reserved)
│   └── agents/                      # Python-side agents (NOT Claude Code agents — see agents/ at root)
│       ├── base_agent.py
│       ├── orchestrator.py
│       ├── options_index_agent.py / options_stock_agent.py
│       ├── futures_agent.py / commodity_agent.py / forex_agent.py
│       └── skills/                  # (empty — reserved)
│
├── dashboard/                       # ★ React 18 + Vite 5 + TypeScript 5 + Tailwind 3
│   ├── src/
│   │   ├── main.tsx                 # React bootstrap
│   │   ├── App.tsx                  # ★ Router. Landing + Login public, everything else ProtectedRoute
│   │   ├── index.css                # Tailwind entry
│   │   ├── pages/                   # 17 pages: Overview, ActiveTrades, Accuracy, Watchlist,
│   │   │                            # Backtesting, Engines, WallStreet, News, Momentum,
│   │   │                            # Options, Payoff, PaperTrading, SignalMonitor,
│   │   │                            # MarketMovers, Settings, Landing, Login
│   │   ├── components/
│   │   │   ├── layout/              # Sidebar, TopBar
│   │   │   ├── ui/                  # Local primitives (NOT shadcn)
│   │   │   └── ProtectedRoute.tsx   # JWT gate
│   │   ├── context/                 # AuthContext (JWT in localStorage, key mkumaran_auth_token)
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── services/
│   │   │   └── api.ts               # ★ Axios instances: /api (CRUD) + /tools (agent actions). 401 → /login redirect
│   │   └── types/                   # Signal, ActiveTrade, MWAScore, etc.
│   ├── public/
│   ├── package.json                 # ★ NO test script, NO Vitest — frontend untested
│   ├── vite.config.ts               # Dev proxy /api + /tools → :8001
│   ├── tailwind.config.ts
│   ├── tsconfig.json / tsconfig.node.json
│   ├── Dockerfile                   # Production nginx stage
│   ├── nginx.conf
│   └── index.html
│
├── dashboard_dist/                  # ⚠ Stale local build artifact? Dockerfile rebuilds its own dist. Check before deleting.
│
├── alembic/                         # DB migrations (3 files)
│   └── versions/
│       ├── 44cb7fb01bfb_initial_schema.py
│       ├── b2c3d4e5f6a7_multi_auth_byok.py
│       └── c3d4e5f6a7b8_users_registration.py
├── alembic.ini                      # prepend_sys_path=., DATABASE_URL overridden by env.py
├── schema.sql                       # ★ Initial DDL + seed data (NSE/MCX/CDS/NFO watchlist). Auto-loaded by postgres container.
│
├── tests/                           # 54 pytest files
│   ├── conftest.py                  # Fixtures (live Postgres assumed via DATABASE_URL)
│   ├── test_mwa_scanner.py / test_mwa_scoring.py / test_mwa_signal_generator.py
│   ├── test_rrms.py / test_debate_validator.py / test_validator_debate_wiring.py
│   ├── test_smc_engine.py / test_wyckoff_engine.py / test_vsa_engine.py / test_harmonic_engine.py
│   ├── test_options_greeks.py / test_options_payoff.py
│   ├── test_signal_monitor.py / test_signal_rules.py / test_signal_cards.py
│   ├── test_backtester.py / test_backtest_compare.py / test_backtest_validation.py
│   ├── test_api_endpoints.py / test_health.py / test_auth.py
│   ├── test_paper_trading.py / test_pretrade_check.py / test_order_manager.py
│   ├── test_trade_memory.py / test_trade_memory_bootstrap.py / test_trade_reflector.py
│   ├── test_portfolio_risk.py / test_news_monitor.py / test_earnings_calendar.py
│   ├── test_asset_registry.py / test_ohlcv_cache.py / test_market_calendar.py
│   ├── test_segment_routing.py / test_filters.py / test_fo_module.py
│   ├── test_forex_scanners.py / test_commodity_scanners.py / test_technical_scanners.py
│   ├── test_tradingview_scanner.py / test_momentum_ranker.py / test_sector_picker.py
│   ├── test_accuracy_improvements.py / test_critical_fixes.py / test_integrations.py
│   ├── test_config_models.py / test_data_provider.py / test_rl_engine.py
│   ├── test_patterns.py / test_prompts.py / test_watchlist.py / test_wallstreet.py
│   └── test_telegram_gate.py
│
├── n8n_workflows/                   # 6 scheduled workflows
│   ├── 00_morning_startup.json      # 8:45 AM: MWA scan + momentum + summary
│   ├── 01_signal_receiver.json      # Webhook → BM25 → Claude → Telegram
│   ├── 02_market_monitor.json       # 30min poll: news + HIGH-impact alerts
│   ├── 03_eod_report.json           # 3:30 PM: P&L + reflection + rebalance
│   ├── 04_extended_market_monitor.json
│   └── 05_mcx_eod_report.json
│
├── pine_script/
│   └── rrms_strategy.pine           # TradingView RRMS strategy
│
├── scripts/                         # One-off dev scripts
│   ├── chartink_debug.py / chartink_setup.py  # Scanner debugging
│   ├── refresh_tv_cookies.py                   # TradingView session cookie refresh
│   └── hash_password.py                         # bcrypt helper for ADMIN_PASSWORD_HASH
│
├── docs/
│   ├── CLAUDE_OVERLAY_CHANGELOG.md  # ⚠ This is the template's changelog, not this project's
│   ├── options_greeks_payoff_guide.md
│   └── wallstreet_prompts_reference.md
│
├── data/                            # (gitignored runtime data: service_account.json, trade_memory.json, etc.)
│
├── ── Shadow Market overlay (added 2026-04-22, pure additive) ──────
├── .claude/
│   ├── project-state.md             # ★ living state doc (read first)
│   ├── codebase-map.md              # ★ this file
│   ├── commands/                    # 18 slash commands (onboard-repo, generate-prp, execute-prp,
│   │                                # tdd, code-review, verify, security-review, compliance-review,
│   │                                # e2e, resume, build-fix, learn, plan, new-client, setup-project, ...)
│   └── templates/                   # project-state.template.md, codebase-map.template.md
│
├── agents/                          # ★ Claude Code specialist agents (14 files)
│   ├── ORCHESTRATOR.md              # Entry point for non-trivial tasks
│   ├── onboarder.md                 # Read-only first-contact (this agent)
│   ├── planner.md                   # Feature planning
│   ├── backend-agent.md / frontend-agent.md / database-agent.md / devops-agent.md
│   ├── security-reviewer.md / code-reviewer.md
│   ├── python-reviewer.md / typescript-reviewer.md
│   ├── tdd-guide.md / e2e-runner.md / build-error-resolver.md
│
├── skills/                          # ~30 skill packs
│   ├── BACKEND.md / FRONTEND.md / DATABASE.md / TESTING.md / DEPLOYMENT.md  (layer skills)
│   ├── api-design/ python-patterns/ python-testing/ frontend-patterns/ e2e-testing/
│   ├── docker-patterns/ tdd-workflow/ coding-standards/ brownfield-patterns/ token-budget/
│   ├── continuous-learning-v2/      # Self-learning pipeline (pairs with this repo's own predictor)
│   ├── security-review/             # SKILL.md + 9 compliance sub-docs
│   │   ├── gdpr-compliance.md / pci-dss-compliance.md / zero-trust-architecture.md
│   │   ├── dast-pen-testing.md / siem-observability.md / end-user-mfa.md
│   │   ├── application-encryption.md / iac-security-scanning.md
│   │   ├── container-image-scanning.md / cloud-infrastructure-security.md
│   └── shadow-3d-scroll/            # ⚠ MARKETING ONLY — never on dashboard/ routes
│
├── rules/                           # Language rule packs
│   ├── common/                      # security, testing, coding-style, code-review, git-workflow, performance
│   ├── python/                      # coding-style, patterns, security, testing, hooks
│   └── typescript/                  # coding-style, patterns, security, testing, hooks
│
├── hooks/
│   └── hooks.json                   # Claude Code session/edit/pre-commit hooks (complementary to .pre-commit-config.yaml)
│
├── PRPs/
│   └── marketing-page-prp.md        # Product Requirements Prompt blueprint
│
├── ── Root files ───────────────────────────────────────────────
├── CLAUDE.md                        # ★ Developer rulebook (forbidden patterns, invariants, agent coordination)
├── TRADING.md                       # ★ User/domain guide (signal cards, RRMS, debate, workflows)
├── README.md                        # Ops-facing quick-start
├── requirements.txt                 # ★ Python deps
├── Dockerfile                       # 3-stage: frontend build → python deps + TA-Lib → runtime
├── docker-compose.yml               # ★ Production stack (postgres + backend + dashboard)
├── docker-compose.dev.yml           # Dev overrides (exposes postgres :5432, mounts src, --reload)
├── .env.example                     # ★ Required env vars (missing: NEUROLINKED_TOKEN)
├── .pre-commit-config.yaml          # ruff + ruff-format
├── .github/workflows/ci.yml         # ruff → pytest (with live Postgres 16 service)
└── .gitignore / .dockerignore
```

★ = critical file, read when changes affect that layer
⚠ = known issue / handle with care (see `.claude/project-state.md` → Known issues)

---

## Key files to read by task

| Task | Read first |
|---|---|
| Adding a new API endpoint | `mcp_server/mcp_server.py` (find a nearby `@app.get/post` handler, same style), `skills/BACKEND.md`, `skills/api-design/SKILL.md` |
| Changing a scanner / adding a new one | `mcp_server/mwa_scanner.py`, one of `technical_scanners.py` / `nse_scanner.py` / `nfo_scanners.py` as pattern, `mcp_server/scanner_bayesian.py` (for the auto-disable), `tests/test_*scanner*.py` |
| Touching RRMS / risk sizing | `mcp_server/rrms_engine.py`, `mcp_server/portfolio_risk.py`, `tests/test_rrms.py`, `CLAUDE.md` invariant #1 (RRMS is mandatory) |
| Touching the debate validator | `mcp_server/debate_validator.py`, `mcp_server/validator.py`, `mcp_server/prompts.py`, `tests/test_debate_validator.py`, `tests/test_validator_debate_wiring.py` |
| Adding a database column | **Do NOT skip Alembic.** `alembic/versions/` (create a new migration), update `mcp_server/models.py`, consider whether `mcp_server/db.py:_add_missing_columns()` should also learn about it (for existing deploys), `skills/DATABASE.md` |
| Adding a new React page | `dashboard/src/App.tsx` (add `<Route>`), `dashboard/src/pages/<similar>Page.tsx` as pattern, `dashboard/src/services/api.ts` for new endpoints, `skills/FRONTEND.md` |
| Wiring a new broker | `mcp_server/{kite,angel,dhan,gwc}_auth.py` (pick closest model), `mcp_server/data_provider.py`, `mcp_server/order_manager.py`, `mcp_server/config.py` (add env vars), `.env.example` |
| Adding an option strategy | `mcp_server/options_signal_engine.py`, `mcp_server/options_selector.py`, `mcp_server/options_greeks.py`, `mcp_server/options_payoff.py`, `tests/test_options_*.py` |
| Changing a Telegram card | `mcp_server/telegram_bot.py`, `mcp_server/signal_cards.py`, `tests/test_telegram_gate.py` |
| Deployment change | `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `skills/DEPLOYMENT.md`, `skills/docker-patterns/SKILL.md` |
| n8n workflow change | `n8n_workflows/*.json` (import to n8n GUI to edit; commit JSON back) |
| Pine Script / TradingView | `pine_script/rrms_strategy.pine`, README.md § "TradingView Alert Setup" |

---

## Do-not-touch zones

Agents must NOT modify these without explicit user permission:

- `alembic/versions/` — **never delete or rewrite existing migrations**; always add a new revision. CLAUDE.md is explicit.
- `schema.sql` — initial DDL + seed data. Changing mid-project drifts from Alembic; touch only during a schema-consolidation pass.
- `n8n_workflows/*.json` — these are JSON exports from live n8n. Hand-editing risks breaking the UI-import round-trip. Prefer editing in n8n UI and re-exporting.
- `pine_script/rrms_strategy.pine` — live TradingView strategy. Test in TV paper before committing.
- `mcp_server/mcp_server.py:lifespan` — startup order is load-bearing (Dhan auth → Kite auth → init_db → background loops). Understand before reordering.
- `.github/workflows/` — CI changes need review
- `TRADING.md` — user-facing domain guide. Don't duplicate into CLAUDE.md (see CLAUDE.md § "Project Overview").
- `data/` — runtime artifacts (service_account.json, trade_memory.json). Gitignored but present in running containers.

---

## Cross-cutting concerns

**Auth flow (opt-in, gated by `AUTH_ENABLED`):**
1. User POSTs to `/auth/login` or `/api/auth/login` (with email + password OR Google OAuth token OR email OTP)
2. Backend issues JWT (PyJWT + bcrypt; see `mcp_server/auth.py` + `auth_providers.py`)
3. Frontend stores token in `localStorage` under `mkumaran_auth_token`, reads via `AuthContext`
4. Axios response interceptor (`dashboard/src/services/api.ts:43`) handles 401 → clear storage → redirect to `/login`
5. Public endpoints include `/tv_webhook`, `/health`, `/api/info` — see `mcp_server.py` `include_in_schema=False` / unauthed routes

**Signal flow (the core pipeline):**
1. Scanner layer (MWA or intraday) emits candidates
2. Debate validator (`debate_validator.py`) runs 8 specialist agents → consensus confidence
3. RRMS engine (`rrms_engine.py`) sizes the position — **MANDATORY gate**
4. Signal persisted (`models.Signal`), enriched with ML features + options (if FNO)
5. Telegram card sent (`telegram_bot.py`) + Google Sheets row (`sheets_sync.py`) + NeuroLinked brain observed (`brain_bridge.py`)
6. `signal_monitor` background loop tracks to SL/TGT
7. Outcome written + postmortem generated → predictor retrains (4PM IST) → scanner Bayesian review

**Error handling:**
- Backend: `HTTPException` from routers; global handler at `mcp_server.py:1212`; broker errors logged but never silently swallowed (CLAUDE.md forbidden pattern)
- Frontend: axios interceptor returns `Promise.reject(error)`; pages surface via toast/inline error state
- Brain bridge: **always silent** — 5s timeout, any failure logged at debug level, trading pipeline never affected

**Logging:**
- Backend: stdlib `logging` + `structlog` + `logzero` → stdout → Docker logs → aggregator (none configured). `LOG_FORMAT=json`, `LOG_LEVEL=INFO`.
- Frontend: `console.error` only; no Sentry/PostHog wired.
- **Never `print()` in trading logic** — CLAUDE.md forbidden pattern.

**Rate limiting:**
- `slowapi` middleware in `mcp_server.py`
- Broker APIs have their own quotas — `CLAUDE.md` invariant #5 (batch + backoff on 429)

**Timezone:**
- Everything routes through `mcp_server.market_calendar.now_ist()`. Server TZ is unreliable in Docker.
