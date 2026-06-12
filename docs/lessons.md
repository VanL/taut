# Lessons Learned

Use this file for durable, project-level lessons that should influence future
sessions.

## When To Add A Lesson

- A correction exposed a repeated failure mode.
- A missing document or runbook caused rework.
- A plan or spec was too ambiguous to execute safely.
- A completed change revealed a stronger general rule than the repo previously
  encoded.

## Project Lessons

- 2026-06-12: Code-first was accepted for the v0.1 bootstrap uplift and
  promptly demonstrated its cost: the one module that shipped with zero
	  tests (identity capture) is exactly where the release-gating bug lived
	  (macOS `ps` truncates `exe` to 16 chars → the shell-skip walk anchors
	  on the per-command wrapper → a new identity is minted on every
	  invocation). Classification must use untruncated `argv[0]` evidence
	  alongside `comm`/`exe`, and macOS executable-path tests should symlink
	  signed system binaries rather than copying them. TDD is now the
	  codified general rule
  (`docs/agent-context/runbooks/testing-patterns.md`, rule 5); the
  bootstrap exception survives only with its test debt enumerated and
  burned down before release.

- 2026-06-12: Allocate broker timestamps only after a command is known to
  mutate taut state. A timestamp generated for convenience still updates the
  broker's high-water mark; doing that during guest read-only identity
  resolution violates the "nothing is written" contract and can distort
  thread metadata if later code reads database-wide timestamp hints.

- 2026-06-12: Treat watcher construction validation and watcher refresh as
  different phases. Explicit watch filters should fail fast when no initial
  membership exists, but a missing membership during refresh is normal
  convergence and should drop the queue, clear per-thread transient state, and
  keep the watcher alive.

- 2026-06-12: Two different reuse modes, chosen by the shape of the
  source. Vendor whole-and-faithfully when the source is one stable
  class (taut's multi-queue watcher: copied entire, provenance recorded,
  diffable against upstream). For an evolving multi-part subsystem
  (Weft's agent task), partial vendoring is reimplementation in denial —
  the extraction cuts exactly the interactions where bugs live and the
  copy drifts. There, copy the *contract* (verbs, queue shapes,
  semantics, with divergences documented) and transfer findings as a
  portable executable conformance suite both projects run, not as prose
  lessons. See `docs/specs/02-taut-core.md` [TAUT-12.3].

- 2026-06-12: Consume-oriented watcher primitives do not transfer to
  broadcast/history semantics unmodified. Weft's `MultiQueueWatcher` PEEK
  mode head-peeks (`peek_one()`), so without a per-queue cursor it
  re-delivers the head message and never lets the queue go inactive. Any
  peek-based consumer needs cursor-aware fetch *and* cursor-aware pending
  checks (`peek_many(after_timestamp=…)` + `has_pending(after_timestamp=…)`).
  See `docs/specs/02-taut-core.md` [TAUT-8.4] and comprehension Q1/Q2 in
  `docs/plans/2026-06-12-taut-foundation-plan.md`.

## Starter Lessons

- Keep canonical agent guidance in shared repo-owned docs and make root agent
  files point to that context instead of carrying divergent copies.
- Non-trivial plans must be executable by a zero-context engineer: exact
  source references, exact files, invariants, verification commands, and a
  fresh-eyes review are required.
- Specs define intended behavior; implementation docs explain why the current
  design exists. Blending those roles causes drift.
- Documentation maintenance is part of the completion gate. If code changes
  without plan/spec/implementation alignment, the work is incomplete.
- Non-trivial plans should be reviewed by an independent agent, and the
  authoring agent should answer each review point by updating the plan or
  documenting why the current path is still the best choice.
- Prefer symlinks from tool-specific root guidance files such as `CLAUDE.md`
  to `AGENTS.md` when the environment supports them; thin pointer files are the
  fallback.
- Optimize docs for agent usability, not just human readability. If something
  is human-clear but agent-ambiguous, call it out and suggest a specific fix.
  Check for missing owner, boundary, verification, or required action.
