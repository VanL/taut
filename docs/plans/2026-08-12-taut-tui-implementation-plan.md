# Taut TUI Implementation Plan

Date: 2026-08-12

Status: completed; integrated verification passed and the owner authorized the
coordinated 0.9.0 preparation commit

Class: 5. Adds a public interactive command, an optional framework
dependency, a new human-facing product surface, background watcher/system work,
mouse and resize contracts, and rich-host process/terminal ownership for
Summon. The work crosses core, packaging, first-party extension, terminal, and
release boundaries. It adds no durable TUI state or schema.

Plan type: implementation with a new specification promoted before runtime
work began.

Authoring baseline: `e80fe0fc9c0b73353b93754c79e93c495ab2667b`.

## Goal

Implement `taut tui` as Taut's optional human-first extension: a
terminal-native, transcript-first reflection over public core and loaded
extension capabilities. The implementation must preserve the existing domain
owners, provide vi-like and conventional keyboard parity plus optional mouse
use, remain coherent while the terminal is resizing, keep persistence load
CLI-only, and host Summon through its public rich-host seam without copying the
historical TUI's obsolete semantics.

The plan is intentionally staged so the ordinary CLI, dependency floor, and
domain contracts remain independently usable and revertible while the TUI is
built.

## Source Documents

Source specs and contracts:

- `docs/specs/10-taut-tui.md` [TUI-1]–[TUI-14], proposed by this plan
- `docs/program-theory.md` [THEORY-1]–[THEORY-6]
- `docs/specs/product-section-registry.md`, especially draft-spec promotion
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-2], [TAUT-4], [TAUT-6.4], [TAUT-7],
  [TAUT-8.3]–[TAUT-8.6], [TAUT-10], [TAUT-12.4]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-2]–[IAN-7], [IAN-9]
- `docs/specs/04-summon.md` [SUM-4], [SUM-7.4], [SUM-9], [SUM-13]
  and proposed [SUM-13.1]
- `docs/specs/06-search.md` [SRCH-2]–[SRCH-5], [SRCH-10]
- `docs/specs/08-persistence-io.md` [PIO-2]–[PIO-3], after the separately
  owned point-in-time dump revision is promoted
- `docs/specs/09-system-doctor.md` [DOCT-1]–[DOCT-7]

Implementation and workflow guidance:

- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/06-command-extensions.md`, especially Rich TUI Boundary
- `docs/implementation/09-search-architecture.md`
- `docs/implementation/10-persistence-io.md`
- `docs/implementation/11-system-doctor.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- Textual public `App.suspend`, `App.run_test`, and `Pilot` click/resize APIs at
  `https://textual.textualize.io/api/app/` and
  `https://textual.textualize.io/api/pilot/`

Historical design input, not a source contract:

- commit `b1a599a565882a2122b57b3c362e69aecd6c5b80`, especially
  `extensions/taut_tui/taut_tui/app.py`, `widgets/navigation.py`, `widgets/transcript.py`, and the
  representative responsive tests. Mine visual ideas only. Do not copy its
  API bridge, all-thread watcher, session unread model, permanent keybar,
  eight-column narrow pane, or private imports.

## Spec Baseline

- `e80fe0fc9c0b73353b93754c79e93c495ab2667b`: active core, identity,
  Summon, search, persistence, doctor, program-theory, and command-extension
  contracts at plan authoring time.
- `docs/specs/10-taut-tui.md` is a new unpromoted review target with prose
  `Status: Proposed`; `docs/specs/product-section-registry.md` classifies the
  family as `draft-spec`. README remains the product-contract owner until the
  promotion slice.
- Promotion baseline: base `e80fe0fc9c0b73353b93754c79e93c495ab2667b`
  plus the 2026-08-13 uncommitted worktree state of
  `docs/specs/10-taut-tui.md`, `docs/specs/04-summon.md`,
  `docs/specs/product-section-registry.md`, `docs/specs/00-specs-index.md`,
  and `README.md`. The owner authorized implementation in the current thread;
  no code cites the promoted contracts before this state.

## Proposed Spec Delta

Promotion strategy: **A: text before link claims**. There are two coordinated
contract deltas:

1. The new whole-spec delta already present in
   `docs/specs/10-taut-tui.md` [TUI-1]–[TUI-14]. It contains no implementation
   mapping claims.
2. The following exact edits to `docs/specs/04-summon.md` [SUM-13]. First,
   replace both existing signature summaries so they name
   `on_ready: Callable[[SummonRunHandle], None] | None = None` after
   `install_signal_handlers`. Then add this subsection after the foreground-run
   paragraphs:

> ### Foreground readiness for rich hosts [SUM-13.1]
>
> `run_foreground` accepts an optional keyword-only
> `on_ready: Callable[[SummonRunHandle], None] | None = None`. Existing callers
> that omit it retain the same blocking behavior, timing, and result contract.
> When supplied, Summon invokes it exactly once on the foreground-run owner
> thread, after the first provider generation is live and its control loop has
> installed its broker handles and is consuming correlated public `status()`
> and `stop()` operations from other threads, and before entering long-running
> supervision. The owner waits only when a callback was supplied; that wait is
> bounded to 30 seconds and aborts early on control failure, shutdown, or first-
> generation death. A timeout or aborted readiness wait follows the normal
> failing-startup cleanup path. Provider-generation resume does not invoke the
> callback again.
>
> The `SummonRunHandle` contains the actual `SummonedMember`: member id,
> collision-resolved current name, provider, and the live handle's provider
> session id when it is not `None`, otherwise the resumed bootstrap session id.
> It exposes that value as immutable field `member: SummonedMember` and one
> method, `request_stop() -> None`. That method is thread-safe, nonblocking,
> idempotent, and bound to this exact foreground run; it requests the existing
> driver-owned shutdown path without resolving a mutable member name or
> affecting a replacement driver. The driver marks the handle completed in the
> foreground run's outer `finally`, after which `request_stop()` is a no-op.
> The blocking
> `run_foreground` return or error, not `request_stop()`, remains the host's
> teardown and release result.
>
> The callback runs inline and must return promptly. It may store the handle or
> call its nonblocking `request_stop()`, but it must not call a blocking
> controller operation that waits for this same foreground owner to complete.
> The callback is not invoked when startup fails before readiness. If it raises
> an `Exception`, Summon tears down the live generation, stops the control lane,
> releases its evidence-owned session row through the normal driver path, and
> raises `SummonOperationError` with the callback failure as its cause. A
> `BaseException` outside `Exception` receives the same cleanup before the
> existing host-cancellation propagation policy applies.
>
> Once invoked, the callback does not promise that the driver remains live
> after it returns; rich hosts must reconcile readiness with the blocking
> foreground call's completion. The handle grants only exact-run stop request
> authority. It does not transfer driver, terminal, signal, process, ledger,
> teardown, or release ownership.
>
> Verification uses the public controller with a real scripted child and real
> control exchange. It proves exact once-only delivery across provider crash
> and resume, actual auto-renamed and re-summoned identity, the exact provider
> session-id precedence, concurrent status at the readiness boundary,
> run-scoped stop after post-readiness member rename, idempotent stop before and
> after completion, bounded control-open failure, callback-failure teardown and
> evidence release, no callback before startup failure, and unchanged CLI
> behavior and timing when the callback is absent. A host must not derive
> foreground ownership by diffing `list_live()` snapshots.

The spec-promotion slice performs a promise-level README audit, resolves owner
feedback, changes the TUI prose status to `Active`, changes the TUI registry
row from `draft-spec` to `canonical-spec`, inserts [SUM-13.1] into the active
Summon spec, and updates README to restate/link the adopted contract. Only
later code slices add reciprocal implementation links. Code must not cite
[TUI-*] or [SUM-13.1] until the promotion baseline is recorded.

The plan does not propose dump snapshot, watermark, read-pointer, or concurrent
writer text. The independent point-in-time dump effort owns that delta. Task 7
has a stop gate that verifies its active contract before exposing dump in the
TUI.

## Current Structure and Key Files

### Existing owners to read before editing

