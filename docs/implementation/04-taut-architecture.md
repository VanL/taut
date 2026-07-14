# Taut Architecture

## Purpose and Scope

This document explains the core implementation boundary: the default `.taut.db`
storage boundary, optional `taut-pg` extension boundary, identity resolution,
message read/write path, watcher, and CLI/API split. The TUI, summon extension,
and non-SQL state mappings remain out of scope.

Implementation status: the current code implements the member-id,
mutable-name, direct-message, notification, and channel-rename model specified
in `docs/specs/03-identity-addressing-notifications.md`.

## Governing Spec References

- `docs/specs/02-taut-core.md` [TAUT-3] storage and project resolution
- `docs/specs/02-taut-core.md` [TAUT-4] threads and membership
- `docs/specs/02-taut-core.md` [TAUT-5] identity and presence
- `docs/specs/02-taut-core.md` [TAUT-6] envelope
- `docs/specs/02-taut-core.md` [TAUT-7] chat-history read model
- `docs/specs/02-taut-core.md` [TAUT-8] CLI, Python API, and watcher
- `docs/specs/02-taut-core.md` [TAUT-10] compound-operation ordering
- `docs/specs/02-taut-core.md` [TAUT-12] forward-compatibility obligations
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3] member ids and
  identity claims
- `docs/specs/03-identity-addressing-notifications.md` [IAN-4] mutable names
  and aliases
- `docs/specs/03-identity-addressing-notifications.md` [IAN-5] addressing
- `docs/specs/03-identity-addressing-notifications.md` [IAN-6] queue namespace
- `docs/specs/03-identity-addressing-notifications.md` [IAN-7] notifications
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8] channel rename

## Design Rationale

`TautClient` owns target resolution, identity resolution, address resolution,
message writes, notification writes, and read cursor semantics. The CLI only
parses arguments and renders results. This keeps one operational path for every
verb and prevents CLI behavior from drifting away from the Python API.

The load-bearing supported SimpleBroker floor is 5.3.2. It includes
interruptible watcher bootstrap while PhaseLock or SQLite connection setup is
blocked. The other core runtime dependency is `psutil`. SimpleBroker owns the
storage and queue substrate; `psutil` is scoped to cross-platform process
metadata for identity capture so taut does not rely on fragile platform-
specific argv parsing for the core recognition path.
`taut-pg` is a separate project under `extensions/taut_pg`; it installs
`simplebroker-pg` beside Taut but does not add a root runtime dependency.
The private `taut._broker_retry` module remains only as an import-compatible,
fail-closed shim for the immutable prior Summon wheel. It raises an upgrade
diagnostic if called and contains no retry classifier or loop.

Postgres support intentionally reuses the same core path. `.taut.toml` selects
SimpleBroker's public `postgres` backend plugin, `TautClient` resolves that
`BrokerTarget`, and `taut/state/_sql.py` uses `Queue.sidecar()` to create the
same `taut_*` tables in the configured schema. The extension package does not
own target parsing, queue construction, SQL, identity, CLI rendering, or
watcher behavior.

Release tooling lives in `bin/release.py`. Its boundary is repository hygiene,
not runtime behavior. Each package manifest owns its version. A target-specific
release changes only that selected version, while every normal invocation
reconciles all derived copies: the core constant, README tags and wheel names,
both extension core floors, the root Summon and SimpleBroker PG dev floors,
every root README SimpleBroker requirement, and the retained Summon lock. The
lock refresh is selective (`uv lock --upgrade-package simplebroker`) so
preparation does not absorb unrelated tool upgrades. The helper stages only
that fixed metadata allowlist and creates a local preparation commit before
pytest, type, lint, and build gates. A later gate failure therefore leaves a
clean, unpushed commit that can be inspected or reused on a rerun.

The helper accepts `core`/`pg`/`summon` targets plus `all`;
`all --version X.Y.Z` coordinates all three manifests, while target-specific
versions remain independent. A real publishing run is allowed only from
`main` or `master`, checked once before any preparation mutation; dry-run and
checks-only remain branch-independent. After checking and building the exact
preparation commit, the helper revalidates branch, HEAD, the full clean
worktree/index, GitHub Release state, and local/remote tags. Only then may it
push the branch, mutate or push tags, or cross the GitHub publication boundary.
Branch and tag commands name the tested commit explicitly, and remote tag
replacement uses an exact force-with-lease deletion before the explicit tag
push. Checkout or tag drift therefore fails instead of redirecting the
release. `--checks-only` never reconciles or commits; `--dry-run` prints the
same ordering without writes. The helper has no PyPI upload path while the
`taut` package-name request is unresolved.

