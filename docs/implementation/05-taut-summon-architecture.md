# Taut Summon Architecture

## Purpose and Scope

This document explains the implementation boundary of the `taut-summon`
extension (`extensions/taut_summon/`): how a summoned agent harness is hosted
as an ordinary workspace member without a daemon, a bespoke agent protocol, or
any change to frozen core state. It covers the ears/mouth split, the
   captive-process/free-agent posture, the driver's three-thread runtime, the
   two-table session ledger, the `sys.*` control queues, and the
   SimpleBroker-handle ownership boundary the extension holds to.

It does not restate the contract — that lives in the spec
(`docs/specs/04-summon.md`, [SUM-1]–[SUM-13]). It explains *why* the code is
shaped the way it is, and where to read and edit.

Implementation status: the structured adapter runtime and provider-session
API have been removed. Every provider registration now uses `PtyAdapter`, and
the packaged `scripted` provider is a real interactive terminal child. The
platform-neutral terminal state remains in `_pty.py`; `_pty_posix.py` owns the
POSIX lifecycle and `_pty_windows.py` owns ConPTY. The extension also ships
`run`/`stop`/`status`, bootstrap, attach/detach, ears, event pump, shutdown,
the persona template, the control plane, and the rate backstop. The control policy uses core's shared
`BaseReactor` lifecycle and reports unexpected control-lane death to the
foreground driver. A lazy public facade exposes typed models and a
`SummonController`; the standalone CLI is a renderer over that controller and
does not own ledger, control, or driver orchestration.

The extension distribution remains `taut-summon`. Its core dependency is the
distribution `taut-chat`, while runtime imports and the agent's mouth remain
`taut`. This distinction is load-bearing at the package boundary: historical
Summon wheels requiring distribution `taut` are diagnostic evidence, not
resolver-compatible releases for `taut-chat`, and the two core distributions
must not be co-installed because they own the same import files.

Historical blocker note: the 2026-07-09 process-lane PING failure was traced to
the dependency release rather than worked around with transient long-lived
handles or per-turn cleanup. SimpleBroker 5.2.2 was the first release with the
required persistent-session visibility behavior; 5.3.0 added the live waiter
replacement required by the shared core reactor; 5.3.2 made cancellation
interrupt locked watcher bootstrap; and 5.3.3 added the cleanup and metric
properties Summon requires. Version 5.6.1 added core reaction fanout; the
repository-wide supported floor is now `simplebroker>=8.0.0`, aligned with
`simplebroker-pg>=4.0.0`. The pair also exposes closeable public Queue
iterators with same-thread synchronous operation cleanup. Version 8.0.0 makes
ascending public message id the default retrieval order and advances the
SQL/backend compatibility line; neither change alters Summon's read-one
control consumption, fixed queue topology, watcher ownership, or cleanup.
Summon does not use
the SimpleBroker command layer whose option binding changed in 6.0.0 and still
relies on the earlier reactor guarantees. The 5.2.0 reactor example remains the
ownership-model provenance, not the supported runtime floor.

Summon's persistence adapter writes component version 2 without the released
provider-session field. It loads exact versions 1 and 2 and discards the
version-1 field at the loader boundary. Timestamp formatting, ledger storage,
and control-body numeric ownership do not change.

## Governing Spec References

