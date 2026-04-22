---
description: Initialize a freshly forked template for a new client project. Substitutes {{PROJECT_NAME}}, renames package.json, creates memory/.
---

# /new-client

Run the client-initialization script for this forked template.

## Usage

```bash
./scripts/new-client.sh "<ProjectName>" [slug]
```

Examples:
- `./scripts/new-client.sh "Acme HRMS"` → slug auto-derived as `acme-hrms`
- `./scripts/new-client.sh "Livvly" livvly-app` → explicit slug

## What it does

1. Substitutes `{{PROJECT_NAME}}` across `CLAUDE.md`, `README.md`, `.env.example`
2. Renames `frontend/package.json` `name` to `<slug>-frontend`
3. Creates `memory/project-state.md` with project metadata
4. Optionally resets git history for a clean initial commit

## After it runs

1. `cp .env.example .env` → edit DB creds + SECRET_KEY
2. `cd backend && alembic revision --autogenerate -m "initial_users" && alembic upgrade head`
3. `cd frontend && npm install`
4. Back in Claude: `/onboard-repo` → `/generate-prp`

## When NOT to run it

- Not a fresh fork (you've already built features on top)
- `{{PROJECT_NAME}}` is already substituted (idempotency is best-effort; re-running with a different name will overwrite the first)