For core or summon releases, it also starts summon local-LLM preparation before
the precheck sequence: reuse a configured loopback endpoint if it already
serves the model; otherwise start a disposable loopback Ollama container and
build the bounded served model while root and PG gates run. The release helper
waits on that endpoint at the dedicated local-LLM lane and runs it with
`TAUT_SUMMON_LOCAL_LLM=1`, so a missing local model is a release failure rather
than a hidden skip. External live harnesses run in a separate strict one-worker
lane from the local-LLM lane to keep each SQLite process workload in a fresh
pytest invocation.
GitHub Actions mirrors those process boundaries without duplicating work.
`.github/workflows/test.yml` owns normal push/PR gates and remains reusable.
Its representative Ubuntu root/unit and deterministic-process cells collect
coverage while running their existing selectors; the prepared local-LLM job
owns the live shard. The final coverage job only downloads, combines, checks,
and reports those shards. The root matrix partitions non-slow tests into a
broad lane and one fresh serial installed-wheel lane, so the wheel-building
fixture has one worker owner per selected cell. That environment uses the
matrix interpreter. CI factor-covers installed artifacts across every Python
version on Ubuntu and one representative for each other supported OS, reducing
ten identical-style wheel lanes to six without dropping either version or OS
coverage.

On canonical branch pushes, the Test packaging job builds core, Summon, and PG
once. It passes the explicit core/Summon wheel paths to the paired checker,
installs the PG wheel with that core wheel in a clean venv, then uses
`bin/release-artifact.py` to create three attempt-qualified bundles. Each
bundle contains one wheel, one sdist, and an inner manifest bound to package
name/version, commit, exact file names, and SHA-256 digests. Verification also
binds the release tag family and version to the package.
`.github/workflows/test-pg-extension.yml` remains the real Docker Postgres
evidence and does not rebuild those packages.

The three tag gates call `bin/require-green-workflows.py`; they do not call the
test workflows. The observer selects canonical push evidence by repository,
head repository, workflow path, branch, event, exact commit peeled from either
a lightweight or annotated tag, and latest attempt,
then pins the package bundle by immutable artifact id and GitHub archive
digest. Its 95-minute observer bound covers the 45-minute Test critical path,
queueing, and API visibility; the enclosing job has 110 minutes including
setup. An older-attempt artifact is treated as not-yet-visible for at most two
minutes, then fails closed. `.github/workflows/release.yml` refetches that metadata, downloads the
exact id from the selected run, verifies the inner manifest against the
checked-out tag, rechecks the remote tag immediately before publication, and
uploads those exact bytes to the GitHub Release. It never builds a package.
No workflow uploads to PyPI.

Core and Summon are one paired reactor release boundary. The single owner of
that proof is `bin/build-and-check-release-wheels.py`: it builds fresh core
and Summon wheels in isolated temporary directories by default, then passes
those exact artifacts to `bin/check-core-summon-wheel-matrix.py`. Its explicit
path mode lets canonical CI reuse the current wheels it just built while the
checker still builds all four historical compatibility wheels. Core and Summon
local release paths run the build-owning proof after the local preparation
commit, prechecks, and ordinary builds, but before any branch push, tag
mutation, tag push, or publication, including `--skip-checks`; a PG-only
release does not run it. The same owner checks the retained Summon lock's
resolved SimpleBroker version and compiles the PG manifest into its temporary
artifact root to prove the resolved `simplebroker-pg` floor. The repository
does not retain a PG lockfile.

All production taut-owned relational state flows through `taut/state/`.
`taut/state/__init__.py` exposes the internal `TautState` interface,
`taut/state/_dialect.py` holds the minimal SQL dialect marker, and
`taut/state/_sql.py` is the only production module with sidecar SQL. The
historical schema compatibility shim has been retired
(`docs/plans/2026-07-01-schema-shim-retirement-plan.md`); all callers,
including tests, go through `taut/state/`. That boundary matters because SQL
sidecar tables are the current state mapping, while [TAUT-12.2] reserves a
future non-SQL mapping behind the same state-access boundary.

