# Debug Failure Capture Plan

Date: 2026-08-14

Status: completed

Owner: Taut maintainers

Class: 5: normative failure, persistence, CLI, and first-party extension change

Plan type: implementation with spec revision

Hardening: required. The change adds operational metadata, retained exceptional
data, a subprocess boundary, and failure-path calls from several containment
points. Debug capture must never replace the failure it is trying to preserve.

## Goal

Add an opt-in, workspace-scoped debug capture facility for exceptions that reach
a Taut-owned outer containment point. Operators enable or disable it with
`taut system debug enable` and `taut system debug disable`; both successful
commands are silent. `taut system doctor` reports the current setting and sink.

When enabled, one core handler records a bounded traceback, frame locals, and
available runtime and operation metadata. By default it writes a versioned JSON
event to the reserved `taut.debug` SimpleBroker queue. If
`TAUT_DEBUG_ACTION` is present, the handler sends the same JSON event to that
executable over stdin instead of writing locally. Every capture path is best
effort. Capture, formatting, deduplication, queue, subprocess, and cleanup
failures are swallowed so the original exception, protocol result, diagnostic,
exit code, and cleanup priority stay unchanged.

The motivating case is a Textual `ScreenStackError` whose rich traceback
contained the actionable state: an enabled `identity.set-name` palette entry
attempted to dismiss the only screen. The feature is intended to retain that
kind of otherwise transient evidence after the ordinary surface has rendered or
contained the failure.

## Requested Outcome

- debug capture is absent and disabled by default
- `taut system debug enable` stores the workspace setting; disable removes it
- both setting commands are actor-free, idempotent, and silent on success
- doctor reports enabled state and whether the selected sink is local or action
- a Taut-owned outer boundary calls one core handler when an `Exception`
  reaches it
- the handler reads the persisted setting at capture time, including in
  long-running processes
- local events use an ordinary SimpleBroker queue and ordinary `broker`
  commands for inspection, read, and deletion
- `TAUT_DEBUG_ACTION` replaces local storage and receives JSON on stdin
- repeated local captures use a deterministic sentinel and the public
  `Queue.find_message_ids(body_contains=..., include_claimed=True)` API for
  best-effort retention-scoped deduplication
- debug settings and events are not part of Taut logical dump/load
- all failures in the debug path leave the original failure behavior unchanged

## Source Documents

- `docs/program-theory.md`
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-14], and [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-3.1], [TAUT-3.2], [TAUT-8.1],
  [TAUT-9], [TAUT-10], and [TAUT-11]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-6.1]
- `docs/specs/04-summon.md` [SUM-3], [SUM-11], and [SUM-12]
- `docs/specs/05-taut-mcp.md` [MCP-3], [MCP-8], [MCP-11], and [MCP-12]
- `docs/specs/08-persistence-io.md` [PIO-5.1], [PIO-5.2], [PIO-5.4],
  [PIO-7.2], [PIO-7.3], and [PIO-11]
- `docs/specs/09-system-doctor.md` [DOCT-2], [DOCT-3], [DOCT-4], and
  [DOCT-7]
- `docs/specs/10-taut-tui.md` [TUI-12] and [TUI-13]
- `docs/specs/product-section-registry.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/implementation/11-system-doctor.md`
- `docs/implementation/12-taut-tui.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/lessons.md`, especially the distinction between opaque operational
  data and secret classification

## Classification and Promotion

This is Class 5 under [DOM-15]. It changes the normative CLI, public Python
surface, doctor inventory, core metadata ownership, persistence eligibility,
retained-data lifecycle, and failure behavior of first-party extensions. It is
also risky under the hardening runbook because it adds a subprocess call on an
already failing path and new durable data that can contain secrets.

Use [DOM-5] strategy A. After maintainer acceptance and independent review,
promote the exact deltas below into the existing active specs before behavior
implementation. Because the promoted core spec will name the two new CLI paths
before their parser exists, add the claim gate's one exact, source-scoped
normalized future-path exemption for `system debug` to
`tests/test_cli_claims.py` in the same promotion slice. It covers only the two
promoted source claims because unresolved nested paths stop at `debug`. Remove
the exemption in the command slice. Do
not add code links or state that the feature is shipped until the firing gates
pass.

## Spec Baseline and Worktree Boundary

The baseline for every proposed spec edit is:

`45592f0f09356d0818a74a8c8bb5fbaebc1976ed`

Before promotion, compare each touched section with that commit. If a section
changed in a conflicting way, revise this plan and repeat plan review instead
of applying the text mechanically.

The planning worktree already contains unrelated changes in:

- `docs/implementation/03-agent-inventory.md`
- `docs/plans/README.md`
- `extensions/taut_tui/taut_tui/screens.py`
- `extensions/taut_tui/tests/test_tui_app.py`
- `docs/plans/2026-08-14-cross-surface-command-capability-plan.md`

Those changes belong to prior work and are not part of this capability. Every
implementation slice must diff from the recorded baseline and preserve them.

## Proposed Spec Delta

### Core ownership and public surface

Add a new `## 13. Debug Failure Capture [TAUT-13]` section to
`docs/specs/02-taut-core.md`, before Implementation Mapping, with these stable
subsections and requirements:

#### [TAUT-13.1] Setting and command

> Debug failure capture is workspace-scoped, absent and disabled by default,
> and stored as core operational metadata under the `taut_meta` key
> `debug_capture`. Enabled is the exact value `1`; disable deletes the key.
> Other values are malformed operational state. Enable replaces a malformed
> value with `1`; disable removes it. Those commands are the supported repair
> path for this one operational key. The actor-free commands are
> `taut system debug enable` and `taut system debug disable`. They accept the
> existing system globals, reject identity and timestamp globals, and emit no
> success record in human, JSON, or quiet mode. Repeating either command is a
> successful no-op. The corresponding class operation is
> `TautClient.set_debug_capture(enabled: bool, *, db_path=None) -> None`.

#### [TAUT-13.2] Capture event and containment boundary

> A debug event is an `Exception` that reaches a named Taut-owned outermost
> containment point before that boundary converts it to a CLI exit, TUI fatal
> exit, MCP workspace crash, or standalone Summon process failure. Exceptions
> already converted to normal domain, tool, worker, or recoverable UI results
> below that point are handled outcomes and are not debug events.
> `KeyboardInterrupt`, `SystemExit`, cancellation implemented outside
> `Exception`, and other direct `BaseException` subclasses are not captured.
> The boundary calls the core handler before rendering or discarding the
> exception and otherwise preserves its existing behavior. The handler reads
> the setting from durable state on every call not suppressed by the inherited
> action-descendant loop marker; long-running processes do not cache it.

#### [TAUT-13.3] Local event and deduplication

> The local sink writes one UTF-8 JSON object to the core-owned, unregistered,
> reserved queue `taut.debug`. The version-1 event contains a type and version,
> UTC capture time, display-safe target, stable surface and operation labels,
> exception type and message, formatted traceback, bounded frame locals,
> bounded runtime/process metadata, a deterministic SHA-256 fingerprint, and
> the literal sentinel `taut-debug:<fingerprint>`. It may contain credentials,
> message bodies, paths, prompts, tokens, and other sensitive process data.
> Its schema is exceptional diagnostic data, not a compatibility API; later
> readers must tolerate added, removed, truncated, or changed metadata.
>
> Before a local write, the handler searches `taut.debug` for the exact
> sentinel with the public literal-substring search, limit one, including
> claimed rows. A retained match skips the write. A process-local lock closes
> the same-process search/write race. Search failure still attempts the write.
> Cross-process search/write remains non-atomic and duplicate events are
> permitted. Deduplication lasts only while a matching message is retained:
> `peek` preserves it; `read` claims it, and claimed inclusion continues to
> suppress a duplicate while that row is retained. Explicit deletion or broker
> vacuum of the claimed row permits later capture. Users manage the queue only
> through ordinary SimpleBroker commands.

#### [TAUT-13.4] Action sink

