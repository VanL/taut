# Taut Summon Architecture

## Purpose and Scope

This document explains the implementation boundary of the `taut-summon`
extension (`extensions/taut_summon/`): how a summoned agent harness is hosted
as an ordinary workspace member without a daemon, a bespoke agent protocol, or
any change to frozen core state. It covers the ears/mouth split, the
captive-process/free-agent posture, the driver's three-thread runtime, the
two-table session ledger, the `sys.*` control queues, the vendored broker
retry, and the SimpleBroker-facade boundary the extension holds to.

It does not restate the contract — that lives in the spec
(`docs/specs/04-summon.md`, [SUM-1]–[SUM-12]). It explains *why* the code is
shaped the way it is, and where to read and edit.

Implementation status: the extension ships `run`/`stop`/`status`, the
scripted adapter, the universal PTY adapter for interactive harnesses, the
`claude-stream` structured adapter, the driver (bootstrap, attach/detach,
ears, event pump, resume, shutdown), the persona template, the control
plane, and the rate backstop.

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
speak by running the ordinary `taut` CLI (the **mouth**). This is the single
most load-bearing decision in the design, and it is why the extension needs
no wire protocol and no core changes beyond two delegation verbs.

The ears are an injected stream. `extensions/taut_summon/taut_summon/_driver.py`
watches, over the public `TautClient.watch(...)` surface, every thread the
member has joined plus its notification inbox, and pushes each message into
the child's stdin as a user-role event ([SUM-5]). The mouth is credential,
not code: the child environment carries `TAUT_TOKEN` (the member's
continuity token, [SUM-6]) and, on path-addressed backends, `TAUT_DB`; the
agent runs `taut say ...` like a human. The driver never posts chat on the
member's behalf outside terminal mode — a hard invariant, because two
speakers under one identity is the double-speak failure ([SUM-6]/[SUM-9]).

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
   The driver's readiness boundary is the watcher's initial drain, not thread
   construction: `TautWatcher.notify_ready_after_initial_drain()` signals after
   the polling strategy is started and the first drain has completed, and only
   then does the driver log `summoned ...`. Tests and operators may use that log
   as a readiness marker because it is downstream of the consumer-ready event,
   not because logging itself synchronizes the watcher.
   `TautWatcher` deliberately uses the core data-version polling path rather
   than the broker-native multi-queue activity waiter: a native waiter can miss
   a write that lands before the first wait call is armed, while data-version
   polling sees database-wide changes across all watched queues.
2. **Event pump — a dedicated drain thread.** Consumes `events()` for the
   life of the child ([SUM-7.1]): session ids to the ledger, `activity` to
   member liveness via a rate-limited token-selected `whoami()` (the public
   [IAN-3.3] side effect — never a private `_state` reach), assistant text to
   the thread in terminal mode or the log otherwise, and `exit` to the
   [SUM-11] resume path. An undrained stream is a child-stdout deadlock; the
   pump exists to prevent it and participates in shutdown ordering.
3. **Control plane — its own consumer thread.** See below.

The backstop audit ([SUM-10]) rides the control thread, not the ears,
because the watch stream never delivers the member's own sends ([TAUT-7.4]
advances the sender cursor at write time), so counting in the handler would
be mechanically inert.

Shutdown ordering (shared by SIGINT and control STOP): stop injection →
adapter interrupt (unblocks any in-flight `inject()`) → pump drains to `exit`
or a bounded timeout → ownership-checked ledger release → exit 0.

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
STATUS after checking reserved keys.

Injection is keyboard input, so it is sanitized before framing: CR/CRLF
canonicalize to LF, C0 controls except LF are stripped, `DEL` and `ESC` are
removed, and tab becomes a space. If the harness enabled bracketed paste, LF is
preserved inside paste framing; otherwise LF collapses to spaces so one chat
message is one submitted turn. Orientation is the first injected turn for PTY
(`orientation_via_inject=True`), after the pump starts and settle observes the
reader's `last_output_ts`, but before the watcher starts. Structured adapters
keep the spawn-time system-prompt path.