SQLite sidecar writer transactions are already serialized by its
`BEGIN IMMEDIATE` discipline. PostgreSQL needs two narrower logical locks that
the relational constraints cannot express: a fixed transaction-scoped
`taut:schema` advisory lock is the first statement of schema initialization,
and `taut:route:<normalized-key>` is acquired before member-name or alias
probes. The per-table unique constraints remain the final integrity backstop;
the advisory lock supplies the missing cross-table name/alias namespace.
`SqlSidecarTautState` passes its resolved dialect into only those operations,
while portable and SQLite dialects remain no-ops.

Taut-owned JSON is decoded according to the column contract, not with a
generic fallback. Nullable member/thread metadata maps SQL `NULL` to an empty
object. Malformed JSON, a wrong top-level type, required claim evidence that
is absent, or a malformed channel-rename affected list raises a contextual
error naming its table and column. In particular, corrupt rename state is
never converted to an empty affected list or marked complete.

Membership removal is one `DELETE ... RETURNING` transaction, so concurrent
callers observe exactly one successful removal. `RETURNING` is not a newly
imposed floor: SimpleBroker already requires SQLite >= 3.35.0 (the release that
introduced `RETURNING`) and Postgres supports it, so this adds no dependency
beyond the existing state-backend baseline. `read_unread` decodes a whole
thread page before advancing that thread's cursor once to the page's highest
timestamp; a decoder failure leaves the page cursor unchanged.

Every live chat write uses SimpleBroker's atomic `Queue.write(body)` and takes
the committed message id from that same call ([TAUT-3.4]). Allocating an id with
`Queue.generate_timestamp()` and inserting it later with
`Queue.insert_messages([(body, ts)])` is reserved for import/restore and
deliberate corruption fixtures; it is never a live-write path, because a
timestamp allocated before a set of sidecar transactions can commit below a
cursor that has already advanced past it, permanently hiding the message. The
committed id is still available before rendering, cursor advancement, and
sub-thread naming — it is simply the return value of the write rather than a
pre-generated timestamp. Sidecar-first operations (`join`, first reply, first
DM) may keep a provisional state timestamp for registry and membership fields,
but never reuse it as a broker message id.

List metadata asks SimpleBroker for the newest pending timestamp with
`Queue.latest_pending_timestamp()`. That keeps `taut list` from walking full
thread history for `last_ts` while preserving the public SimpleBroker API
boundary and avoiding a Taut-owned cache or sidecar denormalization.

Channel rename uses `simplebroker.open_broker(...).rename_queue(...)` against
the resolved Taut target. Taut records a sidecar rename marker before broker
queue renames, applies broker renames in deterministic channel-then-subthread
order, and then updates `taut_threads` plus `taut_membership`. The code must not
repair this by editing SimpleBroker-owned message tables.

The rename marker is also the recovery contract ([IAN-8.3]). It is written
before the first broker rename, carries the authoritative affected-queue
list, and is cleared only by the sidecar apply step, so an interruption
anywhere in the window leaves a marker naming exactly what was in flight.
Recovery deliberately rides the same `taut rename OLD NEW` invocation
instead of a repair verb: the marker already names the one legal operation,
every other command refuses with that exact command line, and [TAUT-10]
reserves general registry/queue divergence for a future `doctor` verb —
resume must not grow into a divergence reporter. Resume decides each
affected item from which of its two queue names currently exist rather than
rerunning the fresh path's global target precheck, because resume's own
partial progress legitimately produces already-renamed targets the precheck
would refuse. Both names absent is the normal broker state for an empty
queue and is skipped silently — the same posture as the fresh path's
`queue_exists(old)` guard — while both names present means a foreign queue
occupies the target and aborts loudly before any mutation.

