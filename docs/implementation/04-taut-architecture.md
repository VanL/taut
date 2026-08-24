# Taut Architecture

## Purpose and Scope

This document explains the core implementation boundary: the default `.taut.db`
storage boundary, optional `taut-pg` extension boundary, identity resolution,
message read/write path, watcher, and CLI/API split. The TUI, summon extension,
MCP extension, and non-SQL state mappings remain out of scope.

Implementation status: the current code implements the member-id,
mutable-name, direct-message, notification, channel-topic, and channel-rename
models specified in `docs/specs/02-taut-core.md` and
`docs/specs/03-identity-addressing-notifications.md`.

## Governing Spec References

- `docs/specs/02-taut-core.md` [TAUT-3] storage and project resolution
- `docs/specs/02-taut-core.md` [TAUT-4] threads and membership
- `docs/specs/02-taut-core.md` [TAUT-5] identity and presence
- `docs/specs/02-taut-core.md` [TAUT-6] envelope
- `docs/specs/02-taut-core.md` [TAUT-7] chat-history read model
- `docs/specs/02-taut-core.md` [TAUT-8] CLI, Python API, and watcher
- `docs/specs/02-taut-core.md` [TAUT-10] compound-operation ordering
- `docs/specs/02-taut-core.md` [TAUT-12] forward-compatibility obligations
- `docs/specs/02-taut-core.md` [TAUT-13] debug failure capture
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

Long-lived embedding hosts may resolve a project before they construct the
client that owns its database handles. The paired `broker_target` and
`broker_config` constructor arguments carry that already resolved SimpleBroker
context into `TautClient` without consulting `cwd` or `TAUT_DB`. Core still
requires an absolute existing SQLite file before opening a queue. It copies the
resolved config and the target's mutable backend-options mapping at the
boundary, so a host cannot change a live attachment by mutating objects it
passed earlier. The pair is mutually exclusive with the path-only `db_path`
selector, so this lower-level handoff does not turn a DSN into a public path
selector. The target owns backend selection after handoff; the config retains
the resolved queue-operation policy and is not re-read from ambient state. This
seam exists in core because it is useful to any multi-project embedding host;
`taut-mcp` is its first consumer.

User-authored message filtering has one core owner:
`taut/_message_text.py`. `MessagingMixin.say()` and `reply()` call its
built-in Unicode whitespace-or-`Cf` predicate as their literal first
operation. A blank result raises public `BlankMessageError` before target,
identity, thread, membership, notification, or cursor work. The dispatcher
alone maps that exact subtype to silent exit 2. It does not silence other
`EmptyResultError` values. The check is absent from `_write_message`, decoding,
and read paths so structural notices, foreign bodies, and stored history keep
their prior meaning. Accepted strings are passed to the envelope unchanged.

`TautClient.init()` also owns the narrow Windows SQLite filename preflight.
Windows rejects U+0000 through U+001F in path components, while passing such a
target into broker setup can otherwise wait in lock coordination before the
filesystem error surfaces. Core rejects those paths before constructing
`Queue`; it does not broaden this into a portable filename policy, so POSIX
acceptance and non-SQLite targets remain unchanged.

The current SimpleBroker minimum is `simplebroker>=7.3.2`, aligned with the
current `simplebroker-pg>=3.8.0` minimum and their owning lock selections.
Version 7.0.0 supplies the public message-id formatter
and the exact-string JSON boundary while leaving Python and backend values as
integers. Version 7.3.2 supplies the immutable ambient-free resolved-config
marker that Taut preserves across lower layers. Version 5.6.1 remains the
origin of atomic exact-name
`broadcast(..., queue_names=..., create_missing=True)`, in addition to the
earlier interruptible watcher bootstrap, corrected runner cleanup, and
initialized timestamp-conflict metrics. Taut does not use
`simplebroker.commands` or the project-config helpers newly re-exported by
`simplebroker.ext` in 6.0.0; its existing advanced imports already use that
public facade. Taut's reactor treats SimpleBroker's `StopWatching` as terminal
handler control flow even when it arrives before Taut's own stop flag becomes
visible. The other core runtime dependency is `psutil`.
SimpleBroker owns the storage and queue substrate; `psutil` is scoped to
cross-platform process metadata for identity capture so taut does not rely on
fragile platform-specific argv parsing for the core recognition path.
CLI JSON rendering uses the package-root `simplebroker.format_message_id`
helper at each owned timestamp field. The import stays lazy so root help and
unrelated extension help retain their no-backend-import startup contract.
Public value objects, state methods, SQL rows, notification bodies, and search
work items remain integer-valued; the string is an output representation only.

### Debug failure capture is one deep core module

`taut/debug.py` owns the complete debug-capture policy behind one total
operation: `capture_exception()`. Callers name only the surface, operation, and
workspace selector. They do not select a sink, build JSON, search a queue, run
an action, or recover from capture failure. Keeping that failure-prone sequence
inside one deep module matters because it runs while another exception is
already primary. Target resolution, metadata reads, object rendering, queue
search/write/close, subprocess work, and cleanup are all contained so they
cannot replace the original diagnostic or exit behavior.

The workspace setting is core operational metadata in `taut_meta`, not logical
workspace content. Absent means disabled; exact `1` means enabled; disable
deletes the key. `TautClient.set_debug_capture()` requires an initialized
workspace and is the Python owner behind the silent actor-free
`taut system debug enable|disable` commands. Capture reads the value on every
eligible call. Long-running TUI and MCP processes therefore observe later
changes without restart. Logical dump omits both the setting and the
unregistered `taut.debug` queue; load preserves a valid destination setting
and rejects retained debug rows as non-fresh broker state.

That dynamic read has a small deliberate cost: even a disabled workspace opens
the core metadata queue and performs one sidecar read when an eligible boundary
exception occurs. Disabled capture never opens `taut.debug` or starts an action.

The local sink writes bounded UTF-8 JSON containing the exception chain,
head-and-tail frame evidence, bounded locals, runtime metadata, a deterministic
fingerprint, and `taut-debug:<fingerprint>`. Each compact JSON candidate passes
through `taut/_redact.py` before its encoded-size decision. That private helper
compiles its immutable standard-library regex manifest lazily, finds exact
credential-value spans, coalesces overlaps, and replaces right-to-left. Both
the local queue and action stdin therefore receive the same final text without
duplicating sink policy. A redaction failure reaches the capture operation's
existing containment and drops the optional event; unredacted text is never a
fallback.

