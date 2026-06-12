# Repository Map

Quick pointers to the key guidance documents in this repository.

## Root Entry Points

| Path | Purpose |
|------|---------|
| `AGENTS.md` | Canonical agent entry point |
| `CLAUDE.md` | Alias for tools that expect Claude-style root guidance |
| `README.md` | Product face and v0.1 behavior contract (see `docs/specs/02-taut-core.md`) |

## Shared Agent Context

| Path | Purpose |
|------|---------|
| `docs/agent-context/README.md` | Context hub and read order |
| `docs/agent-context/context.index.yaml` | Machine-readable context index |
| `docs/agent-context/decision-hierarchy.md` | Conflict-resolution order |
| `docs/agent-context/principles.md` | Shared execution principles |
| `docs/agent-context/engineering-principles.md` | Engineering rules and warning signs |

## Runbooks

| Path | Purpose |
|------|---------|
| `docs/agent-context/runbooks/writing-plans.md` | Plan-writing standard |
| `docs/agent-context/runbooks/hardening-plans.md` | Required hardening checklist for risky or boundary-crossing plans |
| `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` | Independent review workflow and agent bootstrap |
| `docs/agent-context/runbooks/writing-specs.md` | Spec-writing standard |
| `docs/agent-context/runbooks/writing-implementation-docs.md` | Implementation-doc standard |
| `docs/agent-context/runbooks/testing-patterns.md` | Testing and verification guidance |
| `docs/agent-context/runbooks/maintaining-traceability.md` | Documentation-maintenance gate |
| `docs/agent-context/runbooks/skills-lifecycle.md` | Skill promotion and maintenance guidance |

## Core Documentation Corpus

| Path | Purpose |
|------|---------|
| `docs/specs/00-specs-index.md` | Numbered entry point for specs |
| `docs/specs/01-development-documentation-operating-model.md` | Governing spec for the documentation workflow |
| `docs/specs/02-taut-core.md` | Taut v0.1 core spec: storage, identity, envelope, read model, surfaces, trust model |
| `docs/plans/README.md` | Plan directory rules |
| `docs/plans/2026-06-12-taut-foundation-plan.md` | Active plan for the v0.1 implementation |
| `docs/implementation/00-implementation-index.md` | Numbered entry point for implementation docs |
| `docs/implementation/01-documentation-system.md` | Why the documentation system is shaped this way |
| `docs/implementation/03-agent-inventory.md` | Current observed agent availability and review preference |
| `docs/implementation/04-taut-architecture.md` | Taut v0.1 implementation rationale, boundaries, and key files |
| `docs/lessons.md` | Canonical lessons ledger |

## Product Code

| Path | Purpose |
|------|---------|
| `taut/_constants.py` | Taut constants, config translation, identity lists, handle pools |
| `taut/envelope.py` | Envelope v1 encode/decode and foreign-message fallback |
| `taut/schema.py` | Taut sidecar schema and all taut-owned SQL |
| `taut/identity.py` | Process fingerprint capture, anchor selection, presence checks |
| `taut/client.py` | Public Python API and command semantics |
| `taut/watcher.py` | Vendored multi-queue watcher plus cursor-aware `TautWatcher` |
| `taut/cli.py` | Argparse CLI and output/exit-code rendering |
| `tests/` | Contract tests using real `.taut.db` files and subprocess CLI |

## Skills

| Path | Purpose |
|------|---------|
| `skills/README.md` | Skill directory purpose and conventions |
| `skills/_template/SKILL.md` | Starter template for new reusable skills |

## Update Guidance

When the repository grows:

- add new important entry points here
- keep descriptions short and navigational
- prefer linking to the document that explains a concept, not every file that
  happens to mention it