| Existing path/symbol | Current ownership and load-bearing behavior |
|---|---|
| `taut/commands/_builtins.py` | Static lightweight manifests for core-owned verbs. The extension-owned `tui` command must not appear here. |
| `taut/commands/_dispatch.py` and `_protocol.py` | Root/global ordering, lazy command factory load, stream authority, usage exits, and client cleanup. The TUI adapter must fit this path rather than branching in `taut.cli`. |
| `taut/client/__init__.py::TautClient.watch` | Canonicalizes explicit DM selectors, creates an independent watcher runtime, and validates membership. |
| `taut/watcher.py::TautWatcher` | Always watches the member notification queue; filtered chat queues use PEEK and advance a core cursor only after the handler returns. It poison-advances after the existing retry bound. |
| `taut/client/_threads.py` | `joined_thread_names()`, `list_threads(all_threads=True)`, channel metadata, DMs, and rename. Navigation must compose public results, not state rows. |
| `taut/client/_messaging.py` | `log()` is cursor-neutral; `read_unread()` moves cursors and may implicitly join a sub-thread; `say()`, `reply()`, reaction, and deletion own validation/races. |
| `taut/client/_notifications.py` | Notification `inbox()` consumes; `peek_inbox()` does not. Watcher notification delivery has already consumed the pointer. |
| `taut/addressing.py::parse_target` | Public sub-thread origin parsing. Do not reproduce its grammar. |
| `taut/client/_searching.py` | Cursor-neutral search and provider selection. The TUI must not load providers itself. |
| `taut/commands/system.py` | Current CLI grammar/rendering only. The TUI calls typed actor-free operations, never this adapter. |
| `extensions/taut_summon/taut_summon/controller.py` | Public blocking foreground run, provider list, live list, correlated status, and confirmed stop. It owns driver/control lifecycle. |
| `extensions/taut_summon/taut_summon/_driver.py` and `_control.py` | The foreground owner knows the collision-resolved bootstrap identity; the control thread becomes publicly stoppable only after opening its handles. [SUM-13.1] must join those facts inside Summon rather than making a host infer them. |
| `extensions/taut_summon/taut_summon/interaction.py` | Public two-phase terminal availability/lease protocol. |
| `extensions/taut_summon/taut_summon/models.py` | Complete typed request/result fields for native forms. The proposed `SummonRunHandle` adds only an actual member projection plus exact-run nonblocking stop request; it exposes no driver evidence or mutable state. |
| `pyproject.toml` | Root base, `all`, and `dev` dependencies. Root convenience extras install the separate `taut-tui` distribution, not Textual directly. |
| `tests/test_lazy_imports.py` and `tests/test_architecture_boundaries.py` | Import floors and explicit ownership/import rules that prevent optional or private subsystem leakage. |
| `tests/test_project_metadata_consistency.py` | First-party package-extra and release-relationship gates that must learn the TUI extra; package tooling owns third-party range and lock consistency. |
| `.github/workflows/test.yml` | Hosted OS/Python, wheel, PG, and extension evidence. The TUI is a separately built and released first-party target. |

### New implementation files

Create these owned modules unless a slice review proves a smaller grouping is
clearer. Any regrouping is a deviation-log entry before code moves.

| New path | Owner |
|---|---|
| `extensions/taut_tui/taut_tui/command_manifest.py` | Lightweight installed `taut.commands` manifest; no Textual import. |
| `extensions/taut_tui/taut_tui/command.py` | Lightweight selected-command validation and lazy call into the launcher; no Textual import at module import time. |
| `extensions/taut_tui/taut_tui/__init__.py` | Lazy public launch facade and missing-dependency error only. |
| `extensions/taut_tui/taut_tui/_launch.py` | TTY preflight, exact incomplete-install diagnosis, and real app construction. |
| `extensions/taut_tui/taut_tui/app.py` | Textual composition root, screen lifecycle, mode/status coordination, and final cleanup ordering. |
| `extensions/taut_tui/taut_tui/actions.py` | Closed version-1 action ids, applicability, gesture aliases, and one dispatch path. |
| `extensions/taut_tui/taut_tui/models.py` | Session-only immutable/view-model values; no duplicate domain value objects. |
| `extensions/taut_tui/taut_tui/layout.py` | Pure mode selection, physical-surface placement, focus migration, and scroll-anchor plans. |
| `extensions/taut_tui/taut_tui/session.py` | Serialized `TautClient` owner, watcher switching, generation checks, and public core operations. |
| `extensions/taut_tui/taut_tui/system.py` | Actor-free doctor/dump worker coordination and load-help model. |
| `extensions/taut_tui/taut_tui/summon.py` | Optional public-controller adapter, owned-driver workers, terminal handshake, and scoped logger handler. |
| `extensions/taut_tui/taut_tui/widgets.py` | Small public-Textual widget adapters. Widgets emit actions; they do not call domain APIs. |

### Files expected to change

- `pyproject.toml`
- new `extensions/taut_tui/pyproject.toml` distribution metadata
- `taut/commands/_builtins.py`
- new `extensions/taut_tui/taut_tui/command_manifest.py`
- new `extensions/taut_tui/taut_tui/command.py`
- new `extensions/taut_tui/taut_tui/` package above
- `tests/test_command_registry.py`
- `tests/test_lazy_imports.py`
- `tests/test_architecture_boundaries.py`
- new `extensions/taut_tui/tests/test_tui_launch.py`
- new `extensions/taut_tui/tests/test_tui_textual_contract.py`
- new `extensions/taut_tui/tests/test_tui_actions.py`
- new `extensions/taut_tui/tests/test_tui_layout.py`
- new `extensions/taut_tui/tests/test_tui_resize.py`
- new `extensions/taut_tui/tests/test_tui_chat.py`
- new `extensions/taut_tui/tests/test_tui_system.py`
- new `extensions/taut_tui/tests/test_tui_summon.py`
- `extensions/taut_summon/taut_summon/controller.py`
- `extensions/taut_summon/taut_summon/_driver.py`
- `extensions/taut_summon/taut_summon/_control.py`
- `extensions/taut_summon/taut_summon/models.py`
- `extensions/taut_summon/taut_summon/__init__.py`
- `extensions/taut_summon/tests/test_controller.py`
- `extensions/taut_summon/tests/test_driver.py`
- `docs/specs/04-summon.md`
- `docs/implementation/05-taut-summon-architecture.md`
- new `extensions/taut_pg/tests/test_pg_tui.py`
- `tests/test_project_metadata_consistency.py`
- `tests/test_docs_references.py`
- `.github/workflows/test.yml`
- `README.md`, `CHANGELOG.md`, `llms.txt`
- `docs/specs/00-specs-index.md`
- `docs/specs/product-section-registry.md`
- `docs/implementation/00-implementation-index.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`
- new `docs/implementation/12-taut-tui.md`
- this plan and `docs/plans/README.md`

Do not edit persistence implementation/spec files in this plan. Do not modify
`taut.cli` to detect a TTY or make bare `taut` launch the app.

### Required comprehension gate

Before Task 2 edits, the implementer records answers in this plan's execution
log. A wrong answer blocks implementation until the cited owner is reread.

1. **Question:** When may the TUI move unread state, and what does resize do to
   it? **Expected answer:** only public core read/write/watcher operations move
   the core cursor; a watcher advances after its handler accepts a chat item.
   Resize, focus, `log()`, and search are cursor-neutral. The TUI owns no shadow
   cursor.
2. **Question:** Why must a target switch stop the prior watcher before starting
   the next? **Expected answer:** the version-1 policy watches only visible
   reading surfaces. An old filtered watcher left alive can mark a now-inactive
   conversation read, and two watchers introduce duplicate ownership/races.
3. **Question:** What parts of Summon may the TUI own? **Expected answer:** the
   blocking worker, terminal suspension/lease adapter, host log sink, and normal
   exit decision. `SummonController` retains PTY, driver, control, child,
   status, stop, readiness, and evidence-relative release semantics. The TUI
   receives exact run ownership only through the [SUM-13.1] handle, never
   through a remembered name or `list_live()` diff.
4. **Question:** What does an installed command manifest contribute to the TUI?
   **Expected answer:** nothing generically. Native TUI actions use public domain
   interfaces; the palette is not an argv renderer or subprocess shell.
5. **Question:** What is allowed to happen during reflow? **Expected answer:**
   pure presentation over current models, latest-size-wins. No I/O, task fanout,
   watcher restart, notification claim, send, or cursor change.

## Invariants and Constraints

1. **One domain truth.** TUI models may cache render state but never redefine
   core/extension semantics or duplicate domain validation.
2. **Explicit launch.** `taut tui` is an installed extension verb. Bare `taut`,
   core-only help, version, and all existing commands retain behavior and
   dependency floors. Without `taut-tui`, core does not claim the verb.
3. **Extension dependency.** Textual is required by `taut-tui`, never by core's
   base runtime. Root `tui`, `all`, and `dev` convenience extras install the
   extension. `import taut`, CLI help, and command help do not import Textual.
4. **Public imports only.** `extensions/taut_tui/taut_tui/` may import public `taut`, `taut.client`,
   `taut.addressing`, and optional `taut_summon` facades. Architecture tests
   reject core/extension private imports and command-adapter reuse.
5. **UI loop does no I/O.** Broker, sidecar, search, doctor, dump, controller,
   stop/status, and process work run off the Textual event loop.
6. **One serialized client owner.** No `TautClient` instance crosses arbitrary
   worker threads. Watcher runtime is the existing independently owned public
   runtime, not a shared client connection.
7. **Active reading surfaces only.** Exactly one session watcher watches the
   active conversation plus an explicitly open reply thread. It is stopped and
   joined before replacement.
8. **Handler acknowledgment remains core-shaped.** A chat callback returns
   only after the UI model accepts the item. Shutdown rejection raises; no
   “display later” queue acknowledges unseen chat. Notification presentation
   is best-effort after the pointer was consumed.
9. **No hidden send target.** Composer label and action payload carry the same
   public target. A stale async completion cannot redirect a draft or send.
10. **No resize side effects.** Every boundary and transition in [TUI-9] is
    pure, state-preserving, and latest-wins.
11. **Load is CLI-only.** No public load call, CLI subprocess, dry-run, or
    destination inspection occurs in TUI code.
12. **Dump semantics are external.** The TUI adds no quiescence, census,
    watermark, cursor-reset, or snapshot logic. Its slice blocks until the
    active persistence spec permits the intended point-in-time operation.
