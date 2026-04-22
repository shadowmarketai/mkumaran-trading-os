# Setup Project Command

You are a **Project Setup Wizard**. Your job is to interactively collect information from the user about their MicroSaaS project and generate customized `INITIAL.md` and `CLAUDE.md` files.

## Process

### STEP 1: Collect Basic Information

Ask the user these questions using the AskUserQuestion tool. Collect answers in a conversational, friendly manner.

**Question 1: Product Basics**
```
Let's set up your MicroSaaS project! First, tell me about your product:

1. What's the name of your product?
2. In one sentence, what does it do?
3. Who is your target user?
```

**Question 2: Tech Stack** (Use AskUserQuestion with options)
```
questions:
  - question: "Which backend framework do you prefer?"
    header: "Backend"
    options:
      - label: "FastAPI + Python (Recommended)"
        description: "Modern, fast, great for APIs. Best documented in our skills."
      - label: "Express + Node.js"
        description: "JavaScript everywhere. Good for JS-heavy teams."
      - label: "Django + Python"
        description: "Batteries included. Good for complex apps."
    multiSelect: false

  - question: "Which frontend framework?"
    header: "Frontend"
    options:
      - label: "React + Vite + TypeScript (Recommended)"
        description: "Fast dev experience, strong typing, most popular."
      - label: "Next.js + TypeScript"
        description: "SSR, file-based routing, great for SEO."
      - label: "Vue 3 + TypeScript"
        description: "Gentle learning curve, great docs."
    multiSelect: false

  - question: "Which UI framework?"
    header: "UI"
    options:
      - label: "Chakra UI (Recommended)"
        description: "Accessible, composable, great DX."
      - label: "Tailwind + shadcn/ui"
        description: "Utility-first, highly customizable."
      - label: "MUI (Material UI)"
        description: "Google Material Design, enterprise-ready."
      - label: "Mantine"
        description: "Modern, feature-rich, great hooks."
    multiSelect: false

  - question: "Which authentication methods do you need?"
    header: "Auth"
    options:
      - label: "Email/Password + Google OAuth (Recommended)"
        description: "Most common setup for SaaS products."
      - label: "Email/Password only"
        description: "Simple, no third-party dependencies."
      - label: "Google OAuth only"
        description: "Quick signup, no password management."
      - label: "Magic Link (Passwordless)"
        description: "Modern, secure, requires email service."
    multiSelect: false
```

**Question 3: Core Modules**
```
Now let's define your core features. Besides Authentication (which is included by default), what are the main modules of your app?

Example: For an Invoice SaaS, modules might be:
- Invoices (create, send, track)
- Clients (manage client info)
- Dashboard (overview, stats)

List your 2-4 core modules:
```

**Question 4: Module Details** (For each module)
```
Let's detail the "[MODULE NAME]" module:

1. What data/entities does this module manage?
   (e.g., Invoice has: client_name, amount, due_date, status, items)

2. What actions can users perform?
   (e.g., Create, Edit, Delete, Send via email, Mark as paid)

3. What pages are needed?
   (e.g., List view, Detail view, Create/Edit form)
```

**Question 5: Payment Provider** (Use AskUserQuestion - only if app needs payments)
```
questions:
  - question: "Which payment provider do you want to use?"
    header: "Payments"
    options:
      - label: "Dodo Payments (Recommended)"
        description: "Simple API, great for startups, handles global payments easily."
      - label: "Stripe"
        description: "Most popular, extensive features, supports subscriptions."
      - label: "LemonSqueezy"
        description: "Built for digital products, handles taxes automatically."
      - label: "Paddle"
        description: "Merchant of record, handles global taxes & compliance."
      - label: "No payments needed"
        description: "Free product or handle payments later."
    multiSelect: false
```

**Question 6: Additional Features** (Use AskUserQuestion with multiSelect)
```
questions:
  - question: "Which additional features do you need?"
    header: "Features"
    options:
      - label: "Admin Panel"
        description: "Manage users, view stats, system settings."
      - label: "Email Notifications"
        description: "Transactional emails (welcome, reset password, etc.)"
      - label: "File Uploads"
        description: "Upload images, documents, attachments."
      - label: "Analytics Dashboard"
        description: "Usage metrics, charts, reports."
    multiSelect: true
```

**Question 7: MVP Scope**
```
What's the absolute minimum you need for launch?
(This helps prioritize what gets built first)

List 3-5 must-have features for your MVP:
```

---

### STEP 2: Generate INITIAL.md

Based on collected information, generate a complete `INITIAL.md`:

```markdown
# INITIAL.md - [PRODUCT NAME] Product Definition

> [One-sentence description]

---

## PRODUCT

### Name
[Product Name]

### Description
[Expanded description based on user input]

### Target User
[Who this is for]

### Type
- [x] SaaS (Software as a Service)

---

## TECH STACK

### Backend
- [x] [Selected backend]

### Frontend
- [x] [Selected frontend]

### Database
- [x] PostgreSQL (recommended for all stacks)

### Authentication
- [x] [Selected auth method]

### UI Framework
- [x] [Selected UI framework]

### Payments
- [x/blank] [If Stripe selected]

---

## MODULES

### Module 1: Authentication (Required)

**Description:** User authentication and authorization

**Models:**
- User: id, email, hashed_password, full_name, is_active, is_verified, oauth_provider, created_at
- RefreshToken: id, user_id, token, expires_at, revoked

**API Endpoints:**
- POST /auth/register - Create new account
- POST /auth/login - Login with email/password
- POST /auth/refresh - Refresh access token
- POST /auth/logout - Revoke refresh token
- GET /auth/me - Get current user profile
- PUT /auth/me - Update profile
[Add OAuth endpoints if selected]

**Frontend Pages:**
- /login - Login page
- /register - Registration page
- /forgot-password - Forgot password page
- /profile - User profile page (protected)

---

### Module 2: [USER'S FIRST MODULE]

**Description:** [Based on user input]

**Models:**
[Generate based on user's entity description]

**API Endpoints:**
[Generate CRUD + custom actions based on user input]

**Frontend Pages:**
[Generate based on user input]

---

[Repeat for each module...]

---

### Module X: Dashboard

**Description:** Overview and statistics

**Frontend Pages:**
- /dashboard - Main dashboard with widgets and stats
- /settings - User settings and preferences

---

[If Admin Panel selected:]
### Module Y: Admin Panel

**Description:** Admin-only management interface

**API Endpoints:**
- GET /admin/users - List all users
- PUT /admin/users/{id} - Update user status
- GET /admin/stats - Platform statistics

**Frontend Pages:**
- /admin - Admin dashboard (protected, admin only)
- /admin/users - User management

---

## MVP SCOPE

### Must Have (MVP)
- [x] User registration and login
[List user's MVP features]

### Nice to Have (Post-MVP)
[Remaining features not in MVP]

---

## ACCEPTANCE CRITERIA

### Authentication
- [ ] User can register with email/password
- [ ] User can login with email/password
[Add OAuth criteria if selected]
- [ ] JWT tokens work correctly with refresh
- [ ] Protected routes redirect to login

### [Module Name]
[Generate criteria based on module actions]

### Quality
- [ ] All API endpoints documented in OpenAPI
- [ ] Backend test coverage 80%+
- [ ] Frontend TypeScript strict mode passes
- [ ] Docker builds and runs successfully

---

## SPECIAL REQUIREMENTS

### Security
- [x] Rate limiting on auth endpoints
- [x] Input validation on all endpoints
- [x] SQL injection prevention
- [x] XSS prevention
[Add CSRF if OAuth selected]

### Integrations
[Check based on selected features]
- [x/blank] Email service for notifications
- [x/blank] Stripe for payments
- [x/blank] File upload service

---

## AGENTS

> These 6 agents will build your product in parallel:

| Agent | Role | Works On |
|-------|------|----------|
| DATABASE-AGENT | Creates all models and migrations | All database models |
| BACKEND-AGENT | Builds API endpoints and services | All modules' backends |
| FRONTEND-AGENT | Creates UI pages and components | All modules' frontends |
| DEVOPS-AGENT | Sets up Docker, CI/CD, environments | Infrastructure |
| TEST-AGENT | Writes unit and integration tests | All code |
| REVIEW-AGENT | Security and code quality audit | All code |

---

# READY?

```bash
/generate-prp INITIAL.md
```

Then:

```bash
/execute-prp PRPs/[product-name]-prp.md
```
```

---

### STEP 3: Generate CLAUDE.md

Generate a customized `CLAUDE.md` based on the project:

```markdown
# CLAUDE.md - [PRODUCT NAME] Project Rules

> Project-specific rules for Claude Code. This file is read automatically.

---

## Project Overview

**Project Name:** [Product Name]
**Description:** [Description]
**Tech Stack:**
- Backend: [Selected backend]
- Frontend: [Selected frontend]
- Database: PostgreSQL + SQLAlchemy
- Auth: [Selected auth]
- UI: [Selected UI framework]

---

## Project Structure

```
[product-name]/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/
│   │   │   ├── user.py
[Generate model files based on modules]
│   │   ├── schemas/
│   │   ├── routers/
│   │   ├── services/
│   │   └── auth/
│   ├── alembic/
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── context/
│   │   └── types/
│   └── package.json
├── .claude/
│   └── commands/
├── skills/
├── agents/
└── PRPs/
```

---

## Code Standards

### Python (Backend)
```python
# ALWAYS use type hints
def get_[entity](db: Session, [entity]_id: int) -> [Entity]:
    pass

