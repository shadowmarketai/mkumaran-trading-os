# .claude/templates/

Starter templates used by the brownfield and resume skills. Not slash commands — these are boilerplates copied into a project's `.claude/` (or `memory/`) dir on first onboarding.

## Files

### `project-state.template.md`

Copied to `memory/project-state.md` (or `.claude/project-state.md`) by `/onboard-repo` and `/new-client`. Tracks the dossier that every agent reads at session start: identity, current phase, decisions, blockers, next steps.

Auto-updated by `/resume` at the end of each meaningful session.

### `codebase-map.template.md`

Copied to `memory/codebase-map.md` on onboarding. Documents what lives where — directory purposes, key modules, conventions. Re-generated when the tree changes materially (large refactor, new package).

## How it differs from `skills/`

- **Templates** = starter documents meant to be copied once and edited per-project.
- **Skills** = reusable knowledge Claude loads on demand during a task.

If a file belongs in every forked project from day one, it goes here. If it's knowledge Claude should consult when a certain task comes up, it goes in `skills/`.
