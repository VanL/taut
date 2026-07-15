# Changelog

## Unreleased

- Added per-call `limit` paging to `TautClient.read()` and `read_unread()` with
  exact cursor advancement and a 1,000-message per-thread default.

## 0.6.7 - 2026-07-14

- Made the PostgreSQL cross-table route-race proof scheduler-independent. The
  test now holds the first real advisory lock until both contenders reach the
  same lock-key boundary, proves that lock unavailable from an independent
  connection, then releases them together and still requires exactly one
  commit and one `IntegrityError`.

## 0.6.6 - 2026-07-14

- Filtered empty, built-in Unicode whitespace, and Unicode `Cf`-only `say` and
  `reply` input before routing or state work. The Python API raises public
  `BlankMessageError`; the CLI exits 2 without output; accepted text remains
  exact and existing stored blank or foreign messages remain readable.
- Made Summon terminal mode silently continue after that typed blank result
  while retaining error logs for every other core posting failure.
- Made existing explicit name/alias and continuity-token selectors bypass full
  process capture for ordinary operations without changing durable process
  claim ownership. Selector-free inference remains automatic, token activity
  still refreshes, and `rejoin` remains the explicit association operation.
- Raised the SimpleBroker floors to 5.3.3 for core and 3.2.2 for Taut-PG,
  picking up safe runner cleanup and initialized timestamp-conflict metrics.
- Raised the paired core, Taut-PG, and Summon metadata to 0.6.6 so first-party
  extensions cannot resolve against a core missing the new public exception.

## 0.6.5 - 2026-07-14

- Made Windows `taut init` reject control-bearing SQLite targets before broker
  queue and lock setup, with a fixed path-free diagnostic instead of a delayed
  filesystem failure.
- Made terminal-safety release coverage portable across Windows and POSIX by
  proving unsafe database-target rendering without requiring the filesystem to
  accept control bytes in a filename. Real CLI and storage coverage continues
  to use an explicit valid target, without relying on longer timeouts.

## 0.6.4 - 2026-07-14

- Added the public `taut.escape_terminal_text` display transform and packaged
  `taut/defaults.toml` policy. The default policy renders C0, DEL, and C1
  controls visibly while humans through `.taut.toml` and trusted callers
  through the public function can extend, replace, or disable it.
- Routed core and first-party Summon human text through the shared policy,
  including command diagnostics and non-interactive logs. Storage, Python
  models, NDJSON, and explicit raw PTY transport remain byte-for-byte exact.
- Reduced thread-list work by reusing the latest pending timestamp and skipping
  message scans when it proves that a membership has no unread messages.
- Expanded deterministic coverage for PostgreSQL watcher fallback, client
  membership and cursor state transitions, terminal-control rendering, and
  installed core/Summon wheel compatibility.
- Documented terminal escaping as a safe-default relay control within Taut's
  stated trust domain, not as an authentication or sandbox boundary, and raised
  the paired Summon core floor to 0.6.4.

## 0.6.3 - 2026-07-14

- Made every release target run one universal root, PostgreSQL, and Summon
  precheck sequence by default while retaining `--skip-checks` as an explicit
  human override.
- Forced release live-harness execution and strict prewired mode together, and
  made local Ollama preparation lifecycle-safe for every target.
- Required every package tag to observe both canonical exact-commit workflows
  without dispatching duplicate test matrices or rebuilding release artifacts.

## 0.6.2 - 2026-07-14

- Made signal and PTY integration failures deterministic and diagnostic without
  weakening the strict local-LLM smoke or production recovery behavior.
- Removed duplicate coverage, live-test, installed-wheel, packaging, and
  release-gate execution while preserving every supported Python and operating
  system boundary.
- Bound GitHub releases to canonical exact-commit workflow evidence, immutable
  attempt-qualified artifacts, verified package bytes, and the correct package
  tag family and version.

## 0.6.1 - 2026-07-13

- Fixed the Summon STOP/release race where an expected STOP-interrupted PTY
  orientation write was misclassified as a teardown failure. STOP now records
  teardown and ledger-release outcomes separately, preserving clean
  same-process stop and restart without lengthening the timeout.
