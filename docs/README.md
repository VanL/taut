# Documentation Guide

This repository uses a docs-first operating model for agentic development.

## Structure

- `agent-context/`: shared context loaded by agents at session start
- `specs/`: intended behavior, invariants, boundaries, and verification rules
- `plans/`: dated execution documents for concrete changes
- `implementation/`: current rationale, ownership, repository maps, and
  architecture notes
- `../skills/`: reusable task-scoped instructions for recurring workflows
- `lessons.md`: durable corrections and reusable mistakes-to-avoid

## Use By Task

### Starting a Session

Read:

1. `../AGENTS.md`
2. `agent-context/README.md`
3. `implementation/03-agent-inventory.md`, if it exists
4. the relevant spec in `specs/`
5. the active plan in `plans/`, if one exists
6. the relevant implementation note in `implementation/`
7. the relevant skill in `../skills/`, if one exists

### Planning a Change

Read:

- `agent-context/runbooks/writing-plans.md`
- `agent-context/runbooks/hardening-plans.md`
- `agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `agent-context/runbooks/maintaining-traceability.md`

Write the plan in `plans/` with a date-prefixed filename.
For risky or boundary-crossing work, treat `hardening-plans.md` as required
input rather than optional follow-up reading.

### Writing or Updating a Spec

Read:

- `agent-context/runbooks/writing-specs.md`

Keep intended behavior and invariants in `specs/`, then backlink related plans.

### Explaining Current Design

Read:

- `agent-context/runbooks/writing-implementation-docs.md`

Use `implementation/` to capture rationale, boundaries, ownership, and change
guidance. Prefer why over how.

### Managing Reusable Workflows

Read:

- `agent-context/runbooks/skills-lifecycle.md`

Use `../skills/` when a repeated workflow deserves a reusable instruction set
instead of more ad hoc lessons.

### Testing or Debugging

Read:

- `agent-context/runbooks/testing-patterns.md`

Prefer the narrowest proof that exercises real behavior.

## Documentation Standards

- Specs are the source of truth for intended behavior.
- Plans are executable documents for zero-context implementers.
- Strong plans are explicit about what must not change, not only what to add.
- Risky plans are not review-ready until they name hidden couplings,
  anti-mocking posture, rollback or rollout sequencing, one-way doors, and
  post-deploy success signals when those matter.
- Non-trivial plans and final changes should receive independent review.
- Implementation docs explain why the current design exists and what must not
  drift.
- Skills capture recurring workflows that have become stable and reusable.
- Lessons are short, dated, and reusable.
- Documentation maintenance is part of the execution gate for every material
  change.
