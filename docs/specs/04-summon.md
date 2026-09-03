# Taut Summon Specification

Date: 2026-07-06

Status: Active

Promoted on 2026-07-06 from the summon plan's reviewed spec draft
(`docs/plans/2026-07-06-taut-summon-spec-draft.md`).

Design lenses applied to every decision below, recorded once here and cited
as **(L1)** and **(L2)** throughout:

- **L1 — agent-usable:** does this work for an agent operating the system —
  the summoned agent itself, other agents in the chat, and agents reading
  this spec to implement or debug it?
- **L2 — person-shaped:** does the observable behavior match what a human
  member would do in the same situation?

## 1. Purpose and Scope [SUM-1]

`taut summon` hosts any interactive agent CLI as an ordinary member of a
taut workspace. Summon does not build an agent loop, a task runtime, a
provider protocol adapter, or a sandbox; the harness already owns tool
dispatch, session state, interruption, and permissions. Summon is the agent's **terminal**:
it feeds chat into the harness's own control loop, and the agent speaks
through the same CLI verbs a human uses, selected as its member by its
continuity token ([TAUT-5]: continuity, never authentication).

Primary use case: unattended participants in collaborative human +
multi-agent development — a standing reviewer, a commentator, an
implementer that keeps working while hearing comments. Interactive
human-driven sessions do not need summon; they participate via the
documented CLAUDE.md pattern (README, "Working With Agents").

Out of scope for this spec: sandboxing (a pipe-command wrapping concern,
not an architecture), multi-host summon, provider SDKs (CLI adapters
only), and any daemon.

## 2. Mental Model [SUM-2]

**Ears and mouth.** The summoned member's *ears* are an injected stream: the
summon driver watches every thread the member has joined plus its notification
inbox and pushes each message into the harness's live terminal. The ordinary
member *mouth and hands* are the taut CLI itself. The agent speaks by running
`taut say`, `taut reply`, or another explicit Taut command, selected as its
member by its continuity token. Summon never interprets or routes terminal
output as speech.

**The driver is a terminal emulator, not a manager.** One foreground
process per summoned member, exactly like `taut watch`: it exists while
the agent is summoned and is zero processes otherwise. The no-daemon
property of [TAUT-2] holds end to end.

**A summoned agent is just a member.** Identity, cursors, presence,
mentions, DMs, and history work identically to a human member. Every
capability difference between a summoned agent and a human member is a
spec defect (L2 stated as an invariant).

**Captive process, free agent.** The harness child is a captive process: the
driver spawns it on an operating-system pseudoterminal, owns its terminal I/O,
signals it, anchors presence to it, and retires its terminal domain. The
terminal output is read only for coarse activity, bounded terminal-query
replies, attach display, and diagnostics. Conversation state belongs to the
harness and is not parsed or persisted by Summon.

Lifecycle captivity includes the provider leader and descendants that remain
attached to its terminal domain. POSIX retains the process-group guarantee
defined in [SUM-7.4]. Windows owns one ConPTY session and closes that session
while its output remains drained; the real-process acceptance test must show
that an attached descendant is absent afterward. Neither mechanism is a
sandbox and neither chases a process that deliberately escapes its platform
terminal domain.

## 3. Packaging [SUM-3]

- Ships as the separate extension distribution **`taut-summon`**
  (`extensions/taut_summon`), per [TAUT-12.3]. Its sole core runtime
  dependency is distribution `taut-chat`; the imported package remains
  `taut`. It adds no third-party runtime package beyond the existing provider
  requirements. The provider harness is an external executable, not a
  dependency.
- Summon's Windows ConPTY support uses the operating-system API through a
  narrow standard-library boundary and adds no runtime package.
- Surface: the separately installed `taut-summon` distribution registers two
  first-party command slots through the core `taut.commands` entry-point
  interface ([TAUT-8.6]):

```text
taut summon PROVIDER_OR_NAME [THREAD ...] [flags]   # default thread: general
taut dismiss NAME
```

  Core supplies only the absent-package install hint; it contains no Summon
  domain logic and does not delegate to an older extension CLI. Current
  Summon entry points own both reserved command slots.
- The extension also installs `taut-summon run|stop|status`. Both console
  surfaces are adapters over the public [SUM-13] controller. They share
  request models, provider/name resolution, results, error semantics, and
  tests; neither console surface invokes the other's `main()` or parses the
  other's output.

  Both first-party console surfaces use `taut.escape_terminal_text` for
  Taut-owned dynamic human text and diagnostics under [TAUT-6.4]. JSON/domain
  values remain exact.

  `taut summon X ...` remains behaviorally equivalent to
  `taut-summon run X ...`, and `taut dismiss X` remains equivalent to
  `taut-summon stop X`. Both surfaces share one resolution contract:
  `run NAME_OR_PROVIDER [THREAD ...]` — the positional is always the
  **member name**; the provider resolves in order: (1) `--provider`
  when given (a re-summon whose session row disagrees is an error
  naming the stored provider — members do not switch harnesses
  implicitly); (2) the existing session row's stored provider (the
  re-summon case: `taut summon reviewer` just works after
  `taut summon reviewer --provider claude`); (3) the name itself when
  it matches a registered adapter (the first-summon convenience);

  For [TAUT-13] debug capture, the installed `taut summon` and `taut dismiss`
  paths use the core command-dispatch containment point. The standalone
  `taut-summon` process calls the same core handler only for an unexpected
  `Exception` escaping its existing handled-error paths. Neither console calls
  the handler for a normal typed operation result.
  (4) otherwise an error naming the known adapters. Name-collision
  behavior depends on whether the name was chosen or implied
  ([SUM-4] states the rule; summarized): the convenience form
  (`taut summon claude`, name implied by the provider) falls back
  through the [IAN-9] pool — a second Claude becomes `Claudette` or
  `Claude-2`, with a console note; an explicitly chosen name
  (`--provider` given) that collides with a non-summoned member
  refuses loudly instead. Default thread `#general` unless threads are
  given; `taut summon reviewer --provider claude dev` names the member
  `reviewer`, re-summonable thereafter by name alone.
  An implied provider name is an automatically generated display name under
  [IAN-4.2]. `taut summon pi` therefore starts with member name `Pi`, while
  `taut summon reviewer --provider pi` preserves the explicitly chosen
  `reviewer`. Provider registry keys remain lowercase and do not change when
  the member display name is capitalized.
## 4. Identity, Membership, and Presence [SUM-4]

- The member's identity evidence is **ultimately the harness child process**.
  After bootstrap `rejoin()` points the anchor at that child. Before spawn, a
  driver-anchored agent capture creates the member and obtains the continuity
  token required in the child environment. The seam is public:
  `taut.identity` capture types, `capture_process`, and `route_key`, feeding
  `TautClient(identity_capture=...)`.
  - **Name resolution before anything else**: the driver resolves the
    requested name through core (public `who()`/route lookup) to a
    current `member_id`, then reads `taut_summon_sessions` by that id.
    A session row → the re-summon path (bootstrap steps 4-5). A member
    exists but has no session row → the name belongs to a non-summoned
    member and is **never adopted**; what happens next depends on
    whether the user chose the name (the single collision rule, which
    [SUM-3] summarizes):
    - *Implied name* (the convenience form — positional == provider,
      as in `taut summon claude`): fall back through
      **`taut.identity.choose_name()`** — blessed for extensions here
      alongside the capture surface — seeded with the requested name
      against the names in use, with a console note
      (`summoned as 'Claudette' — 'claude' is taken`). The user asked
      for *a* claude, not that exact string (L2).
    - *Chosen name* (`--provider` given, so the positional was a
      deliberate choice): refuse loudly with the collision and a hint
      to pick another name. Silently renaming a name the user chose
      would surprise both people and scripts (L1, L2).
    This chosen-name refusal applies at resolution time, before anything is
    created. A collision that appears after the transient claim is handled the
    same way for implied and chosen names: release that claim, choose the
    documented loud fallback, and retry. A chosen name bypasses automatic
    selection at initial resolution and refuses an already-visible collision.
    If a route collision appears only after its transient claim was acquired,
    the fallback is automatic and therefore uses [IAN-4.2] display casing for
    both implied and initially chosen requests.
  - **Bootstrap ordering** resolves the token/env cycle, the concurrent-summon
    race, and the rule that a foreign member must never be adopted:
    0. *Claim the name*: transactionally insert (name key, provider) into
       the transient claims table ([SUM-8]). The claim boundary normalizes the
       display candidate to its lowercase [IAN-4.2] route key, so `Claude` and
       `claude` serialize through one slot. A loser of a concurrent
       same-name summon gets the constraint error and applies the
       collision rule above — nothing exists yet, so it applies
       cleanly: an implied name retries with the `choose_name`
       fallback (two simultaneous `taut summon claude` yield two
       members, never one shared member); a chosen name refuses loudly
       (two simultaneous `taut summon reviewer --provider claude`
       yield one `reviewer` and one clean refusal). Claims from dead
       drivers are reclaimable by evidence.
    1. *Create under the claimed final name* — first summon only:
       `TautClient(identity_capture=<driver capture>,
       as_name=<claimed-final-name>).join(thread, new=True)`. Core's
       fail-not-adopt behavior ([IAN-3.3]) makes this atomic with respect to the
       visible route: if occupied, no member, membership, or notice is created.
       The driver releases the claim, chooses the next allowed fallback, and
       retries. A successful create yields the token and final visible name in
       one step. Summon never creates a temporary visible member and never
       deletes a partially visible member as collision cleanup.
    2. *Join remaining requested threads* before publishing readiness.
    3. *Record the session*: insert the member-id-keyed sessions row
       ([SUM-8]) and delete the claim row — old names become claimable
       again the moment they are no longer load-bearing.
    4. *Spawn the harness* with `TAUT_TOKEN=<ledger token>` in its
       environment ([SUM-6]).
    5. *Re-anchor to the child*: `TautClient(identity_capture=
       <child capture>, token=<ledger token>).rejoin()` — token-only
       selection (`rejoin` rejects a name combined with a token by
       contract, [TAUT-8.1]); rejoin re-associates the child as the
       member's anchor through the public path ([IAN-3.4]).
    Each candidate attempt owns and closes exactly one creator client. A failure
    after member creation but before session publication may leave a final-named
    non-summoned member. The initiating terminal reports its name and continuity
    token; recovery is to use that token with `taut set name` to move the
    residual aside, then summon again. It is never adopted as a summoned
    session and no destructive rollback is attempted.
    Later summons resolve the current name to a member_id (public
    lookup), read the sessions row, and run exactly steps 4-5 — one
    shape for every summon, no private state calls anywhere.
    When re-summon receives `--persona`, it updates the existing member through
    a token-selected `TautClient.set_persona()` after the driver claim succeeds
    and inside the release-protected bootstrap path, before spawning. The
    returned member id must match the claimed session member. Claim loss never
    mutates persona; update failure spawns no child and releases normally. The
    update must not re-join a thread, write a notice, or move a cursor.
- Evidence-based presence then works unchanged: `taut who` shows `here`
  while the harness runs and `gone` after it exits, with no
  summon-specific presence code (L2: presence means the same thing for
  everyone).
- Thread membership is ordinary membership. **Positional `[THREAD ...]`
  is the canonical thread syntax at both entry points** (`taut summon
  PROVIDER [THREAD ...]` and `taut-summon run NAME [THREAD ...]`). The shared
  parser configuration preserves the same syntax on both surfaces; there is no
  `--thread` flag. Each is a convenience `join`, defaulting to `general` when
  none is given. The agent may `taut join`/`taut leave` on its own thereafter
  ([SUM-6]).

