# Taut Summon — Proposed Spec Draft

Date: 2026-07-06

Status: draft — this file is the review target for the summon plan
(`docs/plans/2026-07-06-taut-summon-plan.md`). The spec-promotion slice
copies it to `docs/specs/04-summon.md` with `Status: Active`; until then the
governing text for summon remains [TAUT-12.3] at the plan's spec baseline.

Design lenses applied to every decision below, recorded once here and cited
as **(L1)** and **(L2)** throughout:

- **L1 — agent-usable:** does this work for an agent operating the system —
  the summoned agent itself, other agents in the chat, and agents reading
  this spec to implement or debug it?
- **L2 — person-shaped:** does the observable behavior match what a human
  member would do in the same situation?

## 1. Purpose and Scope [SUM-1]

`taut summon` hosts an existing agent harness (Claude Code, Codex CLI, or
any provider CLI with a resumable streaming session mode) as an ordinary
member of a taut workspace. Summon does not build an agent loop, a task
runtime, or a sandbox; the harness already owns tool dispatch, session
state, interruption, and permissions. Summon is the agent's **terminal**:
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

**Ears and mouth.** The summoned member's *ears* are an injected stream:
the summon driver watches every thread the member has joined plus its
notification inbox, and pushes each message into the harness's live
session as it arrives. The member's *mouth and hands* are the taut CLI
itself: the agent speaks by running `taut say <thread> ...` as an ordinary
tool call, selected as its member by its continuity token ([TAUT-5]:
continuity, not authentication). Summon never interprets
or routes agent output (L1: explicit, inspectable actions; L2: a person
chooses where to speak — nobody transcribes their mumbling into the right
channel).

**The driver is a terminal emulator, not a manager.** One foreground
process per summoned member, exactly like `taut watch`: it exists while
the agent is summoned and is zero processes otherwise. The no-daemon
property of [TAUT-2] holds end to end.

**A summoned agent is just a member.** Identity, cursors, presence,
mentions, DMs, and history work identically to a human member. Every
capability difference between a summoned agent and a human member is a
spec defect (L2 stated as an invariant).

**Captive process, free agent.** The harness child *is* a captive
process: the driver spawns it, owns its stdio, signals it, anchors
presence to it, resumes it, and kills it. What is deliberately not
captive is meaning: captured stdin carries the ears; captured stdout is
supervision telemetry (activity, session ids, diagnostics), never parsed
into speech; and the conversation loop belongs to the harness. Full
captivity (sealing) is composition, not architecture: wrap the spawn
command (`--exec "docker run -i ..."`) and the same driver supervises a
sealed instance.

## 3. Packaging [SUM-3]

- Ships as the separate extension package **`taut-summon`**
  (`extensions/taut_summon`), per [TAUT-12.3]. Runtime dependencies:
  `taut` only — no new third-party packages. The provider harness is an
  external executable, not a dependency.
- Surface: core gains two **delegation verbs** — a deliberate, small
  [TAUT-8.1] revision (plan delta D4) because the human phrase is
  `taut summon claude`, and the agent-usable phrase is the same one (L1,
  L2 agree):

```text
taut summon PROVIDER_OR_NAME [THREAD ...] [flags]   # default thread: general
taut dismiss NAME
```

  Core's implementation is a thin hand-off: if the `taut_summon` package
  is importable, delegate argv; otherwise exit 1 with a one-line install
  hint. Core gains no summon logic and no dependency.
- The extension installs the console script **`taut-summon`** carrying
  the real entry points (`run`/`stop`/`status`); the core verbs map
  argv **verbatim** onto them (`taut summon X ...` ≡ `taut-summon run
  X ...`), so both surfaces share one resolution contract:
  `run NAME_OR_PROVIDER [THREAD ...]` — the positional is always the
  **member name**; the provider resolves in order: (1) `--provider`
  when given (a re-summon whose session row disagrees is an error
  naming the stored provider — members do not switch harnesses
  implicitly); (2) the existing session row's stored provider (the
  re-summon case: `taut summon reviewer` just works after
  `taut summon reviewer --provider claude`); (3) the name itself when
  it matches a registered adapter (the first-summon convenience);
  (4) otherwise an error naming the known adapters. Name-collision
  behavior depends on whether the name was chosen or implied
  ([SUM-4] states the rule; summarized): the convenience form
  (`taut summon claude`, name implied by the provider) falls back
  through the [IAN-9] pool — a second claude becomes `claudette` or
  `claude-2`, with a console note; an explicitly chosen name
  (`--provider` given) that collides with a non-summoned member
  refuses loudly instead. Default thread `#general` unless threads are
  given; `taut summon reviewer --provider claude dev` names the member
  `reviewer`, re-summonable thereafter by name alone.
