# Summon Enhanced-Keyboard Detach Plan

Status: Implemented, including the post-review `ESC`-gating and symmetric
keyboard-reset follow-ups; automated verification and independent review
passed. Changes are uncommitted. The physical-terminal observation remains
pending and is explicitly waived for the owner-requested 0.9.9 release.

Class: 5 (spec-changing) and risky under [DOM-5]: the change revises the
normative attach input contract and the terminal-protocol compatibility
surface. Hardening is required. The change is not process-changing.

Plan type: implementation with spec revision.

## Goal

Make the advertised `Ctrl-\ Ctrl-\` detach chord work after an attached
provider enables a standard enhanced-keyboard protocol. Summon will recognize
the legacy control byte and the semantic Control-Backslash key event in the
Kitty CSI-u and xterm `modifyOtherKeys` encodings, while forwarding all other
input to the provider byte-for-byte and preserving the existing attach,
cleanup, and `wired` lifecycle.

## Requested Outcomes

- [x] Reproduce the defect as a failing shared-matcher test: two enhanced
  Control-Backslash events are forwarded instead of detaching.
- [x] Recognize the detach chord independently of whether the host terminal
  emits legacy, Kitty CSI-u, or xterm `modifyOtherKeys` input.
- [x] Preserve exact bytes and order for incomplete, malformed, unsupported,
  and non-detach input, including a failed chord after one candidate event.
- [x] Prove the shared matcher through both POSIX PTY and Windows ConPTY attach
  paths without provider-name or terminal-name branches.
- [x] Align the Summon spec, implementation note, extension README, code, and
  tests.

## Source Documents

Source specs:

- `docs/specs/04-summon.md` [SUM-7.4], [SUM-8], [SUM-13]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-4]–[DOM-8],
  [DOM-10], [DOM-11], [DOM-15]

Supporting context:

- `docs/program-theory.md` [THEORY-2]–[THEORY-5]
- `docs/implementation/05-taut-summon-architecture.md`, “PTY adapter” and
  “Attach/detach and `wired`”
- `extensions/taut_summon/README.md`, first-PTY-use handoff
- Kitty keyboard protocol, “Progressive enhancement” and CSI-u event grammar:
  <https://sw.kovidgoyal.net/kitty/keyboard-protocol/>
- xterm `modifyOtherKeys` format as consumed by the installed provider TUI:
  `CSI 27 ; modifiers ; keycode ~`
- OpenAI Codex keyboard-mode implementation: Codex pushes Kitty
  `DISAMBIGUATE_ESCAPE_CODES | REPORT_ALTERNATE_KEYS`, and may include event
  reporting depending on terminal/transport.

Observed defect, 2026-09-23: in a real `taut summon codex` run under Ghostty,
the host tty remained in Summon's raw attach mode, but `Ctrl-\ Ctrl-\` did not
detach after the provider initialized. Grok also received and acted on the
same key. That cross-provider observation, the providers' enhanced-keyboard
negotiation, and the current literal-only matcher identify the boundary bug:
provider output changes how the host terminal encodes later input, while
Summon continues to match only `b"\x1c\x1c"`.

## Spec Baseline

- `1f3b6c6bf70c55725df1268a19066fb06e33818f` —
  `docs/specs/04-summon.md` at plan authoring time.
- The spec file is clean at this baseline. The worktree contains unrelated
  owner edits in other documentation files, including
  `docs/implementation/05-taut-summon-architecture.md`; preserve them and
  stage only task-owned hunks.
- Promotion baseline identifier: uncommitted worktree delta against
  `c0a4616e76e954e3f9fbea93fbf487c3ee660cbe`; `git diff --numstat --
  docs/specs/04-summon.md` reports `62 5` after implementation evidence was
  added.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**. Promote the
replacement [SUM-7.4] paragraph and related-plan backlink before code. Add no
implementation claim until the code/test slice; reconcile reciprocal links in
the final documentation slice.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/04-summon.md` | A | [SUM-7.4] attach/detach matcher paragraph; `## Related Plans` |

### [SUM-7.4] — replace the detach-matcher paragraph

