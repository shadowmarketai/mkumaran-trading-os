# Onboard Repo

Analyze an existing repository and produce a project dossier so Claude Code can work effectively on any part of it.

## When to use

- Opening Claude Code on an unfamiliar repo
- Picking up a client project handed off from another developer
- Returning to a Shadow Market project after weeks away
- Before running `/execute-prp` when the repo already has code (not greenfield)
- When multiple agents keep re-reading the same files because they have no shared context

## When NOT to use

- On a truly empty greenfield repo — go straight to `/execute-prp` with a fresh PRP
- On a repo you just onboarded <24h ago — the dossier is still fresh, just read it
- If you only want to make a one-line fix — overkill

## Step 1: Safety check

Before onboarding, verify:

```bash
git status                                 # must not be dirty
ls .claude/project-state.md 2>/dev/null   # must not exist (if it does, use /resume instead)
```

If a dossier already exists, stop and ask the user:
- "A dossier already exists from [date]. Refresh it, or resume using the existing one?"

## Step 2: Delegate to the onboarder agent

Invoke the `onboarder` agent. It handles the full 7-phase onboarding process:

1. Shallow scan (structure, git log, branches)
2. Manifest deep-read (package.json, pyproject.toml, etc.)
3. Entry point + architecture read
4. Test + CI read
5. Existing docs mining
6. Dossier generation
7. Handoff recommendation

The onboarder is read-only. It will never modify source files.

## Step 3: Read the dossier yourself

Once the onboarder completes, read both output files:

```bash
cat .claude/project-state.md
cat .claude/codebase-map.md
```

Verify the findings match your understanding. If something looks wrong, say so — the onboarder may have misread.

## Step 4: Commit the dossier

```bash
git add .claude/project-state.md .claude/codebase-map.md
git commit -m "docs(claude): onboard repo — project dossier"
```

Committing the dossier means the next person (or next Claude session) inherits the context.

## Step 5: Ask the user what to work on

Based on the dossier's handoff section, present 2–4 concrete next actions. Do NOT start coding until the user picks one.

## Output contract

After this command runs, these files MUST exist and be committed:

- `.claude/project-state.md` — the living state document
- `.claude/codebase-map.md` — annotated directory tree

Every subsequent agent invocation in this repo will read `project-state.md` first. Keep it updated.

## Rules

- NEVER skip onboarding to save time — working blind on an unfamiliar repo costs 3x the tokens
- NEVER modify source files during onboarding
- NEVER write a fresh PRP for an active repo — extend the existing structure instead
- If onboarding takes >15 min, stop and flag it — the repo may need manual triage first