## 5. Ears — the Injection Contract [SUM-5]

### [SUM-5.1] Sources and ordering

The driver watches, via the public `TautClient.watch(...)` surface, every
chat thread the member has joined plus the member's notification inbox,
and injects events into the harness session in **watcher delivery
order** — the multi-queue watcher's merged order, which is per-thread
chronological but makes no global cross-thread timestamp guarantee.
Membership changes mid-run are picked up exactly as `taut watch` does.
Driver readiness is downstream of the watcher's first drain: a session row,
provider start, or watcher-thread start is not enough to prove the member is
hearing chat. The driver may log `summoned ...` only after that
consumer-ready boundary has fired.

### [SUM-5.2] Injection format

Each injected chat message is one user-role event carrying attribution
and location, rendered as:

```text
[#general] van: anyone awake?
[dm] bob: can you look at the parser branch?
[notify] mention by van in #ops (message 1837...024)
```

Notices inject in the same shape (`[#general] · claude joined`). The
format is part of this contract: agents write personas against it (L1)
and it mirrors how a person reads a channel — source, speaker, words
(L2). Exact rendering lives in one adapter-shared helper with tests.

Each chat event remains one user-role event. The first line uses the existing
source/speaker prefix; every continuation line in message text is indented so
content such as `[system]` cannot visually forge a new top-level driver frame.
Text is otherwise preserved. This is attribution hygiene, not prompt-injection
prevention or authorization.

### [SUM-5.3] Filtering

The driver injects **everything except the member's own messages**
(`from_id == self`, mechanical). It does not filter by sender kind: the
flagship reviewer case requires hearing other agents' status posts.
Restraint about *responding* is persona policy ([SUM-10]), not input
policy — a person hears the whole room and chooses when to speak (L2).
Per-thread input filters are not part of the current `run` surface. Adding
them requires a future spec and CLI revision; the present driver injects the
complete non-self stream.

### [SUM-5.4] Cursor as injection ledger

The member's per-thread cursors ([TAUT-7.2]) are the injection ledger,
and the mechanism is the watch surface's existing handler contract — the
driver adds **no cursor code of its own**. `TautWatcher` advances a
thread's cursor only after the user handler returns successfully; a
raising handler leaves the cursor in place and the message is re-seen
([TAUT-8.4]). The driver's watch handler is exactly: self-filter, format
([SUM-5.2]), `inject()`, return. (Rate-backstop counting is **not** in
this handler — the watch stream does not reliably observe the member's complete
own-send history, so [SUM-10] audits separately.) Consequences, all required:

- **At-least-once delivery to the harness process boundary:**
  `inject()` must not return until the event is written *and flushed* to
  the child's stdin, and must surface write failures synchronously — a
  failed or interrupted `inject()` raises out of the handler → cursor
  stays → the message re-injects on the next cycle. A driver killed
  between a successful inject and the watcher's cursor flush re-injects
  a small tail on restart (harnesses tolerate duplicate user messages
  far better than lost ones). Named residual: a harness that crashes
  *after* reading but before processing an event may lose it from that
  harness generation while the cursor has advanced — that window belongs
  to the harness's own durability, and the recovery story is the standing
  one ([SUM-7.3]): the chat history is the durable
  conversation, reachable to the agent itself via `taut log`. Adapters
  are not required to infer an ingestion acknowledgment from terminal output.
- **Restart replay:** a new driver (or a fresh harness session after a
  crash) starts by injecting everything after each stored cursor — the
  chat history is the durable conversation ([SUM-7.3]).
- **Watcher death is a watcher-rebuild signal:** if the watcher thread exits
  unexpectedly after startup, the driver wakes the supervisor and rebuilds the
  watcher against the same live harness session first. It must
  not consume harness crash backoff or interrupt the provider unless the
  pump exits or injection itself fails. A watcher must never be allowed to die
  silently while the foreground driver waits forever and the member stops
  hearing chat.
- **Backpressure:** if the harness stalls, `inject()` blocks or raises,
  cursors stop advancing, and unread accumulates honestly; `taut list`
  shows the member falling behind exactly as it would a person on
  vacation (L2). The driver never buffers message text beyond the write
  in flight.
- Notification-inbox events are claim-consumed by the watch (per
  [IAN-7.4]); their injection is therefore at-most-once, which matches
  their pointer semantics.

## 6. Mouth — the CLI Contract [SUM-6]

- The adapter constructs the provider child environment from a copy of the
  host environment, removes inherited `TAUT_AS` and `TAUT_TOKEN` from that
  copy, then applies the driver's explicit child overlay. The resulting
  child carries exactly the summoned member's `TAUT_TOKEN` (continuity,
  **not** authentication, per [TAUT-5]/[TAUT-9]: it selects the member within
  the storage trust boundary and proves nothing) and, when the backend is
  path-addressed, `TAUT_DB`. The adapter does not mutate the host environment
  or change unrelated inherited variables. The agent speaks with ordinary
  CLI calls; replies route wherever the agent says (`taut say dev ...`,
  `taut reply`, `taut say @van ...`).
- **Terminal output is diagnostics, not speech.** The driver never posts
  harness terminal output to chat and never parses a provider reply envelope.
  Output may update coarse activity, answer a finite set of terminal queries,
  feed an explicit human attach, and contribute a bounded control-stripped
  diagnostic tail. The agent's only mouth is an explicit Taut command. A human
  watches a hosted agent through attach, not through output mirroring.
- The persona template ([SUM-10]) makes the mouth contract explicit to
  the agent, including "never answer in a thread other than the one you
  mean" and "if you cannot run taut, say nothing rather than print to
  stdout" (L1: the failure mode is silence, not misdelivery).

## 7. Provider Adapters [SUM-7]

### [SUM-7.1] Adapter interface

The provider adapter surface is deliberately terminal-shaped:

```python
class ProviderAdapter(Protocol):
    supports_attach: bool
    orientation_via_inject: bool

    def spawn(self, *, system_prompt: str,
              env: Mapping[str, str]) -> AdapterHandle: ...
    # AdapterHandle:
    def inject(self, text: str) -> None: ...
    def events(self) -> Iterator[ActivityEvent | ExitEvent]: ...
    def interrupt(self) -> None: ...
    def request_close(self) -> None: ...
    def close(self) -> None: ...
```

Summon defines no provider event protocol. All production providers use the
interactive PTY adapter. The adapter emits coarse `ActivityEvent` values and
exactly one terminal `ExitEvent`; it emits no assistant-text or provider-
session event. `inject()` is flushed at the child terminal boundary.

Contract requirements on every adapter: `inject()` returns only after a
flushed write and surfaces failures synchronously ([SUM-5.4]);
`interrupt()`, `request_close()`, and `close()` are thread-safe and unblock
any in-flight `inject()` ([SUM-9] depends on this to stop a stalled harness);
`events()` must be **drained continuously by the driver**. The driver owns a
dedicated event-pump thread for the life of the child (`activity` → member
activity via the public seam: a rate-limited
token-selected resolution (`whoami()` on a token client updates
`last_active_ts` as a side effect of [IAN-3.3] step 2 — at most once per
activity window, never a private `_state` call); diagnostics to the log;
`exit` → the [SUM-11] resume path). Shutdown ordering is: stop injection →
request terminal close → foreground close drives bounded
wait/escalation/reap while the pump drains → checked pump join →
ownership-checked release. An undrained stream is a child-stdout deadlock;
waiting for pump exit before close is not valid because a provider may remain
alive after its graceful interrupt.

`PtyAdapter.spawn()` selects a POSIX PTY or Windows ConPTY implementation. The
registry and driver do not branch by platform. POSIX process groups and
Windows ConPTY sessions are platform-specific owned capabilities. Both
implementations preserve reusable interrupt, one terminal close request,
bounded finalization, serialized writes, continuous output drain, and one
exit event. Windows may not fall back to plain pipes or direct-child-only
cleanup when ConPTY setup fails.

The adapter defines `activity` as **coarse lifecycle liveness**: spawn,
injection, or an output burst after an idle gap, never per-byte. A constantly
redrawing idle TUI must not keep `last_active_ts` fresh forever. Member
presence remains anchored to the harness child process being alive ([SUM-4]),
independent of output.

`interrupt()` remains reusable, nonterminal cancellation. It preserves PTY
Ctrl-C behavior, aborts adapter writes in flight, and leaves a surviving
handle and terminal domain open. It does not perform terminal-domain
escalation.

`request_close()` is the nonblocking terminal-retirement operation. Under the
handle's reentrant lifecycle lock it atomically changes `open` to
`close_requested`, permanently rejects or cancels injection, and owns the
retirement's one graceful provider signal or PTY Ctrl-C. It does not wait,
escalate, reap, join, release streams, or close the process domain. After
`close_requested` is visible, `interrupt()` and repeated `request_close()`
calls are no-ops and cannot deliver another graceful signal.

`close()` is the blocking terminal finalizer. A direct close first performs
the same terminal request when the handle is open. Exactly one closer changes
`close_requested` to `closing`; concurrent closers wait for and observe its
result. The closer allows the existing bounded graceful interval. On POSIX it
observes leader exit without reaping, sends the bounded SIGTERM/SIGKILL ladder
to the process group while the unreaped leader still pins the group identity,
and only then reaps the leader. It never signals the numeric process-group ID
after leader reap and does not claim an atomic group-empty proof. On Windows
it closes the owned ConPTY session while output remains drained, proves the
attached descendant is absent, and reaps the leader. Direct provider exit does
not bypass either platform's descendant-retirement step. Finalization then
releases streams, fds, and native terminal handles in adapter-specific order.
A POSIX no-signalable-target
result is successful completion of that ladder stage: `ESRCH`, or Darwin
`EPERM` only after non-reaping observation has already established that the
leader is terminal. Any other failed group signal, leader reap, ConPTY
operation, or Windows attached-descendant check is terminal `AdapterError`;
under an existing primary failure it is attached as a cleanup note rather than
replacing the primary. No cleanup path scans unrelated process ancestry or
signals a process outside the still-retained platform capability.
`interrupt()` and `request_close()` may re-enter from a Python signal handler
at any point in close and must not wait on a non-reentrant lock owned by the
interrupted frame.

Adapter capabilities are part of the interface. `supports_attach` controls
whether the driver may bridge a human terminal
before the pump starts. `orientation_via_inject` controls whether the
persona/orientation is delivered by a first injected turn rather than a
spawn-time system-prompt flag.

### [SUM-7.2] Adapters shipped

- `pty` is the sole production adapter. It hosts every named provider
  (`claude`, `codex`, `coder`, `grok`, `qwen`, `kimi`, `opencode`, `pi`, and
  future interactive CLIs) through the same terminal path. Provider entries
  contain only the executable argv and values already represented by
  `PtySpec`; they are not protocol adapters.
- `scripted` is a packaged test registration for the same PTY adapter. Its
  real interactive child publishes terminal readiness, accepts terminal
  input, records received turns, and exercises explicit Taut commands. It is
  the anti-mocking seam for downstream conformance and contains no second
  adapter or wire protocol.

### [SUM-7.4] PTY shell adapter

The PTY adapter runs the harness in its normal interactive mode on a
pseudo-terminal and drives it as a minimally capable terminal — the
truest form of "summon is the agent's terminal" ([SUM-2]).

The explicit host terminal lease and attach bridge forward PTY bytes
unchanged. They are terminal transport, not Taut-owned text rendering, and
are exempt from [TAUT-6.4]. Sanitizing this byte stream would corrupt the
hosted terminal protocol.

