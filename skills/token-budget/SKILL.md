---
name: token-budget
description: Token discipline for every Claude Code session. ALWAYS active. Enforces read-budget before action, caps per-session token spend, prefers dossier reads over source scans, and stops work when budget is exhausted. Applies to every agent and every skill. Non-negotiable in all modes.
origin: Shadow Market
---

# Token Budget

> Every token costs money. Every re-read is waste. Every agent must respect these rules.

---

## Always active

This skill is NOT opt-in. It activates at the start of every Claude Code session in this repo. Every other skill and agent must defer to its constraints.

---

## The three token laws

### Law 1 — Dossier before source

Before reading ANY source file in the repo:

```
1. Check .claude/project-state.md exists → read it
2. Check .claude/codebase-map.md exists → read it
3. Only THEN read source files — and only the specific ones you need
```

If the dossier says "auth flow lives in backend/app/auth/", you read ONLY those files. You do not scan `backend/app/` looking for auth-related things. The dossier is the map.

If no dossier exists: STOP. Invoke `/onboard-repo` first. Do not proceed with blind scanning.

### Law 2 — Budget per task

Every session declares a budget upfront. Default budgets by command:

| Command / task type | Input token cap | Output token cap |
|---|---|---|
| `/onboard-repo` | 40k | 10k |
| `/resume` | 15k | 3k |
| `/build-marketing-page` | 60k | 20k |
| Simple bug fix | 25k | 5k |
| Feature add | 50k | 15k |
| Refactor | 40k | 10k |
| Free-form question | 10k | 3k |

If the task requires more than the budget, STOP and ask the user before continuing:

```
This task is approaching its token budget.
  Used so far: 38k input / 9k output
  Budget: 40k input / 10k output
  
Options:
  1. Continue with extended budget (+50%) — you approve the spend
  2. Split the task — I finish this subtask, you start next session fresh
  3. Abort — I summarize progress and stop

Which?
```

### Law 3 — No speculative reading

Do NOT read files "just in case." A file read is justified only when:

- The user explicitly mentioned it
- The dossier points to it as the answer
- A test failure / error message references it
- A `git blame` or `git log` request requires it

Anti-patterns that burn tokens:
- "Let me read all the models to understand the domain" → read the ONE model you need
- "Let me check all the tests" → run them, read only the failing ones
- "Let me grep for similar patterns" → grep is cheap, READING every match is not

---

## The read-budget workflow

Before any non-trivial task:

### Step 1 — State the goal in one sentence

"Add a /analytics/daily-summary endpoint that returns total pages printed today."

### Step 2 — List files you think you need

```
- backend/app/routers/analytics.py     (route definition)
- backend/app/models/print_job.py      (data source)
- backend/app/services/                (where business logic lives?)
- tests/integration/test_analytics.py  (test pattern)
```

4 files. Estimate 3-5k tokens each = ~16k input.

### Step 3 — Read in order, STOP when you have enough

Read files one at a time. After each, ask: "Do I have what I need to write the change?"

If yes → stop reading, start writing.
If no → read the next file.

Do NOT read all 4 preemptively. Most of the time you'll know after 2.

### Step 4 — Write. Don't re-read.

Once writing starts, don't cycle back to re-read files you already have. If you need to confirm a detail, use `grep` for the specific symbol, not a full file re-read.

---

## Efficient reading patterns

### Prefer `grep` over `Read` for discovery

```bash
# BAD: read entire file to find one thing
Read("backend/app/routers/auth.py")

# GOOD: find the symbol first, read the scope
Grep("def login", path="backend/app/routers/auth.py")
# then Read just the range around the match
```

### Prefer `ls` + dossier over recursive tree walks

```bash
# BAD: tree the whole project
find . -type f -name "*.py"

# GOOD: consult codebase-map.md, ls the specific folder
ls backend/app/routers/
```

### Prefer paginated reads for big files

```
# BAD: read all 2000 lines
Read("alembic/versions/massive_migration.py")

# GOOD: read the top 100, expand if needed
Read("alembic/versions/massive_migration.py", view_range=[1, 100])
```

### Cache within a session