- Made release metadata preparation deterministic and package-owned, including
  version and dependency-floor copies, README examples, the retained Summon
  lock, a checked local preparation commit, and fresh state checks before
  remote release actions.
- Raised the core SimpleBroker floor to 5.3.2; set both extension `taut` floors
  and the root Summon development floor to 0.6.1; reconciled the retained
  Summon lock.

## 0.6.0 - 2026-07-13

- Replaced the monolithic CLI switchboard with one versioned command-adapter
  interface for every top-level verb. Core commands register statically;
  separately installed packages register lightweight manifests through the
  `taut.commands` entry-point group.
- Added deterministic installed-command ownership, conflict diagnostics,
  command-local parser configuration, shared root-global policy, and lazy
  command factory loading. Root version/help and command help no longer
  initialize unrelated clients, storage, watchers, providers, PTYs, or driver
  subsystems.
- Made the public `taut` and `taut_summon` package facades lazy while retaining
  their typed import surfaces. Runtime failures now occur at the selected
  subsystem boundary with the original cause preserved.
- Added the typed `SummonController`, frozen request/result/status models, and
  host-interaction terminal lease interface. Rich hosts can compose Summon
  directly without parsing console output or importing private ledger,
  control, driver, or PTY modules.
- Moved `taut summon` and `taut dismiss` to native `taut-summon` entry-point
  adapters shared with the standalone console. Core retains a narrow 0.5.4
  compatibility/install-hint bridge for paired rollout; the 0.6.0 Summon wheel
  wins when installed.
- Expanded the fresh-wheel release gate to verify exact command entry points,
  native Summon lifecycle, the retained 0.5.0 reactor case, 0.5.4 legacy
  command compatibility, and rejection of Summon 0.6.0 with core 0.5.4.
- Made every release pytest precheck select the repository `dev` extra, so an
  activated environment with stale Summon metadata cannot replace the current
  0.6.0 command entry points during release validation.
- Coordinated `taut`, `taut-pg`, and `taut-summon` versions and first-party
  dependency floors at 0.6.0.

## 0.5.4 - 2026-07-12

- Updated names to have a default capitalization rule (humans and agents)
  while preserving --as or explicit names.

## 0.5.3 - 2026-07-11

- Adopted SimpleBroker 5.3.1's atomic `Queue.write()` return value for live
  message ids and closed sender cursor races with a bounded post-write probe.
- Serialized Postgres schema initialization and the cross-table name/alias
  namespace with transaction-scoped advisory locks; corrupt Taut-owned JSON
  now fails with table/field context instead of silently becoming empty state.
- Hardened watcher sink shutdown, Summon control/audit/PTY behavior, reply
  notifications, CLI help, release metadata, and maintained documentation
  checks from the 2026-07-11 multi-factor review.

## 0.5.2 - 2026-07-11

- Coordinated the GitHub-only publication of `taut`, `taut-pg`, and
  `taut-summon` from one tested commit after the extension 0.5.1 tags failed
  before creating GitHub Releases. Core 0.5.2 is runtime-code-equivalent to
  the successfully published core 0.5.1 package; the patch bump gives all
  three packages a fresh, immutable release namespace without rewriting old
  tags.
- Carries the 0.5.1 lifecycle and release-gate corrections across the paired
  core/Summon boundary: generation-safe shutdown, complete Windows process
  fakes, test-owned control cleanup, and the fresh installed-artifact canary.

## 0.5.1 - 2026-07-10

- Rebuilt the core watcher and Summon control owners around generation-fenced
  reactor lifecycles, owner-thread handle replacement, bounded shutdown, and
  fatal owned-thread supervision.
- Added deterministic SQLite/PTY process lanes, dynamic Postgres waiter
  replacement coverage, and a fresh installed-wheel compatibility matrix for
  the paired core/Summon release boundary.
- Removed Taut-owned broker retry policy in favor of the supported
  SimpleBroker ownership/retry contract and raised the paired dependency
  floors accordingly.

## 0.5.0 - 2026-07-08

