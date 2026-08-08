# Documentation Guide

This repository uses a docs-first operating model for agentic development.

## Layers and Ownership

Documentation is layered; each surface has one role, and overlap is
resolved by ownership, not duplication:

| Surface | Role |
|---------|------|
| `README.md` (root) | Human product entry; per section, the contract of record until the registry cedes that section to a spec |
| `docs/specs/product-section-registry.md` | Authority table: the winning contract (README section or spec) for each behavior family |
| `docs/program-theory.md` | Conceptual account — what kind of system Taut is (its THEORY-7 defines the registry mechanism) |
| `docs/specs/` | Exact intended behavior, invariants, and verification rules (normative) |
| `docs/agent-kernel.md` | The sole home of agent-executable product recipes; a view, never a contract |
| `llms.txt` (root) | Link index for language models (llmstxt.org format; absolute URLs) |
| `extensions/*/README.md` | Extension depth: requirements, installation, configuration, usage |
| `CHANGELOG.md` (root) | Released behavior deltas |
| `docs/plans/` | Dated execution records (immutable history once completed) |
| `docs/implementation/` | Current rationale, ownership, boundaries, repository maps |
| `docs/lessons.md`, `docs/coalescing.md` | Incident ledger and its compaction state |

Three rules keep the layers honest:

- **Duplication resolution:** a behavior statement lives once, in its
  owning surface; any other surface restates at most a compact summary
  plus a link. When two surfaces disagree, fix the non-owner.
- **Conflict:** for a family registered `canonical-spec`, the spec
  wins **where it speaks**, and the README restates and links. Ceding
  is promise-granular: a README promise the owning spec does not state
  (or states only in recorded-stale form — see the registry's
  README-owned list) remains README-owned; do not delete or "correct"
  it against spec silence. For a `readme-only` family, the README is
  the contract until promotion.
- **Promotion:** a `readme-only` family becomes spec-owned by landing
  the spec text, flipping its registry row, and binding the README
  section to the spec — never by silent drift.

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

Follow the single canonical sequence in `agent-context/README.md`. For
newcomer orientation after that sequence, use `implementation/00-implementation-index.md`
and `implementation/02-repository-map.md`.

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