> Presence of `TAUT_DEBUG_ACTION`, including an empty or malformed value,
> replaces local storage for that event. Taut parses the string into an argv
> with one documented POSIX-style quoting grammar on every platform and
> without a shell. It runs the argv with inherited environment and working
> directory, adds the internal `TAUT_DEBUG_ACTION_ACTIVE=1` loop marker, sends
> the event plus one newline on stdin, suppresses stdout and stderr, and
> requests termination after two seconds. A handler that inherits that marker
> returns without capture, preventing a failing action or its descendants from
> recursively invoking the action. Parse, spawn, write, timeout, termination,
> signal, and nonzero-exit failures are ignored. There is no local fallback.
> Core does not search or deduplicate an action-owned destination; the payload
> fingerprint and sentinel let the action do so if desired.
> `TAUT_DEBUG_ACTION` is separate from the existing `TAUT_DEBUG` translation to
> SimpleBroker `BROKER_DEBUG`.

#### [TAUT-13.5] Best-effort and lifecycle contract

> Event construction, local representation, target resolution, setting read,
> queue search/write/close, action execution, and debug cleanup never raise to
> the caller and never replace the original failure. Action execution requests
> termination after the fixed timeout, then permits only the operating
> system's child-termination wait. Debug state is operational, not logical workspace
> content. The setting and `taut.debug` messages are omitted from Taut logical
> dump/load. A raw SimpleBroker dump remains outside that projection and may
> include the unregistered queue. Captured events persist until an operator
> reads or deletes them; Taut adds no retention, export, repair, or report
> management command.

#### [TAUT-13.6] Verification

> Tests use real SQLite sidecar metadata and real SimpleBroker queues for
> setting reads, local writes, literal search, claimed-row search, retention,
> and handle closure. Action tests run a real fixture executable and inspect its
> stdin and exit behavior. Boundary tests prove the original exception result
> and diagnostic with capture disabled, enabled, and failing. Fakes may control
> time, process metadata, and local-value representation, but may not replace
> the state read, queue search/write, subprocess transport, or outer boundary
> under test.

Amend [TAUT-3.2] so `TAUT_DEBUG_ACTION` and the internal descendant loop marker
are named as Taut-owned operational inputs outside the closed
Taut-to-SimpleBroker configuration translation. State explicitly that existing
`TAUT_DEBUG` continues to translate only to `BROKER_DEBUG` and does not enable
failure capture.

Add “Debug failure capture” with canonical section `[TAUT-13]` to
`docs/specs/product-section-registry.md`.

### Queue namespace

Amend [IAN-6.1] to list `taut.debug` as a core-owned, unregistered system queue
under the reserved `taut.*` namespace. It is never a channel, thread, inbox, or
search-work queue and is not exposed by Taut chat enumeration.

### Persistence

Amend [PIO-5.1], [PIO-5.2], and [PIO-5.4] so `debug_capture` is a recognized
core operational metadata key rather than extension-owned durable state, and
so `taut.debug` is excluded from the Taut logical broker projection because it
is unregistered operational data.

Amend [PIO-7.2] and [PIO-7.3] with this exact destination rule:

> The absent or valid `debug_capture` operational key does not make an
> otherwise fresh destination non-fresh. Load neither imports nor changes it.
> A destination therefore preserves its pre-load debug setting. Malformed
> values fail eligibility. Any retained `taut.debug` message is still a broker
> message and makes the destination non-fresh; the operator must consume,
> delete, or replace the target before retrying.

Add [PIO-11] firing cases for source omission, destination preservation,
malformed metadata, retained debug messages, and the distinction between Taut
logical dump and raw SimpleBroker dump.

### Doctor

Change [DOCT-3] and [DOCT-4] from six to seven fixed checks. Append, without
renumbering existing checks:

#### [DOCT-4.7] `debug_capture`

> Read `debug_capture` from the already-open core metadata snapshot. Absent is
> disabled and passes. Exact `1` is enabled and passes. Any other stored value
> fails. The sink is `disabled` when off, `local` when enabled and
> `TAUT_DEBUG_ACTION` is absent, and `action` when enabled and the environment
> variable is present. Doctor never emits or validates the action string and
> never opens `taut.debug`.
>
> `{"enabled": false, "sink": "disabled"}`
>
> `enabled` is `bool | null`; `sink` is
> `"disabled" | "local" | "action" | null`. Both are null on prerequisite
> skip or malformed stored state.
>
> The reported sink reflects the doctor process's environment at observation
> time. It is advisory for a TUI, MCP server, Summon process, or other process
> whose environment can differ.

Update [DOCT-4.5] so extension-state ownership ignores the recognized core
operational key. Add exact order, output-line, JSON-shape, skip, malformed, and
non-mutation cases to [DOCT-7]. Enabled capture is operational state, not a
health finding.

### TUI, MCP, and Summon containment points

Amend [TUI-12.1] and [TUI-13] to state that an `Exception` raised from
`TautApp.run()` is captured by core command dispatch when enabled. Textual
8.2.8 consumes fatal callback exceptions, retains the first exception on the
completed app, renders its own rich fatal output, and returns. The launch
adapter therefore calls the core handler once for that retained exception
after `run()` returns. Recoverable action, worker, controller, and presentation
failures that remain below Textual's fatal handling keep their existing UI
treatment and are not recaptured. Capture preserves Textual's fatal output,
terminal restoration, and return result.

Amend [MCP-8], [MCP-11], and [MCP-12] so each workspace-reactor path that
converts an unexpected `Exception` into `WorkspaceCrashed` first calls the core
handler when a resolved target/config pair is available. Resolution failures
before that pair exists and process-fatal failures with no single workspace
remain uncaptured. The event stays content-free and protocol behavior does not
change.

Amend [SUM-3], [SUM-11], and [SUM-12] so the installed `taut summon` path relies
on the core dispatch boundary, while the standalone `taut-summon` process calls
the same handler only for an unexpected `Exception` escaping its existing
handled-error paths. Driver cleanup and re-raise order stay unchanged; do not
capture again inside the driver or its expected supervised failure paths.

Add this plan to Related Plans in every active spec changed by the promotion.

## Current Structure and Key Files

- `taut/commands/system.py` owns the actor-free nested `system` grammar and
  currently has `dump`, `load`, and `doctor` operations.
- `taut/client/__init__.py` owns actor-free class operations. Command semantics
  should enter through a class method, not write sidecar SQL from the adapter.
- `taut/_maintenance.py` resolves an existing target without accidentally
  creating SQLite state.
- `taut/state/_sql.py` owns `taut_meta`, current schema/load-guard keys, passive
  metadata reads, and atomic load-guard eligibility.
- `taut/persistence/_operations.py` subtracts `schema_version` after its earlier
  load-guard refusal, then treats the remaining metadata keys as
  extension-owned; it also treats every broker message as load non-freshness.
  Both decisions must learn the exact operational-key exception.
- `taut/_doctor.py` consumes one metadata snapshot and currently builds six
  fixed checks. It must not open the debug queue or execute the action.
- `taut/commands/_dispatch.py` contains the core command-load and command-run
  outer boundaries. It already owns concise diagnostics and exit mapping.
- `extensions/taut_tui/taut_tui/_launch.py` calls `app.run()`. Exceptions
  raised from that call reach core dispatch. Textual 8.2.8 instead retains a
  fatal callback exception and returns, so the launch adapter must inspect that
  first retained exception after return and pass it to the core handler once.
- `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` has several explicit
  `WorkspaceCrashed` conversion points plus one top-level reactor catch. It
  already owns a resolved `BrokerTarget` and `ResolvedConfig` after bootstrap.
- `extensions/taut_mcp/taut_mcp/cli.py` has no single workspace at the
  process-fatal boundary; do not guess which workspace setting should apply.
- `extensions/taut_summon/taut_summon/cli.py` owns the standalone console. Its
  unexpected exceptions currently re-raise; expected command/policy failures
  are already handled.
- `taut/_constants.py` already maps `TAUT_DEBUG` to SimpleBroker
  `BROKER_DEBUG`. That contract must remain untouched.
- The `simplebroker>=7.3.2` project floor currently resolves to SimpleBroker
  7.3.2 in `uv.lock`, which exposes
  `Queue.find_message_ids(*, body_contains, limit=100,
  after_timestamp=None, before_timestamp=None, include_claimed=False)` and
  documents literal substring matching. This is the dedup seam; there is no
  new queue-search abstraction to invent.

Implement the deep core module as `taut/debug.py`. Its small public first-party
extension seam should contain:

```python
capture_exception(
    exc: Exception,
    *,
    surface: str,
    operation: str,
    db_path: str | Path | None = None,
    broker_target: BrokerTarget | None = None,
    broker_config: ResolvedConfig | None = None,
) -> None
```

Ambient/path mode and resolved mode are mutually exclusive. Resolved mode
requires both target and config. Invalid targeting, event construction, and
all sink work are contained inside the function and return `None`. Do not add
public sink classes, adapter registries, callback hooks, or a generic exception
framework.

`TautClient.set_debug_capture()` is the setting operation. Internal status
reading may live in `taut/debug.py` or the state module, but sidecar SQL remains
owned by `taut/state/_sql.py` and must work through the current dialect/session
abstraction on SQLite and PostgreSQL.

## Required Comprehension Checks

Before editing code, record answers in the Implementation Log:

1. Why is `TAUT_DEBUG` not the enable switch? Expected: it already maps to
   SimpleBroker `BROKER_DEBUG`; repurposing it would change an existing config
   contract. Capture enablement is durable `debug_capture` metadata.
2. Which failures become events? Expected: an `Exception` reaching one of the
   named outer containment points. Expected errors already converted below the
   point are not events; direct non-`Exception` `BaseException` values are not
   events.
3. Why does MCP need resolved-target mode? Expected: a resident MCP workspace
   has frozen backend target/config state that may be PostgreSQL; re-resolving
   from a path or ambient process state can select the wrong workspace.
4. Why is local dedup not exactly-once? Expected: public substring search and
   write are separate broker calls. A process lock closes only same-process
   races; cross-process duplicates remain possible and accepted.
5. What ends the dedup window? Expected: removing the retained matching row
   with explicit delete or broker vacuum. `peek` preserves a pending row;
   `read` claims it, and claimed inclusion continues to preserve a match until
   removal.
6. What happens when `TAUT_DEBUG_ACTION` fails? Expected: the event is lost;
   there is no local fallback, no diagnostic, and no change to the original
   failure.
7. How do dump/load treat the setting and reports? Expected: neither is loaded
   from Taut logical dump. A destination keeps its existing valid setting, but
   retained debug queue messages make it non-fresh.
8. What is the downgrade sequence? Expected: disable debug with the newer Taut
   version before installing an older version, because old dump/doctor code
   treats the operational metadata key as unknown.

Wrong, uncertain, or unrecorded answers block implementation until the sources
are reread and the log is corrected.

## Locked Design

### Operational setting

- constant key: `debug_capture`
- disabled representation: key absent
- enabled representation: exact string `1`
- malformed representation: key present with any other value
- enable: portable update-or-insert in one sidecar transaction
- disable: portable idempotent delete in one sidecar transaction
- setting reads never initialize or migrate schema
- `set_debug_capture` requires an existing initialized current-version target
  and exact `bool`; malformed target state fails normally at the setting
  command, not through the best-effort capture path

### Event construction

Version 1 uses one JSON object with these conceptual fields:

| Field | Purpose |
|---|---|
| `type`, `version` | identify `taut_debug_event` and payload version 1 |
| `fingerprint`, `sentinel` | deterministic retained-event identity and literal search marker |
| `captured_at` | UTC event time |
| `surface`, `operation` | stable containment location supplied by the caller |
| `target` | display-safe workspace target when resolution succeeded |
| `exception` | qualified type and bounded message |
| `traceback` | formatted exception chain and stack |
| `frames` | ordered frame file, line, function, and bounded local representations |
| `runtime` | Taut, Python, platform, process, and thread metadata available without new I/O |
| `truncated` | whether any bounded field was reduced or omitted |

The fingerprint hashes canonical JSON containing the qualified exception type,
bounded exception message, and ordered traceback frame file/function/line
identity. It excludes capture time, process ID, thread ID, target, surface
metadata, and local values. This makes repeated instances of the same observed
failure stable while avoiding unstable runtime details. Path normalization and
the exact size constants are implementation policy, not payload compatibility
promises, but they must be deterministic and tested.

Use finite constants for frame count, per-local representation, exception
message, traceback text, and final encoded event size. Preserve type, version,
fingerprint, sentinel, surface, operation, and exception type if truncation is
required. Mark truncation rather than silently producing invalid JSON. Local
`repr()` failure becomes a bounded placeholder. Do not introspect object
attributes, call serializers supplied by local values, or attempt secret
redaction that would make an unreliable safety promise.

### Local sink

1. Build the complete event before opening the queue.
2. Acquire one process-local capture lock.
3. Open `Queue("taut.debug", db_path=target, config=config)`.
4. Search for the exact sentinel with `limit=1` and
   `include_claimed=True`.
5. If a match exists, close and return.
6. If search fails, continue to write.
7. Write the canonical compact JSON plus no extra envelope.
8. Close on every path; swallow search, write, and close failures.

The lock must not cover action execution and must not become a cross-process
lock file. Taut creates no new daemon, cache, state directory, retry queue, or
cleanup worker.

### Action sink

Use `shlex.split(action, posix=True)` on every platform and document that the
value uses POSIX-style token quoting even on Windows. Pass the resulting argv
list to `subprocess.run()` with `shell=False`, event JSON plus newline as text
stdin, inherited cwd and environment plus `TAUT_DEBUG_ACTION_ACTIVE=1`,
stdout/stderr to `DEVNULL`, and a fixed two-second timeout. Python's subprocess
layer owns conversion of that argv list to the Windows process command line;
do not use non-POSIX `shlex`, which retains quote characters in tokens.
Operator documentation must tell Windows users to quote paths containing
backslashes or spaces under this grammar; an unquoted backslash is an escape.

Presence is tested separately from truthiness so an empty value selects the
action path and fails closed without a local write. Before state resolution or
event construction, presence of `TAUT_DEBUG_ACTION_ACTIVE` makes the handler
return `None` without local fallback or another action invocation. The useful
SimpleBroker form is:

```bash
TAUT_DEBUG_ACTION='broker -f /path/to/.broker.db write debug_action -'
```

Do not interpolate the event into argv or invoke a shell. Do not inspect action
stdout. After two seconds, request termination and accept the operating
system's finite child-termination wait rather than claiming a literal absolute
two-second return bound. Do not recursively capture action or descendant
failure.

### Named containment points

| Surface | Boundary | Operation label rule |
|---|---|---|
| core CLI, including `taut tui` and installed `taut summon` | command load/run/cleanup catches in `taut/commands/_dispatch.py` | `command.load:<verb>`, `command.run:<verb>`, or `command.cleanup:<verb>` |
| TUI | core dispatch when `TautApp.run()` raises; launch bridge when Textual retains a fatal callback and returns | `command.run:tui` for raised launch failures; `tui.fatal` for retained callbacks; mutually exclusive paths |
| MCP workspace | each `_workspace_reactor.py` branch that emits `WorkspaceCrashed` from an `Exception`, including the outer run catch | stable phase such as `workspace.command:<tool>`, `workspace.refresh`, `workspace.snapshot`, or `workspace.run` |
| standalone Summon | outer `taut-summon` unexpected-`Exception` re-raise path | `summon.<subcommand>` |

At a catch that currently receives `BaseException`, call capture only after
`isinstance(exc, Exception)`. Preserve existing `KeyboardInterrupt`, terminal
policy, broken-pipe, cancellation, cleanup, and primary-error rules. If cleanup
also fails after a primary failure, capture the primary once; capture cleanup
only when it becomes the rendered primary result.

## Invariants and Constraints

- Disabled is the default and performs no queue or subprocess work.
- The setting is workspace operational state, not user identity, chat state,
  extension state, or a process-global preference.
- Long-running processes read the setting at event time. No watcher, cache,
  polling loop, or process restart is required after enable or disable.
- `TAUT_DEBUG_ACTION` does nothing while the persisted setting is disabled.
- The handler never raises and does not log its own failure.
- Original exception identity, cause/context chain, exit class, MCP event,
  stderr text, TUI terminal restoration, and Summon cleanup priority stay
  unchanged.
- Expected failures that a surface already represents below its outer boundary
  remain expected results and are not recaptured.
- Core CLI exceptions that reach its generic outer command boundary are events
  even when their final concise diagnostic is a domain error. This broad rule
  is deliberate and may produce noisy debug queues.