The helper preserves credential labels, authorization schemes, URI structure,
provider/type prefixes, and PEM boundaries when those contexts exist. It does
not claim completeness. Unknown credential formats and non-credential process
data can remain, continuity tokens are deliberately not label-redacted, and
events retained before the feature are not rewritten. The payload remains
sensitive diagnostic data and is intentionally not a stable compatibility
schema. Under one process lock, the module searches the ordinary SimpleBroker
queue for the literal sentinel, including claimed rows, before writing. This
closes the same-process race but not the cross-process search/write race.
Duplicates across processes are an accepted best-effort result. Removing the
retained message permits recurrence.

Presence of `TAUT_DEBUG_ACTION` replaces the local sink. The value is parsed
with one POSIX argv grammar on every platform and executed without a shell;
the JSON line is stdin, child output is discarded, and a two-second timeout
requests termination. `TAUT_DEBUG_ACTION_ACTIVE=1` is inherited by the child
and suppresses capture in descendants. Parse, spawn, timeout, signal, and
nonzero-exit failure lose that event without local fallback. `TAUT_DEBUG`
remains the separate SimpleBroker debug setting.

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
watcher behavior. Missing-plugin normalization likewise lives below the actor
boundary in `taut/_maintenance.py`; normal client construction, doctor, dump,
and load reuse one install-hint owner instead of importing client-private
diagnostics into actor-free operations.

Release tooling lives in `bin/release.py`. Its boundary is repository hygiene,
not runtime behavior. Each package manifest owns its version. A target-specific
release changes only that selected version, while every normal invocation
reconciles all derived copies: the core constant, any README tags and wheel
names that remain present, all four extension core floors, the root Summon and
SimpleBroker PG dev floors, MCP's development-only `taut-pg` and
`taut-summon` floors, every root
README SimpleBroker requirement, and the retained Summon, MCP, and TUI locks. The
Summon lock refresh is selective (`uv lock --upgrade-package simplebroker`);
the root, MCP, and TUI projects use plain `uv lock` reconciliation for their
local first-party sources and owned ranges. The helper stages
only that fixed metadata allowlist and creates a local preparation commit
before pytest, type, lint, and build gates. Immediately before ordinary release
builds, it preserves and empties all five package `dist/` directories, rejects
a symlink or non-directory at any fixed boundary, and verifies each directory
is empty. This happens even for a single-package release so unselected-package
artifacts cannot linger. Every ordinary build names both its source and that
same package-local output directory explicitly, so uv cannot inherit a parent
workspace's output root. Those ordinary builds also use `--no-sources`, which
prevents local workspace source resolution and unintended lockfile rewrites.
A later gate failure therefore leaves a clean, unpushed commit that
can be inspected or reused on a rerun.

The helper accepts `core`/`pg`/`summon`/`mcp`/`tui` targets plus `all`;
`all --version X.Y.Z` coordinates all five manifests, while target-specific
versions remain independent. A real publishing run is allowed only from
`main` or `master`, checked once before any preparation mutation; dry-run and
checks-only remain branch-independent. By default, every target and `all` run
one identical universal precheck sequence: root, PostgreSQL, an explicit MCP
PostgreSQL selection, all four Summon lanes, the explicit MCP `not pg_only`
lane, the TUI suite at both the retained and exact framework floor,
root/PG/Summon lint/format, package-local MCP and TUI lint/format, and five
collision-safe mypy owners. The local non-PG MCP lane is a fast gate; the
selected MCP PG invocation is its local live-backend proof. Target selection
controls metadata, ordinary builds, tags, and publication, not default
verification scope. `--checks-only` runs that one sequence without mutation.
`--skip-checks` remains an explicit human override; separately owned artifact
builds and paired-wheel compatibility gates still run.

After checking and building the exact preparation commit, the helper
revalidates branch, HEAD, the full clean worktree/index, GitHub Release state,
and local/remote tags. It resolves observer authentication before remote
mutation, pushes the branch, then invokes the workflow-only mode of
`bin/require-green-workflows.py` to wait for canonical root, PostgreSQL, MCP,
and TUI producer success on that exact commit. This local observer consumes no hosted
runner and selects no publication artifact. After success, the helper rechecks
repository settings and repeats the complete fresh release fence before any
tag action. Branch and tag commands name the tested commit explicitly, and
remote tag replacement uses an exact force-with-lease deletion before the
explicit tag push. Checkout, publication, setting, or tag drift therefore
fails instead of redirecting the release. `--skip-checks` bypasses only local
prechecks; it still requires producer evidence. `--checks-only` never
reconciles, authenticates, polls, or commits; `--dry-run` prints the same order
without those actions. The helper has no PyPI upload path while the `taut`
package-name request is unresolved.

For every target whose prechecks run, the helper starts one Summon local-LLM
preparation before the precheck sequence: reuse a configured loopback endpoint
if it already serves the model; otherwise start a disposable loopback Ollama
container and build the bounded served model while root and PG gates run. The
helper waits on that endpoint only at the dedicated local-LLM lane and runs it
with `TAUT_SUMMON_LOCAL_LLM=1`, so a missing local model is a release failure
rather than a hidden skip. External live harnesses run in a separate one-worker
lane with both `TAUT_SUMMON_LIVE_HARNESS=1` and
`TAUT_SUMMON_LIVE_HARNESS_STRICT=1`; enablement and strict prewired behavior
cannot be disabled by an inherited environment. The separate lane keeps each
SQLite process workload in a fresh pytest invocation.
GitHub Actions mirrors those process boundaries without duplicating work.
`.github/workflows/test.yml` owns normal push/PR gates and remains reusable.
Its representative Ubuntu root/unit and deterministic-process cells collect
coverage while running their existing selectors; the prepared local-LLM job
owns the live shard. A separate same-workflow MCP producer installs editable
local MCP and PG packages into the root coverage environment, then runs only
`not pg_only`. The PG package is collection support because MCP's root
`conftest.py` imports `taut_pg` before marker filtering; this job starts no
database. The final coverage job depends on all four producers and only
downloads, combines, checks, and reports their named shards. Root coverage
source includes `taut_mcp`, and the required unique rate-bucket debit line
makes an absent or path-misconfigured MCP shard fatal. The root matrix
partitions non-slow tests into a broad lane and one fresh serial installed-wheel
lane, so the wheel-building fixture has one worker owner per selected cell.
That environment uses the matrix interpreter. Ubuntu and macOS retain complete
source selections. The four Windows Python cells own pairwise-disjoint
deterministic quarters of the complete source selection, plus one small public
CLI smoke on every version. The shard key uses xdist's full effective group
identity after dynamic markers, so grouped tests cannot split. Real-collection
tests prove a nonempty, disjoint, exact union. CI separately factor-covers
installed artifacts across every Python version on Ubuntu and one
representative for each other supported OS, reducing ten identical-style wheel
lanes to six without dropping either version or OS coverage.

