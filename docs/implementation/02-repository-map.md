# Repository Map

Quick pointers to the key guidance documents in this repository.

## Root Entry Points

| Path | Purpose |
|------|---------|
| `AGENTS.md` | Canonical agent entry point |
| `CLAUDE.md` | Alias for tools that expect Claude-style root guidance |
| `README.md` | Product face and current CLI/API behavior contract (see `docs/specs/02-taut-core.md`) |
| `bin/release.py` | GitHub-only release helper for version sync, release gates, and `vX.Y.Z` tags |
| `bin/pytest-pg` | Docker-backed Postgres test runner for shared root tests and `taut-pg` tests |
| `.github/workflows/test.yml` | Push/PR/reusable pytest, lint, type, and build gates |
| `.github/workflows/test-pg-extension.yml` | Push/PR/reusable Docker Postgres gate for `taut-pg` |
| `.github/workflows/release-gate.yml` | `v*` tag gate that runs tests, verifies tag stability, and publishes release artifacts |
| `.github/workflows/release-gate-pg.yml` | `taut_pg/v*` tag gate for GitHub-only `taut-pg` release artifacts |
| `.github/workflows/release.yml` | Reusable GitHub Release artifact builder/uploader; no PyPI path |

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
| `docs/specs/02-taut-core.md` | Taut core spec: storage, threads, envelope, read model, surfaces, trust model |
| `docs/specs/03-identity-addressing-notifications.md` | Identity, addressing, and notifications spec: member ids, names, DMs, queue namespace, rename |
| `docs/specs/04-summon.md` | Summon extension spec: agent harness as member, injection ears, CLI mouth, adapters, session ledger, control plane |
| `docs/plans/README.md` | Plan directory rules |
| `docs/plans/2026-06-12-taut-foundation-plan.md` | Historical foundation implementation plan |
| `docs/plans/2026-06-18-member-identity-addressing-plan.md` | Implemented plan for member ids, addressing, notifications, and channel rename |
| `docs/plans/2026-06-12-taut-0.1.1-hardening-plan.md` | Hardening plan for handle quality, [TAUT-11] proof burndown, README rendering, and 0.1.1 release |
| `docs/plans/2026-06-17-github-release-helper-plan.md` | GitHub-only release-helper plan while PyPI name clearance is pending |
| `docs/plans/2026-06-17-github-actions-release-workflows-plan.md` | GitHub Actions test and GitHub-only release workflow plan |
| `docs/plans/2026-06-17-taut-pg-extension-plan.md` | Postgres extension plan covering `extensions/`, PG test harness, and GitHub-only release gates |
| `docs/plans/2026-06-17-implementation-review-followups-plan.md` | Post-review hardening for missing-plugin errors, bounded `log --limit`, and shared backend conformance |
| `docs/plans/2026-06-18-simplebroker-latest-timestamp-plan.md` | Implemented plan for indexed `list` metadata via SimpleBroker's latest pending timestamp API |
| `docs/plans/2026-06-30-assets-reference-cleanup-plan.md` | Implemented cleanup of stale `assets/` and `generate_knot.py` lint references |
| `docs/plans/2026-06-30-client-module-split-plan.md` | Implemented split of `taut.client` into a package facade and concern-specific mixins |
| `docs/plans/2026-07-01-schema-shim-retirement-plan.md` | Implemented retirement of the historical schema compatibility shim in favor of `taut/state/` |
| `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md` | Implemented `TautState` interface and SQL dialect seam refactor |
| `docs/plans/2026-07-01-taut-watch-runtime-plan.md` | Implemented `TautWatchRuntime` seam between `TautClient` and the watcher |
| `docs/plans/2026-07-06-taut-summon-plan.md` | Implemented `taut-summon` extension: delegation verbs, ledger, adapters, driver, control plane, conformance suite |
| `docs/implementation/00-implementation-index.md` | Numbered entry point for implementation docs |
| `docs/implementation/01-documentation-system.md` | Why the documentation system is shaped this way |
| `docs/implementation/03-agent-inventory.md` | Current observed agent availability and review preference |
| `docs/implementation/04-taut-architecture.md` | Taut implementation rationale, boundaries, dependencies, and key files |
| `docs/implementation/05-taut-summon-architecture.md` | Summon extension rationale: ears/mouth split, three-thread driver, session ledger, control plane, vendored retry |
| `docs/lessons.md` | Canonical lessons ledger |

## Product Code

| Path | Purpose |
|------|---------|
| `taut/_constants.py` | Taut constants, config translation, name validation, and identity name pools |
| `taut/addressing.py` | Channel, sub-thread, DM, mention, and notification addressing helpers |
| `taut/_scripts.py` | Importable developer-script helper logic, currently for `bin/pytest-pg` |
| `taut/envelope.py` | Message envelope encode/decode and foreign-message fallback |
| `taut/state/` | Internal Taut state interface, SQL dialect marker, and sidecar SQL adapter |
| `taut/identity.py` | Process fingerprint capture, anchor selection, presence checks |
| `taut/client/` | Public Python API package: facade plus identity, messaging, notification, and thread mixins |
| `taut/watcher.py` | Vendored multi-queue watcher plus cursor-aware `TautWatcher` |
| `taut/cli.py` | Argparse CLI and output/exit-code rendering |
| `tests/` | Contract tests using real SQLite files, shared backend markers, and subprocess CLI |
| `extensions/taut_pg/` | Separate `taut-pg` project with extension metadata, README, and PG-only tests |
| `extensions/taut_summon/` | Separate `taut-summon` project: the summon driver, adapters, ledger, control plane, persona, and real-process conformance suite |

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