- `stop`/`status` are thin clients of the control plane ([SUM-9]) usable
  from any terminal; `taut dismiss NAME` is `stop`.

## 4. Identity, Membership, and Presence [SUM-4]

- The member's identity evidence is **ultimately the harness child
  process** — after the bootstrap's `rejoin()` step the anchor points at
  the child — and the driver supplies captures explicitly rather than
  relying on ambient capture (a human launching `taut summon` from a
  terminal would otherwise classify as a human member — wrong kind,
  wrong anchor). During bootstrap, a temporary **driver-anchored** agent
  capture bridges the gap, because the token must exist before the
  child can be spawned with it (do not try to spawn first). The seam is
  public: `taut.identity`'s exported capture types and
  `capture_process` (this spec makes that surface part of the extension
  contract) feeding `TautClient(identity_capture=...)`.
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
      (`summoned as 'claudette' — 'claude' is taken`). The user asked
      for *a* claude, not that exact string (L2).
    - *Chosen name* (`--provider` given, so the positional was a
      deliberate choice): refuse loudly with the collision and a hint
      to pick another name. Silently renaming a name the user chose
      would surprise both people and scripts (L1, L2).
    This chosen-name refusal applies at **resolution time**, before
    anything is created. A collision that appears later, inside the
    bootstrap window (step 2's `set_name` failing because the name was
    taken mid-summon), is handled the same way for implied and chosen
    names alike: fall back per step 2 — refusal there would strand the
    already-created temp-named member, and a fallback with a loud
    console note (`requested name 'reviewer' was taken mid-summon;
    member is 'reviewer-2' — rename with 'taut set name' if needed`)
    is recoverable while leaving no debris. No member at all → first
    summon: claim the name (step 0) and create under a temp name
    (step 1).
  - **Bootstrap ordering** (resolves three constraints at once: the
    token/env cycle — the child env needs `TAUT_TOKEN`, minted at
    creation, and env cannot be retrofitted; the concurrent-summon
    race; and the rule that a foreign member must never be touched,
    not even detectably-then-aborted — explicit-`as_name` resolution
    adopts an existing member *before* any check can run, so the
    design must make adoption impossible rather than detected):
    0. *Claim the name*: transactionally insert (name, provider) into
       the transient claims table ([SUM-8]). A loser of a concurrent
       same-name summon gets the constraint error and applies the
       collision rule above — nothing exists yet, so it applies
       cleanly: an implied name retries with the `choose_name`
       fallback (two simultaneous `taut summon claude` yield two
       members, never one shared member); a chosen name refuses loudly
       (two simultaneous `taut summon reviewer --provider claude`
       yield one `reviewer` and one clean refusal). Claims from dead
       drivers are reclaimable by evidence.
    1. *Create under a fresh temp name* — first summon only:
       `TautClient(identity_capture=<agent capture anchored at the
       DRIVER process>, as_name=<temp>).join(thread)` where `<temp>` is
       driver-generated and collision-proof (target name + random
       suffix). A fresh name **cannot adopt** — creation is guaranteed,
       asserted via the public `last_created_member` signal (blessed
       extension-visible surface, with its `token` field); the token
       goes to the ledger. The one cosmetic cost: the join notice
       renders the temp name for a moment (L2: a nickname settling).
    2. *Take the target name*: `set_name(<claimed name>)` — core's
       transactional, fail-loud rename ([IAN-4.4]). If a non-summon
       actor took the name inside the window, this fails **without
       having touched their member**; the driver then releases the now
       stale claim and **restarts at step 0 with a `choose_name`
       fallback target** (console note), so every name the member ends
       up under was covered by a claim — the race guarantee never
       lapses. The already-created temp-named member is reused by the
       restarted pass (steps 0 and 2 rerun; step 1 is skipped).
    3. *Record the session*: insert the member_id-keyed sessions row
       ([SUM-8]) and delete the claim row — old names become claimable
       again the moment they are no longer load-bearing.
    4. *Spawn the harness* with `TAUT_TOKEN=<ledger token>` in its
       environment ([SUM-6]).
    5. *Re-anchor to the child*: `TautClient(identity_capture=
       <child capture>, token=<ledger token>).rejoin()` — token-only
       selection (`rejoin` rejects a name combined with a token by
       contract, [TAUT-8.1]); rejoin re-associates the child as the
       member's anchor through the public path ([IAN-3.4]).
    Later summons resolve the current name to a member_id (public
    lookup), read the sessions row, and run exactly steps 4-5 — one
    shape for every summon, no private state calls anywhere.
