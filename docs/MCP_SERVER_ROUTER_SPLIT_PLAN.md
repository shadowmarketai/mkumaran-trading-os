# `mcp_server.py` Router Split — Plan

> Plan only — no code changes. Approve before execution.
>
> **Goal:** decompose `mcp_server/mcp_server.py` (6,635 lines, 148 routes, ~60 imports, one FastAPI app factory) into per-domain FastAPI routers so that (a) any individual router is readable end-to-end, (b) related routes live together, and (c) the file no longer blocks merges by diff-conflicting on unrelated changes.
>
> **Status:** DRAFT
> **Author:** Claude Opus 4.7
> **Created:** 2026-04-24

---

## 1. Reality today

| Metric | Value |
|---|---|
| Lines | 6,635 |
| Route decorators | 148 |
| `/api/*` routes | 67 |
| `/tools/*` routes | 78 |
| `/health`, `/auth/*` | 3 |
| FastAPI lifespan + middleware + factory | scattered across lines ~735–1240 |
| Top of file imports | ~60 |
| Inline helper functions not exported | ~40 |

Concrete symptoms this causes:
- Every feature PR touches near-random line numbers → high merge conflict rate
- `git blame` on a single route loses context to noise
- New contributors can't find the signal pipeline vs the options vs admin vs wallstreet paths without grep
- Startup sequencing (which background tasks start when) is hidden in a 500-line `lifespan()` deep inside the file

## 2. Route inventory

Counted via `grep -E '^@app\.(get|post|...)\("'` then prefix-binned.

### `/api/*` clusters (67 routes)

| Cluster | Count | Notes |
|---|---|---|
| `selfdev` | 9 | Self-development system (postmortem / predictor / rules) |
| `fno` | 9 | Options / derivatives analytics |
| `auth` | 9 | Login, register, OTP, reset, google OAuth, config |
| `options` | 5 | Option universe, chain, greeks (overlaps with fno) |
| `watchlist` | 4 | Tiered watchlist CRUD |
| `signals` | 3 | Dashboard signal list + delete + cleanup |
| `scanner-review` | 3 | Bayesian scanner disable/enable |
| `user` | 2 | Tier + feature-gate check |
| `settings` | 2 | API key storage |
| `backtest` | 2 | Dashboard-facing backtest |
| Everything else | 19 | Mostly single-endpoint utilities (chart, overview, market-movers, momentum, news, cache, kite/gwc OAuth callbacks, telegram_webhook, tv_webhook, realtime, accuracy, mwa, info, exchanges, live-prices, trades) |

### `/tools/*` clusters (78 routes)

| Cluster | Count | Notes |
|---|---|---|
| `wallstreet/*` | 7 | Fundamental screen, DCF, risk report, earnings, technical, sector, macro |
| `detect_*` | 6 | SMC / VSA / Wyckoff / Harmonic / Pattern / RL pattern detection |
| `stitch_*` | 5 | ETL push to data warehouse |
| `update_*` / `refresh_*` | 8 | Trailing SL / PnL / Bayesian / broker token refreshers |
| `run_*` | 8 | Scans, postmortems, scanner review, self-dev, MWA, fno analytics, rrms |
| `momentum_*`, `market_news`, `news_sentiment` | 4 | Market context tools |
| `place_order`, `order_status`, `portfolio_exposure`, `pretrade_check` | 4 | Trading / execution tools |
| `signal_accuracy`, `validate_signal`, `record_signal`, `get_active_trades`, `get_fo_signal`, `eod_summary`, `reflect_*` | 10 | Signal lifecycle |
| `tier2_monitor`, `tier3_monitor` | 2 | Tier watchlist monitors |
| `get_stock_data`, `get_mwa_score`, `mwa_scan_status`, `run_mwa_scan`, `scan_oi_buildup` | 5 | Scanner primitives |
| `trade_memory_stats`, `reset_sheets`, `refresh_trade_prices`, `mine_rules`, `retrain_predictor` | 5 | Admin / maintenance |
| Other | 14 | Backtesting, RRMS, singular tools |

## 3. Proposed router layout

