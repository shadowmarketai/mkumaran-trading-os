---
name: brownfield-patterns
description: Patterns for safely modifying existing codebases. ALWAYS activate when the repo has prior commits, existing test suites, or an onboarding dossier. Enforces read-before-write, pattern matching over pattern imposition, minimal diffs, and test-bracketed changes. Use when tasks involve refactoring, adding features to existing code, fixing bugs, or any work where a project-state.md exists.
origin: Shadow Market
---

# Brownfield Patterns

> How to work safely in code you didn't write.

Greenfield coding builds from a blank page. Brownfield coding modifies something that already works (or half-works) for real users. The two require different instincts. This skill teaches the brownfield instincts.

---

## When to activate

Activate when ANY of these are true:

- `.claude/project-state.md` exists → this is an onboarded repo, treat everything as brownfield
- The repo has >50 commits or is older than 3 months
- Production traffic is hitting this code
- The user says "fix", "modify", "update", "refactor", "extend", "improve"
- A test suite exists and passes

Do NOT activate for:
- True greenfield repos (just initialized, following a fresh PRP)
- Throwaway prototypes or spikes
- Example/demo repos being used for learning

---

## The four brownfield laws

### Law 1 — Read 10x more than you write

Before writing a single line in an unfamiliar area:

```
1. Read the file you're modifying END TO END (not just the function)
2. Read the 1-3 most recent commits that touched this file
3. Search the codebase for 3 similar patterns and read them
4. Read the test file for the code you're modifying
```

Anti-pattern: jumping straight to edits because "I know how React works." You know React. You don't know how THIS codebase does React. Every team has idioms.

### Law 2 — Match patterns, don't impose them

If the codebase uses:
- `useState` + `useReducer` → don't add Zustand "because it's better"
- `axios` → don't add `fetch` "because it's native"
- Class components → don't rewrite to hooks unless asked
- `snake_case` variables → don't switch to `camelCase`
- 2-space indent → don't switch to 4

The team chose these for reasons you don't see. When you impose your preferences, you:
- Break code review (diff full of unrelated changes)
- Fragment the codebase into "old" and "new" patterns
- Force the next person to decide which pattern to follow

If you genuinely believe the existing pattern is wrong, say so in a separate message. Don't sneak it into a feature PR.

### Law 3 — Minimal diffs

A good brownfield change looks like: "added 12 lines, modified 3, deleted 0."
A bad one looks like: "added 200 lines, modified 80, deleted 40" — even if the feature is small.

Rules:
- Don't reformat files you're editing. If formatter disagrees, that's a separate commit.
- Don't rename variables you're not using.
- Don't refactor "while you're in there."
- Don't add TypeScript strictness to files that weren't strict.
- Don't pin dep versions you didn't change.

The diff should describe the change. If the diff has unrelated noise, it no longer describes the change.

### Law 4 — Test-bracketed changes

Before writing the change:
```bash
# Run existing tests — capture the baseline
npm test 2>&1 | tail -20
# or
pytest 2>&1 | tail -20
```

If tests fail BEFORE your change, that's a finding — flag it, don't silently accept it as "the existing state."

After writing the change:
```bash
# Run again — your change must not break anything new
npm test 2>&1 | tail -20
```

If your change turned green tests red:
- You broke something. Fix it before proceeding.
- "The test was wrong" is sometimes true but rarely. Prove it.

If the feature has no tests, ADD one for your change. Don't let untested code grow.

---

## The 5 brownfield entry points

Depending on the user's ask, use one of these entry sequences:

### Entry A — "Add a feature here"

1. Read `.claude/project-state.md` + `.claude/codebase-map.md`
2. Find the file where similar features live
3. Read that file end-to-end + its test
4. Copy the pattern, adapt to new feature
5. Add test mirroring existing test style
6. Run all tests, commit minimally

### Entry B — "Fix this bug"

1. Reproduce the bug first — do not start fixing before reproducing
2. Write a failing test that captures the bug
3. Make the test pass with the minimum change
4. Confirm no other tests broke
5. Commit the test + fix together