- Evidence-based presence then works unchanged: `taut who` shows `here`
  while the harness runs and `gone` after it exits, with no
  summon-specific presence code (L2: presence means the same thing for
  everyone).
- Thread membership is ordinary membership. **Positional `[THREAD ...]`
  is the canonical thread syntax at both entry points** (`taut summon
  PROVIDER [THREAD ...]` and `taut-summon run NAME [THREAD ...]` — core
  delegation maps argv verbatim; there is no `--thread` flag); each is a
  convenience `join`, defaulting to `general` when none given. The agent
  may `taut join`/`taut leave` on its own thereafter ([SUM-6]).

## 5. Ears — the Injection Contract [SUM-5]

### [SUM-5.1] Sources and ordering

The driver watches, via the public `TautClient.watch(...)` surface, every
chat thread the member has joined plus the member's notification inbox,
and injects events into the harness session in **watcher delivery
order** — the multi-queue watcher's merged order, which is per-thread
chronological but makes no global cross-thread timestamp guarantee.
Membership changes mid-run are picked up exactly as `taut watch` does.

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

### [SUM-5.3] Filtering

The driver injects **everything except the member's own messages**
(`from_id == self`, mechanical). It does not filter by sender kind: the
flagship reviewer case requires hearing other agents' status posts.
Restraint about *responding* is persona policy ([SUM-10]), not input
policy — a person hears the whole room and chooses when to speak (L2).
Per-thread input filters (e.g. mention-only in a noisy channel) are a
`run`-time option, off by default.

### [SUM-5.4] Cursor as injection ledger

The member's per-thread cursors ([TAUT-7.2]) are the injection ledger,
and the mechanism is the watch surface's existing handler contract — the
driver adds **no cursor code of its own**. `TautWatcher` advances a
thread's cursor only after the user handler returns successfully; a
raising handler leaves the cursor in place and the message is re-seen
([TAUT-8.4]). The driver's watch handler is exactly: self-filter, format
([SUM-5.2]), `inject()`, return. (Rate-backstop counting is **not** in
this handler — the member's own sends never reach the watch stream,
[SUM-10] audits separately.) Consequences, all required:

- **At-least-once delivery to the harness process boundary:**
  `inject()` must not return until the event is written *and flushed* to
  the child's stdin, and must surface write failures synchronously — a
  failed or interrupted `inject()` raises out of the handler → cursor
  stays → the message re-injects on the next cycle. A driver killed
  between a successful inject and the watcher's cursor flush re-injects
  a small tail on restart (harnesses tolerate duplicate user messages
  far better than lost ones). Named residual: a harness that crashes
  *after* reading but before processing an event may lose it from that
  provider session while the cursor has advanced — that window belongs
  to the provider's session durability, and the recovery story is the
  standing one ([SUM-7.3]): the chat history is the durable
  conversation, reachable to the agent itself via `taut log`. Adapters
  whose protocol offers an ingestion acknowledgment should await it
  before returning; none is required.
- **Restart replay:** a new driver (or a fresh harness session after a
  crash) starts by injecting everything after each stored cursor — the
  chat history is the durable conversation ([SUM-7.3]).
- **Backpressure:** if the harness stalls, `inject()` blocks or raises,
  cursors stop advancing, and unread accumulates honestly; `taut list`
  shows the member falling behind exactly as it would a person on
  vacation (L2). The driver never buffers message text beyond the write
  in flight.
- Notification-inbox events are claim-consumed by the watch (per
  [IAN-7.4]); their injection is therefore at-most-once, which matches
  their pointer semantics.

## 6. Mouth — the CLI Contract [SUM-6]