13. **No false progress.** Long operations show indeterminate state unless a
    public operation reports measured progress.
14. **Owned foreground work cannot be orphaned normally.** A live dump blocks
    normal exit. TUI-owned Summon workers stop through the public controller or
    cancel exit. A not-yet-ready worker also blocks normal exit until its public
    identity arrives or the worker returns. External Summon drivers are not
    auto-stopped.
15. **Terminal ownership is exclusive.** Textual is fully suspended before fd
    lease publication; Summon alone owns raw bytes inside the scope; complete
    restoration precedes resumed rendering.
16. **Signal ownership stays with the host.** Every rich-host foreground run
    passes `install_signal_handlers=False`.
17. **Logging state is scoped.** TUI does not write Summon logs to the active
    screen, does not modify the root logger, and restores exact prior namespace
    logger state.
18. **Presentation failure cannot rewrite domain outcomes.** A committed send,
    delete, reaction, join, rename, dump, or stop stays successful if a later
    toast/focus/render fails; refresh and report separately.
19. **Untrusted text is inert.** No user/domain/extension string becomes
    Textual/Rich markup or raw control output outside the Summon lease.
20. **No drive-by framework.** No generic TUI plugin SDK, persistent settings,
    multiline editor, or command-manifest renderer enters version 1.

## Hidden Couplings and Error Priorities

### Cursor and watcher coupling

`TautWatcher` always includes notifications and moves chat cursors only after
the callback returns. Its thread is daemonized internally, holds its own
runtime, and has a bounded poison-message policy. `session.py` must retain a
strong watcher/thread reference, stop fetching before shutdown rejection, and
perform watcher replacement on the serialized session worker while the UI loop
remains free to service an in-flight callback. If Textual's cross-thread call
cannot provide synchronous acceptance without deadlock, stop and redesign the
bridge. Do not weaken to fire-and-forget.

### Navigation and DM coupling

There is no “all joined including read” convenience projection. Compose
`joined_thread_names()` with `list_threads(all_threads=True)`, filter public
chat kinds, and merge actor-scoped `list_direct_messages()`. Do not call the
default `list_threads()` and infer that an empty result means no membership; it
uses unread-oriented empty behavior. DM labels come from public projections.

### Thread coupling

Opening a previously unjoined reply thread is a core read/membership action.
Use public `read_unread()` for that transition, then stop/join and recreate the
watcher with the complete expanded filter. Do not show full cursor-neutral
reply history inline in the parent and imply it was read. Public
`parse_target()` supplies the origin relation.

### Resize coupling

Widget reconstruction can lose focus, input cursor, and scroll position even
when the app model survives. `layout.py` therefore produces a transition plan
from logical surface and anchor ids. `app.py` applies it in one batched UI
update. Widgets never initiate a history reload on mount/remount. A hidden
too-small view still accepts model events.

### System operation coupling

Doctor and dump are actor-free class operations and must use scoped handles
independent of the identity client. Dump output replacement and abrupt-exit
safety come from persistence. A preflight `Path.exists()` is only a visual
confirmation cue and cannot become a correctness check.

### Summon coupling

`run_foreground()` blocks for the full driver lifetime. A TUI-started run uses
one retained non-daemon thread and marks it pending-owned before start. The
proposed [SUM-13.1] callback supplies a run-scoped handle only after Summon's
control plane is publicly stoppable. The TUI moves that worker to ready-owned
in a locked registry keyed by worker token before posting presentation work; it
does not infer the member from requested/current name or `list_live()`
snapshots. Worker completion retires pending or ready state idempotently, and a
late UI message cannot recreate it. Normal exit remains open while ownership
is pending. Once ready, it calls each handle's exact-run `request_stop()` in
parallel and waits for the retained foreground workers. At the authoring
baseline, the checked shutdown path can spend 30 seconds joining the watcher,
5 seconds joining the pump, and 30 seconds joining the control thread, so the
aggregate host watchdog is 90 seconds. Task 8 must verify the current
sequential waits before freezing the constant and keep the host budget strictly
above their sum. Production code does not import private timeout constants. If
a worker return misses the host budget, the TUI remains open. Do not hard-kill
a child, stop by mutable name during owned-exit cleanup, or release a ledger
row privately.

`App.suspend()` is a synchronous context manager on the UI owner. The Summon
worker's `terminal_lease()` therefore posts a thread-safe lease-request message
and waits for acquisition. Its UI handler enters `App.suspend()` and blocks the
Textual loop inside that context while waiting on a worker-set release event.
Only after suspension succeeds does it publish acquisition. The worker yields
fd 0/1, sets release in `finally`, and waits for a restoration-complete event;
the same UI handler exits the context and signals restoration. This keeps
`__enter__` and `__exit__` on the UI thread and prevents the event loop from
rendering while suspended. An early behavioral spike must prove this split
thread handshake, not merely the presence of `App.suspend()`. If Textual
`1.0.0` lacks supported `suspend`, click, or dynamic `Pilot.resize_terminal`
behavior, raise the dependency floor to the first release that has all three
and update dependency claims before continuing; do not use Textual private
APIs.

### Error priority

1. A primary domain/controller/terminal failure is the action result.
2. Cleanup runs in `finally`; its errors are diagnostic and do not replace the
   primary result.
3. If the domain operation succeeded but model refresh failed, report success
   plus degraded refresh and retry through public reads.
4. If a watcher cannot stop, do not start another and do not close resources it
   still owns.
5. If terminal restoration fails, stop the affected Summon run and fail closed;
   do not resume concurrent Textual output on an uncertain terminal.

## Rollback and Rollout

### Rollback written before implementation

- The command, implementation, and Textual dependency are isolated in the
  `taut-tui` distribution. Removing that installed distribution removes the
  surface without changing core domain storage or core-owned verbs; the root
  `tui` convenience extra only selects the extension for installation.
- Core domain APIs remain unchanged. Summon gains one backward-compatible,
  optional readiness callback and a narrow run-handle type; callers that omit
  the callback retain current behavior.
  No schema, message, cursor, notification, dump-format, control-message, or
  Summon-ledger migration is introduced, so a rollback uses the same workspace.
- Tasks 2–6 can ship only together as an internal pre-release branch; no
  partially useful `taut tui` is advertised before the launch, conversation,
  resize, and cleanup acceptance floor is green.
- System and Summon adapters are separate later slices. If either fails review,
  its action adapter can remain unregistered while the chat TUI is corrected;
  the final release cannot claim [TUI-2.3] until both are complete.
- A bad optional dependency release is mitigated by installing core without
  `[tui]`; ordinary CLI operation remains available. This is not a substitute
  for fixing the released extra.
- Normal release rollback is a new patch release. Published wheel bytes and
  tags remain immutable under [TAUT-12.5].

### Rollout sequence

1. Promote the spec and authority row after owner approval.
2. Land optional dependency and lazy explicit launch with the real screen still
   guarded by tests.
3. Land the static layout/action shell and resize contract.
4. Land core navigation, live chat, and native core actions.
5. Land system integration only after the point-in-time dump dependency gate.
6. Land Summon integration after independent lifecycle/terminal review.
7. Reconcile docs, installed-wheel tests, hosted matrices, and release notes;
   advertise `taut-chat[tui]` only after all gates pass.

There is no storage one-way door. The public `tui` command name, optional-extra
name, action inventory, and Textual dependency are compatibility surfaces once
released. Owner review is required before changing them after promotion.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [TUI-1], [TUI-3] | Put the implementation and a static `tui` adapter inside `taut-chat`; make Textual a direct core extra | `taut-tui` owns the implementation, required Textual dependency, and installed command manifest; core convenience extras install that distribution | Owner correction on 2026-08-13: the human-first surface is an extension peer of `taut-mcp`, not part of core. Optional dependency status did not establish the right package seam. | Adopted in [TUI-1] and [TUI-3]; add `taut-tui` as a first-class release target under [TAUT-12.5] |
| [TUI-3.1], [TUI-13.2] | Keep a separate exact-oldest-Textual compatibility lane | Test the retained TUI lock only; raise the declared minimum to its selected Textual version | Owner correction on 2026-08-13: the project does not currently promise broader old-dependency support, and exact-floor tests duplicate package constraints | Adopted in [TUI-3.1] and [TUI-13.2] by `2026-08-13-ranged-dependency-policy-plan.md` |

## Decision Log

| Date | Decision | Reason | Reconsider when |
|---|---|---|---|
| 2026-08-12 | Explicit `taut tui`; bare `taut` remains help | Avoid hidden TTY dispatch and preserve script/CLI predictability | Product owner explicitly asks for bare-launch behavior |
| 2026-08-13 | `taut-tui` is a separate extension distribution; no standalone script | Owner clarified that the human-first composition root is an extension peer of `taut-mcp`; core exposes only generic public domain and installed-command seams | A later product contract replaces the extension model |
| 2026-08-12 | Native action registry, no argv renderer | Human-first capability flows need domain types and context; command manifests are not a UI schema | At least two third-party rich capability contributions justify a protocol |
| 2026-08-12 | Watch active conversation plus open reply only | Preserves inactive unread through existing core semantics without a TUI cursor | Core adopts a different multi-surface viewed/read contract |
| 2026-08-12 | `system load` informational and CLI-only | Restore is deliberate maintenance and should not become an in-app destructive convenience | A separately reviewed safe human restore workflow is specified |
| 2026-08-12 | TUI-owned Summon drivers stop on normal exit; no leave-running option | Public controller is blocking and offers no ownership transfer | Summon adds an explicit detached ownership contract |
| 2026-08-12 | Summon reports a run-scoped handle through an optional readiness callback | Requested/current names are mutable, and `list_live()` diffs race with external starts; structured cancellation must target the exact foreground run | The public foreground call itself becomes nonblocking and returns an equivalent owned task handle |
| 2026-08-12 | Exact layout thresholds 120/80/50 columns and 20 rows | They preserve useful labelled surfaces and give enumerable resize tests; historical 8-column compression failed | Real terminal testing shows a different threshold materially improves usable content |