Identity resolution orders its evidence from explicit to inferred: explicit
selection (`--as`), continuity token, claim-hash match, agent anchor match,
then human host/uid fallback ([IAN-3.3]). The anchor-match step exists
because the claim hash deliberately includes mutable process facts (working
directory, tty, process group): a live agent that calls `chdir()`
invalidates its own hash without restarting. The stable
(`host_id`, `anchor_pid`, `anchor_start_time`) triple recovers that
continuity — but only below claim-hash precedence, never under `join --new`,
and never across hosts. An anchor match immediately records the current
claim hash for the member ("healing"), which keeps the fallback
self-limiting: the very next command resolves at the cheaper claim-hash
step, and a healing race against a concurrent process is settled in favor
of the claim-hash owner because step-3 semantics outrank the fallback.

First contact retries auto-chosen names because `choose_name` is
deterministic from the anchor basename seed — simultaneous first contacts
collide by construction, not by accident. Each bounded retry re-mints all
three unique values (name, member id, token) inside the loop body so a
stale candidate can never be reused across attempts. Explicit `--as` names
get exactly one attempt and fail loudly: a collision on a chosen name is a
user decision to surface, not noise to retry through.

Automatic human and agent names share one display rule ([IAN-4.2]): normalize
the login or process seed, then uppercase its first lowercase ASCII letter.
Curated and historical candidates carry display casing, while `choose_name`
canonicalizes every taken name or alias through `route_key`. The state snapshot
is correspondingly route-wide, not member-name-only: `route_keys_in_use()`
unions `taut_members.name_key` with `taut_member_aliases.alias_key`. This keeps
presentation out of uniqueness decisions and lets an alias-owned candidate
advance to the next name instead of failing the same insert repeatedly.

`BaseReactor` is the shared lifecycle mechanism for Taut's long-lived queue
owners. It follows SimpleBroker 5.2.0's executable reference-reactor pattern:
one reactor instance claims one drive thread; inherited final templates own
process, wait, stop signaling, joining, and exactly-once close. A foreign stop
request only signals and wakes. The owner finalizes after a live turn unwinds.
The SIGINT handler follows the same split: it publishes stop and wake state,
then raises `KeyboardInterrupt`; it never closes queues, waiters, or runtime
handles from signal context. `run_forever()` restores the prior handler and
owns exactly-once cleanup from an outer boundary that also covers handler
installation, running-state publication, and drive-owner claim; the CLI's
`finally` remains an idempotent backstop. This keeps native waiter locks and
coverage shutdown hooks outside asynchronous signal re-entry.
The firing proof for the real SIGINT path runs the reactor in a dedicated child
process. The parent owns a bounded watchdog, terminates only that child on a
hang, and converts the failure into a normal assertion before a following
same-worker sentinel. Do not put a thread-mode `pytest-timeout` marker around a
real-signal proof: its timeout path exits the entire xdist worker and reports an
opaque `node down` instead of isolating the faulty probe.
Fixed topology is the default; `TautWatcher` is the explicit owner-thread-only
dynamic-topology policy. A constructor-time compatibility check rejects legacy
subclasses that override lifecycle templates before queue construction while
the `TautBaseWatcher` alias preserves import compatibility.

Each reactor owns one optional native waiter through its `PollingStrategy`;
the rule is per reactor, not process-global. Initial setup calls
`PollingStrategy.start()` once. When the owner commits a later TautWatcher
topology generation, it builds a candidate for the complete queue set and uses
`replace_activity_waiter()` without restarting callback or local-wake state.
Only after replacement succeeds does Taut publish its matching waiter cache and
generation. Taut closes the returned displaced waiter once. Summon's separate
fixed-topology control reactor keeps its own strategy and never needs this
replacement path.

The callback-topology regression proof freezes the module-local monotonic clock:
it verifies replacement occurs before the second strategy wait without turning
runner throughput inside an arbitrary 100 ms window into part of [TAUT-8.5].