- Added `taut summon` / `taut dismiss` as thin core delegation verbs that
  hand off to the new **`taut-summon`** extension when installed, or exit 1
  with a one-line install hint otherwise. The verbs carry no summon logic
  and add no core dependency.
- Added the `taut-summon` extension (separate package under
  `extensions/taut_summon/`) that hosts an existing agent harness as an
  ordinary workspace member — no daemon, no bespoke agent protocol. The
  summon driver injects chat into the harness's live session (its ears) and
  the agent speaks through the ordinary `taut` CLI selected by its
  continuity token (its mouth). Ships the `run`/`stop`/`status` verbs, the
  universal PTY adapter for interactive harnesses (`claude`, `codex`,
  `coder`, `grok`, `qwen`, `kimi`, `opencode`, `pi`), the `claude-stream`
  structured adapter, the `scripted` and fake-TUI test seams, a two-table
  session ledger with a single-driver guard and PTY `wired` flag, a
  weft-congruent `sys.*` control plane (STOP/STATUS/PING), a default persona
  template with a rate backstop, a portable, parameterized cross-provider
  conformance suite, local real-harness smoke tests, and a CI-safe
  local-LLM PTY smoke backed by Ollama. See `docs/specs/04-summon.md` and
  `docs/implementation/05-taut-summon-architecture.md`.
- Raised the SimpleBroker floor to 5.1.0. Taut's vendored Weft-style
  `MultiQueueWatcher` now supplies its fan-in activity waiter through
  SimpleBroker's watcher lifecycle hooks instead of cloning the watcher retry
  loop.
- Changed CLI usage errors (unknown flags, unknown subcommands, malformed
  arguments) to exit 1. Compatibility note: these previously exited with
  argparse's 2, colliding with the exit-2 "empty / nothing matched" class
  that shell polling loops key on.
- Added `--` end-of-options handling so option-like message text is
  sendable (`taut say general -- -q` posts the literal text `-q`).
- Made interrupted channel renames resumable: rerunning the same
  `taut rename OLD NEW` finishes the rename from its recovery marker, and
  other commands name that exact command while a rename is incomplete.
- Added anchor-match identity resolution ([IAN-3.3] step 4): an agent whose
  anchor process changed working directory or other mutable claim inputs
  still resolves to its existing member, and the resolver records the
  current claim so later commands resolve by claim hash again.
- Made concurrent first-contact joins retry auto-chosen names (bounded at
  five attempts), re-minting name, member id, and token on each attempt.
  Explicit `--as` names still fail loudly on collision.
- Scoped direct-message mentions to the DM participants; mentioning any
  other member in a DM no longer notifies them.
- Hardened error paths: `init` into an unwritable directory fails fast with
  a one-line diagnostic instead of stalling in lock retries; malformed
  `.taut.toml` diagnostics name the offending file; non-UTF-8 bytes piped
  to `say -` are reported as invalid stdin rather than a raw decode error.
- Fixed the vendored multi-queue watcher to close removed queues'
  connections instead of leaking them.
- Added a documentation reference gate (`tests/test_docs_references.py`)
  that fails the suite when docs cite nonexistent paths or unknown spec
  codes.
- Extended the GitHub-only release helper with SimpleBroker-style positional
  targets, a `summon` release target, `all` batch release planning, release-file
  tracking for the summon lockfile, local summon LLM gate preparation, and a
  `taut_summon/vX.Y.Z` release gate.

## 0.4.7 - 2026-07-06

- Closed the evaluation-review findings: consistent CLI usage exits and `--`
  handling, resumable channel renames, anchor-based identity recovery,
  bounded first-contact collision retries, DM mention scoping, and clean
  diagnostics for malformed config/stdin/database setup.
- Added adversarial CLI probes and the first documentation path/spec-code
  reference gate.

## 0.4.6 - 2026-07-06

- Moved multi-queue activity waiting onto SimpleBroker's public watcher hooks
  and added real watcher lifecycle and wake coverage.

## 0.4.5 - 2026-07-06

- Refreshed the development dependency set used by the release gates.

## 0.4.4 - 2026-07-03