## Tasks

### 1. Promote the reviewed TUI contract

Outcome: one adopted contract before code cites it.

- Files: `docs/specs/10-taut-tui.md`, `docs/specs/04-summon.md`,
  `docs/specs/00-specs-index.md`, `docs/specs/product-section-registry.md`,
  `README.md`, this plan.
- Read first: product-section promotion rule, [TAUT-12.4], README Roadmap.
- Obtain product-owner approval of the proposed scope and independent review
  dispositions. Perform a promise-by-promise audit between the README TUI
  promise and [TUI-*].
- Change `Status: Proposed` to `Status: Active`; flip `draft-spec` to
  `canonical-spec`; insert the exact [SUM-13.1] delta; make README restate/link
  without inventing extra promises.
- Record the promotion baseline identifier in this plan.
- Do not add implementation mapping claims yet.
- Verify: docs reference tests, CLI-claim tests, registry inspection, and
  `bin/check-plan-status-index`.
- Stop gate: if the owner changes read, launch, load, Summon exit, or resize
  semantics, revise the spec and rerun independent plan/spec review before
  Task 2.
- Done signal: one active spec, one canonical registry row, one audited README
  statement, recorded baseline, zero unresolved review blocker.

### 2. Add optional packaging and the lazy explicit launch seam

Outcome: `taut tui` is discoverable only with the extension and remains lazy
while
ordinary Taut does not import Textual.

- Files: `pyproject.toml`, `extensions/taut_tui/pyproject.toml`,
  `taut/commands/_builtins.py`, new
  `extensions/taut_tui/taut_tui/command_manifest.py`, new
  `extensions/taut_tui/taut_tui/command.py`, new `extensions/taut_tui/taut_tui/__init__.py`, new
  `extensions/taut_tui/taut_tui/_launch.py`, `tests/test_command_registry.py`,
  `extensions/taut_tui/tests/test_tui_launch.py`, new `extensions/taut_tui/tests/test_tui_textual_contract.py`,
  `tests/test_lazy_imports.py`,
  `tests/test_architecture_boundaries.py`, metadata/dependency tests.
- Add Textual to `taut-tui`. Add `taut-tui` to root `tui`, `all`, and `dev`
  convenience extras. The initial compatibility research started with 1.0.0
  because the mined prototype used the 1.x public app/pilot API. The later
  dependency-policy correction sets the ranged declaration to
  `textual>=8.2.8`, matching the retained lock, and keeps behavioral probes for
  `App.suspend`, `Pilot.click`, and `Pilot.resize_terminal` without a separate
  exact-oldest-version lane.
- Add an installed `tui` manifest with only DB/AS/TOKEN post-verb globals. Its adapter
  rejects pre-verb JSON/timestamps/quiet from `CommandContext`; omission from
  `post_verb_globals` makes their post-verb spellings parser errors. Both paths
  fail before importing the app.
- Before app implementation, add `extensions/taut_tui/tests/test_tui_textual_contract.py` with a
  minimal real app/PTY spike. It proves `App.suspend()` can be entered and
  exited on the UI thread while that loop is paused, a worker exclusively uses
  the released terminal, no Textual write escapes during the hold, and
  `Pilot.click`/`Pilot.resize_terminal` behave at the selected floor.
- `_launch.py` checks stdin/stdout TTY, then distinguishes “top-level Textual
  module absent” from “installed Textual or TUI submodule is broken.”
- Red first: core-only help/selection omits `tui`; paired installation exposes
  it; incomplete extension install and non-TTY diagnostics; normal import
  accidentally loading Textual; unsupported globals; source/wheel import
  floors.
- Do not add a branch to `taut.cli` or a `taut-tui` script.
- The existing command registry already expresses both rejection paths. Do not
  special-case dispatch.
- Done signal: source and built-wheel tests prove help/version/lazy imports,
  missing/broken extra, TTY preflight, exact globals, and unchanged existing
  command behavior.

### 3. Build the action/state shell and responsive visual skeleton

Outcome: the real Textual app implements modes, logical surfaces, action
identity, low-chrome theme, and every static/reflow arrangement without domain
I/O.

- Files: new `extensions/taut_tui/taut_tui/app.py`, `actions.py`, `models.py`, `layout.py`,
  `widgets/`, new `extensions/taut_tui/tests/test_tui_actions.py`, `test_tui_layout.py`,
  `test_tui_resize.py`.
- Implement a closed `ActionId` vocabulary exactly matching [TUI-2.3]. Every
  binding/control emits one id plus typed visual context; one dispatcher owns
  applicability and modal construction.
- Implement `NORMAL`, `COMPOSE`, `COMMAND`, and `SEARCH` with a visible mode
  line. Add the exact key parity table, mouse click/scroll behavior, and
  contextual footer. Bare `i` enters compose, never inbox.
- Implement pure `layout_mode(width, height)` and a transition plan carrying
  logical surface/focus/selection/scroll/draft state. Use one batched UI
  update per accepted resize. Use `Pilot.resize_terminal`, not direct private
  event calls.
- Red first: every 49/50, 79/80, 119/120, 19/20 boundary; all forward/reverse
  transitions; rapid latest-wins burst; no task-count growth; focus migration;
  draft/input/anchor preservation; too-small event accumulation/recovery; no
  eight-column or character-wrapped navigation.
- Visual gate: save deterministic SVG screenshots at 130x34, 100x34, 64x34,
  and 40x15 with a documented `bin/` or pytest regeneration command. Review
  them manually for [TUI-5]; structural assertions remain primary.
- Stop gate: if retaining the same Textual widget tree across modes cannot keep
  state, move state to `models.py` and rebuild from ids. Do not trigger domain
  reloads from widget mount hooks.
- Done signal: the domain-free pilot suite proves every gesture/action and
  resize invariant; representative visuals pass owner/design review.

### 4. Implement serialized core session ownership and navigation

Outcome: real workspace bootstrap, identity, navigation, history, active-only
watching, and cleanup work through public core APIs without blocking Textual.

- Files: new `extensions/taut_tui/taut_tui/session.py`, app/navigation/transcript/status widgets,
  new `extensions/taut_tui/tests/test_tui_chat.py`, architecture tests.
- Use one single-thread executor or equivalent explicit owner. Construct and
  close its `TautClient` on that owner. All requests carry a generation and
  immutable input snapshot.
- Bootstrap distinguishes absent local workspace, unrecognized identity, and
  other target failures. Implement native initialize/join/rejoin using public
  calls.
- Build navigation from `joined_thread_names()`,
  `list_threads(all_threads=True)`, and `list_direct_messages()`; filter public
  kinds and preserve stable DM labels. Catch `EmptyResultError` from public DM,
  notification, and search queries and render their specific empty states;
  never turn them into fatal startup banners.
- Target switch sequence: request old watcher stop, reject new callbacks,
  bounded join, load bounded `log()` history, commit current target, create one
  explicit-filter watcher, retain watcher/thread strongly. Use core public
  `read_unread()` only for explicit sub-thread open/join.
- Handler marshals synchronously to the UI model. Chat shutdown rejection does
  not return normally. Notification items append to the bounded session feed
  best-effort and are visibly labelled consumed pointers.
- Red first with real SQLite: inactive thread remains unread while another is
  live; active delivery advances after acceptance; target switch cannot advance
  the old target after commit; stale generations ignored; handler failure and
  shutdown preserve cursor subject to the core retry contract; notification
  appears in feed; watcher/client handles close.
- Use `tests.helpers.eventually.eventually` for side-effect-free positive
  evidence. Do not poll by consuming inbox/read operations.
- Stop gate: any need for private membership/cursor/DM state is a missing core
  seam. Pause, specify it in core, expose it to relevant surfaces, and review
  the spec delta before continuing.
- Done signal: real client/watcher tests prove the cursor, ownership, and
  cleanup invariants; the UI loop remains responsive under an intentionally
  delayed real worker result.

### 5. Complete native core actions and contextual inspectors

Outcome: every non-system core action in [TUI-2.3] works through native forms
and contextual views.

- Files: `extensions/taut_tui/taut_tui/actions.py`, `session.py`, relevant widgets,
  `extensions/taut_tui/tests/test_tui_actions.py`, `extensions/taut_tui/tests/test_tui_chat.py`.
- Implement identity show/name/persona; channel join/leave/topic/rename; start
  DM; target-labelled send; reply-thread open/send; reaction/delete; members;
  notifications; search/open-result.
