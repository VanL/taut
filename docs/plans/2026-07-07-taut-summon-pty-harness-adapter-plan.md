# Taut summon — universal PTY harness adapter plan (v8)

Date: 2026-07-07

Status: **APPROVED FOR IMPLEMENTATION (v8 — clean both-Yes at round 8).** Both
independent reviewers (Codex + Claude, different agent families) returned **Yes /
no P1 blockers** against the actual code. All round-8 P2 precision advisories are
folded in: `rate_breaches` added to the STATUS reserved-key list; `ensure_threads`
pinned in the startup order; the `handed_off`/`_reader_started` flag unified to a
single `_reader_started` (set under the lifecycle lock); the spawn-span guard
re-raises after `close()`; and the close-before-first-read `EBADF` window handled
by treating any `OSError` on the master read as end-of-stream. Ready to build
slice-by-slice (S1→S2→S3→S4→S4b→S5→S6→S7; independent review after S4b).

Plan type: implementation with spec revision. Adds `[SUM-7.4]`; **reconciles**
`[SUM-1]`, `[SUM-6]`, `[SUM-7.1]`, `[SUM-7.2]`, `[SUM-10]`, `[SUM-12]` (the v1
delta was incoherent in isolation — review P1). Promotion strategy **B**
(spec text + code + tests land together per slice; the extension is
uncommitted anyway).

## 1. Goal

Let `taut summon` host **any interactive agent CLI**, not just harnesses with a
headless streaming protocol. Summon runs the harness in its normal
**interactive** mode on a pseudo-terminal and acts as a real (minimally
capable) terminal: it can **attach** the human's terminal to the harness for
setup, then **detach** into a background driver that injects taut chat as typed
input and lets the agent speak through the ordinary `taut say` mouth. One
adapter covers claude, codex, coder (@just-every/code), grok, qwen, kimi,
opencode, pi — and anything future — and delivers the persistent, interruptible
"monitor and comment in real time" session the summon design wanted from the
start (a one-shot `-p` cannot).

## 2. Source Documents

- `docs/specs/04-summon.md` — [SUM-1] scope, [SUM-2] terminal/ears/mouth,
  [SUM-4] presence-by-anchor, [SUM-5] ears, [SUM-6] mouth/terminal-mode,
  [SUM-7] adapters, [SUM-10] persona, [SUM-11] resume, [SUM-12] conformance.
- `docs/plans/2026-07-06-taut-summon-plan.md` — the completed summon build
  (Phases A–E); §15 Implementation Record and §5 context are the structure
  this extends.
- Investigation record (2026-07-07): empirical PTY probes + startup-byte
  diagnostics of all eight installed harnesses. Findings in §3.

## 3. Investigation Findings (ground truth — read before designing)

Probed all eight installed CLIs. **`code` is VS Code on this machine, not a
harness** — the @just-every/code harness binary is **`coder`** (a Codex fork).
Never invoke `code` as a harness.

- **The PTY mechanism works.** With `TERM=xterm-256color`, typing a line + `\r`
  into a stdlib PTY submitted a turn and the agent responded, over
  `pty.openpty()` + `Popen(start_new_session=True)` — threaded-safe, zero
  dependency. Confirmed input reached claude, coder, grok, kimi, opencode.
- **They are full-screen TUIs** (alternate-screen + cursor addressing)
  regardless of `TERM`. `TERM=dumb` does not simplify them — it *breaks* them
  (claude stops accepting input; codex I/O-errors). Present a **capable**
  terminal and do not parse output.
- **Harnesses send terminal queries on startup** that a real terminal answers
  and a dumb reader does not: captured from codex — `ESC[6n` (cursor position),
  `ESC[c` (primary device attributes), `ESC]10;?`/`ESC]11;?` (OSC fg/bg color),
  `ESC[?u` (kitty keyboard). Summon must answer these (a small responder) to be
  a *minimally capable* terminal, not a dumb pipe.
- **Some harnesses gate first use behind an onboarding/trust prompt.** codex's
  captured startup ends at *"Trusting the directory allows project-local
  config, hooks, and exec policies to load. › 1. Yes, continue  2. No, quit —
  Press enter to continue."* It blocks there. In a normal shell the human
  answered it once and codex remembered the directory. This is the real reason
  codex "failed" in the first probe — not PTY incompatibility. **We do not
  auto-bypass this** (it is a security decision); the human answers it during
  the attach phase (§4, [SUM-7.4]).
- **Two harnesses have no credentials configured on this box** — not summon's
  problem: qwen (default model paywalled — needs a model slug) and pi (empty
  `~/.pi/agent/auth.json`, no `GOOGLE_API_KEY`/provider key — never logged in).
  Both would be resolved by the human authenticating during an attach phase, or
  they skip in the live tests.

Design consequences (all load-bearing):

- Library: **stdlib `pty` only.** No `ptyprocess`/`pexpect`/`tmux`/`pyte`. The
  controlling-tty concern did not manifest (harnesses work over the slave fd via
  `isatty`); `Popen(start_new_session=True)` is the threaded-safe spawn.
  Bridging a tty to the master (attach) and answering queries are small stdlib
  loops. Reserve a library only if a real harness forces a controlling tty the
  stdlib path can't give.
- We never parse the TUI as speech. Mouth = `taut say`. The human sees the TUI
  by *attaching*; the driver reads bytes only for coarse liveness.
- Onboarding/trust/login/model-pick are handled by the **human during attach**,
  not by per-harness auto-dismiss flags.

## 4. Proposed Spec Delta (reconciled — replaces the v1 delta)

Promotion strategy B. Exact edits:

### [SUM-1] scope — replace "resumable streaming CLI" with:

> `taut summon` hosts an existing agent harness (any interactive CLI, or a
> resumable streaming CLI where one is available) as an ordinary member.

### [SUM-2] captive process — amend the stdout-telemetry sentence:

> For a structured streaming adapter, captured stdout is supervision telemetry
> (activity, session ids, diagnostics). For the PTY adapter ([SUM-7.4]) there is
> no structured stream: the master carries the harness's raw TUI, read only for
> coarse liveness, the terminal-query responder, and diagnostics — no session
> ids, never parsed as speech. In both cases stdout is never speech; the mouth
> is `taut say`.

### [SUM-6] mouth / terminal mode — append:

> Terminal mode (posting the harness's assistant text to a thread) requires a
> parsed reply and is therefore supported only by structured streaming adapters
> ([SUM-7.2] `claude-stream`), not the PTY adapter ([SUM-7.4]), which never
> parses the screen. An adapter declares `supports_terminal_mode`; the driver
> checks it before enabling terminal mode and warns + disables when false. To
> *watch* a PTY-hosted agent, a human **attaches** ([SUM-7.4]) rather than
> having assistant text mirrored to chat.

### [SUM-7.1] adapter interface — append:

> An adapter that has no structured wire envelope (the PTY adapter, [SUM-7.4])
> emits only the `activity` and `exit` members of the event union — a permitted
> subset; the driver's pump tolerates a stream that never yields `assistant_
> text` or `session`, and a `None` `session_id` degrades to a fresh spawn plus
> replay ([SUM-7.3]). Such an adapter must define `activity` as **coarse
> lifecycle liveness** (spawn, injection, or an output burst after an idle gap),
> never per-byte — a constantly-redrawing idle TUI must not keep `last_active_
> ts` fresh forever. Member presence remains anchored to the harness child
> process being alive ([SUM-4]), independent of output.

### Amend [SUM-7.2] — replace the `codex` bullet with:

> - `pty` — the **universal shell adapter** ([SUM-7.4]). Hosts any interactive
>   agent CLI over a pseudo-terminal; the default host for every named provider
>   (claude, codex, coder, grok, qwen, kimi, opencode, pi, …). No per-provider
>   protocol code — a provider is a binary plus optional spawn quirks.
> - `claude-stream` — the optional Claude Code headless-streaming adapter
>   (`stream-json`), retained for the structured session-resume, typed events,
>   and terminal-mode support it alone provides. Opt in by name.

### Insert [SUM-7.4] — PTY shell adapter

> #### [SUM-7.4] PTY shell adapter
>
> The default adapter runs the harness in its **interactive** mode on a
> pseudo-terminal and drives it as a minimally-capable terminal — the truest
> form of "summon is the agent's terminal" ([SUM-2]).
>
> **Spawn.** `pty.openpty()`; `subprocess.Popen(argv, stdin=slave,
> stdout=slave, stderr=slave, start_new_session=True, env=…)`; the parent
> closes the slave immediately and owns the master. `argv` is the harness's
> normal interactive launch. `TERM=xterm-256color` and a real window size
> (`TIOCSWINSZ`) are set; `TERM=dumb` is forbidden (breaks these TUIs).
> `start_new_session=True` (never `preexec_fn`, never `pty.fork()` from the
> multi-threaded driver) keeps the spawn threaded-safe.
>
> **Terminal-query responder.** A reader over the master answers the queries a
> TUI sends at startup so it can initialize.
>
> *Cursor position with clamping.* The responder tracks the cursor position by
> parsing the cursor-moving sequences a size-probe uses — both the **absolute**
> moves CUP `ESC[<r>;<c>H` / HVP `ESC[<r>;<c>f` **and** the **relative** moves
> CUF `ESC[<n>C` / CUD `ESC[<n>B` (and, for symmetry, CUB `ESC[<n>D` / CUU
> `ESC[<n>A`) — and **clamps the result to the configured window `(rows, cols)`**
> (and to `≥1`) before storing it (default 1;1). It answers **DSR cursor
> `ESC[6n` with the clamped tracked position**, not a fixed `ESC[1;1R`. Two
> common size-probes exist and both must work: the **absolute** park
> (`ESC[999;999H` then `ESC[6n`) *and* the **relative** walk to the corner
> (`ESC[9999C` `ESC[9999B` then `ESC[6n`); a real terminal *clamps* either to its
> winsize before replying, so we reply e.g. `ESC[<rows>;<cols>R`, never the
> literal `999;999R`/`9999R…` (a bogus giant terminal) nor `1;1R` (a 1×1
> terminal — the exact failure the relative walk would hit if we tracked only
> CUP/HVP). `TIOCSWINSZ` alone only helps apps that use `TIOCGWINSZ`, not the
> cursor trick, so the clamp is load-bearing. Tracking is best-effort — these
> absolute+relative moves cover the known probes; we do not emulate a screen.
>
> *Other recognized families.* DSR status `ESC[5n` → `ESC[0n`; primary DA
> `ESC[c`/`ESC[0c` → `ESC[?1;2c`; secondary DA `ESC[>c` → `ESC[>0;0;0c`; DECRQM
> mode queries `ESC[?<n>$p` (including the bracketed-paste-mode query
> `ESC[?2004$p` some apps send before enabling it) → a mode-report with state 0
> (`ESC[?<n>;0$y`, "mode not recognized/reset" — a valid DECRPM answer);
> XTVERSION `ESC[>q` → `ESCP>|taut-summon(0)ESC\`; OSC color `ESC]10;?`/`ESC]11;?`
> → a default rgb reply; kitty keyboard `ESC[?u` → `ESC[?0u`.
>
> *Unknown sequences get no reply — the inverse of a "benign no-op".* The master
> reply channel **is the harness's keyboard-input channel**, so any bytes we
> write in response to a sequence the app did not intend as a *report request*
> are injected as **spurious keystrokes** that corrupt the TUI worse than
> silence — and an arbitrary CSI/OSC emitted for the screen is
> indistinguishable, from the child side, from a report request. There is no
> universal "benign no-op". Therefore the responder replies **only** within the
> finite recognized families above and **emits nothing** for anything it cannot
> classify.
>
> *Validating responder completeness — the detached path has no human backstop.*
> The responder runs **only in detached driver mode**; during attach the real
> terminal answers queries, so **attach never exercises summon's responder**.
> A reader must not conclude "the harness reached a ready prompt under attach,
> therefore our query set is complete" — that proves nothing about the responder.
> The paths that *do* rely on it — **wired re-summons** and **[SUM-11] resumes**
> — run detached from byte zero with no human, and hit the responder with the
> harness's full startup-query battery, possibly for the first time ever (only
> codex's set was empirically captured, §3; the other seven are asserted). So an
> unrecognized **blocking** query would hang the automatic path silently.
> Two mitigations, both required:
> (1) **A `no-progress` stall diagnostic that catches the single-shot hang.** The
> worst case is **one** unclassified report-shaped query followed by the harness
> blocking forever on the reply — there is no *repeat*, so a "same query repeats"
> trigger would never fire. The trigger is therefore
> **"an unanswered report-shaped query is outstanding AND no output progress for
> `stall_s` (default e.g. 10 s)"** (a repeat merely re-arms the timer). This
> relies on a **blocked harness being silent** so `last_output_ts` freezes, so
> the reader uses a **timed `select`/poll, never a permanently blocking `read`**,
> and the timer keeps ticking while the harness waits on the reply. The premise
> holds for a single-threaded TUI (it stops emitting while blocked on the reply —
> codex's captured behavior, §3); a hypothetical render-threaded harness that
> keeps animating while another thread blocks would not trip the timer, which is
> why mitigation (2) is the **required backstop**, not the timer alone. On the
> trigger, the reader raises the bounded **`awaiting_query` stall diagnostic** —
> a driver-log line naming the raw sequence + a STATUS field, the sibling of
> `awaiting_onboarding`. Both STATUS fields reach a `STATUS` reply through a
> **named transport**: the handle exposes **`status_fields() -> dict[str, str]`**
> which the `ControlLoop` merges into the **`_status_fields()` `as_fields()`
> output** (not the frozen `StatusSnapshot` dataclass — it can't be mutated;
> `_status_fields()` already holds `self._handle_provider`, so it is the merge
> point, and `_status_snapshot()` does not consult the handle today — this hook
> is the addition). **JSON contract:** values are JSON-serializable **primitives
> only** — the `awaiting_query` value is the offending sequence as a **printable
> escaped string** (e.g. `[?15n`), never raw `bytes` (`json.dumps` in
> `encode_control_reply` would raise). **Reserved-key rule:** `status_fields()`
> keys must not collide with the existing snapshot keys (`driver`,
> `rate_limited`, `rate_breaches`, `provider`, `session_id`, `thread_count`,
> `cursor_lag`, `control_health`, `health_detail`) nor the envelope keys
> (`command`, `status`, `request_id`); a collision is a programming error a test
> asserts against.
> Covered by a test that issues a real `STATUS` request and observes the field.
> **Contract: report-only +
> human-recoverable, not auto-recover.** The diagnostic does not *break* the hang
> (we deliberately never fabricate a reply — that injects spurious keystrokes,
> the very corruption the responder avoids); it makes the hang *observable and
> named*, and the resolution is `taut summon --attach <name>`, where a real
> terminal answers the arbitrary query. This mirrors the `awaiting_onboarding`
> contract.
> A "report-shaped" sequence is a **conservative finite predicate**, not "any
> `ESC`": it matches the report-*request* families (DSR `ESC[…n`, DA
> `ESC[c`/`ESC[>c`, DECRQM `ESC[?…$p`, XTVERSION `ESC[>q`, OSC color query
> `ESC]1{0,1};?`, kitty `ESC[?u`) and **excludes** ordinary draw/control
> sequences (CUP/HVP, SGR, EL/ED, mouse/mode sets, cursor show/hide, scroll
> region) so a redrawing TUI cannot create false `awaiting_query` noise.
> (2) each registered harness's detached-mode startup query
> set is **captured and asserted** — the S2 fake harness is parametrized per
> family and S6's live test records the real set — so a gap is caught in test,
> not in production.
>
> **Attach / detach — state-based, no readiness heuristic.** Whether a human
> is bridged in is decided by a persisted **wired** flag, not by guessing
> readiness from output (which cannot distinguish "ready" from "waiting at a
> trust prompt" from "animating idle" without the screen parsing this design
> forbids). Per (member, provider), the ledger records whether the harness has
> ever been driven to a working state.
> - **First-ever summon (not wired), summon's stdin is a tty:** the launching
>   terminal is bridged raw-mode to the master both directions. The human
>   answers any trust prompt / `/login` / model pick, sees the agent reach its
>   ready prompt, and **detaches with a configurable chord** (see below). On
>   that detach the pair is marked **wired**. Summon **never auto-detaches on
>   the first run** — the human owns the "it's ready" judgment, so orientation
>   can never be typed into an unanswered prompt.
> - **Subsequent summons (wired):** no onboarding is expected, so summon goes
>   **straight to detached driver mode** — fully automatic, no bridge, no
>   detection. This is the "auto-dismiss if already wired" case.
> - **No tty** (pipe/cron/background): nothing to bridge → detached driver mode
>   with a notice; if the harness is not yet wired it may stall at its own
>   prompt (surfaced via STATUS/log, not a chat relay — see below).
>
> **Attach is two full-screen TUIs sharing one terminal** — it must be designed
> for that, not treated as a passive pipe:
>
> - **Detach chord (not `ESC`).** The harness reads keys in raw mode and uses
>   `ESC` heavily (the Escape key; arrows/function keys are `ESC[…`/`ESC O…`), so
>   intercepting `ESC` would swallow or delay the user's real input. The detach
>   trigger is a **configurable non-`ESC` chord** (tmux-style; default e.g.
>   `Ctrl-\ Ctrl-\`), matched by the bridge on the human's input stream *before*
>   forwarding to the harness. Any chord can collide with a harness binding, so
>   it is configurable and documented — the bridge never touches `ESC`-prefixed
>   sequences.
> - **Nesting (cooperative detection only).** From a normal shell or a
>   **tmux/screen pane** (a pane is a real terminal) attach works — the harness
>   draws in that pane. From **inside a single-terminal host TUI** (notably
>   taut's own future TUI, [TAUT-12.4]) two alt-screen apps cannot share the one
>   terminal. There is **no portable, reliable signal a child process can read to
>   know it is running inside another alt-screen app**, so nesting detection is
>   **cooperative, not automatic**: a host TUI that shells out to `taut summon`
>   sets **`TAUT_HOST_TUI=1`** in the child's environment (and any future
>   in-process host-attach API passes an equivalent flag). When summon sees that
>   marker it **refuses attach** and runs detached, with a message to attach from
>   a real terminal/pane, never scribbling over the host. Summon does **not**
>   promise to detect an *arbitrary* third-party host TUI that does not cooperate
>   — that case is documented as best-effort/unsupported (the human gets a
>   possibly-garbled screen and can `--detach`); the guarantee holds for taut's
>   own TUI, which cooperates. A host TUI attaches a summoned agent via the
>   editor/IDE **shell-out**: suspend itself, hand the whole terminal to the
>   harness for the attach (setting `TAUT_HOST_TUI` so a *further* nested summon
>   still refuses), reclaim and redraw on detach — i.e. the attach entry point
>   must be drivable by a host, not only from a bare shell.
> - **Terminal restore on detach is a fixed reset blast, not "modes it saw".**
>   The harness keeps running after detach and never cleans up its own terminal
>   state, and dynamically tracking "which modes the harness enabled" is
>   unreliable (we do not parse the screen). So summon writes a **fixed,
>   idempotent reset sequence** to the **local** tty in a `finally` on **every**
>   exit path (detach, EOF, exception, signal), in this order: first **`CAN`
>   (`0x18`)** to cancel any partial escape the harness left mid-write on the
>   local tty; then, unconditionally (these resets are harmless when the mode was
>   never set) — exit all alternate-screen variants (`ESC[?1049l`, `ESC[?47l`,
>   `ESC[?1047l`); show the cursor (`ESC[?25h`); reset the scroll region
>   (`ESC[r`); reset all character attributes / SGR (`ESC[0m` — `CAN` cancels a
>   *partial* escape but does not clear an already-applied color/bold the harness
>   set, so a colored shell prompt would otherwise persist); re-enable autowrap
>   (`ESC[?7h`); synchronized-output off (`ESC[?2026l`, so no output stays
>   buffered); alternate-scroll off (`ESC[?1007l`); DECCKM application-cursor-keys
>   off (`ESC[?1l`) and application keypad off (`ESC>`); focus-tracking off
>   (`ESC[?1004l`); disable every mouse variant
>   (`ESC[?1000l ?1002l ?1003l ?1005l ?1006l ?1015l`); bracketed-paste off
>   (`ESC[?2004l`); pop the kitty keyboard flags (`ESC[<u` — a single pop
>   under-pops a multi-level stack, an accepted edge); and **then**
>   `termios.tcsetattr(TCSADRAIN)`-restore the saved attributes. The leading
>   `CAN` is paired with a `ST` (`ESC\`) so a partial **OSC/DCS string** state
>   (which `CAN` alone does not always terminate) is also closed before the mode
>   resets. A wedged shell is unacceptable; the fixed blast plus `termios`
>   restore is the contract, and S2's fake harness enables these modes so the
>   restore is proven at the **byte level** (the reset sequence is emitted on
>   every exit path — a raw PTY has no emulator to assert a *visual* restore
>   against). (The harness's alt-screen content is ephemeral and not in the
>   user's scrollback after detach — expected, not a bug.)
>
> - **Detach-chord matcher (across reads, raw mode).** The bridge reads the
>   human's tty in raw mode (`tty.setraw`), which **disables `ISIG`** — so
>   `Ctrl-\` arrives as the byte `0x1c` rather than raising `SIGQUIT`, which is
>   exactly why a `Ctrl-\`-based chord is readable. The default `Ctrl-\ Ctrl-\`
>   is a two-byte sequence that can **split across `read()` calls**, so the
>   matcher is a small byte-at-a-time state machine: on the first chord byte,
>   hold it (do not forward yet); if the next byte completes the chord, detach;
>   if it does not, forward the *buffered* byte(s) then the current byte, so a
>   partial match never swallows or drops input. The matcher only ever inspects
>   the configured non-`ESC` chord bytes; `ESC`-prefixed input (Escape/arrows/
>   function keys) is forwarded verbatim and never enters the state machine.
>
> `--attach` forces the bridge (errors if no tty or if nested in a host TUI);
> `--detach` forces detached mode even when not wired; a stale/incorrect wired
> flag is recovered by `taut summon --attach` (re-onboard) or clearing it.
> **Attach is first-generation only** — a post-crash resume ([SUM-11]) re-enters
> `spawn` but must **not** re-grab the terminal into raw mode; the attach gate is
> `first_generation AND not wired AND tty AND not nested`, mirroring the existing
> `first_generation` guard in `_supervise`. During attach the driver starts
> **no** event pump and **no** watcher (they would fight the bridge for the
> single master fd and break single-consumer `events()`); pump + watcher start
> only after detach.
>
> **STOP / shutdown during attach.** The attach bridge runs on the supervise
> thread *before* it reaches the normal `_await_wake()` shutdown park, and no
> event pump/reader runs during attach — so a control-plane STOP (or `dismiss`)
> that sets the shutdown flag would otherwise have **no consumer until the human
> detaches**, violating control-responsiveness ([SUM-9]). The bridge therefore
> **selects over three sources** — `[human_tty, master, shutdown_waker]` — not
> two blocking reader threads (a tty→master thread would block on human input
> forever). `shutdown_waker` is a **bridge-owned pipe** written by a small
> **bridge-local forwarder thread**. The forwarder must unblock on **both** exit
> paths — a STOP *and* an ordinary chord-detach (the common case, where
> `self._wake` never fires) — so it does **not** do a single unbounded
> `self._wake.wait()` (that deadlocks the join on every normal detach). Instead
> it loops on `self._wake.wait(timeout=…)` with a **small finite timeout** (so
> `done` is observed within one tick on a normal detach), and on each tick also
> checks a **bridge-local `done` Event** the bridge sets in its `finally`; it
> writes the pipe and exits when **either** `self._wake` or `done` is set. The
> teardown order is fixed: **`done.set()` → join the forwarder → close the pipe
> fds** (never close the pipe before the join, or the forwarder's write races a
> closed fd); the forwarder's pipe write **swallows `BrokenPipeError`/`OSError`**
> (the reader end may already be gone on a torn-down select). This keeps the fix
> **within the four named
> touchpoints** — `request_stop`, `__init__`, and the shutdown ordering are
> **not** edited (they already set `self._wake`), preserving the "shutdown
> unchanged" invariant and the four-touchpoint stop-gate. (Disambiguation is by
> re-checking `self._shutdown.is_set()` after the select wakes, not by which fd
> woke — during attach nothing else sets `self._wake`.) On a shutdown wake the
> driver takes an **explicit post-attach branch**: *if attach returned because
> `self._shutdown` is set, do not start the pump or watcher, do not hand the
> master to the driver reader, and go straight to ordered shutdown.*
> `interrupt()`/`close()` must tolerate an **already-closed master** on this path
> (guard the fd). **Master fd ownership — one rule across every path, never a
> zero-closer window.** The master fd is closed by an idempotent internal
> `close_master()` (lock + `_master_closed` flag), but the **only public rule an
> implementer needs is on `close()`**: `close()` always signals+reaps the child
> (`\x03`→SIGTERM→SIGKILL then `waitpid`), and **also closes the master iff no
> reader has started** (a `_reader_started` flag). If a reader *has* started,
> `close()` does **not** close the master — the reader closes it on EOF/EIO, so
> there is no use-after-close race (the `_stream.py` discipline). This single
> rule covers every path because the driver already calls `handle.close()` on a
> spawn-time failure, and v8 extends that to the **whole `spawn → pump-started`
> span** (see the ordering below): any exception in `rejoin` / attach /
> `set_wired` / `ensure_threads` — **on the detached path as well as the attached
> one** — runs `handle.close()`, which (reader not yet started) both **reaps the
> child (no zombie)** and closes the master (no leak). So the closers are: the
> **reader** on EOF/EIO (normal run); **`close()` via the driver's spawn-span
> guard** on any pre-reader failure (detached *or* attached); and the **bridge
> `finally`** on STOP-during-attach (also a `handle.close()`, reader-never-ran).
> **Exactly one** effective close on every path, **never zero**, and
> `close_master()` is never invoked while a reader is blocked in `read()`.
> (The round-6 P1 was a naive `handed_off`/`close_master()` split that guarded
> only the attach window and closed the fd without reaping; this rule closes the
> detached pre-pump path too and always reaps — round-7 P1s.) The **single**
> marker is **`_reader_started`** (there is no separate `handed_off` flag —
> unify to one name): the reader sets it **as its first action under the
> lifecycle lock**, before its first `read()`, and `close()` reads it under the
> same lock. Two consequences: (1) the spawn-span guard is universal and additive
> (calling `close()` to reap on a failed spawn is correct for every adapter), so
> structured adapters (`claude-stream`, `scripted`) are unaffected — it does not
> add a capability-gated touchpoint, only hardens the existing spawn-failure path
> — **and the guard re-raises after `close()`** (as the existing `rejoin` pattern
> does) so exit-1 propagation is preserved; (2) a **close-before-first-read**
> race (the fast `watch()`/`pump.start()` failure window where `close()` may find
> `_reader_started` False and close the master just before the reader's first
> `os.read`) is handled by the lock (the reader checks `_master_closed` under the
> lock before its first read) **and** by treating **any `OSError` on the master
> read — not only `EIO` — as end-of-stream** (so an `EBADF` from a just-closed fd
> yields the normal single `ExitEvent`, never an escape).
>
> **Startup ordering (pins the attach-vs-`rejoin` question).** Per generation:
> **`spawn` → `rejoin` (anchor the member to the child, [SUM-4]; the member is
> now *present*) → `ensure_threads` (join all threads, matching the existing
> `_supervise` order) → [first-run only: attach bridge → human onboards → detach →
> `set_wired(True)`] → `pump.start()` (reader now owns the master;
> `_reader_started=True`) → settle → `inject(orientation)` → start watcher.**
> `rejoin` + `ensure_threads` are **before** attach, so "the member is
> present/anchored/joined during attach" holds without contradiction (including
> re-summons that add threads); `set_wired` is after detach; the master is
> reader-unowned for the entire `spawn → pump.start()` window, which is exactly
> the span the `close()`-on-failure guard covers.
>
> **Reader ownership (single master consumer).** Exactly one owner reads the
> master at a time: the **attach bridge** during attach, then the **driver's
> reader** (query-responder + liveness + `events()`) after detach — an explicit
> hand-off, never concurrent. `events()` has one consumer. `close()` signals
> the child (`\x03`→SIGTERM→SIGKILL to its session) and reaps it; it closes the
> master **only when no reader has started** (`_reader_started` flag) — in normal
> operation a reader *is* running, so `close()` leaves the fd for the reader to
> close after it observes EOF, and there is no use-after-close race (the
> `_stream.py` discipline). The only time `close()` closes the master itself is a
> pre-reader failure/shutdown (the spawn-span guard or STOP-during-attach), where
> no reader is blocked on the fd. **Platform split:** on Linux a read of the master after the child
> exits raises `OSError(EIO)`; on darwin (this dev box) it returns `b""` (EOF).
> The reader treats **both** EOF and EIO as end-of-stream and emits **exactly
> one** `ExitEvent`, guarded by a lock+flag. Because darwin yields EOF, the fake
> harness locally exercises the **EOF** branch; the **EIO** branch is asserted on
> Linux CI (and, where practical, by a unit that stubs the read to raise
> `OSError(EIO)` — this stubs the OS error, not the broker/CLI, so it stays
> within the anti-mocking rule).
>
> Chat that arrives during attach is not injected — the member is joined
> (present, anchored to the child) but accumulates unread; after detach the
> driver injects orientation and the watcher replays from the cursor.
>
> **Ears.** In driver mode, `inject(text)` writes to the master. The payload is
> **canonicalized then sanitized**, in this order — the newline is *preserved*
> through sanitization because later steps need it (LF is a C0 byte, so a
> blanket "strip all C0" would destroy multi-line handling; that is the round-3
> contradiction this fixes):
> 1. **Canonicalize newlines** — convert CRLF and lone CR to a single `LF`.
> 2. **Sanitize** — strip `ESC`, `DEL` (`0x7f`), and all C0 control bytes
>    **except `LF`**; convert `TAB` to a single space. (`DEL` is outside the
>    C0 range 0x00–0x1F, so "strip C0" alone would let it through as a
>    destructive keystroke; strip it explicitly. C1 controls are a non-issue: a
>    Python `str` encoded UTF-8 never emits standalone `0x80–0x9F` bytes.)
>    Because `ESC` is fully removed, any embedded `ESC[200~`/`ESC[201~` a hostile
>    message carries cannot survive — the paste terminator is gone, and only
>    `LF` remains as structure. The sanitized text therefore contains `LF` (and
>    no other control bytes).
> 3. **Frame for submission.** If the harness has **enabled bracketed paste**
>    (observed `ESC[?2004h` in its output), wrap the sanitized text —
>    `LF`-preserving — as `ESC[200~`…`ESC[201~` and append `\r`. **Otherwise
>    (line mode)**, collapse the remaining `LF`s to single spaces so a multi-line
>    chat message submits as exactly one turn (never fragment turns), then append
>    `\r`.
>
> Injectors are serialized (inject-lock, as `_stream.py`);
> `interrupt()`/`close` unblock a blocked inject.
>
> **Settle (driver mode, before the first chat inject only).** The single master
> reader (the pump) owns the fd, so settle must **not** read the master itself —
> it **polls a `last_output_ts` the reader publishes** and waits until output has
> been quiet for `quiet_ms` (default 500 ms) **or** `max_settle_s` (default 10 s)
> elapses, whichever first, then injects orientation. This bounds the first
> inject against startup churn; it is **not** a readiness/detach signal (that is
> the wired flag above) and never blocks — an animating harness is injected into
> at `max_settle_s`. Settle's quiet window **cannot distinguish "quiet because
> ready" from "quiet because blocked on an unrecognized query"** (that would need
> the forbidden screen parsing); in the latter case orientation is injected into
> a wedged harness and lost, and the `awaiting_query` diagnostic then fires at
> `stall_s` and the human resolves it with `--attach`. The end state is still
> correct and surfaced — this is an inherent, bounded cost of not parsing the
> screen, only reachable in the already-degraded unrecognized-query case.
>
> **Orientation is turn zero — a new, explicit driver step, gated by
> capability.** The driver has no existing orient step; PTY adds one. The exact
> ordering after spawn (and, first-run, after detach) is: **start the pump**
> (the single master reader — it owns the fd and publishes `last_output_ts`) →
> **settle** (poll that timestamp per above) → **`handle.inject(orientation)`
> under the inject-lock** → **start the watcher thread**. So orientation is
> injected after the reader is live (settle needs its timestamp) but strictly
> **before the watcher** replays any chat — that sequencing is what guarantees
> orientation is turn zero. The inject step is gated by an
> **`orientation_via_inject`** adapter capability (True on PTY, False on
> `claude-stream`, which receives the persona as a spawn-time `system_prompt`
> per [SUM-10]) so a structured adapter is not double-oriented. Orientation
> carries the member name and threads, the injection format, the mouth contract
> (`taut say`; `TAUT_TOKEN`/`TAUT_DB` are set), and the interrupt/silence/loop
> policy. Re-injected on every fresh spawn (including resume); harness specs pass
> flags that disable each CLI's own auto-resume so re-orientation starts a clean
> turn.
>
> **Output is never parsed as speech.** The driver reads the master only for
> coarse liveness ([SUM-7.1]), the query-responder, and the log. The mouth is
> `taut say`. Terminal mode is unsupported here ([SUM-6]).
>
> **Interrupt / shutdown.** `interrupt()` writes `\x03` — handled by the
> harness's raw-mode key reader as cancel (kernel job-control SIGINT is not
> assumed; a live interrupt proof is required, §7 S4). Shutdown is
> `\x03`→SIGTERM→SIGKILL per the reader-ownership rules above.
>
> **Detached stall (no chat relay).** A not-yet-wired harness summoned detached
> may sit at its own prompt. Summon does **not** attempt a chat relay — there is
> no reliable "no progress" signal for a mouth-only agent (success is `taut
> say`, not screen output), and no guaranteed recipient under cron/pipe. The
> child stays alive; the condition is a driver-log line and a STATUS field
> (`awaiting_onboarding`), and the resolution is `taut summon --attach <name>`.
>
> **Session continuity** follows [SUM-7.3]: no structured resume; a fresh
> interactive session plus cursor replay recovers the conversation.

### Amend [SUM-8] — the `wired` flag is a versioned ledger schema change

> The per-(member, provider) **wired** flag ([SUM-7.4]) is durable state and
> therefore a first-class ledger schema change, not an ad-hoc field. The current
> ledger is guarded by a **fail-closed version gate**: `ensure_summon_schema`
> installs the tables via `CREATE TABLE IF NOT EXISTS` and rejects any database
> whose stored `summon_schema_version` differs from `SUMMON_SCHEMA_VERSION`
> (a lower version raises "recreate the development database"; there is **no**
> `ALTER TABLE` path). Adding `wired` requires all of:
> 1. **Bump `SUMMON_SCHEMA_VERSION` 1 → 2.** An existing v1 database then trips
>    the fail-closed gate and must be recreated. That is acceptable and is the
>    migration: the extension is uncommitted (§6b), so no production data exists,
>    and recreate-on-version-mismatch is the ledger's designed migration story.
>    (No `ALTER` is added — the recreate path applies the new DDL cleanly.)
> 2. **Add the column** to the `taut_summon_sessions` DDL:
>    `wired INTEGER NOT NULL DEFAULT 0` (SQLite boolean; keyed by the existing
>    `member_id` PK, but semantically per (member, provider) since a member row
>    already carries its `provider`). `wired` **cannot** be derived from an
>    existing column — a PTY session's `provider_session_id` is always `None`, so
>    it carries no onboarding signal.
> 3. **Extend the typed row + the exact column sites (named precisely — a wrong
>    list here silently clobbers `wired`).** Add `wired: bool` to
>    `SummonSessionRow`. The load-bearing sites in `_state.py` are: the shared
>    **`_SESSION_SELECT`** constant (feeds `get_session`, `update_session`,
>    `claim_driver`, `release_driver`) — add `wired` to its column list; the
>    **inline `SELECT` in `list_sessions`** (a *separate* list, not
>    `_SESSION_SELECT`) — add `wired`; the **`INSERT` in `record_session`** — add
>    `wired` with default `0`; and **`_session_row`** (the tuple→dict mapper) —
>    map the new column, converting `0/1`→`bool`. **`claim_driver` and
>    `release_driver` MUST NOT gain a `wired` write** — they issue targeted
>    UPDATEs of `driver_pid`/`driver_start_time`/`updated_ts` only, and
>    `claim_driver` runs on **every re-summon** (`_bootstrap`), so writing `wired`
>    there (even with a default) would reset it to `0` on every reconnect and
>    defeat persistence. Likewise `record_session`'s **UPDATE branch** must
>    **preserve, not overwrite** `wired`. The read side is automatic once
>    `_SESSION_SELECT`/`list_sessions`/`_session_row` carry the column.
> 4. **Add helpers** `get_wired(queue, member_id) -> bool` and
>    `set_wired(queue, member_id, value)` (a scoped UPDATE of `wired`
>    + `updated_ts` only, mirroring the `update_session`/`claim_driver` shape),
>    used by the driver's attach step (read to decide attach vs straight-to-
>    detached) and detach (set True). These are the **only** `wired` writers.
> 5. **Test old-schema behavior:** a v1 database raises
>    `SummonSchemaVersionError` on open (the fail-closed gate still fires); a
>    fresh v2 database round-trips `wired` false→true; and — the regression this
>    prevents — a `set_wired(...True)` followed by a `claim_driver` re-summon
>    leaves `wired` **still True**. These land in S1 (schema) so the flag's
>    storage exists before S4 consumes it.

### Amend [SUM-10] — append:

> For the PTY adapter, orientation is delivered as the first injected message
> ([SUM-7.4]), not a spawn-time system-prompt flag; `--system-prompt-file`
> overrides the orientation text either way.

### Amend [SUM-12] conformance — add:

> - **Deterministic PTY lifecycle** is proven against a **fake interactive
>   harness** (a real subprocess over a real PTY that models a TUI: alternate
>   screen, terminal-query emission, continuous redraw, delayed readiness,
>   optional bracketed-paste support, an optional onboarding prompt) — not a
>   mocked PTY. This is the anti-mocking seam for [SUM-7.4].
> - **Live harness reachability** — for each registered PTY harness, a
>   `requires_<name>` test summons the real CLI (detached, assuming a
>   pre-onboarded/authed harness), orients it to post a sentinel via `taut say`,
>   and asserts the sentinel lands. The **only** skip gate is "binary absent or
>   the harness does not reach a ready prompt"; once it is up, a missing
>   sentinel is a **failure**, not an environment skip.

## 5. Context and Key Files

- **Adapter contract** — `_adapter.py`: `ProviderAdapter`/`AdapterHandle`, the
  `AdapterEvent` union, the registry. The PTY adapter implements this and adds a
  `supports_terminal_mode` capability (default True on existing adapters; False
  on PTY). **Comprehension check:** confirm `_driver.py._pump` handles a stream
  that only ever yields `activity`/`exit` (it does — verify per event branch),
  and that `whoami()` activity is already rate-limited (≈10 s) so a coarse
  activity policy is enough.
- **Driver** — `_driver.py`: **four** scoped, capability-gated touchpoints (not
  one — the v1/v2 "ONE change" claim is retracted; see §6): (a) the
  `supports_terminal_mode` check before it computes `terminal_thread`; (b) the
  first-generation attach step between spawn and starting pump/watcher; (c) a
  **new** orientation-inject step — the driver has **no** existing
  orient-before-watcher step today (verified: `_supervise` runs
  spawn → rejoin → ensure_threads → pump.start → watcher.start, with no orient
  in between), so PTY adds one (start pump → settle → inject orientation →
  start watcher); (d) reading/writing the `wired` ledger flag around the attach
  decision. Everything else (spawn via `spawn(...)`, `_pump`, resume, shutdown)
  is unchanged. **Stop gate:** any driver control-flow edit **beyond these four
  named touchpoints** is a stop-and-re-evaluate signal.
- **Streaming handle mechanics** — `_stream.py`: the inject-lock / lifecycle-
  lock / single-consumer-events / exactly-one-exit / thread-safe interrupt-close
  discipline. The PTY handle needs the **same guarantees** over a master fd;
  reuse the pattern, not the stream-json parsing.
- **Scripted seam** — `_scripted.py` + `scripted_provider.py`: the model for the
  new fake **interactive** harness (§7 S2).
- **Existing claude adapter** — `_claude.py` → re-register as `claude-stream`.
- **Persona/orientation** — `_persona.py`: reframe to opening-briefing voice.
- **CLI** — `cli.py`: `run`/`summon` gains attach-vs-`--detach`; provider
  resolution maps names → PTY specs.

## 6. Invariants and Constraints

- **Frozen core.** No `taut/` change. Extension imports only public
  `simplebroker`/`simplebroker.ext`/`taut` + stdlib. **No new third-party dep.**
- **Scoped driver changes (four, all named and bounded — the v1/v2
  under-counts are retracted, review P1s):** (a) `supports_terminal_mode`
  capability check before `terminal_thread`; (b) a `supports_attach` +
  first-generation + not-wired + tty gated **attach step** between spawn and
  starting pump/watcher, during which pump and watcher do **not** start;
  (c) a new **orientation-inject step** — `handle.inject(orientation)` under
  the inject-lock after spawn/detach and before the watcher (the driver has no
  such step today; PTY needs it); (d) reading/writing the **wired** ledger flag
  around the attach decision. These four are the whole driver surface; a fifth
  touchpoint is a stop-and-re-evaluate signal. All four are additive branches
  guarded by adapter capability, so structured adapters (`claude-stream`,
  `scripted`) are unaffected.
- **Wired flag** is per (member, provider) in the summon ledger; set on a
  successful first-run attach-then-detach; read to decide attach vs. straight-
  to-detached. Never auto-detach on a not-yet-wired first run. It is a
  **versioned schema change**: bump `SUMMON_SCHEMA_VERSION` 1→2, add the
  `wired INTEGER NOT NULL DEFAULT 0` column, extend `SummonSessionRow` and the
  **exact** sites — `_SESSION_SELECT`, the inline `SELECT` in `list_sessions`,
  the `INSERT` in `record_session`, `_session_row` — plus `get_wired`/`set_wired`
  as the **only** `wired` writers; `claim_driver`/`release_driver` get **no**
  `wired` write (they run on every re-summon and would clobber it). An old v1 DB
  trips the fail-closed gate and is recreated (the ledger's designed migration;
  uncommitted extension, no prod data). See the [SUM-8] amend in §4.
- **Presence is anchored to the child process** ([SUM-4]), not output bytes.
  PTY `activity` is coarse lifecycle liveness only.
- **Orientation before any chat**, guaranteed by sequencing (inject under lock
  before the watcher starts), idempotent per spawn; auto-resume disabled per
  harness spec.
- **Never parse the TUI as speech.** Reading the master = liveness + log +
  query-responder + attach bridge only.
- **Injection safety**: canonicalize CRLF/CR→LF; then strip `ESC`, `DEL`
  (`0x7f`), and all C0 **except `LF`** (TAB→space) — removing `ESC` also kills
  any embedded paste terminator, and `LF` is preserved because the framing step
  needs it; then
  frame with bracketed paste (LF-preserving) only when the harness enabled it,
  else collapse `LF`→spaces for a single-turn line submit. Bounded settle
  (polling the reader's `last_output_ts`, not reading the master), serialized
  injectors, interrupt/close unblock a blocked inject.
- **Startup ordering**: `spawn → rejoin (anchor/present, [SUM-4]) →
  ensure_threads → [first-run: attach → detach → set_wired] → pump.start (reader
  owns master) → settle → inject orientation → watcher`. `rejoin` +
  `ensure_threads` are **before** attach (so the member is present and joined to
  all threads during attach, including re-summons that add threads); the master
  is reader-unowned across the whole `spawn → pump.start()` window.
- **Master fd close — one rule, exactly one closer, never zero.** `close()`
  signals+reaps the child (`\x03`→SIGTERM→SIGKILL then `waitpid`) **and** closes
  the master **iff no reader has started** (`_reader_started` flag); if a reader
  started, `close()` leaves the fd for the reader to close on EOF/EIO (the
  `_stream.py` discipline, no use-after-close). The driver calls `handle.close()`
  on **any** exception in the `spawn → pump-started` span (extending the existing
  `rejoin`-failure close to `attach`/`set_wired`/`ensure_threads`), so a pre-pump
  failure on **detached or attached** paths both reaps (no zombie) and closes the
  master (no leak). Closers: reader on EOF/EIO; `close()` via the spawn-span
  guard on any pre-reader failure; bridge `finally` (also `handle.close()`) on
  STOP-during-attach. The spawn-span guard is **universal and additive** (reaping
  a failed spawn is correct for every adapter), so it does not add a
  capability-gated touchpoint and structured adapters are unaffected.
- **Attach lifecycle**: gated `first_generation AND not-wired AND tty AND
  not-nested`; no pump/watcher during attach; single master-reader owner with an
  explicit attach→driver hand-off (the reader sets `_reader_started` under the
  lifecycle lock only after the pump owns the fd — the one marker; no separate
  `handed_off`). **STOP-during-attach**: the bridge `select`s over
  `[human_tty, master, shutdown_waker]` — where `shutdown_waker` is a
  bridge-owned pipe fed by a bridge-local forwarder that waits on the **existing**
  `self._wake` Event **or** a bridge-local `done` Event (so it unblocks on a
  normal chord-detach too, not only on STOP, and `request_stop`/`__init__`/
  shutdown stay unedited — no fifth touchpoint) — so a control STOP is consumed
  while attached ([SUM-9]); on that path the driver takes an explicit branch (no
  pump/watcher, no hand-off) and restores the tty before returning.
- **Attach is two TUIs on one terminal**: a configurable **non-`ESC`** detach
  chord matched by a **byte-at-a-time state machine** across reads (buffer the
  first chord byte, forward it if the match fails; `tty.setraw` disables `ISIG`
  so `Ctrl-\` is a readable byte, not `SIGQUIT`); never intercept `ESC`-prefixed
  input; **refuse attach when the cooperative `TAUT_HOST_TUI` marker is set**
  (nested in a single-terminal host TUI — arbitrary non-cooperating host TUIs are
  best-effort/unsupported; compose with tmux panes; a host TUI shells out and
  sets the marker); on detach write a **fixed idempotent reset blast**
  (`CAN`+`ST` first, then alt-screen variants, cursor, scroll region, **SGR
  reset `ESC[0m`**, autowrap, synchronized-output off, alt-scroll off,
  DECCKM/keypad, focus, all mouse variants, bracketed-paste, kitty pop) **then**
  `tcsetattr` — in a `finally` on every exit path (not "modes it saw enable");
  proven at the byte level by S2.
- **Threaded-safe spawn**: `start_new_session=True`; never `preexec_fn`/
  `pty.fork()`.
- **PTY fd lifecycle explicit**: parent closes slave post-Popen; reader owns the
  master; reader ends on EOF or close flag; exactly one `ExitEvent`.
- **Onboarding/trust is a human decision** via attach — never auto-bypassed.
- **Live tests**: skip only on absent/won't-start; a ready harness that fails
  the sentinel is a failure, not a skip.

## 6a. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## 6b. Spec Baseline

- The uncommitted summon extension at this session's head (Phases A–E + the
  control-message-reaping and `_cursor_lag` fixes), on `2026-07-06-taut-summon-
  plan.md`. Diff-base + worktree state (uncommitted, pending the user's review).

## 7. Tasks (dependency-ordered slices)

Independent adversarial review after **S4b** (adapter core + attach bridge) and
again at completion.

**S1 — Structural spec promotion + capabilities + wired ledger schema.** Land
the reconciled §4 delta **except** the [SUM-7.2] "`pty` is the default host for
`claude`" line — promote [SUM-1]/[SUM-2]/[SUM-6]/[SUM-7.1]/[SUM-7.4]/[SUM-8
amend]/[SUM-10]/[SUM-12] and the `claude-stream` alias. Add three adapter
capabilities: `supports_terminal_mode` (True on existing structured adapters,
False on PTY), `supports_attach` (PTY only), and `orientation_via_inject` (True
on PTY, False on structured adapters that get the persona as a spawn
`system_prompt`). Driver: the `supports_terminal_mode` check before
`terminal_thread`, with a test that a False-capability adapter disables terminal
mode with a warning. **Wired ledger schema ([SUM-8] amend):** bump
`SUMMON_SCHEMA_VERSION` 1→2; add `wired INTEGER NOT NULL DEFAULT 0` to the
`taut_summon_sessions` DDL; extend `SummonSessionRow` (`wired: bool`) and the
**exact** column sites — `_SESSION_SELECT`, the inline `SELECT` in
`list_sessions`, the `INSERT` in `record_session`, `_session_row` — add
`get_wired`/`set_wired` as the only `wired` writers, and leave
`claim_driver`/`release_driver` writes untouched (they run on every re-summon
and must not clobber `wired`). Tests: a v1 DB raises `SummonSchemaVersionError`
(fail-closed gate still fires); a fresh v2 DB round-trips `wired` false→true;
and `set_wired(True)` survives a subsequent `claim_driver` re-summon (the
clobber regression). The flag's storage lands here so S4 can consume
it. **Do not flip `claude` to PTY here** — the PtyAdapter does not exist yet, so
the spec's "pty default" claim and the registry map land **together in S5** to
avoid a code-contradicts-spec window (review P1: S1/S5 inconsistency). S1 keeps
`claude`→stream, reachable also as `claude-stream`. Docs gate green.

**S2 — Fake interactive harness (test seam).** `tests/fixtures/fake_tui.py`: a
real Python program over its PTY, **parametrized by a query profile** (so a test
can drive the exact startup-query set of any registered harness — the seam for
the per-harness detached-responder validation in §4/S6). It emits the startup
queries, including **both** size-probe variants — the absolute park
(`ESC[999;999H` then `ESC[6n`) **and** the relative walk (`ESC[9999C` `ESC[9999B`
then `ESC[6n`), each asserting the reply is the clamped winsize, never
`999;999R`/`9999…R` or `1;1R` — a DECRQM bracketed-paste query, and (for the
diagnostic test) an **unclassifiable blocking query**. It enters the alternate
screen and **enables the full mode set the restore must clear** (alt-screen,
mouse variants, bracketed-paste, kitty keyboard, application-cursor-keys/keypad,
focus tracking, SGR color, synchronized-output) so the fixed reset blast is
proven **at the byte level** (a raw PTY has no emulator for a *visual* assert —
the test checks the reset sequence was emitted on every exit path), redraws
continuously, becomes ready after a delay, optionally shows an onboarding prompt
that stays quiet until answered, reads typed/pasted lines, **records the raw
bytes it receives** (so tests can assert `ESC`-passthrough, paste framing, and
that an unclassifiable query gets **no** reply), runs a directive line as a shell
command (so tests can make it `taut say`), and handles `\x03`/SIGTERM (and, where
the platform allows, closes to exercise EOF; the EIO branch is Linux-CI/stubbed
per §4). The deterministic anti-mocking seam.

**S3 — Terminal-query responder + PTY I/O core.** The reader over the master:
answers the recognized query families with **cursor clamping** (absolute +
relative moves) and **replies to nothing it cannot classify** (§[SUM-7.4]);
classifies "report-shaped" via the **conservative predicate** (report-request
families in; draw/control sequences out) and, when an unclassified report-shaped
query is outstanding **with no output progress for `stall_s`** (the single-shot
hang, not repeat-only), raises the bounded **`awaiting_query` stall diagnostic**
(introduced here: log line naming the raw sequence + STATUS field; report-only,
resolved by `--attach`). The reader uses a **timed `select`/poll, never a
permanently blocking `read`**, so `last_output_ts` freezes while a harness blocks
on a reply and the `stall_s` timer fires. It yields `ActivityEvent` coarsely (on
inject / burst after idle); publishes `last_output_ts` for settle; yields exactly
one `ExitEvent` on EOF/close; fd lifecycle where **`close()` reaps the child and
closes the master iff no reader started** (`_reader_started` flag; else the
reader closes on EOF, per `_stream.py`), the fd-close itself idempotent (lock +
`_master_closed`). Also add the STATUS transport:
the handle's **`status_fields() -> dict[str, str]`** merged by `ControlLoop` into
the `_status_fields()` `as_fields()` output (JSON primitives only; escaped-string
value, never `bytes`; no key collision with existing snapshot/envelope keys).
Tests
(fake harness, parametrized by query profile): each recognized family is answered
(fake harness proceeds only if answered); the clamped reply for both size-probe
variants; a **single** unclassifiable **blocking** query with no progress trips
`awaiting_query` within `stall_s` (the single-shot case) and is **left
unanswered** (no fabricated reply); a redrawing TUI does **not** trip it
(predicate excludes draw sequences); a real `STATUS` request surfaces
`awaiting_query`; coarse activity (idle redraw does not spam activity);
exactly-one-exit under close-vs-events race; reader EOF on child death.

**S4 — `PtyAdapter`/`PtyHandle` + inject + the driver touchpoints, DETACHED
MODE ONLY (P1 review target).** This slice lands **detached-mode summon** —
fully functional on its own for a **wired** (or `--detach`-forced) member; the
attach bridge and everything gated on it are **S4b**, so S4 alone never enters
the bridge path. `_pty.py`: `spawn` (openpty + Popen + start_new_session + TERM
+ winsize) → `PtyHandle`. `inject` (settle-via-reader-timestamp,
canonicalize+sanitize per §4, conditional bracketed paste vs newline-collapse
line mode, inject-lock); `interrupt` (`\x03`); `close`
(`\x03`→SIGTERM→SIGKILL then `waitpid`-reap, **and close the master iff no reader
started** — else the reader closes it on EOF); the driver wraps the
`spawn → pump-started` span so any pre-pump exception (`rejoin`/`ensure_threads`)
calls `handle.close()` (reaps + closes master; the detached zero-closer fix);
`session_id=None`; `supports_terminal_mode=False`; `orientation_via_inject=True`.
(Declare
`supports_attach=True` here so registry/capability shape is complete, but the
**attach gate, the `wired` set-on-detach, the `--attach` force path, and the
first-run-tty branch are S4b** — in S4 the driver treats every summon as
detached: it reads `wired` but, with no bridge yet, a not-yet-wired tty member
runs detached and **S4 introduces the `awaiting_onboarding` STATUS field** it
stalls with, rather than attaching.)
The single master reader (query-responder with **cursor clamping** incl.
relative moves, the `awaiting_query` stall diagnostic, coarse activity, EOF/EIO
both → exactly-one-exit, `last_output_ts` published for settle). The driver
touchpoints active in S4: capability check; the **new** orientation-inject step
(start pump → settle → inject → start watcher); the wired **read**. `cli.py`:
`--detach` override; register `pty`. Tests (fake harness, real PTY, detached):
the absolute **and relative** cursor size-probes each get the **clamped
winsize** reply (never `999;999R`/`1;1R`); an **unclassifiable blocking query
raises the `awaiting_query` diagnostic** (not a silent hang) and a classifiable
one is answered; orientation is injected **before any chat**; multi-line inject
is one turn in both paste and line-collapse modes; a hostile `ESC[201~`/`DEL` in
chat is neutralized and LF survives to the framer; a post-crash resume does
**not** re-grab the tty (first-gen guard); interrupt cancels a running
directive; close reaps the child (no zombie) and does not use-after-close the
master; **a detached `rejoin`/`ensure_threads` exception before pump start leaks
no master fd and leaves no zombie** (the driver's spawn-span `handle.close()`
guard — the round-7 detached zero-closer); EOF yields exactly one exit (EIO
branch per §4). **Stop gate:** any *capability-gated* driver edit beyond the four
named touchpoints → stop and re-evaluate (the universal spawn-span close guard is
additive, not a fifth capability touchpoint).

**S4b — Attach bridge + the attach gate (its own reviewable slice).** The
raw-mode tty↔master bridge plus everything gated on it is a coherent partial
result, split out per CLAUDE.md's "meaningful slice" guidance. This slice adds
the two attach-only driver touchpoints S4 deferred: the **attach step** (gate
`first_generation AND not-wired AND tty AND not-nested`; no pump/watcher during
attach) and the **wired write**. `_pty.py` (or `_attach.py`): a `select` loop
over `[human_tty, master, shutdown_waker]` (never two blocking reader threads),
where `shutdown_waker` is a **bridge-owned pipe fed by a bridge-local forwarder**
that loops on `self._wake.wait(timeout)` **and** checks a **bridge-local `done`
Event** set in the bridge's `finally` (so it unblocks on STOP *and* normal
detach; `request_stop`/`__init__`/shutdown are **not** edited — the
four-touchpoint stop-gate holds); teardown order **`done.set()` → join → close
pipe fds**, forwarder write swallows `BrokenPipeError`/`OSError`; the
**byte-at-a-time non-`ESC` detach-chord matcher** (buffer/forward on partial
match; `tty.setraw` disables `ISIG`); the **cooperative `TAUT_HOST_TUI` nesting
guard** (refuse + detached fallback message; compose with tmux panes); the
**fixed reset-blast + `tcsetattr` restore** in a `finally` on every exit path
(`CAN`+`ST` first, then SGR reset and the enumerated DEC private-mode resets);
**STOP-during-attach** handling (shutdown wake exits the loop, restores the tty,
`handle.close()` since no hand-off occurred — reaps the child *and* closes the
master, reader-never-ran; driver takes the explicit post-attach branch: no
pump/watcher, no hand-off); **atomic master hand-off** — the reader sets
`_reader_started` (the single marker) under the lifecycle lock only after the
pump owns the fd, and the driver guards the whole `spawn → pump-started` span so
an `attach`/`set_wired`/`ensure_threads` exception calls `handle.close()`
(**reaps + closes the master** — no zero-closer
leak, no zombie); the **`--attach` force path**; and the **wired** ledger flag
set True on detach (`set_wired`). Tests
(fake harness, real PTY): attach bridges both ways and detaches on the chord
(chord **split across reads** still detaches), setting wired; **`ESC`-prefixed
input (arrows/Escape) passes through and never triggers detach**; a
**not-yet-wired first run stays attached until the explicit detach chord even
after the harness goes quiet** (the real v3 behavior — replaces the hollow
"does-not-auto-detach" test, since auto-detach no longer exists); a **STOP during
attach** tears the bridge down, restores the tty, closes the master once, and
reaps the child (no zombie, no leaked/double-closed master fd); **an exception
raised in the hand-off window** (after detach, before the pump owns the fd)
leaves **no leaked master fd and no zombie** (the round-6 zero-closer test);
attach is **refused when `TAUT_HOST_TUI` is set** and falls back to detached with
a message; a wired member goes straight to detached mode; **the local tty is
fully restored** (byte-level: the fixed blast + termios are emitted) even when
the bridge raises mid-way.

**S5 — Harness registry + resolution + the `claude`→PTY flip.** Register the
eight → `PtyAdapter(spec)` with correct interactive `argv` (`coder` not `code`;
grok→`grok`, etc.) and per-harness quirks (auto-resume-disable flags,
bracketed-paste expectation). **Atomically** land the [SUM-7.2] "`pty` is the
default host for `claude`" text (deferred from S1) together with the registry
map that makes `claude`→PtyAdapter and `claude-stream`→the stream adapter — no
spec/code window (review P1). The STATUS fields already exist by S5
(`awaiting_query` from S3, `awaiting_onboarding` from S4); S5 only wires them per
provider. Each harness spec carries its **expected
detached-mode startup query set** (codex's is empirically captured, §3; the
other seven are filled from the S6 live-capture and asserted). `[SUM-3]`
resolution maps a name to its spec; `--provider` overrides. Unit tests: each
name → its binary (**grok→grok**, coder→coder, never `code`; `claude`→pty,
`claude-stream`→stream); unknown → error naming known providers.

**S6 — Live conformance (usability-gated).** `tests/test_live_harness.py`,
marked, skipped in CI: per harness, gate on "binary present AND reaches a ready
prompt within a bound" (else skip-with-reason); then — assuming the harness is
already **wired** (pre-onboarded) — a detached summon + orient-to-`taut
say`-sentinel + assert it lands; a ready+wired harness missing the sentinel
**fails** (not skip). Additionally **record each live harness's detached-mode
startup query set** (the responder logs every `ESC` report-request it sees) and
assert the recorded set is a subset of what the responder recognizes — surfacing
the **`awaiting_query`** stall for any harness whose real query set exceeds the
captured one, so a responder gap is caught here rather than as a silent
production hang (§4 P1-C). Feed the captured sets back into the S5 specs.
Document local-only, and that a first run needs one `taut summon --attach <name>`
to onboard/auth (this is how codex/qwen/pi become usable) before the detached
live test can run.

The local-LLM proof is separate: a CI-prepared loopback OpenAI-compatible model
endpoint drives a real PTY child that waits for orientation, calls the model,
and posts the sentinel through `taut say`. This is a credential-free transport
and PTY/mouth proof, not a replacement for the local real-harness matrix.

**S7 — Docs closeout + final gates.** Implementation doc (dumb-vs-capable
terminal, attach/detach + the wired flag, the query-responder, orientation as a
new driver step, why not `-p`/tmux/ptyprocess, the no-chat-relay decision, the
codex-trust-prompt / qwen-model / pi-auth caveats); READMEs; CHANGELOG; this
plan's Implementation Record; docs gate. Final gates (single runs; do not
hammer): full extension suite, core, ruff/format/mypy, `uv build`.

## 8. Testing Plan

- **Not mocked:** the PTY, the subprocess, the broker/CLI. Deterministic proofs
  ride the **fake interactive harness** (real subprocess over real PTY);
  real harnesses are the gated live smoke layer.
- **Layers:** unit (registry/resolution, sanitization, query-responder,
  persona render), PTY-integration (fake harness — attach/detach, orientation
  ordering, inject/interrupt/close, exactly-one-exit, settle, coarse activity),
  live (real harnesses, gated).
- **Contracts protected:** attach bridges + detaches; orientation precedes chat;
  ears reach the agent; interrupt/shutdown leave no zombie and unblock inject;
  activity is coarse; the full ears→mouth loop (sentinel via `taut say`).
- **Serial + `wait_until`** against observable state; never `time.sleep` sync;
  no xdist.

## 9. Verification and Gates

- Per-slice: named tests + ruff + format + mypy on the package.
- Final: single full extension suite, core, docs-reference gate, ruff/format/
  mypy, `uv build extensions/taut_summon`; clean artifacts.
- Observable success (local): `taut summon codex` attaches you to codex (you
  answer its trust prompt), you detach, and it answers injected chat in #dev via
  `taut say`; `taut dismiss codex` stops it cleanly (no zombie, ledger
  released).
- Rollback: additive + uncommitted — delete `_pty.py`, the fake harness, the
  registry rows, the `supports_terminal_mode` check, and the [SUM-7.4] text. No
  data migration, no one-way door.

## 10. Independent Review Loop

- After **S4b** and at completion, an independent adversarial review (Codex, a
  different agent family). Reviewer reads this plan, the reconciled delta,
  `_pty.py`, the fake-harness tests, the driver boundary, and the attach bridge.
  Prompt: *"Could you implement/verify this confidently and correctly? Attack
  the PTY lifecycle (zombie/fd leaks across resume, exactly-one-exit under
  races), the attach↔driver hand-off, orientation ordering, conditional
  bracketed paste + sanitization, the query-responder's sufficiency, the
  settle bound, coarse-activity vs presence, and whether the scoped driver
  change is truly minimal."* Handle each finding: fix, justify, or scope out
  with reason.

## 11. Out of Scope

- **Any chat relay of a stalled harness's prompt** (review P1: ungrounded — no
  recorded summoner, no reliable "no progress" signal for a `taut say` agent).
  A detached-not-wired stall is a log line + the `awaiting_onboarding` STATUS
  field; the resolution is `taut summon --attach`.
- Auto-detecting harness "readiness" from output (impossible without screen
  parsing) — replaced by the wired flag + explicit first-run detach.
- Terminal-mode assistant-text posting under PTY (needs screen emulation;
  `claude-stream` provides it).
- Structured session resume for PTY harnesses ([SUM-7.3]).
- Fixing codex's MCP config, qwen's model entitlement, pi's auth — resolved by
  the human during attach, or skipped in live tests.
- Windows PTY (`pywinpty`); summon is unix/one-machine ([TAUT-2]).
- Adopting `ptyprocess`/`pexpect`/`tmux`/`pyte` — reserved fallbacks only.
- Screen-scraping harness output for any purpose beyond liveness.

## 12. Fresh-Eyes Check

Load-bearing risks: (a) PTY lifecycle + the attach↔driver hand-off (zombies, fd
leaks, exactly-one-exit) — mitigated by reusing `_stream.py`'s discipline and
testing against a real fake-harness PTY that models redraw/queries/onboarding;
(b) the scoped driver change (capability check + attach hook) is minimal —
pinned as an invariant + stop-gate; (c) environment-dependent live tests —
contained by the fake harness carrying the real proofs and an honest skip gate.
The onboarding/trust problem is resolved the right way — the human answers it
via attach, not an auto-bypass. No one-way doors; additive and uncommitted.

## 13. Review Log

**Round 1 — Codex (2026-07-07), on the v1 plan. Verdict: No.** 8 P1 + 3 P2.
All resolved in this v2 (see the reconciled §4 delta and §6 invariants):

1. "Zero driver changes" false (terminal mode computed pre-spawn with no
   capability check) → v2 retracts the claim; adds `supports_terminal_mode`
   and one scoped driver check ([SUM-6], §6 Blocker-1).
2. Byte-flow `ActivityEvent` pins `last_active_ts` forever → v2 makes PTY
   activity coarse and anchors presence to the child process ([SUM-7.1],
   [SUM-4]).
3. Unbounded "TUI settle" → bounded (quiet-500ms **or** max-10s).
4. Orientation ordering underspecified → injected under the inject-lock
   before the watcher starts; per-harness auto-resume disabled.
5. PTY lifecycle vague (fd close, EOF, exactly-one-exit) → specified,
   mirroring `_stream.py`.
6. Bracketed paste overclaimed → conditional (only when the harness enabled
   it) + payload sanitization + line fallback.
7. Ctrl-C/controlling-terminal semantics → `\x03` as raw-mode cancel with
   SIGTERM/SIGKILL fallback + live proof; terminal-query responder added.
8. Spec delta incoherent (stale [SUM-1]/[SUM-6]/[SUM-7.1]/[SUM-10]/[SUM-12])
   → all reconciled in §4. Typo (grok≠coder) fixed in S5.

**Beyond the review**, two empirical diagnostics reshaped the design:
codex's "failure" was a first-run **trust prompt** (not PTY
incompatibility), and harnesses emit **terminal queries** at startup. Both
are handled the right way — the human answers onboarding/trust/login via
the **attach** phase (not an auto-bypass), and summon answers queries as a
minimally-capable terminal. pi (empty auth) and qwen (paywalled model) are
credential gaps resolved during attach or skipped in live tests.

**Round 2 — Codex + an independent Claude reviewer (2026-07-07), on v2.
Both verdicts: No; independently convergent.** 6 (Codex) + 3 (Claude) P1s,
resolved in this v3:

1. **Auto-detach quiescence heuristic broken both ways** — premature at a
   quiet trust prompt (orientation typed into the gate) *and* never-fires on
   an animating ready TUI; distinguishing the states needs the forbidden
   screen parsing. → Removed entirely; replaced by the **wired ledger flag**
   + explicit first-run detach (§4 attach/detach, §6).
2. **Orientation is a new driver step**, not an existing sequence → §4 says
   so; the driver-touchpoint count corrected to **four** (§6), honestly.
3. **Attach vs. the event pump race for the master fd** → pump/watcher do not
   start during attach; single reader owner with an explicit hand-off (§4).
4. **Attach re-triggers on resume / termios wedge / close-vs-reader fd
   ownership / EIO-as-EOF** → first-generation gate, `finally` termios
   restore, close-vs-reader fd ownership defined (later refined in v8 to the
   single `close()`-reaps-and-closes-iff-no-reader rule), EOF+EIO both → one
   exit (§4, §6).
5. **Relay fallback ungrounded** → dropped; stall = log + `awaiting_
   onboarding` STATUS (§4, §11).
6. **S1/S5 registry migration inconsistent** → the `claude`→PTY flip + the
   [SUM-7.2] "pty default" text land atomically in S5 (§7).
7. **Sanitization order + multi-line line-mode** → strip C0/ESC first (kills
   the terminator), then frame or newline-collapse (§4 ears, §6).
8. **Query-responder gaps** (cursor-park size-probe, XTVERSION/DECRQM,
   blocking-on-unknown) and **stale [SUM-2]** → both addressed (§4).

**Design input (user, 2026-07-07): attach vs. a TUI.** Attach is two
full-screen TUIs on one terminal, and v3-draft under-specified it. Fixed in
§4/§6: (a) the detach trigger is a **configurable non-`ESC` chord**, not
`ESC q` — a raw-mode bridge must never intercept `ESC` (Escape/arrows); (b)
**nesting** — attach composes with tmux/screen panes but is **refused inside
a single-terminal host TUI** (taut's own future TUI shells out to attach);
(c) **terminal restore on detach is more than `termios`** — the still-running
harness never cleans up, so summon exits the alt screen and disables
mouse/paste/kitty modes on the local tty too. Detached driver mode is
unaffected (no human terminal involved).

**Round 3 — Codex + an independent Claude reviewer (2026-07-07), on v3.
Both verdicts: No; convergent on precise PTY-detail blockers. All six
round-2 design blockers confirmed *resolved*.** Fixed in this v4:

1. **Wired flag had no storage design and would trip the fail-closed schema
   gate** (both, P1) — v4 makes it a versioned [SUM-8] change: bump
   `SUMMON_SCHEMA_VERSION` 1→2, add the `wired` column, extend the typed row +
   explicit column lists + `get_wired`/`set_wired`, old-v1-DB recreate is the
   migration; landed in S1 with tests before S4 consumes it (§4 [SUM-8] amend,
   §6, S1).
2. **Sanitization stripped the newlines it later needed** (`LF` is a C0 byte)
   (both, P1) — v4 canonicalizes CRLF/CR→LF, strips `ESC`+C0 **except `LF`**
   (TAB→space), then paste preserves `LF` / line mode collapses it (§4 ears, §6).
3. **"Benign no-op reply to unknown queries" was unsafe** (Codex P2, Claude P1)
   — the reply channel *is* the app's keyboard input, so replying to an
   unclassifiable sequence injects spurious keystrokes, and "unknown query" is
   not even identifiable from the child. v4 **inverts** the rule: reply only
   within the finite recognized families, emit nothing else (§4 responder).
4. **Cursor-park DSR must clamp** (Codex P1) — v4 tracks CUP/HVP with clamping to
   the configured winsize and replies the clamped size to `ESC[6n`, never
   `999;999R`/`1;1R` (§4 responder; S2 proves it).
5. **STOP-during-attach was unhandled; master-fd ownership on that path
   unspecified** (Claude P1) — v4 makes the bridge `select` over
   `[tty, master, shutdown_waker]` so a control STOP is consumed while attached
   ([SUM-9]); on that path the bridge owns/closes the master and restores the tty
   (§4 attach, §6, S4b).
6. **§5 carried stale v1/v2 "ONE change"/"existing orient sequence" text**
   (Claude P1) — reconciled to the four named touchpoints, orientation as a new
   step, verified against `_supervise` (§5).
7. **Terminal restore incomplete + "modes it saw" dynamic tracking** (both) —
   v4 uses a **fixed idempotent reset blast** (`CAN`, alt-screen variants,
   cursor, scroll region, DECCKM/keypad, focus, all mouse variants,
   bracketed-paste, kitty pop) then `tcsetattr`, and S2 enables these modes so
   restore is proven (§4, §6, S2).

P2s folded: `Ctrl-\` is readable because `tty.setraw` disables `ISIG` (noted);
the detach chord is a byte-at-a-time matcher across reads; nesting detection is
**cooperative only** via `TAUT_HOST_TUI` (arbitrary host TUIs best-effort);
DECRQM answers a valid state-0 DECRPM report; EIO is Linux-only (darwin=EOF), so
the fake harness exercises EOF and the EIO branch is Linux-CI/stubbed; the
orientation-inject step is gated by `orientation_via_inject`; S4 split into S4
(adapter + touchpoints) and **S4b** (attach bridge) as separate reviewable
slices; the hollow "does-not-auto-detach" test replaced with a real
"stays-attached-until-explicit-detach" test; header corrected to v4;
`[TAUT-8.4]` (Watcher) miscite for the TUI corrected to `[TAUT-12.4]`.

**Round 4 — Codex + an independent Claude reviewer (2026-07-07), on v4.
Both verdicts: No; both confirmed every round-1–3 design blocker resolved and
called the residue "small, well-scoped." Fixed in this v5** (the three were
v4-introduced precision errors, not design regressions):

1. **Wired-flag edit-site list was wrong and would silently clobber** (Claude
   P1, Codex P2) — the named `claim_driver`/`release_driver` have **no** wired
   column list (they read via shared `_SESSION_SELECT` + targeted UPDATEs) and
   `claim_driver` runs on **every re-summon**, so editing them as written resets
   `wired→0` on every reconnect. v5 names the **real** sites — `_SESSION_SELECT`,
   the inline `SELECT` in `list_sessions`, `record_session`'s `INSERT`,
   `_session_row` — states `claim_driver`/`release_driver` get **no** wired
   write and `record_session`'s UPDATE **preserves** it, makes `get_wired`/
   `set_wired` the only writers, and adds a clobber-regression test (§4 [SUM-8]
   amend, §6, S1).
2. **STOP-during-attach fix tripped the four-touchpoint stop-gate** (Claude P1,
   Codex P1) — having `request_stop` write the waker pipe is a fifth edit. v5
   uses a **bridge-local forwarder waiting on the existing `self._wake` Event**
   (request_stop/shutdown untouched) feeding a bridge-owned pipe the `select`
   watches, plus an **explicit post-attach driver branch** (on shutdown: no
   pump/watcher, no hand-off, `interrupt`/`close` tolerate a closed master,
   bridge closes the master once) (§4 attach, §6, S4b).
3. **"Ignore unknown queries is safe" argument was logically void** (Claude P1,
   highest-value) — the responder runs **only detached**, so attach never
   exercises it; wired re-summons and [SUM-11] resumes hit it cold, and only
   codex's query set was captured. v5 **drops the void argument** and adds a
   bounded **`awaiting_query` stall diagnostic** (log + STATUS) so a blocking
   unknown query is observable, not a silent hang, plus **per-harness
   detached-mode query-set capture** (S2 parametrized, S6 live, fed to S5 specs)
   (§4 responder, S2/S3/S5/S6).

P2s folded: strip **DEL `0x7f`** in sanitization (C1 is a non-issue over UTF-8);
cursor clamping also tracks **relative** moves (CUF/CUD/CUB/CUU) for the
`ESC[9999C`-walk size-probe; restore blast adds **SGR reset `ESC[0m`**, autowrap,
synchronized-output `?2026l`, alt-scroll `?1007l`, and `CAN`+`ST` for OSC/DCS
string termination; **S4 is now explicitly detached-only** (the attach gate,
`wired` set-on-detach, `--attach`, and first-run-tty branch all live in S4b, so
S4 alone can't wedge a real-tty first run); S2's restore proof is stated as
**byte-level** (a raw PTY has no emulator for a visual assert). Header → v5.

**Round 5 — Codex + an independent Claude reviewer (2026-07-07), on v5.
Split verdict: Claude **Yes** (all round-4 fixes verified correct against the
code, nothing new broke); Codex **No** on two precision gaps in the new v5 S4b
surface. They agreed on substance, differing only on P1-vs-P2 severity. Both
confirmed the wired-flag edit sites correct line-by-line against `_state.py`
(`_SESSION_SELECT`, `list_sessions` inline SELECT, `record_session` INSERT with
a targeted UPDATE that preserves `wired`, `_session_row`; `update_session`/
`claim_driver`/`release_driver` all targeted, no clobber) and all P2 fixes
correct. v6 specifies the two mechanisms (no new design surface):**

1. **Forwarder deadlock on normal detach** (Codex P1 / Claude P2) — waiting only
   on `self._wake` never unblocks on an ordinary chord-detach (the common path),
   hanging the join. v6: the forwarder loops on `self._wake.wait(timeout)` and
   also checks a **bridge-local `done` Event** set in the bridge's `finally`,
   unblocking on either path (still no `request_stop` edit) (§4, §6, S4b).
2. **Master double-close race** (Claude P2) — v6 names the **`handed_off` flag**
   gating the bridge's conditional `finally` close: reader closes on normal
   detach, bridge closes on STOP-during-attach, exactly one per path (§4, §6).
3. **Single-shot query-hang missed** (Codex P1) — the repeat-only trigger never
   fires when a harness emits **one** unknown query then blocks on the reply.
   v6: the trigger is **"an unanswered report-shaped query outstanding + no
   output progress for `stall_s`"** (single-shot), the contract is stated
   **report-only + `--attach`-recoverable** (never fabricate a reply), and a
   **conservative "report-shaped" predicate** (report-request families in;
   draw/control sequences out) prevents redraw false-positives (§4, S3).
4. **STATUS-field slice alignment** (Codex minor) — `awaiting_query` is
   introduced in S3, `awaiting_onboarding` in S4; S5 only wires them per
   provider (S3/S4/S5).

Header → v6. Round-5 also reconfirmed: DEL strip, relative-move cursor clamping,
the fuller restore blast, the detached-only S4/S4b split, and byte-level S2
restore proof are all correct and not harmful.

**Round 6 — Codex + an independent Claude reviewer (2026-07-07), on v6.
Claude r6 returned Yes (all three v6 mechanisms sound, every code-checkable
claim verified against `_driver.py`/`_state.py`); Codex r6 returned No on one
P1. Both independently identified the **same** issue — a zero-closer window in
the master hand-off — differing only on severity (Codex blocker, Claude benign
because process-exit reclaims the fd + `close()` still reaps the child). Fixed
in this v7:**

1. **Zero-closer window** (Codex P1 / Claude P2) — an exception after a naive
   `handed_off=True` but before the pump owns the fd (the `rejoin`/
   `ensure_threads`/`set_wired` span) would leave the master unclosed by anyone.
   v7: an **idempotent `close_master()`** (lock + `_master_closed` flag); flip
   `handed_off` only after the reader is confirmed running; the driver guards the
   post-detach→pump-started span so any exception there calls `close_master()`.
   Exactly one effective closer on every path, never zero; `close_master()` is
   never called while a reader is blocked in `read()`, so it adds the
   reader-never-ran closers without a use-after-close race, and `close()` still
   only signals (§4, §6, S4b + the round-6 zero-closer test).
2. **Forwarder pipe cleanup** (Codex P2) — v7 specifies a small finite wait
   timeout, teardown order `done.set()` → join → close pipe fds, and swallowing
   `BrokenPipeError`/`OSError` on the forwarder write (§4, S4b).
3. **STATUS transport hook** (Codex P2) — `StatusSnapshot` is fixed-field with no
   handle query, so v7 names the transport: the handle's
   **`status_fields() -> dict[str, Any]`** merged by `ControlLoop` into the
   snapshot, tested through a real `STATUS` request (§4, S3).
4. **`stall_s` blocked⇒silent premise** (Claude P2 / Codex check) — v7 states the
   reader uses a **timed `select`/poll, never a blocking `read`**, so the timer
   fires while a harness blocks; the blocked⇒silent premise holds for
   single-threaded TUIs and is backstopped by the S6 query-set capture for a
   render-threaded harness (§4, S3). Plus a sentence that **settle cannot detect
   the block** — orientation is lost, `awaiting_query` then fires and `--attach`
   resolves; a bounded, surfaced cost inherent to not parsing the screen (§4).

Round 6 also re-confirmed against the code (no regression): the wired-flag
column sites, the `_supervise` ordering / four-touchpoint framing, the
forwarder-is-not-a-fifth-touchpoint claim, the conservative report-shaped
predicate, and report-only-+-`--attach` as the correct final query contract.

**Round 7 — Codex + an independent Claude reviewer (2026-07-07), on v7.
Split verdict: Claude **Yes** (traced all four fd paths, "round-6 zero-closer
airtightly closed", no remaining P1); Codex **No** on two P1s. Both reviewers'
concerns converged on one edit, folded in v8:**

1. **Zero-closer didn't generalize to the detached path** (Codex P1) — v7 guarded
   only the *attach* hand-off window, but `_supervise` runs `rejoin`/
   `ensure_threads` before `pump.start()` on **every** summon, and a detached
   pre-pump exception still leaked the master.
2. **Attach-vs-`rejoin` ordering contradiction** (Codex P1) — "guard includes
   `rejoin` post-detach" vs "member present/anchored during attach" (spec anchors
   at `rejoin()`) can't both hold.
3. **`close_master()` alone leaves a zombie** (Claude P2, important) — it closes
   the fd but does not `waitpid`-reap.

v8 unifies all three into **one `close()` rule**: `close()` signals+reaps the
child **and** closes the master **iff no reader has started** (`_reader_started`
flag; else the reader closes on EOF, preserving the `_stream.py` discipline). The
driver calls `handle.close()` on **any** exception in the whole
`spawn → pump-started` span (extending the existing `rejoin`-failure close),
covering **detached and attached** paths and always reaping (no zombie, no leak).
The ordering is pinned: **`spawn → rejoin (anchor/present) → ensure_threads →
[attach→detach→set_wired] → pump.start → settle → inject → watcher`** — `rejoin`
+ `ensure_threads` before attach,
so "present during attach" holds. The spawn-span guard is **universal/additive**
(reaping a failed spawn is correct for every adapter), so structured adapters are
unaffected and it is **not** a fifth capability-gated touchpoint (§4, §6, S4/S4b).

Plus P2s: the STATUS transport gets a **JSON-primitive contract + reserved-key
rule** (merge `status_fields() -> dict[str, str]` into `_status_fields()`'s
`as_fields()` output — not the frozen `StatusSnapshot`; the `awaiting_query` value
is an escaped string, never `bytes`; no collision with existing snapshot/envelope
keys) (§4, S3). Round 7 also **re-confirmed** (both reviewers, against the code):
the forwarder pipe cleanup, the `stall_s`/timed-read premise, the settle caveat,
the `_supervise` ordering, and the wired-flag sites — all still correct, no
regression. Header → v8.

**Round 8 — Codex (2026-07-07), on v8. Verdict: Yes — no P1 blockers** (the
first Codex Yes; the Claude round-8 verdict is pending). Codex verified against
the code: the unified `close()` rule (signal+reap, close master iff no reader
started) is sound and reconciles with `_stream.py` (which closes pipes in
`close()` only because pipes have no reader-owned master-fd race — PTY needs the
split); the existing code already calls `handle.close()` on `rejoin` failure so
the shared `spawn→pump-started` guard is implementable and also covers an
`_agent_capture()` failure; `rejoin`-before-attach matches [SUM-4] and a present
member during a long onboarding is acceptable (child alive/anchored, chat unread
until pump/watcher start); the spawn-span guard is not a fifth capability-gated
touchpoint (it only affects structured adapters on failure paths, where reaping
a spawned child is correct); and `_status_fields()` is the right STATUS merge
point. Two exact-text P2s, both applied: (a) add **`rate_breaches`** to the
reserved-key list (also emitted by `StatusSnapshot.as_fields()`); (b) pin
**`ensure_threads`** in the startup order (`spawn → rejoin → ensure_threads →
[attach→detach→set_wired] → pump.start`) so re-summons that add threads stay
joined during attach.

**Round 8 (Claude) — Yes; CLEAN BOTH-YES CONVERGENCE.** The independent Claude
reviewer also returned **Yes** against the code: it traced all four fd paths
(exactly-one/never-zero holds), confirmed the `_supervise` ordering and the
[SUM-4] rejoin anchoring, validated the universal spawn-span guard, and confirmed
the STATUS merge point. Its three non-blocking P2 advisories are folded in:
(a) `rate_breaches` added to the reserved-key list (same as Codex); (b) the
`handed_off`/`_reader_started` two-names-one-flag unified to a single
`_reader_started` set under the lifecycle lock; (c) the spawn-span guard
re-raises after `close()`, and the **close-before-first-read `EBADF`** window
(fast `watch()`/`pump.start()` failure) is handled by treating **any `OSError`
on the master read as end-of-stream** plus a `_master_closed`-under-lock check
before the reader's first read. **Both reviewers now Yes; the plan is approved
for slice-by-slice implementation.**

## 14. Implementation Record

_(appended as slices land)_

- 2026-07-07 — S1 landed: promoted the summon spec delta for PTY hosting,
  adapter capabilities, terminal-mode capability gating, the `wired` schema
  contract, PTY orientation, and verification expectations. Implemented
  adapter capabilities, `claude-stream`, `SUMMON_SCHEMA_VERSION = 2`,
  `wired` DDL/row mapping, `get_wired`/`set_wired`, and the terminal-mode
  capability warning. Targeted proof:
  `uv run pytest extensions/taut_summon/tests/test_state.py extensions/taut_summon/tests/test_scripted_adapter.py::test_registry_knows_scripted_and_rejects_unknown_names extensions/taut_summon/tests/test_claude_adapter.py::test_registry_knows_claude`
  → 25 passed.
- 2026-07-07 — S2/S3 landed: added the real fake-TUI PTY fixture and the PTY
  core responder/handle with cursor clamping, finite query replies,
  `awaiting_query`, sanitized injection, bracketed-paste framing, coarse
  activity, EOF/OSError exit handling, and STATUS fields. Targeted proof:
  `uv run pytest extensions/taut_summon/tests/test_pty_adapter.py` → 8 passed.
- 2026-07-07 — S4/S4b landed: wired detached PTY into the driver with the
  universal spawn-span close guard, reader-owned master fd lifecycle,
  orientation-before-watcher, `--detach`, attach bridge, `--attach`, `wired`
  set-on-detach, STOP-aware bridge wakeup, non-ESC split chord matching, and
  terminal reset blast. Targeted proof:
  `uv run pytest extensions/taut_summon/tests/test_driver.py::test_pty_terminal_mode_is_disabled_by_capability extensions/taut_summon/tests/test_driver.py::test_pty_detached_orientation_is_injected_before_chat extensions/taut_summon/tests/test_driver.py::test_pty_status_reports_awaiting_query extensions/taut_summon/tests/test_driver.py::test_pty_detached_pre_pump_failure_reaps_child extensions/taut_summon/tests/test_driver.py::test_pty_first_run_attaches_until_chord_and_sets_wired`
  → 5 passed.
- 2026-07-07 — S5/S6 scaffold landed: registered named PTY providers
  (`claude`, `codex`, `coder`, `grok`, `qwen`, `kimi`, `opencode`, `pi`),
  kept `claude-stream` for structured mode, documented the default flip, and
  added live harness smoke scaffolding that runs by default locally and remains
  opt-in for CI. Final formatting, type, docs, and suite gates still pending.
- 2026-07-07 — Final local gates: `uv run ruff format --check
  extensions/taut_summon/taut_summon extensions/taut_summon/tests` → 27 files
  already formatted; `uv run ruff check extensions/taut_summon/taut_summon
  extensions/taut_summon/tests` → all checks passed; `uv run --extra dev mypy
  extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file
  pyproject.toml` → success, no issues in 27 files; `uv run pytest
  extensions/taut_summon/tests` → 145 passed, 15 skipped; `uv run pytest
  tests/test_docs_references.py` → 2 passed; `uv run pytest` → 297 passed;
  `uv build extensions/taut_summon` → sdist and wheel built, then generated
  `extensions/taut_summon/dist/` removed.
- 2026-07-07 — Independent review: a Codex read-only review found four
  serious issues: blocking Ctrl-C writes could wedge STOP behind a full PTY
  input queue; `--attach` could re-grab the terminal on crash-resume inside the
  same driver run; orientation had no pump-reader readiness barrier; and
  `awaiting_query` was not visible through public `taut-summon status`. Fixes:
  PTY interrupt/close use nonblocking Ctrl-C, and `interrupt()` escalates to
  SIGTERM if the byte cannot be queued; `--attach` is gated by
  `first_generation`; `PtyHandle` exposes a reader-start event and resets
  `last_output_ts` when the reader owns the master before settle/orientation;
  `awaiting_query` logs and public status renders adapter fields. A follow-up
  review found one remaining P1: `interrupt()` itself still did not unblock a
  full-queue `inject()` before driver watcher join. Fixed by escalating
  `interrupt()` to SIGTERM on nonblocking Ctrl-C `EAGAIN`, with
  `test_interrupt_unblocks_full_pty_input_queue`. Narrow follow-up read-only
  review: no remaining blocker for this issue; reviewer verified the test
  passed.
- 2026-07-07 — Local live harness policy corrected per project preference:
  `tests/test_live_harness.py` now runs the live matrix on local pytest by
  default, skips in CI unless `TAUT_SUMMON_LIVE_HARNESS=1`, and keeps
  `TAUT_SUMMON_LIVE_HARNESS=0` as the local fast-loop escape hatch.
- 2026-07-07 — Added the Backstitch-style local LLM lane for summon:
  `tests/test_live_local_llm.py` uses a loopback OpenAI-compatible endpoint, a
  counting proxy, a real PTY child, orientation injection, and `taut say`
  sentinel posting. `.github/workflows/test.yml` now has a dedicated Ubuntu
  Ollama job that creates `taut-summon-local-model:latest` from
  `qwen2.5:0.5b` and runs this lane with `TAUT_SUMMON_LOCAL_LLM=1`.
