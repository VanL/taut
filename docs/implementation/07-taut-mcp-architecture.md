# Taut MCP Architecture

## Purpose and Scope

This document explains why the optional `taut-mcp` extension is a
connection-scoped reactor over workspace reactors. It covers workspace
attachment, owner-thread boundaries, ordinary tool dispatch, the aggregate
notification resource, standard resource hints, and the experimental Claude
channel adapter.

The behavior contract lives in `docs/specs/05-taut-mcp.md` [MCP-1]–[MCP-12].
The execution history and review record live in
`docs/plans/2026-07-14-taut-mcp-extension-plan.md`. This note owns current
implementation rationale and edit points, not protocol requirements.

Implementation status: `extensions/taut_mcp/` contains the version-coordinated
0.7.0 package and real stdio server. It is not yet published. The portable
surface is 15 explicit tools plus `taut://notifications/current`; the optional
Claude channel is only a best-effort wake hint.

## Governing Spec References

- `docs/specs/05-taut-mcp.md` [MCP-2] process and connection model,
  [MCP-3] lifecycle, [MCP-4] workspace attachment, [MCP-5] tools,
  [MCP-6] results, [MCP-7] resource representation, [MCP-8] reactor and
  subscription behavior, [MCP-9] agent instructions and host adapters,
  [MCP-10] trust/rate limits, [MCP-11] failures, and [MCP-12] proof
- `docs/specs/02-taut-core.md` [TAUT-3.2] project configuration,
  [TAUT-8.2] public records, [TAUT-8.3] Python client and observational inbox
  peek, [TAUT-9] trust boundary, and [TAUT-11] backend conformance
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3] identity,
  [IAN-6.5] notification queues, and [IAN-7.4] consuming versus observational
  notification reads

## Design Rationale

### One connection reactor, one owner reactor per workspace

MCP stdio already supplies the process lifetime and request loop. Taut state
lives in each selected database, so `taut-mcp` adds no daemon and no durable
session registry. One process serves one MCP connection. Its asyncio thread
owns protocol framing, attachment status, rate admission, resource text, and
response futures.

Each attached workspace has a dedicated persistent child thread. That thread
alone resolves the selected project, constructs the configured `TautClient`,
uses its queues, runs synchronous Taut operations, observes notifications, and
closes all owned handles. This is what lets a blocked backend call stall one
workspace without blocking MCP framing or another workspace.

The shape follows `BaseReactor`'s ownership rule without inheriting
`TautWatcher`'s consuming chat policy. Payloads cross threads only through
unbounded `queue.Queue` instances. Payload-free `threading.Event` and
`call_soon_threadsafe` wakes prompt the appropriate owner to drain its queue.
The master never calls a child client or queue directly and never joins a
child from a request path.

### Hidden attachment seats are lifecycle ownership

An attachment starts with an absolute locator and sensitive continuity token,
but canonical project identity is backend-dependent and must be resolved in a
child. The master therefore reserves a hidden cap seat, fingerprints the token
for same-connection comparison, and starts a provisional child. The child
returns canonical path, stable directory identity, and backend before the
master grants client construction.

This two-phase handshake prevents database work on the MCP thread and prevents
two aliases of one project from publishing two clients. A hidden seat remains
cap-counted until its owner thread exits, including failed or timed-out
cleanup. That can temporarily make fewer than eight entries visible while all
eight seats are occupied. Releasing the seat earlier would permit a second
client while the first still owns backend state.

Published entries retain canonical path and directory identity. Later tool
calls use the exact returned canonical string; they do not rediscover a path.
Detach moves the entry to non-routable `detaching` before it wakes the child.
Identity loss and reactor failure remain visible until explicit detach rather
than silently selecting or healing another member.

### Ordinary tools are explicit child inputs

`_tools.py` declares a fixed manifest. It does not reflect the CLI command
registry, so future core or extension commands cannot become remote tools by
accident. `_commands.py` dispatches the 12 CLI-shaped tools directly to public
`TautClient` methods and serializes public value objects; it never launches the
CLI or parses renderer output.