> The detach chord matcher consumes a stream of host-input bytes across read
> boundaries. For the default `Ctrl-\ Ctrl-\` chord, each chord atom may be
> either the legacy `0x1c` byte or a complete semantic Control-Backslash key
> event encoded by Kitty CSI-u or xterm `modifyOtherKeys`. Kitty press events
> and repeat events count as chord atoms, preserving the legacy behavior in
> which terminal repeat is indistinguishable from repeated control bytes;
> release events for the same logical Control-Backslash identity may occur
> between atoms but do not count or break the chord. Such a release uses the
> same permitted identity and modifier rules as a press, with event type 3.
> The accepted Kitty wire grammar is exactly
> `CSI <primary>[:<shifted>[:<base>]];<modifier>[:<event>]u`, where each named
> value is a non-negative decimal integer, `<shifted>` may be empty only when
> `<base>` is present, and no associated-text field follows the modifier field.
> The event defaults to press when omitted; `1`, `2`, and `3` mean press,
> repeat, and release. The primary or shifted value must be code point 92;
> base-layout value 92 alone does not identify the chord. A present shifted
> value requires the Shift modifier.
>
> Kitty modifiers are the decimal value `1 + bitmask`, with Shift `1`, Alt
> `2`, Control `4`, Super `8`, Hyper `16`, Meta `32`, Caps Lock `64`, and Num
> Lock `128`. Control is required; Shift and the two lock bits are permitted;
> Alt, Super, Hyper, Meta, unknown bits, and unknown event types reject the
> candidate. Thus the accepted encoded modifier values are exactly `5`, `6`,
> `69`, `70`, `133`, `134`, `197`, and `198`.
>
> The accepted xterm grammar is exactly `CSI 27;<modifier>;92~` and carries no
> event type or alternate key. Its modifier is likewise `1 + bitmask`, with
> Shift `1`, Alt `2`, Control `4`, and Meta `8`; Control is required, Shift is
> permitted, and Alt, Meta, or unknown bits reject the candidate. Its accepted
> encoded modifier values are therefore exactly `5` and `6`.
>
> The matcher buffers only a bounded possible chord or supported enhanced-key
> sequence, detaches only after two recognized atoms, and otherwise forwards
> every original byte once and in order. Split sequences are recognized across
> reads. A possible enhanced-key prefix creates a 100 ms input-ambiguity
> deadline owned by the attach adapter. The adapter supplies the remaining
> deadline to its existing blocking source wait (`select()` on POSIX and the
> input-chunk queue on Windows); continuation bytes do not move that initial
> deadline, and the adapter does not poll the clock independently.
> When the wait returns, the same serialized input owner handles ready input
> before a simultaneously due deadline, then forwards all expired pending bytes
> unchanged. The deadline creates no timer thread and publishes no separate
> broker event. Incomplete, malformed,
> expired, overlong, unsupported, unrelated, or failed chord input is not
> normalized or dropped.
> The matcher may hold an `ESC` prefix only for that bounded decision; it
> intercepts only a complete encoding of the reserved detach key. Escape,
> arrows, function keys, paste data, and provider shortcuts otherwise pass
> through unchanged. Non-default internal test chords retain byte-exact
> matching and do not acquire protocol aliases.

### `## Related Plans` — add

> - `docs/plans/2026-09-23-summon-enhanced-keyboard-detach-plan.md` — makes
>   the default detach chord semantic across legacy, Kitty CSI-u, and xterm
>   `modifyOtherKeys` input without provider- or terminal-specific branches.

## Context and Key Files

Files to modify:

- `docs/specs/04-summon.md`: promote the exact [SUM-7.4] delta and backlink.
- `extensions/taut_summon/taut_summon/_pty.py`: keep
  `_DetachChordMatcher` as the single shared input owner; add the bounded,
  narrow enhanced-key event recognition here.
- `extensions/taut_summon/tests/test_pty_adapter.py`: pure streaming/parser
  matrix plus real POSIX PTY bridge proof.
- `extensions/taut_summon/tests/test_pty_windows.py`: prove the existing
  ConPTY attach session consumes an enhanced chord through the shared matcher
  and forwards mismatches exactly.
- `docs/implementation/05-taut-summon-architecture.md`: explain why the
  bridge recognizes semantic aliases and how its buffering boundary remains
  narrow. Preserve the owner's existing dependency-floor edit.
- `extensions/taut_summon/README.md`: clarify that the documented chord also
  works when the provider has enabled enhanced keyboard reporting.
- `docs/plans/README.md`: keep this plan's status row current.

Read before editing:

- `_TerminalState.detach_matcher()` and `_DetachChordMatcher.feed()` in
  `_pty.py`: both POSIX and Windows obtain the same matcher here.
- `PosixPtyHandle.attach()` in `_pty_posix.py`: it reads raw host bytes,
  invokes the matcher, and forwards the returned bytes to the provider PTY.
- `_AttachSession._bridge()` in `_pty_windows.py`: it applies the same contract
  to Win32 `ReadFile` chunks and the ConPTY writer.
- `_TerminalInputModeTracker` and `_TerminalResponder` in `_pty.py`: they
  observe provider output but must not become a second detach owner.
- Existing attach tests around
  `test_attach_bridges_and_split_chord_detaches_with_reset` and Windows
  `_AttachSession` tests: reuse their real bridge seams.

Current owner: `_DetachChordMatcher` owns chord buffering. Do not move
recognition into provider adapters, the driver, the POSIX loop, the Windows
loop, or terminal-name detection.

Comprehension gates before implementation:

1. **Question:** Why can provider output alter bytes later read from the host
   tty even though Summon set the tty to raw mode?
   **Expected answer:** raw mode disables local line/signal processing, but an
   attached TUI's output can ask the terminal emulator to encode future key
   events with Kitty CSI-u or `modifyOtherKeys`; those encoded bytes then reach
   Summon's raw reader.
2. **Question:** Why must failed candidate input remain buffered until its
   status is known?
   **Expected answer:** forwarding the first detach atom or a prefix early can
   expose half a chord, reorder a Kitty release before its press, or duplicate
   bytes when a later byte disproves the match. On failure, the original bytes
   must be emitted once in their original order.

Record both answers in the Execution Log before the first code edit. An
incorrect answer blocks implementation until the cited code and spec are
reread.

## Invariants and Constraints