`TautWatcher` subclasses `BaseReactor`, which itself extends a copied Weft
`MultiQueueWatcher`, and changes
the peek behavior at the taut boundary for chat queues: fetch uses
`peek_many(..., after_timestamp=cursor)`, pending checks use
`has_pending(after_timestamp=cursor)`, and cursor advancement happens inside the
taut handler wrapper after the user handler returns. For `taut watch`, that
return means a complete record has also been flushed to stdout. A closed output
pipe becomes `StopWatching`: the default error policy stops notification,
initial-chat, and refresh-added queues immediately, while the chat wrapper keeps
the cursor in place and does not count the sink as poison content. Ordinary
handler exceptions retain the three-strike poison rule. Notification queues are
a separate consumable inbox path and must not be forced through chat-history
cursor semantics. The vendored multi-queue watcher installs its fan-in activity
waiter through SimpleBroker's watcher lifecycle hook rather than cloning the
base retry loop. Membership refresh is wired both to SimpleBroker's data-version
callback and to a timer that deliberately counts as pending work, so an idle
watcher still reaches the refresh code on backends whose native waiters only wake
for queue writes. The copied watcher primitive is not edited for Taut cursor semantics;
those adaptations live in `TautWatcher`. Its data-version callback is a wake
hint and membership-refresh trigger, not a `last_ts` cache refresh, because
delivery is governed by taut cursors. `TautWatcher`
keeps persistent owned SimpleBroker queue handles because it is a long-lived
actor that may be queried repeatedly. `TautClient.watch()` returns the exact
instance later driven by `start()`; there is no background proxy or clone. Its
watcher-owned runtime has a separate persistent metadata Queue and state
adapter, so closing the source client cannot invalidate the live watcher and
closing the watcher cannot close the source client. It closes removed
membership handles with `Queue.close()` and closes all owned handles on the
drive owner at watcher shutdown. One-shot
CLI/client paths stay non-persistent. Taut does not add a retry classifier
around queue operations; SimpleBroker owns lock/busy retry, and Taut owns only
handle lifetime and taut-specific state.

`TautClient.watch()` builds a client-owned `TautWatchRuntime` adapter before it
constructs `TautWatcher`. The watcher owns live-follow mechanics and local
in-memory cursors; the runtime adapter owns the translation from `TautState`
membership rows to watched-thread values, message/notification decoding, and
cursor persistence. If watcher validation or construction fails after that
runtime is acquired, `TautClient.watch()` closes it before preserving the
construction error. The copied `MultiQueueWatcher` resolves its cwd fallback
only for `db=None`; the normal client path passes an already resolved target, so
an unrelated cwd config cannot override or break explicit construction.
Direct `TautWatcher(client, ...)` construction is preserved only as a deprecated
constructor compatibility path and is converted immediately to the same runtime.

The core CLI is a thin call into the command dispatcher. Root parsing consumes
only root options and the selected verb; the selected adapter configures its
own core-created parser. Root help still owns the cross-command exit classes,
token trust boundary, and JSON diagnostic rule. Explicit `main([])` is distinct
from `main(None)`: only `None` reads process argv. Runtime reply-id failures
retain their normal exit class and add the owning command form plus the
full-id/4-digit-suffix rule to stderr.

Top-level verb dispatch now lives under `taut/commands/`. Lightweight
`CommandSpec` manifests are static for built-ins and discovered through the
`taut.commands` entry-point group for installed extensions. The registry loads
manifest metadata for root help, but imports a command factory only after that
verb is selected. The core-created `CommandArgumentParser` and
`CommandContext` keep usage exits, root globals, streams, lazy client lifetime,
and final cleanup under core policy while each adapter owns only its local
syntax and controller/client call. Commands with a variable-length positional
grammar may explicitly enable intermixed parsing; the default parser policy is
unchanged for all other adapters.

`summon` and `dismiss` are reserved extension slots, not built-ins. A unique
entry point from the normalized `taut-summon` distribution owns each slot.
Core retains a narrow 0.5.4 compatibility/install-hint adapter for paired
rollout only. Once the 0.6.0 extension is selected, its native command adapters
run directly and the compatibility bridge is not involved.

The complete static-versus-installed registration flow, extension packaging
contract, registry cache timing, and rich-host boundary are documented in
`docs/implementation/06-command-extensions.md`.

Human notification actions are derived at render time from current thread and
membership state. Channel and subthread mentions use the membership-independent
`log` path; DM mentions use bare `read` because internal `dm.*` names are not
public log operands. Only a joined top-level channel gets a reply action, using
the shortest unique suffix in the same 1,000-message window as `reply` and the
full id when no shorter suffix is safe. JSON notification fields remain the
durable machine contract.

## Boundaries and Invariants