If you've already read a file in this session, DO NOT read it again. Reference your existing context. Claude Code doesn't actively flush previous reads — they're still available.

---

## Compression patterns

### For skills

Skill descriptions in frontmatter should be under **200 characters**. Longer descriptions bloat every session-start context.

Current skill audit (from reading your template):
- Most skills have descriptions under 200 chars ✓
- `shadow-3d-scroll` description is 550+ chars → compress
- `brownfield-patterns` description is 430+ chars → compress
- `token-budget` (this skill) — MUST be <200 chars

### For agents

Agent markdown files should stay under **3k tokens each**. Anything longer means the agent is trying to do too much and should be split.

Current agent audit:
- `ORCHESTRATOR.md` is ~2.5k → fine
- `frontend-agent.md` is ~2k → fine
- `onboarder.md` is ~3.5k → acceptable given scope

### For CLAUDE.md

Root CLAUDE.md is read on EVERY session. Keep it under **8k tokens**. If it grows beyond that, move content into referenced skills.

Current `CLAUDE.md` is ~12k. Candidates for extraction:
- "Role-Based Access Rules" table → move to `skills/auth/SKILL.md`
- "Business Rules" section → move to `skills/business-logic/SKILL.md` (project-specific)
- "API Conventions" → already covered by `api-design` skill, delete duplicate

---

## Progressive skill disclosure

Anthropic's Claude Code loads skill *descriptions* at session start, then loads full skill content only when the skill activates. This is already efficient — BUT you can make it more efficient:

### Rule A — Skills have tight descriptions

Description = 1 sentence. The trigger condition. Not the full explanation.

```markdown
# BAD (160 tokens)
description: This skill provides comprehensive patterns for building React components, including state management, performance optimization, data fetching strategies, form handling, accessibility, and responsive design. Use when building any React component or when the user asks about React best practices.

# GOOD (30 tokens)
description: React component patterns (state, data fetching, forms, a11y). Activate when building any React component.
```

### Rule B — Only include a skill if it can activate

Your template has skills for Swift, Kotlin, Flutter, Compose Multiplatform, Android. If you're not building native mobile, DELETE these. They cost tokens every session for zero benefit.

### Rule C — Group related skills

Instead of 6 TypeScript-adjacent skills, have one `typescript-patterns` skill that covers the lot. Fewer descriptions loaded at session start.

---

## The token kill list

Immediate deletions recommended for token savings (from reading your template):

| File | Why | Tokens saved per session |
|---|---|---|
| `skills/android-clean-architecture/` | No Android work | ~80 |
| `skills/compose-multiplatform-patterns/` | No native work | ~80 |
| `skills/flutter-dart-code-review/` | No Flutter work (confirm first) | ~80 |
| `skills/kotlin-coroutines-flows/` | No Kotlin work | ~80 |
| `skills/kotlin-patterns/` | No Kotlin work | ~80 |
| `skills/swift-actor-persistence/` | No Swift work | ~80 |
| `skills/swift-concurrency-6-2/` | No Swift work | ~80 |
| `skills/swift-protocol-di-testing/` | No Swift work | ~80 |
| `skills/swiftui-patterns/` | No Swift work | ~80 |
| `rules/swift/` | No Swift work | ~200 |
| `rules/kotlin/` | No Kotlin work | ~200 |
| `agents/flutter-*.md` (2 files) | No Flutter work | ~500 |
| `agents/react-native-agent.md` | Confirm if used | ~250 |
| `login-page.png` | Not used by Claude | ~0 (but dir clutter) |
| `localhost` (empty file) | Garbage | ~0 |

Potential savings per session: **~2000 tokens** just at startup. Over 100 sessions/month = **200k tokens saved**.

**BEFORE deleting**, confirm with the user. Only delete what is genuinely unused.

---

## Enforcement

This skill is read on every session. The agents/commands that follow must respect its laws. Specifically:

- `onboarder` must stay under 40k input tokens
- `ORCHESTRATOR` must check token spend after each phase
- Every agent must estimate tokens before long reads
- No agent may read a file it has already read this session

If an agent violates these rules, the user should see a budget warning. The warning itself is cheap; over-spending is not.
