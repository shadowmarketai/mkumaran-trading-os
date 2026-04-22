# Template Changelog

## 2026-04-22 — Template hardening pass

### Added
- `scripts/new-client.sh` + `/new-client` slash command — substitutes `{{PROJECT_NAME}}` placeholders, renames `package.json`, seeds `memory/project-state.md`, optionally resets git history
- `scripts/README.md` — documents `new-client.sh`, `_gen_migration.py`, `hooks/`, `lib/`
- `.claude/templates/README.md` — explains `project-state.template.md` + `codebase-map.template.md` and the templates-vs-skills distinction
- `resources/README.md` — layout conventions (brand/ samples/ fixtures/ screenshots/) + "no secrets, no large binaries" rules
- CI status badge in `README.md`
- Agent call graph + dispatch-rules table in `agents/ORCHESTRATOR.md`
- Three-tier knowledge architecture section in `CLAUDE.md` (agent → layer skill → pattern skill)
- 9 compliance skills imported from MicroSaaS-Template (GDPR, PCI DSS, Zero Trust, DAST, SIEM, MFA, encryption, IaC, container scanning)
- `start.sh` + `stop.sh` for macOS/Linux/WSL parity

### Changed
- `README.md` — full rewrite as "fork-and-run" guide (was MicroSaaS-era)
- `CLAUDE.md` — parameterized with `{{PROJECT_NAME}}`, stripped PrintSight business rules, motion stack marked as pre-installed
- `resourses/` → `resources/` (spelling fix)
- PrintSight sample CSVs removed from `resources/`
- `frontend/package.json` name → `shadow-market-template-frontend`
- `.env.example` neutralized (no more PrintSight user/DB defaults)
- `backend/app/models/user.py` — removed domain-specific relationships (Printer, Paper, NotificationConfig, WebhookConfig)
- `skills/shadow-3d-scroll/SKILL.md` — removed "PrintSight fork" phrasing

### Removed
- `backend/app/models/`: paper, printer, toner, upload, notification, webhook
- `backend/app/routers/`: printers, print_jobs, cost_config, analytics, toner_replacements, reports, admin
- `backend/alembic/versions/`: all 3 domain migrations (regenerate via autogenerate)
- `frontend/src/pages/`: dashboard, printers, reports, analytics, settings, admin
- `frontend/src/context/PrinterContext.tsx`
- `PRPs/shadow-market-prp.md` (PrintSight-specific PRP)
- Stale branches: `feature/phase1-implementation`, `claude-upgrade-20260422-094121`

### Known TODOs (intentionally deferred)

These remain on the improvement list but are out of scope for this pass:

- **Stack-swap branches** — Next.js, Django, Rails variants of the template. Current template is FastAPI+React only.
- **Full skills rename** — `skills/FRONTEND.md` → `skills/frontend/LAYER.md` etc. Heavy refactor across ~16 referencing files; lightweight tier-naming doc added instead.
- **Example PRP** with full build→ship cycle as a tutorial. Needs a non-trivial feature spec to make useful.
- **Docker stack cross-platform verification** — `start.sh` tested on Windows bash only; needs macOS + Linux smoke test.
- **Branch protection** — `.github/workflows/ci.yml` exists but no required-checks rule; enforce via GitHub repo settings.
