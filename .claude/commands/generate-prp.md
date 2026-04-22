# Generate PRP Command

You are a **Product PRP Generator**. Create a focused implementation blueprint for a MicroSaaS product.

## Input
Read the product definition file: $ARGUMENTS (defaults to INITIAL.md)

---

## Context Files

Read these files before generating:
- `CLAUDE.md` (project rules)
- `agents/ORCHESTRATOR.md` (orchestrator role)

---

## Step 1: Parse INITIAL.md

Extract from the input file:

```yaml
PRODUCT:
  name: [Product name]
  description: [What it does]
  type: [SaaS, Marketplace, Platform, etc.]

TECH_STACK:
  backend: [FastAPI / Express / Django]
  frontend: [React / Next.js / Vue]
  database: [PostgreSQL / MySQL / MongoDB]
  auth: [JWT / Session / Auth0]
  ui: [Chakra UI / Tailwind + shadcn / MUI]
  payments: [Stripe / Dodo / LemonSqueezy / None]

MODULES:
  - name: [Module 1]
    models: [List of entities]
    endpoints: [List of API endpoints]
    pages: [List of UI pages]

MVP_SCOPE:
  - [Feature 1]
  - [Feature 2]

ACCEPTANCE_CRITERIA:
  - [Criterion 1]
  - [Criterion 2]
```

---

## Step 2: Map Agents to Modules

```yaml
DATABASE-AGENT:
  models: [All models from all modules]
  skills: [skills/DATABASE.md]

BACKEND-AGENT:
  modules: [All modules needing API]
  skills: [skills/BACKEND.md]

FRONTEND-AGENT:
  modules: [All modules needing UI]
  skills: [skills/FRONTEND.md]

DEVOPS-AGENT:
  tasks: [Docker, CI/CD, environments]
  skills: [skills/DEPLOYMENT.md]

TEST-AGENT:
  coverage: [All modules]
  skills: [skills/TESTING.md]

REVIEW-AGENT:
  review: [Security, performance, code quality]
```

---

## Step 3: Generate PRP File

Create `PRPs/[product-name-kebab-case]-prp.md` with this structure:

```markdown
# PRP: [Product Name]

> Implementation blueprint for parallel agent execution

---

## METADATA

| Field | Value |
|-------|-------|
| **Product** | [Name] |
| **Type** | [SaaS / Marketplace / etc.] |
| **Version** | 1.0 |
| **Created** | [Date] |
| **Complexity** | [Low / Medium / High] |

---

## PRODUCT OVERVIEW

**Description:** [What this product does]

**Value Proposition:** [Why users will pay]

**MVP Scope:**
- [ ] [Feature 1]
- [ ] [Feature 2]
- [ ] [Feature 3]

---

## TECH STACK

| Layer | Technology | Skill Reference |
|-------|------------|-----------------|
| Backend | [FastAPI + Python 3.11+] | skills/BACKEND.md |
| Frontend | [React + TypeScript + Vite] | skills/FRONTEND.md |
| Database | [PostgreSQL + SQLAlchemy] | skills/DATABASE.md |
| Auth | [JWT + bcrypt] | skills/BACKEND.md |
| UI | [Chakra UI / Tailwind] | skills/FRONTEND.md |
| Testing | [pytest + RTL] | skills/TESTING.md |
| Deployment | [Docker + GitHub Actions] | skills/DEPLOYMENT.md |

---

## DATABASE MODELS

### User Model
- id, email, hashed_password, full_name, is_active, is_verified, oauth_provider, created_at

### [Other Models]
[List each model with key fields and relationships]

---

## MODULES

### Module 1: Authentication
**Agents:** DATABASE-AGENT + BACKEND-AGENT + FRONTEND-AGENT

**Backend Endpoints:**
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /auth/register | Create account |
| POST | /auth/login | Get tokens |
| POST | /auth/refresh | Refresh token |
| GET | /auth/me | Current user |

**Frontend Pages:**
| Route | Page | Components |
|-------|------|------------|
| /login | LoginPage | LoginForm, GradientButton |
| /register | RegisterPage | RegisterForm |

---

### Module 2: [Core Module]
**Agents:** BACKEND-AGENT + FRONTEND-AGENT

**Backend Endpoints:**
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/[resource] | List all |
| POST | /api/[resource] | Create |
| GET | /api/[resource]/{id} | Get one |
| PUT | /api/[resource]/{id} | Update |
| DELETE | /api/[resource]/{id} | Delete |

**Frontend Pages:**
| Route | Page | Components |
|-------|------|------------|
| /[route] | [Page] | [Components] |

[Repeat for each module]

---

## PHASE EXECUTION PLAN

**Phase 1: Foundation (4 agents in parallel)**
- DATABASE-AGENT: All models, migrations, database.py
- BACKEND-AGENT: main.py, config.py, project structure
- FRONTEND-AGENT: Vite setup, folder structure, base components
- DEVOPS-AGENT: Docker, CI/CD, env files

**Validation Gate 1:** pip install, alembic upgrade, npm install, docker-compose config

**Phase 2: Modules (backend + frontend parallel per module)**
- Auth Module: JWT endpoints + Login/Register pages
- [Module 2]: API endpoints + UI pages
- [Module 3]: API endpoints + UI pages

**Validation Gate 2:** ruff check, mypy, npm lint, npm type-check

**Phase 3: Quality (3 agents in parallel)**
- TEST-AGENT: pytest + RTL tests, 80%+ coverage
- REVIEW-AGENT: Security audit, performance review
- RESEARCH-AGENT: Best practices validation

**Final Validation:** Full test suite, docker build, health checks

---

## VALIDATION GATES

| Gate | Commands |
|------|----------|
| 1 | `alembic upgrade head`, `npm install`, `docker-compose config` |
| 2 | `ruff check backend/`, `npm run type-check` |
| 3 | `pytest --cov --cov-fail-under=80`, `npm test` |
| Final | `docker-compose up -d`, `curl localhost:8000/health` |

---

## ENVIRONMENT VARIABLES

```env
DATABASE_URL=postgresql://user:password@localhost:5432/[dbname]
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
GOOGLE_CLIENT_ID=your-client-id (if OAuth)
GOOGLE_CLIENT_SECRET=your-secret (if OAuth)
VITE_API_URL=http://localhost:8000
```

---

## NEXT STEP

Execute with parallel agents:
/execute-prp PRPs/[product-name]-prp.md
```

---

## Output

Save to: `PRPs/[product-name-kebab-case]-prp.md`

Report to user:
```
PRP GENERATED

Product: [Name]
File: PRPs/[name]-prp.md
Modules: [count]
Models: [count]
Endpoints: [count]
Pages: [count]

Phases:
1. Foundation: 4 agents parallel
2. Modules: [X] pairs parallel
3. Quality: 3 agents parallel

NEXT: /execute-prp PRPs/[name]-prp.md
```