Real CLI subprocess assertions use a test-only loopback readiness channel in
`tests/conftest.py::run_cli`. The child acknowledges process startup, imports
the real `taut.cli.main`, arms a separate traceback file, and only then
acknowledges application readiness. The unchanged 20-second command deadline
starts at that second event; interpreter/import startup has its own bound. A
post-readiness timeout remains fatal, kills and reaps the child, and includes
the armed traceback. Cleanup kills and verifies the whole descendant tree
before bounded output collection, so a grandchild cannot keep inherited pipes
open indefinitely. The traceback delay is derived from the exact behavior
deadline rather than a fixed default. The control socket closes before command execution and
never shares stdout, stderr, stdin, argv, storage, or coverage ownership with
the application. A direct `python -m taut` parity probe and the per-version
Windows workflow smoke retain the module-entry contract. Loopback TCP is an
explicit test-runner assumption; inability to bind or connect is a fatal
harness failure, not a skipped test or fallback to elapsed-time polling.

On canonical branch pushes, the Test packaging job builds core, Summon, PG,
MCP, and TUI once. It passes the explicit core/Summon wheel paths to the paired checker,
installs PG with the exact core wheel in one clean venv, and installs MCP with
the exact core wheel in another before running `taut-mcp --version`. It then
uses `bin/release-artifact.py` to create five attempt-qualified bundles. Each
bundle contains one wheel, one sdist, and an inner manifest bound to package
name/version, commit, exact file names, and SHA-256 digests. Verification also
binds the release tag family and version to the package. The core distribution,
bundle, and artifact prefix are `taut-chat`; its import package and console
command remain `taut`, and its `vX.Y.Z` tag family remains unchanged. Extension
distribution and tag names also remain unchanged.
`.github/workflows/test-pg-extension.yml` remains the real Docker Postgres
evidence for the shared backend. `.github/workflows/test-mcp-extension.yml`
runs the complete MCP suite with its own real PostgreSQL service plus MCP-owned
quality checks. `.github/workflows/test-tui-extension.yml` owns the retained-lock
TUI OS/Python matrix moved out of the root workflow. None of these extension
workflows produces release bytes.

Before any real tag push, `bin/release.py` checks twice that immutable GitHub
Releases are enabled and that environment `pypi` admits exactly the five
release-tag families: once as an early preflight and again after exact-SHA
producer observation. Its explicit read-only settings mode runs the same check
without preparing a release. Those read-only requests use a short bounded
retry only for GitHub 502/503/504 responses; credentials, response shape, and
the policy itself stay fail-closed. PyPI Trusted Publisher records are a separate
operator-owned prerequisite because the GitHub API cannot verify them.

The five tag gates call the artifact-selecting mode of
`bin/require-green-workflows.py`; they do not call the test workflows. Every
tag requires root Test, PostgreSQL Test, MCP Test, and TUI Test
evidence for its exact peeled commit. The observer selects canonical push evidence by
repository, head repository, workflow path, branch, event, exact commit peeled
from either a lightweight or annotated tag, and latest attempt,
then pins the package bundle by immutable artifact id and GitHub archive
digest. Its 95-minute observer bound covers the 45-minute Test critical path,
queueing, and API visibility; the enclosing job has 110 minutes including
setup. An older-attempt artifact is treated as not-yet-visible for at most two
minutes, then fails closed. The shared release workflow refetches that
metadata, downloads the exact id from the selected run, verifies the inner
manifest against the checked-out tag, rechecks the remote tag, and stages the
wheel and sdist as a complete draft GitHub Release. It carries the same
verified bundle forward rather than rebuilding. The remote tag, inner
manifest, and checked-out SHA are the commit binding. The release object's
nominal `target_commitish` stays on the default branch: GitHub otherwise
requires Workflows-write permission to publish a draft whose target differs
from current workflow files, and Actions' `GITHUB_TOKEN` cannot receive that
permission.

Each top-level tag gate owns its package's PyPI Trusted Publisher identity.
That job re-verifies the carried bundle and gets OIDC access but no GitHub
contents write access. Existing PyPI files are accepted only when their names
and SHA-256 digests are a matching subset of the expected wheel/sdist pair;
only that preflight permits completion with `skip-existing`, whose
filename-only behavior is not itself the safety check. A bounded post-upload
check requires the complete exact PyPI set. The publish action may create
attestation sidecars in its input directory, so the postflight reconstructs a
separate clean wheel/sdist directory from the carried verified bundle; it does
not weaken the distribution allowlist to ignore new files. Only then does a separate
least-privilege finalizer recheck the tag and exact draft assets and publish
the GitHub Release as immutable. To tolerate eventual release-API visibility,
the finalizer boundedly polls only when an expected asset's uploaded state or
SHA-256 digest is not yet visible. Extra assets, invalid or mismatched digests,
and bound exhaustion remain fatal. Each retry searches only until the
maintainer-visible release listing finds the known release id, which preserves
draft visibility without scanning later pages after the match. The preceding
PyPI job and the independent finalizer each run the same bounded exact PyPI
convergence check before the draft transition because one runner's successful
CDN observation does not linearize a later runner's view. Only absent or exact
matching partial state is retried; mismatches and malformed or failed requests
stay immediately fatal. The workflow is resumable after a matching partial
upload or after PyPI success, but it never rebuilds or reuses a mismatched
version.

Core and Summon are one paired reactor release boundary. The single owner of
that proof is `bin/build-and-check-release-wheels.py`: it builds fresh core
and Summon wheels in isolated temporary directories by default, then passes
those exact artifacts to `bin/check-core-summon-wheel-matrix.py`. Its explicit
path mode lets canonical CI reuse the current wheels it just built while the
checker still builds the historical Summon wheel used as a metadata
diagnostic. The current matrix proves the `taut-chat` core by itself, current
extension pairing and live Summon control, exact current project names and
floors, and resolver rejection of an older incompatible `taut-chat` core when
such a published baseline exists. Historical extension wheels that require
distribution `taut` are not installed as compatible: Python packaging has no
alias from `taut` to `taut-chat`, and the two distributions must not coexist
because both own the same `taut/` files. Core and Summon local release paths
run the build-owning proof after the local preparation commit, prechecks, and
ordinary builds, but before any branch push, tag mutation, tag push, or
publication, including `--skip-checks`; a PG-only release does not run it.
Package tooling checks third-party ranges and retained-lock consistency. The
repository does not retain a PG lockfile; its development dependency selections
come from the root lock.

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