- The child environment carries `TAUT_TOKEN` (the member's continuity
  token — continuity, **not** authentication, per [TAUT-5]/[TAUT-9]: it
  selects the member within the storage trust boundary and proves
  nothing) and, when the backend is path-addressed, `TAUT_DB`. The agent
  speaks with ordinary CLI calls; replies route wherever the agent says
  (`taut say dev ...`, `taut reply`, `taut say @van ...`).
- **stdout is diagnostics, not speech.** In multi-thread operation the
  driver never posts harness output to chat. Assistant text that arrives
  unrouted goes to the driver's log. Exception — *terminal mode*: when
  summoned with exactly one thread and `--terminal`, the adapter posts
  assistant text blocks to that thread, preserving the degenerate
  single-channel case for harnesses without tool access.
- The persona template ([SUM-10]) makes the mouth contract explicit to
  the agent, including "never answer in a thread other than the one you
  mean" and "if you cannot run taut, say nothing rather than print to
  stdout" (L1: the failure mode is silence, not misdelivery).

## 7. Provider Adapters [SUM-7]

### [SUM-7.1] Adapter interface

An adapter owns exactly four things:

```python
class ProviderAdapter(Protocol):
    def spawn(self, *, session_id: str | None, system_prompt: str,
              env: Mapping[str, str]) -> AdapterHandle: ...
    # AdapterHandle:
    def inject(self, text: str) -> None          # one user-role event
    def events(self) -> Iterator[AdapterEvent]   # typed output stream
    def interrupt(self) -> None                  # harness-graceful stop
    # .session_id property: provider session for resume
```

`AdapterEvent` is a small closed union: `assistant_text`, `activity`
(tool use — feeds presence, never posted), `session` (id updates),
`exit`. There is **no summon-defined wire protocol**: the wire format is
the provider's own streaming envelope (Claude Code `stream-json`, Codex
JSONL). Adapters translate; they do not define.

Contract requirements on every adapter: `inject()` returns only after a
flushed write and surfaces failures synchronously ([SUM-5.4]);
`interrupt()` and handle close are thread-safe and unblock any in-flight
`inject()` ([SUM-9] depends on this to stop a stalled harness);
`events()` must be **drained continuously by the driver** — the driver
owns a dedicated event-pump thread that consumes the stream for the life
of the child (session-id updates to the ledger; `activity` → member
activity via the public seam: a rate-limited token-selected resolution
(`whoami()` on a token client updates `last_active_ts` as a side effect
of [IAN-3.3] step 2 — at most once per activity window, never a private
`_state` call); diagnostics to the log; `exit` → the [SUM-11] resume
path). An undrained event stream is a child-stdout deadlock waiting to
happen; the pump participates in shutdown ordering (stop injection →
interrupt → pump drains to `exit` or bounded timeout → close).

### [SUM-7.2] Adapters shipped

- `claude` — Claude Code headless streaming (`--input-format
  stream-json --output-format stream-json`, resume via the harness's
  session mechanism). Exact flags are adapter implementation detail,
  verified against the installed CLI at implementation time, not
  contract.
- `scripted` — a test adapter spawning a real subprocess running a
  scripted provider (a small Python program speaking the same
  stream-json shapes). This is the anti-mocking seam: real process, real
  pipes, real protocol, fake model. It ships in the package (not tests/)
  so downstream integrators can use it (L1).
- `codex` — follow-on, same interface; named here so the interface is
  reviewed against two real providers even though only one ships first.

### [SUM-7.3] Session continuity

Session persistence belongs to the harness. The adapter reports the
provider session id; the driver persists it ([SUM-8]) and offers it back
at the next spawn. A provider whose session cannot resume degrades to a
fresh session plus cursor replay ([SUM-5.4]) — the chat history *is* the
durable conversation; the harness session is an optimization of it.

## 8. Session Ledger and Single-Driver Guard [SUM-8]

- **Two extension-owned sidecar tables**, split by lifetime:
  - `taut_summon_claims` — **transient**. One row per in-flight
    bootstrap: (name, provider) PRIMARY KEY (the concurrent-summon
    serialization point, [SUM-4] step 0), driver pid + start-time
    evidence, claimed timestamp. Deleted at [SUM-4] step 3; a row whose
    driver evidence is dead is reclaimable. Because claims are
    transient, a name a member has since renamed away from is claimable
    again — the name key never permanently occupies anything.
  - `taut_summon_sessions` — **durable**. One row per summoned member:
    `member_id` PRIMARY KEY (created only after the member exists, so
    never NULL on any backend), the member's continuity token (captured
    at creation — output-visible once, per [TAUT-8.2]; storing it is
    consistent with [TAUT-9]: db access is already membership),
    provider name, provider session id, driver pid + start-time
    evidence, updated timestamp.
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
  (SQLite or Postgres); Redis waits on the [TAUT-12.2] state mapping.