- Selected-message inspector supplies reaction/delete/reply actions. Use full
  ids. It renders sub-thread markers by `parse_target()` and does not expand
  reply history until explicit open.
- Opening or closing a reply inspector stops and joins the current watcher,
  then creates a replacement with the complete active-conversation/reply
  filter. Never call inherited `add_queue()` on a live filtered watcher.
- Send captures target and draft revision at dispatch. It clears only that
  revision after a successful returned message is accepted. Target switches
  cannot retarget an in-flight send.
- Search uses real provider discovery/core search, ignores stale generations,
  and opens/anchors results without changing cursor through the search call.
- All destructive forms name exact targets. Revalidate via public domain calls
  on submit; display-only preflight never authorizes.
- Red first for every action id and failure class; mouse, vi, conventional, and
  palette invocation of representative actions must yield the same action id
  and state transition.
- Stop gate: if an action needs configurable domain vocabulary (for example
  reaction values) that has no public accessor, use a free-text field and core
  validation for v1 or propose a core API. Never read private config.
- Done signal: the closed action-inventory test fires every id, every
  destructive confirmation, and core observable effect with real SQLite.

### 6. Finish dynamic reflow under live session load

Outcome: resize behavior remains correct with real transcripts, drafts,
inspectors, live deliveries, and in-flight worker results.

- Files: `extensions/taut_tui/taut_tui/layout.py`, app/widgets as needed,
  `extensions/taut_tui/tests/test_tui_resize.py`, `extensions/taut_tui/tests/test_tui_chat.py`.
- Add message-id/intra-row scroll anchors and tail-pin detection. Wide/medium
  use aligned metadata; compact stacks metadata. Restore selected message and
  logical inspector after reflow.
- Drive rapid resize while a worker completion and watcher delivery arrive.
  Assert both enter the model, only the latest geometry renders, and no watcher
  or request count changes because of resize.
- Exercise too-small entry/recovery with active compose, command/search input,
  selected message, open reply inspector, non-tail history, and live delivery.
- Add a bounded memory/task diagnostic to the rapid burst test: after pilot
  settles, no resize worker/future/timer remains and app-owned task count returns
  to the pre-burst baseline, excluding the known session/watcher workers.
- Stop gate: if Textual emits transient zero or inconsistent sizes, normalize
  them in the pure layout boundary and add the observed case. Do not perform a
  delayed I/O refresh as a workaround.
- Done signal: [TUI-9.1]–[TUI-9.3] matrices pass with real session state and
  the visual review shows no overlap, glyph strip, or character wrapping.

### 7. Add native doctor, point-in-time dump, and CLI-only load guidance

Outcome: system capabilities are reflected with the ownership split in
[TUI-10].

- Dependency gate before red test: inspect the active `docs/specs/08-persistence-io.md`
  and its implementation baseline. It must define the owner-approved
  point-in-time dump behavior expected by the user. If not active, block only
  dump UI work; do not copy the concurrent plan or anticipate its algorithm.
- Files: new `extensions/taut_tui/taut_tui/system.py`, system report/path/form widgets,
  `extensions/taut_tui/tests/test_tui_system.py`.
- Doctor calls the real actor-free class operation on a background worker and
  maps typed checks to native rows. Assert no identity client construction or
  repair.
- Dump uses a required output field, an overwrite confirmation cue, a
  single-flight background operation, indeterminate status, typed receipt, and
  normal-quit gate. It passes the selected target/output unchanged to the
  public class operation.
- Load-help displays exact CLI shape and never imports/calls load or a
  subprocess. A tripwire makes any such call fail the test.
- Red first: healthy/findings/framework doctor; dump success/replace/domain
  failure/unwritable path/quit; load-help zero mutation and zero invocation;
  resize during each state.
- Do not mock SQLite, doctor checks, dump serialization, or atomic replace in
  acceptance. Narrow unit tests may fake a slow operation solely to test stale
  UI generations and exit gating.
- Done signal: real typed operations and tripwires prove [TUI-10], with no dump
  semantic code in `extensions/taut_tui/taut_tui/`.

### 8. Integrate Summon through the public rich-host boundary

Outcome: optional native start/list/status/dismiss, supervised owned drivers,
exclusive terminal handoff, scoped logs, and honest exit behavior.

- Files: new `extensions/taut_tui/taut_tui/summon.py`, Summon form/status/log widgets,
  `extensions/taut_tui/tests/test_tui_summon.py`,
  `extensions/taut_summon/taut_summon/controller.py`, `_driver.py`,
  `_control.py`, `models.py`, `taut_summon/__init__.py`,
  `extensions/taut_summon/tests/test_controller.py`,
  `extensions/taut_summon/tests/test_driver.py`, `docs/specs/04-summon.md`, and
  `docs/implementation/05-taut-summon-architecture.md`.
- First implement promoted [SUM-13.1] inside Summon. Add the optional
  `on_ready` callback to the public controller and propagate it to the driver.
  The control loop publishes internal readiness only after its broker handles
  are installed and its consumer is live. Only callback-bearing runs wait for
  that event: at most 30 seconds, aborting early on control failure, shutdown,
  or first-generation death. The foreground owner invokes the host callback
  exactly once with a `SummonRunHandle` whose member uses the collision-resolved
  bootstrap identity and `handle.session_id if handle.session_id is not None
  else boot.provider_session_id`. Its private stop closure calls only that
  driver's thread-safe `request_stop()`. The opaque handle owns a completion
  event set in the foreground run's outer `finally`, and its public stop method
  checks that event before touching the driver so post-completion calls are
  guaranteed no-ops.
  Invoke it inside the first generation's cleanup scope. An `Exception` follows
  normal generation teardown, control shutdown, and evidence-owned release
  before surfacing as `SummonOperationError`; other `BaseException` values get
  the same cleanup before existing propagation.
- On readiness timeout or abort, request driver/control shutdown and checked-
  join the control owner through the normal cleanup path. The fault-injection
  test must leave no provider child, foreground worker, or control thread after
  its bounded cleanup. If current broker bootstrap cannot be interrupted and
  joined under this contract, stop and revise [SUM-13.1]; do not return a
  failed foreground run while its private control thread continues opening.
- Import only from `taut_summon`. Probe availability lazily. Build every
  `SummonRequest` field from native controls and provider names from the
  controller; provider selection populates `provider_flag`.
- Start each blocking run in a retained `daemon=False` thread with
  `install_signal_handlers=False` and a bounded, nonblocking `on_ready`
  callback. Insert a pending-owned record before thread start. The callback
  synchronously replaces it with the exact run handle in a locked registry
  keyed by worker token before posting a visual update. Worker return retires
  either record; late UI events for retired tokens are discarded. Never
  correlate ownership by requested/current name or by diffing `list_live()`.
- Implement list/status/stop off the UI loop. External live drivers are shown
  but never included in automatic normal-exit stop.
- Exit confirmation calls exact-run `request_stop()` handles in parallel, then
  waits for their retained foreground workers; it never stops owned runs by
  mutable member name.
  A pending-owned worker cancels exit with a visible startup-in-progress reason
  until readiness or worker return resolves it.
  Verify the current sequential checked shutdown waits (30-second watcher,
  5-second pump, and 30-second control joins) and use one 90-second aggregate
  host watchdog; if those phases change, keep the watchdog strictly above their
  sum and update this plan. A miss or public worker error cancels exit and keeps
  exact member/error detail visible.
- Implement the terminal interaction over a thread-safe request message and
  acquisition/release/restored events. The UI handler enters and exits public
  `App.suspend()` on the UI thread and intentionally pauses the loop inside the
  context; the worker never enters/exits it. Grant public `TerminalLease(0, 1)`
  only after acquisition. One lock/lease at a time. Restore and force full
  refresh on all exits. Unsupported suspend reports `UNAVAILABLE` before a
  lease.
- Install one queue-backed handler on logger namespace `taut_summon`, with
  `propagate=False` only for the TUI scope. Save exact handlers/level/propagate;
  restore without closing handlers the TUI did not create. Escape/bound display
  and buffer during lease.
- Red first with a real scripted Summon child/control plane: present/absent,
  request fields, readiness exactly once across provider crash/resume, actual
  identity after auto-rename and re-summon, provider session-id precedence,
  concurrent status at the callback boundary, exact-run stop after a member
  self-rename, idempotent stop before/after completion, bounded control-open
  failure, callback failure cleanup/release, startup failure without callback,
  unchanged CLI behavior/timing when absent, pending/ready/returned ownership
  races, live status, dismiss, worker return, external-vs-owned exit, failed
  worker return, no signal handler mutation, lease exclusivity and restoration, log
  containment/restoration, app resize/focus/draft recovery after attach.
- Run a separate PTY smoke only where supported. Do not mock the controller
  status/stop or ledger/control exchange in contract tests.
- Independent review gate after this slice: different-family reviewer reads
  [TUI-11], [SUM-7.4], [SUM-13], `summon.py`, and tests, focusing on deadlock,
  orphan, terminal, signal, logger-global, and cleanup hazards.
- Stop gate: if [SUM-13.1], host log routing, or worker ownership cannot be
  expressed without private Summon state, return to the Summon owning spec.
  Do not inspect the ledger or driver object and do not weaken readiness to a
  polling/list-diff heuristic.
