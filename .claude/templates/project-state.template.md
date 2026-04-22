# Project State

> Living document. Updated at the end of every meaningful Claude Code session.
> Every agent reads this FIRST before doing work.

**Last updated:** YYYY-MM-DD by <agent or user name>
**Dossier version:** 1

---

## Identity

| Field | Value |
|---|---|
| **Project name** | _____________ |
| **Client** | _____________ |
| **Type** | [Marketing site / SaaS dashboard / Mobile app / Internal tool / Library] |
| **Status** | [Greenfield / Active development / Maintenance / Dormant / Broken] |
| **Started** | YYYY-MM-DD |
| **Target ship date** | YYYY-MM-DD or "ongoing" |
| **Primary contact** | _____________ |

---

## Stack

| Layer | Technology | Version | Notes |
|---|---|---|---|
| Frontend | | | |
| Backend | | | |
| Database | | | |
| Auth | | | |
| Hosting | | | |
| CI/CD | | | |
| Monitoring | | | |

---

## Architecture summary

_2–4 paragraphs. What is this system, how does it work at a high level, what are the key data flows?_

**Main entry points:**
- Frontend: `path/to/main.tsx`
- Backend: `path/to/main.py`
- Database migrations: `path/to/alembic/` or equivalent

**Key abstractions:**
- _List 3–5 core models/concepts a new developer must understand_

---

## Current phase

_One sentence. What is being worked on right now?_

Example: "Phase 3 of 5 — building the analytics dashboard. Backend endpoints are live, frontend pages are stubs."

---

## Open TODOs

Ordered by priority. The top item is what `/resume` suggests next.

- [ ] **HIGH** — _item 1 with enough context to pick up without re-reading code_
- [ ] **HIGH** — _item 2_
- [ ] **MED** — _item 3_
- [ ] **LOW** — _item 4 (nice to have)_

---

## Recently completed

Last 10 things closed, newest first. Prune older items periodically.

- [x] YYYY-MM-DD — _what was done, where_
- [x] YYYY-MM-DD — _..._

---

## Decisions log

Non-obvious decisions made during development. Why we chose X over Y. Every agent must respect these.

| Date | Decision | Rationale |
|---|---|---|
| YYYY-MM-DD | Chose Lenis over ScrollSmoother | GSAP Club license cost; Lenis is MIT |
| YYYY-MM-DD | No Redis — use Postgres LISTEN/NOTIFY | Ops simplicity for Year 1 |
| | | |

---

## Known issues / tech debt

Things that are broken or ugly but intentionally left alone. Flag them so agents don't "fix" them.

- _Issue 1 and why it's parked_
- _Issue 2 and when to revisit_

---

## Gotchas for new contributors

Things that confused the onboarder or recent developers. Save future time.

- _Non-obvious thing 1_
- _Non-obvious thing 2_

---

## Active agents / skills

Skills that are particularly relevant to this project. Agents should activate these by default when working here.

- `skills/<name>` — _why it applies_
- `skills/<name>` — _..._

---

## Deployment

**Production URL:** ___
**Staging URL:** ___
**Deployment trigger:** [auto on merge to main / manual / CI]
**Last deploy:** YYYY-MM-DD
**Rollback procedure:** _link or 1-line summary_

---

## Secrets and config

Reference only — do NOT store secrets here.

- See `.env.example` for required vars
- Secrets stored in: [Coolify env vars / Vercel env vars / .env.local / 1Password]
- Who has access: _____________

---

## Session log

Recent Claude Code sessions. Most recent at top. Keeps the thread across handoffs.

### YYYY-MM-DD — <session summary in 1 line>
- Worked on: _..._
- Completed: _..._
- Blocked on: _..._
- Next up: _..._

### YYYY-MM-DD — <previous session>
- _..._

---

## Links

- Repo: _link_
- Issue tracker: _link_
- Design file: _link_
- Client docs: _link_
- Deployment dashboard: _link_