# ALWAYS add docstrings for public functions
def create_[entity](db: Session, data: [Entity]Create) -> [Entity]:
    """
    Create a new [entity].

    Args:
        db: Database session
        data: [Entity] creation data

    Returns:
        Created [Entity] object
    """
    pass
```

### TypeScript (Frontend)
```typescript
// ALWAYS define interfaces for props and data
interface [Entity]Props {
  id: number;
  [fields based on module]
}

// NO any types allowed
const fetch[Entity] = async (id: number): Promise<[Entity]> => {
  // ...
};
```

---

## Forbidden Patterns

### Backend
- ❌ Never use `print()` - use `logging` module
- ❌ Never store passwords in plain text
- ❌ Never hardcode secrets - use environment variables
- ❌ Never use `SELECT *` - specify columns
- ❌ Never skip input validation

### Frontend
- ❌ Never use `any` type
- ❌ Never leave console.log in production
- ❌ Never skip error handling in async operations
- ❌ Never use inline styles - use [UI framework]

---

## Module-Specific Rules

[Generate based on modules, e.g.:]

### [Module Name] Module
- All [entities] must belong to a user (user_id foreign key)
- [Entity] status must be one of: [list valid statuses]
- [Any business rules the user mentioned]

---

## API Conventions

- All endpoints prefixed with `/api/v1/`
- Use plural nouns for resources: `/invoices`, `/clients`
- Return appropriate HTTP status codes:
  - 200: Success
  - 201: Created
  - 400: Bad Request
  - 401: Unauthorized
  - 404: Not Found
  - 409: Conflict

---

## Authentication

[Based on selected auth method]

### JWT Configuration
- Access token expires: 30 minutes
- Refresh token expires: 7 days
- Algorithm: HS256

[If OAuth selected:]
### OAuth Providers
- Google OAuth 2.0 enabled
- Always verify state parameter for CSRF protection

---

## Environment Variables

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/[product_name]

# Auth
SECRET_KEY=your-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

[If Google OAuth:]
# Google OAuth
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret

[If Stripe:]
# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Frontend
VITE_API_URL=http://localhost:8000
```

---

## Development Commands

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev

# Docker
docker-compose up -d

# Tests
pytest backend/tests -v
cd frontend && npm test

# Linting
ruff check backend/
cd frontend && npm run lint
```

---

## Commit Message Format

```
feat([module]): add [feature]
fix([module]): fix [bug]
refactor([module]): refactor [component]
test([module]): add tests for [feature]
docs: update [documentation]
```

---

## Skills Reference

| Task | Skill to Read |
|------|---------------|
| Database models | skills/DATABASE.md |
| API + Auth | skills/BACKEND.md |
| React + UI | skills/FRONTEND.md |
| Testing | skills/TESTING.md |
| Deployment | skills/DEPLOYMENT.md |

---

## Agent Coordination

For complex tasks, the ORCHESTRATOR coordinates:
- DATABASE-AGENT → Backend models
- BACKEND-AGENT → API development
- FRONTEND-AGENT → UI components
- TEST-AGENT → Testing
- REVIEW-AGENT → Code review
- DEVOPS-AGENT → Deployment

Read agent definitions in `/agents/` folder.
```

---

### STEP 4: Confirm and Save

Show the user a summary of what will be generated:

```
═══════════════════════════════════════════════════════════════════
                    PROJECT SETUP COMPLETE
═══════════════════════════════════════════════════════════════════

Product: [Name]
Description: [One-liner]

Tech Stack:
├─ Backend:  [Selection]
├─ Frontend: [Selection]
├─ Database: PostgreSQL
├─ Auth:     [Selection]
└─ UI:       [Selection]

Modules:
├─ Authentication (default)
├─ [Module 1]
├─ [Module 2]
├─ [Module 3]
└─ [Dashboard/Admin if selected]

Additional Features:
├─ [x] [Feature 1]
├─ [x] [Feature 2]
└─ [ ] [Feature 3]

FILES GENERATED:
├─ INITIAL.md (Product definition)
└─ CLAUDE.md (Project rules)

═══════════════════════════════════════════════════════════════════

NEXT STEPS:

1. Review the generated files (optional)
2. Run: /generate-prp INITIAL.md
3. Run: /execute-prp PRPs/[product-name]-prp.md

Would you like me to proceed with /generate-prp now?
═══════════════════════════════════════════════════════════════════
```

---

## Important Notes

1. **Be Conversational** - Make the user feel guided, not interrogated
2. **Provide Examples** - Always show examples for each question
3. **Validate Input** - If user's input is unclear, ask for clarification
4. **Smart Defaults** - Pre-select recommended options
5. **Generate Both Files** - Always create both INITIAL.md and CLAUDE.md
6. **Offer Next Step** - Ask if they want to proceed with /generate-prp
