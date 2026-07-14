# Documentation System

## Purpose and Scope

This document explains why the repository is organized around shared agent
context, specs, dated plans, implementation docs, reusable skills,
independent reviews, and a lessons ledger.

This file started as the scaffold installed from the agent-guidance
repository and is project-owned: the taut product code and its
repo-specific boundaries are documented in
`docs/implementation/04-taut-architecture.md`.

## Governing Spec References

- `docs/specs/01-development-documentation-operating-model.md` [DOM-2]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-3]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-4]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-7]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-8]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-12.5]

## Design Rationale

### Shared Agent Context

The repository keeps durable guidance in `docs/agent-context/` so multiple
agent tools can consume one source of truth. Root files such as `AGENTS.md`
and tool-specific aliases are intentionally thin entry points rather than
separate policy documents.

### Separate Specs, Plans, and Implementation Docs

The split exists because each document answers a different question:

- specs answer what should be true
- plans answer how a specific change will be executed without breaking
  load-bearing boundaries
- implementation docs answer why the current design exists and where it lives

Combining those roles makes documents harder to trust and easier to let drift.

### Documentation As a Delivery Gate

The repository treats documentation maintenance as part of completion because
the main failure mode in agentic development is silent drift between intent,
execution, and implementation.

### Planning Cost Follows Novelty

Task classification scales planning and review effort, not verification.
Classes 1 and 2 keep a compact record in git or the handoff; classes 3 and
above use dated plans. A normal release is the narrow exception to Class 2's
usual reversibility rule because `bin/release.py` already owns the hardening:
universal local gates, exact-SHA CI evidence, tag fences, artifact checks, and
built-in resumable batches. Only execution of that unchanged path receives the
exception. Product work, machinery changes, disabled gates, override flags,
manual publication, and recovery outside the built-in path classify normally.

### Scaffold Boundary

The bootstrap script installs only the neutral starter surface. It does not
infer repo-specific engineering principles, merge with existing docs, or decide
what your product architecture should be.

## Boundaries and Invariants

- `docs/agent-context/` is the canonical shared context surface.
- `docs/specs/` is the source of truth for intended behavior.
- `docs/plans/` contains dated execution records.
- `docs/implementation/` explains rationale and important edit points.
- `skills/` stores reusable task-scoped workflow instructions.
- `docs/lessons.md` is the one canonical lessons ledger.

These roles should stay distinct even as taut grows.

## Key Files

| Path | Purpose |
|------|---------|
| `AGENTS.md` | Primary agent entry point |
| `CLAUDE.md` | Alias for tools that expect Claude-style root guidance |
| `docs/agent-context/README.md` | Shared context hub |
| `docs/specs/00-specs-index.md` | Numbered entry point for specs |
| `docs/specs/01-development-documentation-operating-model.md` | Governing operating-model spec |
| `docs/implementation/00-implementation-index.md` | Numbered entry point for implementation docs |
| `docs/implementation/02-repository-map.md` | Quick pointer map for important docs |
| `docs/implementation/03-agent-inventory.md` | Current observed agent availability and review preference |
| `skills/README.md` | Skill directory conventions and promotion criteria |

## Change Guidance

When work changes product code or its governing boundaries:

1. add or update the governing spec first
2. classify the unit under [DOM-15]; create a dated plan for Class 3 and above,
   while Classes 1 and 2 keep their record in git or the handoff
3. for risky work, harden the plan before implementation by making invariants,
   hidden couplings, anti-mocking guidance, rollback or rollout, and one-way
   doors explicit
4. run independent plan review and feed the results back into the plan
5. add or update the relevant implementation note for the touched area
6. update the repository map when new entry points become important
7. decide whether repeated workflow knowledge should become or update a skill
8. capture reusable corrections in `docs/lessons.md`