- Updated the SimpleBroker dependency and strengthened spec-promotion,
  traceability, and independent-review guidance used by implementation plans.

## 0.4.3 - 2026-07-02

- Added adversarial acceptance/testing guidance, raised the SimpleBroker
  dependency, and required patch coverage above 50 percent.

## 0.4.2 - 2026-07-01

- Relaxed the Codecov project threshold while retaining patch-level coverage
  enforcement.

## 0.4.1 - 2026-07-01

- Added focused messaging/identity/dev-script coverage and made identity tests
  portable across checkout paths.

## 0.4.0 - 2026-07-01

- Added stable member identity, aliases, direct-message routing by current
  name, consumable mention/DM notifications, `inbox`, `set name`, `rejoin`,
  and channel rename support.
- Reworked `taut.client` into a package facade over concern-specific modules
  while keeping `from taut.client import TautClient, Message, ...` as the
  public import surface.
- Replaced the old `schema.py` helper layer with `taut.state` and a SQL dialect
  hook so sidecar ownership is explicit and tested across SQLite and Postgres.
- Changed `TautWatcher` to depend on a `TautWatchRuntime` protocol. The normal
  public API remains `TautClient.watch()`, and direct `TautWatcher(client, ...)`
  construction is deprecated.
- Updated Taut and `taut-pg` tests for the state adapter, public watcher
  surface, and Postgres-visible behavior. Both the core package and `taut-pg`
  are versioned `0.4.0` for this release.
- Cleaned project hygiene: `.envrc` is local-only, stale generated logo assets
  are out of workflow gates, and private test coupling was reduced where the
  public API gives the same proof.

## 0.3.0 - 2026-07-01

- Introduced the stable member-id, addressing, notification, SQL state-adapter,
  and watcher-runtime refactors later released together as the 0.4 public
  contract.
- Split the client facade into concern-specific modules, retired the schema
  compatibility shim, and refreshed Postgres state-adapter coverage and the
  repository documentation map.

## 0.2.1 - 2026-06-18

- Fixed Postgres project-config and shared backend conformance coverage.
- Documented `read` pagination and tightened bounded `log --limit` behavior.

## 0.2.0 - 2026-06-17

- Added the separate `taut-pg` extension package for Postgres-backed Taut
  projects through `.taut.toml`.
- Added `bin/pytest-pg` and typed shared/PG-only tests against real Docker
  Postgres.
- Relaxed core target resolution for SimpleBroker project-config targets while
  keeping `TAUT_DB`, `--db`, and `db_path=` as filesystem path selectors.
- Added GitHub-only release gates for `taut-pg` using the `taut_pg/vX.Y.Z` tag
  namespace.
- Updated sidecar DDL to use `BIGINT` for 64-bit timestamp/id portability.

## 0.1.1 - 2026-06-12

- Added `psutil` as a bounded runtime dependency for cross-platform process
  metadata capture, while preserving native start-time tokens where available.
- Fixed identity handle quality for fallback `ps args=` output with spaces in
  `argv[0]`.
- Updated human `read`, `log`, `watch`, and `list` rendering to match the
  README transcript shape, including grouped thread headings, local HH:MM
  display, `-t` id columns, and bounded unread counts.
- Completed the remaining [TAUT-11] proof obligations for concurrent writer
  processes, mid-watch joins, idle peek queues, and continuity-token acts-as.
- Added strict mypy coverage for the test suite (`mypy taut tests`).
- Added a GitHub-only `bin/release.py` helper for version sync, local release
  gates, and `vX.Y.Z` tag management while PyPI name clearance is pending.
- Added GitHub Actions test and release workflows that publish GitHub Releases
  without uploading to PyPI.

## 0.1.0 - 2026-06-12

- Added the taut v0.1 core package: config translation, schema, identity,
  envelope, client API, watcher, and CLI.
- Added contract tests for config, envelope tolerance, sidecar schema,
  cursor semantics, client messaging, CLI JSON/exit behavior, and watcher
  membership refresh.
- Added implementation documentation for the v0.1 architecture and release
  checklist context.
