# Repository Map

Quick pointers to the key guidance documents in this repository.

## Root Entry Points

| Path | Purpose |
|------|---------|
| `AGENTS.md` | Canonical agent entry point |
| `CLAUDE.md` | Alias for tools that expect Claude-style root guidance |
| `README.md` | Product face and, per section, contract of record; ceded sections resolve through `docs/specs/product-section-registry.md` |
| `llms.txt` | llmstxt.org link index for language models (absolute URLs) |
| `docs/agent-kernel.md` | Agent product-use kernel: the sole home of agent-executable recipes; a view, never a contract |
| `bin/release.py` | Five-package release helper for manifest-owned metadata/lock reconciliation, one universal default precheck sequence with an explicit human override, exact-path local preparation commits, non-mutating checks, producer-first exact-SHA observation, repeated fail-closed settings/publication/tag fences, namespaced tags, and coordinated `all --version` batches |
| `bin/check-plan-status-index` | Structured plan status index gate: completeness, closed status/exemplar vocabulary, and table well-formedness |
| `bin/check-doc-paths` | Pytest-free path-claim gate over the maintained guidance surfaces plus `docs/coalescing.md` and `docs/plans/README.md`; reuses the claim grammar in `tests/test_docs_references.py` |
| `bin/check-cli-claims` | Pytest-free command-path gate over maintained Markdown; reuses the registry-derived grammar, exact source set, and exemptions in `tests/test_cli_claims.py` |
| `bin/coalesce-check` | Coalescing evidence trail: resolves every SHA claim and retrieval cue in `docs/coalescing.md` locally, in named siblings, and against `origin/main` (reporting local-only pins), and derives the lessons-tier counts |
| `bin/pytest-pg` | Docker-backed Postgres test runner for shared root tests and `taut-pg` tests |
| `bin/combine-coverage.py` | Pre-combine raw-shard integrity owner: validates every downloaded file through Coverage's public data API, rejects absent, zero-byte, unreadable, or warning-producing evidence, and preserves all inputs while combining |
| `bin/check-required-coverage-paths.py` | Post-combine coverage-data checker for required child-process, critical Summon, and MCP rate-admission execution paths |
| `bin/render-tui-screens` | Deterministic wide, medium, compact, and too-small TUI SVG regeneration for manual visual review |
| `bin/check-core-summon-wheel-matrix.py` | Isolated installed-artifact checker for the `taut-chat` core/current-Summon pair, exact distribution metadata, live control behavior, incompatible current-core floors, and the historical `Requires-Dist: taut` rename boundary |
| `bin/build-and-check-release-wheels.py` | Fresh-build owner, or paired explicit-current-wheel consumer in canonical CI, that builds the historical diagnostic artifact before invoking the installed-artifact matrix checker |
| `bin/release-artifact.py` | Creates and verifies commit-bound release bundles containing one wheel, one sdist, and an inner SHA-256 manifest |
| `bin/ruff_suppression_index.py` | Validates source-local approved Ruff directives against the human DOM-10.2.1 registry, raw `--ignore-noqa` diagnostics, the global active-rule inventory, and a generated symbol-keyed location index; check mode is read-only and write mode atomically replaces only the generated block |
| `bin/require-green-workflows.py` | Observes canonical exact-SHA workflow evidence; its workflow-only mode lets the local release producer wait without artifact or output-file access, while tag gates select attempt-bound release artifacts by immutable id and archive digest |
| `.github/scripts/release_publication.py` | Fail-closed draft, PyPI filename/digest, remote-tag, and immutable GitHub finalization state machine used by release workflows |
| `.github/workflows/test.yml` | Push/PR/reusable pytest, lint, type, deterministic serial direct root/Summon unit coverage plus checked same-run process/MCP aggregation, deterministic exact-union Windows source-factor shards, and sole canonical release-byte production for all five packages |
| `.github/workflows/test-pg-extension.yml` | Push/PR/reusable Docker Postgres gate for `taut-pg` |
| `.github/workflows/test-mcp-extension.yml` | Push/PR/reusable Ubuntu SQLite/live-PostgreSQL MCP behavior, representative macOS/Windows non-PG compatibility, package-local quality, and disposable build gate; never a release-byte owner |
| `.github/workflows/release-gate.yml` | `v*` observer for `taut-chat`: exact-SHA Test/PG/MCP evidence, draft staging, top-level PyPI Trusted Publishing, digest verification, and immutable GitHub finalization |
| `.github/workflows/release-gate-pg.yml` | `taut_pg/v*` observer for `taut-pg`: exact-SHA Test/PG/MCP evidence, draft staging, top-level PyPI Trusted Publishing, digest verification, and immutable GitHub finalization |
| `.github/workflows/release-gate-summon.yml` | `taut_summon/v*` observer for `taut-summon`: exact-SHA Test/PG/MCP evidence, draft staging, top-level PyPI Trusted Publishing, digest verification, and immutable GitHub finalization |
| `.github/workflows/release-gate-mcp.yml` | `taut_mcp/v*` observer for `taut-mcp`: exact-SHA Test/PG/MCP evidence, draft staging, top-level PyPI Trusted Publishing, digest verification, and immutable GitHub finalization |
| `.github/workflows/release-gate-tui.yml` | `taut_tui/v*` observer for `taut-tui`: exact-SHA Test/PG/MCP evidence, draft staging, top-level PyPI Trusted Publishing, digest verification, and immutable GitHub finalization |
| `.github/workflows/release.yml` | Reusable no-rebuild exact-artifact draft staging and verified-bundle carry; the five top-level gates, not this reusable workflow, own PyPI OIDC publication |
| `.github/workflows/release-finalize.yml` | Reusable least-privilege exact-artifact PyPI recheck and immutable GitHub Release finalizer |

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
| `docs/specs/product-section-registry.md` | Authority table naming the winning contract (README section or spec) per behavior family, with promise-granular conflict and promotion rules |
| `docs/specs/02-taut-core.md` | Taut core spec: storage, threads, envelope, read model, surfaces, trust model |
| `docs/specs/03-identity-addressing-notifications.md` | Identity, addressing, and notifications spec: member ids, names, DMs, queue namespace, rename |
| `docs/specs/04-summon.md` | Summon extension spec: agent harness as member, injection ears, CLI mouth, adapters, session ledger, control plane |
| `docs/specs/05-taut-mcp.md` | MCP extension spec: dual-era stdio lifecycle, process-local shared ensure, explicit identity-bearing tools, notification resource, legacy/modern subscriptions, and host hints |
| `docs/specs/06-search.md` | Search spec: cursor-neutral visible history, derived providers, durable work, recovery, and backend parity |
| `docs/specs/07-agent-theory-and-program-theory.md` | Definitional reference for Agent Theory and program theory |
| `docs/specs/08-persistence-io.md` | Actor-free live logical dump/load, contributor, H-boundary, and guarded recovery contract |
| `docs/specs/09-system-doctor.md` | Fixed passive workspace-diagnostic report, findings/framework split, and no-repair boundary |
| `docs/specs/10-taut-tui.md` | Human-first core/extension reflection, native actions, live-read ownership, responsive layout, system operations, and rich-host Summon contract |
| `docs/plans/README.md` | Plan directory rules |
| retired: 2026-06-12-taut-foundation-plan (source `f1259c0`; see the ledger in docs/plans/README.md) | Historical foundation implementation plan |
| `docs/plans/2026-06-18-member-identity-addressing-plan.md` | Implemented plan for member ids, addressing, notifications, and channel rename |
| retired: 2026-06-12-taut-0.1.1-hardening-plan (source `f1259c0`; see the ledger in docs/plans/README.md) | Hardening plan for handle quality, [TAUT-11] proof burndown, README rendering, and 0.1.1 release |
| retired: 2026-06-17-github-release-helper-plan (source `dadd324`; see the ledger in docs/plans/README.md) | Initial GitHub-only release-helper plan; current publication ownership is in [TAUT-12.5] |
| retired: 2026-06-17-github-actions-release-workflows-plan (source `33e13ee`; see the ledger in docs/plans/README.md) | Initial GitHub Actions test and release-workflow plan; current publication ownership is in [TAUT-12.5] |
| `docs/plans/2026-06-17-taut-pg-extension-plan.md` | Postgres extension plan covering `extensions/`, PG test harness, and GitHub-only release gates |
| `docs/plans/2026-07-08-release-helper-simplebroker-port-plan.md` | SimpleBroker-style release helper target, batch, and summon release gate port plan |
| `docs/plans/2026-06-17-implementation-review-followups-plan.md` | Post-review hardening for missing-plugin errors, bounded `log --limit`, and shared backend conformance |
| `docs/plans/2026-06-18-simplebroker-latest-timestamp-plan.md` | Implemented plan for indexed `list` metadata via SimpleBroker's latest pending timestamp API |
| `docs/plans/2026-06-30-assets-reference-cleanup-plan.md` | Implemented cleanup of stale `assets/` and `generate_knot.py` lint references |
| `docs/plans/2026-06-30-client-module-split-plan.md` | Implemented split of `taut.client` into a package facade and concern-specific mixins |
| `docs/plans/2026-07-01-schema-shim-retirement-plan.md` | Implemented retirement of the historical schema compatibility shim in favor of `taut/state/` |
| `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md` | Implemented `TautState` interface and SQL dialect seam refactor |
| `docs/plans/2026-07-01-taut-watch-runtime-plan.md` | Implemented `TautWatchRuntime` seam between `TautClient` and the watcher |
| `docs/plans/2026-07-06-taut-summon-plan.md` | Implemented `taut-summon` extension: delegation verbs, ledger, adapters, driver, control plane, conformance suite |
| `docs/plans/2026-07-10-taut-summon-quality-remediation-plan.md` | Implemented and independently verified remediation for state, lifecycle, control, PTY, driver-generation, and paired-release findings |
| `docs/plans/2026-07-11-multi-factor-review-remediation-plan.md` | Implemented and independently reviewed external multi-factor remediation |
| `docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md` | Reviewed implementation plan for command extensions, lazy subsystem loading, public Summon composition, and rich-host boundaries |
| `docs/plans/2026-07-13-ci-speed-determinism-release-evidence-plan.md` | Reviewed implementation plan for existing-lane coverage, deterministic worker/process ownership, strict local-LLM evidence, canonical package artifacts, and exact-SHA release gates |
| `docs/plans/2026-07-14-universal-release-gates-plan.md` | Reviewed implementation and release plan for one default all-extension local gate, explicit human override, and both exact-SHA workflow requirements for every tag |
| `docs/plans/2026-07-15-taut-mcp-release-integration-plan.md` | Reviewed implementation plan for the fourth release target, root-owned MCP bundle, three-workflow exact-SHA gates, and same-run MCP coverage shard |
| `docs/plans/2026-07-15-taut-0.7.1-portability-and-coverage-plan.md` | Reviewed patch-release plan for macOS/Windows MCP proof, complete direct coverage ownership, publication-record correction, and coordinated 0.7.1 release |
| `docs/plans/2026-07-27-message-show-delete-plan.md` | Reviewed implementation plan for exact message show/delete across the Python, CLI, and MCP surfaces |
| `docs/plans/2026-07-28-message-react-plan.md` | Reviewed implementation plan for configured best-effort message reactions across Python, CLI, notification, and MCP surfaces |
| `docs/plans/2026-07-28-direct-message-navigation-plan.md` | Completed implementation plan for actor-scoped DM route/stable-handle navigation, directory, rendering, watcher, and MCP behavior |
| `docs/plans/2026-07-28-taut-mcp-dual-era-sessionless-plan.md` | Reviewed implementation plan for one SDK v2 server serving both MCP wire eras through explicit workspace-and-token continuity, shared ensure, and independent notification adapters |
| `docs/plans/2026-07-28-summon-terminal-retirement-plan.md` | Reviewed implementation plan separating reusable adapter interruption from one-signal terminal retirement and making invalid raw coverage evidence fatal |
| `docs/plans/2026-07-29-taut-chat-pypi-publication-plan.md` | Reviewed implementation plan for the `taut-chat` core distribution rename, exact-artifact Trusted Publishing, draft-first immutable GitHub finalization, and explicit migration boundary |
| retired: 2026-07-14-terminal-output-safety-plan (source `281f04fa`; see the ledger in docs/plans/README.md) | Retired reviewed implementation plan for packaged and project-customizable terminal-text policy, public extension API, human renderer coverage, and raw PTY exemption |
| `docs/plans/2026-07-14-blank-message-no-op-plan.md` | Reviewed implementation plan for the built-in Unicode blank-input guard, typed empty result, silent CLI exit 2, and Summon terminal-mode adaptation |
| `docs/implementation/00-implementation-index.md` | Numbered entry point for implementation docs |
| `docs/implementation/01-documentation-system.md` | Why the documentation system is shaped this way |
| `docs/implementation/03-agent-inventory.md` | Current observed agent availability and review preference |
| `docs/implementation/04-taut-architecture.md` | Taut implementation rationale, boundaries, dependencies, and key files |
| `docs/implementation/05-taut-summon-architecture.md` | Summon extension rationale: ears/mouth split, three-thread driver, session ledger, control plane, and SimpleBroker handle ownership |
| `docs/implementation/06-command-extensions.md` | Static and installed command registration, registry/dispatch ownership, lazy imports, extension packaging, and rich composition guidance |
| `docs/implementation/07-taut-mcp-architecture.md` | MCP reactor-over-reactors rationale: workspace ownership, explicit tool dispatch, cached notification resource, edge hints, and cancellation boundaries |
| `docs/implementation/09-search-architecture.md` | Search rationale: source-hydrated derived state, backend provider boundary, durable work recovery, reconciliation, and generation rebuilds |
| `docs/implementation/10-persistence-io.md` | Composite logical dump/load rationale: SimpleBroker H-boundary, sidecar authority, extension contributors, and guarded load recovery |
| `docs/implementation/11-system-doctor.md` | Fixed passive diagnostic rationale: typed findings, shared validation, queue statistics, contributor compatibility, and resource ownership |
| `docs/implementation/12-taut-tui.md` | TUI rationale: worker ownership, typed actions/forms, active-only live reads, reflow state, system boundary, and Summon terminal handoff |
| `docs/lessons.md` | Canonical lessons ledger |