The PostgreSQL contention proof coordinates at that lock boundary rather than
polling `pg_locks` after a Python-side “about to lock” event. The first
transaction acquires and retains the real route lock; the second contender
records the same normalized key and waits at the test gate. An independent
connection must fail `pg_try_advisory_xact_lock` for that exact key before the
gate opens. Releasing both then forces the database lock and the final
one-success/one-conflict state to prove the contract without assuming that a
thread reaching a Python line has submitted its next SQL statement. Bounded
worker gates and transaction-local lock and statement timeouts turn cleanup
defects into ordinary failures rather than stuck executor shutdown.

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
beyond the existing state-backend baseline. `read_unread` first validates its
keyword-only per-call limit as a non-boolean integer in `1..1000`, before
rename, identity, membership, queue, decode, or cursor work. It passes that
limit into the broker peek for each selected membership, so a no-thread call
may return up to the limit from every joined chat thread. It decodes each whole
returned page before advancing that thread's cursor once to the page's highest
timestamp; a decoder failure leaves the page cursor unchanged. `read` is a
thin delegating alias, and the CLI omits the keyword to preserve its
1,000-per-thread default.

Direct-message selection has one actor-aware boundary in the client. The
operation-specific selector parser recognizes current `@name-or-alias` routes
and exact stable `dm.d_*` handles without broadening channel-only commands;
the `say` target parser recognizes the stable form before its dotted
sub-thread branch. The shared resolver validates the registered DM kind,
exact two-member metadata, deterministic pair/name relation, actor
participation, both member rows, and both memberships before any queue access.
It fails closed with one content-free miss for absent, corrupt, or cross-pair
state.

Stable-handle `say` resolves the actor with creation and claim healing both
disabled, then uses that same validated context. Its dedicated existing-DM
writer takes the context's actor, canonical thread, and prior cursor directly;
it publishes through the ordinary message writer and sender-cursor guard. It
does not re-resolve general membership and never enters `_say_dm`, which
remains the sole owner of pair/membership creation and `dm_started`. Ordinary
mention delivery is therefore still constrained by the validated two-person
DM audience. A failed stable send may touch only an already existing actor's
ordinary activity timestamp; it creates or repairs no identity, registry,
membership, notification, message, or queue state.

`read` uses that canonical queue and advances only its existing cursor.
`log` uses non-healing, activity-neutral actor resolution and moves no cursor.
`list_direct_messages()` derives an actor-scoped directory from existing DM
memberships and the same validation boundary, including caught-up and empty
conversations. It adds no index. Machine records retain canonical stable
thread names. The client keeps a stable per-instance label mapping that human
renderers use for `DM with <current-name>` headings without changing message
or JSON values.

Channel topics live in the existing top-level channel registry row because
they describe the channel, not any one message or queue. The `meta` object is a
small namespace: `topic` is an exact audit object and `closed` is only a
reserved sibling in this version. Topic writes replace or remove only the
`topic` member, preserving `closed` and unknown keys. A malformed topic object
fails closed. Readers never infer or repair a partial shape.

`get_channel()` is deliberately cheaper and more observational than
`list_threads()`: it reads one sidecar row and the current topic author's
display name without resolving an actor, opening a broker queue, touching
activity, or moving a cursor. `set_channel_topic()` validates text before
identity work, then requires an existing actor and current channel membership.
An actual change stores text, timestamp, and stable author id together and
updates activity. An identical set or already-absent clear preserves the
existing audit object and activity.

Metadata merge and authority checks happen inside one state transaction.
SQLite's write transaction serializes the mutation. PostgreSQL also takes the
advisory lock for `taut:channel:<channel-name>`. Rename-marker creation joins
that same namespace, which closes the only race that could otherwise let an
old-name topic update miss a concurrent rename. The topic follows the registry
row when the topic transaction wins; the mutation sees the marker and refuses
the old name when rename wins. No topic operation posts a chat notice or a
notification. History remains reserved for conversation events, while the
topic audit fields carry current-state attribution.

The reserved `closed` key and the `channel` CLI noun leave room for a later
lifecycle feature, but they do not implement one. This version assigns no
shape or default to `closed`, does not write or interpret it, and does not
filter or reject channel operations based on it.

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
boundary and avoiding a Taut-owned cache or sidecar denormalization. The same
captured timestamp proves a joined membership is caught up when it is absent
or no newer than `last_seen_ts`, so those rows skip the bounded
`peek_many(1000, after_timestamp=...)` count. A newer timestamp still selects
the existing bounded peek, preserving exact counts through 999 and the 1000
value rendered as `999+`. Listing is not a transactional snapshot: a write
after the latest-timestamp probe may appear on the next list call. Listing
never advances the membership cursor.

Cursor-neutral `log(limit=N)` likewise streams decoded history through a
`deque(maxlen=N)` and sorts only the retained tail chronologically. Its decoded
retention is therefore O(N) even when the selected history is much larger.

Exact message lookup is intentionally separate from history pagination.
`show_message` validates a full ASCII 19-digit signed-int64 id before state
access, searches only the acting member's current chat memberships, and uses
SimpleBroker's exact public peek. A successful show advances that membership's
high-water cursor through the message, so earlier unread rows become seen while
later rows remain unread. The broker row is never claimed.

`history_around` shares the exact validator but binds the lookup to one
`log`-visible canonical thread and deliberately performs no cursor or activity
write. The anchor uses public exact peek. The following side uses bounded
`peek_many(after_timestamp=...)`; because SimpleBroker's public bounded peek is
oldest-first, the preceding side streams a public
`peek_generator(before_timestamp=...)` through a bounded deque to retain the
nearest rows without retaining the full history. This stays backend-neutral and
caps returned/decode-retained state at 1,000 even though finding the nearest
predecessors may scan older history.

`delete_message` uses the same exact validation but searches all registered
chat threads, which lets an author delete after leaving a channel. It exposes
only owned ordinary messages: a miss, foreign author, join/leave notice,
foreign broker body, or lost delete race all produce the same not-found class.
The sole mutation is SimpleBroker's exact `Queue.delete(message_id=...)`.
Taut deliberately does not cascade into memberships, cursors, notifications,
DM registry rows, or sub-thread queues. Those records may therefore point
through a gap or at a message that no longer exists.