- Storage: `.taut.db` is the default durable target. SQLite WAL/shm companions
  are SQLite-managed transients. Under `taut-pg`, `.taut.toml` is config and
  durable chat state lives in the configured Postgres schema.
- Project resolution: `TautClient` resolves a target before any queue is opened.
  Only `TautClient.init()` creates a database.
- Backend selection: `--db`, `db_path=`, and `TAUT_DB` remain filesystem path
  selectors. Postgres is selected only through `.taut.toml`.
- SimpleBroker API: taut imports from `simplebroker` and `simplebroker.ext`
  only. No private SimpleBroker modules and no SQL against broker tables.
- Process capture: `psutil` is the primary source for argv, executable, cwd,
  uid, parent, process group/session, and terminal when available. Native
  `/proc` or `ps` evidence remains the start-time token where needed for
  process identity claims.
- Read model: chat client and CLI paths use peek APIs only. Notification inbox
  paths intentionally claim/read notification messages.
- Cursor writes: `TautState.advance_cursor()` is the only production cursor
  update helper and is monotonic for chat queues.
- Identity timestamps: broker timestamps are generated lazily, only once a
  command is known to create or update member state. Guest read-only commands
  must not move the broker timestamp high-water mark.
- Identity claims: claim recording is idempotent under the read/insert race.
  If another process inserts the same deterministic claim before this process
  does, core rereads the row, refreshes `last_seen_ts` for the same member, and
  still rejects claims owned by a different member.
- Watcher refresh: explicit watch-thread validation is strict at construction.
  During refresh, missing filtered threads are convergence events and are
  dropped rather than treated as fatal errors. The interval refresh must remain
  independent of queue message presence; moving it behind a message-pending gate
  breaks non-SQLite forward compatibility.

## Key Files

| Path | Owner |
|---|---|
| `taut/_constants.py` | Version, config translation, name rules, identity constants |
| `taut/_broker_retry.py` | Fail-closed prior-Summon import compatibility; no active retry behavior |
| `taut/addressing.py` | Target parsing, channel/sub-thread validation, and internal queue naming |
| `taut/_scripts.py` | Developer helper logic for `bin/pytest-pg` |
| `taut/_exceptions.py` | Public exception hierarchy |
| `taut/_watch_runtime.py` | Internal watcher runtime protocol and watched-thread value object |
| `taut/envelope.py` | Envelope encode/decode, `from_id`/`from` snapshot handling, and foreign fallback |
| `taut/state/` | Internal state interface, row types, dialect marker, sidecar DDL, version gate, member, claim, alias, thread, membership, cursor, and rename-state queries |
| `taut/identity.py` | Process-chain capture, claim hashing, identity resolution evidence, presence |
| `taut/client/` | Public API facade, shared base, value models, verb mixins, shared codecs, and watcher runtime adapter |
| `taut/watcher.py` | Shared `BaseReactor`, vendored multi-queue scheduling, chat cursor watching, notification inbox integration |
| `taut/cli.py` | Argparse tree, rendering, exit-code mapping |
| `bin/release.py` | GitHub-only release helper, target/tag planning, dependency sync, and local release gates |
| `bin/release-artifact.py` | Attempt-bound release bundle manifest creation and fail-closed package-byte verification |
| `bin/require-green-workflows.py` | Exact-SHA canonical workflow observer and immutable artifact selector for tag gates |
| `bin/pytest-pg` | Docker-backed Postgres test runner for shared and extension suites |
| `extensions/taut_pg/` | Separate `taut-pg` package, docs, and PG-only tests |
| `extensions/taut_summon/` | Separate `taut-summon` package, summon driver/adapters, docs, and real-process tests |
| `.github/workflows/` | GitHub Actions test and GitHub-only release publication gates |
| `tests/` | Contract tests against real SQLite files, shared backend tests, and subprocess CLI |

## Spec-Code Trace

Normative specs intentionally describe behavior instead of current file
layout. This table is the code-to-spec map agents should use when changing a
requirement or auditing implementation coverage.

