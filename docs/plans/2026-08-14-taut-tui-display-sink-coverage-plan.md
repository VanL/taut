# Taut TUI Display-Sink Coverage Plan

Date: 2026-08-14

Status: completed

Class: 3. This is a security-relevant, behavior-preserving ownership refactor
across the TUI composition root, modal screens, widget adapters, and their
tests. The active terminal-text contract supplies intent, no public contract
or persistence/async boundary changes, and no [DOM-5] risky trigger fires.

Plan type: implementation against the active specification; no spec revision.

## Goal

Close the TUI terminal-escape call-site coverage gap. Dynamic display content
must be escaped by extension-owned sink widgets or the application-owned toast
boundary when content is installed or updated, so a new transcript, navigation,
inspector, placeholder, selector, modal, or notification render path cannot
silently bypass terminal-control escaping by omitting an `_display_text` call.

## Source Documents

- `docs/program-theory.md` [THEORY-3], [THEORY-4]
- `docs/specs/10-taut-tui.md` [TUI-12.2], [TUI-13.1]
- `docs/specs/02-taut-core.md` [TAUT-6.4]
- `docs/implementation/12-taut-tui.md`, especially the terminal presentation
  boundary and verification section
- `docs/agent-context/engineering-principles.md` §12 enumerable contracts
- `docs/agent-context/runbooks/testing-patterns.md`, Patterns 5–6
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- the reviewer finding supplied on 2026-08-14: the existing real-PTY OSC-8
  proof covers one transcript-shaped path, while other sinks depend on every
  caller remembering `_display_text`

## Spec Baseline

- `7ecd6c1` — active [TUI-12.2] and [TUI-13.1] contract at plan authoring.
- This plan changes ownership and proof, not intended behavior. No promotion
  slice is required.

## Context and Key Files

| File | Current ownership and gap |
|------|---------------------------|
| `extensions/taut_tui/taut_tui/widgets.py` | Owns only option-list pointer semantics. It is the narrow place to add fail-closed Textual display adapters and protected already-escaped values. |
| `extensions/taut_tui/taut_tui/app.py` | Manually calls `_display_text` for transcript rows, navigation, status, target title, inspector content, and composer placeholder. |
| `extensions/taut_tui/taut_tui/screens.py` | Defines a second `_display_text` wrapper and manually escapes modal errors, prompts, option rows, search results, and provider labels. |
| `extensions/taut_tui/taut_tui/summon.py` | `SummonLogBridge` escapes before callback delivery; the sink boundary must recognize that protected one-pass result rather than applying project regexes twice. |
| `extensions/taut_tui/tests/test_tui_textual_contract.py` | Proves one manually escaped `Static` path through a real PTY; it does not prove the production sink types apply the policy themselves. |
| `extensions/taut_tui/tests/test_tui_app.py`, `test_tui_screens.py` | Exercise the production app and modal surfaces through Textual's real pilot and are the behavior-level homes for representative dynamic values. |

Comprehension gate before editing:

1. What is the failure mode? Expected answer: a new display sink can render
   raw dynamic text if its caller omits `_display_text`; consolidating duplicate
   wrappers does not prevent that omission.
2. Where should the invariant live? Expected answer: in extension-owned widget
   adapters at content installation/update, plus a structural inventory that
   prevents production TUI modules from reintroducing raw text widgets.
3. What must remain real? Expected answer: the terminal proof must launch
   Textual under a real PTY; production app/screen tests must use real widgets,
   not mocks of Rich, Textual rendering, or `escape_terminal_text`.

Recorded answers: all three match the expected answers above.

## Invariants and Constraints

- Every production TUI sink that can contain core, extension, diagnostic,
  target, path, or message text escapes at the widget boundary on both initial
  content and later updates. `TautApp.notify()` owns the same rule for Textual
  toasts, including title, message, and `markup=False`.
- Rich styling used for message authors, timestamps, and inspector emphasis
  survives escaping. Raw `rich.Text` is rejected because Rich can discard BEL
  before a sink sees it. A protected factory escapes semantic string segments
  before styling and is the only styled-text input accepted by owned sinks.
- Structural content such as newlines remains structural exactly as today.
  Generated escape notation must not be treated as Rich markup.
- Inputs escape display-only placeholders, never editable values or submitted
  domain data. Select display labels are escaped without changing their values.
- `TautOptionList` retains its pointer-chain behavior and option ids/disabled
  state. Constructor/add/replace-by-id/replace-by-index paths all escape. Safety
  wrapping must not create a second option-list implementation.
- `TautSelect` escapes both constructor and `set_options()` labels. Unsupported
  renderable types fail closed instead of passing through on trust.