`react_to_message` returns to current-membership lookup and accepts only a
decoded ordinary message. The configured reaction vocabulary is loaded from
packaged defaults or replaced by the nearest project `.taut.toml`, then frozen
on the client. Audience comes from one exact-thread membership snapshot with
the actor removed; DM membership is intersected with validated two-party
registry metadata. Empty audiences fail before cursor work.

A valid reaction advances the actor's monotonic cursor through the target,
then converts the audience to exact notification queue names and calls the
public SimpleBroker broadcast once with `create_missing=True`. That broker call
owns validation, queue provisioning, timestamps, transaction, rollback, and
backend retry. Taut neither loops over recipients nor opens broker internals.
An exception is auxiliary: Taut records one warning through the existing
notification-warning channel and returns the intended-audience receipt without retry or cursor
rewind. The shared payload omits `to_id`; the receiving queue is its route.
Repeated calls deliberately create repeated consumable events.

Channel rename uses `simplebroker.open_broker(...).rename_queue(...)` against
the resolved Taut target. Taut records a sidecar rename marker before broker
queue renames, applies broker renames in deterministic channel-then-subthread
order, and then updates `taut_threads` plus `taut_membership`. The code must not
repair this by editing SimpleBroker-owned message tables.

The rename marker is also the recovery contract ([IAN-8.3]). It is written
before the first broker rename, carries the authoritative affected-queue
list, and is cleared only by the sidecar apply step, so an interruption
anywhere in the window leaves a marker naming exactly what was in flight.
Recovery deliberately rides the same `taut channel rename OLD NEW` invocation
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

Identity resolution separates deterministic acting-member selection from local
evidence inference and durable process-claim association ([IAN-3.3]). An
existing explicit name or alias selects first without full process/session
capture. A missing explicit route captures only after the command reaches an
allowed creation path. A valid continuity token selects second, when no
explicit `as` exists, and retains its token-claim/activity writes without
associating the current process. Invalid deterministic selectors terminate;
they never fall through to inferred evidence.

Only selector-free resolution captures before claim-hash match, agent anchor
match, and human host/uid fallback. The anchor-match step exists because the
claim hash deliberately includes mutable process facts (working directory,
tty, process group): a live agent that calls `chdir()` invalidates its own hash
without restarting. The stable (`host_id`, `anchor_pid`, `anchor_start_time`)
triple recovers that continuity, but only below claim-hash precedence, never
under `join --new`, and never across hosts. An anchor match immediately records
the current claim hash for the member ("healing"), which keeps the fallback
self-limiting: the next command resolves at the cheaper claim-hash step, and a
healing race against a concurrent process is settled in favor of the
claim-hash owner because step-3 semantics outrank the fallback.

`rejoin` captures because it is the explicit command for binding the current
process claim to a caller-chosen existing member. `whoami --explain` captures
for diagnostics but does not persist that evidence. The resolver memoizes
capture and claim only within one synchronous operation; it does not cache a
complete capture across commands. There is no deferred identity verification
or association because a later claim collision could not be reported by the
operation that appeared to succeed.

First contact retries auto-chosen names because `choose_name` is
deterministic from the anchor basename seed — simultaneous first contacts
collide by construction, not by accident. Each bounded retry re-mints all
three unique values (name, member id, token) inside the loop body so a
stale candidate can never be reused across attempts. Explicit `--as` names on
creation-capable first contact get exactly one attempt and fail loudly: a
collision on a chosen name is a user decision to surface, not noise to retry
through. Claim-race recovery is role-aware for the same reason. Selector-free
automatic creation may resolve to the member that won the current claim, but
explicit creation never substitutes that member for the caller's selected
name. If another member owns or wins the process claim after the explicit row
is inserted, the new explicit member survives without stealing the claim.

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
process. The child first emits structured startup readiness after imports; only
then does the parent start the strict three-second behavior watchdog. A distinct
bounded startup watchdog diagnoses scheduler or interpreter-launch stalls
without weakening the production-deadlock check. All probe and watchdog tests
share one xdist group. The parent terminates only the child on a hang and
converts the failure into a normal assertion before a following same-worker
sentinel. Do not put a thread-mode `pytest-timeout` marker around a real-signal
proof: its timeout path exits the entire xdist worker and reports an opaque
`node down` instead of isolating the faulty probe.
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

Returning no native waiter is a supported path, not an error-only fallback.
The polling strategy still performs authoritative cursor-aware pending checks,
the timer refreshes membership topology, and handler success persists the
cursor. The PostgreSQL reactor suite forces this capability result to `None`
while keeping the real database, Queue objects, watcher loop, topology change,
post-refresh write, cursor persistence, and shutdown. The existing companion
test keeps the native LISTEN/NOTIFY topology-rebind path covered.

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
pipe becomes Taut's public `WatcherRejected`; the Taut error policy translates
that sentinel to SimpleBroker's internal `StopWatching` mechanism. It stops
notification, initial-chat, and refresh-added queues immediately, while the
chat wrapper keeps the cursor in place and does not count the sink as poison
content. Ordinary handler exceptions retain the three-strike poison rule.
Notification queues are a separate consumable inbox path and must not be forced
through chat-history cursor semantics. The vendored multi-queue watcher installs
its fan-in activity waiter through SimpleBroker's watcher lifecycle hook rather
than cloning the base retry loop. Membership refresh is wired both to
SimpleBroker's data-version
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
Explicit DM filters resolve once on the client owner thread, canonicalize to
stable queue names, and deduplicate before runtime construction. The runtime
and watcher never re-resolve a mutable member route. Dynamic membership
refresh still validates selected DM metadata before decoding and updates the
shared human label mapping in place.
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
Core retains a narrow absent-extension compatibility/install-hint adapter.
The distribution rename ends its historical 0.5.4 installed-artifact
compatibility claim: an old wheel requiring distribution `taut` is not
resolver-compatible with `taut-chat`. When the current extension is selected,
its native command adapters run directly and the compatibility bridge is not
involved.

The complete static-versus-installed registration flow, extension packaging
contract, registry cache timing, and rich-host boundary are documented in
`docs/implementation/06-command-extensions.md`.

