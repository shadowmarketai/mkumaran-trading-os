# CLAUDE.md — MKUMARAN Trading OS Rules

> Rules Claude follows in every conversation for this project.
> **Domain guide (user-facing):** see `TRADING.md` — the trading workflows, signal card reading, RRMS, debate validator, etc.
> This file is the **developer/agent** rulebook. Don't duplicate TRADING.md content here.

---

## Project Overview

**Project:** MKUMARAN Trading OS
**Description:** Multi-segment trading assistant (NSE Equity / F&O / Commodity / Forex) with signal generation, AI-assisted debate validation, RRMS risk management, backtesting, and paper-trading. Multi-timeframe (intraday / swing / positional).

**Tech Stack:**
- **Backend:** Python (MCP server, Alembic migrations, Dhan/Angel broker APIs, n8n workflows)
- **Frontend:** React + Vite + TypeScript + Tailwind (`dashboard/`)
- **Database:** Postgres (Alembic-owned schema + data migrations in `alembic/versions/`)
- **Integrations:** Dhan API, Angel One SmartAPI, Telegram bot, n8n workflows, Pine Script for TradingView
- **AI:** Debate validator with 8 specialist agents (SMC, ICT, VSA, Wyckoff, Classical, Harmonic, etc.) + self-learning pipeline

---

## Code Standards

### Python (MCP server, scripts, workers)

```python
# ALWAYS type hints on public functions
def score_signal(signal: Signal, ctx: MarketContext) -> Decision:
    ...

# ALWAYS log, never print in production paths
import logging
logger = logging.getLogger(__name__)
logger.info("Signal scored: id=%s confidence=%.2f", signal.id, decision.confidence)

# Trading math uses Decimal, not float, past the boundary
from decimal import Decimal
pnl: Decimal = exit_price - entry_price
```

### TypeScript (dashboard)

```typescript
// ALWAYS typed interfaces — no `any`
interface SignalCard {
  id: string;
  symbol: string;
  segment: 'NSE_EQ' | 'NFO' | 'MCX' | 'FX';
  timeframe: 'intraday' | 'swing' | 'positional';
  entry: number;
  stopLoss: number;
  target: number;
  confidence: number;
}

// Async calls always typed
const fetchSignals = async (segment: Segment): Promise<SignalCard[]> => { ... };
```

---

## Forbidden Patterns

### Backend
- `print()` in trading logic → use `logging`
- Bare `float` for money — use `Decimal` (rounding errors compound)
- Hardcoded broker credentials or bot tokens → `.env`
- `SELECT *` from trading tables — specify columns (latency matters)
- Skipping the RRMS risk check before emitting a signal
- Swallowing broker-API exceptions silently — must log + alert

### Frontend
- `any` type in signal/trade structures
- `console.log` in production build
- Inline styles — use Tailwind
- Unvalidated numeric inputs into risk sizing (could size 100× intended)

---

## Trading-specific rules

These are short, testable invariants. Do NOT restate TRADING.md here.

1. **RRMS gate is mandatory** — every signal must pass risk sizing before surfacing to the user.
2. **Decimal money** — all P&L, stop-loss, target computations use `Decimal`, not `float`.
3. **Paper trading must be reversible** — no paper trade may affect real broker state.
4. **Signal dedup** — same symbol + timeframe + strategy + timestamp-minute = deduplicate.
5. **Rate-limit respect** — broker APIs have quotas; batch calls and backoff on 429.
6. **No leaks across segments** — equity signals must not accidentally route to F&O sizing (and vice versa).

---

## Three-tier knowledge architecture (from Shadow Market overlay)

| Tier | Naming | Purpose | When Claude loads it |
|---|---|---|---|
| **Agent** | `agents/<domain>-agent.md` | WHO does the work | When orchestrator dispatches |
| **Layer skill** | `skills/<DOMAIN>.md` | Domain-wide conventions | Session start in that domain |
| **Pattern skill** | `skills/<domain>-patterns/SKILL.md` | Task-specific recipes | When task triggers its description |