- Checkbox label assignment and Select prompt assignment escape at their
  reactive/property boundaries. Production tooltip construction or assignment
  is structurally rejected until an owned tooltip adapter and firing test exist.
- Summon log escaping produces a protected already-safe string; widget and
  toast sinks recognize it and do not rescan generated escape notation under
  project regex policy.
- The raw Summon terminal lease remains byte-transparent and outside widget
  rendering. No escaping moves into that lease.
- No new dependency, public API, spec behavior, or unrelated visual redesign is
  authorized. Existing user changes in the worktree must remain untouched.
- Rollback is one coherent extension-local slice: revert widget adapters,
  production adoption, tests, and this implementation-note update together.
  There is no rollout order or one-way door.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Dependency-Ordered Tasks

### Slice 1: failing sink-boundary proof

1. Add one focused production-widget test that sends OSC-8/CSI-bearing strings
   through initial and update paths for static text, protected styled text,
   `OptionList.add_option`, `add_options`, `set_options`,
   `replace_option_prompt`, and `replace_option_prompt_at_index`; input
   placeholder initialization/assignment; and select constructor/`set_options`
   labels, checkbox label assignment, and Select prompt assignment. Assert
   literal escaped text, preserved styles/values,
   rejection of raw Rich/unsupported visuals, and absence of raw controls.
2. Add a structural inventory test over every production module in
   `extensions/taut_tui/taut_tui/` recursively except the exact owned
   `taut_tui/widgets.py` path. Reject direct and qualified raw Textual widget
   imports (including submodules), raw Rich `Text`, local
   `_display_text`/`escape_terminal_text`, and tooltip construction/assignment;
   allow only Textual's data-only `Option` import. Require owned adapters and
   the application-owned `notify()` override for every production display sink.
3. Run only those tests and record RED. Stop if the test cannot fail against
   the current call-site implementation without asserting private framework
   storage; revise the public observable seam instead.

### Slice 2: widget ownership and production adoption

1. Add one shared newline-preserving display conversion in `widgets.py`.
2. Add small extension-owned adapters for each production dynamic-text sink,
   a protected already-safe string type for one-pass producers, and a protected
   styled-text factory that escapes each semantic segment before Rich sees it.
   They must escape every public insertion/mutation path, reject unsupported
   visuals, and preserve styles, option metadata, placeholder/domain separation,
   and select values.
3. Replace raw sink construction in `app.py` and `screens.py`; remove manual
   `_display_text` calls and both local wrappers. Override `TautApp.notify()` to
   escape message/title and disable markup. Move `SummonLogBridge` to the
   protected already-safe result. Keep call sites responsible only for semantic
   composition and styling.
4. Run the Slice 1 tests to GREEN, then the neighboring app, screen, chat, and
   Textual contract tests. Stop if visual styles, selection ids, editable input
   values, or pointer activation change.

### Slice 3: real-terminal and documentation reconciliation

1. Rewrite the real-PTY OSC-8 probe to exercise a production-owned sink without
   importing or calling an escape helper at the call site. Cover at least one
   initial render and one post-mount update in the child process.
2. Add a project-regex test over the real `SummonLogBridge` to
   `TautApp._apply_summon_log` to inspector path, proving protected escape
   notation survives semantic composition without a second scan.
3. Update `docs/implementation/12-taut-tui.md` to name widget-owned escaping and
   the structural inventory; add nonnormative Related Plans backlinks to that
   note and `docs/specs/10-taut-tui.md`; add [TUI-12.2]/[TUI-13.1] to the
   Textual-contract test header. Do not strengthen [TUI-12.2]; this change makes
   the existing claim executable.
4. Run focused PTY, all TUI tests, Ruff format/check, mypy, documentation/path,
   plan-index, and diff gates. Record exact observed results.
5. Request an independent completed-work review focused on missed raw sinks,
   protected Rich style preservation, one-pass escaping, and whether the structural gate
   fires on a realistic new sink. Address or explicitly rebut each finding.

## Testing and Verification

Red-green tests use public widget content/rendering and Textual's real pilot.
No mock may replace `escape_terminal_text`, Rich `Text`, Textual widgets, or the
PTY byte stream.

Required commands:

```text
uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests/test_tui_textual_contract.py extensions/taut_tui/tests/test_tui_app.py extensions/taut_tui/tests/test_tui_screens.py
uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests/test_tui_*.py
uv run --project extensions/taut_tui --extra dev --locked ruff format --check extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev --locked ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev --locked mypy --config-file extensions/taut_tui/pyproject.toml extensions/taut_tui/taut_tui extensions/taut_tui/tests
bin/check-plan-status-index
uv run bin/check-doc-paths
uv run --extra dev pytest -n 0 tests/test_docs_references.py
git diff --check
```

## Independent Review Loop

