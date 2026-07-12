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
2. Read `decision-hierarchy.md`.
3. Read `principles.md`.
4. Read `engineering-principles.md`.
5. Read the relevant runbook(s) in `runbooks/`.
6. Read `lessons.md`.
7. Read `../lessons.md`.
8. Read the relevant spec, active plan, and implementation note for the task.
9. Read the relevant skill under `../../skills/` when one exists.
10. For delegation or independent review, read
    `../implementation/03-agent-inventory.md`.

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
- When a repeated mistake shows up, add a lesson in `../lessons.md` and
  strengthen a runbook if the fix should become reusable guidance.
- When plans keep failing at boundaries, strengthen `writing-plans.md` or
  `runbooks/hardening-plans.md` instead of leaving the correction trapped in a
  single plan.
- When a repeated workflow becomes stable and reusable, promote it into a skill
  under `../../skills/`.
