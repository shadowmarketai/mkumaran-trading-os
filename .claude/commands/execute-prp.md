# Execute PRP Command

You are the **ORCHESTRATOR**. Execute the Product PRP by coordinating 6 specialized agents working in **TRUE PARALLEL**.

## Input
Read the PRP file: $ARGUMENTS

---

## CRITICAL: How Parallel Execution Works

To run agents in parallel, you MUST dispatch multiple Task tool calls in a **SINGLE response**.

**Pattern:**
```
In ONE response, call Task tool multiple times with:
- subagent_type: "general-purpose"
- run_in_background: true
- Each agent gets its own Task call
```

**This is required for parallelism.** Sequential responses = sequential execution.

---

## STEP 1: Read PRP & Load Context

Read these files first:
- `agents/ORCHESTRATOR.md` (your role)
- The PRP file from $ARGUMENTS

Extract from PRP:
- Product name and description
- All modules to build
- Database models
- API endpoints per module
- Frontend pages per module
- Tech stack choices

---

## STEP 2: PHASE 1 - Foundation (4 Agents in Parallel)

**Launch ALL 4 agents in ONE response using 4 Task tool calls:**

### DATABASE-AGENT Prompt
```
You are DATABASE-AGENT.

READ FIRST:
- agents/database-agent.md
- skills/DATABASE.md

PROJECT: [Name from PRP]

CREATE ALL DATABASE MODELS:
[List all models from PRP]

TASKS:
1. Create backend/app/models/base.py with TimestampMixin, SoftDeleteMixin
2. Create backend/app/models/__init__.py
3. Create model file for EACH entity
4. Create backend/app/database.py with engine, SessionLocal, get_db
5. Initialize Alembic: alembic init alembic
6. Configure alembic/env.py to import models
7. Generate migration: alembic revision --autogenerate -m "initial"

Follow patterns from skills/DATABASE.md exactly.

OUTPUT: List all files created with paths.
```

### BACKEND-AGENT Prompt (Foundation)
```
You are BACKEND-AGENT (Foundation Phase).

READ FIRST:
- agents/backend-agent.md
- skills/BACKEND.md

PROJECT: [Name from PRP]

CREATE BACKEND FOUNDATION:
1. backend/requirements.txt (all dependencies)
2. backend/app/__init__.py
3. backend/app/main.py (FastAPI app with CORS, exception handlers)
4. backend/app/config.py (Settings with Pydantic)
5. backend/app/dependencies.py (get_db, get_current_user stub)
6. backend/app/exceptions.py (NotFoundError, ConflictError, etc.)
7. backend/app/routers/__init__.py
8. backend/app/schemas/__init__.py
9. backend/app/services/__init__.py
10. backend/app/auth/__init__.py

This is STRUCTURE ONLY - module code comes in Phase 2.

OUTPUT: List all files created with paths.
```

### FRONTEND-AGENT Prompt (Foundation)
```
You are FRONTEND-AGENT (Foundation Phase).

READ FIRST:
- agents/frontend-agent.md
- skills/FRONTEND.md

PROJECT: [Name from PRP]
UI FRAMEWORK: [From PRP - Chakra UI or Tailwind]

CREATE FRONTEND FOUNDATION:
1. Initialize: npm create vite@latest frontend -- --template react-ts
2. Install dependencies from PRP tech stack
3. Create folder structure:
   - frontend/src/components/ui/
   - frontend/src/components/layout/
   - frontend/src/pages/
   - frontend/src/hooks/
   - frontend/src/services/
   - frontend/src/context/
   - frontend/src/types/
   - frontend/src/lib/
4. Create frontend/src/services/api.ts (Axios client with interceptors)
5. Create frontend/src/types/index.ts
6. Create frontend/src/App.tsx with React Router
7. Configure UI framework (ChakraProvider or Tailwind config)

IMPORTANT: Copy modern components from skills/FRONTEND.md:
- GlassCard, GradientButton, PageWrapper, AnimatedList

OUTPUT: List all files created with paths.
```

### DEVOPS-AGENT Prompt
```
You are DEVOPS-AGENT.

READ FIRST:
- skills/DEPLOYMENT.md

PROJECT: [Name from PRP]

CREATE INFRASTRUCTURE:
1. backend/Dockerfile (multi-stage, non-root user)
2. frontend/Dockerfile (multi-stage build)
3. docker-compose.yml (backend, frontend, postgres)
4. docker-compose.dev.yml (with volume mounts)
5. .env.example (all required env vars)
6. .gitignore (Python + Node)
7. .github/workflows/ci.yml (lint, test, build)

OUTPUT: List all files created with paths.
```

### After Dispatching Phase 1

Use TaskOutput for each agent to wait for completion:
```
TaskOutput(task_id="database-agent-id", block=true)
TaskOutput(task_id="backend-agent-id", block=true)
TaskOutput(task_id="frontend-agent-id", block=true)
TaskOutput(task_id="devops-agent-id", block=true)
```

### Validation Gate 1
```bash
cd backend && pip install -r requirements.txt
alembic upgrade head
cd ../frontend && npm install
docker-compose config
```

---

## STEP 3: PHASE 2 - Core Modules (Parallel per Module)

For EACH module in PRP, launch Backend + Frontend agents together.
**All modules run in parallel with each other.**

### Auth Module Example