- Plan review: verify every named file/symbol exists, the adapters cover all
  current dynamic sink families, and the tests fail for omission rather than
  only for a broken escape algorithm.
- Completed-work review: inspect the diff and rerun or inspect the structural
  inventory plus PTY proof. Verdict must be `no blocker` before closeout.
- Findings are recorded below with disposition. The author owns all edits.

## Review Log

| Round | Reviewer | Finding | Disposition |
|-------|----------|---------|-------------|
| 1 | independent plan reviewer | BLOCKED: toast diagnostics were outside widget ownership; the structural scan was module/import/sink-incomplete; option mutations were not enumerated; Summon logs risked a project-regex second pass; spec/test/implementation backlinks were incomplete. | Accepted. Added the `TautApp.notify` boundary; package-wide direct/qualified sink inventory and owned Button/Label/Checkbox adapters; exact OptionList/Select mutation list and firing tests; protected factory-only escaped string and styled text values with unsupported-visual rejection; Summon bridge one-pass marker; and explicit traceability tasks. Re-review required. |
| 2 | same independent reviewer | BLOCKED: flat-only scan and `from textual import widgets` bypass; checkbox-label and Select-prompt mutations unsafe; tooltip unowned; Summon interpolation stripped the protected type and the one-pass test skipped the real app path. | Accepted. Made the scan recursive and import-form complete; added checkbox property and Select reactive validation plus firing tests; structurally prohibited tooltips; composed Summon logs with protected styled segments; replaced the direct-widget one-pass check with bridge-to-app-to-inspector project-policy proof. Re-review required. |
| 3 | same independent reviewer | BLOCKED: recursion excluded any nested file named `widgets.py`; Textual widget submodule imports bypassed exact-module matching; plan still described raw fixed-label exceptions that no longer exist. Behavior probes otherwise passed. | Accepted. Exempted only the exact owner path, rejected `textual.widgets` and all submodule import forms while allowing only data-only `Option`, and aligned the plan with owned adapters plus tooltip prohibition. Re-review required. |
| 4 | same independent reviewer | PASS: all prior plan findings resolved; focused behavior, mypy, and Ruff evidence passed. Residual reflection-built imports are outside the cheap structural gate and nonblocking. | Accepted. Plan cleared for final completed-work review. |
| 5 | same independent reviewer | Completed-work review found no code or security blocker. One closeout-doc blocker: the Implementation Log froze a transient concurrent-work failure that no longer reproduced. | Accepted. Replaced the transient claim with stable full-suite and display-slice evidence. The retained-Textual private checkbox label seam remains an explicit nonblocking compatibility residual with a firing test. |

## Implementation Log

| Slice | RED evidence | GREEN / verification evidence | Residual risk |
|-------|--------------|-------------------------------|---------------|
| 1 | `pytest -k 'owned_display_sinks or cannot_bypass'` failed twice: production imported raw `Input`/`OptionList`/`Static`, and the owned sink classes did not exist. | Structural and owned-sink tests now pass, including all option mutations, placeholder/value separation, styled content, Button/Label/Checkbox, Select labels/prompts, toast ownership, unsupported visuals, and tooltip prohibition. | Dynamic/reflection-built imports are not statically enumerable. |
| 2 | The first styled-content attempt exposed Rich dropping BEL before sink ownership; the first one-pass attempt exposed protected Summon text losing its marker during app interpolation. | Protected segment-first styling and `SummonLogBridge` marker composition pass under a project regex that would visibly alter a second scan. App/screen/Textual focused suite passes. | Protected types are process-local presentation values, not an authorization boundary. |
| 3 | The original PTY child imported and called `_display_text`, proving only caller discipline. | Production-owned initial/update PTY probe and the full TUI suite passed during final independent display-slice review; the current display-owned Textual/app/screen/Summon/chat suites pass; Ruff and mypy over the display slice pass; plan index, doc paths, docs references, and `git diff --check` pass. | `TautCheckbox` overrides retained Textual's private `_make_label` seam; the retained lock and constructor/assignment firing test own that compatibility risk. |

## Out of Scope

- Changing core's terminal escape syntax or project configuration.
- Escaping editable input values, persisted chat data, JSON, or Summon's raw
  attached-terminal byte stream.
- A general third-party TUI widget protocol or a visual redesign.
- Extending the PTY matrix to every modal when the structural sink inventory
  and production-widget tests already enumerate those surfaces.

## Fresh-Eyes Review

Before closeout, search all production TUI modules for raw/qualified Textual
display widget imports, Rich `Text`, `.update`, `.placeholder =`, every option
add/replace API, `set_options`, `.notify`, and local calls to
`escape_terminal_text`. Any remaining result must be fixed or entered in the
Deviation Log with an owning boundary and executable proof.