Each ready workspace has one no-wait command slot. A second call returns busy
instead of growing an unbounded per-workspace queue. Calls to other workspaces
continue independently. A child completion contains the command result and
post-command notification snapshot in one event. The master installs the
snapshot, recomputes resource text, frees the slot, then returns or discards
the result.

Cancellation is queue-ordered. If the child sees a cancel envelope before the
empty-queue start boundary, it does not run the operation. Once the operation
starts, synchronous Taut work is not rolled back; its state and snapshot are
installed while the transport receives the SDK's standard cancellation error.
This is why successful nonempty `read` results carry cursor guidance, the
initialization instructions teach recovery for both `read` and `inbox`, and
the server never retries either operation automatically.

### The notification resource is a cached level; hints are edges

Every ready child keeps an oldest-first, read-only `peek_inbox(limit=101)`
snapshot and publishes at most 100 records plus a truncation bit. The master
sorts workspace entries by canonical path and stores one canonical JSON text.
A resource read returns that text and does no database work. Non-ready entries
remain present with empty notifications so identity or reactor failure is
visible without leaking backend diagnostics.

After binding the existing member, the child registers SimpleBroker's public
multi-queue activity waiter on that member's notification queue before taking
its baseline peek. PostgreSQL can wake through LISTEN/NOTIFY; SQLite returns no
native waiter. Either way, a 0.5-second observational backstop detects missed
wakes and foreign consumption. Native-only bursts are paced to one snapshot
event per 0.5 seconds. The waiter is a hint only: notification content always
comes from `peek_inbox`, so it is never claimed by observation.

Standard `notifications/resources/updated` messages compare exact aggregate
text. Subscription state has its own last-signalled text. The opt-in Claude
adapter has a separate last-attempted text and emits only a fixed cue. It
records the attempt before sending, so a dropped or failed custom event does
not spin on unchanged content. Neither hint is authoritative; clients recover
by rereading the resource.

### Backend neutrality and trust boundaries

The child resolves ordinary Taut configuration, then passes the paired public
`broker_target` and copied `broker_config` into `TautClient`. SQLite and
PostgreSQL therefore create different client objects through the same MCP
path; the server has no backend branch after resolution.

Attachment tokens are secret-equivalent identity selectors, not remote auth.
The raw token transfers to the child queue and the master clears its local
reference immediately after the child thread starts. The child clears its
copy after validation, and the token is never returned. The master keeps only a SHA-256 fingerprint while an entry is
ready. Canonical paths are intentionally returned identifiers, but paths,
tokens, DSNs, participant names, and message text never enter fixed errors,
stderr templates, instructions, or channel cues.

One connection-wide monotonic token bucket covers schema-valid tool calls and
direct resource reads. It limits accidental polling loops but is not an access
control boundary. Schema rejection and server-owned hints are free; admitted
calls are never refunded.

An unexpected child fault is isolated to its workspace and emits one fixed,
content-free stderr diagnostic. Unexpected server or protocol-construction
failure crosses the CLI boundary as one fixed fatal diagnostic and exit 1;
the underlying exception is never rendered. Malformed requests that the SDK
can reject without ending the stdio session remain recoverable protocol input.

### Release bytes and backend evidence have different owners

`taut-mcp` participates in the repository's GitHub-only release system as the
`mcp` target and uses `taut_mcp/vX.Y.Z` tags. The canonical root Test workflow
is the sole release-byte owner. It builds the exact core and MCP wheels,
installs them together in a fresh environment, runs the MCP console version
smoke, and wraps the MCP wheel/sdist pair in an immutable commit-bound bundle.
The MCP tag gate waits for exact-SHA root, PostgreSQL, and MCP workflow
evidence, then gives that root-produced bundle to the generic no-rebuild
release workflow.