- Done signal: real process/controller tests prove no normal orphan, no terminal
  concurrency, exact logger restoration, and external-driver survival.

### 9. Cross-backend, installed-artifact, documentation, and release closeout

Outcome: the complete surface is packaged, documented, mapped, and proved in
the same environments as the released core.

- Files: PG smoke, metadata/dependency tests, workflow, README/CHANGELOG/llms,
  implementation index/map/architecture docs, new
  `docs/implementation/12-taut-tui.md`, spec implementation mappings, this plan.
- Add a focused real-PostgreSQL TUI smoke: open navigation, send, live receive,
  search, and doctor. Do not duplicate the full UI suite.
- Add fresh-wheel lanes for core without extra (install hint/no eager import)
  and wheel with `[tui]` (app import and headless pilot smoke). Cover supported
  OS/Python factors; mark real PTY/Summon attach only where the platform owns
  that capability.
- Update README install/roadmap from ahead to shipped only after gates pass.
  Explain `taut tui`, vi/conventional/mouse controls, load CLI-only, active-only
  read behavior, and Summon exit ownership without leaking internals.
- Write `docs/implementation/12-taut-tui.md` for thread ownership, generation
  flow, layout state, terminal handoff, logging, and where to edit. Update
  repository maps and reciprocal spec implementation links.
- Run full traceability, CLI-claim, metadata, core, PG, Summon, MCP, wheel,
  lint, type, coverage, and workflow gates. Record exact observed results in
  the execution log.
- Run final independent review over the whole diff and a fresh manual visual
  pass at all sizes. Resolve or disposition every finding.
- Owner-authorized commit only. Verify the resulting SHA with `git log`; do not
  add agent attribution.
- Done signal: every [TUI-13] matrix passes, docs graph is reconciled, hosted
  required factors are green, independent review has no unresolved blocker,
  and owner-authorized landing is verified.

## Testing Plan

### Red-green discipline

Every behavior slice starts with the named failing test. Record the observed
red failure before implementation and the narrow green command afterward.
Docs-only index/prose edits use the existing docs/checker failure as their red
gate when applicable. No bootstrap exception is planned.

### What stays real

- SQLite `Queue`, sidecar state, `TautClient`, `TautWatcher`, cursor changes,
  notification consumption, direct-message routing, search provider selection,
  doctor, dump serialization, and atomic output replacement.
- PostgreSQL target, broker, sidecar, search, and doctor in the focused PG lane.
- Public `SummonController` start/status/stop, scripted child process, control
  exchange, readiness callback, and evidence-relative release for lifecycle
  proof.
- Textual `App.run_test`, `Pilot.press`, `Pilot.click`, and
  `Pilot.resize_terminal` for interaction and reflow.

Do not mock these paths and then claim contract coverage. Narrow fakes are
allowed for pure layout inputs, delayed completions, terminal fd adapters,
provider behavior outside Summon, monotonic time, and an injected failure after
a domain success to prove error priority.

### Focused commands during implementation

Exact selectors may be refined to real test names, but files and scopes stay:

```bash
uv run --extra dev pytest extensions/taut_tui/tests/test_tui_launch.py extensions/taut_tui/tests/test_tui_textual_contract.py tests/test_command_registry.py tests/test_lazy_imports.py tests/test_architecture_boundaries.py -n 0 -q
uv run --extra dev pytest extensions/taut_tui/tests/test_tui_actions.py extensions/taut_tui/tests/test_tui_layout.py extensions/taut_tui/tests/test_tui_resize.py -n 0 -q
uv run --extra dev pytest extensions/taut_tui/tests/test_tui_chat.py tests/test_watcher.py -n 0 -q
uv run --extra dev pytest extensions/taut_tui/tests/test_tui_system.py tests/test_system_doctor.py tests/test_persistence_io.py -n 0 -q
uv run --extra dev pytest extensions/taut_tui/tests/test_tui_summon.py -n 0 -q
uv run --extra dev pytest extensions/taut_pg/tests/test_pg_tui.py -n 0 -q
```

Retained dependency proof:

```bash
uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests/test_tui_*.py -n 0 -q
```

### Adversarial probes

- top-level Textual absent versus broken transitive import;
- stdin non-TTY, stdout non-TTY, terminal setup/suspend failure, closed output;
- malformed DB/config and absent local workspace classification;
- message/name/topic/persona/log strings with CSI, OSC, bidi, control, and
  markup-looking content;
- stale worker result after target change, resize, modal close, and app quit;
- watcher callback failure, switch race, stop timeout, and notification render
  failure;
- dump unwritable/replace/failure/quit and no partial TUI-created file claim;
- Summon startup failure before readiness, callback failure, auto-renamed
  identity, readiness/worker-return race, controller timeout, failed evidence
  release, concurrent lease request, lease acquisition/restore error, and
  logger restoration;
- rapid alternating resize at every boundary with live delivery and non-tail
  scroll.

All user-entry failures assert an honest exit/result class, useful substring,
no traceback, and restored terminal state. Every enumerable action, binding,
threshold, mode, and destructive confirmation has a firing test.

## Verification and Gates

### Per-slice gates

- Targeted pytest command above, observed red then green.
- `uv run --extra dev ruff check` and `ruff format --check` on touched Python.
- `uv run --extra dev mypy` on exact touched production/test paths where the
  repository's package-boundary invocation permits.
- `git diff --check` and explicit file-list diff inspection.
- Independent review after the layout shell, core live-session slice, Summon
  slice, and final whole diff.

### Final local gates

Run the repository's current canonical commands at implementation time. At
minimum:

```bash
uv run --extra dev pytest
uv run --extra dev pytest extensions/taut_pg/tests
uv run --extra dev pytest extensions/taut_summon/tests
uv run --extra dev pytest extensions/taut_mcp/tests
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy taut tests
uv run bin/check-cli-claims
bin/check-plan-status-index
git diff --check
```

Also run the project metadata/dependency, docs reference, architecture, lazy
import, workflow, build, installed-wheel, coverage, and release-precheck gates
selected by current `AGENTS.md` and release documentation. The implementation
log records commands and observed counts/results, not only “passed.”

### Observable success after release

- Installing plain `taut-chat` leaves existing CLI startup/import behavior and
  dependencies unchanged; `taut tui` gives the exact extra hint.
- Installing `taut-chat[tui]` makes explicit `taut tui` open without a service,
  daemon, preference file, or schema change.
- Inactive conversations retain unread while the active conversation follows
  live; quitting releases the watcher and terminal cleanly.
- Continuous terminal resizing leaves the newest geometry coherent and
  preserves active target, draft, selection, and history anchor.
- Doctor and point-in-time dump keep the UI responsive; load remains a CLI
  instruction.
- TUI-started Summon workers either stop cleanly on normal exit or keep the app
  open with an exact failure. Externally started workers survive normal exit.

### Stop and re-plan triggers

Stop implementation and return to spec/owner review if any of these occurs:

- active-only watching cannot preserve cursor semantics through public APIs;
- a required view needs private sidecar, DM, search, dump, or Summon state;
- Textual has no supported suspend/resize/mouse seam at a reasonable floor;
- normal Summon exit needs hard kill, private release, or detached ownership;
- Summon cannot publish the actual identity at a publicly stoppable readiness
  point without exposing private state or changing existing CLI behavior;
- resize requires domain reload or loses unsaved input by framework design;
- point-in-time dump semantics are not active before Task 7;
- the optional extra changes ordinary command imports or base dependencies; or
- a new generic extension protocol appears necessary to ship one first-party
  adapter.

## Independent Review Loop