If you can't reproduce, the report is ambiguous. Ask the user for:
- Exact steps
- Expected vs actual
- Environment (dev/staging/prod)
- Logs or screenshots

### Entry C — "Refactor this"

1. STOP. Ask: "Is this refactor user-visible? If not, why now?"
2. Confirm test coverage exists for the code being refactored
3. If no tests → add tests FIRST (characterization tests)
4. Refactor in small commits, each keeping tests green
5. Never refactor + add feature in one commit

### Entry D — "I don't know where to start"

Invoke the `onboarder` agent if no dossier exists. Otherwise invoke `/resume`. Never guess.

### Entry E — "Make this faster / better / cleaner"

Ask for a concrete metric before touching code:
- Faster by how much? What's slow now?
- Better how? Against what criterion?
- Cleaner how? Specific files or the whole codebase?

Without a metric, "improvement" is subjective and the diff will fight the reviewer.

---

## Reading the codebase efficiently

You don't have infinite context. Be surgical.

### Where to look first

For a file `src/features/billing/invoice.ts`, read in this order:
1. `src/features/billing/invoice.ts` itself
2. `src/features/billing/` — siblings (similar feature implementations)
3. Test: `src/features/billing/__tests__/invoice.test.ts` or equivalent
4. Consumers: `git grep -l "from.*billing/invoice"` → read 1-2 callers
5. Type definitions it imports from

Skip:
- Unrelated feature folders
- Build config unless deps are the question
- Documentation unless the task is doc-related

### Using `git log` as a map

```bash
# Who wrote this code, when?
git log --follow -p path/to/file.ts | head -100

# What was changed in this folder recently?
git log --oneline -20 -- path/to/folder/

# Why was this weird thing added?
git log -S "weird_string" -- path/to/file.ts
```

Commit messages encode decisions. Read them.

---

## Updating the dossier

Every brownfield session updates `.claude/project-state.md`:

**At start of session:**
- Read the dossier
- Add a new "Session log" entry header with date and goal

**During session:**
- If you discover an architectural quirk → add to "Gotchas"
- If you make a non-obvious decision → add to "Decisions log"
- If you find tech debt but don't fix it → add to "Known issues"

**At end of session:**
- Mark completed TODOs
- Add new TODOs that emerged
- Update "Current phase" if it shifted
- Fill in what you did / what's blocked / what's next

Commit the dossier update alongside code changes.

---

## The "I don't understand this code" protocol

When you genuinely don't understand a pattern:

1. **DO NOT** guess and write around it
2. **DO NOT** rewrite it "because it's unclear"
3. **DO** read `git blame` on the lines in question
4. **DO** read the PR that introduced it (GitHub link in commit message)
5. **DO** ask the user: "This does X in a way I don't understand. Before I touch it: is there a reason?"

Unknown code usually has a reason. The cost of misunderstanding it is higher than the cost of asking.

---

## Common brownfield traps

| Trap | Why it hurts | Correct move |
|---|---|---|
| "Let me modernize this while I'm here" | Doubles diff size, breaks review | Separate commit/PR for modernization |
| "The tests are slow, I'll skip them" | You shipped a regression | Run them; if too slow, make that the issue |
| "The linter is noisy, I'll disable it" | Disables it for everyone | Fix the specific warnings in your file |
| "This pattern is weird, I'll use the standard one" | Fragments the codebase | Match existing pattern; raise separately |
| "I'll add the types later" | Later = never | Types with the change, not after |
| "Let me bump this dep version" | Untracked behavior changes | Separate commit, separate review |
| "I'll rewrite the failing test" | Green tests aren't truth | Understand why it fails first |

---

## When to violate these laws

The laws above have exceptions. A non-exhaustive list:

- **The repo is a genuine mess and the user asked for cleanup** → large diffs are the job
- **Critical security fix** → ship now, refactor later
- **Deprecated dependency with CVE** → upgrade + tests, bigger diff is justified
- **Codebase consensus has already shifted** (e.g., half the files use the new pattern) → converge to the new one

When violating, SAY so in the commit message and session log. Make the decision visible.
