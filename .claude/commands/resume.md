# Resume

Pick up work on a repo that has already been onboarded. Reads the dossier, shows current state, and asks what to work on next.

## When to use

- Returning to a Shadow Market project after a few days/weeks
- Starting a new Claude Code session on an already-onboarded repo
- Context switch between client projects

## When NOT to use

- The repo has no `.claude/project-state.md` → use `/onboard-repo` first
- You want a fresh dossier (architecture changed significantly) → use `/onboard-repo` again to refresh

## Step 1: Verify onboarding exists

```bash
test -f .claude/project-state.md || echo "NOT ONBOARDED"
```

If not onboarded, stop and suggest `/onboard-repo`.

## Step 2: Read the dossier

Read in this order:
1. `.claude/project-state.md` — current state, open TODOs, decisions log
2. `.claude/codebase-map.md` — where things live
3. `git log --oneline -10` — what happened since last session
4. `git status` — anything uncommitted?

## Step 3: Detect staleness

Compare the dossier's "last updated" timestamp to recent git activity:

- Dossier is <7 days old AND <20 commits since → fresh, no refresh needed
- Dossier is 7–30 days old OR 20–100 commits since → read the git log carefully, flag any major changes
- Dossier is >30 days old OR >100 commits since → recommend re-running `/onboard-repo` to refresh

## Step 4: Report state to user

Show:

```
Resuming: <Project Name>
Last worked: <N days ago>
Commits since: <N>
Current phase: <from dossier>
Uncommitted changes: <yes/no, summary if yes>

Open items from the dossier:
  [ ] <TODO 1 from project-state.md>
  [ ] <TODO 2>
  [ ] <TODO 3>

Recent commits:
  - <commit 1>
  - <commit 2>
  - <commit 3>

Where do you want to pick up?
  1. Continue the top open TODO: <TODO 1>
  2. Commit the uncommitted work first
  3. Something else — tell me
```

## Step 5: Wait for user direction

Do NOT start coding. Do NOT assume the next action. Ask, then act.

## Update contract

Every time a session ends meaningful work, update `.claude/project-state.md`:
- Mark completed TODOs
- Add new TODOs that emerged
- Update "current phase" if it shifted
- Log any architectural decisions made in this session

This is how the dossier stays useful across sessions.