Use `skills/call-agent/SKILL.md` and
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`. Prefer a
verified reviewer family different from the author. The review unit is this
plan plus the complete proposed `docs/specs/10-taut-tui.md` delta at the
authoring baseline.

Review stance:

> You are reviewing; do not implement or modify anything. Review the proposed
> TUI spec and implementation plan at the stated baseline. Check every named
> current public surface against code. Look for semantic leakage into the TUI,
> cursor/read errors, deadlocks, stale async results, resize state loss,
> terminal/logging/signal ownership mistakes, optional-dependency or release
> drift, missing real tests, and performative overengineering. Prefer removing
> unnecessary work. Explicitly answer: could a zero-context engineer implement
> this confidently and correctly after promotion? Mark findings [P1] or [P2]
> and end with PASS or BLOCKED.

Accepted risks supplied to the reviewer:

- exact layout thresholds are v1 product choices and may be tuned only through
  spec revision, not re-litigated as “responsive thresholds are arbitrary”;
- notification pointers are consumable under core and watcher semantics;
- normal exit cannot guarantee cleanup after SIGKILL or OS termination;
- version 1 intentionally has no generic TUI plugin protocol, durable drafts,
  or multiline composer;
- dump semantics are a separate dependency, not review scope here.

Pre-existing concerns are observations unless this plan worsens them. Findings
carry suggested dispositions; scope expansions are labelled for owner decision
and are not automatically blockers. Provide out-of-scope observations in a
separate non-actionable section.

The author reproduces each claim, records it below, updates or rejects with
reasoning, then sends only accepted finding ids for re-review. Any “cannot
implement confidently” verdict blocks promotion or implementation until the
ambiguity is resolved.

### Plan/spec review disposition

| Finding | Reviewer claim | Disposition | Change/evidence |
|---|---|---|---|
| T1 (P2) | `l` was assigned both next-surface and activate/open, so its required firing test was ambiguous. | Accepted | [TUI-8.1] now reserves `l`/Right for surface movement and Enter for activation. |
| T2 (P2) | Checking only that `App.suspend()` exists does not prove a safe cross-thread terminal lease; a split hold could allow writes or deadlock. | Accepted | [TUI-11.3], the coupling analysis, Tasks 2 and 8 now require an early real PTY behavioral spike and one UI-thread enter/wait/exit handler with the event loop intentionally paused. |
| T3 (P3) | `list_direct_messages()` and other public empty queries raise `EmptyResultError`; a zero-context implementer could render a fatal error. | Accepted | [TUI-3.3] and Task 4 classify public empty results as specific empty views. |
| T4 (P3) | A filtered live watcher cannot be expanded by queue mutation because membership refresh removes queues outside its immutable filter. | Accepted | [TUI-6.4] and Task 5 require stop/join/recreate with the full new filter. |
| T5 (P3) | Pre-verb and post-verb rejected globals use distinct existing mechanisms that the plan left implicit. | Accepted | [TUI-3.2] and Task 2 name post-verb manifest omission and pre-verb `CommandContext` rejection; the speculative protocol stop gate was removed. |
| T6 (nit) | A fixed host stop budget could cease to exceed the shutdown path if its phases change. | Accepted and corrected upward | The exact-run handle uses the current sequential 30-second watcher, 5-second pump, and 30-second control joins. Final lifecycle review raised the aggregate budget to 90 seconds so exceptional cleanup retains headroom; Task 8 re-verifies the relation without a private production import. |
| T7 (nit) | `SummonRequest` uses `provider_flag`, not a `provider` field. | Accepted | [TUI-11.1] and Task 8 now name the exact field. |
| T8 (fresh-eyes) | A host cannot identify a TUI-started driver robustly from the requested name or a `list_live()` diff, especially after auto-rename or concurrent external starts. | Accepted | Proposed [SUM-13.1] supplies an exact-run handle through an optional exact-once readiness callback; [TUI-11.2] and Task 8 track pending/ready/returned ownership without inference. |
| T9 (P1) | Readiness must wait for control broker handles to be installed and consuming, not merely for `thread.start()`; the wait must abort or time out cleanly and must not alter callback-absent CLI timing. | Accepted | [SUM-13.1] and Task 8 require an internal ready event, a callback-only 30-second wait, early failure/shutdown/generation abort, and normal cleanup. |
| T10 (P2) | A marshalled readiness update arriving after worker-return could resurrect a dead ownership record. | Accepted | [TUI-11.2] and Task 8 use a locked worker-token registry updated synchronously by the callback; late visual events are no-ops. |
| T11 (P2, owner decision) | A member can rename after readiness, so name-based owned exit can strand the run; resolving by member id can still race a replacement generation. | Accepted with the stronger lifecycle boundary | `SummonRunHandle.request_stop()` targets the exact in-process run; normal owned exit never resolves a mutable name. This is a deliberate narrow public scope expansion. |
| T12 (P2) | The callback's provider session-id source was ambiguous between the first-summon bootstrap value and the live handle. | Accepted | The contract and Task 8 require `handle.session_id or boot.provider_session_id`. |
| T13 (P2) | Adding [SUM-13.1] without changing [SUM-13]'s two existing signature summaries would make the canonical spec internally inconsistent. | Accepted | The exact promotion delta now replaces both existing signature summaries as well as adding [SUM-13.1]. |
| T14 (P2) | Exactly-once verification did not explicitly exercise a provider crash/resume within the same foreground run. | Accepted | [SUM-13.1], [TUI-13.2], and Task 8 add a forced same-run provider resume test. |

### Slice and final review evidence

| Slice | Reviewer | Result | Disposition state |
|---|---|---|---|
| Plan and proposed spec | Claude Opus 2.1.207, read-only, 2026-08-12 | PASS; T1–T7; scoped round-2 PASS | Every finding accepted, applied, and verified against source; no fix-introduced defect. |
| Summon readiness delta | Claude Opus 2.1.207, read-only, 2026-08-12 | NO BLOCKER; T9–T14; scoped round-2 NO BLOCKER | All findings accepted and applied. Round 2 verified the exact-run handle, callback-only readiness wait, cleanup gates, and race fences against current controller/driver/control code. |
| Layout/action/reflow shell | Independent read-only adversarial review, 2026-08-13 | BLOCKED, then scoped re-review passed after corrections | Replaced private widget state, added typed runtime mouse dispatch, true modal focus shielding, bidirectional anchor tests, control escaping, and exact Textual 3.0 floor proof. |
| Core session/live chat | Independent read-only real-SQLite review, 2026-08-13 | BLOCKED, then focused probes passed after corrections | Preserved claimed reply history, added intent and per-send tokens, live reply-marker refresh, actor-scoped DM labels, and stale search/delete fences. |
| Summon rich-host lifecycle | Independent read-only lifecycle review, 2026-08-13 | BLOCKED, then focused controller/lease/log probes passed | Fixed close-before-ready, stale readiness, terminal fail-closed re-entry, overlapping logger scopes, primary-error priority, and surviving control-owner ownership. |
| Final whole diff | Independent read-only product/lifecycle review, 2026-08-13 | PASS; no unresolved TUI P1/P2 findings | Exact Textual 3.0.0: 176 passed; focused blockers: 15 passed; Ruff, format, mypy, diff check, generated visuals, startup/reflow/action/Summon/system boundaries all verified. |
| Extension ownership correction | Independent read-only package-boundary review, 2026-08-13 | PASS; no P1/P2 ownership, residue, or test-boundary defects | Fresh core and TUI wheels prove absence/presence of the installed command; retained and exact Textual 3.0.0 suites each pass 181 tests; release/workflow tests pass 201; public-import, lock, docs, lint, format, and mypy gates pass. |

## Out of Scope

- Any persistence dump semantic change, algorithm, watermark, or cursor reset.
- Executing, dry-running, or preflighting persistence load in the TUI.
- Implicit bare-`taut` launch or a standalone `taut-tui` console script.
- A generic argv/argparse UI or subprocess wrapper for CLI commands.
- A public third-party TUI extension/widget protocol.
- A dedicated PG, MCP, search-provider, or persistence-component dashboard.
- A daemon, tray process, detached driver, or rich-host ownership transfer.
- Persistent layouts, drafts, themes, remappable keys, or per-device inboxes.
- Multiline composer/editor.
- A new viewed/read definition, viewport cursor, presence model, notification
  delivery guarantee, or message format.
- Directly porting or merging PR 1's historical implementation.

## Fresh-Eyes Review

Before promotion and again before implementation closeout, a reviewer who did
not author the immediately preceding slice must:

1. resolve every current path/helper named above and mark new paths as such;
2. trace one active chat message from broker through watcher callback, UI model,
   cursor advance, resize, and shutdown;
3. trace one inactive message and prove no TUI watcher marks it read;
4. trace a wide → compact → too-small → wide transition with a draft and
   non-tail anchor and identify the exact state owner at each step;
5. trace a TUI-owned Summon start, lease, detach, quit, public stop, worker
   return, logging restore, and terminal restore without private state;
6. trace external Summon status through normal TUI quit and prove no stop;
7. verify missing/broken Textual and plain-core wheel behavior;
8. search for private imports, CLI subprocess calls, raw markup interpolation,
   alternate cursor/unread state, and load calls; and
9. remove any task, abstraction, golden, or matrix that does not protect a
   named invariant.

If this pass finds a material scope or architecture decision rather than a
local correction, append the deviation/decision log and return to owner/spec
review. Do not hide it in implementation.

## Execution Log

Append dated slice records only after work occurs. Each record includes the
red test and observed failure, changed files, green command/result, independent
review disposition, residual risk, and landing SHA when owner-authorized.

### 2026-08-13 — Task 1 contract promotion

- Comprehension gate answers: only public core read/write/watcher operations
  move unread; a target switch stops and joins its active-only watcher before
  replacement; the TUI owns Summon worker/terminal/log host lifecycle while
  Summon owns driver/control/PTY/release plus the exact-run readiness handle;
  installed command manifests contribute no generic TUI action; resize is pure
  latest-size-wins presentation with no domain I/O or cursor effect.
- Owner authorization: “Please implement per plan” in the current thread.
- Changed contract files: `docs/specs/10-taut-tui.md` promoted to Active;
  `docs/specs/04-summon.md` gained [SUM-13.1]; the product-section registry
  moved TUI to `canonical-spec`; README now restates and links the precise TUI
  promise; specs and plan indexes were aligned.
- Promotion baseline: base `e80fe0fc9c0b73353b93754c79e93c495ab2667b`
  plus the exact uncommitted worktree paths recorded under `## Spec Baseline`.
- Plan/spec review evidence: the authoring review and the scoped Summon
  readiness review both passed before promotion; dispositions T1–T14 remain in
  this plan.
- Verification: `uv run --extra dev pytest tests/test_docs_references.py
  tests/test_cli_claims.py -n 0 -q` passed 26 tests;
  `bin/check-plan-status-index` passed; `git diff --check` passed.