Human text has a separate presentation boundary from storage and the client
API. `taut/terminal.py::escape_terminal_text` lazily loads regex source from
the packaged `taut/defaults.toml` and, in inherited mode, the nearest CWD
`.taut.toml` `[terminal_text]` table. It scans each expression independently
and merges matches against the original input. Core human renderers converge
on `taut/commands/_rendering.py::write_human_line`, which escapes one complete
record body before appending structural LF. JSON serialization remains a
separate exact-data seam. Sender values are previewed through the policy for
display-width calculation, but the intermediate row retains the original
sender so generated escape text is never scanned again. Human commands
whose trusted layout contains control characters escape each dynamic field
once before composing that layout: `emit_members` joins its escaped member
fields with real structural tabs and appends its structural LF afterward.
This prevents the packaged C0 policy from turning Taut's own column separators
into visible `\\t` text while retaining field-level control escaping. Human
commands preflight the policy before domain side effects; successful JSON
commands skip that presentation preflight. `watch` also preflights at its direct adapter
boundary. If freshness or a data-dependent empty match exposes a policy failure
while rendering a live item, the adapter converts it to a terminal-delivery
stop before cursor advance, then carries the fixed bootstrap signal out of the
reactor. The item is not retried or classified as poison content.

Presentation discovery is deliberately separate from backend resolution:
resolve CWD, walk to filesystem root without an artificial depth cap, and use
the nearest `.taut.toml`. Storage selectors do not relocate it. Discovery runs
on each inherited call; parsed tables use a bounded path/device/inode/mtime/size
cache. This reflects edits, deletion, and newly created nearer policy on the
next call without a filesystem watcher. A public `inherit_defaults=False`
call bypasses both ambient discovery and packaged-resource access.

Missing or invalid packaged or project policy fails closed with one fixed
diagnostic. Core dispatch keeps the pre-existing malformed-project-file signal
with a separate static `invalid .taut.toml: ...` bootstrap line; it never
renders a dynamic path or TOML parser text through the failed policy. Project
patterns are trusted local configuration and may disable
the safety default or impose expensive regex work. This is aimed at accidental
relay, including an agent echoing controls after prompt injection. It does not
authenticate senders or make Taut a security boundary. Summon's explicit PTY
lease remains byte-transparent and bypasses the text renderer by design.

Human notification actions are derived at render time. Channel and subthread
mentions use the membership-independent `log` path and retain their membership
and reply-suffix probes. DM mentions use the pointer's stable source thread in
`taut log`, and `dm_started` uses it in `taut read`. Classifying and building
those DM actions performs no identity, registry, list, or source-queue lookup.
Only a joined top-level channel gets a reply action, using the shortest unique
suffix in the same 1,000-message window as `reply` and the full id when no
shorter suffix is safe. JSON notification fields remain the durable machine
contract.

Notification observation has two deliberately different public operations.
`NotificationsMixin.inbox()` resolves through the ordinary activity-touching
identity path and claims pending pointers. `peek_inbox()` uses the same queue
selection and decoder but resolves only an existing member without activity or
claim writes and calls SimpleBroker's non-consuming `peek_many`. That makes the
peek suitable for bounded extension-side observation while keeping queue names,
payload compatibility, and malformed-pointer handling in core. It is not a
durable subscription: another consumer can claim a pointer between peeks, and
the source chat message remains the recovery record.

Reaction pointers use the same observation and claim paths. Their decoder
checks only the stable slug grammar, not the receiver's configured outbound
vocabulary, so peers with different attachment-time config remain compatible.
Human and MCP renderers preserve the source id as an inspection hint without
preflighting the source; deletion can therefore leave a stale but valid
pointer.

There is no second Taut acknowledgement table. For this contract,
acknowledgement state is the notification queue's pending-versus-claimed state,
while chat cursor state is the stored membership rows. The cross-backend proof
therefore snapshots notification queue statistics and every membership for the
selected member, along with the member row, continuity-token claim, and metadata
queue high-water mark.

## Boundaries and Invariants

- Storage: `.taut.db` is the default durable target. SQLite WAL/shm companions
  are SQLite-managed transients. Under `taut-pg`, `.taut.toml` is config and
  durable chat state lives in the configured Postgres schema.
- Project resolution: `TautClient` resolves a target before any queue is opened,
  or receives one paired with the exact resolved broker config through its
  explicit embedding handoff. Only `TautClient.init()` creates a database.
- Backend selection: `--db`, `db_path=`, and `TAUT_DB` remain filesystem path
  selectors. Postgres is normally selected through `.taut.toml`; explicit
  `TAUT_BACKEND*` values are the no-project-file backend-selection door.
- SimpleBroker API: taut imports from `simplebroker` and `simplebroker.ext`
  only. No private SimpleBroker modules and no SQL against broker tables.
- Reaction fanout: exactly one public exact-name broadcast owns the
  cross-queue transaction. Taut does not enumerate broker storage, use a
  wildcard, or write once per recipient.
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

Configuration crosses the SimpleBroker boundary as a complete immutable
`ResolvedConfig`. `taut/_constants.py` first lists the few named defaults that
encode Taut behavior: storage, project discovery, SQLite selection, and load
skew. Its other named defaults mostly have nothing to do with Taut policy.
They mirror SimpleBroker solely to close every field and isolate Taut from
ambient `BROKER_*`. The nominal mapping matters as much as completeness because
broker lower layers resolve config repeatedly; an ordinary dictionary would
resume ambient environment reads. Client and watcher ownership boundaries
therefore recreate the public marker through the ambient-free resolver.

| Path | Owner |
|---|---|
| `taut/_constants.py` | Version, config translation, name rules, identity constants |
| `taut/_message_text.py` | Built-in Unicode blank classifier for user-authored message entry points |
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
| `bin/release.py` | PyPI/GitHub publication-state-aware release helper, target/tag planning, dependency sync, producer-first exact-SHA observation, repeated settings/fresh-state fences, and local release gates |
| `bin/release-artifact.py` | Attempt-bound release bundle manifest creation and fail-closed package-byte verification |
| `bin/require-green-workflows.py` | Exact-SHA canonical workflow observer; workflow-only local waiting for the release helper and immutable artifact selection for tag gates |
| `bin/pytest-pg` | Docker-backed Postgres test runner for shared and extension suites |
| `extensions/taut_pg/` | Separate `taut-pg` package, docs, and PG-only tests |
| `extensions/taut_summon/` | Separate `taut-summon` package, summon driver/adapters, docs, and real-process tests |
| `extensions/taut_mcp/` | Separate `taut-mcp` package, stdio protocol adapter, package-local quality gates, and cross-backend conformance tests |
| `.github/workflows/` | GitHub Actions tests plus exact-artifact PyPI and immutable GitHub Release gates |
| `tests/` | Contract tests against real SQLite files, shared backend tests, and subprocess CLI |