- `taut.debug` remains unregistered and reserved. It cannot appear as a Taut
  channel, direct message, notification inbox, persistence thread, or search
  queue.
- Taut adds no `debug list`, `debug read`, `debug clear`, export, retention,
  aggregation, or upload operation.
- Payload contents are explicitly sensitive and unredacted. Debug enablement is
  an operator choice inside Taut's existing storage trust domain, not a safety
  guarantee.
- Payload schema evolution is allowed, but every event remains valid UTF-8 JSON
  and retains a type, version, fingerprint, sentinel, and truncation signal.
- Local dedup is best effort, retention-scoped, and at-least-one-attempt rather
  than exactly-once. Search failure favors preservation by attempting a write.
- Action mode has no core-owned durable dedup and no local fallback.
- No schema-version bump is needed because the new value is a recognized row in
  the existing key/value table and absence remains valid.
- No new dependency is added. Use the standard library and the public
  SimpleBroker API available at the `>=7.3.2` floor and current locked
  resolution.
- Public setting and capture APIs must support SQLite and PostgreSQL through
  existing target/config and sidecar abstractions.

## Hidden Couplings and Failure Modes

- Old Taut versions interpret `debug_capture` as unknown extension metadata.
  They may fail doctor or dump after a downgrade even though ordinary chat
  operations still work.
- Textual 8.2.8 renders its rich traceback, stores the first fatal callback
  exception on the app, and returns from `app.run()` without raising. The
  launch bridge inspects only that retained first exception after return. It
  does not catch widget events or change framework rendering. A compatibility
  test locks this integration seam; a future Textual change may reduce
  best-effort capture but must not make launch fail.
- MCP deliberately strips exception content from `WorkspaceCrashed`. Capture
  must happen before that conversion while retaining the content-free event.
- MCP resolution failure may occur before a workspace target exists. Core
  cannot read a workspace flag and must skip capture rather than use ambient
  process configuration.
- The SimpleBroker literal search and write are separate transactions. Another
  process can write the same sentinel between them; duplicate retention is
  accepted.
- A claimed matching event must still suppress a duplicate. Omitting
  `include_claimed=True` shortens the dedup window unexpectedly.
- Reading a debug event claims it. Because dedup includes claimed rows, later
  recurrence remains suppressed until explicit deletion or broker vacuum;
  tests must cover both claimed retention and post-removal recurrence.
- A local value's `repr()` can raise, recurse, be slow, or expose secrets.
  Bound and contain it, but do not claim a hard execution-time limit beyond the
  action subprocess timeout.
- The action receives a potentially large sensitive event and inherits the
  current environment and cwd, with one added loop marker. That is
  operator-authorized executable code.
- An action can invoke Taut directly or indirectly. Without a descendant
  marker, each failing generation could spawn another before its parent times
  out, and parent termination could orphan descendants. The inherited
  `TAUT_DEBUG_ACTION_ACTIVE` marker makes every descendant handler return
  without capture and breaks that chain. It is an internal safety guard, not a
  durable setting or a public sink-selection input.
- Queue write may succeed and close may fail. Retrying can duplicate; the next
  sentinel search normally suppresses it. Do not delete on ambiguous failure.
- Doctor must distinguish recognized malformed operational metadata from an
  unknown extension key. Otherwise the new check and `extension_state` produce
  contradictory or duplicate findings.
- Load must preserve a destination setting without importing a source setting.
  Passing the key through either logical records or the load guard would violate
  that asymmetry.
- Raw `broker dump` covers all broker queues and may retain debug events. The
  Taut logical dump exclusion must not be described as a SimpleBroker guarantee.

## Rollout, Rollback, Retention, and One-Way Doors

Roll out the core/spec/persistence/doctor/CLI changes atomically before relying
on extension calls. First-party extension releases that import `taut.debug`
must retain their existing compatible core floor or raise it to the first core
release containing that module. Do not ship an extension that imports the seam
against an older compatible-core declaration.

The core retains the existing `simplebroker>=7.3.2` dependency floor because
that version supplies the required public search signature on SQLite and the
paired PostgreSQL plugin. Verify the locked release candidate still satisfies
the literal-substring and `include_claimed` contract; do not add a new upper
bound solely for debug capture.

The setting is additive and absence-compatible in new code. There is no sidecar
table migration and no irreversible data transform. The retained event queue is
ordinary SimpleBroker data and can be inspected or deleted independently.

Rollback has one required sequence:

1. With the new version still installed, run `taut system debug disable` for
   every enabled workspace.
2. Then install the older version.

If rollback happened first, reinstall the new version to disable before using
old doctor or dump. The plan does not authorize ad hoc SQL deletion as the
normal recovery. Retained `taut.debug` messages may remain because older Taut
does not register or inspect that queue; operators may remove them with broker
commands when no longer needed.

Captured data is the one durable lifecycle effect. It may contain secrets and
persists until consumed or deleted. Enable only for the diagnostic interval,
inspect with owner-appropriate storage permissions, disable afterward, and
remove retained events when they are no longer needed. The action destination
owns its own access, retention, backup, and deletion policy.

Post-release success signals are:

- doctor reports the exact setting and selected sink without exposing the
  action string
- an induced outer-boundary fixture failure leaves its ordinary output/exit
  unchanged and creates one readable local event when enabled
- repeated capture while that event is retained does not add another row in a
  single process
- the same fixture reaches an action-owned SimpleBroker database when the
  sample command is configured and leaves no local row
- disabled workspaces show no queue or subprocess activity
- dump/load and existing TUI, MCP, and Summon failure suites remain green

## Dependency-Ordered Tasks

### Task 1: Review and accept the contract

Read first:

- this plan, especially Proposed Spec Delta, Locked Design, and rollback
- all active spec sections named in Source Documents
- the current files named in Current Structure and Key Files

Actions:

1. Run the independent plan review required by [DOM-11].
2. Disposition every finding in the append-only Review Log.
3. Obtain maintainer acceptance of the operational key, broad outer-boundary
   event definition, sensitive unredacted payload, action replacement/no
   fallback rule, retention-scoped dedup, and rollback sequence.
4. Record the comprehension answers before implementation starts.

Stop gate: any unresolved disagreement about what counts as a debug event, who
owns the setting, whether action replaces local storage, or how rollback works
blocks spec promotion.

Done signal: the plan review verdict is PASS, every finding is dispositioned,
and the owner has accepted the normative delta.

### Task 2: Promote the active specifications

Files:

- `docs/specs/02-taut-core.md`
- `docs/specs/03-identity-addressing-notifications.md`
- `docs/specs/04-summon.md`
- `docs/specs/05-taut-mcp.md`
- `docs/specs/08-persistence-io.md`
- `docs/specs/09-system-doctor.md`
- `docs/specs/10-taut-tui.md`
- `docs/specs/product-section-registry.md`
- `tests/test_cli_claims.py`

Actions:

1. Compare each active section with the recorded baseline.
2. Apply the accepted exact delta and plan backlinks.
3. Add only the one exact source/path normalized future CLI exemption needed
   during the red phase.
4. Run reference, CLI-claim, and diff gates.
5. Record the promotion baseline and any wording adjustment in the Deviation
   Log before behavior work.

Stop gate: any stable-reference collision, stale CLI exemption, or semantic
wording change that was not reviewed returns to Task 1.

Done signal: active specs are one unambiguous red-test authority and all doc
gates pass with the temporary normalized exemption named.

### Task 3: Add red tests for operational state and commands

Files:

- new `tests/test_debug_capture.py`
- `tests/test_system_doctor.py`
- `tests/test_persistence_io.py`
- `tests/test_persistence_io_adversarial.py`
- `tests/test_command_registry.py`
- existing CLI dispatch tests selected by the implementer
- shared PostgreSQL persistence/state conformance tests

Actions:

1. Add actor-free class-operation and CLI cases for absent, enable, repeated
   enable, disable, repeated disable, enable repairing a malformed value,
   disable removing a malformed value, missing target, and SQLite/PostgreSQL
   parity.
2. Prove success is silent in human, JSON, and quiet modes; globals work before
   and after `system`; identity/timestamp/extra/unknown arguments fail before
   mutation.
3. Extend doctor to the exact seven-check inventory and all `debug_capture`
   pass/fail/skip data shapes and line counts.