- Landing SHA: none; owner did not request a commit.

### 2026-08-13 — Task 2 optional packaging and lazy launch

- Red tests: the static registry lacked `tui`; root help omitted it; actual
  selection failed as an unknown command; the optional package and Textual
  floor were absent. Focused launch tests failed 9 cases before production
  code existed, and the metadata test failed on the missing dev dependency.
- Changed files: `pyproject.toml` and all three retained locks;
  `taut/commands/_builtins.py`; new `extensions/taut_tui/taut_tui/command.py` and `extensions/taut_tui/taut_tui/`
  launch/app seams; launch, real-Textual, lazy-import, architecture, registry,
  metadata, and CLI-claim tests; the core ambient-stdio wording and [TUI-3.2]
  were aligned with Textual's ownership of process stdin/stdout.
- Initial compatibility probe: Textual 1.0.0 exposes public `App.suspend`, `App.run_test`,
  `Pilot.click`, and `Pilot.resize_terminal`. A real PTY test proved the UI
  thread enters and exits suspension while the worker has an exclusive output
  lease. Full interaction testing later found that 1.0.0 cannot support the
  required click contract: its double-click pilot raises inside Textual and its
  single-click metadata does not identify the selected option. Textual 3.0.0 is
  the first tested release where the complete public mouse, resize, modal, and
  suspend contract passes. That research originally produced a
  `textual>=3.0.0` declaration and exact-oldest-version lane; the 2026-08-13
  dependency-policy correction supersedes both with `textual>=8.2.8` and the
  complete TUI suite against the retained lock.
- Verification: the focused Task 2 matrix passed 303 tests; the initial
  `textual==1.0.0` contract lane passed only its two narrow seam probes. The
  historical exact-3.0.0 lane passed before the policy correction; it no longer
  owns a compatibility claim. The retained TUI lock plus behavioral suite now
  owns the supported evidence; root, Summon, and MCP retained
  lock checks passed; `git diff --check` passed. The installed-wheel case
  proves `taut tui --help` stays Textual-free and an actual launch without the
  extra emits one actionable install hint with no traceback.
- Independent research review found and corrected three issues before slice
  close: ambient rather than injected TTY checks, `raw_stdio_transport=True`
  as the existing ambient-fd ownership seam, and TUI-owned launch exceptions
  instead of importing the command package from the then-planned TUI package.
- Residual risk: POSIX PTY suspension is proved locally; Windows needs a real
  hosted-console lane at final closeout because stdlib PTYs cannot simulate a
  Windows console.
- Landing SHA: none; owner did not request a commit.

### 2026-08-13 — Package-ownership correction

- Owner correction: “This is an extension, it is not in core.” The existing
  plan had incorrectly treated an optional dependency extra as the ownership
  seam even though the product model makes `taut-tui` the human-first
  extension peer of `taut-mcp`.
- Red contract: `extensions/taut_tui/tests/test_tui_packaging.py` failed because
  there was no installed command manifest and the implementation still existed
  inside core. The copied `taut_pg` test scaffold was unrelated and was
  deleted at the owner's request.
- Changed ownership: all TUI source and behavior tests moved under
  `extensions/taut_tui`; its manifest now publishes `taut tui` through
  `taut.commands`; core's static built-in and adapter were removed. Root
  `taut-chat[tui]`, `all`, and `dev` remain convenience install surfaces for
  the separate distribution.
- Package seam review found no core-private imports and no need for a new core
  interface. The extension uses public core/client, installed-command, and
  `taut_summon` facades.
- Release, lock, CI, metadata, spec, map, README, and installed-wheel evidence
  become five-distribution obligations rather than optional core-package
  details.
- Final extension verification: retained and exact `textual==3.0.0` suites each
  passed 181 tests; direct release/workflow tests passed 201; fresh wheel
  inspection contained only `taut_tui`; core-only help omitted `tui`, while an
  installed extension contributed `taut tui` through `taut.commands` and
  launched the real app headlessly. The final independent package-boundary
  review found no P1/P2 ownership, copied-test, or release-boundary defect.

### 2026-08-13 — Tasks 3–6 action shell, session ownership, chat, and reflow

- Red evidence covered the exact action inventory and native forms before the
  app shell existed; reply history was later proved claimed but absent from the
  transcript; overlapping send completions cleared the wrong draft; stale
  search/delete work replaced newer intent; a compact-to-wide reflow moved a
  deep anchor to the next message; and a hidden modal continued accepting
  input while `too-small`.
- Changed files: the domain-free action/form/model/layout/widget modules;
  `extensions/taut_tui/taut_tui/app.py`, `session.py`, `domain.py`, and `screens.py`; public core
  `history_around()` and `WatcherRejected`; the full SQLite pilot/unit matrix;
  the 130/100/64/40-column SVG fixtures and regeneration script.
- Result: keyboard, navigation, palette, and explicit mouse controls converge
  on typed action invocations; active target plus explicit reply are the only
  watched chat surfaces; exact search context remains cursor-neutral; intent
  and send tokens fence late work; live reply markers refresh through public
  navigation; modal mutations are single-flight; resize preserves drafts,
  focus, modal stack, and bounded message anchors in both directions.
- Security proof: a real PTY emitted raw CSI/OSC bytes when Rich `Text` received
  them directly. Central display escaping and every text-bearing widget test
  now prevent that output.
- Independent review: the layout/action and core-session reviews initially
  blocked on those concrete defects. Their accepted findings were reproduced,
  corrected, and covered by real Textual/SQLite tests rather than mocks.
- Landing SHA: none; owner did not request a commit.

### 2026-08-13 — Task 7 native system operations

- Implemented actor-free doctor and single-flight dump through public class
  operations. Normal quit is blocked while a dump is active. Load remains
  CLI-only: its native form renders one shell-quoted `taut system load --input`
  command and never calls load or a subprocess.
- The TUI deliberately owns no dump snapshot or quiescence semantics. Final
  root-suite failures in the separately owned point-in-time dump files remain
  outside this plan and are recorded in the verification closeout below.
- Landing SHA: none; owner did not request a commit.

### 2026-08-13 — Task 8 Summon rich-host lifecycle

- Red evidence covered absent/present Summon, pending/ready ownership,
  callback exact-once behavior, provider resume, auto-rename, exact-handle
  replacement isolation, terminal acquisition/restoration, close-before-ready,
  stale readiness, logger overlap, and a surviving control-owner thread.
- Public Summon gained immutable `SummonRunHandle` readiness. The TUI disables
  host signal installation, tracks opaque ownership separately from human
  requested/actual names, stops only exact owned runs, contains scheduled
  presentation failures, and renders correlated public status/member fields.
- Terminal leases suspend and restore on the UI owner, never time out an active
  human attach, and latch closed after uncertain restoration. Logger ownership
  supports overlapping scopes and exact out-of-order restoration. Core keeps
  the foreground ownership boundary live while its control owner survives;
  cleanup failure is a note rather than a replacement for a primary failure.
- Independent lifecycle review initially blocked on the close/readiness,
  terminal, logger, and control-owner cases. Every accepted finding has a
  firing regression test.
- Landing SHA: none; owner did not request a commit.

### 2026-08-13 — Task 9 verification and documentation closeout

- Packaging/docs before the ownership correction: `taut-chat[tui]`, lazy
  `taut tui`, the then-retained locks,
  README, changelog, maps, implementation notes, `llms.txt`, and the exact-floor
  CI lane were aligned to the superseded core-owned package model. The later
  package-ownership correction replaces that evidence with paired core and
  `taut-tui` wheels plus core-only absence.
- Backend evidence: focused public/core/Summon gates passed; PostgreSQL TUI
  smoke passed 1 test; mypy passed 159 root sources plus extension lanes; the
  locked Textual TUI suite and the exact `textual==3.0.0` suite passed before
  final re-review, then the final findings added their own focused green tests.
- Root suite evidence: the complete run reached 100% with three failures, all
  in concurrent point-in-time dump work: one dump-boundary assertion and two
  Ruff-policy gates caused by that slice's current complexity/unused import.
  The TUI-focused Ruff gate is clean. These files are not edited by this plan.
- Final review: independent reviewers found and drove fixes for initial
  too-small startup, context-control geometry, correlated Summon projection,
  internal-token presentation, and composer Enter bypassing the typed route.
  The stable read-only re-review returned PASS with no unresolved TUI P1/P2
  findings. Its exact Textual 3.0.0 run passed 176 tests and its focused
  blocker set passed 15.
- Worktree state: uncommitted by design; the owner did not request a commit, so
  this plan is not claimed ready to land under the repository completion gate.

### 2026-08-13 — Integrated completion gate

- The owner authorized the coordinated 0.9.0 preparation commit. The retained
  TUI environment passed all 182 tests, its Ruff check and format gate passed,
  and mypy passed all 29 TUI source files.
- A late navigation completion exposed a real unmount race. `_watch_future()`
  now fences both queue time and apply time against shutdown; a firing test
  proves work queued before unmount cannot render after teardown.
- The coordinated release precheck also passed core, installed-wheel,
  PostgreSQL, Summon (including strict live-harness and local-LLM smoke), and
  MCP test lanes. No TUI P1/P2 finding remains open.