| Spec area | Primary code owners | Contract tests |
|---|---|---|
| [TAUT-3.2], project resolution and config | `taut/_constants.py::load_config`, `taut/client/_base.py::_ClientBase._resolve_target`, `taut/client/__init__.py::TautClient.init` | `tests/test_project_config.py`, `tests/test_cli.py::test_init_uses_project_config_postgres_backend` |
| [TAUT-3.3], [TAUT-3.4], sidecar schema and version gate | `taut/state/_sql.py::SqlSidecarTautState.ensure_schema`, `taut/state/__init__.py::TautState` | `tests/test_state_contract.py`, `tests/test_shared_contract.py`, `extensions/taut_pg/tests/test_pg_sidecar.py::test_postgres_concurrent_empty_schema_initializers_converge` |
| [TAUT-4], channels, membership, replies, reads, logs, and listing | `taut/client/_threads.py::ThreadsMixin.join`, `leave`, `list_threads`; `taut/client/_messaging.py::MessagingMixin.say`, `reply`, `read_unread`, `log`; `taut/client/_identity.py::IdentityMixin.who` | `tests/test_client.py`, `tests/test_cli.py`, `tests/test_shared_contract.py` |
| [TAUT-5], [IAN-3], [IAN-4], identity claims, recognition, automatic display names, rejoin, and name changes | `taut/identity.py`, `taut/state/_sql.py::route_keys_in_use`, `taut/client/_identity.py::IdentityMixin._resolve_member`, `_create_member`, `rejoin`, `set_name` | `tests/test_identity.py`, `tests/test_client.py::test_automatic_*`, `test_repeated_pi_agents_use_capitalized_curated_names`, `tests/test_shared_contract.py::test_project_automatic_name_skips_alias_owned_route_contract`, `tests/test_cli.py::test_rejoin_*` |
| [TAUT-6], message envelopes and sender snapshots | `taut/envelope.py`, `taut/client/_codec.py::message_from_body`, `message_from_decoded`, `taut/client/_messaging.py::MessagingMixin._write_message` | `tests/test_envelope.py`, `tests/test_client.py::test_set_name_changes_current_name_without_changing_member_id` |
| [TAUT-7], read cursors and chat-history peek discipline | `taut/client/_messaging.py::MessagingMixin.read_unread`, `_implicit_subthread_membership`, `taut/state/_sql.py` membership and cursor helpers | `tests/test_client.py`, `tests/test_state_contract.py`, `tests/test_shared_contract.py` |
| [TAUT-8.1], [TAUT-8.2], CLI behavior, rendering, JSON, help, and exit codes | `taut/cli.py` | `tests/test_cli.py` parser-inventory, help-phrase, explicit-argv, subprocess, rendering, and exit-class tests; `tests/test_public_api.py` |
| [TAUT-8.6], command manifests, installed discovery, dispatch, parser/context policy, and lazy loading | `taut/commands/` | `tests/test_command_registry.py`, `tests/test_lazy_imports.py`, `tests/test_architecture_boundaries.py`, installed-wheel cases in `tests/test_core_summon_wheel_matrix.py` |
| [TAUT-8.3], Python API objects and verb semantics | `taut/client/__init__.py::TautClient`, `taut/client/_models.py`, and the client mixins | `tests/test_public_api.py`, `tests/test_client.py` |
| [TAUT-8.4], [TAUT-8.5], watcher behavior and shared reactor lifecycle | `taut/watcher.py::BaseReactor`, `taut/watcher.py::TautWatcher`, `taut/_watch_runtime.py`, `taut/client/_watching.py`, `taut/client/__init__.py::TautClient.watch`, `taut/cli.py::_cmd_watch` | `tests/test_watcher.py` ownership, stop, wake, cursor replay, construction cleanup, explicit-target resolution, terminal-stop, poison, ordering, and same-instance tests; `tests/test_cli.py::test_cli_watch_json_flushes_records_while_live`, `test_cli_watch_closed_pipe_exits_0_without_advancing_cursor`; `tests/test_architecture_boundaries.py::test_first_party_reactors_inherit_guarded_lifecycle_templates`; `tests/test_shared_contract.py::test_project_watcher_receives_cli_write`; `extensions/taut_pg/tests/test_reactor.py::test_taut_watcher_native_waiter_rebinds_on_membership_topology_change` |
| [IAN-4], alias/name route namespace | `taut/state/_sql.py` member and alias helpers, `taut/_constants.py::route_key`, `validate_member_name` | `tests/test_state_contract.py`, `tests/test_client.py::test_set_name_changes_current_name_without_changing_member_id`, PostgreSQL create/rename-versus-alias races in `extensions/taut_pg/tests/test_pg_sidecar.py` |
| [IAN-5], [IAN-6], addressing and special queue names | `taut/addressing.py`, `taut/client/_messaging.py::MessagingMixin.say`, `_say_dm`; `taut/client/_threads.py::_thread_from_row` | `tests/test_addressing.py`, `tests/test_client.py::test_direct_message_queue_is_stable_across_name_change`, `test_channel_names_reject_dots_and_reserved_words` |
| [IAN-7], notification payloads and claiming | `taut/client/_messaging.py::_write_mention_notifications`; `taut/client/_codec.py::notification_from_body`; `taut/client/_notifications.py::_write_notification`, `inbox`; `taut/watcher.py` notification path | `tests/test_client.py::test_mention_notification_is_claimed_without_touching_chat_history`, `tests/test_watcher.py` |
| [IAN-8], channel rename and partial-rename reporting | `taut/client/_threads.py::ThreadsMixin.rename_channel`, `taut/client/_base.py::_ClientBase._ensure_no_incomplete_channel_rename`; `taut/state/_sql.py` rename helpers | `tests/test_client.py::test_rename_channel_moves_messages_and_subthreads`, `test_incomplete_channel_rename_blocks_chat_history_operations`, `tests/test_state_contract.py`, shared rename tests |
| [TAUT-12.1], Postgres extension boundary | `extensions/taut_pg/`, `taut/_scripts.py`, `bin/pytest-pg` | `extensions/taut_pg/tests/`, `tests/test_shared_contract.py` under `bin/pytest-pg` |

