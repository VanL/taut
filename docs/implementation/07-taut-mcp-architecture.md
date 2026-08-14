# Taut MCP Architecture

## Purpose and Scope

This document explains the current `taut-mcp` implementation: one
process-scoped reactor over persistent workspace reactors, exposed through one
MCP SDK v2 server that accepts both legacy `2025-11-25` clients and modern
sessionless `2026-07-28` clients.

The behavior contract lives in `docs/specs/05-taut-mcp.md` [MCP-1]–[MCP-12].
The original implementation history lives in
`docs/plans/2026-07-14-taut-mcp-extension-plan.md`; the dual-era migration and
review record live in
`docs/plans/2026-07-28-taut-mcp-dual-era-sessionless-plan.md`. This note owns
implementation rationale and edit points, not protocol requirements.

The search adapter and its review record live in
`docs/plans/2026-08-10-mcp-search-plan.md`.

The current portable surface is 21 explicit tools plus
`taut://notifications/current`. The optional Claude channel is a
legacy-host-only best-effort wake hint. The package was first published as
0.7.0 from commit `8dfed910d0429226f2faaab776166ad5fd261189`, with root Test
run [29455388946](https://github.com/VanL/taut/actions/runs/29455388946), MCP
run [29455389050](https://github.com/VanL/taut/actions/runs/29455389050), MCP
release gate
[29455393317](https://github.com/VanL/taut/actions/runs/29455393317), and the
[`taut_mcp/v0.7.0` GitHub Release](https://github.com/VanL/taut/releases/tag/taut_mcp/v0.7.0)
as historical release evidence.

## Governing Spec References

- `docs/specs/05-taut-mcp.md` [MCP-2] process model, [MCP-3] lifecycle and
  protocol eras, [MCP-4] shared ensure and identity, [MCP-5] tools and
  cancellation, [MCP-6] results and errors, [MCP-7] resource representation,
  [MCP-8] reactor and subscription behavior, [MCP-9] agent instructions and
  host adapters, [MCP-10] trust and rate limits, [MCP-11] failures, and
  [MCP-12] proof
- `docs/specs/02-taut-core.md` [TAUT-3.2] project configuration, [TAUT-4.4]
  channel topics, [TAUT-8.1] CLI-shaped command behavior, [TAUT-8.2] public
  records, [TAUT-8.3] Python client and observational inbox peek, [TAUT-9]
  trust boundary, and [TAUT-11] backend conformance
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3] identity,
  [IAN-5.1]/[IAN-5.3] asymmetric DM creation and existing-handle validation,
  [IAN-6.5] notification queues, and [IAN-7.4] consuming versus observational
  notification reads
- `docs/specs/06-search.md` [SRCH-3] query grammar, [SRCH-4] visibility and
  scope, [SRCH-5] public results, [SRCH-8] deferred warnings, [SRCH-11]
  backend differences, and [SRCH-12] conformance

## Design Rationale

### One SDK server, two wire eras

The MCP SDK v2 `Server` owns stdio framing, legacy initialization, modern
discovery, protocol negotiation, result envelopes, cache metadata, and
request cancellation. `server.py` installs one async handler set and one
era-neutral lifespan. That lifespan constructs the `ProcessReactor` from the
running asyncio loop before a workspace child can start.

Modern discovery advertises only `2026-07-28`. Legacy compatibility is
provided through the SDK's legacy initialization path, not by adding a legacy
version to modern discovery. Both paths use the same manifest, input
validator, dispatcher, result serializer, fixed tool errors, instructions,
and Taut operations. The only era checks in application code select
protocol-owned resource-not-found codes and the legacy-only Claude adapter.

SDK cache hints keep fixed discovery and list results reusable while making
the changing notification resource private and immediately stale. The SDK
adds modern `resultType`, server information, TTL, and cache-scope fields and
keeps those fields out of legacy envelopes.

### The process reactor is a reactor over workspace reactors

MCP stdio supplies the process lifetime. Taut state remains in each selected
database, so `taut-mcp` adds no daemon and no durable MCP session registry.
The asyncio master thread owns the bounded resident registry, hidden
candidate seats, parent command slots, rate state, response futures,
aggregate resource text, legacy edge tracking, modern bus publication, and
teardown.

Each resident workspace has one dedicated child thread. That thread alone
resolves the selected project, constructs and uses one persistent configured
`TautClient`, owns its broker queues and activity waiter, runs synchronous
Taut operations, observes notifications, and closes its handles. A blocked
backend operation can therefore stall only its workspace.

Cross-thread payloads use unbounded `queue.Queue` instances. Payload-free
`threading.Event` and `call_soon_threadsafe` wakes tell the receiving owner to
drain its queue. The master never calls a child client or broker queue and
never blocks its event loop on `Thread.join()`.

### Two launch adapters, one process runner

The installed distribution registers `taut mcp` through a lightweight command
manifest and retains `taut-mcp` as a standalone convenience script. Both parser
surfaces read installed identity from lightweight `taut_mcp._version`, use
`taut_mcp.cli.configure_parser()`, and call
`taut_mcp.cli.run_process()`; neither invokes the other executable. The shared
runner alone owns `asyncio.run`, broken-transport silence, the fixed fatal
diagnostic, and shell status.

The manifest's raw-stdio declaration makes the root dispatcher skip ambient
terminal-policy description escaping and preflight on successful execution.
The adapter then calls `run_server()` without explicit streams, preserving the
MCP SDK's ownership of file descriptors 0 and 1 and its diversion of stray
process output away from the wire. Help and parser failures occur before that
handoff and remain ordinary `taut mcp` text. The adapter declares no root
globals and never constructs a core client.

### Workspace plus token is the reconstructable handle

Every identity-using tool carries an absolute workspace locator and an
existing continuity token. The token selects an existing Taut member. It is
continuity, not authentication, authorization, or a capability.

`attach_workspace` and every CLI-shaped tool enter the same
`ProcessReactor.ensure_workspace()` state machine. Explicit attach is the
eager path: it pays setup cost and begins observation before a domain
operation. A first CLI-shaped call performs the same setup lazily. Either path
publishes and retains the same child owner until detach, terminal failure, or
process exit.

An exact canonical ready key with the same token fingerprint is the no-I/O
fast path. Another absolute locator enters child-owned resolution and stable
directory-identity arbitration, so aliases converge without publishing a
second client. Hidden seats stay cap-counted until their owner exits; releasing
one earlier could let a second client overlap unresolved backend ownership.

Detach is intentionally narrower. It accepts the exact published canonical
identifier and performs no project or identity reconstruction. An exact
active hidden locator reports busy; every other miss is an idempotent no-op.
Identity-lost, reactor-failed, and validation-timeout records remain visible
until that explicit cleanup.

### Token lifetime and the domain boundary

The process computes an exact-byte SHA-256 fingerprint for resident-binding
comparison, then removes its raw request reference from live reactor state
after child dispatch. The child clears the mutable bootstrap token and its
local validation copy. Its one canonical `TautClient` keeps the constructor
token required by core continuity operations until the owner closes. A caught
internal exception traceback may retain request values until traceback
collection; that local debugging context is outside the live-state cleanup
invariant.

The token and workspace locator end at the ensure boundary. `server.py`
removes both before constructing `RunWorkspaceCommand`; `_commands.py`
receives only the arguments of the named Taut operation. There is no second
token-bearing client, identity cache, or transient command path.

### One manifest, validator, and thin dispatcher

`_tools.py` owns the fixed 21-tool manifest and compiles one Draft 2020-12
validator from each advertised input schema. The shared handler normalizes
only omitted SDK arguments from `None` to `{}`, validates before charging the
rate bucket, and returns one fixed content-free result for known-tool schema
failure. Unknown tools remain protocol errors.

`_commands.py` is the explicit allowlisted dispatcher for the 18 CLI-shaped
tools. It calls public `TautClient` methods and serializes public value
objects. It never launches the CLI, parses terminal output, reflects the
command registry, or receives MCP identity fields. A startup assertion keeps
the manifest's domain partition equal to this dispatcher.

`say.target` intentionally remains a shape-only string in the manifest.
Core accepts bare and quoted-`#` channel/sub-thread forms as well as route and
stable-DM targets, and the selector pattern used by `read`/`log` would narrow
that grammar. Core therefore owns semantic parsing. The command adapter has
one result-only exception: `NotFoundError` from an exact stable `dm.d_*` send
becomes the ordinary empty `message` envelope. Route, channel, sub-thread, and
malformed-target failures retain their existing tool-error behavior.

The `search` branch is intentionally an adapter, not a second search layer.
The process copies its validated selector arrays to immutable tuples before
the child queue boundary. The child supplies the documented defaults and
calls `TautClient.search()` once. It performs no tokenization, filtering,
ranking, retry, or backend branch. `SearchHit` receives its own explicit
ten-field serializer and closed channel/subthread/DM result branches; all
external timestamps remain 19-digit strings.

Core domain and argument exceptions keep their existing MCP handling. A
backend-native unexpected exception from the single search call is translated
to one fixed content-free `TautError`, so provider failure is a tool error and
does not retire the workspace. `EmptyResultError` still reaches the existing
empty-result handler and returns an empty `search_hit` success envelope.

Before each domain command, the child clears both notification and search
warning lists. It returns notification warnings first, then search warnings.
This preserves successful source results when derived-index enqueue fails and
prevents warnings from leaking into the next command.

That serializer applies `simplebroker.format_message_id` only to its explicit
timestamp fields; `_process_reactor.py` does the same for the independently
constructed notification resource. Closed output schemas require 19-digit
strings, while the domain objects and parent/child IPC remain integer-valued.
`log.since` preserves the core ISO-8601/Unix/native-id string grammar and null,
but schema and dispatch reject bare integers outside JavaScript's safe range.
Accepted strings pass to the existing core resolver without a second parser.

Each ready workspace has one no-wait parent command slot. A second command for
that workspace returns busy instead of growing a queue; another workspace can
still proceed. Child completion carries the domain outcome and selected
notification snapshot in one event. The process installs the snapshot,
recomputes the resource, frees the slot, then returns or discards the outcome.

### Cancellation is an ordering boundary, not transaction evidence

The process-owned ensure lifecycle is shielded from request-task
cancellation. A canceled waiter may therefore leave a ready reusable child.
After ensure, command admission and queue enqueue form one non-awaiting master
transition. Cancellation that wins before that transition creates no command;
enqueue that wins first uses the child queue boundary.

For an admitted command, cancellation is another queued control payload. If
the child observes it before the queue-empty start boundary, no `TautClient`
operation runs. Once synchronous work starts, it is not rolled back. Its
status and snapshot still reach the process and its slot still clears. The SDK
sends no JSON-RPC response for a canceled stdio request in either era, so
clients must inspect Taut state before deciding whether a consuming or
mutating operation is safe to retry.

### The notification resource is a cached level; delivery paths are edges

Each ready child keeps an oldest-first observational
`peek_inbox(limit=101)` snapshot and publishes at most 100 records plus a
truncation bit. The process sorts resident entries by canonical path and
stores one canonical JSON string. Reading the resource returns that string
without database work, identity activity, cursor movement, or notification
consumption.

Native database activity wakes and the 0.5-second observational backstop both
lead the child to recompute. Wakes are hints only; content always comes from
`peek_inbox`. Non-ready entries stay visible with empty notifications and no
backend diagnostic.

One aggregate comparison independently offers a semantic change to:

- the legacy `resources/subscribe` sender, tracked by
  `last_signalled_text`;
- the modern SDK v2 `InMemorySubscriptionBus`, whose `ListenHandler` owns
  listener filters, acknowledgments, subscription ids, fanout, cancellation,
  and graceful closure; and
- when enabled for a legacy client, the Claude channel adapter, tracked by
  `last_claude_attempted_text`.

These states are deliberately separate. Failure or duplication in one edge
path cannot suppress another. The resource read is the level-triggered
recovery path for all of them.

### Backend neutrality, rate control, and trust

The child resolves ordinary Taut configuration, then passes the paired public
broker target and copied configuration to `TautClient`. SQLite and PostgreSQL
therefore use the same MCP path. The server has no backend-specific branch
after resolution.

One process-wide monotonic token bucket covers schema-valid tool calls and
successful reads of the fixed resource. It limits accidental loops; it is not
access control. Schema rejection and protocol-owned work are free, admitted
calls are never refunded, and abusive resource polling can throttle a later
tool.

Storage access is the security boundary. A continuity token selects an
identity; it is not a credential, access-control token, or added security
boundary. Deployments may still classify it as sensitive application data.
Workspace paths and tokens are intentionally supplied inputs, but they never
enter fixed diagnostics. Attachment processing does not add the supplied
request token or derived fingerprint to tool results, protocol control text,
stderr, or MCP-owned logs. Core Taut member storage retains the existing
continuity token; the MCP extension persists no additional request-token copy
or fingerprint. Participant names and message text may appear in domain tool
results, and that content could independently contain the same text as a token;
it does not enter fixed diagnostics or protocol control text. Caught internal
exception tracebacks may retain token or fingerprint context for local
debugging. Canonical workspace paths are returned identifiers and remain
untrusted data.

### Release bytes and backend evidence have different owners

`taut-mcp` remains the `mcp` distribution and release target and keeps
`taut_mcp/vX.Y.Z` tags. It depends on the core distribution `taut-chat` while
importing package `taut`. The canonical root Test workflow builds the release
bytes and same-run coverage shard. The dedicated MCP workflow owns the
supported Python matrix, live PostgreSQL conformance, representative
macOS/Windows non-PG lanes, and package-local quality gates.

The tag gate observes exact-SHA evidence and hands the root-produced bundle to
the shared no-rebuild staging workflow. That workflow creates a complete draft
GitHub Release. The top-level MCP gate then re-verifies and publishes the same
wheel and sdist through the `taut-mcp` PyPI Trusted Publisher, checks the
published filenames and SHA-256 digests, and only then invokes the
least-privilege finalizer that makes the GitHub Release public and immutable.
Configuring this path is not evidence that a PyPI version has been published.

## Boundaries and Invariants

- The asyncio master owns process state and performs no project, config,
  filesystem-identity, database, or broker-queue operation.
- A workspace child owns exactly one persistent configured `TautClient` and
  every backend handle derived from it.
- All cross-thread payloads use queues; wakes never carry shared mutable
  command state. Validated JSON arrays are copied to tuples before enqueue.
- Identity-using tool calls always carry workspace plus token. Detach alone
  is workspace-only because it removes process-local state.
- Eager attach and lazy first use share one ensure lifecycle and one retained
  owner. Do not add a transient client path or an attach-required fallback.
- Application behavior does not branch by protocol era. Era checks stay at
  the SDK-owned error, envelope, and host-adapter boundary.
- The aggregate resource is notification-only. Do not add unread-thread
  inventory, search results, or consuming watch behavior without a new product
  contract. Search retains only the ordinary post-command observational inbox
  refresh.
- Legacy updates, modern listen events, and Claude channel cues are redundant
  hints. Correctness depends only on Taut state and resource reread.
- A live stuck child is never force-detached in-process. Restart is safer than
  allowing a second client to overlap unknown backend ownership.

## Key Files and Verification

| Path | Ownership |
|------|-----------|
| `extensions/taut_mcp/taut_mcp/command_manifest.py`, `extensions/taut_mcp/taut_mcp/command.py` | lightweight `taut mcp` registration and raw-stdio command adapter |
| `extensions/taut_mcp/taut_mcp/_version.py` | lightweight installed server identity shared by help/version and runtime paths |
| `extensions/taut_mcp/taut_mcp/cli.py` | shared launch arguments, process runner, transport-failure mapping, and standalone adapter |
| `extensions/taut_mcp/taut_mcp/server.py` | SDK v2 dual-era handlers, lifespan, instructions, cache hints, protocol adapters, and result serialization |
| `extensions/taut_mcp/taut_mcp/_process_reactor.py` | resident registry, shared ensure, alias arbitration, admission, rate state, aggregate text, edge fanout, and teardown |
| `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` | child resolution, client ownership, command loop, token-copy cleanup, and observational notification service |
| `extensions/taut_mcp/taut_mcp/_tools.py` | exact manifest, input validators, descriptions, annotations, and output schemas |
| `extensions/taut_mcp/taut_mcp/_commands.py` | explicit public-client command dispatch and record conversion |
| `extensions/taut_mcp/taut_mcp/_claude_channel.py` | isolated legacy-host fixed-payload experimental notification |
| `extensions/taut_mcp/tests/test_dual_era_contract.py` | focused manifest, application-validator, and per-tool lazy-first-use contract |
| `extensions/taut_mcp/tests/test_process_reactor.py` | shared ensure, alias, lifecycle, cancellation, and process-reactor invariants |
| `extensions/taut_mcp/tests/test_stdio_server.py` | legacy and modern discovery, exact instructions/manifest, stable-DM send/miss framing, schema, cache, subscription, rate, cancellation, and installed-wheel stdio behavior |
| `extensions/taut_mcp/tests/test_tools.py` | exact stable-only miss normalization, shape-only target grammar, real SQLite stable send/effects, search state neutrality, warnings, errors, projection, and cancellation |
| `extensions/taut_mcp/tests/test_pg_conformance.py` | real PostgreSQL stable-DM and search adapter conformance |
| `taut/_scripts.py`, `tests/test_dev_scripts.py` | canonical PostgreSQL runner routing and MCP/PG dependency overlay |
| `.github/workflows/test.yml` | sole MCP release-byte owner and same-run non-PG MCP coverage producer/aggregator |
| `.github/workflows/test-mcp-extension.yml` | Ubuntu SQLite/PostgreSQL matrix, macOS/Windows non-PG lanes, and package-local quality gates |
| `.github/workflows/release-gate-mcp.yml` | `taut_mcp/v*` exact-SHA observer, top-level `taut-mcp` Trusted Publisher, and immutable-release gate |

Verify changes at the owner boundary. Use real Taut clients, broker queues,
child threads, and stdio for behavior. Fake only a notification sink or clock
when isolating delivery or rate policy. PostgreSQL behavior requires
`SIMPLEBROKER_PG_TEST_DSN`; `bin/pytest-pg` recognizes explicit MCP test paths
and installs both extension overlays. The release helper therefore runs an
explicit MCP PG conformance selection immediately after its ordinary PG gate;
the package-local non-PG MCP suite cannot stand in for that proof. A skipped
live lane is a reported residual, not backend-conformance evidence.

## Change Guidance

Read [MCP-4], [MCP-5], [MCP-8], and [MCP-11] before changing reactor state.
Most apparent shortcuts create a second path or move work to the wrong owner:
resolving on the master blocks all workspaces; forwarding identity fields into
domain envelopes unnecessarily broadens token propagation; sharing a client
crosses queue
ownership; force-removing a live failed child permits overlap; and using
`TautWatcher` consumes the pointers this adapter must only observe.

If tool fields change, update the spec first and refresh the exact manifest
and both-era snapshots. If aggregate delivery changes, prove legacy and modern
trackers cannot suppress each other and prove reread recovery. If lifecycle
changes, fire both event/deadline and cancellation/admission orders, then
exercise clean and forced teardown. Update this note, repository maps, README,
changelog, and plan evidence whenever ownership or rationale changes.

## Related Plans

- `docs/plans/2026-08-14-review-findings-remediation-plan.md`
- `docs/plans/2026-08-12-extension-main-path-and-all-extra-plan.md`
- `docs/plans/2026-08-10-stable-dm-send-plan.md`
- `docs/plans/2026-08-10-mcp-search-plan.md`
- `docs/plans/2026-07-29-taut-chat-pypi-publication-plan.md`
- `docs/plans/2026-07-28-taut-mcp-dual-era-sessionless-plan.md`
- `docs/plans/2026-07-28-channel-topics-plan.md`
- `docs/plans/2026-07-28-direct-message-navigation-plan.md`
- `docs/plans/2026-07-15-taut-0.7.1-portability-and-coverage-plan.md`
- `docs/plans/2026-07-15-taut-mcp-release-integration-plan.md`
- `docs/plans/2026-07-14-taut-mcp-extension-plan.md`
