# Agent Context Hub

This folder is the canonical shared context for coding agents, automation
agents, and human contributors working in this repository.

## Goals

- Keep one repo-owned source of truth for durable execution standards.
- Reduce drift across agent-specific root files.
- Make planning, testing, and documentation maintenance explicit.
- Make review loops, agent bootstrap, and skill maintenance explicit.
- Keep spec, plan, implementation, and code traceability bidirectional.

## Canonical Startup Order

This is the one canonical startup sequence. Root entry points and newcomer
guides link here rather than copying it.

1. If it was not already loaded by the tool, read `../../AGENTS.md`.
2. Read `../program-theory.md` — conceptual identity of **this
   product** (frames placement and refusal; load-bearing for
   product-scope judgment — audits, reviews, feature-fit and design
   opinions — not only for implementation). Theory does not override
   the winning product contract.
3. Read `decision-hierarchy.md`.
4. Read `principles.md`.
5. Read `engineering-principles.md`.
6. Read the relevant runbook(s) in `runbooks/`.
7. Read `lessons.md`.
8. Read `../lessons.md` — required startup reading is the **Golden Rules
   plus dated entries after the lessons watermark** (see
   `../coalescing.md`); older entries are searchable reference.
9. Read the relevant spec, active plan, and implementation note for the task.
10. Read the relevant skill under `../../skills/` when one exists.
11. For delegation or independent review, read
    `../implementation/03-agent-inventory.md`.

Read-order compliance is a declared-claim floor, not a gate: when you
produce product-scope judgment — a plan, review, audit, or design
opinion — declare which of these surfaces you consulted. Plans do this
via their source-documents section; plan-free work declares it in its
report. The declaration is checked by review, like task classification
([DOM-15]), not by tooling.

## Runbooks

- `writing-plans.md`: how to write executable implementation plans (including
  spec baseline, proposed spec delta, promotion slices, and status
  mechanisms)
- `hardening-plans.md`: required companion for risky or boundary-crossing plans
  that must survive review
- `review-loops-and-agent-bootstrap.md`: how to bootstrap available agents and
  run independent plan/work reviews
- `writing-specs.md`: how to define intended behavior with stable references
- `writing-implementation-docs.md`: how to capture rationale and boundaries
- `testing-patterns.md`: how to choose the right proof and avoid weak tests
- `adversarial-acceptance-probes.md`: black-box probe kit and invariant floors
  for accepting agent-built tools
- `maintaining-traceability.md`: how to keep docs synchronized during delivery
- `skills-lifecycle.md`: how to add, update, and retire reusable skills
- `external-skill-suites.md`: precedence and crosswalk for external skill
  suites (superpowers, gstack, Every's compound engineering)

## What Belongs Here

- durable decision policies
- reusable engineering workflow guidance
- short pointers into the canonical lessons ledger

## What Does Not Belong Here

- product or architecture specs that define the system itself
- one-off execution notes for a single task
- agent-vendor-specific syntax that is not reusable across tools

## Maintenance Rules

- Keep files short, operational, and repository-owned.
- Prefer checklists and direct rules over long prose.
- When `../coalescing.md` shows a tripped threshold, report it and respond
  per [DOM-14]: a checked-deferred line with derived counts, or a full
  sweep (its own unit of work) on user request, at twice the threshold, or
  at a completion boundary. The session-start check itself is read-only.
- When a repeated mistake shows up, add a lesson in `../lessons.md` and
  strengthen a runbook if the fix should become reusable guidance.
- When plans keep failing at boundaries, strengthen `writing-plans.md` or
  `runbooks/hardening-plans.md` instead of leaving the correction trapped in a
  single plan.
- When a repeated workflow becomes stable and reusable, promote it into a skill
  under `../../skills/`.