- `docs/specs/04-summon.md` [SUM-1]–[SUM-13] — the full summon contract
- `docs/specs/02-taut-core.md` [TAUT-2] no-daemon posture,
  [TAUT-3.3]/[TAUT-3.4] sidecar schema and SimpleBroker interop,
  [TAUT-4.1] reserved queue naming, [TAUT-7.4] senders and their own
  messages, [TAUT-8.4] watcher cursor advancement, [TAUT-12.3] the captive
  agents shape decision, [TAUT-12.5] release and CI verification topology
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3.3] claim
  association, [IAN-3.4] rejoin, [IAN-4.4] name changes, [IAN-6.1] queue
  classes (amended by the summon plan's D3), [IAN-9] failure-mode robustness

### Promoted target and transition boundary

The target has one production `PtyAdapter`. Provider registrations contain
only executable argv and existing `PtySpec` values; none parses a provider
reply protocol. The packaged `scripted` registration uses that same adapter
and a real interactive child. Terminal output feeds activity, terminal-query
responses, attach display, and a bounded diagnostic tail, never chat speech.

Platform ownership sits below the adapter. `_pty_posix.py` and
`_process_domain_posix.py` retain the current POSIX fd, signal, and process-
group rules. `_pty_windows.py` owns ConPTY creation, synchronous input/output,
continuous drain, and terminal-session close. `_win32_io.py` is limited to
duplicated Win32 handles, synchronous reads/writes, exact-thread cancellation,
and console mode/code-page snapshot and restoration. Registry, driver,
readiness, terminal-query, injection, and event contracts remain platform-
neutral.

The public adapter, persistence deletion, and platform split are implemented.
Every named provider reaches the same `PtyAdapter`; its one spawn boundary
selects `_pty_posix.py` or `_pty_windows.py`. Windows named providers therefore
run through ConPTY rather than a vendor-specific stream path.

## Design Rationale

### Logical persistence contributor ([SUM-8], [PIO-5.3])

Summon registers a lazy `taut-summon` persistence component for full-workspace
dump/load. The component exports durable member continuity (`member_id`, token,
provider, wired state, and update timestamp) while excluding bootstrap claims
and driver pid/start evidence. Restored rows cannot falsely claim an old driver
is live.

Core owns framing, file and guard lifecycle, and supplies the Queue and shared
SidecarSession. `persistence.py` owns logical validation; every SQL statement
remains in `_state.py`. Dump activates the component only when
`summon_schema_version` already exists, so installing Summon does not mutate or
add an empty schema to an otherwise unused source.

### Typed embedding boundary ([SUM-13])

`extensions/taut_summon/taut_summon/controller.py` is the finite public
operation boundary. It is bound to one optional database path and owns provider
discovery, live-session listing, correlated STATUS, ACK-plus-release STOP, and
one blocking foreground driver lifecycle. The foreground method requires a
public `SummonInteraction`; the controller passes it through without inspecting
terminal state. It returns frozen typed values from `models.py` and raises the
public error hierarchy; it never prints, accepts
argv, returns CLI exit codes, or exposes ledger rows, queue handles, raw control
replies, or mutable driver state. Empty live-session discovery is the ordinary
tuple `()` for polling hosts; only the CLI turns it into the nothing-summoned
exit class.

The controller deliberately reuses `_members.find_member`, `_state`,
`ControlClient`, and `SummonDriver` behind that boundary. A second state or
control abstraction would duplicate invariants. STATUS validation copies
cursor lag and scalar detail fields into public values, rejects malformed
reply shapes, and excludes request/protocol keys. STOP still requires both a
correlated ACK and evidence-relative ledger release before returning a
`StopResult`.

The foreground controller defaults to rich-host ownership:
`install_signal_handlers=False` does not inspect or change process signal
state. The native command adapter opts in explicitly because it owns a
short-lived foreground CLI process. Opt-in is restricted to the Python main
thread. The driver snapshots the exact prior `SIGINT` and `SIGTERM`
dispositions, rolls back a partial installation before lifecycle work starts,
and restores every installed disposition in `finally`, including
`BaseException` exits. A restoration error becomes the public operation error
only when no earlier failure exists; otherwise the driver logs it as secondary
cleanup evidence and preserves the primary failure.

Rich hosts may pass `on_ready` to the same blocking foreground call
([SUM-13.1]). The callback does not move lifecycle ownership out of Summon.
It receives an opaque `SummonRunHandle` only after the first provider
generation has completed watcher initial drain and the control owner has
opened and installed its broker handles. The driver creates the control-ready
event only for callback-bearing runs, so the existing callback-absent command
path adds no readiness wait. Its bounded owner-thread wait also watches
shutdown, first-generation death, watcher failure, and fatal control state.

The handle freezes the collision-resolved bootstrap identity. Its only
authority is a closure over that exact driver's existing thread-safe
`request_stop()`. The driver sets the handle's private completion
event in `run()`'s outer `finally`; later stop requests therefore cannot resolve
a renamed member or affect a replacement run. Callback failure remains inside
the first generation's watcher and provider cleanup scopes. Ordinary
exceptions become `SummonOperationError` with the host failure as direct
cause; host cancellation outside `Exception` propagates only after the same
watcher, provider, control, evidence-release, and completion cleanup.

Rich-host identity is object-local rather than process-global. Driver and
control-loop `TautClient` instances pass
`inherit_environment_identity=False` and select identity only through their
explicit name, token, or capture arguments. Each provider adapter copies the
host environment, removes inherited `TAUT_AS` and `TAUT_TOKEN` from that local
copy, then applies the summoned member's explicit environment overlay. This
keeps the host's identity usable during a foreground run without leaking it
into the provider child or mutating `os.environ`.

`cli.py` owns only argparse, human rendering, database-path suffixes, and the
exit mapping (`NothingSummoned` to 2, other operation errors to 1). It imports
the controller inside the selected command function, after parsing. The
package facade uses typed `TYPE_CHECKING` imports plus cached runtime lookup, so
plain `import taut_summon` loads no adapter, core client, control, state,
driver, provider, or PTY implementation. Accessing a public export loads only
its owning module. This keeps help and embedding discovery cheap without a
general lazy-loader framework.

The standalone console also owns one outer debug boundary. After argument
parsing, an unexpected `Exception` escaping the selected command is passed to
core `capture_exception()` with `summon.<command>`, then the same exception
object is re-raised. Expected `CommandError` outcomes, terminal-policy errors,
signals, and driver-internal supervised failures keep their existing owners
and do not become standalone debug events. The installed `taut summon` route
does not enter `cli.main`; its unexpected adapter failure is captured once by
the core command dispatcher. This split prevents duplicate events while
keeping the standalone executable useful outside the root CLI.

### Terminal, not runtime: ears and mouth ([SUM-2])

Summon does not build an agent loop. The harness (Claude Code, Codex CLI,
or another interactive CLI) already owns tool dispatch, session state,
interruption, and permissions. Summon is the agent's *terminal*: it feeds
chat into the harness's own control loop (the **ears**) and lets the agent
speak by running the ordinary `taut` CLI (the **mouth**) in normal tool-using
operation. Summon never interprets terminal output as speech. This is the
load-bearing reason the extension needs no provider wire protocol and no core
Summon domain logic. Core knows only its generic command-extension protocol and
the two first-party ownership slots; the installed extension owns the command
adapters and controller calls.

The ears are an injected stream. `extensions/taut_summon/taut_summon/_driver.py`
watches, over the public `TautClient.watch(...)` surface, every thread the
member has joined plus its notification inbox, and pushes each message into
the child's stdin as a user-role event ([SUM-5]). The mouth is credential,
not code: after adapter-side removal of inherited host selectors, the child
environment carries the explicit `TAUT_TOKEN` (the member's continuity token,
[SUM-6]) and, on path-addressed backends, `TAUT_DB`; the agent runs
`taut say ...` like a human. Those CLI calls are transient broker
clients. Config-backed targets such as Postgres are rediscovered from the
child's inherited working directory; their DSN is never placed in `TAUT_DB`.
Prompts and diagnostics use `BrokerTarget.display_target`, so any credentials
in a server DSN remain redacted. The driver never posts chat on the member's
behalf. That is a hard invariant because two speakers under one identity is the
double-speak failure ([SUM-6]/[SUM-9]).

### Captive process, free agent ([SUM-2])

The harness child *is* a captive process: the driver spawns it, owns its
stdio, signals it, anchors presence to it, resumes it, and kills it. What is
deliberately not captive is *meaning*: captured terminal output is supervision
telemetry and diagnostics, never parsed into speech.
Sealing (`--exec "docker run -i ..."`) is composition over this boundary,
not architecture.

### The three-thread driver ([SUM-5], [SUM-7.1], [SUM-9])

One foreground process per summoned member ([TAUT-2] holds end to end),
running three concurrent lanes that a cold reader must keep distinct:

1. **Ears — the watch handler.** A `TautClient.watch` handler that is
   exactly self-filter → format ([SUM-5.2]) → `inject()` → return. The
   watcher's handler-return contract *is* the injection ledger: it advances a
   thread's cursor only after the handler returns ([TAUT-8.4]). The driver
   therefore contains **zero cursor code** ([SUM-5.4]). A failed `inject()`
   raises out of the handler, the cursor stays, and the message re-injects —
   at-least-once to the process boundary. Adapter death is fatal-and-resume:
   the handler halts injection (blocking until the driver stops the watcher)
   so [TAUT-8.4]'s three-strikes poison advance can never skip live chat.
   PTY orientation settling spends one aggregate deadline across reader start
   and quiet observation. It waits for the reader to observe at least one byte
   from the child before treating a quiet interval as settled; if a harness
   never prints a prompt, the bounded settle deadline remains the fallback.
   Terminal retirement and master closure wake this wait through the handle's
   synchronized settle event, so STOP does not spend the remaining budget.
   This keeps slow-starting PTY children from losing orientation during process
   startup while preserving a hard upper bound.
   The driver's readiness boundary is the watcher's initial drain, not thread
   construction: `TautWatcher.notify_ready_after_initial_drain()` signals after
   the polling strategy is started and the first drain has completed, and only
   then does the driver log `summoned ...`. Tests and operators may use that log
   as a readiness marker because it is downstream of the consumer-ready event,
   not because logging itself synchronizes the watcher.
   `TautWatcher` uses persistent owned queue handles because the watcher is a
   long-lived actor that may be re-queried. It still spends little time in
   locked database sections: reads and cursor writes are short SimpleBroker
   operations, removed membership handles are closed with `Queue.close()`, and
   shutdown closes the owned client. If the watcher exits, the supervisor
   rebuilds the watcher over the same live provider generation; only pump exit or
   injection failure spends the harness crash budget. Transient CLI clients
   remain non-persistent.
   Multiline chat remains one user-role event. `format_injection()` indents
   every continuation line without stripping content, so `[system]`,
   `[notify]`, or a speaker-like prefix stays visibly inside the originating
   frame. This is attribution hygiene, not prompt-injection prevention.
   Notification events retain inbox claim semantics and are therefore at most
   once; the referenced source chat remains durable.
2. **Event pump — a dedicated drain thread.** Consumes `events()` for the
   life of the child ([SUM-7.1]): `activity` updates member liveness via a
   rate-limited token-selected `whoami()` (the public [IAN-3.3] side effect,
   never a private `_state` reach), and `exit` enters the [SUM-11] fresh-
   generation recovery path. An undrained stream is a child-output deadlock; the
   pump exists to prevent it and participates in shutdown ordering. Each pump
   captures one immutable generation context; a lock-backed active-token check
   is atomic with every ledger, control, presence, chat, driver-field, and wake
   effect. A checked join retires the token and forbids the next spawn if the
   pump remains alive. Adapter stream failure may use the provider resume path;
   broker/storage failure is stored on the generation and transferred to the
   foreground as a fatal driver error after teardown, never as an unhandled
   thread exception or a provider crash.
3. **Control plane — its own consumer thread.** See below.

The backstop audit ([SUM-10]) rides the control thread, not the ears. The watch
stream is not a complete source for own sends: [TAUT-7.4] normally catches the
sender up after commit, though an intervening unread row can leave an own send
visible. Counting in the handler would therefore be incomplete and unstable.

`_driver.py` deliberately remains the cohesive owner of bootstrap, harness
generation, event pump, watcher, and their generation fences. These are one
live state machine, with named transition tests. Splitting the file by size
would hide the side-effect fences between transitions and make stale-generation
writes easier to introduce.

Shutdown ordering (shared by SIGINT and control STOP): publish shutdown →
request terminal close on the adapter → stop and checked-join the watcher →
foreground `close()` while the event pump drains → checked pump join →
ownership-checked ledger release → exit 0. Signal and control paths call only
nonblocking `request_close()`; they never wait, join, reap, or release streams.
Assignment plus a post-publication shutdown/control-failure recheck covers both
spawn/stop orders without another driver lock. `_teardown_generation()` is the
only blocking adapter finalizer. A fatal control error remains primary when it
races an adapter failure: generation teardown still runs inside the control
error's exception scope, and cleanup failures attach as notes rather than
replacing the control diagnostic.

### Owned process domains ([SUM-7.1])

`_process_domain_posix.py` is the POSIX provider-process lifecycle owner.
Adapter spawn receives an atomic pair: a `ProcessIO` view containing only PID
and borrowed stdin/stdout, plus a `ProcessDomain` capability. The raw `Popen`
remains private to that domain, so PTY code cannot accidentally reap through
`poll()` or `wait()`. The POSIX PTY backend owns its fds; the domain owns
containment, terminal observation, forced retirement, and the one leader reap.

On POSIX, spawn forces a new session and saves the leader PID as the process-
group identity. Natural exit is observed with `waitid(..., WNOWAIT)` and cached
without reaping. Python runtimes that expose `os.waitid()` use it directly;
macOS Python 3.11/3.12 use the isolated typed libc compatibility binding in
`_darwin_wait.py`. Finalization keeps the leader waitable while sending the
bounded SIGTERM/SIGKILL ladder to the saved group. A successful SIGTERM
delivery gets one bounded grace interval; finalization then attempts SIGKILL
regardless of leader status or the prior stage's accepted no-target result,
observes leader termination within the kill bound, and performs one final
`Popen.wait()`. It never uses `killpg(..., 0)` as an emptiness oracle: an
unreaped zombie leader can keep that probe successful even after every live
member is gone. `ESRCH` is the portable no-target stage result. Darwin `EPERM`
is accepted only after non-reaping leader-terminal evidence. Unexpected signal
errors remain terminal diagnostics, but finalization aggregates them while
continuing through KILL and the one reap whenever terminal status is known.
This is bounded best-effort group retirement, not atomic proof that a numeric
POSIX group is empty. A descendant that deliberately creates a new session is
outside the retained capability and must have an explicit external lifetime.

On Windows, `_pty_windows.py` creates the ConPTY and starts the provider with
`CREATE_SUSPENDED`, attaching the pseudoconsole before the primary thread can
run. ConPTY owns the attached process tree: closing it retires the leader and
descendants, after which one monitor records the leader exit and publishes one
`ExitEvent`. Setup failure terminates the unpublished suspended child and
releases every acquired pseudoconsole, process, thread, and pipe handle. The
sole output drain never waits for process exit or blocks on a terminal reply;
reply writes use the serialized, cancellable input writer on a separate owner.
The drain starts on the first operation that needs output consumption: attach
routing, detached event or settle consumption, or teardown. Publishing an
attach sink before that start preserves one-shot startup prompts for the human
path without replaying already-observed terminal queries. While a sink is
routed, observation is passive and the host terminal owns replies; after
detach, the same drain resumes Summon's bounded query responder.

The PTY pump checks leader status after every readable output turn, so a
continuously readable terminal cannot defer terminal observation. It drains
terminal output continuously for activity, query handling, attach display, and
bounded diagnostics. It never waits for a newline-delimited provider frame or
interprets screen output as speech.

### PTY adapter: capable terminal, not screen parser ([SUM-7.4])

`extensions/taut_summon/taut_summon/_pty.py` is the default host for
interactive CLIs. It uses stdlib `pty.openpty()` and the shared POSIX process-
domain spawn; no `pexpect`, `ptyprocess`, `tmux`, or screen emulator is in the
dependency surface. The child sees a real PTY with `TERM=xterm-256color`, and
the parent owns exactly one master fd.

The PTY reader deliberately does not parse the TUI as speech. It reads raw
bytes for three reasons only: finite terminal-query replies, coarse liveness,
and diagnostics/STATUS. The responder answers known report-request families
including cursor-position DSR with clamped cursor tracking, parameterized
XTVERSION, OSC color, and kitty keyboard query. Kitty keyboard mode sets and
cursor-style sets are consumed as no-reply mode changes so they do not become
false `awaiting_query` diagnostics. Unknown report-shaped queries get no
fabricated reply and instead surface `awaiting_query` through
`AdapterHandle.status_fields()`. The control loop merges those fields into
STATUS after checking reserved keys. Incomplete CSI/OSC retention is capped;
oversized prefixes are discarded or reduced to the last bounded plausible ESC
suffix, and deterministic byte-scan tests keep parser work linear.

The pump start point depends on the cached host decision. Forced detach,
`NESTED_HOST`, and generic `UNAVAILABLE` rule out a bridge before bootstrap, so
the pump starts immediately after spawn and keeps the terminal-query responder
live while SQLite and queue setup run. `AVAILABLE` and historical `NO_TTY`
remain delayed through `rejoin` and thread bootstrap. The driver then either
lets the first-generation attach bridge own the master until detach or records
the detached reason before starting the pump. Later crash generations reuse
the same decision and never acquire another lease. These paths preserve the
single-reader invariant and the shipped shell ordering.

Injection is keyboard input, so it is sanitized before framing: CR/CRLF
canonicalize to LF, C0 controls except LF are stripped, `DEL` and `ESC` are
removed, C1 controls (`U+0080..U+009F`) are stripped, and tab becomes a space.
If the harness enabled bracketed paste, LF is preserved inside paste framing;
otherwise LF collapses to spaces so one chat message is one submitted turn.
The attached bridge remains byte-transparent; this sanitizer owns only detached
Unicode injection. Orientation is the first injected turn for PTY
(`orientation_via_inject=True`), after the pump starts and settle observes the
reader's `last_output_ts`, but before the watcher starts. If STOP or SIGINT
races this pre-watch orientation step, the driver requests terminal close and
treats the retired `inject()` as a clean stop. The driver leaves the caught
`AdapterError` scope before entering generation teardown. This is load-bearing:
teardown uses `sys.exception()` to preserve a real primary failure, so calling
it from the expected cancellation handler would relabel `PTY write interrupted`
as a fatal shutdown error and make a confirmed ledger release return a false
STOP failure. The rich-host regression pins the real write lease, control
close request, and teardown order with events. Structured adapters keep the
spawn-time system-prompt path.

PTY writes distinguish an ordinary adapter fault from a terminal provider
outcome with an internal, non-exported `AdapterExitedError`. This closes the
small interval where the pump has closed the PTY master but has not yet
published generation death. Orientation preserves control failure first and
explicit shutdown second; while a rich-host readiness callback is still
pending, the terminal outcome becomes the specified readiness-abort diagnostic.
After readiness, the same outcome remains an ordinary orientation failure.
Classification never waits for the pump thread; normal teardown still joins it
and keeps cleanup failures subordinate to the selected primary error.

PTY construction validates argv, unsigned-short terminal dimensions, and
finite timing values before publishing a handle. Any setup or `Popen` failure
closes both fds and becomes `AdapterError`, so malformed environment knobs
cannot leak a master or escape the CLI as a traceback. The master is made
nonblocking once before publication. All ordinary writers (injection, attach,
and terminal replies) share one serializer and a method-entry write epoch;
interrupt cancels active and queued old-epoch writes without acquiring that
serializer and leaves the next epoch reusable. Write-side leases below pin fd
identity while syscalls run outside the lifecycle lock; readiness-wait errors
from concurrent close are normalized to the newer lifecycle state.

The fd lifecycle is the load-bearing boundary. `PtyHandle.request_close()`
publishes terminal retirement and owns one graceful Ctrl-C without waiting.
`PtyHandle.close()` ensures that request exists, drains operations, delegates
the bounded group ladder and leader reap to the shared domain, and closes the
master only if no reader has started. Once the pump owns the master, the reader
closes it on EOF/EIO. Leader exit is a non-reaping observation and cannot skip
domain retirement. The driver closes the handle and joins any already-started
pump on exceptions through bootstrap and the pump hand-off, so a failed rejoin
or thread join cannot leak a master fd or leave a zombie. Stream and PTY
handles publish `close_requested` before the graceful signal, so injections
that begin after terminal retirement fail synchronously; concurrent close
callers observe the same terminal result.

Write-side fd lifetime is carried by lifecycle-registered operation tokens and
duplicated master fds. Normal writers snapshot their epoch before
serialization, lease a duplicate under the reentrant lifecycle lock, and
perform nonblocking write/wait syscalls outside it. Reusable `interrupt()` and
terminal `request_close()` each register before attempting their dup and hold
that token through Ctrl-C plus fallback. The terminal request also publishes
`_retired` and advances the epoch before fd I/O. `close()` sends no second
Ctrl-C; it drains every request/write token, then escalates and reaps. This
makes cancellation non-starving without letting canonical-fd close or numeric
reuse redirect an in-flight syscall. Reader-side canonical ownership remains
unchanged. Epoch and retirement state are rechecked after successful and failed
syscalls so a published cancellation outranks concurrent reader close and a
stale lower-level fd diagnostic. At completion, the writer rechecks its epoch
and retires its operation token in one lifecycle-lock action. Cancellation
published before that linearization point makes the call fail even when its
final bytes were already transferred; cancellation after it applies only to
later calls.

### Attach/detach and `wired` ([SUM-7.4], [SUM-8])

First PTY use is not guessed from output. The session row carries a durable
`wired` boolean (`SUMMON_SCHEMA_VERSION` 3; introduced in version 2). A
not-yet-wired first generation with a real tty first asks the host to confirm
the exact attach transition. The notice says that the provider screen is setup,
not Taut chat; limits the task to trust/login/model or equivalent prompts;
names the non-`ESC` detach chord `Ctrl-\ Ctrl-\`; and explains that the
foreground Summon run stays active afterward. Cancellation returns before a
child, terminal lease, or readiness callback exists and leaves the durable row
unwired. After confirmation, the human completes provider setup and detaches.
Only that explicit detach sets `wired=True`. Future summons go detached.
`--attach` forces setup, while `--detach` forces detached mode.

`interaction.py` is the Textual-free public host seam. Importing it remains
lightweight; the shell confirmation lazily imports core's terminal-text escape
policy only when it renders a notice. The seam separates a pure availability
probe and typed pre-spawn confirmation from a scoped terminal lease. The driver
samples one
availability value before provider bootstrap for every attach-capable run
except forced detach, then reuses it across crash generations and after the
durable `wired` row becomes known. It computes one immutable first-generation
attach decision from those facts and asks for confirmation before spawning the
provider. Ordinary crash generations never prompt again; the single
setup-recovery escalation below is the one later-generation exception.
`AVAILABLE` and `NO_TTY`
retain the delayed pump path; `NESTED_HOST` and generic `UNAVAILABLE` start the
pump early. A lease is entered only for a confirmed attach transition —
first-generation or setup-recovery. The driver, not the host, calls the
provider bridge with the lease
fds and interprets
`detached`, `eof`, or `shutdown`; the host never receives an adapter handle or
state/control access. Lease acquisition and restoration failures are fatal, so
a failed restore cannot mark the member wired.

**Setup-gate detection and recovery attach ([SUM-7.4]).** A provider gate —
trust dialog, login, model chooser — is behaviorally indistinguishable from
a crash without one extra fact: gates render a quiescent full-screen menu
without presenting an input prompt, and orientation injection would press
Enter into it (the 2026-08-18 Kimi 0.37.2 incident: the default menu answer
exited 0, so a wired re-summon crash-looped four times). The PTY handle
therefore latches whether a bracketed-paste enable has been observed since
spawn (`input_prompt_observed`); the tracker latches the enable separately
from the live paste mode so an alt-screen exit cannot unconfirm it. At
settle, an unconfirmed prompt with an available, acknowledged terminal path
(`supports_setup_recovery()` on the interaction; shell yes, TUI yes per
[TUI-11.1] since the 2026-08-19 TUI setup-recovery offer plan)
tears the suspect generation down, offers exactly one acknowledged recovery
attach per foreground run, and reuses the whole first-attach machinery for
it. The boundary is offer-not-bridge: heuristics never start a bridge, an
explicit human decline continues the detached path (inject-after-settle,
`awaiting_onboarding` STATUS), a shutdown-produced refusal ends the run
cleanly, and a generation that itself just completed an acknowledged attach
never escalates — the human deliberately left that screen. The tradeoff is
that a paste-less provider on an available shell terminal earns one
decline-able prompt per run; the kill switch is
`TAUT_SUMMON_SETUP_RECOVERY=0`. The handle also keeps a bounded raw output
tail, exposed control-stripped, so the crash-ladder give-up error can show
the final screen plus the `taut summon --attach <name>` recovery command —
turning the previously opaque give-up into a self-explaining one. The same
tail is captured once more at escalation time, before the suspect
generation's teardown, and travels to the host inside the acknowledgement
notice's optional `screen_excerpt` field ([SUM-13]) — the offer can show
the provider's own pending question, and a host that ignores the field
renders exactly the pre-excerpt notice.

`ShellSummonInteraction` preserves historical shell behavior. It tests stdin
only, allows redirected stdout, gives no-tty diagnostics precedence over the
nested marker, reads confirmation from the command context's authoritative
stdin, writes the escaped notice to its authoritative stderr, and grants fds
0/1 without changing terminal state. A blank Enter confirms; EOF, other input,
or cancellation declines before spawn. A rich host may render a native
confirmation while its UI remains active, then pause rendering and grant other
real tty fds only inside the later lease before restoring and redrawing.

Cancellation keeps the platform's real line reader authoritative. POSIX waits
for fd readiness before the existing `readline()`. Windows cannot use that
path because `select()` accepts sockets, not console or anonymous-pipe handles.
Instead, one method-owned non-daemon thread performs exactly one synchronous
`readline()`. That reader opens and publishes a handle to its own exact native
thread before the owner releases a start/abort barrier. The owner arbitrates
line completion against cancellation under one lock and uses
`CancelSynchronousIo` only after cancellation owns the terminal action.
`ERROR_NOT_FOUND` is the read-entry race and retries while the same reader
lives. An aborted read is normal only after a successful cancellation request
for that reader. CPython may expose that cancellation either as Win32
`ERROR_OPERATION_ABORTED` or as `OSError(EINVAL)` after its Windows file/text
boundary drops the Win32 code. The translated form is normalized only under the
same exact cancellation ownership; either form without that ownership and all
other read or Win32 errors remain fatal. Every path joins the reader before
closing its native handle, and cleanup preserves the first failure. The 100 ms
wait is an event-observation cadence, never a success condition or substitute
for line/cancel evidence.

The bridge is a single select loop over the human tty, PTY master, and a
shutdown waker pipe. It is not two blocking copy threads, because STOP must be
observable during attach. It never intercepts `ESC` sequences. In `finally`, it
writes a fixed reset blast to the local tty and restores termios, because the
harness keeps running and will not clean up the user's terminal after detach.
PTY test peers must drain that blast before joining the bridge: the deliberate
`TCSADRAIN` restore may wait until the peer consumes pending terminal output.
Provider bytes observed by the attach loop also update the handle's quiet-time
evidence and a narrow persistent input-mode tracker. That tracker recognizes
split bracketed-paste control sequences but emits no replies and owns no
terminal-query diagnostics. The later event pump is still the only active
terminal responder. This passive handoff lets post-detach settling use output
already seen during attach and preserves bracketed multiline orientation when
the provider does not redraw after detach.
`TAUT_HOST_TUI=1` is the fallback marker for an uncooperative nested shell-out.
A cooperative in-process host supplies its own interaction instead.

### The session ledger: split by lifetime ([SUM-8])

`extensions/taut_summon/taut_summon/_state.py` owns two extension sidecar
tables, versioned under their own `taut_meta` key `summon_schema_version` so
core's schema gate is untouched (verified: the core suite passes against a db
bearing summon tables — the oblivious-core invariant):

- `taut_summon_claims` — **transient**. One row per in-flight bootstrap,
  `(name, provider)` primary key. Version-3 writers store the lowercase Taut
  route key; `LOWER(name)` lookup plus a unique expression index on
  `(LOWER(name), provider)` makes `Claude` and `claude` one slot even while an
  already-running version-2 writer drains. This is the concurrent-summon
  serialization point ([SUM-4]): a losing racer takes the constraint
  error and applies the collision rule. Deleted after session publication; a row
  whose driver evidence is dead is reclaimable. Because it is transient, a
  name renamed away from is claimable again — the name key never permanently
  occupies anything.
- `taut_summon_sessions` — **durable**. One row per summoned member,
  `member_id` primary key (created only after the member exists, so never
  NULL on any backend). Holds the member's continuity token (captured once at
  creation, [SUM-6]), provider, driver liveness evidence, and the PTY `wired`
  flag. The historical nullable provider-session column remains physical and
  is always written as NULL.

Names never key durable state ([IAN-4.4]: names are mutable). Every
post-creation lookup — `stop`, `status`, re-summon — resolves the *current*
name through core (`who()`) to a `member_id` and reads the sessions row by
that key. This is why a mid-run `taut set name` does not strand the control
plane, and why re-summoning a renamed-away name creates a fresh member rather
than adopting the old one.

Summon state helpers are a thin sidecar layer over SimpleBroker. SQL is fixed
module-level template text with qmark parameters and one canonical session
projection; there is no `SELECT *`, no runtime-assembled projection, and no
taut retry wrapper around sidecar calls. Row-shape failures are Taut contract
failures and surface immediately. Claim and driver ownership helpers keep
SQLite write transactions short: they read evidence, release the operation,
run process-liveness checks outside the write transaction, then perform a short
predicate-guarded write that rechecks enough ownership to preserve race safety.
Schema version 3 migrates version-2 transient claim names to lowercase route
keys and constructs the unique route expression index in the same sidecar
transaction as the version update. Index construction serializes against claim
inserts on SQLite and PostgreSQL; a second read under that lock normalizes a
non-conflicting late version-2 write. Case-variant collisions fail with version
2 and every claim row untouched, so operators resolve one transient owner and
retry without a partial migration. Normalized lookup keeps any version-2 write
that begins after commit visible until it is released or reclaimed.

Migration proof installs version 2 from the fixed JSON fixture in
`extensions/taut_summon/tests/fixtures/summon-schema-v2.json`. Its four
portable parameterized steps are copied from `_state.py` at the released
`taut_summon/v0.5.3` source commit recorded in the fixture: metadata-table DDL,
the two extension-table DDL statements, and the v2 version-row insert. Root
shared-contract and extension tests each load that fixed path locally and run
the steps through their real SQLite or PostgreSQL sidecar. The fixture is not
made by running the current installer and rewriting its version marker, because
that would test the target's idea of history rather than the historical
producer's state. It is deliberately not a generic migration-fixture format or
SQL parser.

The bootstrap order ([SUM-4]) resolves three constraints at once:
the token/env cycle (the token must exist before the child is spawned with
it), the concurrent-summon race, and the never-touch-a-foreign-member rule.
An implied provider request runs through core's `choose_name` before its first
claim, so `taut summon scripted` creates `Scripted`; an explicit
`taut summon reviewer --provider scripted` preserves `reviewer`. Later
automatic fallbacks use the same cased candidate path for either request form.
Each bounded candidate attempt claims the proposed final name, then calls core
`join(new=True)` directly under that name. Core's fail-not-adopt rule makes an
occupied route a clean collision: Summon releases only that attempt's transient
claim and tries the documented fallback. It never creates a visible temporary
member and never deletes a member as rollback. A later failure after successful
creation can leave a final-named ordinary member. The initiating terminal gets
its continuity token and the non-destructive recovery command: rename that
residual member aside with `TAUT_TOKEN=... taut set name ...`, then summon
again. It cannot be resumed as a summoned session because no session row was
published.

### Control plane: unregistered `sys.*` queues, weft-congruent verbs ([SUM-9])

`extensions/taut_summon/taut_summon/_control.py` mirrors Weft's task
control-queue contract and reactor ownership shape: verbs STOP / STATUS / PING,
single-line JSON bodies keyed `command`/`request_id`, replies correlating by
`request_id` with a `status` field, and a long-lived reactor owning persistent
queue handles. The queues derive from the member id
(`sys.ctl_<member-id>` in, `sys.rsp_<member-id>` out) under the `sys` prefix
[TAUT-4.1] reserves, and are deliberately **unregistered** ([IAN-6.1] as
amended by the plan's D3): they are invisible broker queues to every core
command — the same treatment as foreign queues — so the extension's write
surface is exactly its own tables plus plain broker queues, needing no core
seam. A debugging agent still finds them with `broker -f .taut.db list`
([TAUT-3.4]).

The extension sidecar uses the separate reserved broker queue
`taut.summon_state`. The dot makes it invalid as a Taut chat-channel name, so
the ledger cannot alias an audited chat queue. The pre-hardening
`taut_summon_state` queue may remain as inert broker metadata after upgrade;
the durable summon rows live in sidecar tables and require no row migration.

The driver consumes control with fixed-topology `_ControlReactor`, a policy
subclass of core's shared `BaseReactor`. It inherits the guarded process/wait/
stop templates unchanged, owns persistent queue handles, and uses
SimpleBroker 5.2.0's process-local session plus owner-thread-local core model.
That preserves at-most-once command semantics: a
command lost to a driver crash is moot, STOP on a dead driver is meaningless,
and STATUS/PING requesters retry. `TautClient.watch` is chat-only and knows
nothing about `sys.*`. Replies go to a **per-request** queue
`sys.rsp_<member-id>_<request_id>` so concurrent clients from different
terminals never consume each other's answers. Control reads and writes call
SimpleBroker queues directly. The only retry Taut owns here is semantic:
idempotent STATUS/PING clients may resend the same correlated request after no
reply on the same reply queue. Broker exceptions are not retried by substring.
The control thread stays responsive while an `inject()` is blocked on a stalled
harness because STOP calls nonblocking `request_close()`. That operation
publishes permanent retirement and cancels the in-flight write under [SUM-7.1];
the foreground alone performs blocking finalization.

`ControlLoop` is a thin supervisor around replaceable reactor generations.
Dispatch, native wait, and rate-audit faults are recorded while their current
stack is live, then classified only after the turn or wait unwinds. A pending
recoverable fault gates the loop: it builds a complete persistent handle bundle
off to the side, installs it atomically, closes the retired complete bundle,
and continues from loop head so no method runs on the old reactor. Partial
construction closes every resource already created. Failed replacement uses a
stop-interruptible capped backoff and permits no further old-reactor turn;
threshold exhaustion is fatal. The rate audit runs at the same between-turn
seam before the wait timeout is computed, and the timeout is bounded by both
the inactive probe and next audit deadline.

The driver wraps the control thread with a separate failure event and primary
exception. Initial open failure, programming failure, exhausted replacement,
or an unexpected clean return stops the watcher, requests terminal close on
the adapter, wakes the foreground supervisor, and exits nonzero after
foreground teardown and normal release cleanup. Expected STOP and driver
shutdown remain clean exits. Control failure never spends the watcher-rebuild
or provider-resume budgets.

Before publishing `shutdown_complete`, the foreground freezes one immutable
STOP outcome with three distinct facts: teardown error, release exception, and
release confirmation. The control owner maps those facts to an ACK only when
teardown is clean and release is confirmed. Failures keep their actual plane in
the correlated reply; teardown and ledger failures are never collapsed into a
generic release boolean. The event is the publication fence, so the control
thread never reads a partially assembled result.

Each chat-watcher attempt also has attempt-local stop state and captures the
current harness-generation death event. The foreground publishes that stop
before reading `self._watcher`; the owner publishes its watcher, rechecks stop,
generation death, shutdown, and control failure, then alone registers readiness
or enters `run()`. Foreground callers use `request_stop()` only. The owner
performs close in `finally`, and a checked bounded join is fatal if the owner
does not exit, preventing rebuild or a later harness generation from starting
over a live stale watcher.

Control cleanup closes broker handles but does not hard-delete control queues.
Completed commands and replies are already claim-consumed by `read_one`; every
control request also carries the live `driver_pid`/`driver_start_time` resolved
from the session ledger, and the driver drops commands whose evidence does not
match its own process. Any timeout reply row is isolated on a random
unregistered `sys.*` queue. That inert residue is preferable to running
delete-all maintenance in the same high-churn SQLite window as driver, provider,
and CLI subprocesses.

The rate backstop ([SUM-10]) is a circuit breaker, not a content policy. Before
each due pass, the control owner calls read-only
`TautClient.joined_thread_names()` and reconciles auxiliary persistent handles.
Left-thread handles close on that owner; rejoin gets a fresh handle while the
retained audit cursor and active-window timestamp dedupe survive. Never-seen
threads start at the later of driver audit start and the moving window floor,
never at current head. A soft breach injects a nudge and logs; a hard breach
interrupts the harness and surfaces through STATUS plus logs — never posting
to chat and never leaving an unconsumed control reply. It limits posting volume;
it does not detect a semantic loop below the configured rate.

POSIX PTY and Windows ConPTY mechanics remain separate because their resources
and cancellation primitives differ. STATUS reserved keys remain separate from
adapter display fields: they protect control-protocol ownership, not resource closure.
The release-evidence predicate is shared because ledger release and CLI polling
answer the same ownership question; those other similar-looking sets do not.

### SimpleBroker handle ownership, not a Taut retry layer ([TAUT-3.4])

Summon follows the same ownership rule as Weft's `BaseTask`: SimpleBroker owns
queue mechanics and retry; Taut owns domain state, control correlation, and
handle lifetime. `TautClient.queue()` returns a plain `simplebroker.Queue`.
Long-lived actors use persistent owned handles: the chat watcher, summon
control loop, driver ledger client, and watcher client. One-shot paths use
transient handles: ordinary `taut say`, CLI
`status`/`stop`, per-request reply queues, and short support reads outside
loops. Owned lifetime ends with `Queue.close()` or `TautClient.close()`;
`cleanup_connections()` is reserved for in-place recovery when the queue lease
must remain alive.

If a broker fault surfaces on a long-lived control path, summon records health
detail and defers complete handle replacement to the control owner's
between-turn seam. It never closes a reactor from its handler, error callback,
or inherited wait template. It does not classify
`malformed`, magic mismatch, disk I/O, timestamp row-shape, or
`malformed summon session row` errors as transient in Taut. If SimpleBroker
still leaks a lock/busy contention failure after its own budget, the fix belongs
in SimpleBroker or the dependency selection, not in a second retry wrapper.
`simplebroker>=8.0.0` is the minimum supported runtime. Its reference reactor
and
persistent session design provide one process-local session with
owner-thread-local cores; cancellation can interrupt watcher bootstrap while
PhaseLock or SQLite connection setup is blocked; runner cleanup does not infer
ownership from path names; and timestamp-conflict metrics exist before
concurrent first writes. The 5.1.x per-operation release pattern was buggy and
is unsupported.

The real-process test harness follows the same posture. Readiness is a
correlated PING/STATUS reply from the expected driver evidence; session rows and
logs are diagnostics. The harness must not hide a malformed session row as "not
ready" and must not create tight fresh-client polling loops that amplify SQLite
connection churn.

The prepared local-LLM smoke proves a different boundary. Workflow readiness
waits for model listing, then makes exactly one real completion request and
validates its response shape. The PTY child makes exactly one completion of its
own and posts the sentinel through a real `taut say`. Transport, timeout, JSON,
and response-shape failures are structured child errors without a traceback;
test failures retain the driver stderr tail, raw TUI event-log tail, and proxy
request count. Production still recovers from a crashed harness under [SUM-11],
but this smoke fails if any harness exit or resume occurred before the sentinel:
recovery is useful production behavior, not successful smoke evidence.

The real-process summon test lane uses a correctness-first SQLite posture:
`BROKER_AUTO_VACUUM=0` removes test-only maintenance writes, while
`BROKER_SYNC_MODE=FULL` keeps SQLite's default sync semantics. The lane is slow
by design because it starts real driver/provider/CLI processes; downgrading sync
to `NORMAL` made CI more likely to surface storage noise. Its bootstrap PING
barrier is a live control proof with a separately bounded overall readiness
deadline, not a ledger-polling loop.

### SimpleBroker facade boundary

The extension holds to core's dependency posture: it imports from
`simplebroker` and `simplebroker.ext` only, runs no SQL against broker-owned
tables, and touches core through the public `TautClient`, `taut.identity`,
`taut.addressing`, `taut.envelope`, and `taut.watcher` seams. The adapter
supervises a real interactive child over one pseudo-terminal. Injection is
serialized and guarded by a lifecycle epoch: reusable `interrupt()` cancels
active and queued old-epoch writes while leaving the next epoch open;
`request_close()` advances the epoch and permanently retires delivery before
signaling. A duplicated descriptor or handle keeps cancellation checks from
holding the lifecycle lock across I/O. Cancellation may follow a written
prefix, so callers never treat an interrupted injection as delivered.

The event pump continuously drains terminal output while the lifecycle owner
performs bounded whole-domain finalization. Natural leader exit publishes the
cached status before the one final reap; inherited descendant output cannot
turn EOF into the liveness oracle.

The extension CLI keeps one documented argparse inventory for `run`, `stop`,
and `status`. Root help owns exit classes; each subcommand owns its syntax and
database-selection guidance. Omitting `--db` explicitly means normal Taut
discovery from the current directory through its ancestors. The standalone
root parser and the installed `taut summon` adapter both select intermixed
parsing because the Summon grammar permits thread positionals after local
options. One shared parser configurator supplies the same description and
action help to both console surfaces. Parser inventory, installed-wheel parity,
and phrase tests prevent the surfaces from drifting while preserving verbatim
`--` tails.

Standalone human `status` rows apply core's terminal policy to each dynamic
field before composing their trusted tab separators and final LF. This includes
member/provider/session fields, lag thread names, and every extensible adapter
detail key and value. The separators never enter the C0 escape policy, while
generated escape notation is never scanned a second time. Domain values remain
exact; the standalone status surface has no JSON mode.

The console adapter installs one handler on the package-scoped `taut_summon`
logger for each foreground command execution and escapes the final owned log
body through core's effective packaged/project terminal policy. Propagation is
disabled, so a preconfigured host root logger cannot bypass the safe formatter
and is not replaced. Rich hosts call `SummonController` directly and own their
logging policy and streams. Provider-owned stderr inherited directly by an
external adapter is outside Taut-owned rendering and may contain controls.
Mediating it would
require a separately drained subprocess pipe.

## Boundaries and Invariants

- **Core contains command policy, not Summon domain logic.** Core owns the
  generic command registry, parser/context protocol, two reserved first-party
  slots, and the absent-extension compatibility/install-hint adapter. That
  adapter does not make historical wheels requiring distribution `taut`
  compatible with `taut-chat`. The installed `taut-summon` distribution owns
  the native adapters and all controller calls. Core has no Summon runtime
  dependency.
- **No daemon** ([TAUT-2]): the driver is foreground; `stop`/`status` are
  clients, not services.
- **Mouth is CLI-only** ([SUM-6]): no extension code path posts chat under
  the member's identity.
- **No summon wire protocol**: the closed `AdapterEvent` union carries only
  activity and exit; a provider envelope would be drift.
- **Extension-owned state only**: `taut_summon_*` tables + the extension's
  own `taut_meta` version key + unregistered `sys.*` queues. The extension
  writes no core registry rows; core's schema gate stays oblivious.
- **Anti-mocking floor** ([SUM-12]): broker, sidecar, and CLI are never
  mocked; the provider seam is the scripted adapter (real subprocess, real
  pipes). The driver/conformance suites run real multi-process flows. The
  local-LLM live lane adds a real PTY child that calls a loopback
  OpenAI-compatible endpoint and then speaks through `taut say`, giving CI a
  credential-free transport proof without pretending to cover provider
  onboarding; it prewires the synthetic PTY member as already onboarded so
  detached CI tests injection and model transport rather than the human attach
  chord. External PTY harnesses have a default local readiness probe and an
  opt-in strict mode (`TAUT_SUMMON_LIVE_HARNESS_STRICT=1`) that prewires the
  temp database and fails on readiness or injection catch-up gaps. Release
  prechecks explicitly enable that lane with `TAUT_SUMMON_LIVE_HARNESS=1` as
  well as selecting strict mode; strictness alone does not override an inherited
  disabled live-test environment.
- **Weft congruence is contract, not code**: STOP/STATUS/PING verbs and
  queue roles per [SUM-9]; no weft imports, no vendored weft agent code.

## Key Files

| Path | Owner |
|---|---|
| `extensions/taut_summon/taut_summon/__init__.py` | Lazy, typed public facade and stable export inventory |
| `extensions/taut_summon/taut_summon/models.py` | Public request/result/status values and operation-error hierarchy ([SUM-13]) |
| `extensions/taut_summon/taut_summon/controller.py` | CLI-independent provider/list/status/stop/foreground-run orchestration ([SUM-13]) |
| `extensions/taut_summon/taut_summon/interaction.py` | Textual-free public acknowledgement/terminal-lease protocol and lazily core-dependent shell adapter ([SUM-7.4]/[SUM-13]) |
| `extensions/taut_summon/taut_summon/cli.py` | Lightweight `run`/`stop`/`status` argparse, human rendering, exit-code mapping, and standalone unexpected-exception capture boundary |
| `extensions/taut_summon/taut_summon/_driver.py` | Bootstrap ([SUM-4]), ears watch handler, event pump, resume, nonblocking terminal-close request, foreground finalization; `format_injection` ([SUM-5.2]) |
| `extensions/taut_summon/taut_summon/_state.py` | The two-table ledger, claim/session helpers, single-driver guard evidence ([SUM-8]) |
| `extensions/taut_summon/taut_summon/_control.py` | Fixed `_ControlReactor`, between-turn replacement supervisor, client, `sys.*` queue derivation, rate backstop ([SUM-9]/[SUM-10]/[SUM-11]) |
| `extensions/taut_summon/taut_summon/_adapter.py` | `AdapterHandle` lifecycle, `ProviderAdapter` protocol, `AdapterEvent` union, adapter registry ([SUM-7.1]) |
| `extensions/taut_summon/taut_summon/_process_domain_posix.py` | POSIX atomic spawn boundary, capability-minimal process I/O view, non-reaping group owner, and one leader reap ([SUM-7.1]) |
| `extensions/taut_summon/taut_summon/_darwin_wait.py` | Narrow typed libc `waitid(..., WNOWAIT)` compatibility binding for macOS Python 3.11/3.12 |
| `extensions/taut_summon/taut_summon/_pty.py` | Platform-neutral interactive adapter, validation and dispatch, terminal state, query responder, injection framing, and detach matching |
| `extensions/taut_summon/taut_summon/_pty_posix.py` | POSIX PTY fd, attach, signal, write-cancellation, and terminal-retirement lifecycle |
| `extensions/taut_summon/taut_summon/_pty_windows.py` | Windows ConPTY creation, continuous output drain, attach generations, cancellable input, and process-tree retirement |
| `extensions/taut_summon/taut_summon/_win32_io.py` | Typed Win32 calls, exact-thread I/O cancellation, duplicated handles, and console mode/code-page restoration |
| `extensions/taut_summon/taut_summon/scripted_provider.py` | The scripted provider child, including readiness publication inside bounded physical-SIGINT cleanup ownership and signal-count evidence |
| `extensions/taut_summon/taut_summon/_persona.py` | The default persona template ([SUM-10]) and env assembly |
| `extensions/taut_summon/tests/conftest.py` | The shared real-process driver harness (`DriverProcess`) and fixtures |
| `extensions/taut_summon/tests/test_conformance.py` | The portable, parameterized [SUM-12] conformance suite |
| `extensions/taut_summon/tests/test_live_local_llm.py` | The CI-safe local-LLM PTY smoke: loopback model endpoint, counting proxy, orientation, and `taut say` sentinel |
| `bin/combine-coverage.py` | Canonical raw-shard validator and public Coverage combiner; required-path truth remains separate |
| `tests/test_combine_coverage.py` | Firing proof for absent, zero-byte, unreadable, warning-producing, valid-empty, and populated coverage inputs |

## Spec-Code Trace

| Spec area | Primary code owners | Contract tests |
|---|---|---|
| [SUM-3], distribution identity, `taut-chat` floor, command registration, name/provider resolution, CLI help, database discovery, and exit classes | `extensions/taut_summon/pyproject.toml`, `extensions/taut_summon/taut_summon/command_manifest.py`, `extensions/taut_summon/taut_summon/commands/`, `extensions/taut_summon/taut_summon/controller.py`, `extensions/taut_summon/taut_summon/cli.py` | `extensions/taut_summon/tests/test_controller.py`, `extensions/taut_summon/tests/test_summon_cli.py` parser-inventory, help-phrase, grammar, discovery, and exit-class tests; current installed-wheel ownership/parity/floor cases plus the historical `Requires-Dist: taut` diagnostic in `tests/test_core_summon_wheel_matrix.py`; real root adapter lifecycle in `extensions/taut_summon/tests/test_driver.py` |
| [SUM-4], bootstrap, identity, presence | `extensions/taut_summon/taut_summon/_driver.py`, `extensions/taut_summon/taut_summon/_state.py` | `extensions/taut_summon/tests/test_driver.py` |
| [SUM-5], ears injection contract | `extensions/taut_summon/taut_summon/_driver.py` | `extensions/taut_summon/tests/test_driver.py`, `extensions/taut_summon/tests/test_conformance.py` |
| [SUM-6], mouth CLI contract | `extensions/taut_summon/taut_summon/_driver.py`, `extensions/taut_summon/taut_summon/_persona.py`, `extensions/taut_summon/taut_summon/_pty.py`, `extensions/taut_summon/taut_summon/scripted_provider.py` | `extensions/taut_summon/tests/test_driver.py` real child identity and mouth cases; `extensions/taut_summon/tests/test_persona.py`; installed paired exception proof in `tests/test_core_summon_wheel_matrix.py` |
| [SUM-7.1], adapters and process domains | `extensions/taut_summon/taut_summon/_adapter.py`, `extensions/taut_summon/taut_summon/_process_domain_posix.py`, `extensions/taut_summon/taut_summon/_darwin_wait.py`, `extensions/taut_summon/taut_summon/_pty.py`, `extensions/taut_summon/taut_summon/_pty_posix.py`, `extensions/taut_summon/taut_summon/_pty_windows.py`, `extensions/taut_summon/taut_summon/_win32_io.py` | `extensions/taut_summon/tests/test_pty_posix.py`, `extensions/taut_summon/tests/test_pty_adapter.py`, and `extensions/taut_summon/tests/test_pty_windows.py` |
| [SUM-7.4], PTY shell adapter | `extensions/taut_summon/taut_summon/_pty.py`, `extensions/taut_summon/taut_summon/_pty_posix.py`, `extensions/taut_summon/taut_summon/_pty_windows.py`, `extensions/taut_summon/taut_summon/_driver.py` | `extensions/taut_summon/tests/test_pty_adapter.py`, platform primitive cases in `extensions/taut_summon/tests/test_pty_posix.py` and `extensions/taut_summon/tests/test_pty_windows.py`, plus driver, interaction, and live-harness cases |
| [SUM-8], session ledger and guard | `extensions/taut_summon/taut_summon/_state.py` | `extensions/taut_summon/tests/test_state.py`, `extensions/taut_summon/tests/test_driver.py` |
| [SUM-8], [PIO-5.3], durable session persistence and live-lease exclusion | `extensions/taut_summon/taut_summon/persistence_manifest.py`, `persistence.py`, `_state.py::persistence_records`, `persistence_is_fresh`, `load_persistence_records` | `extensions/taut_summon/tests/test_persistence.py`; cross-backend component coverage in `extensions/taut_pg/tests/test_persistence_io.py` |
| [SUM-9], [SUM-10], [SUM-11], control lifecycle, backstop, recovery, and fatal supervision | `extensions/taut_summon/taut_summon/_control.py::_ControlReactor`, `extensions/taut_summon/taut_summon/_control.py::ControlLoop`, `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._run_control_loop`, `_report_control_failure`, `_raise_if_control_failed` | `extensions/taut_summon/tests/test_control.py` fixed topology, ownership, native wake, inter-turn recovery, audit, partial-bundle, and close tests; `extensions/taut_summon/tests/test_driver.py` publication-race, request ordering, physical STOP signal-count, fatal-control, and PING cases |
| [SUM-12], conformance | (all of the above), `bin/combine-coverage.py` | `extensions/taut_summon/tests/test_conformance.py`, `extensions/taut_summon/tests/test_driver.py` real child-boundary signal-count cases, `extensions/taut_summon/tests/test_live_harness.py`, `extensions/taut_summon/tests/test_live_local_llm.py`, `tests/test_combine_coverage.py`, `tests/test_github_workflows.py` |
| [SUM-13], [SUM-13.1], typed embedding, exact-run readiness, and lazy host boundary | `extensions/taut_summon/taut_summon/__init__.py`, `extensions/taut_summon/taut_summon/models.py`, `extensions/taut_summon/taut_summon/controller.py`, `extensions/taut_summon/taut_summon/interaction.py`, `extensions/taut_summon/taut_summon/_driver.py`, `extensions/taut_summon/taut_summon/_control.py`, `extensions/taut_summon/taut_summon/commands/summon.py` | `extensions/taut_summon/tests/test_controller.py` real scripted readiness, control, resume, rename, replacement, and callback-failure cases; `extensions/taut_summon/tests/test_driver.py` readiness timeout/session precedence and callback-absent gate; `extensions/taut_summon/tests/test_control.py` control-open publication ordering; `extensions/taut_summon/tests/test_interaction.py` real environment and signal-boundary cases; `extensions/taut_summon/tests/test_summon_cli.py` explicit CLI opt-in, controller-backed CLI and real-process driver cases |

## Change Guidance

Read `docs/specs/04-summon.md` and the summon plan before editing. The
injection format ([SUM-5.2]) and the ledger schema are the stickiest
contracts — treat a post-ship change to the injection format as a spec
revision, not a tweak, and version any ledger schema change under
`summon_schema_version`. Prefer extending the driver's three lanes over
adding a fourth; new provider behavior belongs in an adapter, never in a
summon-defined protocol.

Before completion, run the extension gate block from the active plan (the
extension suite, the core suite untouched-green, ruff/format/mypy over the
extension paths, and `uv build extensions/taut_summon`). Keep the deterministic
process, external-live, and local-LLM lanes in separate fresh pytest
invocations. Every lane uses `-n auto --dist load`; CI collects coverage during
the same unit, deterministic-process, and prepared local-LLM executions. Every
selected item owns its database, paths, processes, descriptors, and Taut
control state. External provider CLIs still share host auth/config/cache stores
and account quotas. Those are explicit prerequisites; a concurrency failure at
that boundary must be classified and fixed rather than used to restore a
worker cap. The process lane's
`xdist_group("process")` marker still co-locates process-heavy tests in broad
default `--dist loadgroup` runs, but is selection-only when the isolated lane
deliberately overrides the scheduler with `--dist load`. Host CPU count is
intentional pressure: a concurrency failure is classified and fixed rather
than hidden behind a worker cap.

External-live and local-LLM lanes also use `-n auto --dist load` and select only
`requires_live_harness` or `requires_local_llm`. Their non-live diagnostics
remain in the unit selector, and a collection proof keeps the unit/live
partitions disjoint and complete.
Release prechecks set both `TAUT_SUMMON_LIVE_HARNESS=1` and
`TAUT_SUMMON_LIVE_HARNESS_STRICT=1` locally for the external-live lane so an
inherited disable cannot skip it and installed provider CLIs fail instead of
skipping when detached onboarding would otherwise be reported as not ready.
The external-provider live lane proves detached readiness and injection
catch-up; the local LLM lane is the deterministic sentinel-posting proof. Every
release target runs these lanes by default as part of one repository-wide
precheck sequence; `--skip-checks` is the explicit human override. CI runs the
deterministic selector in a fresh `taut-summon process` matrix job rather than
after broad root and summon unit suites, and does not serialize isolated matrix
hosts for SQLite safety.

The coverage artifact boundary has two owners. `bin/combine-coverage.py`
enumerates every downloaded regular file before reading any of them, rejects
missing input, zero-byte or publicly unreadable data, and promoted
`CoverageWarning`s, then combines valid shards without deleting them.
`bin/check-required-coverage-paths.py` runs on the combined result and remains
the separate owner of named execution-path evidence. Do not add private
Coverage schema checks, file-name filtering, or per-shard line requirements to
the integrity step.

Automatic subprocess coverage belongs only to children expected to exit
normally and save their evidence. The watcher `hang` and `startup-hang` probes,
whose successful assertion requires forced termination, remove Coverage's three
subprocess-control variables before spawn. The `probe`, `early-exit`,
`invalid-startup`, and `unexpected-startup` modes retain coverage. Malformed
startup modes are allowed to exit and save normally after their output is
captured. A missed cleanup cap fails; kill-and-reap runs only if the child is
still live after the timeout/poll boundary. Otherwise a
parent kill can race the coverage SQLite file's creation and leave a validly
named zero-byte shard. The healthy watcher probe owns the real `BaseReactor`
execution path. The aggregator must still reject every zero-byte shard.
Producer lifecycle, not post-upload filtering, prevents a green test cleanup
from manufacturing invalid evidence.

## Related Plans

- `docs/plans/2026-09-03-summon-unified-pty-cross-platform-plan.md` — promotes
  the one-adapter target, Windows ConPTY owner boundary, structured-runtime
  deletion, persistence version 2, and cross-platform test topology tracked by
  the transition note above.
- `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md` — authentic
  version-2 migration fixture and collision-preserving proof.
- `docs/plans/2026-08-17-summon-shell-cancel-portability-plan.md` — Windows
  synchronous-reader cancellation ownership without socket-only `select()`.
- `docs/plans/2026-08-17-summon-first-attach-handoff-plan.md` — pre-spawn
  host acknowledgement plus passive PTY state transfer across attach/detach.
- `docs/plans/2026-08-14-windows-postrelease-ci-determinism-plan.md` — exact
  callback/MCP ownership diagnosis and killed negative-probe coverage lifecycle.
- `docs/plans/2026-08-14-review-findings-remediation-plan.md` — bounded
  stream-write cancellation, one-budget PTY settle, primary-error teardown,
  C1 sanitization, Claude startup, and final confirmation polling.
- `docs/plans/2026-07-29-taut-chat-pypi-publication-plan.md` — core
  distribution rename, current-wheel boundary, and exact-artifact publication.
- `docs/plans/2026-07-14-blank-message-no-op-plan.md` — typed core blank result
  and terminal-mode continuation.
- `docs/plans/2026-07-14-universal-release-gates-plan.md` — universal local
  release verification, explicit live enablement plus strictness, and PG
  evidence for the Summon tag.
- `docs/plans/2026-07-13-ci-speed-determinism-release-evidence-plan.md` —
  strict local-LLM evidence, existing-lane coverage, and release reuse of
  exact-SHA canonical test artifacts.
- `docs/plans/2026-07-13-bounded-summon-process-test-parallelism-plan.md` —
  superseded fixed-width policy; the 2026-09-01 release determinism plan makes
  every fresh Summon lane an auto-width pressure proof.
- `docs/plans/2026-07-12-automatic-display-name-capitalization-plan.md` —
  implied-provider display casing, shared candidate selection, and normalized
  transient name claims.
- `docs/plans/2026-07-10-taut-dynamic-native-waiter-replacement-plan.md` — the
  shared-core waiter replacement follow-on; Summon's control reactor remains
  fixed-topology.
- `docs/plans/2026-07-06-taut-summon-plan.md` — the implementing plan
  (spec promotion, extension package, delegation verbs, ledger, adapters,
  driver, control plane, conformance suite)
- `docs/plans/2026-07-07-taut-summon-pty-harness-adapter-plan.md` — the
  universal PTY adapter, attach/detach, `wired` schema, provider registry, and
  live harness conformance plan
- `docs/plans/2026-07-08-taut-sqlite-contention-hardening-plan.md` — the
  SQLite contention hardening plan: live STATUS/readiness evidence,
  SimpleBroker handle ownership, integrity probes, and watcher handle lifetime
  proof
- `docs/plans/2026-07-09-taut-reactor-safety-plan.md` — implemented shared
  reactor lifecycle, Summon inter-turn recovery, native control wake, and
  fatal control-lane supervision