Full architecture: see `agents/ORCHESTRATOR.md`.

---

## Quality Commands

| Command | Purpose |
|---|---|
| `/onboard-repo` | Index the codebase + load `memory/` + read TRADING.md |
| `/resume` | Continue from last session (brownfield) |
| `/plan` | Plan a change before touching code |
| `/tdd` | Write failing tests first |
| `/code-review` | Full-stack code review against `rules/` |
| `/verify` | Build + lint + test + security |
| `/security-review` | OWASP scan |
| `/compliance-review` | GDPR + PCI DSS + encryption + MFA audit |
| `/e2e` | Generate Playwright tests |
| `/build-fix` | Auto-fix build errors |
| `/learn` | Extract session patterns to continuous-learning-v2 |

---

## Agent Coordination

See `agents/ORCHESTRATOR.md` for the full call graph. Entry point is the orchestrator.

| Agent | Role in this project |
|---|---|
| `orchestrator` | Entry for all non-trivial tasks |
| `backend-agent` | MCP server, strategy engines, brokers, n8n workflows |
| `frontend-agent` | dashboard/ (React + Vite) |
| `database-agent` | Alembic migrations (structure + seed data), query performance |
| `devops-agent` | Docker, CI, deploy |
| `security-reviewer` | Credential handling, RRMS leaks, injection, secrets |
| `python-reviewer` / `typescript-reviewer` | Per-language review |
| `tdd-guide` | Tests-first for strategy logic |
| `e2e-runner` | Dashboard journey tests with Playwright |

---

## ECC Quality Enforcement Layer

Rules in `rules/`:
- `rules/common/` — security, testing, coding style, code review, git workflow, performance
- `rules/python/` — Python-specific style, patterns, security, testing, hooks
- `rules/typescript/` — TypeScript-specific style, patterns, security, testing, hooks

### Compliance skills (cross-cutting, in `skills/security-review/`)

- `gdpr-compliance.md`, `pci-dss-compliance.md`, `zero-trust-architecture.md`
- `dast-pen-testing.md`, `siem-observability.md`, `end-user-mfa.md`
- `application-encryption.md`, `iac-security-scanning.md`, `container-image-scanning.md`

For regulated-broker integration and user data, run `/compliance-review` quarterly.

Claude Code hooks in `hooks/hooks.json` are complementary to your existing `.pre-commit-config.yaml` (ruff). Both run — no conflict.

---

## Skills reference

Layer skills (file):
- `skills/BACKEND.md` — Python backend conventions
- `skills/FRONTEND.md` — React + Tailwind conventions
- `skills/DATABASE.md` — SQLAlchemy + Alembic
- `skills/TESTING.md` — pytest + Vitest patterns
- `skills/DEPLOYMENT.md` — Docker + CI

Pattern skills (dir with SKILL.md):
- `skills/api-design/`, `skills/python-patterns/`, `skills/python-testing/`
- `skills/frontend-patterns/`, `skills/e2e-testing/`, `skills/docker-patterns/`
- `skills/tdd-workflow/`, `skills/coding-standards/`
- `skills/brownfield-patterns/`, `skills/token-budget/`
- `skills/continuous-learning-v2/`, `skills/security-review/`
- `skills/shadow-3d-scroll/` — USE ONLY on marketing/public pages, NEVER on `dashboard/` routes

---

## Overlay provenance

The `.claude/`, `agents/`, `skills/`, `rules/`, `hooks/`, `PRPs/` directories were overlaid from [`shadowmarketai/SHADOW-MARKET-TEMPLATE`](https://github.com/shadowmarketai/SHADOW-MARKET-TEMPLATE) on 2026-04-22. See `docs/CLAUDE_OVERLAY_CHANGELOG.md`. To refresh when the template evolves:

```bash
git remote add template https://github.com/shadowmarketai/SHADOW-MARKET-TEMPLATE.git
git fetch template
# Manually cherry-pick improvements to .claude/, agents/, skills/, rules/, hooks/
```