## Product Code

| Path | Purpose |
|------|---------|
| `taut/_constants.py` | Taut constants, config translation, name validation, and identity name pools |
| `taut/_message_text.py` | Small built-in Unicode classifier for user-authored `say` and `reply` text |
| `taut/_maintenance.py`, `taut/_doctor.py` | Shared existing-target resolution and the actor-free six-check passive diagnostic orchestrator |
| `taut/terminal.py`, `taut/defaults.toml` | Lightweight public terminal-text display transform, CWD `.taut.toml` presentation discovery, and packaged baseline regex policy |
| `taut/_broker_retry.py` | Import-only, fail-closed compatibility shim for the immutable prior Summon artifact; no retry policy |
| `taut/addressing.py` | Channel, sub-thread, DM, mention, and notification addressing helpers |
| `taut/_scripts.py` | Importable developer-script helper logic, currently for `bin/pytest-pg` |
| `taut/envelope.py` | Message envelope encode/decode and foreign-message fallback |
| `taut/state/` | Internal Taut state interface, SQL dialect marker, sidecar SQL adapter, and passive core schema/record inspection |
| `taut/identity.py` | Process fingerprint capture, anchor selection, presence checks |
| `taut/client/` | Public Python API package: facade plus identity, actor-scoped DM selection/directory, messaging (including exact show/delete/react), notification, thread mixins, and plain SimpleBroker queue ownership |
| `taut/search/` | Core search projection, SQLite FTS5 provider, strict PostgreSQL provider discovery, durable invalidation jobs, and worker state machine |
| `taut/persistence/` | Composite dump validation, official component discovery, shared live/dump record validation, actor-free file lifecycle, and guarded workspace restore |
| `taut/watcher.py` | Shared `BaseReactor`, vendored multi-queue scheduling, and cursor-aware `TautWatcher` with persistent owned queue handles |
| `taut/cli.py` | Thin console entry point into the registry-backed dispatcher |
| `taut/commands/` | Versioned command manifests/protocol, deterministic installed-command registry, root dispatcher, shared renderers, lazy per-verb adapters, and the temporary reserved Summon compatibility bridge |
| `tests/` | Contract tests using real SQLite files, shared backend markers, and subprocess CLI |
| `tests/helpers/eventually.py` | Repository-only [DOM-10.3] sync/async eventual-evidence helper; owns aggregate deadlines, final recheck, failure priority, and timeout diagnostics without driving product state |
| `tests/test_eventually.py` | Controlled-time firing tests for every [DOM-10.3] interface and deadline edge, including snapshot failure and asyncio cancellation |
| `tests/test_docs_references.py` | Maintained-source path and local/external citation-family gate |
| `tests/test_cli_claims.py` | Maintained-source inline/fenced Taut command-path grammar, deterministic registry validation, and exact exemption gate |
| `tests/test_project_metadata_consistency.py` | Relational gate comparing constants, first-party floors, README pins, wheel names, and retained-lock versions to their owning package manifests |
| `extensions/taut_pg/` | Separate `taut-pg` project with backend registration, built-in PostgreSQL full-text search provider, extension metadata, README, and PG-only tests |
| `extensions/taut_summon/` | Separate `taut-summon` project: lazy public facade, typed rich-host controller with non-owning signal default and object-local identity, explicit CLI signal opt-in, one-signal terminal-retirement adapters with sanitized child identity, ledger, control plane, persona, and real-process conformance suite |
| `extensions/taut_mcp/` | Separate `taut-mcp` project: installed `taut mcp` manifest/adapter plus standalone convenience script over one process runner, dual-era stdio server, master process reactor, one owner-thread reactor per resident workspace, explicit workspace-plus-token schemas for identity-using tools, notification resource, legacy/modern subscription adapters, and optional legacy Claude channel hint |
| `extensions/taut_tui/` | Separate `taut-tui` project: installed `taut tui` manifest/adapter, Textual human surface, semantic actions, native forms/screens, serialized public-client session, pure reflow state, actor-free system work, and public Summon rich-host adapter |

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