## Change Guidance

Read `docs/specs/02-taut-core.md`,
`docs/specs/03-identity-addressing-notifications.md`, and the active plan for
the behavior before editing. Prefer extending `TautClient` and `taut/state/`
over adding logic in the CLI or watcher.

The canonical full local verification block lives in `README.md` under
**Development**. Do not duplicate it here. For state/release changes, add the
focused state, Docker Postgres, docs-reference, release-helper, and metadata
tests named by the active plan before running that canonical block.

`bin/pytest-pg` owns a fixed four-worker default for both its shared and
PG-only suites. This is a repeatable concurrency-pressure lane, not a request
to mirror the host's logical CPU count. Operators may pass an explicit pytest
`-n` override. PostgreSQL lock tests use coordinator-owned events to retain
controlled transactions until cleanup releases them; helper threads do not
release real locks merely because the coordinator was descheduled.

Also run the active plan's grep gates for private imports, unexpected consuming
broker APIs, SQL outside `taut/state/_sql.py`, and live-write path drift.
Expected exceptions: `taut/watcher.py` consumes notification queues during
watch, `taut/client/_notifications.py::NotificationsMixin.inbox` claims notification pointers, and
`taut/_scripts.py` may use `SELECT 1` only to validate a Postgres test DSN.

## Related Plans

- `docs/plans/2026-07-13-ci-speed-determinism-release-evidence-plan.md`
- `docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md`
- `docs/plans/2026-07-12-automatic-display-name-capitalization-plan.md`
- `docs/plans/2026-07-10-taut-dynamic-native-waiter-replacement-plan.md`
- `docs/plans/2026-06-18-member-identity-addressing-plan.md`
- `docs/plans/2026-06-12-taut-foundation-plan.md`
- `docs/plans/2026-06-12-taut-0.1.1-hardening-plan.md`
- `docs/plans/2026-06-17-github-release-helper-plan.md`
- `docs/plans/2026-06-17-github-actions-release-workflows-plan.md`
- `docs/plans/2026-06-17-taut-pg-extension-plan.md`
- `docs/plans/2026-06-17-implementation-review-followups-plan.md`
- `docs/plans/2026-06-18-simplebroker-latest-timestamp-plan.md`
- `docs/plans/2026-07-01-schema-shim-retirement-plan.md`
- `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md`
- `docs/plans/2026-07-01-taut-watch-runtime-plan.md`
- `docs/plans/2026-07-06-evaluation-findings-remediation-plan.md`
- `docs/plans/2026-07-09-taut-reactor-safety-plan.md`