## Spec-Code Trace

Normative specs intentionally describe behavior instead of current file
layout. This table is the code-to-spec map agents should use when changing a
requirement or auditing implementation coverage.

| Spec area | Primary code owners | Contract tests |
|---|---|---|
| [TAUT-3.2], isolated config translation, project resolution, resolved target/config handoff, and Windows SQLite path preflight | `taut/_constants.py::load_config`, `freeze_broker_config`, `taut/client/_base.py::_ClientBase.__init__`, `_resolve_target`, `taut/client/__init__.py::TautClient.init`, `taut/client/_watching.py`, `taut/watcher.py` | exhaustive translation/isolation cases in `tests/test_constants.py`; resolved-handoff, argument-pair, missing-target cases in `tests/test_client.py`; `tests/test_shared_contract.py::test_project_resolved_target_config_handoff_contract` on SQLite and PostgreSQL; `tests/test_project_config.py`; `tests/test_cli.py::test_init_uses_project_config_postgres_backend`, `test_windows_sqlite_target_validation_rejects_every_control`, `test_posix_sqlite_target_validation_preserves_control_bearing_paths`, and `test_cli_windows_control_bearing_database_target_fails_fast` |
| [TAUT-3.3], [TAUT-3.4], sidecar schema and version gate | `taut/state/_sql.py::SqlSidecarTautState.ensure_schema`, `taut/state/__init__.py::TautState` | `tests/test_state_contract.py`, `tests/test_shared_contract.py`, `extensions/taut_pg/tests/test_pg_sidecar.py::test_postgres_concurrent_empty_schema_initializers_converge` |
| [TAUT-4], channels, membership, replies, reads, logs, and listing | `taut/client/_threads.py::ThreadsMixin.join`, `leave`, `list_threads`; `taut/client/_messaging.py::MessagingMixin.say`, `reply`, `read_unread`, `log`; `taut/client/_identity.py::IdentityMixin.who` | `tests/test_client.py`, `tests/test_cli.py`, `tests/test_shared_contract.py` |
| [TAUT-4.4], channel-topic validation, observational reads, membership-scoped mutation, metadata merge, and rename serialization | `taut/state/_channel_topics.py`; `taut/state/_sql.py::set_channel_topic`, `start_channel_rename`; `taut/client/_threads.py::ThreadsMixin.get_channel`, `set_channel_topic`, `_channel_from_row` | Channel-topic and corruption cases in `tests/test_state_contract.py`, `tests/test_client.py`, and `tests/test_shared_contract.py` on SQLite and PostgreSQL; channel CLI cases in `tests/test_cli.py` |
| [TAUT-5], [IAN-3], [IAN-4], identity claims, deterministic selector capture, recognition, automatic display names, rejoin, and name changes | `taut/identity.py`, `taut/state/_sql.py::route_keys_in_use`, `taut/client/_identity.py::IdentityMixin._resolve_member`, `_create_member`, `rejoin`, `set_name` | `tests/test_identity.py`; `tests/test_client.py::test_existing_explicit_selector_skips_capture_and_preserves_process_identity`, `test_valid_token_selector_skips_capture_and_preserves_token_activity`, selector creation/guest/rejoin/explain cases, and `test_automatic_*`; `tests/test_identity_performance.py` (manual evidence, not a timing contract); `tests/test_shared_contract.py::test_project_automatic_name_skips_alias_owned_route_contract`; `tests/test_cli.py::test_rejoin_*` |
| [TAUT-6], message envelopes and sender snapshots | `taut/envelope.py`, `taut/client/_codec.py::message_from_body`, `message_from_decoded`, `taut/client/_messaging.py::MessagingMixin._write_message` | `tests/test_envelope.py`, `tests/test_client.py::test_set_name_changes_current_name_without_changing_member_id` |
| [TAUT-6.5], blank user messages and exact accepted text | `taut/_message_text.py::is_blank_message_text`, `taut/_exceptions.py::BlankMessageError`, `taut/client/_messaging.py::MessagingMixin.say`, `reply`, and `taut/commands/_dispatch.py::_render_execution_error` | `tests/test_message_text.py`; blank, precedence, historical-read, and exact-text cases in `tests/test_client.py`, `tests/test_cli.py`, and `tests/test_shared_contract.py`; paired import proof in `tests/test_core_summon_wheel_matrix.py` |
| [TAUT-6.4], [TAUT-8.3], [TAUT-8.6], [TAUT-9], terminal text safety and exact-data boundaries | `taut/terminal.py::escape_terminal_text`, `taut/defaults.toml`, `taut/commands/_rendering.py::write_human_line`, dispatcher/parser diagnostics, and the Summon command/log adapters | `tests/test_terminal_text.py`, terminal-control cases in `tests/test_cli.py` and `tests/test_command_registry.py`, `tests/test_architecture_boundaries.py::test_first_party_terminal_sink_inventory_is_explicit`, and the touched Summon CLI/driver/PTY tests |
| [TAUT-7], read cursors, exact show/delete/react/context, bounded per-call unread/context pages, and chat-history peek discipline | `taut/client/_messaging.py::MessagingMixin.read`, `read_unread`, `show_message`, `history_around`, `delete_message`, `react_to_message`, `_implicit_subthread_membership`; `taut/client/_threads.py::_thread_from_row`, `_unread_count`; `taut/state/_sql.py` membership and cursor helpers | `tests/test_client.py` exact-id, ownership, reaction audience/failure, visibility, cursor, history-context, race, limit, decode-failure, caught-up-list, saturation, and list-race cases; `tests/test_client_stateful.py`; `tests/test_state_contract.py`; `tests/test_shared_contract.py::test_project_read_limit_paginates_without_skipping`, `test_project_exact_show_and_delete_contract`, `test_project_history_around_is_cursor_neutral_across_sql_backends`, and `test_project_message_reaction_contract` on SQLite and PostgreSQL |
| [TAUT-8.1], [TAUT-8.2], CLI behavior, rendering, JSON, help, and exit codes | `taut/cli.py`, `taut/commands/_dispatch.py`, `taut/commands/channel.py`, and the other per-verb command adapters | `tests/test_cli.py` parser-inventory, channel-topic/rename, help-phrase, explicit-argv, subprocess, rendering, blank-input, and exit-class tests; `tests/test_public_api.py` |
| [TAUT-8.6], command manifests, installed discovery, dispatch, parser/context policy, and lazy loading | `taut/commands/` | `tests/test_command_registry.py`, `tests/test_lazy_imports.py`, `tests/test_architecture_boundaries.py`, installed-wheel cases in `tests/test_core_summon_wheel_matrix.py` |
| [TAUT-8.3], Python API objects, `Channel`, `MessageDeletion`, `MessageReaction`, notification peek, and verb semantics | `taut/client/__init__.py::TautClient`, `taut/client/_models.py`, `taut/client/_notifications.py::NotificationsMixin.peek_inbox`, the other client mixins, and lazy root exports | `tests/test_public_api.py`, `tests/test_client.py` channel, exact-message, reaction, notification-peek, and other client contracts, shared channel/exact-message/reaction/notification contracts in `tests/test_shared_contract.py` on SQLite and PostgreSQL, `tests/test_terminal_text.py`, `tests/test_lazy_imports.py` |
| [TAUT-8.4], [TAUT-8.5], watcher behavior, public `WatcherRejected`, and shared reactor lifecycle | `taut/_exceptions.py::WatcherRejected`, `taut/watcher.py::BaseReactor`, `taut/watcher.py::TautWatcher`, `taut/_watch_runtime.py`, `taut/client/_watching.py`, `taut/client/__init__.py::TautClient.watch`, `taut/commands/watch.py` | `tests/test_watcher.py` ownership, stop, wake, cursor replay, construction cleanup, explicit-target resolution, terminal rejection, poison, ordering, and same-instance tests; `tests/test_cli.py::test_cli_watch_json_flushes_records_while_live`, `test_cli_watch_closed_pipe_exits_0_without_advancing_cursor`, `test_cli_watch_policy_failure_stops_without_advancing_cursor`; `tests/test_public_api.py`; `tests/test_architecture_boundaries.py::test_first_party_reactors_inherit_guarded_lifecycle_templates`; `tests/test_shared_contract.py::test_project_watcher_receives_cli_write`; `extensions/taut_pg/tests/test_reactor.py` native-waiter rebind and forced polling-fallback tests |
| [IAN-4], alias/name route namespace | `taut/state/_sql.py` member and alias helpers, `taut/_constants.py::route_key`, `validate_member_name` | `tests/test_state_contract.py`, `tests/test_client.py::test_set_name_changes_current_name_without_changing_member_id`, PostgreSQL create/rename-versus-alias races in `extensions/taut_pg/tests/test_pg_sidecar.py` |
| [IAN-5], [IAN-6], addressing, stable existing-DM send, and special queue names | `taut/addressing.py`, `taut/client/_base.py::_resolve_direct_message`, `taut/client/_messaging.py::MessagingMixin.say`, `_say_existing_dm`, `_say_dm`; `taut/client/_threads.py::_thread_from_row` | `tests/test_addressing.py`; direct selection, corruption, nonhealing, and blank-order cases in `tests/test_direct_messages.py` and `tests/test_client.py`; full valid/miss/name-reassignment matrix in `tests/test_shared_contract.py` on SQLite and PostgreSQL; CLI/registry cases in `tests/test_cli.py` and `tests/test_command_registry.py` |
| [IAN-7], notification and reaction payloads, observational peek, claiming, and stale pointers after message deletion | `taut/client/_messaging.py::_write_mention_notifications`, `react_to_message`, `delete_message`; `taut/client/_codec.py::notification_from_body`; `taut/client/_notifications.py::_write_notification`, `peek_inbox`, `inbox`; `taut/commands/_rendering.py`; `taut/watcher.py` notification path | notification/reaction peek, consuming-inbox, audience, broadcast-failure, and deletion-without-cascade cases in `tests/test_client.py`; notification rendering in `tests/test_cli.py`; shared notification/reaction contracts in `tests/test_shared_contract.py`; `tests/test_watcher.py` |
| [IAN-8], channel rename, topic preservation/serialization, and partial-rename reporting | `taut/client/_threads.py::ThreadsMixin.rename_channel`, `taut/client/_base.py::_ClientBase._ensure_no_incomplete_channel_rename`; `taut/state/_sql.py` topic and rename helpers | `tests/test_client.py::test_rename_channel_moves_messages_and_subthreads`, channel topic/corruption cases, `test_incomplete_channel_rename_blocks_chat_history_operations`, `tests/test_state_contract.py`, shared rename/topic tests |
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

