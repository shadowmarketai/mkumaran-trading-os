# Codebase Map

> What lives where. Updated when structure changes significantly.

**Last updated:** YYYY-MM-DD

---

## Navigation guide

For a new developer (or Claude session) joining this repo, read in this order:

1. This file
2. `.claude/project-state.md`
3. `README.md`
4. The entry point for the layer you're working on (see below)

---

## Directory tree (annotated)

```
project-root/
├── frontend/                    # Vite + React 18 + TypeScript
│   ├── src/
│   │   ├── App.tsx              # ★ main router, marketing/app split
│   │   ├── main.tsx             # ★ React bootstrap
│   │   ├── components/
│   │   │   ├── ui/              # shadcn-style primitives (do not modify)
│   │   │   ├── layout/          # Sidebar, PageWrapper
│   │   │   └── scroll/          # shadow-3d-scroll components (marketing only)
│   │   ├── pages/
│   │   │   ├── marketing/       # Public-facing, SmoothScroll wrapped
│   │   │   ├── dashboard/       # Authed, native scroll
│   │   │   ├── printers/        # Authed
│   │   │   └── auth/            # Login, Register
│   │   ├── hooks/               # Custom React hooks
│   │   ├── services/
│   │   │   └── api.ts           # ★ Axios client + interceptors
│   │   ├── context/
│   │   │   └── AuthContext.tsx  # ★ JWT + user session
│   │   └── types/               # TypeScript interfaces
│   ├── public/                  # Static assets (models, images)
│   ├── package.json             # ★ dependency source of truth
│   └── vite.config.ts           # ★ alias @/ → src/
│
├── backend/                     # FastAPI + SQLAlchemy + Postgres
│   ├── app/
│   │   ├── main.py              # ★ FastAPI app factory, middleware
│   │   ├── config.py            # Settings via pydantic-settings
│   │   ├── database.py          # ★ SQLAlchemy engine + session factory
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── routers/             # FastAPI routers (one file per resource)
│   │   ├── services/            # Business logic (keep routers thin)
│   │   └── auth/                # JWT, password hashing, deps
│   ├── alembic/                 # DB migrations
│   │   └── versions/            # Individual migration files
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   ├── pyproject.toml           # ★ Python deps
│   └── alembic.ini
│
├── .claude/                     # Claude Code memory + config
│   ├── project-state.md         # ★ living state doc (read first)
│   ├── codebase-map.md          # this file
│   ├── commands/                # custom slash commands
│   └── settings.local.json      # permissions (MCP access)
│
├── agents/                      # Specialized agent definitions
│   ├── ORCHESTRATOR.md          # coordinator
│   ├── onboarder.md             # first-contact (read-only)
│   ├── planner.md               # feature planning
│   ├── frontend-agent.md
│   ├── backend-agent.md
│   ├── database-agent.md
│   └── ...
│
├── skills/                      # Skill library
│   ├── FRONTEND.md              # React conventions
│   ├── BACKEND.md               # FastAPI conventions
│   ├── DATABASE.md              # SQLAlchemy/Alembic
│   ├── shadow-3d-scroll/        # Marketing page scroll effects
│   ├── brownfield-patterns/     # How to work safely in existing code
│   ├── frontend-patterns/       # React patterns (composition, state)
│   ├── api-design/              # REST conventions
│   └── ...
│
├── PRPs/                        # Product Requirements Prompts
│   └── *.md                     # one PRP per major feature
│
├── rules/                       # Language-specific rules
│   ├── common/                  # Applies to all
│   ├── typescript/
│   ├── python/
│   ├── swift/
│   └── kotlin/
│
├── scripts/                     # One-off dev scripts
│
├── docker-compose.yml           # ★ production stack
├── docker-compose.dev.yml       # dev overrides
├── CLAUDE.md                    # ★ project-wide Claude Code rules
├── README.md
└── .env.example                 # ★ required env vars
```

★ = critical file, read when changes affect that layer

---

## Key files to read by task

| Task | Read first |
|---|---|
| Adding a new API endpoint | `backend/app/main.py`, `backend/app/routers/<similar>.py`, `skills/BACKEND.md` |
| Adding a new React page | `frontend/src/App.tsx`, `skills/FRONTEND.md`, `frontend-patterns` skill |
| Building a marketing page | `skills/shadow-3d-scroll/SKILL.md`, `frontend/src/pages/marketing/LandingPage.example.tsx` |
| Adding a database table | `backend/app/models/`, `backend/alembic/versions/`, `skills/DATABASE.md` |
| Changing auth behavior | `backend/app/auth/`, `frontend/src/context/AuthContext.tsx` |
| Deployment change | `docker-compose.yml`, `.github/workflows/ci.yml`, `skills/DEPLOYMENT.md` |
| Onboarding a new client fork | `.claude/project-state.md`, this file, `rules/common/` |

---

## Do-not-touch zones

Agents must NOT modify these without explicit user permission:

- `frontend/src/components/ui/` — shadcn primitives, bumped via CLI only
- `backend/alembic/versions/` — never delete or rewrite existing migrations; always add a new one
- `.github/workflows/` — CI changes need review
- Any file matching `**/generated/**` or `**/*.generated.*`
- `frontend/public/brand/` — brand assets, change only with design sign-off

---

## Cross-cutting concerns

**Auth flow:**
1. User POSTs to `/api/v1/auth/login`
2. Backend issues JWT (see `backend/app/auth/`)
3. Frontend stores in `localStorage`, reads via `AuthContext`
4. Axios interceptor attaches `Authorization: Bearer` header

**Error handling:**
- Backend raises from `backend/app/exceptions.py`
- Frontend catches in API layer, surfaces via toast

**Logging:**
- Backend: Python `logging` → stdout → Docker → aggregator
- Frontend: console in dev only; production errors go to [Sentry / PostHog / other]
