# Summon Enhanced-Keyboard Detach Plan

Status: Draft — implementation is blocked until the independent plan and
proposed-spec review passes.

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

- [ ] Reproduce the defect as a failing shared-matcher test: two enhanced
  Control-Backslash events are forwarded instead of detaching.
- [ ] Recognize the detach chord independently of whether the host terminal
  emits legacy, Kitty CSI-u, or xterm `modifyOtherKeys` input.
- [ ] Preserve exact bytes and order for incomplete, malformed, unsupported,
  and non-detach input, including a failed chord after one candidate event.
- [ ] Prove the shared matcher through both POSIX PTY and Windows ConPTY attach
  paths without provider-name or terminal-name branches.
- [ ] Align the Summon spec, implementation note, extension README, code, and
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
- Promotion baseline identifier: pending the spec-promotion slice. Record the
  commit SHA if committed, otherwise the baseline SHA plus the exact worktree
  diff for `docs/specs/04-summon.md`.

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
> release events for the same key may occur between atoms but do not count or
> break the chord. A Kitty event identifies the logical backslash through its
> primary or shifted key code, requires Control, permits Shift and lock-state
> modifiers, and rejects Alt, Super, Hyper, Meta, unknown modifier bits, and
> unknown event types. A base-layout key code alone does not identify the
> chord. The xterm form requires key code 92 and the same modifier rule and
> carries no event type.
>
> The matcher buffers only a bounded possible chord or supported enhanced-key
> sequence, detaches only after two recognized atoms, and otherwise forwards
> every original byte once and in order. Split sequences are recognized across
> reads. Incomplete, malformed, overlong, unsupported, unrelated, or failed
> chord input is not normalized or dropped. Except for complete encodings of
> the reserved detach key while matching this chord, `ESC`-prefixed input,
> Escape, arrows, function keys, paste data, and provider shortcuts pass
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
- Two qualifying press/repeat atoms detach. Same-key Kitty release events may
  appear between them, are held with the pending chord, and are discarded on
  successful detach; on failure, the press/release bytes are forwarded in
  original order. Release alone never starts or completes a chord.
- For Kitty identity, primary or shifted code point 92 is logical backslash;
  base-layout-only 92 is insufficient. Control is required. Shift and
  Caps/Num Lock bits are tolerated; Alt, Super, Hyper, Meta, unknown bits,
  invalid numeric fields, and unknown event types are not detach input.
- For xterm `modifyOtherKeys`, accept only the complete
  `CSI 27;<modifier>;92~` grammar with the same modifier rule.
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
     handles/chunks. The red run must fail because the enhanced chord is
     forwarded or attach does not return `detached`.
   - What stays real: `_DetachChordMatcher`, POSIX `pty.openpty()` and attach
     loop, and the Windows attach-session bridge. OS-only Win32 calls may use
     the established fake API; do not mock the matcher or replace either
     bridge with a direct return value.
   - Stop if the test requires provider-name detection, terminal-name
     detection, wall-clock sleeps, or changes to driver lifecycle.
   - Done signal: the new focused tests fail for the intended missing behavior,
     while existing legacy detach tests still pass.

4. **Implement one bounded semantic detach matcher.**
   - File: `extensions/taut_summon/taut_summon/_pty.py`.
   - Extend the existing matcher rather than adding a sibling parser. Retain
     original byte slices, parse incrementally across `feed()` calls, cap
     candidate retention, and use a small internal event classification such
     as detach atom / same-key release / other. Keep the public return shape
     `(forward_bytes, detached)` unchanged.
   - The grammar must accept decimal fields only within the cap; recognize
     Kitty primary/shifted identity and modifier/event fields, plus exact xterm
     `modifyOtherKeys`. It must not treat the Kitty associated-text field or
     base-layout-only identity as authority for the chord.
   - Stop and re-evaluate if correct forwarding needs changes in either
     platform loop, if buffer ownership becomes duplicated, if the parser
     starts decoding unrelated keys for consumers, or if complexity pressure
     suggests a general terminal library.
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
| D2 | two Kitty `CSI 92;5u` presses | detach; forward nothing |
| D3 | Kitty press forms with explicit press event and permitted lock bits | detach after two atoms |
| D4 | Kitty repeat as the second atom | detach, matching legacy repeat behavior |
| D5 | Kitty same-key release between two atoms | release does not count or break; successful chord forwards nothing |
| D6 | Kitty shifted-key field identifies code point 92 with Control+Shift | detach after two atoms |
| D7 | two xterm `CSI 27;5;92~` atoms | detach; forward nothing |
| F1 | first detach atom followed by ordinary text | forward both exactly once and in order |
| F2 | first Kitty press/release followed by unrelated input | forward press, release, and input exactly once and in order |
| F3 | unrelated Kitty or xterm key | forward unchanged |
| F4 | base-layout-only backslash identity | forward unchanged |
| F5 | missing Control or forbidden Alt/Super/Hyper/Meta/unknown modifier | forward unchanged |
| F6 | Kitty release alone or unknown event type | forward unchanged; do not alter chord state |
| F7 | malformed numeric fields, delimiters, final byte, or extra fields | forward unchanged |
| F8 | incomplete supported prefix split across reads then completed | buffer boundedly, then classify correctly |
| F9 | incomplete or overlong prefix exceeding the cap | flush unchanged with linear work and bounded retained bytes |
| F10 | Escape, arrows, function keys, paste delimiters, mouse/focus input | forward unchanged without waiting beyond the finite prefix decision |
| F11 | non-default internal chord | preserve byte-exact matching; no enhanced aliases |
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
lifecycle, reset blast, or host lease ownership. Detach must still traverse the
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
implementations. A future keyboard protocol with a different grammar will
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

## Review Log

| Date | Reviewer | Baseline / scope | Finding | Disposition |
|------|----------|------------------|---------|-------------|

## Execution Log

| Date | Slice | Evidence / result |
|------|-------|-------------------|
| 2026-09-23 | Diagnosis | Live Summon owner remained on raw `/dev/ttys004`; Codex and Grok received Control-Backslash after enabling enhanced input. `_DetachChordMatcher` accepts only `b"\x1c\x1c"`, while both platform attach loops share it and forward mismatches. Root cause fixed before plan drafting: child output negotiates host key encoding across the transparent bridge. |

## Completion Gate

Do not call this work complete until the promoted spec, implementation note,
README, matcher, POSIX proof, Windows proof, acceptance matrix, full Summon
gates, static checks, documentation gates, manual observation, and independent
completed-work review all agree. Record exact commands and observed results in
the Execution Log. If the user wants the implementation reviewed uncommitted,
report that state and changed files explicitly; do not claim the repository
definition-of-done commit gate has passed.