```
mcp_server/
├── mcp_server.py              — app factory + lifespan + middleware
│                                 (~400 lines after split)
├── routers/
│   ├── __init__.py
│   ├── health.py              — /health, /api/info, /api/exchanges (~80 ln)
│   ├── auth.py                — /auth/*, /api/auth/* (~350 ln, 11 routes)
│   ├── user_settings.py       — /api/user/*, /api/settings/* (~150 ln, 4 routes)
│   ├── signals.py             — /api/signals/*, /tools/record_signal,
│   │                             /tools/signal_accuracy,
│   │                             /tools/validate_signal,
│   │                             /tools/get_active_trades,
│   │                             /tools/eod_summary (~800 ln, ~18 routes)
│   ├── trades.py              — /api/trades/*, /tools/place_order,
│   │                             /tools/order_status,
│   │                             /tools/portfolio_exposure,
│   │                             /tools/pretrade_check,
│   │                             /tools/update_pnl,
│   │                             /tools/update_trailing_sl,
│   │                             /tools/update_all_trailing_sl,
│   │                             /tools/refresh_trade_prices (~600 ln, ~12 routes)
│   ├── options_fno.py         — /api/fno/*, /api/options/*,
│   │                             /tools/run_fno_analytics,
│   │                             /tools/scan_oi_buildup,
│   │                             /tools/get_fo_signal (~800 ln, ~18 routes)
│   ├── scanners.py            — /tools/run_mwa_scan,
│   │                             /tools/mwa_scan_status/*,
│   │                             /tools/get_mwa_score,
│   │                             /tools/get_stock_data,
│   │                             /tools/detect_*,
│   │                             /api/scanner-review/*,
│   │                             /tools/run_scanner_review,
│   │                             /tools/tier2_monitor, /tools/tier3_monitor
│   │                             (~900 ln, ~20 routes)
│   ├── watchlist.py           — /api/watchlist/*,
│   │                             /tools/manage_watchlist (~200 ln, 5 routes)
│   ├── wallstreet.py          — /tools/wallstreet/* (~400 ln, 7 routes)
│   ├── selfdev.py             — /api/selfdev/*,
│   │                             /tools/run_self_development,
│   │                             /tools/run_postmortems,
│   │                             /tools/reflect_trades,
│   │                             /tools/reflect_single,
│   │                             /tools/mine_rules,
│   │                             /tools/retrain_predictor,
│   │                             /tools/update_bayesian_stats
│   │                             (~500 ln, ~17 routes)
│   ├── backtest.py            — /api/backtest/*,
│   │                             /tools/backtest_strategy,
│   │                             /tools/backtest_validate,
│   │                             /tools/backtest_confluence,
│   │                             /tools/run_rrms (~400 ln, 6 routes)
│   ├── market_data.py         — /api/chart/*, /api/live-prices,
│   │                             /api/market-movers, /api/overview,
│   │                             /api/realtime, /api/cache,
│   │                             /api/news, /api/mwa, /api/accuracy,
│   │                             /api/momentum,
│   │                             /tools/market_news,
│   │                             /tools/news_sentiment,
│   │                             /tools/momentum_rankings,
│   │                             /tools/momentum_rebalance
│   │                             (~600 ln, ~14 routes)
│   ├── brokers.py             — /api/kite_login_url, /api/kite_callback,
│   │                             /api/gwc_login_url, /api/gwc_callback,
│   │                             /tools/refresh_kite_token,
│   │                             /tools/refresh_gwc_token,
│   │                             /tools/refresh_angel_token
│   │                             (~350 ln, 7 routes)
│   ├── webhooks.py            — /api/tv_webhook, /api/telegram_webhook
│   │                             (~200 ln, 2 routes)
│   ├── admin.py               — /tools/reset_sheets,
│   │                             /tools/trade_memory_stats,
│   │                             /tools/stitch_*,
│   │                             /tools/update_signal (~300 ln, ~8 routes)
│   └── deps.py                — shared Depends (get_db, current_user, etc.)
```

**Target**: `mcp_server.py` shrinks to ~400 lines containing only:
- `app = FastAPI(...)` factory
- `lifespan()` + background task registration
- Middleware (rate limit, CORS, JWT auth)
- `app.include_router(...)` calls for each router module
- Global exception handlers

Routers include via:
```python
from mcp_server.routers import (
    health, auth, user_settings, signals, trades,
    options_fno, scanners, watchlist, wallstreet,
    selfdev, backtest, market_data, brokers, webhooks, admin,
)

app.include_router(health.router)
app.include_router(auth.router)
# ... etc
```

## 4. Phased execution

Each phase is a standalone PR. Each PR is mergeable on its own — the app keeps working after every merge.

### Phase 0 — scaffolding (low risk, ~30 min)

- Create `mcp_server/routers/` directory + empty `__init__.py`
- Create `mcp_server/routers/deps.py` holding `get_db` (currently inline in mcp_server.py) and any other shared Depends
- No route migration yet.
- PR risk: zero. Just structural scaffold.

### Phase 1 — extract the leaf clusters first (low risk, ~1 hr per router)

Order chosen: smallest/most-self-contained first so each PR is reviewable and the blast radius of a bug is small.

1. **`health.py`** (3 routes) — trivial, pure info endpoints. Prove the extraction pattern.
2. **`webhooks.py`** (2 routes) — well-isolated, external-facing, no imports of other routes.
3. **`wallstreet.py`** (7 routes) — self-contained fundamental suite.
4. **`watchlist.py`** (5 routes) — small CRUD cluster.
5. **`brokers.py`** (7 routes) — OAuth callbacks + token refreshers, well-scoped.

Each one:
- Creates the router file with `router = APIRouter(tags=["..."])`
- Moves route handlers verbatim
- Deletes them from `mcp_server.py`
- Adds `app.include_router(...)` at the factory
- Verifies: `curl localhost:8001/<route>` before and after returns identical JSON
- Expands the test suite only if there's an obvious gap