- The visible chord remains `Ctrl-\ Ctrl-\`; no terminal configuration,
  provider flag, environment workaround, or provider-specific branch becomes
  part of the product contract.
- `_DetachChordMatcher` remains the one shared recognizer used by POSIX and
  Windows. The platform bridges keep their present lifecycle and ownership.
- Legacy `b"\x1c\x1c"` behavior stays exact, including matching across read
  boundaries and treating repeated bytes as two atoms.
- Recognition is semantic but narrow. Kitty CSI-u and xterm
  `modifyOtherKeys` are parsed only far enough to identify the reserved key;
  this work does not introduce a general keyboard library.
- Original bytes are the source of truth. A mismatch flushes the whole pending
  candidate exactly once and in order; the matcher never reserializes input.
- Buffering is bounded by a named constant and linear in bytes scanned. An
  unterminated or oversized CSI prefix cannot retain memory without bound or
  make repeated rescans quadratic.
- Enhanced-prefix ambiguity is also time-bounded. The matcher exposes its one
  pending monotonic deadline and one expiry operation. The attach adapter folds
  that deadline into its existing blocking source wait: POSIX waits for input,
  provider output, or the earlier of its lifecycle bound and matcher deadline;
  Windows waits for an input chunk or the earlier of its lifecycle bound and
  matcher deadline. This is clock work owned by the serialized input adapter,
  consistent with [BASE-3]/[BASE-4]; it is not a second poll of present state.
  Ready input wins over expiry at an equal boundary. After servicing ready
  sources, the owner expires any still-pending prefix due at the current
  monotonic time. Provider output, spurious wakes, and repeated empty waits
  must not starve or reset the deadline; continuation bytes do not move it.
  Do not add a timer thread, another
  event loop, a broker-reactor callback, or a second platform parser.
- Two qualifying press/repeat atoms detach. Same-key Kitty release events may
  appear between them, are held with the pending chord, and are discarded on
  successful detach; on failure, the press/release bytes are forwarded in
  original order. Release alone never starts or completes a chord.
- For Kitty identity, implement exactly the finite grammar and modifier table
  in the proposed [SUM-7.4] delta. In particular, alternate-key reporting can
  produce `CSI 92::92;5u`, `CSI 92::92;5:1u`, and the corresponding repeat or
  release forms; these are required fixtures, not optional examples.
- For xterm `modifyOtherKeys`, implement only the finite grammar and its
  protocol-specific modifier table in the proposed [SUM-7.4] delta. Do not
  infer Kitty lock-bit meanings for xterm fields.
- A non-default `detach_chord` remains byte-exact. Protocol aliases are tied to
  the default public chord, preventing surprising semantics in internal tests
  or future configuration work.
- Escape, arrows, function keys, bracketed paste, mouse/focus reports,
  unrelated CSI-u events, and malformed sequences continue to reach the child
  unchanged.
- Detach cleanup remains unchanged: terminal reset, tty/console restoration,
  reader cancellation, child lifetime, `wired=True`, watcher start, and
  readiness publication keep their existing owners and precedence.
- No dependency is added. If implementation appears to require one, stop and
  ask the owner under Golden Rule 9.
- Preserve all unrelated worktree changes. Do not reformat untouched code or
  stage by directory.

Hidden coupling: during attach, provider output and human input meet at the
physical terminal emulator. `_TerminalResponder` treats keyboard mode sets as
no-reply output, while the host terminal applies them and changes subsequent
input encoding. The matcher therefore cannot assume raw mode implies legacy
key encoding. Both platform bridges share the matcher, so a parser change is
cross-platform even though the live report occurred on macOS.

Failure policy: malformed or unsupported input is ordinary provider input and
must be forwarded, not raised as an adapter failure. Existing OS read/write,
lease restoration, and cleanup failures retain their current fatal/best-effort
classification.

## Task Breakdown

1. **Independent review of this plan and exact spec delta.**
   - Reviewer: Claude, using the repository's verified read-only review
     invocation and no implementation tools.
   - Review the plan, [SUM-7.4], `_pty.py`, both platform attach loops, and the
     named tests. Require a PASS/BLOCKED verdict and explicit P1/P2 findings.
   - Stop if the reviewer cannot implement the streaming/forwarding semantics
     without guessing, disputes the modifier/event rules, or finds the proposed
     `ESC` exception too broad. Revise and run a scoped second review.
   - Done signal: all findings are dispositioned in the Review Log and the
     final verdict is PASS.

2. **Promote the reviewed spec delta before code.**
   - Files: `docs/specs/04-summon.md`, this plan.
   - Apply the exact [SUM-7.4] replacement and related-plan backlink using
     strategy A. Run documentation/reference gates and record the promotion
     baseline identifier.
   - Stop if the promoted wording requires recognizing a protocol form not
     covered by a finite grammar or contradicts terminal byte transparency
     elsewhere in [SUM-7.4]. Record a deviation before revising the spec.
   - Done signal: promoted text matches the reviewed delta and doc gates pass.

3. **Add failing tests before production changes.**
   - Files: `extensions/taut_summon/tests/test_pty_adapter.py`,
     `extensions/taut_summon/tests/test_pty_windows.py`.
   - Add a table-driven matcher contract covering the enumerable acceptance
     and rejection matrix below. Add one POSIX real-PTY attach test with split
     CSI-u input and one Windows `_AttachSession` test using existing fake
     handles/chunks. Drive enhanced-prefix expiry with an injected monotonic
     clock or explicit deadlines, not sleeps. Prove the platform waits receive
     the matcher's remaining deadline, ready input wins at an equal deadline,
     and unrelated wakeups do not reset it. The red run must fail because
     the enhanced chord is forwarded or attach does not return `detached`.
   - What stays real: `_DetachChordMatcher`, POSIX `pty.openpty()` and attach
     loop, and the Windows attach-session bridge. OS-only Win32 calls may use
     the established fake API; do not mock the matcher or replace either
     bridge with a direct return value.
   - Stop if the test requires provider-name detection, terminal-name
     detection, wall-clock sleeps, or changes to driver lifecycle.
   - Done signal: the new focused tests fail for the intended missing behavior,
     while existing legacy detach tests still pass.

4. **Implement one bounded semantic detach matcher.**
   - Files: `extensions/taut_summon/taut_summon/_pty.py`,
     `extensions/taut_summon/taut_summon/_pty_posix.py`, and
     `extensions/taut_summon/taut_summon/_pty_windows.py`.
   - Extend the existing matcher rather than adding a sibling parser. Retain
     original byte slices, parse incrementally across `feed()` calls, cap
     candidate retention, and use a small internal event classification such
     as detach atom / same-key release / other. Keep the public return shape
     `(forward_bytes, detached)` unchanged for input. Add one narrow matcher
     deadline query and expiry operation that returns pending bytes. Compose
     that deadline into each platform bridge's existing source wait rather
     than sampling it through an independent poll: use the earlier of the
     existing lifecycle bound and the matcher deadline. On a return where
     input is ready and the deadline is due, feed the input first and expire
     only if the candidate remains pending. Check expiry after all other ready
     sources so continuously readable provider output cannot starve it. Use
     100 ms as the ambiguity interval; add no new thread, loop, or notification
     path to the foreground broker reactor.
   - The grammar must accept decimal fields only within the cap and implement
     the exact Kitty and xterm productions and protocol-specific modifier
     tables in [SUM-7.4]. The required regression fixture is
     `b"\x1b[92::92;5:1u"` twice, matching Codex's combination of
     disambiguation, alternate-key, and event-type reporting. Also cover the
     no-event-type `b"\x1b[92::92;5u"` form and event values 2 and 3. Reject
     an associated-text field and base-layout-only identity rather than using
     either as authority for the chord.
   - Stop and re-evaluate if platform changes extend beyond calling the shared
     expiry operation from existing wait branches, if buffer ownership becomes
     duplicated, if the parser starts decoding unrelated keys for consumers,
     or if complexity pressure suggests a general terminal library.
   - Done signal: focused matcher and platform attach tests pass; all legacy
     matcher behavior remains green.

5. **Close documentation and traceability.**
   - Files: `docs/implementation/05-taut-summon-architecture.md`,
     `extensions/taut_summon/README.md`, `docs/specs/04-summon.md`, this plan,
     and `docs/plans/README.md`.
   - Explain the child-output/host-input mode coupling, the narrow semantic
     exception to ESC transparency, the shared parser owner, and the bounded
     exact-forwarding rule. Add reciprocal implementation/test evidence to the
     promoted spec only with the code slice.
   - Evaluate whether the incident yields a durable lesson: “raw tty mode does
     not freeze terminal key encoding; a child may negotiate it through
     output.” Add it to `docs/lessons.md` only if final review shows it applies
     beyond this already-documented Summon boundary.
   - Stop if documentation would need to claim support beyond the two named
     enhanced protocols or beyond the tested modifier/event matrix.
   - Done signal: minimum traceability chain is complete and documentation
     gates pass without disturbing the owner's existing doc changes.

6. **Run full verification and independent completed-work review.**
   - Run targeted tests first, then the complete Summon unit/process suites,
     Ruff, formatting, mypy, doc/reference/index gates, and `git diff --check`.
   - Use a different-family read-only reviewer on the final diff. Require the
     reviewer to inspect parser bounds, exact-byte forwarding, event ordering,
     POSIX/Windows reuse, spec compliance, and test firing strength.
   - Stop on any un-dispositioned P1/P2 finding, failed gate, platform path that
     bypasses the shared matcher, or mismatch between promoted spec and code.
   - Done signal: all gates pass and review findings are resolved or explicitly
     rejected with evidence.

## Enumerable Acceptance Matrix

Each row requires a firing test; parameterization is allowed only when every
row is named in test IDs and removing support for that row fails the suite.

| ID | Input/event | Expected result |
|----|-------------|-----------------|
| D1 | two legacy `0x1c` atoms, including split reads | detach; forward nothing |
| D2 | `ESC [ 92 :: 92 ; 5 u` twice, including every split boundary | detach after two atoms; forward nothing |
| D3 | `ESC [ 92 :: 92 ; 5 : 1 u` twice, plus accepted Kitty modifier values `6`, `69`, `70`, `133`, `134`, `197`, and `198` with grammar-valid shifted fields | detach after two atoms |
| D4 | Kitty repeat as the second atom | detach, matching legacy repeat behavior |
| D5 | Kitty same-key release between two atoms | release does not count or break; successful chord forwards nothing |
| D6 | `ESC [ 124 : 92 ; 6 u` twice, so the Kitty shifted-key subfield identifies code point 92 with encoded Control+Shift modifier `6` | detach after two atoms |
| D7 | two xterm `CSI 27;5;92~` atoms | detach; forward nothing |
| D8 | mixed legacy and enhanced atoms, in either order | detach; forward nothing |
| F1 | first detach atom followed by ordinary text | forward both exactly once and in order |
| F2 | first Kitty press/release followed by unrelated input | forward press, release, and input exactly once and in order |
| F3 | unrelated Kitty or xterm key | forward unchanged |
| F4 | base-layout-only backslash identity | forward unchanged |
| F5 | missing Control; each protocol's forbidden Alt/Super-or-Meta/Hyper/Meta/lock/unknown bit; or a shifted field without Shift | forward unchanged |
| F6 | Kitty release alone or unknown event type | forward unchanged; do not alter chord state |
| F7 | malformed numeric fields, empty fields outside Kitty's permitted shifted slot, delimiters, final byte, associated-text field, or extra fields | forward unchanged |
| F8 | incomplete supported prefix split across reads then completed | buffer boundedly, then classify correctly |
| F9 | incomplete or overlong prefix exceeding the cap | flush unchanged with linear work and bounded retained bytes |
| F10 | Escape, arrows, function keys, paste delimiters, mouse/focus input | forward unchanged without waiting beyond the finite prefix decision |
| F11 | non-default internal chord | preserve byte-exact matching; no enhanced aliases |
| F12 | lone `ESC` or stalled supported prefix, including continuously readable provider output, spurious wakes, and empty waits | the owning source wait wakes at the 100 ms ambiguity deadline and flushes unchanged; unrelated activity neither resets nor starves it |
| F13 | final continuation becomes ready exactly when the ambiguity deadline is due | serialized input owner feeds the ready bytes first; expiry applies only if the candidate remains incomplete |
| F14 | one accepted detach atom followed by a stalled enhanced-key prefix | expiry forwards the first atom and stalled prefix exactly once and in order, then clears chord state |
| P1 | POSIX real-PTY bridge receives an enhanced chord | returns `detached`, restores tty, and does not deliver chord bytes to child |
| W1 | Windows attach-session bridge receives an enhanced chord | returns `detached`, runs existing cleanup, and does not deliver chord bytes to ConPTY |

## Testing Plan

Red-green TDD is mandatory. The substitute-proof exception does not apply
because the defect is deterministic at the shared byte-stream boundary.

Targeted red/green commands:

```bash
uv run --no-sync --project extensions/taut_summon --extra dev pytest \
  extensions/taut_summon/tests/test_pty_adapter.py \
  extensions/taut_summon/tests/test_pty_windows.py -n0
```

Static checks for the changed package:

```bash
uv run --no-sync ruff check \
  extensions/taut_summon/taut_summon/_pty.py \
  extensions/taut_summon/tests/test_pty_adapter.py \
  extensions/taut_summon/tests/test_pty_windows.py
uv run --no-sync ruff format --check \
  extensions/taut_summon/taut_summon/_pty.py \
  extensions/taut_summon/tests/test_pty_adapter.py \
  extensions/taut_summon/tests/test_pty_windows.py
uv run --no-sync --extra dev mypy \
  extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests \
  extensions/taut_summon/tests/conftest.py --config-file pyproject.toml
```

Full Summon behavior gates:

```bash
uv run --no-sync --project extensions/taut_summon --extra dev pytest \
  extensions/taut_summon/tests -m 'not xdist_group' -n auto --dist load
uv run --no-sync --project extensions/taut_summon --extra dev pytest \
  extensions/taut_summon/tests \
  -m 'xdist_group and not requires_live_harness and not requires_local_llm' \
  -n auto --dist load
```

Documentation and repository gates:

```bash
uv run --no-sync pytest tests/test_docs_references.py -n0
uv run --no-sync bin/check-doc-paths
uv run --no-sync bin/check-plan-status-index
uv run --no-sync bin/check-dom15-fixtures
git diff --check
```

Manual acceptance after automated proof, on one available Kitty-capable
terminal but without terminal-specific configuration:

1. Run `taut summon --attach NAME` with a provider that enables enhanced
   keyboard reporting.
2. Wait until the provider TUI is fully initialized and accepts shortcuts.
3. Press Control-Backslash twice.
4. Observe terminal restoration, the foreground Summon readiness line, and a
   live `taut-summon status` row. Confirm the provider remains running and the
   listener starts.

This observation validates integration but does not replace the protocol and
platform tests. A second terminal brand is useful confidence, not a completion
gate; the implementation is protocol-based rather than terminal-branded.

## Hardening and Operational Notes

### Rollback and rollout

The change is local and backward-compatible: old terminals continue to emit
the legacy byte, while enhanced terminals gain aliases. Roll out code, tests,
and docs together. Rollback is a normal revert of the matcher/spec/docs delta;
there is no storage migration, persisted state change, or mixed-version
coordination. A rollback restores the known defect on enhanced protocols but
does not corrupt sessions.

### One-way doors and cleanup

There is no one-way door. Do not alter the `wired` schema, child process
lifecycle, or host lease ownership. The reset blast changes only by the
append-only `ESC[>4m` recorded in the Deviation Log. Detach must still traverse the
existing cleanup path on both platforms.

### Post-rollout success signals

- Enhanced-protocol attach detaches on the documented chord after provider
  initialization.
- The provider remains live and Summon publishes readiness after detach.
- Ordinary provider shortcuts, arrows, paste, and text show no byte loss,
  duplication, or delay regression.
- No new attach failure, tty restoration, or ConPTY cleanup errors appear.

### Residual risk

The plan covers the two enhanced encodings evidenced by current provider
implementations. The `ESC` gate trusts that a terminal which ignores an
enhanced-mode request also never sends enhanced keys; a terminal that ignores
the request costs those users only the bounded Escape hold. With
`modifyOtherKeys` active, bare Escape is still a legacy `ESC`, so Escape-then-key
can still coalesce within 100 ms while that mode is on. A future keyboard protocol with a different grammar will
still require explicit support. The bounded exact-forwarding rule makes that
failure visible as the current behavior rather than guessing or swallowing
input.

## Independent Review Loop

Plan review occurs before spec promotion or implementation. The review unit is
this plan and its proposed [SUM-7.4] delta at baseline
`1f3b6c6bf70c55725df1268a19066fb06e33818f`. Accepted risks: support is finite
to legacy, Kitty CSI-u, and xterm `modifyOtherKeys`; manual observation is one
terminal/provider pairing after protocol-level automated proof. Pre-existing
terminal-emulation concerns are observations unless this change worsens them.

Review stance: find incorrect protocol grammar, unsafe interception,
unbounded/ambiguous buffering, byte-order loss, weak firing tests, duplicated
platform logic, lifecycle drift, and needless abstraction. Prefer removing
work. Findings use P1/P2/P3/nit severity with suggested dispositions and a
PASS/BLOCKED verdict. Scope expansions belong in a separate non-actionable
observations section.

After implementation, review the exact changed-file diff against the promoted
spec and acceptance matrix. A round-2 review is scoped only to accepted
findings and their fixes. Every finding receives an accepted, rejected, or
out-of-scope disposition below.

## Out of Scope

- Making the detach chord configurable or changing its visible key choice.
- Provider-specific or terminal-specific environment flags and configuration.
- A general keyboard-event API for Taut or a complete Kitty/xterm parser.
- Parsing PTY output as agent speech or changing detached terminal-query
  handling.
- Changes to attach acknowledgement, setup recovery, `wired` persistence,
  driver restart policy, watcher startup, or process cleanup.
- Supporting unobserved keyboard protocols without a concrete grammar and
  firing fixture.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SUM-7.4] | Hold any `ESC` prefix up to 100 ms for the chord decision. | The hold is armed only while forwarded provider output leaves Kitty flags or `modifyOtherKeys` active; unarmed, `ESC` forwards immediately. | R-01: the unconditional hold delayed Escape and coalesced Escape-then-key into an Alt-key write in the default legacy mode, for every user. | Promoted into [SUM-7.4] in this change. |
| [SUM-7.4] | A failed candidate forwards all held bytes. | An `ESC` that ends a failed candidate starts a new candidate. | R-02: `Esc` then an enhanced `Ctrl-\` within one read lost a chord atom. | Promoted into [SUM-7.4] in this change. |
| [SUM-7.4] reset blast | Reset blast unchanged. | POSIX and Windows clear the bounded Kitty stack on the current screen, leave alternate mode, clear the main-screen stack, then reset `modifyOtherKeys`. | R-03: enhanced keyboard state is screen-specific and stack-based; leaving any push set makes the next attach's fresh tracker disagree with the physical terminal and can make the detach chord unreachable. | Promoted into [SUM-7.4] in this change. |

## Review Log

| Date | Reviewer | Baseline / scope | Finding | Disposition |
|------|----------|------------------|---------|-------------|
| 2026-09-23 | Claude Opus 4.6, read-only plan review; exit 0, `success` / `end_turn`, `terminal_reason=completed`, `is_error=false`; PASS | `1f3b6c6`; this plan, exact proposed [SUM-7.4] delta, shared matcher, platform bridges, and named tests | F-01 (P3): xterm grammar was implicit in normative text. | Accepted: proposed text now names exact `CSI 27;<modifier>;92~` grammar. |
| 2026-09-23 | same | same | F-02 (P3): “same key” release identity was undefined. | Accepted: proposed text now applies the same logical identity/modifier rules and event type 3. |
| 2026-09-23 | same | same | F-03 (nit): no mixed legacy/enhanced atom row. | Accepted: D8 requires both mixed orders. |
| 2026-09-23 | same | same | F-04 (P3): “complete encodings” could obscure necessary prefix buffering. | Accepted: proposed text explicitly permits only bounded prefix holding and distinguishes it from interception. |
| 2026-09-23 | same | same | F-05 (nit): diagnosis/gate/coupling prose is partly repetitive. | Rejected: each occurrence serves a separate zero-context role (evidence, comprehension gate, invariant); no implementation scope results. |
| 2026-09-23 | same | same | F-06 (P2): an `ESC` prefix could be buffered indefinitely without an expiry path. | Accepted: spec, invariants, tasks, and F12 now require a 100 ms owned deadline composed into each platform's existing source wait and driven deterministically in tests. |
| 2026-09-23 | Claude Opus 4.6, read-only scoped round 2; exit 0, `success` / `end_turn`, `terminal_reason=completed`, `is_error=false`; PASS | Accepted findings F-01, F-02, F-03, F-04, and F-06 only | Verified every accepted fix, continuous-output starvation prevention, shared cross-platform expiry ownership, and deterministic testability; found no new defect. | Closed: PASS. F-05 was outside the round-2 scope as required. |
| 2026-09-23 | Owner-supplied independent agent review | Plan after round 2, focused on live failure coverage | F-07 (P2): the prose named Kitty semantic fields but neither a finite colon-field grammar nor the alternate-key/event-type bytes Codex requests, so simpler tests could pass while the live failure remained. Modifier bit meanings were also implicit and xterm was incorrectly told to share Kitty's rule. | Accepted: proposed [SUM-7.4] now contains finite protocol-specific productions and modifier tables; D2/D3 require `CSI 92::92;5u` and `CSI 92::92;5:1u`; task 4 requires event variants. |
| 2026-09-23 | Claude Opus 4.6, read-only deadline review; exit 0; PASS | Deadline/source-wait correction only | F-08 (P3): “expired prefix” could imply dropping the already-held first chord atom. | Accepted: normative text says all expired pending bytes, and F14 fires the mid-chord expiry path. |
| 2026-09-23 | same | same | F-09 (P3): no explicit firing row covered expiry after one recognized atom. | Accepted: F14 requires exact ordered forwarding and chord-state reset. |
| 2026-09-23 | Fresh-eyes scoped reviewer after different-family reviewers timed out; PASS | Corrected Kitty/xterm grammar, modifier arithmetic, and D2-D7/F3-F8 only | No P1/P2/P3/nit finding. Confirmed finite grammar, Codex alternate-key/event fixtures, Kitty accepted values `5,6,69,70,133,134,197,198`, xterm values `5,6`, and primary/shifted/base identity rules. | Closed: PASS. Fallback is disclosed because Claude and OS-sandboxed Grok produced no result before their review bounds. |
| 2026-09-23 | Fresh-eyes completed-work reviewer; initial verdict BLOCKED | Full implementation diff and D1-D8/F1-F14/P1/W1 firing map | F-IMPL-01 (P2): Windows timed expiry without a final queue-readiness check, so a continuation published at the boundary could lose input priority. | Accepted: the timeout path now performs `get_nowait()` before expiry; a deterministic bridge test publishes the continuation on that recheck and proves detach with no forwarding. |
| 2026-09-23 | same | same | F-IMPL-02 (P2): D2, F7, F9, F12, and F13 firing proofs were incomplete. | Accepted: both Kitty press forms split at every boundary; malformed grammar categories are enumerated; a 10,000-byte scan count proves bounded work; POSIX drives repeated provider-ready turns; Windows fires the deadline-boundary race. |
| 2026-09-23 | same | same | F-IMPL-03 (P3): continuation bytes slid the ambiguity deadline, permitting retention beyond 100 ms. | Accepted: the deadline is fixed when the initial `ESC` arrives; code, spec, implementation note, plan, and slow-byte test agree. |
| 2026-09-23 | Same reviewer, scoped round 2; PASS | F-IMPL-01 through F-IMPL-03 only | Confirmed both blockers and the P3 finding resolved; narrow matcher/bridge suite reported 60 passed and no new finding. | Closed: PASS. |
| 2026-09-23 | Owner-requested review of uncommitted implementation (Claude Opus 5.5) | Uncommitted diff on `c0a4616` | R-01 (P2): every bare `ESC` was held up to 100 ms and then written together with the next byte, even with no enhanced mode active; probe showed `Esc`, then `j` 40 ms later, forwarded as one `b"\x1bj"` write. | Accepted: hold gated on a per-attach keyboard-mode tracker; see Deviation Log. |
| 2026-09-23 | same | same | R-02 (P3): an `ESC` that ended a failed candidate was flushed instead of starting a new one. | Accepted: re-armed with its own deadline. |
| 2026-09-23 | same | same | R-03 (P3, pre-existing, raised in importance by this plan): reset blast lacked `ESC[>4m`. | Accepted: appended on both platforms. Observation only: Kitty pop after `?1049l` targets the main-screen stack; left unchanged because reordering risks leaving a main-screen push active. |
| 2026-09-23 | Codex independent final review | Final uncommitted implementation and R-01..R-03 follow-up | P2: POSIX popped Kitty only once after leaving alternate mode and Windows did not pop it, so nested or alternate-screen pushes could survive detach and make a later fresh tracker disagree with the physical terminal. P3: the POSIX bridge proof did not assert chord bytes stayed out of child input. | Accepted. Both reset blasts now clear the bounded active-screen stack, leave alternate modes, clear main, then reset `modifyOtherKeys`; tracker tests cover nested main/alternate pushes and Windows parity, and the real POSIX bridge asserts the child receives only ordinary input. Re-review PASS with no remaining finding. |

## Execution Log

| Date | Slice | Evidence / result |
|------|-------|-------------------|
| 2026-09-23 | Diagnosis | Live Summon owner remained on raw `/dev/ttys004`; Codex and Grok received Control-Backslash after enabling enhanced input. `_DetachChordMatcher` accepts only `b"\x1c\x1c"`, while both platform attach loops share it and forward mismatches. Root cause established before plan drafting: child output negotiates host key encoding across the transparent bridge. |
| 2026-09-23 | Plan review | Claude Opus 4.6 completed in 463 seconds with PASS and six non-blocking findings. F-01 through F-04 and F-06 were incorporated; F-05 was rejected with rationale in the Review Log. Local pre-review gates: plan-status index OK, 12 documentation-reference tests passed, 63-source/1410-claim doc-path check passed, and scoped `git diff --check` passed. |
| 2026-09-23 | Scoped review round 2 | Claude Opus 4.6 completed in 216 seconds with PASS. It verified all five accepted fixes, including the every-turn expiry check under continuously readable provider output, and found no new defect. |
| 2026-09-23 | Deadline ownership correction | Replaced poll-turn expiry wording with one matcher deadline composed into the existing POSIX `select()` and Windows input-queue waits. Ready input wins at an equal deadline; unrelated wakes cannot reset or starve it. Scoped Claude review passed and produced F-08/F-09, both incorporated. |
| 2026-09-23 | Wire-grammar correction | Owner-supplied independent review found that semantic field names did not guarantee support for Codex's colon-form bytes. Added exact Kitty/xterm productions, protocol-specific modifier tables, live alternate-key/event fixtures, and rejection rows. Claude and Grok follow-up invocations timed out without output; disclosed fresh-eyes fallback returned PASS with no findings. |
| 2026-09-23 | Spec promotion and red-green proof | Promoted [SUM-7.4] against `c0a4616e76e954e3f9fbea93fbf487c3ee660cbe`. The first matcher run failed 14 enhanced/deadline cases for the intended literal-only behavior; after implementation, the final focused matcher/platform selection passed 62 tests. |
| 2026-09-23 | Implementation | `_DetachChordMatcher` recognizes the reviewed Kitty/xterm forms only for the default chord, retains original bytes, caps individual sequences and total pending bytes, and exposes one fixed monotonic deadline. POSIX `select()` and Windows chunk waits compose that deadline without a new scheduler. Real POSIX and Windows-session tests prove shared use. |
| 2026-09-23 | Automated verification | Final gates: ordinary Summon suite `313 passed`; process-group Summon suite `340 passed, 9 skipped` for documented platform-only cases; mypy checked 49 files with no issues; Ruff check and format passed; 12 documentation-reference tests passed; doc paths passed for 63 sources/1414 claims; plan index, DOM-15 fixtures, and `git diff --check` passed. |
| 2026-09-23 | Completed-work review | Initial review blocked on F-IMPL-01/F-IMPL-02 and raised F-IMPL-03. All were accepted and fixed. Scoped round 2 returned PASS with no new finding. |
| 2026-09-23 | R-01..R-03 follow-up | Red first: the new and updated matcher, tracker, POSIX-wiring, and Windows tests failed on the missing `observe_output`/tracker, the immediate-`ESC` expectation, and the absent `ESC[>4m`. Green: `_KeyboardProtocolTracker` fed before each host write on both platforms; `_flush_failed_candidate` re-arms a terminating `ESC`; both resets append `ESC[>4m`. Real-PTY test now covers Kitty and `modifyOtherKeys` splits after the fake provider requests each mode. Full `extensions/taut_summon/tests` run: pytest exit 0 with only platform-only skips. Mypy under the release-gate invocation: summon 49 files and root 150 files, no issues. Ruff check and format passed. Plan index, `check-doc-paths` (63 sources/1414 claims), 12 documentation-reference tests, and `git diff --check` passed. |
| 2026-09-23 | Symmetric keyboard reset follow-up | Independent review found the reset did not retire nested, screen-specific Kitty state. Red: tracker models retained enhanced state under the old ordering. Green: shared bounded pop before alternate-screen exit and again on main, followed by xterm reset, passes on POSIX and Windows constants; real POSIX child input remains chord-free. Full Summon gates passed 313 non-group tests and 381 grouped tests with 7 platform-only skips. Scoped re-review PASS. |
| 2026-09-23 | Manual acceptance | Not run: this non-interactive implementation environment cannot generate a physical terminal's post-negotiation Control-Backslash event. The real PTY, deterministic protocol, and both platform bridge seams are covered; one live Kitty-capable terminal observation remains the explicit residual gate. |
| 2026-09-23 | 0.9.9 release disposition | The owner explicitly requested the coordinated release after the automated and independent-review gates. Proceed with the physical-terminal observation still recorded as residual risk; do not rewrite it as completed evidence. |
| 2026-09-24 | Automated host-terminal acceptance | The follow-on controlling-terminal plan added a test-owned POSIX shell session and drove the real root `taut summon` CLI through both legacy and negotiated Kitty chord bytes, direct termios restoration, out-of-band dismiss, shell return, fresh attach, and final provider retirement. The deterministic lane passed for both encodings and replaces the pending physical-observation gate by owner direction. Its explicitly selected real-provider variant was implemented but not executed in this run. |

## Completion Gate

Do not call this work complete until the promoted spec, implementation note,
README, matcher, POSIX proof, Windows proof, acceptance matrix, full Summon
gates, static checks, documentation gates, manual observation, and independent
completed-work review all agree. Record exact commands and observed results in
the Execution Log. If the user wants the implementation reviewed uncommitted,
report that state and changed files explicitly; do not claim the repository
definition-of-done commit gate has passed.