**BACKEND-AGENT (Auth):**
```
You are BACKEND-AGENT for AUTH MODULE.

READ FIRST:
- skills/BACKEND.md

MODELS AVAILABLE: [from Phase 1]

CREATE AUTH MODULE:
1. backend/app/schemas/auth.py
2. backend/app/auth/jwt.py (create_access_token, verify_token, hash_password)
3. backend/app/auth/oauth.py (if Google OAuth)
4. backend/app/services/auth_service.py
5. backend/app/routers/auth.py with endpoints:
   - POST /auth/register
   - POST /auth/login
   - POST /auth/refresh
   - POST /auth/logout
   - GET /auth/me
   - GET /auth/google (if OAuth)
   - GET /auth/google/callback
6. Update dependencies.py - implement get_current_user
7. Update main.py - add auth router

OUTPUT: All files + list of endpoints created.
```

**FRONTEND-AGENT (Auth):**
```
You are FRONTEND-AGENT for AUTH MODULE.

READ FIRST:
- skills/FRONTEND.md

API ENDPOINTS: /auth/register, /auth/login, /auth/refresh, /auth/me

CREATE AUTH UI:
1. frontend/src/context/AuthContext.tsx
2. frontend/src/hooks/useAuth.ts
3. frontend/src/services/authService.ts
4. frontend/src/pages/LoginPage.tsx (use PageWrapper, GlassCard)
5. frontend/src/pages/RegisterPage.tsx
6. frontend/src/components/auth/LoginForm.tsx (use GradientButton)
7. frontend/src/components/auth/RegisterForm.tsx
8. frontend/src/components/auth/ProtectedRoute.tsx
9. frontend/src/components/auth/GoogleLoginButton.tsx (if OAuth)
10. Update App.tsx with auth routes

MANDATORY: Use components from skills/FRONTEND.md for modern look.

OUTPUT: All files created.
```

### Other Modules

Repeat the pattern for each module in the PRP:
- Spawn BACKEND-AGENT + FRONTEND-AGENT for each module
- All module pairs can run in parallel

### Validation Gate 2
```bash
ruff check backend/ --fix
ruff format backend/
mypy backend/app --ignore-missing-imports
cd frontend && npm run lint && npm run type-check
```

---

## STEP 4: PHASE 3 - Quality (3 Agents in Parallel)

Launch TEST-AGENT, REVIEW-AGENT, and RESEARCH-AGENT together.

### TEST-AGENT Prompt
```
You are TEST-AGENT.

READ: skills/TESTING.md

FILES TO TEST: [All files from Phase 1 & 2]

CREATE:
1. backend/tests/__init__.py
2. backend/tests/conftest.py (fixtures, test db, test client)
3. backend/tests/test_auth.py
4. backend/tests/test_[module].py for each module
5. frontend/src/__tests__/setup.ts
6. frontend/src/__tests__/components/*.test.tsx
7. frontend/src/__tests__/pages/*.test.tsx

TARGET: 80%+ coverage for backend.

OUTPUT: All test files + coverage summary.
```

### REVIEW-AGENT Prompt
```
You are REVIEW-AGENT.

REVIEW all files from Phase 1 & 2.

SECURITY CHECKLIST (OWASP):
- SQL Injection - parameterized queries?
- XSS - sanitized outputs?
- Broken Auth - proper token handling?
- Sensitive Data - no secrets in code?
- Rate Limiting - implemented?

PERFORMANCE CHECKLIST:
- N+1 Queries - eager loading?
- Indexes - on queried columns?
- Bundle Size - code splitting?

CODE QUALITY:
- No 'any' types in TypeScript
- All errors handled
- Input validation complete

OUTPUT: Review report with severity levels.
```

### RESEARCH-AGENT Prompt
```
You are RESEARCH-AGENT.

VALIDATE implementation against best practices:
1. FastAPI best practices followed?
2. React patterns up to date?
3. Security advisories for dependencies?
4. Missing edge cases?

OUTPUT: Recommendations and improvements.
```

### Final Validation
```bash
pytest backend/tests -v --cov=backend/app --cov-fail-under=80
cd frontend && npm test -- --coverage
docker-compose build
docker-compose up -d
sleep 10
curl -f http://localhost:8000/health
curl -f http://localhost:3000
docker-compose down
```

---

## STATUS DISPLAY

Show progress after each phase:

```
PHASE 1: FOUNDATION
├─ DATABASE-AGENT     [✅ Complete] 8 model files
├─ BACKEND-AGENT      [✅ Complete] 10 files
├─ FRONTEND-AGENT     [✅ Complete] 12 files
└─ DEVOPS-AGENT       [✅ Complete] 6 files

PHASE 2: MODULES
├─ AUTH: Backend [✅] Frontend [✅]
├─ [MODULE 2]: Backend [✅] Frontend [✅]
└─ [MODULE 3]: Backend [✅] Frontend [✅]

PHASE 3: QUALITY
├─ TEST-AGENT         [✅ Complete] 85% coverage
├─ REVIEW-AGENT       [✅ Complete] 0 critical issues
└─ RESEARCH-AGENT     [✅ Complete] 2 suggestions
```

---

## FINAL REPORT

```
EXECUTION COMPLETE

Product: [Name]
Status: SUCCESS
Agents: 6 (parallel execution)

FILES CREATED:
Backend:  [X] files
Frontend: [X] files
Tests:    [X] files
Infra:    [X] files

HOW TO RUN:
docker-compose -f docker-compose.dev.yml up

URLs:
Frontend: http://localhost:3000
Backend:  http://localhost:8000
API Docs: http://localhost:8000/docs
```

---

## ERROR HANDLING

If an agent fails:
1. Log error with context
2. Continue with other parallel agents
3. Attempt auto-fix (formatters, imports)
4. If still failing, mark as partial
5. Generate report of what succeeded/failed
6. User can fix and resume: `/execute-prp [PRP] --resume`