The fd lifecycle is the load-bearing boundary. `PtyHandle.close()` always
signals and reaps the child, but closes the master only if no reader has
started. Once the pump owns the master, the reader closes it on EOF/EIO. The
driver guards the whole `spawn → pump.start` span with `handle.close()` on
exception, so a failed rejoin or thread join cannot leak a master fd or leave a
zombie.

### Attach/detach and `wired` ([SUM-7.4], [SUM-8])

First PTY use is not guessed from output. The session row carries a durable
`wired` boolean (`SUMMON_SCHEMA_VERSION` 2). A not-yet-wired first generation
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
  `(name, provider)` primary key. This is the concurrent-summon
  serialization point ([SUM-4] step 0): a losing racer takes the constraint
  error and applies the collision rule. Deleted at bootstrap step 3; a row
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

Every summon state helper wraps its complete sidecar operation in the
extension's narrow broker retry policy. The retry boundary includes row parsing,
not just SQL execution: a false SQLite malformed-page read can surface as a
wrong-shaped row before SimpleBroker raises `DatabaseError`. The parser converts
that shape failure into the same `malformed` `DatabaseError`, so it retries
inside the bounded budget and still surfaces if the row is persistently broken.

The bootstrap's six-step order ([SUM-4]) resolves three constraints at once:
the token/env cycle (the token must exist before the child is spawned with
it), the concurrent-summon race, and the never-touch-a-foreign-member rule.
Creation happens under a driver-generated collision-proof **temp name** —
a fresh name cannot adopt anything — followed by core's transactional
`set_name()` to take the target. The single cosmetic cost is one temp-name
join notice.

### Control plane: unregistered `sys.*` queues, weft-congruent verbs ([SUM-9])