4. Add dump/load cases for source omission, destination preservation,
   malformed key refusal, retained local event non-freshness, and raw broker
   versus Taut logical projection.
5. Add a tripwire proving `TAUT_DEBUG` does not toggle capture and
   `TAUT_DEBUG_ACTION` does not act while disabled.

Red gate: run the focused state/command command in Testing Plan and record the
expected failures against the baseline. If the tests pass without the feature,
strengthen them before implementation.

Done signal: failures isolate absent state APIs, grammar, seventh doctor check,
and persistence exceptions without unrelated regressions.

### Task 4: Implement operational state, command, doctor, and persistence rules

Files:

- `taut/state/_sql.py`
- `taut/state/__init__.py`
- `taut/debug.py`
- `taut/client/__init__.py`
- `taut/commands/system.py`
- `taut/_doctor.py`
- `taut/persistence/_operations.py`
- `tests/test_cli_claims.py`

Actions:

1. Add state-owned read/write/delete helpers for `debug_capture` using portable
   sidecar sessions.
2. Add `TautClient.set_debug_capture()` and the exact nested command grammar.
3. Add the seventh doctor check from the existing metadata snapshot and exempt
   only this recognized key from extension ownership. Update the system parser
   help from six to seven checks and sweep active specs, implementation docs,
   help, and tests for other fixed-count claims.
4. Teach dump selection and load guard/eligibility the exact operational-key
   asymmetry. Update both different baseline sets: dump's post-guard
   `schema_version` subtraction in `taut/persistence/_operations.py` and
   doctor's `schema_version`/`load_guard` subtraction in `taut/_doctor.py`.
   Do not omit arbitrary unknown core metadata.
5. Remove the temporary CLI-claim exemption as soon as the grammar exists.
6. Make Task 3 green on SQLite and the shared PostgreSQL contract.

Stop gate: implementation introduces backend-specific production SQL, creates
a target during a read, imports the setting through dump/load, or turns unknown
metadata into an allowed class.

Done signal: exact setting, command, doctor, and persistence tests pass with no
future exemption remaining.

### Task 5: Add red tests for event construction and sinks

Files:

- `tests/test_debug_capture.py`
- one small executable fixture under `tests/fixtures/` for action stdin and
  exit/timeout behavior

Actions:

1. Cover exact required fields, canonical valid JSON, deterministic fingerprint
   inputs, changed stack/message behavior, exception chaining, local frame
   order, locals, repr failure, and every truncation marker.
2. With real SimpleBroker, cover first write, retained duplicate, claimed
   duplicate, deletion then recurrence, search failure followed by write, write
   failure containment, close failure containment, and same-process concurrent
   calls.
3. With a real fixture process, cover argv parsing, stdin newline, inherited
   environment/cwd, suppressed output, success, nonzero, missing executable,
   malformed/empty string, timeout, descendant loop suppression, and no local
   fallback. Add a Windows-marked case proving a quoted executable path with
   spaces becomes an unquoted `argv[0]` and reaches the fixture.
4. Prove malformed setting, resolution failure, event-format failure, and every
   sink failure return `None` without raising.
5. Prove the event and action command string are not emitted to Taut stderr or
   doctor output.

Red gate: focused tests fail because the handler and sink behavior do not yet
exist, not because the fixture cannot execute on a supported platform.

Done signal: the red matrix isolates event, local sink, dedup, and action
requirements.

### Task 6: Implement the deep core capture module

Files:

- `taut/debug.py`
- state exports only where Task 4 did not already add them

Actions:

1. Implement the target-mode validation, current setting read, event builder,
   deterministic bounds, fingerprint/sentinel, and no-raise wrapper.
2. Implement local search/write under one process lock with real
   `Queue.find_message_ids()` and `include_claimed=True`.
3. Implement the no-shell two-second action transport with no fallback.
4. Keep public surface to the one capture function and setting class method.
5. Make Task 5 green without mocking state, queue, or subprocess boundaries.

Stop gate: callers must choose a sink, know queue details, serialize events,
perform dedup, or catch capture errors; or the handler can re-raise.

Done signal: all pure and real-boundary capture tests pass with the module as
the sole policy owner.

### Task 7: Integrate core CLI and prove the motivating TUI path

Files:

- `taut/commands/_dispatch.py`
- core dispatch tests
- `extensions/taut_tui/tests/test_tui_launch.py`
- TUI files only if a real test proves Textual consumes fatal exceptions before
  the existing boundary

Actions:

1. Call capture for command-load, command-run, and primary cleanup
   `Exception`s at the existing boundaries.
2. Preserve terminal-policy, interruption, SystemExit, broken-pipe, primary
   versus cleanup, quiet, and exit-code behavior byte for byte.
3. Use a synthetic failing command fixture to prove disabled, enabled,
   duplicate, local-sink failure, and action-sink failure paths.
4. Run a real Textual failing-app test modeled on a callback exception and
   prove Textual retains it after `run()` returns. Pass that retained exception
   through one launch bridge to the core handler, retain useful frame locals,
   and preserve the TUI's existing fatal/terminal behavior.
5. Prove an exception actually raised from `run()` bypasses the post-return
   bridge and remains owned once by core dispatch. Do not catch every widget
   event or override Textual's fatal renderer.

Stop gate: any path renders twice, changes an exit class, captures a direct
`BaseException`, or adds a second TUI policy owner.

Done signal: the ordinary CLI, raised TUI launch path, and retained Textual
callback path each produce one event only when enabled and preserve all
existing failure evidence.

### Task 8: Integrate MCP workspace failure conversion

Files:

- `extensions/taut_mcp/taut_mcp/_workspace_reactor.py`
- `extensions/taut_mcp/tests/test_process_reactor.py`
- other MCP tests only where an existing crash matrix owns the path

Actions:

1. Route every unexpected-`Exception` `WorkspaceCrashed` conversion through one
   reactor helper that calls core capture with the frozen target/config pair.
2. Keep identity loss, normal tool errors, cancellation, resolution failures,
   and process-fatal no-workspace paths unchanged and uncaptured.
3. Prove command, refresh, snapshot, and outer-loop crash labels; one capture;
   content-free `WorkspaceCrashed`; cleanup; disable-after-attach and
   enable-after-attach behavior without reactor restart.
4. Use real reactor threads, SQLite queues, and command outcomes. Do not replace
   the reactor or capture setting with a mock.

Stop gate: the reactor re-resolves ambient workspace state, includes debug
content in MCP events, or changes parent lifecycle/tombstone semantics.

Done signal: the MCP crash matrix and full MCP suite pass with dynamic setting
reads and unchanged protocol output.

### Task 9: Integrate standalone Summon failure propagation

Files:

- `extensions/taut_summon/taut_summon/cli.py`
- `extensions/taut_summon/tests/test_summon_cli.py`
- driver tests only as regression proof; do not add capture to the driver

Actions:

1. At the standalone outer boundary, capture an unexpected `Exception` with
   the parsed command and database selector, then re-raise the same object.
2. Preserve expected `CommandError`, policy error, nothing-summoned,
   unresponsive-driver, signal, and cleanup behavior.
3. Prove the installed `taut summon` route is captured only by core dispatch
   and does not double-write.
4. Prove driver-internal supervised provider, watcher, control, and teardown
   outcomes are not promoted to debug events merely because they are failures.

Stop gate: a known Summon outcome becomes a traceback/debug event, the same
exception writes twice, or capture alters signal/cleanup ownership.

Done signal: standalone and installed Summon failure matrices pass with one
outer owner each.

### Task 10: Align implementation documentation and close verification

Files:

- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/implementation/11-system-doctor.md`
- `docs/implementation/12-taut-tui.md`
- this plan and `docs/plans/README.md`
- user-facing README/help text only if the accepted contract calls for it

Actions:

1. Document why `taut/debug.py` is deep, why the setting is operational
   metadata, where each outer boundary lives, and why dedup remains
   retention-scoped and non-atomic.
2. Document sensitive-data retention, broker inspection commands, action stdin
   usage, no-fallback semantics, Windows action-path quoting, and downgrade
   sequence without claiming a stable payload schema.
3. Update doctor from six to seven checks and repository ownership maps.
4. Run one independent review after the core green slice, one after extension
   integration, and one final integrated review.
5. Record red/green evidence, full gates, review dispositions, changed files,
   residual risks, and authorized commits.
6. Mark the plan completed only when the final finished slice is committed with
   owner authorization and verified through `git log`.

Stop gate: spec, implementation docs, help, code, and tests disagree on setting
ownership, event boundaries, sink selection, retention, or rollback.

Done signal: every completion gate below is met and repository history proves
the authorized finished commits.

## Testing Plan

Red-green TDD is required. No substitute-proof exception is planned.

### State, command, doctor, and persistence matrix

Every enumerable element below needs a firing test:

- metadata: absent, exact `1`, empty, `0`, whitespace, and another unknown key
- command: enable/enable, disable/disable, missing target, malformed core
  schema, before/after globals, human/JSON/quiet silence, identity/timestamp
  rejection, missing operation, extra argument, and unknown operation
- doctor: exact seven names/order, pass enabled local, pass enabled action,
  pass disabled, malformed fail, core prerequisite skip, exact data keys,
  human lines, aggregate JSON, healthy state, and no queue/action side effect
- persistence: source setting omitted, source debug messages omitted,
  destination setting absent/preserved enabled/preserved disabled, malformed
  refusal, retained pending/claimed debug message refusal, raw broker dump
  inclusion, and load guard cleanup
- backend: shared real SQLite and PostgreSQL state/persistence cases

### Event and sink matrix

- exception: simple, chained cause, chained context, empty message, multiline
  message, Unicode, deep stack, too many frames, large traceback, large locals,
  recursive repr, repr exception, and no traceback object
- fingerprint: identical event, changed type, changed bounded message, changed
  frame, and unstable runtime/local values excluded
- local: first write, pending match, claimed match, consumed recurrence, deleted
  recurrence, search error then write, write error, close error, and same-process
  concurrent repeats
- action: unset, empty, malformed quoting, missing program, stdin success,
  nonzero, timeout, signal termination, stdout/stderr suppression, sensitive
  argv non-interpolation, quoted Windows executable path, descendant marker,
  indirect recursive action suppression, and no local fallback
- enable timing: disabled, enabled, disable after process start, enable after
  process start, malformed setting, and setting-read failure

### Boundary matrix

- core command load, execution, and cleanup primary failure
- primary plus cleanup failure with primary captured once
- usage/SystemExit, `KeyboardInterrupt`, direct `BaseException`, terminal policy,
  and broken pipe exclusions
- real Textual fatal callback retention, post-run bridge, and terminal restoration
- MCP command, refresh, snapshot, and outer-loop crash; pre-resolution and
  process-fatal exclusion
- standalone Summon unexpected exception; handled command/policy/domain cases;
  installed-command single capture
- capture disabled, local enabled, action enabled, capture-internal failure, and
  exact original exit/event/diagnostic comparison at each boundary

### Anti-mocking rules

Do not mock:

- the `taut_meta` setting read/write under test
- SimpleBroker `Queue.find_message_ids`, write, claim visibility, read/delete,
  or close in integration tests
- action stdin transport in acceptance tests
- command dispatch, Textual app runner, MCP reactor thread/event conversion, or
  Summon outer boundary in their integration tests
- dump/load freshness or doctor metadata snapshot

Narrow fakes are allowed for clocks, platform/process metadata, pathological
local `repr()`, deterministic subprocess timeout scheduling, and a synthetic
command body that raises. Fault injection may wrap a real boundary to force a
documented error, but the contract-owning state, queue, subprocess, or reactor
must remain real.

### Focused commands

The implementer may refine test names as files land, but must record the exact
commands actually run. Expected starting commands are:

```bash
uv run --locked pytest -q -n 0 \
  tests/test_debug_capture.py \
  tests/test_system_doctor.py \
  tests/test_persistence_io.py \
  tests/test_persistence_io_adversarial.py \
  tests/test_command_registry.py
```

```bash
uv run --project extensions/taut_tui --extra dev --locked pytest -q -n 0 \
  extensions/taut_tui/tests/test_tui_launch.py
uv run --project extensions/taut_mcp --extra dev --locked pytest -q -n 0 \
  extensions/taut_mcp/tests/test_process_reactor.py
uv run --project extensions/taut_summon --extra dev --locked pytest -q -n 0 \
  extensions/taut_summon/tests/test_summon_cli.py
```

Use the repository's documented PostgreSQL runner for the shared state,
persistence, and doctor cases rather than a fake dialect.

### Full package and static gates

```bash
uv run --locked pytest -q
uv run --locked ruff check taut tests
uv run --locked ruff format --check taut tests
uv run --locked mypy taut tests
```

```bash
uv run --project extensions/taut_tui --extra dev --locked pytest -q \
  extensions/taut_tui/tests
uv run --project extensions/taut_mcp --extra dev --locked pytest -q \
  extensions/taut_mcp/tests
uv run --project extensions/taut_summon --extra dev --locked pytest -q \
  extensions/taut_summon/tests