- `docs/plans/2026-08-14-review-findings-remediation-plan.md`
- `docs/plans/2026-08-11-ci-factor-and-release-order-plan.md`
- `docs/plans/2026-08-10-stable-dm-send-plan.md`
- `docs/plans/2026-07-29-taut-chat-pypi-publication-plan.md`
- `docs/plans/2026-07-28-direct-message-navigation-plan.md`
- `docs/plans/2026-07-14-blank-message-no-op-plan.md`
- `docs/plans/2026-07-14-smaller-quality-followups-plan.md`
- `docs/plans/2026-07-14-universal-release-gates-plan.md`
- `docs/plans/2026-07-13-ci-speed-determinism-release-evidence-plan.md`
- `docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md`
- `docs/plans/2026-07-12-automatic-display-name-capitalization-plan.md`
- `docs/plans/2026-07-10-taut-dynamic-native-waiter-replacement-plan.md`
- retired: 2026-06-18-member-identity-addressing-plan (source `3cae1f4`; see
  the ledger in `docs/plans/README.md`)
- retired: 2026-06-12-taut-foundation-plan (source `f1259c0`; see the ledger
  in `docs/plans/README.md`)
- retired: 2026-06-12-taut-0.1.1-hardening-plan (source `f1259c0`; see the
  ledger in `docs/plans/README.md`)
- retired: 2026-06-17-github-release-helper-plan (source `dadd324`; see the
  ledger in `docs/plans/README.md`)
- retired: 2026-06-17-github-actions-release-workflows-plan (source
  `33e13ee`; see the ledger in `docs/plans/README.md`)
- retired: 2026-06-17-taut-pg-extension-plan (source `24dc2bc`; see the
  ledger in `docs/plans/README.md`)
- retired: 2026-06-17-implementation-review-followups-plan (source `348eae9`;
  see the ledger in `docs/plans/README.md`)
- retired: 2026-06-18-simplebroker-latest-timestamp-plan (source `348eae9`;
  see the ledger in `docs/plans/README.md`)
- `docs/plans/2026-07-01-schema-shim-retirement-plan.md`
- `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md`
- `docs/plans/2026-07-01-taut-watch-runtime-plan.md`
- `docs/plans/2026-07-06-evaluation-findings-remediation-plan.md`
- `docs/plans/2026-07-09-taut-reactor-safety-plan.md`
