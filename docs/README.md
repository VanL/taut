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

### Known documentation gaps

Recorded at the 2026-08-07 information-architecture cutover and carried
here so they outlive that plan: there is no tutorial or learning path beyond
the README Quick Start (a two-agent first-workspace walkthrough is the
natural piece); a configuration how-to is deliberately not written
(default no, per that plan's review); and presence and liveness remain the
thinnest explanation in the corpus. Each is a candidate for its own plan
when a reader asks for it, not a promise.

## Directory Structure

Each directory or top-level file answers one specific question:

- `program-theory.md`: what kind of system **this repository** is, who owns its
  core concepts, what it refuses to build, and what evidence would show that
  model is wrong
- `agent-context/`: shared rules, principles, and runbooks loaded by agents at
  session start
- `specs/`: behavioral contracts (intended behavior, invariants, and
  verification) plus reference definitions such as
  `specs/07-agent-theory-and-program-theory.md`
- `plans/`: dated execution plans for non-trivial changes, tracked in
  `plans/README.md`
- `implementation/`: design rationale, ownership boundaries, repository maps,
  and agent availability
- `../skills/`: step-by-step instructions for recurring workflows
- `lessons.md`: golden rules and dated corrections from past mistakes
- `coalescing.md`: thresholds, watermarks, and run log for periodic
  distillation of completed plans and lessons

## What to Read by Task

### Understanding Agent Theory and Program Theory

Read these on demand when onboarding or before drafting a theory file (not at
every session start):

- `specs/07-agent-theory-and-program-theory.md` — short primer defining the
  terms and how the documents fit together
- `program-theory.md` — the working theory of **this repository** (Taut's
  identity account)
- `../skills/crystallize-program-theory/SKILL.md` — one-question-at-a-time
  interview for writing a product or module theory

### Starting a Session

Follow the single canonical sequence in `agent-context/README.md`. For
newcomer orientation after that sequence, use `implementation/00-implementation-index.md`
and `implementation/02-repository-map.md`.

### Planning a Non-Trivial Change (Classes 3–5)

Read:

- `agent-context/runbooks/writing-plans.md`
- `agent-context/runbooks/hardening-plans.md` (required for risky or
  boundary-crossing changes)
- `agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `agent-context/runbooks/maintaining-traceability.md`

Write a dated plan in `plans/YYYY-MM-DD-<slug>.md` and add a row to the status
index in `plans/README.md`.

### Writing or Updating a Spec

Read `agent-context/runbooks/writing-specs.md`. Put intended behavior,
invariants, and stable reference codes in `specs/`, and link the related plans
at the bottom of the spec.

### Explaining Why the Code Is Shaped This Way

Read `agent-context/runbooks/writing-implementation-docs.md`. Use
`implementation/` to explain design tradeoffs, ownership boundaries, and key
edit points rather than narrating the code line by line.

### Creating or Updating a Skill

Read `agent-context/runbooks/skills-lifecycle.md`. Promote a workflow into
`../skills/` once it has recurred across multiple tasks and needs a repeatable
checklist.

### Testing or Debugging

Read `agent-context/runbooks/testing-patterns.md` (plus
`../skills/test-audit/SKILL.md` when authoring, changing, reviewing, or
auditing tests; `../skills/test-audit/SWEEP.md` when pruning a whole
subsystem's test surface; and `../skills/debugging/SKILL.md` when diagnosing a
bug). Prefer tests that exercise real code paths over heavy mocking.

## Core Documentation Standards

- **Specs own intended behavior.** Update the spec before or alongside any
  material behavior change.
- **Plans are written for zero-context engineers.** State what must *not*
  change, not only what to add.
- **Risky plans require explicit hardening.** Name hidden couplings, what must
  not be mocked, rollback or rollout order, one-way doors, and post-deploy
  checks before implementation starts.
- **Non-trivial plans and completed changes get an independent review** from a
  different model family when available.
- **Implementation docs explain *why*, not just *how*.**
- **Documentation updates are part of the completion gate**, never optional
  follow-up cleanup.