`extensions/taut_summon/taut_summon/_control.py` mirrors Weft's task
control-queue contract by *shape*, never by code: verbs STOP / STATUS / PING,
single-line JSON bodies keyed `command`/`request_id`, replies correlating by
`request_id` with a `status` field. The queues derive from the member id
(`sys.ctl_<member-id>` in, `sys.rsp_<member-id>` out) under the `sys` prefix
[TAUT-4.1] reserves, and are deliberately **unregistered** ([IAN-6.1] as
amended by the plan's D3): they are invisible broker queues to every core
command — the same treatment as foreign queues — so the extension's write
surface is exactly its own tables plus plain broker queues, needing no core
seam. A debugging agent still finds them with `broker -f .taut.db list`
([TAUT-3.4]).

The driver consumes control with its own `read_one` consumer (at-most-once:
a command lost to a driver crash is moot — STOP on a dead driver is
meaningless, and STATUS/PING requesters retry). `TautClient.watch` is
chat-only and knows nothing about `sys.*`. Replies go to a **per-request**
queue `sys.rsp_<member-id>_<request_id>` so concurrent clients from different
terminals never consume each other's answers. Reply writes use a larger
transient-broker retry budget than ordinary reads/writes: dropping a STATUS
reply after a short SQLite contention window makes a healthy driver look
unresponsive to the client. The control thread stays responsive while an
`inject()` is blocked on a stalled harness because STOP's path closes the
adapter handle, which the [SUM-7.1] contract requires to unblock the in-flight
write.

The rate backstop ([SUM-10]) is a circuit breaker, not a content policy: a
driver-local audit cursor per thread counts `from_id == self` messages on the
control cadence; a soft breach injects a nudge and logs, a hard breach
interrupts the harness and surfaces through STATUS plus logs — never posting
to chat and never leaving an unconsumed control reply. A
documented limitation: coverage is the startup thread set (late-joined
threads are not audited), because a per-tick `list_threads()` re-records the
member's continuity claim and races the watcher on a UNIQUE constraint; the
state layer now treats same-member claim insert races as idempotent, but
late-join audit expansion remains deliberately out of scope for this release.

### The vendored retry: layering, not reaching ([TAUT-3.4])

The added control thread raised WAL concurrency enough to surface a *false*
`malformed`-page read a fresh reader can see mid-checkpoint — a
`DatabaseError` that does not subclass `OperationalError`, so SimpleBroker's
own watcher-retry predicate misses it too. Taut's facades-only rule forbids
importing `simplebroker._retry`, so the generic engine is **vendored
byte-identical** into `extensions/taut_summon/taut_summon/_retry.py` (its
`__version__` documents the vendored version for re-vendoring), and the
taut-summon policy (`is_transient_broker_error` + `broker_retry`) sits on top
in `extensions/taut_summon/taut_summon/_broker_retry.py` — exactly as
`simplebroker/helpers.py` layers its own policy over the same engine. The
predicate is narrowed to the two known transients by message marker and
honors the `retryable` attribute; it also recognizes SimpleBroker's
connection-open `RuntimeError("Failed to get database connection: ...")`
wrapper only when the wrapped message carries one of those same markers. Thus
genuine corruption still surfaces rather than dying silent. Control-drain
failures are split by recovery boundary: non-recoverable faults mark
`control_health: degraded` immediately because STOP/STATUS/PING depend on that
path; recoverable long-lived-handle faults close and reopen the driver's broker
handles so queued requests can be consumed on the next cadence, and degrade
only after repeated consecutive failures. Rate-audit failures use the same
recoverable boundary. The audit is a backstop, so a single skipped pass under
heavy local process churn is logged and retried without making a live driver
look control-dead.

`taut-summon stop/status` use that same policy while resolving the current
member name and while writing/reading control replies. If the bounded budget is
exhausted on a known transient, the CLI reports an exit-1 control failure rather
than leaking a Python traceback; if the error is outside the narrow predicate,
it still propagates.

### SimpleBroker facade boundary

The extension holds to core's dependency posture: it imports from
`simplebroker` and `simplebroker.ext` only (plus the one vendored engine
above), runs no SQL against broker-owned tables, and touches core solely
through public `TautClient`/`taut.identity` seams. The adapters supervise
real child processes over real pipes; the shared stream-json plumbing lives
in `extensions/taut_summon/taut_summon/_stream.py` so both shipped adapters
share the [SUM-7.1] handle mechanics (flushed inject, thread-safe
interrupt/close, single-consumer events) once.

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
  onboarding. External PTY harnesses have a default local readiness probe and
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
| `extensions/taut_summon/taut_summon/_control.py` | Control loop + client, `sys.*` queue derivation, rate backstop ([SUM-9]/[SUM-10]) |
| `extensions/taut_summon/taut_summon/_adapter.py` | `ProviderAdapter` protocol, `AdapterEvent` union, adapter registry ([SUM-7.1]) |
| `extensions/taut_summon/taut_summon/_stream.py` | Shared stream-json child-process handle mechanics for both adapters |
| `extensions/taut_summon/taut_summon/_pty.py` | Universal interactive PTY adapter, terminal-query responder, attach bridge, and PTY fd lifecycle |
| `extensions/taut_summon/taut_summon/_scripted.py` | The `scripted` test adapter (real subprocess, fake model) — the anti-mocking seam |
| `extensions/taut_summon/taut_summon/scripted_provider.py` | The scripted provider program spawned as the harness child |
| `extensions/taut_summon/taut_summon/_claude.py` | The `claude-stream` adapter: headless stream-json, resume, event translation |
| `extensions/taut_summon/taut_summon/_persona.py` | The default persona template ([SUM-10]) and env assembly |
| `extensions/taut_summon/taut_summon/_retry.py` | Vendored byte-identical `simplebroker._retry` engine (re-vendor via `__version__`) |
| `extensions/taut_summon/taut_summon/_broker_retry.py` | The taut-summon retry policy layered over the vendored engine |
| `extensions/taut_summon/tests/conftest.py` | The shared real-process driver harness (`DriverProcess`) and fixtures |
| `extensions/taut_summon/tests/test_conformance.py` | The portable, parameterized [SUM-12] conformance suite |
| `extensions/taut_summon/tests/test_live_local_llm.py` | The CI-safe local-LLM PTY smoke: loopback model endpoint, counting proxy, orientation, and `taut say` sentinel |

## Spec-Code Trace

| Spec area | Primary code owners | Contract tests |
|---|---|---|
| [SUM-3], name/provider resolution and CLI exit classes | `extensions/taut_summon/taut_summon/cli.py` | `extensions/taut_summon/tests/test_summon_cli.py` |
| [SUM-4], bootstrap, identity, presence | `extensions/taut_summon/taut_summon/_driver.py`, `extensions/taut_summon/taut_summon/_state.py` | `extensions/taut_summon/tests/test_driver.py` |
| [SUM-5], ears injection contract | `extensions/taut_summon/taut_summon/_driver.py` | `extensions/taut_summon/tests/test_driver.py`, `extensions/taut_summon/tests/test_conformance.py` |
| [SUM-6], mouth CLI contract | `extensions/taut_summon/taut_summon/_driver.py`, `extensions/taut_summon/taut_summon/_persona.py` | `extensions/taut_summon/tests/test_driver.py`, `extensions/taut_summon/tests/test_persona.py` |
| [SUM-7.1], [SUM-7.2], adapters | `extensions/taut_summon/taut_summon/_adapter.py`, `extensions/taut_summon/taut_summon/_stream.py`, `extensions/taut_summon/taut_summon/_pty.py`, `extensions/taut_summon/taut_summon/_scripted.py`, `extensions/taut_summon/taut_summon/_claude.py` | `extensions/taut_summon/tests/test_scripted_adapter.py`, `extensions/taut_summon/tests/test_claude_adapter.py`, `extensions/taut_summon/tests/test_pty_adapter.py` |
| [SUM-7.4], PTY shell adapter | `extensions/taut_summon/taut_summon/_pty.py`, `extensions/taut_summon/taut_summon/_driver.py` | `extensions/taut_summon/tests/test_pty_adapter.py`, PTY cases in `extensions/taut_summon/tests/test_driver.py`, `extensions/taut_summon/tests/test_live_harness.py` |
| [SUM-8], session ledger and guard | `extensions/taut_summon/taut_summon/_state.py` | `extensions/taut_summon/tests/test_state.py`, `extensions/taut_summon/tests/test_driver.py` |
| [SUM-9], [SUM-10], control plane and backstop | `extensions/taut_summon/taut_summon/_control.py`, `extensions/taut_summon/taut_summon/_broker_retry.py`, `extensions/taut_summon/taut_summon/_retry.py` | `extensions/taut_summon/tests/test_control.py`, `extensions/taut_summon/tests/test_driver.py` |
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
real-process and local-LLM lanes under xdist, but run them as one-worker lanes:
they start multiple real processes against temporary SQLite sidecars, so worker
fan-out tests host pressure more than summon behavior. Release prechecks also
set `TAUT_SUMMON_LIVE_HARNESS_STRICT=1` locally so installed external provider
CLIs fail instead of skipping when detached onboarding would otherwise be
reported as not ready. The external-provider live lane proves detached
readiness and injection catch-up; the local LLM lane is the deterministic
sentinel-posting proof.

## Related Plans

- `docs/plans/2026-07-06-taut-summon-plan.md` — the implementing plan
  (spec promotion, extension package, delegation verbs, ledger, adapters,
  driver, control plane, conformance suite)
- `docs/plans/2026-07-07-taut-summon-pty-harness-adapter-plan.md` — the
  universal PTY adapter, attach/detach, `wired` schema, provider registry, and
  live harness conformance plan