The dedicated MCP workflow owns compatibility and live-backend behavior, not
publication bytes. Its matrix runs the complete suite with a real PostgreSQL
service; its quality job runs package-local Ruff, mypy, and an ordinary build.
The root Test workflow also has one separate non-PG MCP coverage producer. It
installs editable local MCP and PG packages because the test `conftest.py`
imports `taut_pg` at collection time, but it starts no database and excludes
`pg_only`. The same-run aggregator requires the named shard and the unique
connection-rate debit line. This split avoids both false PostgreSQL claims and
cross-workflow coverage artifact coupling.

## Boundaries and Invariants

- The MCP/asyncio thread owns registry status, cap seats, admission slots,
  response futures, rate state, and aggregate text. It performs no project or
  database resolution.
- A workspace child owns exactly one persistent configured `TautClient`, its
  queue handles, activity waiter, and synchronous operations.
- Cross-thread payloads use queues. Events are wakeups, not shared mutable
  command state.
- Workspace identity is explicit and object-local. MCP clients pass
  `inherit_environment_identity=False`; ambient `TAUT_AS`, `TAUT_TOKEN`, and
  `TAUT_DB` cannot replace an attachment's selected identity or project.
- The resource is notification-only. Do not add unread-thread inventory or
  consuming watch behavior without a new product contract.
- Standard resource updates and Claude channel events are redundant hints.
  No correctness path may depend on their delivery.
- A live stuck child is never force-detached in-process. Restart is safer than
  allowing a second client to overlap unknown backend ownership.

## Key Files and Verification

| Path | Ownership |
|------|-----------|
| `extensions/taut_mcp/taut_mcp/server.py` | MCP handlers, instructions, capabilities, stdio lifecycle, standard resource subscription wiring |
| `extensions/taut_mcp/taut_mcp/_connection_reactor.py` | master registry, lifecycle arbitration, admission, results, aggregate text, edge trackers, teardown |
| `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` | child resolution, client ownership, command loop, observational notification service, native waiter |
| `extensions/taut_mcp/taut_mcp/_tools.py` | exact 15-tool schemas, descriptions, annotations, output schemas |
| `extensions/taut_mcp/taut_mcp/_commands.py` | explicit public-client command dispatch and record conversion |
| `extensions/taut_mcp/taut_mcp/_claude_channel.py` | isolated fixed-payload experimental notification model and send call |
| `extensions/taut_mcp/tests/` | real SQLite/stdio lifecycle, tool, resource, subscription, cancellation, and adversarial proof; optional live PostgreSQL conformance |
| `.github/workflows/test.yml` | sole MCP release-byte owner, exact core/MCP wheel smoke, and same-run non-PG MCP coverage producer/aggregator |
| `.github/workflows/test-mcp-extension.yml` | required SQLite/PostgreSQL test matrix, package-local quality gates, and ordinary disposable build; no release bytes |
| `.github/workflows/release-gate-mcp.yml` | `taut_mcp/v*` exact-SHA observer and handoff of the immutable root-produced MCP bundle |

Verify a change at the owner boundary. Use real Taut clients, broker queues,
child threads, and stdio for behavior. Fake only an MCP notification sink or
the backend activity-waiter edge when isolating delivery policy. PostgreSQL
activity, pagination, native-wake, and mixed-backend changes require
`SIMPLEBROKER_PG_TEST_DSN`; a skipped live lane is a reported residual, not
passing backend evidence.

## Change Guidance

Read [MCP-4], [MCP-5], [MCP-8], and [MCP-11] before changing reactor state.
Most apparent simplifications move work to the wrong owner or create a race:
normalizing a workspace on later calls breaks identifier stability; sharing a
client crosses queue ownership; force-removing a live failed child permits
overlap; using `TautWatcher` consumes pointers; and merging the two edge
trackers makes one optional hint suppress the other.

If tool fields change, update the spec first and refresh the exact manifest
snapshot. If the aggregate changes, prove read-only state and hostile-content
encoding. If lifecycle changes, fire both event/deadline orders and teardown.
Update this note, the implementation index, repository map, README, changelog,
and plan evidence whenever ownership or rationale changes.

## Related Plan

- `docs/plans/2026-07-15-taut-mcp-release-integration-plan.md`
- `docs/plans/2026-07-14-taut-mcp-extension-plan.md`