- **Single-driver guard:** `run` refuses when the ledger row shows a
  live driver (pid + start-time still alive, same evidence style as
  presence). Two drivers injecting into two harness sessions as one
  member would double-speak (L2: a person is in one place). `--takeover`
  replaces a dead or abandoned claim.

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
- The driver consumes control queues with its **own consumer on a
  dedicated thread**, over the public `simplebroker` Queue/watcher
  surface — control commands are claim-consumed (they are commands, not
  history), and `TautClient.watch(...)` deliberately knows nothing about
  `sys.*`. Control must stay responsive while injection is blocked on a
  stalled harness: STOP's shutdown path closes the adapter handle, and
  `AdapterHandle.close()`/`interrupt()` are required to be thread-safe
  and to **unblock any in-flight `inject()`** ([SUM-7.1] contract) — a
  stuck harness can always be stopped.
- `taut-summon stop NAME` writes STOP; the driver stops injection,
  interrupts the harness via the adapter (its own graceful path — the
  Ctrl-C analogy), waits bounded, posts nothing on the member's behalf,
  updates the ledger, exits 0. SIGINT to the driver is the same path.
- STATUS returns driver liveness, provider, session id, thread count,
  cursor lag summary. PING is STATUS minus detail. Both work while the
  harness is mid-turn (control responsiveness during idle *and* busy is
  a conformance item).
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
    addresses work products, not other commentary.
- Driver-side backstop: a per-member posting rate limit (default
  generous, `run`-configurable) so a persona failure degrades to
  throttled chatter, not a two-agent feedback loop. Observation
  mechanism: the watch stream **cannot** see the member's own sends —
  [TAUT-7.4] advances the sender's cursor at write time — so the driver
  runs a periodic **audit pass** on its control-thread cadence:
  log-semantics peeks after a driver-local audit cursor per thread
  (never touching the member cursor), counting messages with
  `from_id == self` in the window. Breach → inject a system nudge and
  log; hard breach → interrupt the harness and report on ctrl_out
  (never posting to chat as the member). The driver never enforces
  content policy — restraint is the persona's job; the backstop is a
  circuit breaker (L1: mechanical guarantees where personas can fail;
  L2: the rate of a person typing).
- `--persona TEXT` sets the member's short taut persona as `join` does;
  `--system-prompt-file PATH` replaces the template for full control.

## 11. Failure Modes [SUM-11]

- Harness crash: driver observes `exit`, marks ledger, attempts one
  resume (session id, then cursor replay); repeated crashes back off and
  exit with the reason on ctrl_out and stderr. Never auto-posts to chat
  as the member.
- Driver crash: cursors and ledger make restart safe (at-least-once
  injection); the stale ledger claim is reclaimable by evidence.
- Unroutable output ([SUM-6]) → driver log only.
- Slow harness → backpressure via cursor lag ([SUM-5.4]); STATUS reports
  it.
- Storage gone / token invalid → driver exits loudly; nothing is
  consumed beyond claimed notifications already injected.
- Two summons, one member → refused by the single-driver guard.

## 12. Verification Expectations [SUM-12]

- Anti-mocking floor unchanged: broker, sidecar, and CLI are never
  mocked. The provider seam is the `scripted` adapter — a **real
  subprocess speaking the real stream shapes**; only the model is fake.
  One live smoke test against an installed Claude Code CLI ships marked
  `requires_claude`, skipped when absent.
- The **conformance suite** obligated by [TAUT-12.3] ships as tests
  parameterized over `ProviderAdapter` + driver, portable so Weft can
  run them against its agent lane. Named items: control responsiveness
  while idle and while mid-turn; restart with conversation scope intact
  (session resume and fresh-session replay both); backpressure when the
  agent is slower than the chat; clean shutdown on stop with no
  double-speak; single-driver guard; injection format stability.
- Driver tests run real multi-process flows (a second CLI process
  writing to the watched thread), matching [TAUT-11] discipline.