```

Run each extension's Ruff, format, and mypy commands from its `pyproject.toml`
configuration. Run the repository's prepared PostgreSQL gate before claiming
cross-backend readiness.

### Adversarial acceptance probes

Apply the relevant floors from
`docs/agent-context/runbooks/adversarial-acceptance-probes.md`:

- malformed, missing, extra, reordered, and repeated CLI arguments
- empty and whitespace action strings; POSIX-style quoting on every platform;
  quoted Windows executable paths; argv boundaries; descendant loop marker
- nonzero, signal, timeout, closed stdin, and noisy action executables
- Unicode, control characters, multiline text, huge locals, and repr failure
- queue search false negative/failure, claimed match, write ambiguity, and
  concurrent repeat
- disabled and malformed setting during a long-running process
- stdout/stderr closed or broken while the original error is rendered
- interruption and cleanup failure during an existing primary failure
- no traceback or debug metadata added to MCP protocol output

## Verification and Evidence Gates

Documentation and repository gates:

```bash
uv run bin/check-doc-paths
uv run bin/check-cli-claims
uv run bin/check-plan-status-index
uv run --locked pytest -q tests/test_docs_references.py tests/test_cli_claims.py
git diff --check
```

Record concrete observed results:

- exact changed files per slice
- focused red failures and why each proves the missing behavior
- focused and full green test counts
- SQLite and PostgreSQL results
- exact seven doctor checks and representative JSON
- representative local event with sensitive values removed from the plan log
- queue counts before first capture, repeat, peek, read/claim, delete, and recurrence
- action-owned database count and absence of a local row
- byte-for-byte or structured equality of original diagnostics, exits, MCP
  events, and cleanup outcomes with capture off versus failing capture
- proof the motivating Textual failure is retained after `App.run()` returns
  and reaches the reviewed post-run bridge exactly once
- no remaining temporary CLI exemptions
- final `git status`, `git diff --check`, and authorized commit identities from
  `git log`

Do not paste a real debug event containing locals into the plan, review prompt,
CI logs, or release notes. Use a synthetic secret-free fixture.

## Independent Review Loop

Run an independent family review at these meaningful slices:

1. this Class 5 plan before spec promotion
2. promoted spec plus red tests and the core green state/capture slice
3. integrated TUI/MCP/Summon slice
4. final complete diff and verification evidence

The reviewer must existence-check the named state, queue search, command,
doctor, dispatch, TUI, MCP, Summon, and test seams. The review brief must name
the exact baseline/delta, accepted risks, standing constraints, and pre-existing
scope fence from the repository review runbook. It must prefer removing
unnecessary machinery and provide a separate observations section.

For the plan review, explicitly accepted risks are:

- sensitive unredacted locals and traceback are retained only after operator
  opt-in
- local cross-process duplicates are possible because search plus write is not
  atomic
- action failure loses the event with no local fallback
- expected core CLI domain exceptions reaching generic dispatch may create
  noisy debug events
- payload metadata can evolve without a compatibility promise
- exceptions consumed below the named boundaries cannot be captured
- rollback requires disabling before downgrade

A reviewer may challenge whether the plan implements these decisions safely,
but should label a request to reverse an accepted product decision as an owner
scope expansion rather than an implementation blocker.

Every finding is recorded below as accepted and fixed, rejected with evidence,
or deferred with a named reopen condition. A finding that exposes ambiguity in
the event boundary, operational-key lifecycle, no-raise guarantee, or extension
release floor returns work to Task 1.

## Out of Scope

- automatic bug reporting, network upload, telemetry, crash analytics, or a
  Sentry-style service
- a Taut debug-event list/read/delete/export CLI, TUI panel, or MCP tool
- stable payload compatibility or migration across debug event versions
- encryption, redaction, field allowlists, secret detection, or claims that
  captured locals are safe to share
- automatic retention, expiry, compaction, vacuum, retry, dead-letter, or queue
  cleanup
- exactly-once cross-process deduplication or a transaction spanning search and
  write
- core-owned deduplication inside an external action destination
- capturing signals, hard exits, `os._exit`, process kills, native crashes,
  interpreter failures, or non-`Exception` cancellation
- capturing exceptions before a workspace can be resolved
- changing Textual's own rich traceback display policy
- changing existing CLI/MCP/TUI/Summon error messages or exit classes
- adding a general logging, tracing, event bus, exception-hook, or extension
  callback framework
- including debug state or events in Taut logical dump/load

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [DOM-10.1] promotion gate | Two temporary exact exemptions for `system debug enable` and `system debug disable` | One exact source-scoped exemption for normalized unresolved path `system debug` | The claim checker stops at the unknown nested operation before it can classify `enable` or `disable`; full paths can never match. The single exemption covers only the two promoted source claims and becomes stale once `debug` enters the grammar. | None; remove the temporary exemption in the command slice as planned. |
| [TUI-12.1], [TUI-13] fatal boundary | Fatal Textual callback exceptions escape `App.run()` and reach core dispatch | A real Textual 8.2.8 probe rendered the traceback, retained the first exception on the app, and returned `None`; the launch adapter must call core capture after return | The plan's explicit stop gate required evidence before adding a TUI seam. Post-return inspection preserves Textual handling and is mutually exclusive with the raised-from-`run()` dispatch path. | Promoted in [TUI-12.1] and [TUI-13.3] before TUI implementation. |
| [TAUT-13.3] read lifecycle | `broker read` was described as immediately ending dedup | SimpleBroker `read` claims the row; `include_claimed=True` intentionally keeps suppressing duplicates until explicit delete or broker vacuum removes it | The prior wording contradicted both the required claimed-row search and the real queue behavior. Retaining claimed evidence better matches the best-effort preservation goal. | Corrected [TAUT-13.3], the comprehension gate, hidden coupling, and tests before completion. |
| [TAUT-13.4] Windows argv proof | One Windows-marked real fixture executable path with spaces | A platform-neutral argv-interception test proves a quoted Windows path becomes an unquoted `argv[0]`; the separate real subprocess fixture proves spaced arguments, UTF-8 stdin, environment, cwd, timeout, output suppression, and status behavior | The parsing contract is deliberately identical on every platform. Running this assertion on every lane gives stronger grammar coverage than skipping it off Windows, while the real fixture keeps transport proof independent of platform launcher rules. | No normative change; Task 5's proof is split across two firing tests. |

Any deviation that changes event eligibility, state ownership, sink selection,
payload minimums, dedup semantics, failure containment, rollout, rollback, or
test realism requires plan and spec review before implementation continues.

## Review Log

| Date | Reviewer | Scope | Findings and disposition |
|---|---|---|---|
| 2026-08-14 | Author fresh-eyes pass | Current code/spec seams, persistence lifecycle, deep-module boundary, test realism, and rollback | No blocker found before independent review. The pass made downgrade ordering explicit, separated Taut logical dump from raw SimpleBroker dump, required resolved target/config for MCP, and kept action failure from recursively entering local storage. Independent review remains required before promotion. |
| 2026-08-14 | Claude Fable 5, read-only plan review | Full embedded plan at `45592f0`, active specs, live state/persistence/doctor/dispatch/TUI/MCP/Summon seams, SimpleBroker API, test paths, rollout, and accepted risks | PASS. Two P2, four P3, and two nit findings were accepted and incorporated as F1-F8 below. The reviewer existence-checked every named seam and found no missing file, API, spec code, test path, or containment point. The review ran for 479 seconds with terminal reason `end_turn`, empty stderr, and no repository write. |
| 2026-08-14 | Claude Fable 5, read-only round 2 | Accepted F1-F8 fixes only | PASS for all eight fixes. Two new promotion nits were accepted: move the doctor-process advisory sentence inside the quoted [DOCT-4.7] delta and qualify [TAUT-13.2]'s every-call state read for the descendant-marker short circuit. The Windows path-quoting observation was added to operator-doc requirements. |
| 2026-08-14 | Claude Fable 5, read-only final scoped check | F9-F10 fixes and Windows operator note only | PASS. The reviewer verified the advisory remains inside the quoted [DOCT-4.7] delta, [TAUT-13.2] now matches the pre-resolution marker return, and quoted Windows backslash/space paths are consistent with the universal POSIX-style argv grammar. No new finding. |
| 2026-08-14 | Claude, read-only integrated implementation review | Current working-tree code, specs, implementation docs, real capture/state/action boundaries, CLI/TUI/MCP/Summon ownership, and focused static/test gates | PASS. No P1-P3 finding. Three nits/observations were dispositioned as I1-I3 below. The reviewer ran 84 core debug/doctor tests, persistence/registry suites, 30 TUI launch, 48 Summon CLI, 30 MCP reactor tests, lint, formatting, typing, and documentation gates without modifying the repository. |
| 2026-08-14 | Claude, read-only scoped implementation follow-up | I1-I3 fixes, [TAUT-13.3] claimed-row clarification, deviation/review/implementation logs, and documentation gates | PASS. The reviewer verified the universal Windows-style argv test plus real-process split, malformed-quote containment, disabled metadata-read note, pending/claimed retention semantics, and plan consistency. Four focused action cases and all documentation gates passed; no new finding. |

### Independent plan-review dispositions

| ID | Finding | Disposition |
|---|---|---|
| F1 [P2] | Inheriting `TAUT_DEBUG_ACTION` permits an action that indirectly invokes failing Taut to spawn an unbounded descendant chain; suppressing capture only inside the parent handler breaks direct recursion but not descendants. | Accepted. The action child inherits `TAUT_DEBUG_ACTION_ACTIVE=1`; any descendant handler seeing it returns without capture. Spec delta, locked design, hidden coupling, and real recursive-action tests now name the guard. |
| F2 [P2] | `shlex.split(..., posix=False)` retains quote characters on Windows, so a normal quoted executable path with spaces silently fails to spawn. | Accepted. The plan now specifies one POSIX-style token grammar on every platform, `shlex.split(..., posix=True)`, argv-list subprocess execution, and a Windows-marked quoted-path firing test. |
| F3 [P3] | Doctor's sink reflects its own environment, which may differ from a resident TUI, MCP, or Summon process. | Accepted. [DOCT-4.7] now calls the sink advisory and explicitly ties it to the doctor process at observation time. |
| F4 [P3] | SimpleBroker 7.3.2 is the locked resolution under a `>=7.3.2` floor, not a pinned dependency. | Accepted. Context, invariants, and rollout now distinguish the floor from the locked resolution and require release-candidate API verification. |
| F5 [P3] | The plan did not say whether enable/disable repair a malformed operational value. | Accepted. [TAUT-13.1] now makes replacement/removal the supported repair and Task 3 tests both paths. |
| F6 [P3] | `SystemCommand` help still says doctor runs six checks. | Accepted. Task 4 names that help update and a fixed-count documentation/test sweep. |
| F7 [nit] | `subprocess.run(timeout=2)` requests child termination at the bound but the post-termination wait can exceed two seconds. | Accepted. The normative text no longer promises an absolute return bound and names the operating-system termination wait. |
| F8 [nit] | Dump and doctor subtract different baseline metadata-key sets, so a generic description could cause one site to be missed. | Accepted. Current Structure and Task 4 name dump's post-guard `schema_version` subtraction and doctor's `schema_version`/`load_guard` subtraction separately. |
| F9 [round-2 nit] | The doctor-process advisory sentence was outside the blockquoted proposed delta and could be lost during mechanical promotion. | Accepted. The sentence is now inside the [DOCT-4.7] quote. |
| F10 [round-2 nit] | [TAUT-13.2]'s “reads the setting on every call” contradicted the new pre-resolution descendant-marker return. | Accepted. The clause now applies to every call not suppressed by the inherited action-descendant marker. |

### Independent implementation-review dispositions

| ID | Finding | Disposition |
|---|---|---|
| I1 [nit] | Task 5 named a Windows-marked real action executable-path test, while the real fixture covered a spaced argument path rather than `argv[0]`. | Accepted with an explicit proof substitution. A platform-neutral firing test now intercepts the actual subprocess call and proves a quoted Windows backslash/space path becomes an unquoted `argv[0]`; the separate real process test retains transport proof. The deviation is recorded above. |
| I2 [nit] | Unbalanced action quoting was not directly tested. | Accepted and fixed. The no-fallback action-failure matrix now includes an unterminated quote that makes `shlex.split` raise. |
| I3 [observation] | Disabled eligible failures still perform the required operational-metadata read. | Accepted as inherent to dynamic enablement, not a defect. `docs/implementation/04-taut-architecture.md` now states the one meta-queue/sidecar-read cost and the absence of debug-queue or subprocess work. |

## Fresh-Eyes Review

The author pass checked every named seam against the baseline and SimpleBroker
7.3.2. It rejected three broader designs: a generic crash-report registry, a
surface-owned sink interface, and a background debug worker. None addresses the
requested best-effort failure preservation better than one deep synchronous
core handler. The pass also found that a new `taut_meta` key is not transparent
to older doctor/dump code, which produced the required disable-before-downgrade
sequence.

The main residual uncertainty is Textual propagation. The screenshot proves
the framework had the useful traceback, but code inspection alone does not
prove every fatal callback exception exits `App.run()`. Task 7 therefore makes
a real failing-app test a stop gate rather than assuming the current core catch
is sufficient.

The read-only Claude Fable 5 pass then verified the complete file/API/spec/test
inventory and returned PASS. Its recursion finding corrected the only material
failure-path hole: action descendants now carry an explicit loop marker. Its
Windows finding replaced platform-dependent non-POSIX `shlex` behavior with
one documented argv grammar. The six smaller findings tightened doctor
advisory meaning, dependency-floor wording, malformed-value recovery, fixed
check counts, timeout wording, and exact metadata ownership sites. No finding
expanded the feature or required a new abstraction.

## Implementation Log

| Date | Commit | Slice | Verification |
|---|---|---|---|
| 2026-08-14 | plan worktree based on `45592f0` | Plan authorship | Verified active specs, core state/persistence/doctor/dispatch seams, TUI launch, MCP workspace crash conversions, standalone Summon boundary, SimpleBroker 7.3.2 literal substring search signature, and current dirty-worktree exclusions. Independent plan review pending. |
| 2026-08-14 | uncommitted plan worktree | Independent plan review and revision | Claude Fable 5 returned PASS after existence-checking all named seams. F1-F8 were reproduced and accepted. Plan-index, doc-path, 11 doc-reference tests, and `git diff --check` had passed before review; they are rerun after disposition edits. Maintainer acceptance remains the Task 1 gate before spec promotion. |
| 2026-08-14 | uncommitted plan worktree | Scoped round-2 review | F1-F8 each passed. New nits F9-F10 were accepted and fixed; the Windows path-quoting observation was added to Locked Design and Task 10. Final documentation gates are rerun from this state. |
| 2026-08-14 | uncommitted plan worktree | Final scoped review check | Claude Fable 5 returned PASS for F9-F10 and the Windows quoting note with no new finding. The independent plan-review loop is closed. |
| 2026-08-14 | uncommitted plan worktree | Plan verification | Plan-status index, doc paths, CLI claims, 11 documentation-reference tests, tracked `git diff --check`, untracked-plan whitespace, and style scan passed. The worktree still contains only the pre-existing dirty files plus this plan and its index row. |
| 2026-08-14 | uncommitted worktree based on `45592f0` | Owner acceptance and comprehension gate | User instruction `Please implement per plan` accepts the reviewed normative delta and authorizes implementation. Answers: `TAUT_DEBUG` remains the existing SimpleBroker debug translation while durable `debug_capture` enables failure capture; only an `Exception` reaching a named outer containment point is an event; MCP passes its frozen target/config pair; local search/write is not atomic across processes; removing the retained pending/claimed event ends dedup; action failure loses the event without fallback; Taut logical dump omits source setting/events while load preserves the destination setting and rejects retained debug rows; disable with the new version before downgrade. |
| 2026-08-14 | uncommitted promotion based on `45592f0` | Strategy A spec promotion | Promoted [TAUT-13], [IAN-6.1], [SUM-3]/[SUM-11]/[SUM-12], [MCP-8]/[MCP-11]/[MCP-12], [PIO-5]/[PIO-7]/[PIO-11], [DOCT-4.7]/[DOCT-7], [TUI-12]/[TUI-13], the product-section registry row, and all plan backlinks. The claim gate required one normalized `system debug` exemption rather than two impossible full-path exemptions; the deviation is recorded. Doc paths, CLI claims, 11 doc-reference tests, plan index, and `git diff --check` passed before behavior code. |
| 2026-08-14 | uncommitted implementation worktree | Textual fatal-boundary stop gate | A real Textual 8.2.8 application whose `on_mount` callback raised rendered the rich traceback, retained the exception, and returned `None` from `App.run(headless=True)`. Revised [TUI-12.1], [TUI-13.3], this plan's boundary table, hidden coupling, Task 7, and Deviation Log before adding the post-return bridge. |
| 2026-08-14 | uncommitted implementation worktree | Core operational state and deep capture module | Added exact setting mutation, seventh doctor check, logical persistence asymmetry, bounded versioned events, real local queue dedup, action transport, and no-raise containment. Focused state/event/sink/doctor/persistence tests passed; real SQLite queue, claimed-row, concurrency, and subprocess fixtures are used. |
| 2026-08-14 | uncommitted implementation worktree | CLI, TUI, MCP, and Summon containment integration | Added one core command boundary helper, the evidence-driven Textual post-return bridge, frozen-target MCP crash capture, and standalone Summon capture/re-raise. Full non-PG results: Summon unit 306 plus process 244; MCP 269 with 7 PG-only deselected; TUI 313. Installed core-wheel lane passed 28. |
| 2026-08-14 | uncommitted implementation worktree | PostgreSQL and integrated verification | Real PostgreSQL results: 258 shared tests, including debug setting/event portability, 37 PG-extension tests, and 7 MCP PG tests. Root non-wheel passed 2,022 with one expected Windows-only skip when the pre-existing branch-name release test was excluded; the unfiltered run passed 2,016 and exposed five stale debug-related inventories that were fixed plus that unrelated branch fence. Ruff, format, suppression registry, all four mypy owners, doc paths, CLI claims, plan index, documentation-reference tests, and `git diff --check` passed. |
| 2026-08-14 | uncommitted implementation worktree | Integrated independent review | Claude returned PASS with no P1-P3 finding. I1-I3 were accepted and addressed; malformed quoting and universal Windows-style `argv[0]` tests passed. A scoped follow-up returned PASS with no new finding. No owner-authorized commit has been made, so the plan remains active. |
| 2026-08-15 | owner-authorized close-out commit | Plan completion | User instruction `Close and commit` authorized the finished debug-capability slice. The commit is limited to this capability; the deferred cross-surface inventory and pre-existing TUI palette fix remain outside it. Final documentation, claim, static, type, focused behavior, full SQLite, PostgreSQL, extension, installed-wheel, and independent-review evidence is recorded above. |

## Completion Gate

Do not mark this plan completed until:

- the accepted normative delta is active and linked from all affected specs
- enable/disable and doctor behavior match the exact command/state contracts
- operational state and events obey the dump/load asymmetry
- one core module owns event construction, local/action selection, dedup, and
  no-raise containment
- every named boundary calls that handler at most once for an eligible event
- every enumerable contract and adversarial edge case has a firing test
- SQLite, PostgreSQL, core, TUI, MCP, Summon, static, doc, and claim gates pass
- implementation docs explain ownership, sensitive retention, failure limits,
  extension floors, and rollback
- all independent review findings are dispositioned and accepted fixes are
  verified in scoped follow-up
- residual risks and exact observed evidence are recorded without leaking real
  debug contents
- the finished slices are committed only with owner authorization and verified
  through `git log`

Current state: completed by the owner-authorized close-out commit. The handoff
records the exact commit identity verified through `git log`.