**Spawn.** `PtyAdapter` validates one `PtySpec`, then selects a platform
implementation below the adapter boundary. On POSIX, `pty.openpty()` and the
shared POSIX process-domain owner retain the current fd and process-group
behavior. On Windows, the adapter calls the documented `CreatePseudoConsole`
and `ClosePseudoConsole` APIs through `ctypes`, passes the pseudoconsole in
`STARTUPINFOEX`, and owns the input/output pipe handles. ConPTY input and
output are serviced on independent threads. Output remains drained through
close, and `ClosePseudoConsole` owns the terminal session rather than only the
leader PID. The registry, driver, readiness policy, terminal-query responder,
injection framing, diagnostics, and adapter event contract remain platform-
neutral.

The harness argv is its normal interactive launch. `TERM=xterm-256color` and
a real window size are set; `TERM=dumb` is forbidden because it breaks these
TUIs. PTY configuration is validated before handle publication: argv is a
non-empty sequence of non-empty strings; rows and columns are integers in
`1..65535`; stall and maximum-settle durations are finite positive numbers;
and quiet milliseconds is a non-negative integer whose seconds conversion is
finite. Timing values must be representable by the runtime float used for
deadlines. Invalid configuration and
any pre-publication setup/spawn exception releases every acquired terminal
resource and surfaces as `AdapterError`.
The POSIX threaded driver uses `start_new_session=True`, never `preexec_fn` or
`pty.fork()`.

Validation exists only for values constructible through `PtySpec` or the
documented `TAUT_SUMMON_PTY_*` environment variables. Platform setup errors
are normalized to `AdapterError` at `PtyAdapter.spawn()`. The adapter does not
validate speculative provider profiles or unreachable internal states.

**Terminal-query responder.** A reader over the master answers only a
finite set of report-request families that common TUIs send at startup.
It tracks cursor position best-effort by parsing absolute moves
`ESC[<r>;<c>H` / `ESC[<r>;<c>f` and relative moves `ESC[<n>C`,
`ESC[<n>B`, `ESC[<n>D`, `ESC[<n>A`, clamping every stored position to
the configured `(rows, cols)` and to at least `1;1`. DSR cursor
`ESC[6n` replies with the clamped tracked position, so both common size
probes work: absolute park (`ESC[999;999H` then `ESC[6n`) and relative
walk (`ESC[9999C` `ESC[9999B` then `ESC[6n`) return the window size,
never `999;999R`, a giant relative value, or a fake `1;1R`.