### Phase 2 — extract the big domains (medium risk, ~2 hrs per router)

6. **`options_fno.py`** (18 routes) — has interdependencies with options_selector + fno_module; needs import audit.
7. **`selfdev.py`** (17 routes) — touches signal_predictor + rules_engine + postmortem.
8. **`signals.py`** (18 routes) — core domain; the dashboard reads this heavily. Needs careful smoke test.
9. **`trades.py`** (12 routes) — touches order_manager + portfolio_risk; exercise paper mode.
10. **`scanners.py`** (20 routes) — biggest by route count; breaks mwa_scanner + detect_* into one router.

### Phase 3 — extract remaining + cleanup (low risk, ~1 hr)

11. **`market_data.py`** (14 routes) — the misc API cluster.
12. **`admin.py`** (8 routes) — maintenance + ETL tools.
13. **`auth.py`** (11 routes) — moved last because every other router depends on the `current_user` dep that lives here. Safe once deps.py has already extracted the shared helpers.
14. **`user_settings.py`** (4 routes) — trivial, saves for last.

### Phase 4 — collapse `mcp_server.py`

- After all routers are extracted, `mcp_server.py` should have zero `@app.*` decorators.
- Strip now-unused imports.
- Leave only: lifespan, middleware, app factory, include_router calls, global handlers, the long opening docstring.
- Target: ~400 lines.

## 5. What this does NOT change

- **No behavior change.** Every route responds identically byte-for-byte before and after.
- **No API contract change.** Path, query, body, response schema, status codes all preserved.
- **No test rewrite.** Existing tests that `GET /api/signals` still pass; they don't know the route moved internally.
- **No new abstractions.** Each router is a dumb re-home of existing handlers, not a refactor of their internals.
- **No framework upgrade.** Still FastAPI 0.104 + Pydantic 2.12.

## 6. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Moving a route changes the import side-effects it relied on (e.g., a module-level singleton initialised in mcp_server.py) | Medium | Before each phase, grep `from mcp_server.mcp_server import` across the codebase. Any import must be extracted to the deps module or left in mcp_server.py. |
| `include_router()` registers paths in a different order → route precedence bug for overlapping paths (e.g., `/api/fno/snapshot/{symbol}` vs `/api/fno/expiry/{symbol}`) | Low | FastAPI matches by exact path shape, not order. But audit any two routes that could be ambiguous and keep them in the same router. |
| Lifespan startup hooks implicitly depended on route handlers being defined first | Low | Lifespan functions don't reference route handlers. Grep confirms it. |
| Mocks in existing tests patch `mcp_server.mcp_server._get_kite_for_fo` etc — if those helpers move, the patch path breaks | High | **Don't move helper functions in this refactor.** Only routes move; helpers stay in mcp_server.py (or are imported from domain modules they already live in). |
| Silent duplicate route registration | Low | After every phase, `curl /docs` and count routes — should equal 148 every time. |
| Merge conflicts while this is in flight | High (file is hot) | Phase PRs should be **small and merge same-day**. Don't leave a half-extracted router branch open for days. |

## 7. Validation protocol per phase

Before merging each phase's PR:

1. `ruff check mcp_server/` → clean
2. `pytest` → same pass/fail count as `main` (cleared 35+ in PR #13 so baseline is close to green)
3. Start server locally, `curl /docs` → still shows all 148 routes
4. `curl` 3-5 random routes from the extracted cluster → identical JSON response vs pre-refactor
5. Dashboard smoke: load signals page, load FNO page, load overview page → no network errors in browser console

## 8. Ballpark sizing

| Phase | Routers | Routes | Calendar |
|---|---|---|---|
| 0 | scaffold | 0 | 30 min |
| 1 | 5 leaves (health, webhooks, wallstreet, watchlist, brokers) | 24 | 5 hrs |
| 2 | 5 big domains (options_fno, selfdev, signals, trades, scanners) | 85 | 10 hrs |
| 3 | 4 misc (market_data, admin, auth, user_settings) | 37 | 4 hrs |
| 4 | mcp_server.py cleanup | — | 1 hr |
| **Total** | 14 routers | **148** | **~20 hrs** over ~10 PRs |

## 9. Open questions for the operator

1. **PR cadence.** 10 PRs over two weeks with `main` staying hot, or one mega-PR? Plan assumes small PRs.
2. **Router tags.** OK to add FastAPI `tags=[...]` to each router (changes OpenAPI grouping on `/docs`, makes API explorer cleaner)?
3. **Scanner + options split.** Should options stay folded into `options_fno.py` or be its own `options.py`? Current proposal keeps them together because they share the `_get_kite_for_fo()` plumbing.
4. **Back-compat.** Do we need to preserve the exact line numbers for any external tooling (IDEs, log parsers, bug trackers) that reference `mcp_server.py:NNN`? Plan assumes no.
5. **Go / no-go.** Approve Phase 0 only, Phase 0+1, or the full plan?

Answer inline on the PR that adopts this plan, or reply with numbered responses.
