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
(`docs/specs/04-summon.md`, [SUM-1]–[SUM-12]). It explains *why* the code is
shaped the way it is, and where to read and edit.

Implementation status: the extension ships `run`/`stop`/`status`, the
scripted adapter, the universal PTY adapter for interactive harnesses, the
`claude-stream` structured adapter, the driver (bootstrap, attach/detach,
ears, event pump, resume, shutdown), the persona template, the control
plane, and the rate backstop. The control policy uses core's shared
`BaseReactor` lifecycle and reports unexpected control-lane death to the
foreground driver.

Historical blocker note: the 2026-07-09 process-lane PING failure was traced to
the dependency release rather than worked around with transient long-lived
handles or per-turn cleanup. SimpleBroker 5.2.2 was the first release with the
required persistent-session visibility behavior; 5.3.0 is the supported floor
because the shared core reactor requires live waiter replacement. The 5.2.0 reactor
example remains the ownership-model provenance, not the supported runtime
floor.

## Governing Spec References

- `docs/specs/04-summon.md` [SUM-1]–[SUM-12] — the full summon contract
- `docs/specs/02-taut-core.md` [TAUT-2] no-daemon posture,
  [TAUT-3.3]/[TAUT-3.4] sidecar schema and SimpleBroker interop,
  [TAUT-4.1] reserved queue naming, [TAUT-7.4] senders and their own
  messages, [TAUT-8.4] watcher cursor advancement, [TAUT-12.3] the captive
  agents shape decision
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3.3] claim
  association, [IAN-3.4] rejoin, [IAN-4.4] name changes, [IAN-6.1] queue
  classes (amended by the summon plan's D3), [IAN-9] failure-mode robustness

## Design Rationale

### Terminal, not runtime: ears and mouth ([SUM-2])

Summon does not build an agent loop. The harness (Claude Code, Codex CLI,
any resumable streaming CLI) already owns tool dispatch, session state,
interruption, and permissions. Summon is the agent's *terminal*: it feeds
chat into the harness's own control loop (the **ears**) and lets the agent
speak by running the ordinary `taut` CLI (the **mouth**) in normal tool-using
operation. Terminal mode is the narrow exception: parsed assistant text is
posted through the driver-owned persistent mouth client because the harness has
no separate tool path. This is the single most load-bearing decision in the
design, and it is why the extension needs no general wire protocol and no core
changes beyond two delegation verbs.

The ears are an injected stream. `extensions/taut_summon/taut_summon/_driver.py`
watches, over the public `TautClient.watch(...)` surface, every thread the
member has joined plus its notification inbox, and pushes each message into
the child's stdin as a user-role event ([SUM-5]). The mouth is credential,
not code: the child environment carries `TAUT_TOKEN` (the member's
continuity token, [SUM-6]) and, on path-addressed backends, `TAUT_DB`; the
agent runs `taut say ...` like a human. Those CLI calls are transient broker
clients. Config-backed targets such as Postgres are rediscovered from the
child's inherited working directory; their DSN is never placed in `TAUT_DB`.
Prompts and diagnostics use `BrokerTarget.display_target`, so any credentials
in a server DSN remain redacted. The terminal-mode mouth path is reactor-owned by the driver and uses
the driver's persistent client. The driver never posts chat on the member's
behalf outside terminal mode — a hard invariant, because two speakers under one
identity is the double-speak failure ([SUM-6]/[SUM-9]).

### Captive process, free agent ([SUM-2])

The harness child *is* a captive process: the driver spawns it, owns its
stdio, signals it, anchors presence to it, resumes it, and kills it. What is
deliberately not captive is *meaning* — captured stdout is supervision
telemetry (activity, session ids, diagnostics), never parsed into speech.
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
   PTY orientation settling waits for the reader to observe at least one byte
   from the child before treating a quiet interval as settled; if a harness
   never prints a prompt, the bounded settle deadline remains the fallback.
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
   rebuilds the watcher over the same live provider session; only pump exit or
   injection failure spends the harness crash budget. Transient CLI clients
   remain non-persistent.
   Multiline chat remains one user-role event. `format_injection()` indents
   every continuation line without stripping content, so `[system]`,
   `[notify]`, or a speaker-like prefix stays visibly inside the originating
   frame. This is attribution hygiene, not prompt-injection prevention.
   Notification events retain inbox claim semantics and are therefore at most
   once; the referenced source chat remains durable.
2. **Event pump — a dedicated drain thread.** Consumes `events()` for the
   life of the child ([SUM-7.1]): session ids to the ledger, `activity` to
   member liveness via a rate-limited token-selected `whoami()` (the public
   [IAN-3.3] side effect — never a private `_state` reach), assistant text to
   the thread in terminal mode or the log otherwise, and `exit` to the
   [SUM-11] resume path. An undrained stream is a child-stdout deadlock; the
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

Shutdown ordering (shared by SIGINT and control STOP): stop injection →
adapter interrupt (unblocks any in-flight `inject()`) → pump drains to `exit`
or a bounded timeout → ownership-checked ledger release → exit 0. The signal
and control paths interrupt the current adapter handle immediately, before
waiting for the main loop to reach a later shutdown checkpoint.

### PTY adapter: capable terminal, not screen parser ([SUM-7.4])

`extensions/taut_summon/taut_summon/_pty.py` is the default host for
interactive CLIs. It uses stdlib `pty.openpty()` and
`subprocess.Popen(..., start_new_session=True)`; no `pexpect`, `ptyprocess`,
`tmux`, or screen emulator is in the dependency surface. The child sees a real
PTY with `TERM=xterm-256color`, and the parent owns exactly one master fd.

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

The pump start point depends on who owns the PTY master. In detached/no-tty
operation there is no human bridge reading the master, so the pump starts
immediately after spawn, before `rejoin` and thread bootstrap. That keeps the
terminal-query responder live while SQLite and queue setup run. In the first-run
attach path, the attach bridge owns the master until the detach chord; only then
does the driver start the pump. Keeping those paths distinct preserves the
single-reader invariant while avoiding early TUI query timeouts.

Injection is keyboard input, so it is sanitized before framing: CR/CRLF
canonicalize to LF, C0 controls except LF are stripped, `DEL` and `ESC` are
removed, and tab becomes a space. If the harness enabled bracketed paste, LF is
preserved inside paste framing; otherwise LF collapses to spaces so one chat
message is one submitted turn. Orientation is the first injected turn for PTY
(`orientation_via_inject=True`), after the pump starts and settle observes the
reader's `last_output_ts`, but before the watcher starts. If STOP or SIGINT
races this pre-watch orientation step, the driver interrupts the handle and
treats an interrupted `inject()` as a clean stop. Structured adapters keep the
spawn-time system-prompt path.

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

The fd lifecycle is the load-bearing boundary. `PtyHandle.close()` always
signals and reaps the child, but closes the master only if no reader has
started. Once the pump owns the master, the reader closes it on EOF/EIO. The
driver closes the handle and joins any already-started pump on exceptions
through bootstrap and the pump hand-off, so a failed rejoin or thread join
cannot leak a master fd or leave a zombie. Stream and PTY handles publish their
closing state before signaling, so injections that begin after close starts
fail synchronously; concurrent close callers observe the same terminal result.

Write-side fd lifetime is carried by lifecycle-registered operation tokens and
duplicated master fds. Normal writers snapshot their epoch before serialization,
lease a duplicate under the reentrant lifecycle lock, and perform nonblocking
write/wait syscalls outside it. Interrupt registers before attempting its dup
and holds that token through Ctrl-C plus fallback; close atomically leases its
own graceful Ctrl-C fd while publishing retirement, releases its own token,
drains external tokens, then escalates and reaps. This makes cancellation
non-starving without letting canonical-fd close or numeric reuse redirect an
in-flight syscall. Reader-side canonical ownership remains unchanged. Epoch and
retirement state are rechecked after successful and failed syscalls so a
published cancellation outranks concurrent reader close and a stale lower-level
fd diagnostic. At completion, the writer rechecks its epoch and retires its
operation token in one lifecycle-lock action. Cancellation published before
that linearization point makes the call fail even when its final bytes were
already transferred; cancellation after it applies only to later calls.

### Attach/detach and `wired` ([SUM-7.4], [SUM-8])

First PTY use is not guessed from output. The session row carries a durable
`wired` boolean (`SUMMON_SCHEMA_VERSION` 3; introduced in version 2). A not-yet-wired first generation
with a real tty attaches the human terminal to the harness; the human answers
trust/login/model prompts and detaches with the non-`ESC` chord
`Ctrl-\ Ctrl-\`. Only that explicit detach sets `wired=True`. Future summons
go detached. `--attach` forces setup, while `--detach` forces detached mode.

The bridge is a single select loop over the human tty, PTY master, and a
shutdown waker pipe. It is not two blocking copy threads, because STOP must be
observable during attach. It never intercepts `ESC` sequences. In `finally`, it
writes a fixed reset blast to the local tty and restores termios, because the
harness keeps running and will not clean up the user's terminal after detach.
`TAUT_HOST_TUI=1` is the cooperative marker for taut-owned host TUIs to refuse
nested attach.

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
  creation, [SUM-6]), provider, provider session id, driver liveness
  evidence, and the PTY `wired` flag.

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
harness because STOP's path closes the adapter handle, which the [SUM-7.1]
contract requires to unblock the in-flight write.

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
or an unexpected clean return stops the watcher, interrupts the adapter, wakes
the foreground supervisor, and exits nonzero after normal release cleanup.
Expected STOP and driver shutdown remain clean exits. Control failure never
spends the watcher-rebuild or provider-resume budgets.

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

PTY and stream close machines stay separate because their resources and
interrupt mechanisms differ (fd epochs and terminal signals versus pipes and
structured streams). STATUS reserved keys also remain separate from adapter
display fields: they protect control-protocol ownership, not resource closure.
The release-evidence predicate is shared because ledger release and CLI polling
answer the same ownership question; those other similar-looking sets do not.

### SimpleBroker handle ownership, not a Taut retry layer ([TAUT-3.4])

Summon follows the same ownership rule as Weft's `BaseTask`: SimpleBroker owns
queue mechanics and retry; Taut owns domain state, control correlation, and
handle lifetime. `TautClient.queue()` returns a plain `simplebroker.Queue`.
Long-lived actors use persistent owned handles: the chat watcher, summon
control loop, driver ledger client, watcher client, and terminal-mode mouth
client. One-shot paths use transient handles: ordinary `taut say`, CLI
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
SimpleBroker 5.3.0 is the minimum supported runtime. Its reference reactor and
persistent session design provide one process-local session with
owner-thread-local cores;
the 5.1.x per-operation release pattern was buggy and is unsupported.

The real-process test harness follows the same posture. Readiness is a
correlated PING/STATUS reply from the expected driver evidence; session rows and
logs are diagnostics. The harness must not hide a malformed session row as "not
ready" and must not create tight fresh-client polling loops that amplify SQLite
connection churn.

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
`taut.addressing`, `taut.envelope`, and `taut.watcher` seams. The adapters
supervise real child processes over real pipes; the shared stream-json plumbing lives
in `extensions/taut_summon/taut_summon/_stream.py` so both shipped adapters
share the [SUM-7.1] handle mechanics (flushed inject, thread-safe
interrupt/close, single-consumer events) once.

The extension CLI keeps one documented argparse inventory for `run`, `stop`,
and `status`. Root help owns exit classes; each subcommand owns its syntax and
database-selection guidance. Omitting `--db` explicitly means normal Taut
discovery from the current directory through its ancestors. The root parser's
special `run` dispatch still uses the standalone intermixed parser required by
Python 3.11/3.12, and `_add_run_arguments()` supplies the same description and
action help to both parser instances. Parser inventory and phrase tests prevent
the executable help surface from drifting while preserving verbatim `--` tails.

## Boundaries and Invariants

- **Core changes are exactly two spec-text deltas plus the two delegation
  verbs.** `summon`/`dismiss` in core carry zero summon logic and add no
  dependency; they find-and-hand-off to `taut_summon` or exit 1 with an
  install hint. Any other core code change is a stop-and-re-plan gate.
- **No daemon** ([TAUT-2]): the driver is foreground; `stop`/`status` are
  clients, not services.
- **Mouth is CLI-only** ([SUM-6]): no extension code path posts chat under
  the member's identity except terminal mode, which is single-thread by
  construction.
- **No summon wire protocol**: adapters translate provider-native streams
  into the closed `AdapterEvent` union; a summon envelope would be drift.
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
  chord. External PTY harnesses have a default local readiness probe and
  an opt-in strict mode (`TAUT_SUMMON_LIVE_HARNESS_STRICT=1`) that prewires
  the temp database and fails on readiness or injection catch-up gaps.
- **Weft congruence is contract, not code**: STOP/STATUS/PING verbs and
  queue roles per [SUM-9]; no weft imports, no vendored weft agent code.

## Key Files

| Path | Owner |
|---|---|
| `extensions/taut_summon/taut_summon/cli.py` | `run`/`stop`/`status` argparse, [SUM-3] name/provider resolution, exit-code mapping |
| `extensions/taut_summon/taut_summon/_driver.py` | Bootstrap ([SUM-4]), ears watch handler, event pump, resume, shutdown; `format_injection` ([SUM-5.2]) |
| `extensions/taut_summon/taut_summon/_state.py` | The two-table ledger, claim/session helpers, single-driver guard evidence ([SUM-8]) |
| `extensions/taut_summon/taut_summon/_control.py` | Fixed `_ControlReactor`, between-turn replacement supervisor, client, `sys.*` queue derivation, rate backstop ([SUM-9]/[SUM-10]/[SUM-11]) |
| `extensions/taut_summon/taut_summon/_adapter.py` | `ProviderAdapter` protocol, `AdapterEvent` union, adapter registry ([SUM-7.1]) |
| `extensions/taut_summon/taut_summon/_stream.py` | Shared stream-json child-process handle mechanics for both adapters |
| `extensions/taut_summon/taut_summon/_pty.py` | Universal interactive PTY adapter, terminal-query responder, attach bridge, and PTY fd lifecycle |
| `extensions/taut_summon/taut_summon/_scripted.py` | The `scripted` test adapter (real subprocess, fake model) — the anti-mocking seam |
| `extensions/taut_summon/taut_summon/scripted_provider.py` | The scripted provider program spawned as the harness child |
| `extensions/taut_summon/taut_summon/_claude.py` | The `claude-stream` adapter: headless stream-json, resume, event translation |
| `extensions/taut_summon/taut_summon/_persona.py` | The default persona template ([SUM-10]) and env assembly |
| `extensions/taut_summon/tests/conftest.py` | The shared real-process driver harness (`DriverProcess`) and fixtures |
| `extensions/taut_summon/tests/test_conformance.py` | The portable, parameterized [SUM-12] conformance suite |
| `extensions/taut_summon/tests/test_live_local_llm.py` | The CI-safe local-LLM PTY smoke: loopback model endpoint, counting proxy, orientation, and `taut say` sentinel |

## Spec-Code Trace

| Spec area | Primary code owners | Contract tests |
|---|---|---|
| [SUM-3], name/provider resolution, CLI help, database discovery, and exit classes | `extensions/taut_summon/taut_summon/cli.py` | `extensions/taut_summon/tests/test_summon_cli.py` parser-inventory, help-phrase, grammar, discovery, and exit-class tests |
| [SUM-4], bootstrap, identity, presence | `extensions/taut_summon/taut_summon/_driver.py`, `extensions/taut_summon/taut_summon/_state.py` | `extensions/taut_summon/tests/test_driver.py` |
| [SUM-5], ears injection contract | `extensions/taut_summon/taut_summon/_driver.py` | `extensions/taut_summon/tests/test_driver.py`, `extensions/taut_summon/tests/test_conformance.py` |
| [SUM-6], mouth CLI contract | `extensions/taut_summon/taut_summon/_driver.py`, `extensions/taut_summon/taut_summon/_persona.py` | `extensions/taut_summon/tests/test_driver.py`, `extensions/taut_summon/tests/test_persona.py` |
| [SUM-7.1], [SUM-7.2], adapters | `extensions/taut_summon/taut_summon/_adapter.py`, `extensions/taut_summon/taut_summon/_stream.py`, `extensions/taut_summon/taut_summon/_pty.py`, `extensions/taut_summon/taut_summon/_scripted.py`, `extensions/taut_summon/taut_summon/_claude.py` | `extensions/taut_summon/tests/test_scripted_adapter.py`, `extensions/taut_summon/tests/test_claude_adapter.py`, `extensions/taut_summon/tests/test_pty_adapter.py` |
| [SUM-7.4], PTY shell adapter | `extensions/taut_summon/taut_summon/_pty.py`, `extensions/taut_summon/taut_summon/_driver.py` | `extensions/taut_summon/tests/test_pty_adapter.py`, PTY cases in `extensions/taut_summon/tests/test_driver.py`, `extensions/taut_summon/tests/test_live_harness.py` |
| [SUM-8], session ledger and guard | `extensions/taut_summon/taut_summon/_state.py` | `extensions/taut_summon/tests/test_state.py`, `extensions/taut_summon/tests/test_driver.py` |
| [SUM-9], [SUM-10], [SUM-11], control lifecycle, backstop, recovery, and fatal supervision | `extensions/taut_summon/taut_summon/_control.py::_ControlReactor`, `extensions/taut_summon/taut_summon/_control.py::ControlLoop`, `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._run_control_loop`, `_report_control_failure`, `_raise_if_control_failed` | `extensions/taut_summon/tests/test_control.py` fixed topology, ownership, native wake, inter-turn recovery, audit, partial-bundle, and close tests; `extensions/taut_summon/tests/test_driver.py::test_control_loop_exception_is_driver_fatal`, `test_unexpected_clean_control_loop_return_is_driver_fatal`, `test_initial_control_open_failure_is_driver_fatal`, and real-process fatal-control/STOP/PING cases |
| [SUM-12], conformance | (all of the above) | `extensions/taut_summon/tests/test_conformance.py`, `extensions/taut_summon/tests/test_live_harness.py`, `extensions/taut_summon/tests/test_live_local_llm.py` |

## Change Guidance

Read `docs/specs/04-summon.md` and the summon plan before editing. The
injection format ([SUM-5.2]) and the ledger schema are the stickiest
contracts — treat a post-ship change to the injection format as a spec
revision, not a tweak, and version any ledger schema change under
`summon_schema_version`. Prefer extending the driver's three lanes over
adding a fourth; new provider behavior belongs in an adapter, never in a
summon-defined protocol.

Before completion, run the extension gate block from the summon plan's §10
(the extension suite, the core suite untouched-green, ruff/format/mypy over
the extension paths, and `uv build extensions/taut_summon`). Keep the
deterministic process, external-live, and local-LLM lanes under xdist, but run
them as separate one-worker pytest invocations: they start multiple real
processes against temporary SQLite sidecars, so worker fan-out or one very long
worker tests host storage pressure more than summon behavior. Release prechecks
also set `TAUT_SUMMON_LIVE_HARNESS_STRICT=1` locally for the external-live lane
so installed provider CLIs fail instead of skipping when detached onboarding
would otherwise be reported as not ready. The external-provider live lane proves
detached readiness and injection catch-up; the local LLM lane is the
deterministic sentinel-posting proof. CI mirrors this boundary by running the
deterministic process selector in a fresh `taut-summon process` matrix job,
rather than after the broad root and summon unit suites in the same runner.

## Related Plans

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