Recognized families and replies: DSR status `ESC[5n` → `ESC[0n`;
primary DA `ESC[c`/`ESC[0c` → `ESC[?1;2c`; secondary DA `ESC[>c` →
`ESC[>0;0;0c`; DECRQM mode queries `ESC[?<n>$p` → `ESC[?<n>;0$y`;
XTVERSION `ESC[>q` and parameterized `ESC[><n>q` →
`ESCP>|taut-summon(0)ESC\`; OSC foreground/background color queries
`ESC]10;?`/`ESC]11;?` → default rgb replies; color-scheme query
`ESC[?996n` → dark-mode `ESC[?997;1n`; and kitty keyboard query `ESC[?u` →
`ESC[?0u`. Kitty keyboard mode sets such as `ESC[><n>u` and cursor-style sets
such as `ESC[<n> q` are handled as no-reply mode changes, not report requests.
Unknown sequences get no reply. The master reply channel is also the harness
keyboard-input channel, so writing a guessed "benign no-op" injects spurious
keystrokes and can corrupt the TUI worse than silence.

Responder completeness is a detached-mode risk. During attach, the real
terminal answers queries, so attach proves nothing about summon's
responder. Wired re-summons and [SUM-11] resumes run detached from byte
zero. Therefore the reader maintains an `awaiting_query` diagnostic for
the single-shot hang case: when an unanswered conservative
report-shaped query is outstanding and no output progress occurs for
`stall_s` (default 10s), it logs the escaped sequence and exposes a
STATUS field. The diagnostic is report-only and human-recoverable; summon
does not fabricate a reply. The resolution is `taut summon --attach NAME`.
The report-shaped predicate matches report-request families (DSR, DA,
DECRQM, XTVERSION, OSC color query, kitty keyboard) and excludes ordinary
draw/control sequences such as cursor moves, SGR, EL/ED, mouse/mode sets,
cursor show/hide, and scroll region. The reader uses timed `select`/poll,
never a permanently blocking read, so the stall timer advances while a
single-threaded TUI blocks for a reply. Each registered harness's
detached startup query set is also captured and asserted in tests.

Adapter-specific STATUS fields are transported by
`AdapterHandle.status_fields() -> dict[str, str]`, merged by the control
loop into the `_status_fields()` `as_fields()` output. Values must be
JSON-serializable primitives; raw `bytes` are forbidden. Keys must not
collide with snapshot keys (`driver`, `rate_limited`, `rate_breaches`,
`provider`, `thread_count`, `cursor_lag`, `control_health`,
`health_detail`) or envelope keys (`command`, `status`, `request_id`).
A collision is a programming error and is tested.

`control_health` is the health of the control plane, not a catch-all latency
signal. A broker fault on an owned long-lived control handle is handled by
recording health detail, closing and reopening the driver's owned broker
handles, and letting the next tick or idempotent STATUS/PING request proceed.
Taut does not classify `malformed`, magic mismatch, disk I/O, or row-decode
errors as transient by substring. STATUS reports
`control_health=degraded` only if drain failures repeat across consecutive
cadences. The rate backstop audit shares the same thread but is a safety audit;
its broker faults use the same close/reopen discipline and must repeat before
they poison `control_health`. Skipped passes stay visible in logs without
permanently marking a live driver unhealthy for one local SQLite/process-churn
blip.

**Attach / detach and host interaction.** Whether a human is bridged is
decided by the durable `wired` flag, the single setup-recovery escalation
defined below, and a [SUM-13] host-interaction adapter. Screen-readiness
observations may cause Summon to offer an acknowledged attach; they never
start a bridge, and no bridge ever begins without an explicit host
acknowledgement. On a first-ever summon of a not-wired
member, the shell interaction reports an ordinary real tty as available and
Summon bridges it in raw mode to the PTY master. The human answers
trust/login/model prompts and explicitly detaches with the configured
non-`ESC` chord, defaulting to `Ctrl-\ Ctrl-\`; only then does Summon mark the
row wired. Summon never auto-detaches on a first run. Subsequent wired summons
go straight to detached driver mode. No-tty runs go detached with the current
notice and may surface `awaiting_onboarding` through log plus STATUS.
`--attach` requires terminal availability; `--detach` forces detached mode.
They are mutually exclusive at CLI parsing and at the driver boundary.
The shell adapter preserves the existing fd behavior: fd 0 must be a tty, fd 1
may be redirected, and a missing stdin tty reports `NO_TTY` before considering
the nested-host marker. With a tty, `TAUT_HOST_TUI=1` reports `NESTED_HOST`;
otherwise the shell reports `AVAILABLE` and grants a no-op lease over fds 0/1.

Attach occurs in exactly two cases: the first-generation attach decision
(unchanged below) and at most one setup-recovery attach per foreground
run (defined below). An ordinary post-crash resume does not re-grab the
terminal. During any attach the driver starts no event pump and no
watcher; there is exactly one master reader at a time: the bridge during
attach, then the driver's reader after detach. Chat that arrives during
attach is not injected until the watcher starts after detach.

The detach chord matcher runs byte-at-a-time across raw-mode reads. It
buffers partial chord bytes, detaches only on a complete match, and
forwards the buffered bytes plus current byte on mismatch. It never
intercepts `ESC`-prefixed input; Escape, arrows, and function keys pass
through unchanged.

An uncooperative nested shell-out marked `TAUT_HOST_TUI=1` refuses attach so
two full-screen applications never share the terminal. A cooperative future
TUI supplies a [SUM-13] interaction adapter instead of setting that fallback
marker for the in-process call.

A host-supplied generic `UNAVAILABLE` result is distinct from `NO_TTY` and
`NESTED_HOST`. Required attach fails with `--attach requires an available
terminal`. Preferred attach stays detached and warns that the provider is not
wired because the host terminal is unavailable, including the member name in
the follow-up `taut summon --attach` instruction.

The interaction has a pure availability phase and a scoped terminal-lease
phase. A cooperative TUI may report availability during bootstrap, then pause
rendering and grant explicit input/output fds only when the lease is entered.
Summon calls the provider attach bridge itself and owns when attach occurs,
the harness PTY, detach result, reset bytes, driver lifecycle, and the rule
that chat is not injected until the watcher starts after detach. The
interaction never receives the provider handle, reads Summon state, or writes
control messages.

On Windows, attach converts the lease's input/output fds to owned Win32
handles. A console input handle is switched from line/echo processing to
virtual-terminal input after its exact mode is saved; restoration occurs on
every exit. A dedicated blocking `ReadFile` owner scans the existing detach
chord and is cancelled with `CancelSynchronousIo` during detach or shutdown.
Non-console handles supplied by a rich host skip console-mode mutation but use
the same owned read/cancel path. Output uses the lease's output handle. A
failed mode change, cancellation, restoration, or write follows the existing
attach failure-priority rules; there is no fallback to cooked `input()`.

On every bridge exit path, summon restores the local tty with a fixed,
idempotent reset blast before `termios.tcsetattr(TCSADRAIN)`: `CAN`
(`0x18`) plus `ST` (`ESC\`), exit alternate screens (`ESC[?1049l`,
`ESC[?47l`, `ESC[?1047l`), show cursor, reset scroll region, SGR
`ESC[0m`, autowrap on, synchronized-output off, alternate-scroll off,
DECCKM/application keypad off, focus tracking off, all mouse variants
off, bracketed-paste off, and one kitty keyboard pop. The fake TUI tests
prove this at the byte level.

STOP during attach is consumed by the bridge. The bridge selects over
`[human_tty, master, shutdown_waker]`, where `shutdown_waker` is a
bridge-owned pipe fed by a bridge-local forwarder watching the existing
driver wake event and a bridge-local `done` event. Teardown order is
`done.set()` → join forwarder → close pipe fds; forwarder writes swallow
`BrokenPipeError`/`OSError`. On shutdown wake, the driver does not start
the pump or watcher and goes straight to ordered shutdown.

**Master fd ownership.** `request_close()` publishes retirement and attempts
the one graceful Ctrl-C; `close()` drains write-side operations and delegates
bounded process-domain finalization to [SUM-7.1] before resolving master-fd
ownership. It does not return early when the provider leader has exited: the
shared owner retains the unreaped leader through the safe process-group signal
ladder. `close()` closes the master iff no reader has started. If a reader has
started, the reader closes the master on EOF/EIO. The reader sets
`_reader_started` under the lifecycle lock as its
first action and checks `_master_closed` before its first read. Any `OSError`
on master read is end-of-stream, so a close-before-first-read `EBADF` produces
the normal single `ExitEvent`. Direct `handle.close()` first requests
retirement, so exceptions in the universal `spawn → pump-started` span cannot
leak a master fd or zombie.

The PTY master is configured nonblocking once before concurrent publication,
preserving unrelated flags. No writer calls `F_SETFL` afterward. Injection,
terminal-query replies, and attach-forwarded human input serialize through one
normal-writer primitive. Every normal-write call snapshots the current epoch at
method entry, before waiting for serialization. Before fd I/O, it validates the
epoch, child, and handle state under the lifecycle lock, registers a unique
active-operation token, and duplicates the canonical master fd. The duplicated
fd pins the same nonblocking open file description, so `os.write` and readiness
wait run outside the lifecycle lock without risking numeric-fd reuse. The
operation closes its duplicate in `finally`, then rechecks the epoch and
retires its token as one lifecycle-lock action. It also rechecks the epoch
after every syscall, including error outcomes. A published epoch mismatch
outranks concurrent reader-side close and stale lower-level fd diagnostics. An
attempt already authorized when interruption is published may transfer its
current chunk, but cancellation published before token retirement makes the
call report interruption and no later chunk begins. Once the token is retired,
the write is complete and later cancellation applies only to later calls.

Interrupt and terminal-close request are the two out-of-band writers. Neither
acquires the normal-writer lock. `interrupt()` registers an operation token,
advances the write epoch, duplicates the master fd, and attempts Ctrl-C
outside the lifecycle lock. Failed duplication or Ctrl-C may use the existing
SIGTERM fallback while the operation token remains live. The handle stays
open, so calls entering afterward capture the new epoch and remain valid.

`request_close()` changes `open` to `close_requested`, publishes `_retired`,
advances the epoch, and acquires its close-request duplicated-fd operation
token as one lifecycle-lock transition. The winning request attempts the one
graceful Ctrl-C outside the lock, closes the duplicate, and retires its token.
Failed duplication still commits retirement and may use the existing signal
fallback; no later close request or interrupt sends another graceful Ctrl-C.

`close()` first ensures retirement was requested, then the winning closer
changes `close_requested` to `closing`, drains every external operation,
performs bounded escalation and reap, and publishes the terminal result. It
never waits on its own close-request token and never repeats the graceful
Ctrl-C. The reader's canonical select/read and EOF-close ownership remains
unchanged. Concurrent close, reader-side close, and numeric-fd reuse cannot
redirect leased write-side syscalls because their duplicates pin the original
open file description. Query replies retain best-effort error reporting but
use the same serializer, epoch checks, and operation leases.

Close re-reads reader ownership after each reap outcome and makes the fd
ownership decision atomically under the lifecycle lock. Spawn closes each fd
once. Failure to reap after SIGKILL permanently retires the handle, unblocks
readers and writers, releases the master exactly once through the terminal
ownership path, and raises `AdapterError` after best-effort cleanup. Cleanup
errors do not replace an existing primary exception; interrupt after retirement
is a no-op and cannot touch a reused fd.

**Pre-attach acknowledgement.** After resolving that the first provider
generation will actually attach, but before spawning that generation, Summon
asks the host interaction to present a typed terminal-attach notice and
return an explicit proceed/cancel decision. The notice identifies the member
and provider and supplies the Summon-owned detach hint. Every host must make
four facts clear: this screen is provider setup rather than Taut chat; the
user should complete only trust, login, model, or equivalent setup; the user
returns with `Ctrl-\ Ctrl-\`; and the foreground Summon run continues after
detach. The shell requires an Enter acknowledgement. A rich host may use a
native confirmation that was opened by this exact attach decision.

For the first-generation attach decision, cancellation is a normal
pre-spawn end. It starts no provider child, terminal lease, event pump,
control loop, watcher, or readiness callback and never marks the session
wired. A declined setup-recovery acknowledgement is governed by the
escalation block below: it never ends the run and its suspect generation
was already torn down before the decision was requested. The
already-bootstrapped member and durable unwired
session remain available for a later summon, as they do after an interrupted
first attach; Summon performs no destructive identity rollback. A host error
while presenting or collecting the decision is fatal to this foreground run
and follows normal ownership-checked cleanup. Forced detach, a wired
automatic run, and unsupported attach never request acknowledgement. Later
generations request acknowledgement only for the single setup-recovery
escalation defined below; ordinary crash resumes never do.

**Setup-recovery escalation.** Settle publishes one additional passively
observed fact per generation: whether the harness has enabled bracketed
paste since spawn (the input prompt is *confirmed*). A generation that
reaches its settle outcome without a confirmed input prompt is a
suspected interactive setup gate — trust, login, or model onboarding —
because injecting orientation would submit an Enter keystroke into an
unknown full-screen dialog. Wired members are deliberately eligible: a
provider self-update can re-gate an already-onboarded member, so `wired`
is not an escalation condition. When every escalation condition holds —
the adapter supports attach and orients via injection, the run is not
`--detach`, cached availability is `AVAILABLE`, the host interaction
declares setup-recovery support, `TAUT_SUMMON_SETUP_RECOVERY` is not
`0`, no setup-recovery attempt has been consumed in this foreground
run, and the generation did not itself complete an acknowledged attach
(a human who just detached deliberately left the screen they saw; a
paste-less provider must not re-prompt its own onboarder) — the driver
does not inject. It tears the suspect generation down
through the ordinary generation teardown, requests the same typed
pre-spawn acknowledgement, and on proceed runs one fresh generation
through the acknowledged attach order (`acknowledge → spawn → rejoin →
ensure_threads → attach → detach → set_wired(True) → pump.start →
settle → inject orientation → watcher`). The teardown always precedes
the acknowledgement request, so a person is never deciding while a
suspect harness runs. Before that teardown the driver captures the
suspect handle's bounded output tail and offers it to the host through
the acknowledgement notice, so the offer can show the provider's own
pending question. Declining consumes the single attempt and is a
normal mid-run result: the driver starts the next generation detached
and injects orientation after that generation's settle exactly as
today; the run does not end and no second offer is made. A `False`
acknowledgement produced by driver shutdown rather than a human decline
follows the ordinary shutdown path — nothing further is spawned and
nothing is injected. When any escalation condition fails, the driver
injects after the settle bound exactly as today — providers that never
enable bracketed paste retain today's behavior — and, while
unconfirmed, surfaces the suspected gate through the existing
`awaiting_onboarding` log-plus-STATUS surface. The escalation consumes
no harness crash budget; the input-prompt fact is passive,
per-generation, and never read from the master by settle itself.

Startup order per generation is fixed around PTY master ownership. When policy
rules out attach before bootstrap (`--detach`, `NESTED_HOST`, or generic
`UNAVAILABLE`), the driver starts the pump immediately after spawn, before
`rejoin` and `ensure_threads`, so the terminal-query responder is live while
bootstrap work runs:
`spawn → pump.start → rejoin → ensure_threads → settle → inject orientation →
watcher`. For a first-generation attach, the driver first computes one attach
decision from request, adapter capability, cached host availability, and
durable `wired` state, then obtains host acknowledgement before provider
spawn. After acknowledgement, the human bridge owns the PTY master until
detach:
`acknowledge → spawn → rejoin → ensure_threads → attach → detach →
set_wired(True) → pump.start → settle → inject orientation → watcher`.
`--attach` follows that path when the terminal is available. `NO_TTY` and
`AVAILABLE` preserve their reason-specific detached or acknowledged-attach
outcomes. The same cached availability is reused after a provider crash. No
generation ever reacquires availability; the setup-recovery escalation
reuses the cached value and is the only later-generation path that may
request acknowledgement and a scoped lease.
`rejoin` still anchors the member to the child before raw onboarding or
detached operation, and the watcher starts only after orientation is
injected. Early-pump refusal paths remain required because TUIs may emit DSR,
XTVERSION, or kitty queries immediately after spawn and time out while the
driver is doing SQLite or thread bootstrap work.

Settling must not treat genuine pre-output silence as readiness. In a
detached cold start, when the PTY reader has started but no Summon owner has
observed provider output, the driver waits for first output or the bounded
settle deadline. During human attach, the byte-transparent bridge may
passively retain that provider output was observed, its latest timestamp, and
input-mode state such as bracketed paste. Passive observation emits no
terminal replies and retains no attach-era unanswered-query diagnostic,
because the real host terminal owns query responses until detach. The pump
inherits that bounded state when it becomes the sole reader. Output consumed
during attach therefore satisfies the first-output condition, while a
provider that emitted nothing still receives the existing cold-start bound.

**Ears and orientation.** In detached driver mode, `inject(text)` writes to
the master under an inject lock. Payloads are canonicalized and sanitized
before submission: CRLF/lone CR become LF; `ESC`, `DEL`, all C0 controls
except LF, and all C1 controls (`U+0080` through `U+009F`) are stripped;
`TAB` becomes a space. If the harness has enabled bracketed paste
(`ESC[?2004h` observed in output), the sanitized text is framed as
`ESC[200~...ESC[201~` plus `\r`, preserving LF. Otherwise remaining LFs
collapse to spaces and exactly one turn is submitted with trailing `\r`.
Embedded 7-bit or Unicode C1 paste delimiters cannot survive this
Unicode-to-terminal encoding path because `ESC` and C1 controls are removed.

Before the first injected chat turn, the current PTY reader publishes
`last_output_ts`; settle waits until observed output has been quiet for
`quiet_ms` (default 500ms) or spends one aggregate `max_settle_s` deadline
(default 10s). Starting the pump after attach does not erase prior observed
output or terminal input modes. Settle never reads the master and is not a
readiness signal. Orientation remains an explicit driver step gated by
`orientation_via_inject`; the PTY adapter injects it as the first turn.

Output is never parsed as speech. The PTY reader exists for liveness,
diagnostics, query response, and attach bridging only.

The PTY handle additionally retains a bounded tail of raw harness output
(final bytes only, fixed cap) for diagnostics. The tail is exposed as
sequence-stripped printable text: well-formed terminal escape sequences
whose introducer lies within the retained window — CSI, OSC,
DCS/SOS/PM/APC, and other ESC- or C1-introduced forms — are removed with
their parameter and string bodies (a well-formed sequence left
unterminated at the buffer end is dropped, not leaked), then ESC, DEL,
all remaining C0 controls except LF, and all C1 controls are removed and
the result is length-bounded before it reaches any log, error, or host
surface. A sequence truncated by the window cap itself, or a malformed
mid-stream sequence, may leave parameter text; C1 introducers are
recognized only where they cannot be UTF-8 continuation bytes. Tail capture is best-effort
and read-only; it never emits terminal replies, never blocks the reader,
and its failure never changes a driver outcome.

Interrupt writes raw `\x03` for the harness key reader; shutdown escalates
with the platform terminal-domain escalation per the ownership rule. STOP and
SIGINT interrupt the
current handle immediately, including during pre-watch settle/orientation. If
shutdown races an orientation `inject()` and the adapter reports interruption,
that is a clean stop rather than a startup failure. A fresh interactive
session plus cursor replay recovers the conversation under [SUM-7.3].

### [SUM-7.3] Session continuity

Session persistence belongs entirely to the harness. Summon neither receives
nor stores a provider session id. Every provider-generation restart starts a
fresh interactive process and replays unread chat through the existing cursor
contract. Chat history is the durable conversation; provider-local state is
outside Summon's recovery guarantee.

## 8. Session Ledger and Single-Driver Guard [SUM-8]

- **Two extension-owned sidecar tables**, split by lifetime:
  - `taut_summon_claims` — **transient**. One row per in-flight
    bootstrap: (name, provider) PRIMARY KEY. Version-3 writers store the
    lowercase [IAN-4.2] route key in `name`; a unique expression index on
    `(LOWER(name), provider)` is the concurrent-summon serialization point
    ([SUM-4] step 0). Claim lookup and release use the same `LOWER(name)` key,
    so an already-running version-2 writer cannot create an invisible
    mixed-case route during rollout. The remaining fields are driver pid +
    start-time evidence and claimed timestamp. Deleted at [SUM-4] step 3; a row whose
    driver evidence is dead is reclaimable. Because claims are
    transient, a name a member has since renamed away from is claimable
    again — the name key never permanently occupies anything.
    Summon schema version 3 migrates version-2 claim names to lowercase route
    keys and creates the unique route expression index in one transaction. The
    index construction serializes with concurrent claim inserts on supported
    SQL backends; migration re-reads and normalizes rows under that lock. If two
    legacy or racing rows for the same provider collapse to one route key,
    migration fails loudly before changing either row or the stored version; an
    operator must let or make one transient claim clear and retry. The index
    plus normalized lookup keeps a late version-2 writer visible and unique
    after migration.
  - `taut_summon_sessions` — **durable**. One row per summoned member:
    `member_id` PRIMARY KEY (created only after the member exists, so never
    NULL on any backend), the member's continuity token (captured at creation,
    output-visible once per [TAUT-8.2]), provider name, driver pid/start-time
    evidence, the PTY onboarding `wired` flag, and updated timestamp. The
    historical nullable `provider_session_id` SQL column remains physical
    compatibility ballast in schema version 3, but new writes leave it NULL.
- **Names never key durable state.** Names are mutable current values,
  not identity ([IAN-2.2]; `set name` can rename a summoned member
  mid-run like anyone else). Every post-creation lookup — `stop NAME`,
  `status NAME`, re-summon by name — resolves the *current* name
  through core (public `who()`/route lookup) to a `member_id` and reads
  `taut_summon_sessions` by its key. Re-summoning an old, renamed-away
  name finds no member and no claim — it creates a fresh member, which
  is what the words say (L2). Created via
  `Queue.sidecar()` under the same rules as core tables ([TAUT-3.3]);
  versioned under its own `taut_meta` key `summon_schema_version` so
  core and extension schemas evolve independently and core's version
  gate is untouched. Summon therefore requires a SQL-sidecar backend
  (SQLite or Postgres); Redis waits on the [TAUT-12.2] state mapping. The
  extension's SQL is fixed, module-level template text with qmark parameters;
  reads use the canonical session projection rather than `SELECT *` or
  runtime-assembled column lists.
- **Persistence I/O:** Summon participates through the `taut-summon` component
  [PIO-5.3]. Persistence component version 2 exports `member_id`, token,
  provider, wired, and updated timestamp. The historical
  `provider_session_id` field is not part of the typed model, status output, or
  version-2 record, and version 2 rejects it. The exact version-1 reader still
  requires that field, validates it as string or null, and discards it.
  Bootstrap claims and driver pid/start-time evidence are transient and are
  never exported; restored driver evidence is null. The component writer
  represents `updated_ts` as [TAUT-3.5]'s canonical string; accepted string or
  exact JSON integer input is normalized to an integer before the Summon
  sidecar write.
- **Single-driver guard:** `run` refuses when the ledger row shows a
  live driver (pid + start-time still alive, same evidence style as
  presence). Two drivers injecting into two harness sessions as one
  member would double-speak (L2: a person is in one place). `--takeover`
  replaces a dead or abandoned claim.
  A claim succeeds only when a same-transaction readback carries the caller's
  exact pid/start-time evidence. Predicated writes use null-safe expected
  evidence, so partial-null corruption can be replaced only by explicit
  takeover and can never return false success. Partial evidence is classified
  indeterminate by readers. `record_session` accepts driver evidence only when
  both values are null or both are non-null. Ordinary renewal requires both
  stored values to null-safely match both expected values; takeover is the only
  path that may replace a partial-null legacy row.
- **Wired flag:** the per-(member, provider) `wired` flag ([SUM-7.4]) is
  durable state and a versioned ledger schema change. `SUMMON_SCHEMA_VERSION`
  is 3, and `taut_summon_sessions` includes
  `wired INTEGER NOT NULL DEFAULT 0`. A stored version 1 database fails
  closed with the existing "recreate the development database" path. Version 2
  already has the wired column and uses the claim-key migration above; no
  `ALTER TABLE` is required. The
  typed session row carries `wired: bool`. The load-bearing column sites
  are `_SESSION_SELECT_BY_MEMBER`, `_SESSION_SELECT_ALL`, the `INSERT` in
  `record_session`, and `_session_row`.
  `record_session` preserves `wired` on update. `claim_driver` and
  `release_driver` must not write `wired` because they run on re-summon and
  cleanup. The only writers are `set_wired(queue, member_id, value)` and
  fresh-row default `0`; callers read through `get_wired(queue, member_id)`.

A stored provider value of `claude-stream` is not silently rewritten. Public
start without an explicit replacement returns a handled diagnostic. If driver
evidence is absent, or a complete pid/start-time pair is proven dead, an
explicit `--provider claude` start performs one transactionally predicated
rewrite from exactly `claude-stream` to `claude`. The predicate includes the
exact classified driver evidence, clears stale evidence, and fails if the row
changes concurrently. Live evidence, either partial-evidence orientation, and
every other stored-provider mismatch remain errors. Status may display the
stored legacy provider value before replacement.

Migration compatibility is defined by the predecessor's named semantic
schema, not physical column order. The v2 to v3 proof starts from a checked-in
fixture copied from the actual v2 release. Running the v3 installer and
rewriting its version marker is not a v2 fixture.

## 9. Control Plane [SUM-9]

- Congruent with **Weft's task control-queue contract** — the ctrl_in /
  ctrl_out surface in weft's task layer (`weft/core/tasks/base.py`), not
  weft's private agent-session multiprocessing protocol
  (`agent_session_protocol.py`), which summon looked at only for
  supervision craft. Summon mirrors the **`command`/`request_id` JSON
  subset** of that contract: verbs **STOP / STATUS / PING**, single-line
  JSON bodies keyed `command` and `request_id`, replies correlating by
  `request_id` with a `status` field. Weft additionally accepts
  raw-string commands and returns extra response fields (`tid`,
  `timestamp`, ...); summon requires JSON and guarantees only the
  subset — consumers must ignore unknown reply fields, so weft-shaped
  replies remain conformant. In
  summon's mapping the *inbox role* is the member's chat threads
  themselves; control queues derive from the member id
  (`sys.ctl_<member-id>` in, `sys.rsp_<member-id>` out) under the `sys`
  prefix [TAUT-4.1] reserves.
- Control queues are deliberately **unregistered** ([IAN-6.1] as amended
  by this plan's D3): they are invisible broker queues to every core
  command — the same treatment as foreign queues — and only summon reads
  or writes them. This keeps core registry state core-owned and the
  extension's write surface exactly its own tables plus plain broker
  queues (L1: an implementer needs no core seam; a debugging agent finds
  them with `broker -f .taut.db list`, which [TAUT-3.4] guarantees).
- The driver consumes control queues with a long-lived control reactor on a
  dedicated thread, over public `simplebroker` Queue/watcher primitives.
  The reactor owns persistent queue handles and uses the copied
  `MultiQueueWatcher` scheduling path to claim-consume commands with
  `read_one` (they are commands, not history). `TautClient.watch(...)`
  deliberately knows nothing about `sys.*`. Control must stay responsive
  while injection is blocked on a stalled harness. STOP's signal/control path
  calls nonblocking `AdapterHandle.request_close()`, which publishes permanent
  retirement and unblocks any in-flight `inject()` under [SUM-7.1]. The
  foreground generation owner alone calls blocking `close()`, checked-joins
  the event pump, and publishes teardown before release. A stuck harness can
  therefore always be stopped without making a signal handler or control
  thread own reap or join.
  The control reactor follows SimpleBroker 5.2.0's reference
  persistent-session and thread-local-core ownership model, with
  `simplebroker>=8.0.0` required for the supported reactor lane. Version
  5.2.2 first proved persistent process visibility; 5.3.2 makes cancellation
  interrupt watcher bootstrap while PhaseLock or SQLite connection setup is
  blocked; and 5.3.3 removes unsafe path-name-based runner cleanup and
  initializes timestamp-conflict metrics before concurrent first writes.
  Version 5.6.1 supplies core reaction fanout's full-requested-set exact-name
  broadcast; `simplebroker>=8.0.0` is the repository-wide supported floor,
  aligned with
  `simplebroker-pg>=4.0.0`. The current pair preserves resolved configuration
  through watcher and backend creation and includes serialized watcher cleanup
  and terminal error-handler propagation. It also publishes closeable Queue
  iterators with same-thread synchronous operation cleanup. Version 8.0.0
  changes default retrieval to ascending public message id and advances the
  SQL/backend compatibility line without changing Summon's fixed control
  topology, read-one command consumption, watcher lifecycle, retry ownership,
  or closeable-iterator cleanup contract. Summon does not
  call the SimpleBroker command layer,
  so 6.0.0's keyword-only command-option binding does not alter the control
  reactor path.
  Operation release ends only the active lease; the owner thread retains its
  core until explicit cleanup or close.
  Summon must not recreate that release policy in extension-specific retry or
  cleanup code, and it must not run on SimpleBroker 5.1.x.

The Summon control reactor is a fixed-topology policy subclass of the shared
[TAUT-8.5] `BaseReactor`. It is constructed, driven, recovered, and closed on
the dedicated control thread; its command topology is fixed for one driver
generation; and its long-lived command, shared-reply, ledger, audit, and
owner-client handles are persistent and owned. Per-request reply queues and
one-shot control clients remain transient.

`ControlLoop` is the thin context-specific supervisor for replaceable reactor
instances. It invokes the shared public turn and wait templates, but regains
control between them for audit, recovery, and fatal escalation. Control-handle
recovery occurs only between turns. A handler, audit, or error callback may
classify and record the failed turn, but it must not replace or close the
reactor that remains on the dispatch stack. After the turn unwinds,
`ControlLoop` may build a complete replacement handle set, atomically install
it on the same owner thread, close the old set, and continue so the next loop
iteration reacquires the installed reactor. Partial construction failure
closes every new partial handle and leaves the old complete set installed. A
failed replacement leaves the old set installed and reports degraded health.
While the fault is pending, the supervisor retries replacement before any
further process/audit/wait call on that old set, using the existing bounded,
stop-interruptible backoff. Taut does not retry the consumed command or
classify broker failures by message substring. Repeated replacement failure is
bounded: once the existing control-drain failure threshold is reached without
a successful complete replacement, the control loop reports a fatal
control-plane failure to the driver supervisor. It must not remain alive
indefinitely with unusable handles.

Control waiting combines broker activity, local stop/wake activity, and the
next rate-audit deadline. A due audit runs before timeout calculation, so a
zero deadline cannot create a hot loop. A queued command can wake the loop
before the audit cadence. The rate audit runs only at the between-turn
supervisor seam, remains control-thread-owned, and preserves its in-memory
cursor across successful handle replacement.

Unexpected control-loop exit is a first-class driver failure. The control
thread reports the failure to the foreground supervisor, requests terminal
close on the current adapter, stops the chat watcher, releases the driver claim
after foreground teardown, and exits nonzero. It must never leave a live
harness without STOP/STATUS/PING, and it must not spend watcher-rebuild or
harness-crash retry budgets. Expected STOP and driver shutdown remain clean
exits and preserve release-before-ACK ordering.
- `taut-summon stop NAME` writes STOP. The driver first publishes shutdown,
  requests terminal close on the currently published adapter, and wakes the
  foreground. Watcher coordination only stops and joins the watcher; it does
  not finalize the adapter. Foreground generation teardown calls `close()`,
  checked-joins the pump, posts nothing on the member's behalf, updates the
  ledger, and exits 0. SIGINT to the driver uses the same path. If shutdown or
  fatal control failure was published while spawn was returning, handle
  publication rechecks those events and requests close on that exact handle.
- STATUS returns driver liveness, provider, thread count, and cursor lag
  summary. PING is STATUS minus detail. Primary fields come from driver-owned
  memory and adapter status; the session ledger remains the durable generation-
  fence authority, but STATUS/PING must not read the ledger just to answer a
  live correlated request. Both work while the harness is mid-turn (control
  responsiveness during idle *and* busy is a conformance item).
- Replies use a per-request queue `sys.rsp_<member-id>_<request_id>` so
  concurrent control clients cannot consume each other's answers. Control
  reads and writes call SimpleBroker directly; SQLite lock/busy retry belongs
  to SimpleBroker, not to summon. STATUS/PING clients may rewrite the same
  idempotent request to the same per-request reply queue after no reply within
  their timeout budget. They do not retry broker exceptions by substring. STOP
  is not retried because duplicate stop commands blur shutdown ownership.
- Every STOP / STATUS / PING request carries the live driver evidence
  (`driver_pid`, `driver_start_time`) the client resolved from the session
  ledger. The driver drops commands whose evidence does not match its own
  process. This generation fence makes stale commands left in the stable
  `sys.ctl_<member-id>` queue inert, especially stale STOP rows from a previous
  driver generation.
- Control cleanup is consume-and-close, not delete-all. Commands and successful
  replies are already removed by `read_one()`; timeout leftovers live on random
  unregistered `sys.*` reply queues and are inert. The driver and clients must
  not hard-delete control queues during shutdown, because delete-all maintenance
  in the hot multi-process control path can add SQLite contention without
  strengthening the command contract.
- Adapter STATUS-key collisions and other programming errors are fatal control
  failures, not `status=ok` degradation. STOP replies success only after clean
  shutdown and confirmation that the driver claim is absent or replaced;
  cleanup/release exceptions and indeterminate confirmation reply
  `status=error`. The stop CLI requires that correlated `status=ack` before it
  polls evidence; no reply or `status=error` can become exit 0 merely because a
  later row appears clear. Relative to the evidence placed in the request,
  absent and both-null rows confirm release, complete different evidence
  confirms replacement, and either partial-null orientation remains
  indeterminate. Rate audit computes one inclusive raw cutoff for the pass as a
  fresh public `Queue.generate_timestamp()` value minus the configured window
  in nanoseconds, then compares each message's hybrid timestamp directly. This
  relies on [TAUT-3.5]'s supported hybrid format rather than a private decoder.
  Future timestamps count as current; old recovery backlog never receives a
  new observation timestamp.
- Divergences from Weft, each with its reason (the [TAUT-12.3]
  obligation): **(a)** the data lane is provider-native streaming plus
  chat threads, not execute/result work items — conversation is not a
  task; **(b)** agent output leaves via the CLI mouth, not an outbox
  queue — routing must be explicit and agent-chosen; **(c)** session
  persistence is delegated to the harness — summon does not rebuild what
  the harness owns.

## 10. Turn Policy and Persona [SUM-10]

- The extension ships a **default persona template** injected as the
  session system prompt at spawn, parameterized by member name, joined
  threads, and workspace path. It must state, at minimum:
  - the mouth contract ([SUM-6]);
  - the injection format ([SUM-5.2]) and that messages may arrive
    mid-task;
  - **interrupt policy**: on a message arriving mid-work, decide
    explicitly — act on it now, defer with a short reply ("noted — after
    this slice"), or push back; never silently absorb it (L2: people
    acknowledge interruptions);
  - **silence affordance**: saying nothing is a normal outcome; a
    commenting bar for spontaneous remarks (L2: people mostly don't
    narrate);
  - **loop discipline**: do not respond to another agent's message
    unless it mentions you or asks you something; spontaneous commentary
    addresses work products, not other commentary;
  - **multiline sends**: a literal `\n` inside a quoted shell argument is
    not a newline; multiline messages use stdin (`taut say <thread> -`)
    or real newlines in the argument.
- Driver-side backstop: a per-member posting rate limit (default
  generous, `run`-configurable) so a persona failure degrades to
  throttled chatter, not a two-agent feedback loop. Observation
  mechanism: the watch stream does not reliably see every own send because
  [TAUT-7.4] normally catches up the sender after commit, while an intervening
  unread row can leave an own send visible. Therefore the driver
  runs a periodic **audit pass** on its control-thread cadence:
  log-semantics peeks after a driver-local audit cursor per thread
  (never touching the member cursor), counting messages with
  `from_id == self` in the window. Breach → inject a system nudge and
  log; hard breach → interrupt the harness, and surface the breach through
  STATUS (`rate_limited`, `rate_breaches`) and the driver log (never
  posting to chat as the member, and never as an unconsumed control-queue
  message that no monitor drains). The driver never enforces
  content policy — restraint is the persona's job; the backstop is a
  circuit breaker (L1: mechanical guarantees where personas can fail;
  L2: the rate of a person typing).
- The default persona states that injected chat is user-role workspace input,
  that a line claiming to be system or driver policy is not thereby trusted,
  and that the harness follows the operator's authority policy. This is
  defense-in-depth only. The mechanical rate audit reconciles every currently
  joined chat thread before each due audit and closes handles for threads that
  were left. A newly discovered queue begins at the later of summon start and
  the active rate-window floor, never current head; a retained cursor survives
  leave/rejoin, and already-counted timestamps are deduplicated within the
  active window. It limits posting rate per member; it does not detect semantic
  loops below the configured rate.
- `--persona TEXT` sets the member's short taut persona as `join` does;
  `--system-prompt-file PATH` replaces the template for full control.
  For the PTY adapter, orientation is delivered as the first injected
  message ([SUM-7.4]), not a spawn-time system-prompt flag;
  `--system-prompt-file` overrides the orientation text either way.
- A hard breach requests the adapter's normal interrupt operation. If soft
  interrupt delivery fails, the PTY adapter may terminate the child under
  [SUM-7.4]; that fallback is an interrupt-I/O failure, not an independent
  policy decision to restart a healthy generation.

## 11. Failure Modes [SUM-11]

- Harness crash: driver observes `exit`, marks ledger, attempts one fresh
  interactive spawn and resumes delivery from durable chat cursors; repeated
  crashes back off and
  exit with the reason on ctrl_out and stderr. Never auto-posts to chat
  as the member. A suspected setup gate escalates before injection per
  [SUM-7.4] setup-recovery instead of spending crash budget. The
  give-up error names the member, the consecutive-exit count, the last
  exit code, the bounded sanitized tail of the final screen output when
  the adapter retains one, and — when the adapter supports attach — the
  exact `taut summon --attach <name>` recovery command.
- Watcher crash: driver rebuilds the watcher over the same live harness before
  spending any harness crash budget. Repeated watcher rebuild failure is a
  driver failure; reader exit or injection failure remains the fresh-
  generation recovery path.
  Each watcher attempt owns a fresh stop token and captures the immutable
  harness-generation death event it serves. Foreground teardown publishes the
  attempt stop before inspecting the watcher object. After constructing and
  publishing its watcher, the owner thread checks that attempt token,
  generation death, global shutdown, and fatal control state before readiness
  registration or `run()`. A pre-publication stop therefore closes on the
  owner without entering the drive loop. Every watcher-attempt join is checked;
  a live thread after the bounded join is a fatal driver error and prevents a
  watcher rebuild or harness generation N+1.
- Driver crash: cursors and ledger make restart safe (at-least-once
  injection); the stale ledger claim is reclaimable by evidence.
- An unexpected `Exception` escaping the standalone `taut-summon` outer
  adapter is offered once to [TAUT-13] with its parsed subcommand and database
  selector, then the same exception re-raises. Expected `CommandError`, policy,
  nothing-summoned, unresponsive-driver, signal, provider, watcher, control,
  and supervised teardown outcomes retain their existing handling and are not
  promoted to debug events. The installed command path relies only on core
  dispatch, so driver internals and extension adapters must not capture the
  same exception again.
- Unroutable output ([SUM-6]) → driver log only.
- Slow harness → backpressure via cursor lag ([SUM-5.4]); STATUS reports
  it.
- Storage gone / token invalid → driver exits loudly; nothing is
  consumed beyond claimed notifications already injected.
- A broker/storage exception in the event-pump lane is recorded on that
  generation and transferred to the foreground supervisor after checked
  teardown. It must not escape as an unhandled thread traceback, spend the
  provider crash budget, or permit generation N+1.
- Two summons, one member → refused by the single-driver guard.
- Control reactor failure: a surfaced broker fault may reopen the complete
  owned handle set between turns and continue under [SUM-9]. An unexpected
  control-thread exit, programming failure, or exhausted consecutive
  replacement-failure threshold wakes the foreground supervisor, interrupts
  the harness, stops ears, releases the driver slot, and exits loudly. A
  live-but-uncontrollable provider is forbidden.
- Every spawn owns an immutable generation context containing its token,
  completion, exit, readiness, and wake state. The pump mutates only that local
  context and, immediately before every shared or external side effect, proves
  that its token is still active. A stale pump may not update driver fields,
  durable ledger state, control state, presence, or wake
  state for any adapter event. The token is retired before a generation is
  abandoned. One checked-join helper owns every pump join; timeout prevents
  generation N+1. During normal STOP/resume it is the primary fatal error and
  makes STOP reply error; during cleanup it is secondary and never masks the
  original failure.

## 12. Verification Expectations [SUM-12]

- The provider seam is the packaged `scripted` registration over the production
  PTY adapter and a real interactive child. Broker, sidecar, CLI, child
  process, and PTY/ConPTY are not mocked. Driver, controller, CLI,
  persistence, conformance, and shared terminal-behavior tests collect and run
  on Linux, macOS, and Windows. Only tests whose subject is a POSIX fd/process-
  group primitive or a Windows ConPTY primitive carry a platform marker or
  skip.
- CI runs the same complete non-live Summon selection on each operating
  system; it does not use a Windows file allowlist. POSIX primitive tests prove
  the unreaped-leader process-group ladder. Windows primitive tests prove real
  ConPTY spawn, input, output drain, reusable interrupt, bounded close, and
  attached-descendant retirement. Common adapter conformance is parameterized
  over the platform implementation selected by production code.
- Every new guard includes a firing proof through a current CLI or public typed
  API path. A guard with no constructible production input/state is removed
  rather than preserved as defensive ceremony.
- The **conformance suite** obligated by [TAUT-12.3] proves control
  responsiveness while idle and mid-turn, fresh-generation replay,
  backpressure, clean shutdown without double-speak, the single-driver guard,
  and injection format stability.
- Driver tests run real multi-process flows (a second CLI process
  writing to the watched thread), matching [TAUT-11] discipline.
- Standalone and installed-console tests prove one outer debug capture for an
  unexpected exception, no capture for every named handled class, dynamic
  enable/disable observation, the same re-raised exception and cleanup order,
  and no duplicate capture inside driver supervision. The setting and local
  queue remain real.
- Schema tests install the historical version-2 fixture directly and prove
  successful normalization plus fail-before-mutation handling for colliding
  case variants on real SQLite and PostgreSQL sidecars.
- Deterministic PTY lifecycle is proven against the packaged scripted child
  over the production platform PTY. It models a TUI with alternate screen,
  terminal queries, continuous redraw, delayed readiness, optional bracketed
  paste, and optional onboarding prompt.
- Live harness reachability is gated per registered PTY harness:
  `requires_<name>` tests summon the real CLI detached, assuming a
  pre-onboarded/authed harness, and assert detached `STATUS` reaches a usable
  state and catches up after a real chat injection. Default local pytest probes
  real binaries and may skip with an explicit onboarding/readiness reason,
  because a fresh noninteractive test database cannot complete the human
  attach chord. Strict local mode (`TAUT_SUMMON_LIVE_HARNESS_STRICT=1`)
  prewires the temporary session row to model an already-onboarded harness;
  in that mode, a missing binary, readiness gap, status timeout, unanswered
  terminal query, or injection catch-up failure is a failure. These tests do
  not require hosted CLIs to auto-execute shell commands; the local LLM lane
  below owns the deterministic sentinel-posting proof.
- A CI-safe local LLM lane uses a real PTY child and a loopback
  OpenAI-compatible model endpoint. Prepared CI first performs a bounded
  model-list wait, then exactly one real chat completion rather than completion
  retries. The child must receive the summon orientation, complete one request
  through the counting proxy, and post a sentinel through real `taut say`. The
  model's prose does not control the sentinel post; this is a deterministic
  transport and PTY/mouth proof, not an instruction-following benchmark. With
  `TAUT_SUMMON_LOCAL_LLM=1`, missing models, endpoint/completion errors,
  malformed responses, failed sentinel posts, and any harness exit/restart
  observed before success are hard failures and never skips or silent greens.
  Production [SUM-11] crash recovery remains enabled; the smoke inspects its
  lifecycle evidence and fails if recovery was needed. Failure evidence
  includes driver stderr, TUI events, request count, and provider/container
  diagnostics. The lane prewires the synthetic PTY member as already onboarded
  and does not replace the real-harness, local-only smoke matrix.
  Structured child diagnostics enumerate HTTP failure, URL failure, timeout,
  invalid JSON, non-object response, non-list choices, empty choices, missing
  message, and missing content; each class has a firing test. Dedicated
  external-live and local-LLM invocations select only their respective live
  marker. Non-live diagnostics in the same files are owned once by the unit
  lane rather than rerun by the dedicated smoke.
- Control-reactor tests are independent of core reactor tests. They must prove
  fixed topology, control-thread ownership, persistent long-lived handles,
  broker-activity wake before a long audit interval, no in-turn handle
  close/reopen from dispatch or audit, cleanup of every partial
  replacement-construction stage, no method call on a retired reactor, due-now
  audit without spin, audit-cursor preservation across between-turn reopen, and
  driver-visible initial-open/unexpected-return/fatal-exit cases. At least the
  wake, STOP-during-blocked-inject, fatal-exit, and cleanup cases run through a
  real SQLite broker and real driver/scripted-provider process; mocks may cover
  only adapter or clock boundaries, never broker/control dispatch.
- Installed-artifact compatibility after the `taut-chat` distribution
  boundary proves current core alone, current core plus current Summon, live
  current-pair control operations, exact metadata, and resolver rejection of a
  current Summon wheel with an older incompatible `taut-chat` core when such a
  published baseline exists. Immutable historical `taut-summon` wheels are
  inspected to record their `Requires-Dist: taut` metadata, but are not
  installed as compatible with `taut-chat`. Python packaging provides no alias
  between those distribution names. Tests must not bypass this boundary with
  `--no-deps` or by co-installing both distributions that own the same `taut/`
  files.
- Firing tests cover invalid partial record evidence, indeterminate takeover,
  both partial-null takeover orientations, claim write postconditions,
  mid-bootstrap fallback-claim collision, double SIGINT, PTY reply/inject and
  attach-writer serialization, active-plus-queued write cancel,
  inject-after-close-start fencing, reader-start-during-close, concurrent
  close, post-interrupt reuse, readiness-wait close normalization, invalid PTY
  configuration/fd cleanup, unreaped child cleanup/primary-error precedence,
  same-thread PTY signal reentry, fd-operation lease drain and numeric-fd
  reuse, interrupt/close dup-failure cleanup, deterministic queued old-epoch
  capture, cancellation priority over concurrent reader close, cancellation at
  final write-token retirement, watcher pre-publication stop, fatal
  watcher-attempt join timeout,
  stale-pump fencing for every event, foreground event-pump broker failure,
  STOP cleanup/release error, missing/error ACK refusal, evidence-relative
  release confirmation, fatal STATUS-key collision supervision,
  old-backlog/exact-boundary rate audit, bare status success, dead-driver stop,
  unknown-verb reply, persona re-summon, unsupported attach, malformed
  ledger/configuration diagnostics, the 8.0.0 floor, and ordered release
  invocation with fresh built artifacts.

Terminal-retirement conformance observes the child boundary, not only handle
method counts. PTY tests prove `request_close()` is nonblocking,
publishes retirement before signaling, cancels active and queued writes,
refuses later injection, is idempotent under repeated requests and
signal-handler reentry, and composes with direct and concurrent `close()` while
delivering one graceful SIGINT or Ctrl-C for that retirement. Separate tests
preserve reusable `interrupt()` and inject-after-interrupt. Real
scripted-provider process tests make the first graceful interrupt enter an observable,
bounded cleanup gate and record every reentrant signal; correlated control
STOP and direct driver SIGINT each record one graceful signal and exit cleanly.
The assertion counts signals after cleanup rather than waiting for a target
count.

Process-domain conformance uses real provider and descendant processes, not
`Popen` doubles or signal-call counts. It proves, on every supported platform,
that terminal close delivers retirement to a same-domain descendant when the
provider remains alive, when the provider exits first, and when the descendant
inherits stdout and would otherwise delay EOF. Normal descendant processes
must be absent after close in those firing probes. POSIX proof covers non-
reaping natural-exit observation, safe group identity through graceful exit,
SIGTERM and SIGKILL stages for PTY handles, and the rule that
no group signal occurs after leader reap; it is evidence for the bounded
retirement algorithm, not an atomic proof that a numeric process group is
empty. Windows proof covers real ConPTY spawn, input, output drain, reusable
interrupt, bounded close, and attached-descendant retirement. Existing tests
continue to prove that reusable
`interrupt()` does not retire the handle and that exactly one graceful close
signal is sent. A POSIX-only boundary probe may show that a child which
deliberately creates a new session is outside the owned domain, but the test
must retain creation identity and clean it explicitly. Every descendant probe
has bounded failure cleanup that refuses to signal a reused PID.

Canonical coverage aggregation validates every downloaded raw shard before
combine. No shard may be missing, zero-byte, or unreadable through Coverage's
public data API, and any `CoverageWarning` during combine is fatal. Aggregation
does not delete or filter invalid evidence, require every valid shard to
contain project lines, depend on Coverage's private schema, or replace the
existing required-execution-path gate.

Command/embedding verification additionally proves: both console surfaces use
one controller; source and installed-wheel command discovery; the absent
Summon install hint; controller list/status/stop truth through real SQLite and
real control queues; shell interaction parity through a real PTY child; a
deterministic host adapter that grants explicit terminal fds and observes the
attach transition; no private state/control access by adapters; and lazy
import floors showing core and standalone command help do not import
client/controller/driver/provider/PTY implementations until execution. Mocks
may replace only metadata enumeration, clocks, or the external host adapter
response in narrow unit tests. Broker, sidecar, CLI subprocess, control
dispatch, driver process, and PTY remain real for contract proof.

The installed-wheel checker uses the new core alone and requires the exact
`taut-summon` install hint without importing `taut_summon`. It installs the
new core and current Summon to prove the native command path and live control
behavior. It separately inspects the immutable Summon 0.5.4 wheel to record
its `Requires-Dist: taut` metadata; it does not install that unrelated legacy
distribution beside `taut-chat`.

## 13. Embedding and Rich Hosts [SUM-13]

`taut_summon` exports a typed `SummonController` with provider-name discovery,
session listing, live status, confirmed stop, and foreground-run operations,
plus typed request/result/status models and a host-interaction interface. The
standalone CLI, core command adapters, and future rich TUI use this controller
rather than private ledger/control/driver modules.

Command and standalone-console adapters escape their Taut-owned dynamic human
text through the core public utility. A host interaction's scoped terminal
lease remains byte-transparent as specified by [SUM-7.4]; rich hosts must not
assume attached PTY bytes have passed through the text-rendering safety
policy.

The controller hides extension table rows, queue handles and names, control
JSON, evidence predicates, adapter handles, and driver mutable state. `status`
proves a live correlated control response; a session row alone is not live
status. `stop` succeeds only after correlated ACK and evidence-relative release
confirmation.
`run_foreground(request, interaction, *, install_signal_handlers=False,
on_ready: Callable[[SummonRunHandle], None] | None = None)`
remains blocking and owns exactly one foreground driver lifecycle; it never
silently daemonizes or detaches. The default is the rich-host boundary: it
does not inspect, install, or replace process signal handlers. Command
adapters that own a short-lived foreground process pass
`install_signal_handlers=True` explicitly. Opt-in is valid only on the
Python main thread; an invalid opt-in fails before the driver lifecycle
starts with `SummonOperationError`.

A controller foreground run never mutates the host process's `TAUT_AS` or
`TAUT_TOKEN`. Every driver-owned and control-loop-owned core client disables
ambient identity inheritance and uses only its explicit name, token, or
capture inputs ([TAUT-8.3]); the provider child receives only the summoned
member's explicit identity overlay after adapter-side removal of inherited
host identity as required by [SUM-6]. This non-mutation invariant applies
while the run is active and after every success or failure, so concurrent host
work retains its own process environment.

When signal handling is explicitly enabled, Summon temporarily installs its
driver handler for `SIGINT` and `SIGTERM` and restores the exact prior
disposition for each successfully installed signal on every exit. Partial
installation rolls back earlier installations before the lifecycle begins.
The temporary opt-in does not grant ownership of unrelated signals, logging,
terminal policy, or host environment.

A host interaction reports terminal availability, declares through
`supports_setup_recovery()` whether it can present acknowledgements and
grant leases after its host has left bootstrap, presents one typed
pre-spawn acknowledgement only when the driver has resolved an actual
attach — first-generation or [SUM-7.4] setup-recovery — and grants a
later scoped lease containing input/output fds. The notice owns semantic fields, including member, provider, detach
hint, and — for setup-recovery offers — an optional bounded,
sequence-stripped excerpt of the suspect generation's final screen
output; hosts own their presentation, may omit an absent excerpt, and
must escape dynamic text, the excerpt included, outside the raw lease. A cancelled
decision is a normal pre-spawn result. A presentation failure is fatal and
never falls through to attach. Summon owns the attach decision, provider PTY
bytes, bridge invocation, finite detach result, and lifecycle. Shell and rich
TUI adapters present different host-appropriate wording while preserving the
same transition; neither inspects Summon persistence or provider screens. The
shell interaction declares setup-recovery support; a host that declares no
support never receives a mid-run acknowledgement request. For a
setup-recovery acknowledgement, an explicit human decline is a normal
mid-run result that continues the detached path rather than ending the
run; a refusal produced by driver shutdown follows the ordinary shutdown
outcome and spawns nothing; a presentation failure remains fatal and never
falls through to attach. A
rich TUI host that wants a nonblocking managed driver must define process
supervision, terminal-release handshake, log routing, exit policy, and
rollback in its own spec; Taut's first such host is governed by
`docs/specs/10-taut-tui.md` [TUI-11] rather than by guessed Summon behavior.

A rich host may publish a typed command-syntax provider for the extension's
CLI command paths and a separate native host binding. The provider may parse
`summon` and `dismiss` mirror input into typed request values, but it never
invokes the CLI adapter or owns the host terminal. A TUI host continues to
call the public controller and to supply the [SUM-13] interaction adapter.
Provider absence, malformed input, unavailable provider, and terminal-lease
failure remain distinct user-visible outcomes.

### Foreground readiness for rich hosts [SUM-13.1]

`run_foreground` accepts an optional keyword-only
`on_ready: Callable[[SummonRunHandle], None] | None = None`. Existing callers
that omit it retain the same blocking behavior, timing, and result contract.
When supplied, Summon invokes it exactly once on the foreground-run owner
thread, after the first provider generation is live and its control loop has
installed its broker handles and is consuming correlated public `status()`
and `stop()` operations from other threads, and before entering long-running
supervision. The owner waits only when a callback was supplied; that wait is
bounded to 30 seconds and aborts early on control failure, shutdown, or first-
generation death. A timeout or aborted readiness wait follows the normal
failing-startup cleanup path. A fresh provider generation does not invoke the
callback again.

The `SummonRunHandle` contains the actual `SummonedMember`: member id,
collision-resolved current name, and provider. It exposes that value as
immutable field `member: SummonedMember` and one method,
`request_stop() -> None`. That method is thread-safe, nonblocking,
idempotent, and bound to this exact foreground run; it requests the existing
driver-owned shutdown path without resolving a mutable member name or
affecting a replacement driver. The driver marks the handle completed in the
foreground run's outer `finally`, after which `request_stop()` is a no-op. The
blocking `run_foreground` return or error, not `request_stop()`, remains the
host's teardown and release result.

The callback runs inline and must return promptly. It may store the handle or
call its nonblocking `request_stop()`, but it must not call a blocking
controller operation that waits for this same foreground owner to complete.
The callback is not invoked when startup fails before readiness. If it raises
an `Exception`, Summon tears down the live generation, stops the control lane,
releases its evidence-owned session row through the normal driver path, and
raises `SummonOperationError` with the callback failure as its cause. A
`BaseException` outside `Exception` receives the same cleanup before the
existing host-cancellation propagation policy applies.

Once invoked, the callback does not promise that the driver remains live after
it returns; rich hosts must reconcile readiness with the blocking foreground
call's completion. The handle grants only exact-run stop request authority. It
does not transfer driver, terminal, signal, process, ledger, teardown, or
release ownership.

Verification uses the public controller with a real scripted child and real
control exchange. It proves exact once-only callback delivery across a fresh-
generation restart, actual auto-renamed and re-summoned identity, exact
member/provider delivery, concurrent status at the readiness boundary, run-scoped
stop after post-readiness member rename, idempotent stop before and after
completion, bounded control-open failure, callback-failure teardown and
evidence release, no callback before startup failure, and unchanged CLI
behavior and timing when the callback is absent. A host must not derive
foreground ownership by diffing `list_live()` snapshots.

`SummonController` is bound to one optional database path. It exposes sorted
provider names through `provider_names()` without constructing adapters; live
session summaries through `list_live()`; one correlated live status; one
confirmed stop result; and a blocking foreground run with keyword-only
`install_signal_handlers: bool = False` and
`on_ready: Callable[[SummonRunHandle], None] | None = None` that returns no
value on clean completion. `list_live()` returns an empty tuple when no database or no
live rows exist; command adapters, not embedders, translate that empty result to
the nothing-summoned exit class. The request model contains `name`, `threads`,
`persona`, `system_prompt_file`, `rate_limit`, `attach`, `detach`,
`provider_flag`, and `takeover`; the database path belongs to the controller.
A live summary contains member id, current name, and provider. A stop result
contains member id and current name. Status contains
those identity/provider values plus driver, thread count, cursor lag, and
defensive copies of remaining validated JSON-primitive detail fields; it never
exposes a raw reply.

Public controller operations return typed domain results and raise typed
`NothingSummoned`, `DriverUnresponsive`, or `SummonOperationError`. They do not
print, return CLI exit codes, or require callers to parse human or JSON output.
Command adapters own rendering and map `NothingSummoned` to exit 2 and the other
public operation errors to exit 1.

[SUM-13] verification crosses the public controller boundary with real
process environment and signal APIs. It proves environment non-mutation
during and after a real rich-host lifecycle; default signal non-ownership;
exact opt-in restoration on clean and failing exits; invalid worker-thread
opt-in; exact child `TAUT_TOKEN` with absent child `TAUT_AS` through the single
PTY adapter on each supported platform; and unchanged CLI SIGINT/STOP release. Tests that
clear ambient identity, disable signal installation, or run only off the main
thread do not satisfy this boundary by themselves.

The shell-first attach matrix additionally proves acknowledgement precedes
provider spawn, cancel and prompt failure spawn no child or lease, attach
output survives the reader handoff without duplicate terminal replies,
bracketed-paste framing survives detach, and listener readiness follows the
retained quiet interval rather than the no-output maximum. The
setup-recovery matrix proves: an unconfirmed input prompt with a
supporting host offers exactly one acknowledged recovery attach and
injects nothing beforehand; proceed tears down the suspect generation,
completes setup through the bridge, and reaches watcher readiness;
decline, `--detach`, kill-switch, non-`AVAILABLE` availability, and a
non-supporting host each fall through to today's inject-after-settle
behavior with at most one offer per run; a confirmed input prompt
changes nothing; and the give-up error carries the bounded sanitized
tail plus the `--attach` instruction.

## Implementation Mapping

- `docs/implementation/05-taut-summon-architecture.md` explains controller,
  driver, terminal-close request versus foreground finalization, PTY
  fd-operation ownership, host interaction, [SUM-7.4]'s byte-transparent
  attach boundary, and the raw-coverage integrity owner.
- `docs/implementation/06-command-extensions.md` explains how installed Summon
  manifests replace the temporary core bridge and how rich hosts compose the
  public controller without parsing a CLI. It also maps [SUM-3]/[SUM-13]
  command, standalone-console, and owned-log text through the public core
  terminal-text policy.

## Related Plans

- `docs/plans/2026-09-03-summon-unified-pty-cross-platform-plan.md` — removes
  the vendor-specific structured adapter and terminal-output speech path,
  promotes one PTY adapter for every provider, and adds the Windows ConPTY
  backend and cross-platform verification contract.
- `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md` — replaces
  target-shaped downgrade setup with a provenance-pinned Summon v2 migration
  fixture shared across real SQLite and PostgreSQL sidecars.
- `docs/plans/2026-08-28-simplebroker-8-reconciliation-plan.md` — raises the
  shared broker floors while preserving Summon's control and cleanup contract.
- `docs/plans/2026-08-24-extension-seams-process-containment-coverage-plan.md`
  — defines cross-platform Summon process-domain ownership and bounded
  descendant finalization without treating lifecycle containment as a
  sandbox.
- `docs/plans/2026-08-20-human-tabular-output-plan.md` — restores [SUM-3]'s
  field-before-structure boundary for standalone live and named status rows,
  including extensible detail fields.
- `docs/plans/2026-08-19-tui-setup-recovery-offer-plan.md` — sequence-
  stripped give-up tail (Slice 0), the [SUM-13] notice screen-excerpt
  field, and driver excerpt capture for the setup-recovery offer.
- `docs/plans/2026-08-18-summon-setup-gate-recovery-attach-plan.md` — adds
  [SUM-7.4] setup-gate detection (input-prompt confirmation via bracketed
  paste), the single acknowledged setup-recovery attach, the bounded
  output-tail diagnostic, and the enriched [SUM-11] give-up error.
- `docs/plans/2026-08-18-tui-deep-review-remediation-plan.md` — adds the
  [SUM-10] multiline-sends briefing bullet so summoned members stop typing
  literal `\n` into quoted `taut say` arguments.
- `docs/plans/2026-08-17-summon-first-attach-handoff-plan.md` — repairs the
  shell-first attach handoff, then adapts and proves the same public
  interaction through the TUI host.
- `docs/plans/2026-08-17-tui-command-mirror-plan.md` — adds typed Summon
  syntax discovery and a separate TUI-native binding over the public
  controller without reusing the CLI adapter or terminal owner.
- `docs/plans/2026-08-14-debug-failure-capture-plan.md` — assigns one debug
  containment owner to each Summon console path without changing driver
  supervision or cleanup priority.
- `docs/plans/2026-08-14-review-findings-remediation-plan.md` — review-driven
  lifecycle, contract-proof, diagnostic, and release-gate remediation for
  the coordinated 0.9.0 candidate.
- `docs/plans/2026-08-12-taut-tui-implementation-plan.md` — adds the
  human-first TUI rich-host lifecycle and this exact-run readiness handle.
- `docs/plans/2026-08-10-test-quality-remediation-plan.md` — replaces
  scheduler-sensitive and fail-open Summon tests with deterministic lifecycle,
  process, PTY, observation, and coverage-preserving proof.
- `docs/plans/2026-08-10-simplebroker-7-json-id-boundary-plan.md` — aligns the
  Summon v1 persistence timestamp boundary with SimpleBroker 7.
- `docs/plans/2026-08-07-taut-dump-load-plan.md` — durable Summon session
  export/import through the core persistence component seam.
- `docs/plans/2026-08-01-summon-rich-host-global-state-plan.md` — makes
  driver identity object-local, prevents inherited host identity in provider
  children, and separates safe rich-host signal defaults from explicit
  temporary CLI signal ownership.
- `docs/plans/2026-07-31-simplebroker-6-reconciliation-plan.md` —
  SimpleBroker 6.0.0 and SimpleBroker-PG 3.5.0 compatibility reconciliation.
- retired: 2026-07-14-terminal-output-safety-plan — shared terminal-text
  safety defaults for Summon command/diagnostic output, coordinated core floor,
  and an explicit byte-transparent PTY exemption; source `281f04fa`; see the
  ledger in docs/plans/README.md.
- `docs/plans/2026-07-13-ci-speed-determinism-release-evidence-plan.md` —
  strict prepared local-LLM proof, complete failure evidence, and shared
  exact-SHA release artifacts without duplicate test workflow calls.
- `docs/plans/2026-07-13-release-metadata-preparation-plan.md` — synchronized
  SimpleBroker floor ownership and release preparation before verification.
- `docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md`
  — installed command adapters, lazy loading, public Summon embedding, and
  future rich-host terminal composition.
- `docs/plans/2026-07-12-automatic-display-name-capitalization-plan.md` —
  capitalized implied-provider names and cased automatic collision fallbacks.
- `docs/plans/2026-07-11-multi-factor-review-remediation-plan.md` — reviewed
  direct-name bootstrap, trust framing, dynamic audit, PTY bound, and
  documentation remediation program for v0.5.3.
- retired: 2026-07-10-ci-failure-remediation-plan — v0.5.1 CI
  remediation for PTY write leases, watcher pre-publication stop, artifact
  fixture portability, and deterministic waiter-rebind proof; source
  `b03709452`; see the ledger in docs/plans/README.md.
- `docs/plans/2026-07-10-taut-dynamic-native-waiter-replacement-plan.md` —
  active shared-core waiter replacement and paired dependency-floor follow-on;
  Summon's control topology remains fixed.
- `docs/plans/2026-07-10-taut-summon-quality-remediation-plan.md` — approved
  state, lifecycle, control, artifact-release, and documentation remediation.
- `docs/plans/2026-07-28-summon-terminal-retirement-plan.md` — separates
  reusable adapter interruption from one-signal terminal retirement and makes
  invalid raw coverage shards fatal.
- `docs/plans/2026-07-09-taut-reactor-safety-plan.md` — planned control-reactor
  ownership, inter-turn recovery, activity wake, and fatal control-thread
  supervision hardening.
- `docs/plans/2026-07-06-taut-summon-plan.md` — implementing plan: spec
  promotion and reference-gate extension, the `taut-summon` extension
  package, core delegation verbs, session ledger, adapters, driver,
  control plane, and conformance suite.
- `docs/plans/2026-07-07-taut-summon-pty-harness-adapter-plan.md` —
  implementation plan for the universal PTY adapter, attach/detach, the
  `wired` ledger flag, and live harness conformance.
- `docs/plans/2026-07-08-taut-sqlite-contention-hardening-plan.md` —
  hardening plan for SQLite contention robustness: live STATUS/readiness
  evidence, SimpleBroker handle ownership, integrity probes, and watcher
  handle-lifetime proof.
