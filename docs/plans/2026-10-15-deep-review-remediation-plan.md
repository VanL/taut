# Deep-Review Remediation Plan

Date: 2026-10-15

Status: active (see `docs/plans/README.md` status index)

Class: 4+P (effective 5). The unit remediates verified product and lifecycle
defects in `taut-tui`, `taut-summon`, `taut-pg`, and core `taut`, and upgrades
repository documentation and coalescing gates (`tests/test_docs_references.py`,
`bin/check-doc-paths`, `bin/coalesce-check`, `tests/test_coalesce_check.py`).
The `+P` modifier applies because extending the citation gate and
`bin/coalesce-check` plan-tier count derivation materially changes how future
changes and coalescing sweeps are verified ([DOM-6], [DOM-15]). The hardening
checklist (`docs/agent-context/runbooks/hardening-plans.md`) is mandatory
because Slice 1 touches asynchronous worker cancellation and multi-step modal
confirmation lifecycles in `taut-tui` ([DOM-5]).

Plan type: implementation, test, and process-gate remediation without normative
product-spec changes (all product fixes restore conformance with existing
[TUI-11.1], [TUI-11.3], [TUI-12.1], [TUI-12.2], [SUM-7.4], [DOCT-4], and
[SRCH-4.1] contracts).

Owner: implementing engineer; durable-policy decisions and plan-retirement
sweeps remain gated on the human repository owner ([DOM-14], [DOM-15]).

## Goal

Remediate the verified findings from the 2026-10-15 repository deep-dive review
across four reviewable, dependency-ordered slices:

1. **Slice 1 — `taut-tui` Summon Bootstrap Cancellation & Two-Step Modal Failure Containment**:
   Linearize `TuiSummonOperations.on_ready()`, `request_owned_stops()`, and
   `stop_owned_and_wait()` under `self._lock` so a foreground run whose handle
   arrives after `record.cancel` is set is stopped immediately, and wrap
   prompt construction plus both the initial and asynchronous second-step modal
   pushes in `TautApp.on_terminal_attach_confirmation_request()` /
   `_present_attach_confirmation()` (`decide_offer`) so an exception fails the
   `TerminalAttachConfirmationRequest` immediately instead of stranding the
   worker thread.
2. **Slice 2 — `taut-tui` Bounded Transcript Selection Extraction**:
   Bound `TautTranscript.get_selection()` to the vertical span `[start_y, end_y]`
   covered by the `Selection` and memoize `Visual.to_strips()` per option index
   within a selection extraction call so copying a selection in a long
   transcript renders each selected option at most once instead of re-rendering
   every virtual line in the transcript, while preserving exact [TUI-12.2]
   policy-filtered output across all `Selection` boundary cases.
3. **Slice 3 — Core, Search, and Summon Hygiene & Test Completeness**:
   Eliminate the duplicate `open_broker` + `list_queue_stats()` pass in
   `taut/_doctor.py::_doctor_workspace`; bind `SEARCH_PROJECTION_VERSION`
   instead of literal `1` in both `SQLiteSearchProvider._delete_in_generation()`
   and `PostgresSearchProvider._delete_in_generation()` with executed SQLite and
   PostgreSQL regression tests; guard `self._owner_phase = "spawn-ready"` in
   `extensions/taut_summon/taut_summon/_driver.py::_accept_phase_result()` as
   diagnostic state cleanup when `not self._shutdown.is_set()`; and add the
   missing surviving-mutant unit test in `extensions/taut_summon/tests/test_pty_adapter.py`
   proving that a completed first enhanced-keyboard detach atom clears
   `_pending_deadline` and survives `expire()` before the second atom detaches.
4. **Slice 4 — Documentation Reference Gate, Plan-Tier Coalescing Counts, and Plan Index Reconciliation**:
   Include `docs/coalescing.md` and `docs/plans/README.md` in
   `tests/test_docs_references.py::_markdown_path_sources()` so `[FAMILY-N]`
   citations in both maintained routing/state files are gated alongside paths;
   extend `bin/coalesce-check` (and `tests/test_coalesce_check.py`) to validate
   `## Plan Status Index` structure before the shallow-clone early return and
   derive/print live plan-tier status counts from `docs/plans/README.md`; and
   reconcile `docs/plans/README.md`, stale transient plan headers, and the
   `docs/coalescing.md` plan-count snapshot.

This document plans the work; authoring and reviewing this plan does not
execute its production slices or authorize publication.

## Source Documents and Baseline

Baseline: `22468ee291b6d6aec3ce74ebf2a25cc3dd43c983` (`HEAD` on `main`, post
`v0.9.11` at `f4275a6eb28a400df412b3ad857b044e25f49a3f`). All file paths, line
numbers, symbols, and reproduction outputs below refer to that commit.

Consulted sources:

- `AGENTS.md`; `docs/agent-context/README.md`; `docs/program-theory.md`
  [THEORY-1]–[THEORY-8] and adopted alternatives [THEORY-5.A1]–[THEORY-5.A6];
  `docs/specs/product-section-registry.md`.
- `docs/agent-context/decision-hierarchy.md`, `principles.md`,
  `engineering-principles.md`, `docs/lessons.md`, `docs/coalescing.md`, and
  runbooks under `docs/agent-context/runbooks/` (`writing-plans.md`,
  `hardening-plans.md`, `testing-patterns.md`, `adversarial-acceptance-probes.md`,
  `review-loops-and-agent-bootstrap.md`, `maintaining-traceability.md`).
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-10.2.1], [DOM-11], [DOM-14], [DOM-15].
- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-3.4], [TAUT-6.4], [TAUT-12.5];
  `docs/specs/04-summon.md` [SUM-7.4], [SUM-12], [SUM-13];
  `docs/specs/06-search.md` [SRCH-4.1], [SRCH-9.3];
  `docs/specs/09-system-doctor.md` [DOCT-4], [DOCT-4.6];
  `docs/specs/10-taut-tui.md` [TUI-5.3], [TUI-8.2], [TUI-11.1], [TUI-11.3],
  [TUI-12.1], [TUI-12.2], [TUI-13.2].
- `docs/implementation/01-documentation-system.md`,
  `02-repository-map.md`, `03-agent-inventory.md`, `04-taut-architecture.md`,
  `05-taut-summon-architecture.md`, `09-search-architecture.md`,
  `11-system-doctor.md`, `12-taut-tui.md`.
- Active and completed plans with adjacent scope:
  `docs/plans/2026-08-19-tui-setup-recovery-offer-plan.md`,
  `docs/plans/2026-09-15-reported-issues-followup-plan.md`,
  `docs/plans/2026-09-23-summon-enhanced-keyboard-detach-plan.md`,
  `docs/plans/2026-09-24-tui-text-selection-and-clipboard-plan.md`,
  `docs/plans/2026-09-24-summon-controlling-terminal-and-live-lane-plan.md`,
  `docs/plans/2026-09-24-cli-read-delivery-and-agent-recipes-plan.md`,
  `docs/plans/2026-09-24-review-inputs-and-doc-gates-plan.md`,
  `docs/plans/2026-09-28-simplification-and-hot-path-plan.md`,
  `docs/plans/2026-10-14-agent-theory-delta-wave-plan.md`.

## Investigation Disposition Matrix

| ID | Verified finding and evidence at baseline `22468ee` | Disposition / owner |
|----|-----------------------------------------------------|---------------------|
| F1 | `TuiSummonOperations.stop_owned_and_wait()` (`extensions/taut_tui/taut_tui/summon.py:342-346`) inspects `record.handle` and sets `record.cancel.set()` outside `self._lock` without setting `self._closed = True`, and `request_owned_stops()` (`lines 306-315`) does not set `record.cancel.set()` on pending records. When `on_ready(handle)` subsequently runs (`summon.py:220-237`), line 227 checks `if self._closed:` instead of `if self._closed or current.cancel.is_set():`, storing `current.handle = handle` without calling `handle.request_stop()`. Live reproduction shows `stop_called=False` and `unresolved=1`. | Fix in Slice 1 (`summon.py` + `test_tui_summon.py`). |
| F2 | `TautApp.on_terminal_attach_confirmation_request()` (`extensions/taut_tui/taut_tui/app.py:810-821`) wraps `_present_attach_confirmation()` in `try ... except BaseException as exc: event.fail(exc)`, protecting only prompt construction and the initial `present()` call (`app.py:3749-3751`). When a setup-recovery offer is accepted (`decide_offer` at `app.py:3739-3743`), the second `present(prompt, decide_acknowledgement)` runs asynchronously inside Textual's screen-dismiss callback without exception containment; if `push_screen` raises there, `event.fail(exc)` is never called and the worker's `event.resolved.wait()` blocks until timeout. | Fix in Slice 1 (`app.py` + `test_tui_summon.py`). |
| F3 | `TautTranscript.get_selection()` (`extensions/taut_tui/taut_tui/widgets.py:596-632`) calls `self._selection_line(y)` for every `y in range(self.virtual_size.height)`, invoking `Visual.to_strips()` across every virtual line of the entire transcript (and repeating `Visual.to_strips()` for each wrapped line of the same option) even when selecting a single line. | Fix in Slice 2 (`widgets.py` + `test_tui_selection.py`). |
| F4 | `taut/_doctor.py::_doctor_workspace()` opens `open_broker(target, config=config)` and calls `broker.list_queue_stats()` at lines 212–213 (`stats`), then opens a second `open_broker(target, config=config)` and calls `broker.list_queue_stats()` again at lines 266–268 (`search_stats`) solely to read `search_stats.get(PENDING_QUEUE_NAME)`. | Fix in Slice 3 (`taut/_doctor.py` + `tests/test_system_doctor.py`). |
| F5 | `SQLiteSearchProvider._delete_in_generation()` (`taut/search/_sqlite.py:345-374`) and `PostgresSearchProvider._delete_in_generation()` (`extensions/taut_pg/taut_pg/_search.py:305-333`) hardcode literal `1` for `projection_version` in tombstone upserts (`VALUES (?, ?, ?, '', 0, 1, ?, 0)` and `VALUES (?, ?, ?, '', 0, 1, ?, FALSE)`) instead of binding `SEARCH_PROJECTION_VERSION` as `replace_document` does (`_sqlite.py:293, 307`; `_search.py:255, 270`). | Fix in Slice 3 (`_sqlite.py`, `_search.py`, `tests/test_search.py`, `extensions/taut_pg/tests/test_pg_integration.py`). |
| F6 | In `extensions/taut_summon/tests/test_pty_adapter.py`, the surviving-mutant unit test recorded in `docs/plans/2026-09-24-summon-controlling-terminal-and-live-lane-plan.md:435-437` (verifying that `_DetachChordMatcher` clears `_pending_deadline` when the first enhanced-keyboard atom completes, so advancing the clock 0.5 s and calling `expire()` returns `b""` and the second atom still detaches) was never added. Additionally, in `SummonDriver._accept_phase_result()` (`extensions/taut_summon/taut_summon/_driver.py:1058-1066`), when initial attach confirmation is declined (`not result.value` and `not self._pending_setup_recovery_attach`), `self.request_stop()` sets `_shutdown` (which prevents `_owner_turn()` from spawning), but line 1066 still sets `self._owner_phase = "spawn-ready"` during the window before teardown begins. | Fix in Slice 3 (`test_pty_adapter.py`, `_driver.py`, `test_driver.py`). |
| F7 | `tests/test_docs_references.py::_markdown_path_sources()` (`lines 110-125`) omits `docs/coalescing.md` and `docs/plans/README.md` (which `bin/check-doc-paths:47-50` had to add via `EXTRA_SOURCES`), leaving `[FAMILY-N]` spec citations in those two maintained surfaces unchecked by `test_cited_spec_codes_resolve_to_spec_headings()`. | Fix in Slice 4 (`tests/test_docs_references.py`, `bin/check-doc-paths`). |
| F8 | `bin/coalesce-check` derives and prints `lessons_counts()` (`lines 195-206, 303-317`) but does not derive or print plan-tier counts from `docs/plans/README.md`, which allowed the 2026-10-15 run-log entry in `docs/coalescing.md:130` to record stale mental-arithmetic counts (`29 indexed rows ... completed 8 ... active 8, draft 10` vs actual 31 rows, 0 draft). Furthermore, `2026-07-29-taut-chat-pypi-publication-plan.md` has its complete hosted release-gate and post-publication evidence recorded in its Execution Log (`lines 824-838`, `v0.8.2` at `a12a8fa`) yet remains `active` in `docs/plans/README.md`, and 3 legitimately `active` plans carry stale transient header phrases (`Changes are uncommitted`, `Status: draft`, `is promoted in the working tree`). | Fix in Slice 4 (`bin/coalesce-check`, `tests/test_coalesce_check.py`, `docs/plans/README.md`, plan headers, `docs/coalescing.md`). |
| N1 | Candidate claim: `PostgresSearchProvider.retarget_threads()` omits `AND latest_revision <= ?` compared to SQLite. **Rejected (false positive)**: `extensions/taut_pg/taut_pg/_search.py:216` (`_retarget_generation`) already enforces `WHERE queue_name = ? AND latest_revision <= ?` identically to `taut/search/_sqlite.py:254` (`_retarget_slot`). | No action; verified identical. |
| N2 | `[TAUT-3.2]` strict invalid-target `.taut.db` discovery (`taut/client/_base.py:343-358`, `taut/_maintenance.py:74-86`) and upstream SimpleBroker ephemeral `Queue` finalizer guard (`../simplebroker/simplebroker/sbqueue.py:300, 2122`). | Out of scope here; already owned by active `docs/plans/2026-09-24-cli-read-delivery-and-agent-recipes-plan.md` (Slice 1, blocked on upstream SimpleBroker release seam). Do not duplicate or fork ownership. |

## Context and Key Files

### Slice 1 (`taut-tui` Summon Bootstrap Cancellation & Modal Failure Containment)

- `extensions/taut_tui/taut_tui/summon.py`:
  - `TuiSummonOperations` (`lines 190-408`): manages TUI-owned foreground Summon
    runs via `_OwnedRecord` records (`token`, `cancel: threading.Event`,
    `handle: _RunHandle | None`, `future: Future[None] | None`), alongside
    `TuiSummonInteraction` (`lines 725-920`) and `_ScopedSummonInteraction`
    (`lines 679-722`), which enforce single-flight confirmation and terminal
    lease ownership per logical foreground run (`operation_scope()`).
  - `on_ready(handle: _RunHandle)` (`lines 220-237`): callback passed to
    `self._controller.run_foreground(..., on_ready=on_ready)` (`line 262`).
    Currently checks `if self._closed:` under `with self._lock:`, setting
    `stop_after_close = True` only when `self._closed` is true.
  - `request_owned_stops()` (`lines 306-315`) and
    `stop_owned_and_wait(timeout: float = 90.0)` (`lines 332-381`):
    `stop_owned_and_wait` inspects `record.handle` and calls `record.cancel.set()`
    inside `supervise()` without holding `self._lock`, and does **not** set
    `self._closed = True`. Both `request_owned_stops()` and `stop_owned_and_wait()`
    must set `record.cancel.set()` and read `record.handle` under `with self._lock:`
    so `self._lock` forms a single mutual-exclusion linearization point with
    `on_ready(handle)`.
- `extensions/taut_tui/taut_tui/app.py`:
  - `on_terminal_attach_confirmation_request()` (`lines 810-821`): catches
    `BaseException` around `self._attach_confirmation_prompts(event.notice)` and
    `_present_attach_confirmation(self, event, offer=offer, prompt=prompt)`
    and calls `event.fail(exc)`.
  - `_present_attach_confirmation()` (`lines 3708-3752`): presents the one- or
    two-step confirmation modal for `TerminalAttachConfirmationRequest`. In the
    two-step setup-recovery flow (`offer is not None`), `present(offer, decide_offer)`
    pushes the offer modal (`line 3751`), and when the user confirms it,
    `decide_offer(decision)` (`lines 3739-3743`) runs asynchronously from the
    modal dismissal callback and calls `present(prompt, decide_acknowledgement)`
    without a `try ... except BaseException as exc: event.fail(exc)` guard.
- `extensions/taut_tui/tests/test_tui_summon.py`:
  - Existing real-controller / `TuiSummonOperations` and modal confirmation
    tests (`lines 1-920`).

### Slice 2 (`taut-tui` Bounded Transcript Selection Extraction)

- `extensions/taut_tui/taut_tui/widgets.py`:
  - `TautTranscript.get_selection(self, selection: Selection) -> tuple[str, str]`
    (`lines 596-606`) and `_selection_line(self, y: int) -> str` (`lines 608-631`).
- `extensions/taut_tui/tests/test_tui_selection.py`:
  - Existing real `TautApp` / `TautTranscript` selection and OSC 52 copy tests.

### Slice 3 (Core, Search, and Summon Hygiene & Test Completeness)

- `taut/_doctor.py`:
  - `_doctor_workspace()` (`lines 195-330`): passive workspace health check.
- `taut/search/_sqlite.py` (`lines 345-374`) and
  `extensions/taut_pg/taut_pg/_search.py` (`lines 305-333`):
  - `SQLiteSearchProvider._delete_in_generation()` and
    `PostgresSearchProvider._delete_in_generation()` tombstone
    `INSERT INTO taut_search_documents ... ON CONFLICT` statements.
- `extensions/taut_summon/taut_summon/_pty.py` (`lines 708-847`) and
  `extensions/taut_summon/taut_summon/_driver.py` (`lines 1052-1067`):
  - `_DetachChordMatcher._feed_sequence_byte()` (`line 782`,
    `self._pending_deadline = None`) and `SummonDriver._accept_phase_result()`.
- `extensions/taut_summon/tests/test_pty_adapter.py` (`lines 582-635`),
  `extensions/taut_summon/tests/test_driver.py`,
  `tests/test_system_doctor.py`, `tests/test_search.py`, and
  `extensions/taut_pg/tests/test_pg_integration.py`.

### Slice 4 (Documentation Gates, Plan-Tier Coalescing Counts, Plan Index)

- `tests/test_docs_references.py` (`lines 110-125, 334-349`) and
  `bin/check-doc-paths` (`lines 45-50, 75-103, 167-171`).
- `bin/coalesce-check` (`lines 97-144, 195-207, 263-341`),
  `tests/test_coalesce_check.py` (`lines 1-184`), and
  `bin/check-plan-status-index` (`lines 23-86`).
- `docs/plans/README.md`, `docs/coalescing.md`, and plan headers in:
  - `docs/plans/2026-07-29-taut-chat-pypi-publication-plan.md`
  - `docs/plans/2026-09-23-summon-enhanced-keyboard-detach-plan.md`
  - `docs/plans/2026-08-19-tui-setup-recovery-offer-plan.md`
  - `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md`

### Comprehension Questions (Read Before Editing)

1. **In `TuiSummonOperations`, why did `on_ready(handle)` miss a prior `stop_owned_and_wait()` call when `close()` had not yet set `self._closed = True`, and why must `record.cancel.set()` and `record.handle` inspection happen under `self._lock`?**
   - *Expected answer*: `stop_owned_and_wait()` (`summon.py:342-346`) sets `record.cancel.set()` for any owned run whose `record.handle` is still `None`, without setting `self._closed = True`. When the worker thread enters `on_ready(handle)` after passing the pre-run `record.cancel.is_set()` check in `_run_owned()` (`line 260`), `on_ready` only checked `if self._closed:` (`line 227`), ignoring `current.cancel.is_set()`. Furthermore, because `supervise()` read `record.handle` and called `record.cancel.set()` outside `self._lock`, `on_ready` could run between `if record.handle is not None:` and `record.cancel.set()`. Acquiring `self._lock` when setting `record.cancel.set()` and reading `record.handle` in `stop_owned_and_wait()` / `request_owned_stops()`, paired with checking `self._closed or current.cancel.is_set()` under `self._lock` in `on_ready()`, establishes a strict mutual-exclusion linearization point.
2. **Why does the `try ... except BaseException` in `TautApp.on_terminal_attach_confirmation_request` (`app.py:817-821`) not protect the second modal step in `_present_attach_confirmation`, and why would a test that invokes `decide_offer(True)` synchronously inside the first `push_screen` pass on unchanged code?**
   - *Expected answer*: For setup-recovery notices (`offer is not None`), `_present_attach_confirmation` pushes the offer screen and returns immediately (`line 3751`). In production, `decide_offer` runs later from Textual's screen-dismiss callback, outside the synchronous stack frame of `on_terminal_attach_confirmation_request`. If a test stub invokes `decide_offer(True)` synchronously inside the first `push_screen`, the second `push_screen` is still on the initial call stack and caught by line 820. The test must capture `decide_offer`, let `on_terminal_attach_confirmation_request` return, and then invoke `decide_offer(True)`.
3. **Why does `_DetachChordMatcher` clear `_pending_deadline` when the first enhanced-keyboard atom completes (`_pty.py:782`)?**
   - *Expected answer*: `_pending_deadline` is the 100 ms CSI-prefix ambiguity deadline (`_DETACH_AMBIGUITY_SECONDS`) that distinguishes a bare `ESC` from an in-flight escape sequence, *not* a timeout between the two `Ctrl-\` atoms of a detach chord. Once the first enhanced atom (`b"\x1b[92;5u"`) completes, `_pending_deadline` is reset to `None` so `expire()` after 0.5 s does not flush the completed first atom, and a subsequent second `Ctrl-\` atom completes the detach chord.

## Invariants, Constraints, and Hidden Couplings

### What Must Not Change

1. **Single workspace & core authority ([THEORY-2], [THEORY-4])**:
   No new daemon, lockfile, background thread, or retry loop is added. All
   adopted alternatives in `[THEORY-5.A1]`–`[THEORY-5.A6]` remain in force.
2. **TUI Summon ownership and single-flight coordination ([TUI-11.1], [TUI-11.3], [SUM-13])**:
   `TuiSummonInteraction` and `_ScopedSummonInteraction` continue to allow at
   most one active confirmation or terminal lease per logical foreground run
   (`operation_scope()`). `TuiSummonOperations` remains the sole owner of
   `_OwnedRecord` lifecycles.
3. **Policy-filtered display copy contract ([TUI-8.2], [TUI-12.2], [TAUT-6.4])**:
   `TautTranscript.get_selection(selection)` must return the exact same
   extracted text and `"\n"` delimiter for every `Selection` (`start=None`,
   `end=None`, single-line, multi-line, wrapped option, out-of-range `end.y`,
   and trailing blank display row) as the baseline implementation.
4. **Search schema and projection version ([SRCH-4.1])**:
   `SEARCH_PROJECTION_VERSION` remains `1`; binding the constant in tombstone
   upserts does not alter stored values or schema version (`SEARCH_SCHEMA_VERSION = 2`),
   and requires no migration.
5. **Ruff suppression inventory ([DOM-10.2.1])**:
   Do not add unapproved `# noqa` suppressions.
6. **Plan status completion gate ([DOM-10], [DOM-14])**:
   Do not flip an `active` plan to `completed` in `docs/plans/README.md` unless
   every qualification gate required by that plan's own Completion Gate (such as
   exact-SHA native Windows or hosted OS/Python CI evidence) is recorded in the
   plan or explicitly waived by the owner.

### Hidden Couplings

- **Ruff suppression scope `[RUFF-SUP-085]` (`docs/specs/01-development-documentation-operating-model.md:580`)**:
  `[RUFF-SUP-085]` is pinned to `extensions/taut_tui/taut_tui/app.py::TautApp.on_terminal_attach_confirmation_request`
  with count `1` (`BLE001=1`). Defining `def run_guarded(step: Callable[[], None]) -> None:`
  inside `TautApp.on_terminal_attach_confirmation_request` with that single
  `try: step() except BaseException as exc: event.fail(exc)` block, using
  `run_guarded` to run prompt construction + initial `_present_attach_confirmation`,
  and passing `run_guarded` into `_present_attach_confirmation` to wrap
  `decide_offer`'s deferred `present(prompt, decide_acknowledgement)` protects
  prompt construction and both modal pushes while keeping the exact `BLE001=1`
  count in `TautApp.on_terminal_attach_confirmation_request`.
- **`bin/check-doc-paths` vs `tests/test_docs_references.py` source lists**:
  `bin/check-doc-paths` imports `tests.test_docs_references` and prints
  `beyond the pytest gate's list: ...` from `EXTRA_SOURCES`. When
  `docs/coalescing.md` and `docs/plans/README.md` move into
  `tests/test_docs_references.py::_markdown_path_sources()` (and
  `bin/check-doc-paths::_root_sources`), set `EXTRA_SOURCES: list[Path] = []` in
  `bin/check-doc-paths` so its CLI output and `self_test()` continue to work
  cleanly without duplicate scanning.
- **`docs/plans/README.md` vs `bin/coalesce-check` and `tests/test_coalesce_check.py`**:
  `bin/check-plan-status-index` already owns `parse_rows(text)` for the
  `## Plan Status Index` table. `bin/coalesce-check` should validate any present
  `## Plan Status Index` table **before** the `--is-shallow-repository` early
  return (just as `retired_plan_claims()` is called before the shallow-clone
  branch at `bin/coalesce-check:268`), report any structural errors in `BROKEN`
  (exit 1), and print the derived plan counts informational line on both normal
  and shallow-clone runs when the table is present.

## Rollout, Rollback, and One-Way Doors

- **Rollout sequencing**: All four slices are backward-compatible and can land
  in dependency order (Slices 1 -> 2 -> 3 -> 4) on `main`. No schema version,
  wire protocol, or CLI flag changes.
- **One-way doors**: None. Every slice is a pure source/test/doc change with
  no persistent data migration.
- **Rollback**: Each slice can be reverted independently via `git revert`.
- **Stop-and-re-evaluate gates**:
  - Stop in Slice 1 if protecting `decide_offer` would require changing the
    `[RUFF-SUP-085]` suppression count or altering `TuiSummonInteraction` /
    `_ScopedSummonInteraction` state transitions.
  - Stop in Slice 2 if bounding `TautTranscript.get_selection` alters the
    extracted string for any `Selection` case in `test_tui_selection.py`.
  - Stop in Slice 4 if adding `docs/coalescing.md` and `docs/plans/README.md`
    to `_markdown_path_sources()` causes retired-plan stems in the `## Retired Plans`
    table or `git show <sha>:docs/plans/...` cues in `docs/coalescing.md` to be
    misclassified as live path claims.

## Dependency-Ordered Tasks

### Slice 1: `taut-tui` Summon Bootstrap Cancellation & Two-Step Modal Failure Containment

1. **Write RED tests in `extensions/taut_tui/tests/test_tui_summon.py`**:
   - **Test 1A-1 (`test_stop_owned_and_wait_stops_handle_arriving_at_on_ready`)**:
     Create a `TuiSummonOperations` instance with a controller whose
     `run_foreground` blocks after entering `run_foreground` until
     `stop_owned_and_wait()` has set `record.cancel.set()` (while `record.handle`
     is still `None` and `ops.close()` has *not* been called), and then invokes
     `on_ready(handle)`. Assert that `on_ready(handle)` immediately calls
     `handle.request_stop()` and `stop_owned_and_wait()` returns an
     `OwnedSummonShutdown` with `unresolved == ()` and `handle.stop_calls == 1`.
     Verify RED failure at baseline (`handle.stop_calls == 0` and
     `len(shutdown.unresolved) == 1`).
   - **Test 1A-2 (`test_stop_owned_and_request_owned_stops_linearize_with_on_ready_under_lock`)**:
      verify both: (i) `request_owned_stops()` sets `record.cancel.set()` on a
     pending `_OwnedRecord` (`record.handle is None`) so a subsequent
     `on_ready(handle)` stops the handle immediately, and (ii) when `on_ready`
     holds `ops._lock` (or via a deterministic barrier at the `_OwnedRecord.handle`
     read / `cancel.set()` transition), `stop_owned_and_wait()` cannot read
     `record.handle is None` and set `record.cancel.set()` across an interleaved
     `on_ready(handle)` execution without `self._lock`.
   - **Test 1B (`test_setup_recovery_offer_second_modal_push_failure_fails_request`)**:
     Invoke `app.on_terminal_attach_confirmation_request(event)` with a
     setup-recovery notice (`offer` non-None) where `app.push_screen` captures
     `(screen, callback)` on the first call and returns normally (so
     `on_terminal_attach_confirmation_request` finishes its synchronous stack
     frame with `event.resolved.is_set() is False`), and raises
     `RuntimeError("screen stack closed")` on the second `push_screen` call.
     Then invoke the captured `decide_offer(True)` callback asynchronously (as
     Textual's modal dismissal does). Assert that `decide_offer(True)` does not
     propagate an unhandled exception, `event.resolved.is_set()` is `True`, and
     `event.error` is the `RuntimeError("screen stack closed")`. Verify RED
     failure at baseline (`RuntimeError` escapes unhandled from `decide_offer`
     and `event.resolved.is_set()` remains `False`).
2. **Implement Slice 1 fixes**:
   - In `extensions/taut_tui/taut_tui/summon.py:220-237, 306-315, 341-347`:
     Add a private helper `_cancel_and_collect_handles(self, records: Iterable[_OwnedRecord] | None = None) -> tuple[_RunHandle, ...]`
     that under `with self._lock:` iterates the target records (defaulting to
     `self._owned.values()`), sets `record.cancel.set()` on each record, and
     collects `record.handle` when non-None; then both `request_owned_stops()`
     and `stop_owned_and_wait()`'s `supervise()` call this helper and invoke
     `handle.request_stop()` on the returned handles outside the lock. In
     `on_ready(handle)`, under `with self._lock:`, set `current.handle = handle`
     and check `if self._closed or current.cancel.is_set(): stop_after_close = True`.
   - In `extensions/taut_tui/taut_tui/app.py:810-821` and `3708-3752`:
     Define `run_guarded(step: Callable[[], None]) -> None` inside
     `TautApp.on_terminal_attach_confirmation_request` using its single existing
     `try: step() except BaseException as exc: event.fail(exc)` block (`[RUFF-SUP-085]`).
     Use `run_guarded` to execute prompt construction + the initial
     `_present_attach_confirmation(self, event, offer=offer, prompt=prompt, run_guarded=run_guarded)`
     call, and inside `_present_attach_confirmation`, wrap `decide_offer`'s
     deferred `present(prompt, decide_acknowledgement)` call in `run_guarded`.
3. **Verify Slice 1 (GREEN + Mutation Check)**:
   - Run `uv run --directory extensions/taut_tui --extra dev pytest -n 0 tests/test_tui_summon.py`.
   - Perform the required P1 mutation checks:
     1. Revert `or current.cancel.is_set()` in `on_ready` -> confirm Test 1A-1 fails.
     2. Remove `with self._lock:` from `_cancel_and_collect_handles` -> confirm Test 1A-2 fails.
     3. Bypass `run_guarded` in `decide_offer` -> confirm Test 1B fails.
     Restore all three and re-run green.

### Slice 2: `taut-tui` Bounded Transcript Selection Extraction

1. **Write RED tests in `extensions/taut_tui/tests/test_tui_selection.py`**:
   - **Test 2A (`test_transcript_get_selection_renders_only_selected_options_once`)**:
     In a real `TautApp` under `run_test` with 25 messages in the transcript
     (including a multi-line wrapped message spanning `>= 2` virtual lines),
     wrap `Visual.to_strips` to record the `visual` / option rendered on each
     call while delegating to the real `Visual.to_strips`. Select a **3-row**
     vertical span covering **2 virtual rows of the wrapped multi-line option**
     plus **1 virtual row of an adjacent option** near the bottom of the
     transcript. Assert that:
     1. `Visual.to_strips` is called **exactly 2 times** (`len(calls) == 2`) —
        once for the wrapped multi-line option (despite 2 of its virtual lines
        being selected) and once for the adjacent option — proving both vertical
        bounding and per-option memoization; and
     2. the extracted text equals the policy-filtered rendered display rows.
     Verify RED failure at baseline (`Visual.to_strips` is called for every
     virtual line in the transcript, and twice for the 2 selected rows of the
     wrapped option).
   - **Test 2B (`test_transcript_get_selection_boundary_matrix_matches_full_render`)**:
     On a real `TautTranscript` under `run_test` containing wrapped rows and a
     trailing blank display row, assert that `transcript.get_selection(sel)`
     returns the exact same `(text, "\n")` result across the complete boundary
     matrix:
     1. `Selection(None, None)` (full selection),
     2. `Selection(Offset(2, 1), None)` (`end=None`),
     3. `Selection(None, Offset(4, 2))` (`start=None`),
     4. `Selection(Offset(0, 1), Offset(5, 999))` (out-of-range `end.y >= height`),
     5. single-option multi-line wrapped span, and
     6. selection reaching the final blank display row.
2. **Implement Slice 2 fix in `extensions/taut_tui/taut_tui/widgets.py`**:
   - In `TautTranscript.get_selection(self, selection: Selection)` (`lines 596-632`),
     call `self._update_lines()` and read `height = self.virtual_size.height`.
     If `height <= 0` or not `self._lines`, return `"", "\n"`.
   - Compute vertical bounds:
     `start_y = 0 if selection.start is None else max(0, selection.start.y)` and
     `end_y = height - 1 if selection.end is None else min(height - 1, selection.end.y)`.
   - Pass a per-call cache `strips_by_option: dict[int, list[Strip]] = {}` to
     `_selection_line(self, y: int, strips_by_option: dict[int, list[Strip]] | None = None) -> str`
     so each `option_index` overlapped by `[start_y, end_y]` is converted via
     `Visual.to_strips()` at most once, while rows `y < start_y` or `y > end_y`
     use the interned `""` literal without calling `_selection_line`. Preserve
     `if lines and not lines[-1]: rendered += "\n"` so `Selection.extract(rendered)`
     splits `rendered` into `height` lines with identical indices and boundary
     behavior. (Note: allocating `height` references to interned `""` is
     $O(\text{height})$ pointer copies — ~8 KB for 1,000 lines — while avoiding
     all `Visual.to_strips` layout work outside `[start_y, end_y]` and keeping
     `Selection.extract`'s `end_line = min(len(lines), end_line)` clamp exact.)
3. **Verify Slice 2**:
   - Run `uv run --directory extensions/taut_tui --extra dev pytest -n 0 tests/test_tui_selection.py tests/test_tui_textual_contract.py`
     and the canonical parallel TUI suite
     `uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests -n 2 --dist loadfile`.

### Slice 3: Core, Search, and Summon Hygiene & Test Completeness

1. **Write RED tests**:
   - **Test 3A (`tests/test_system_doctor.py`)**: Spy on `taut._doctor.open_broker`
     (delegating to the real `open_broker`) during `run_doctor(workspace)` on a
     real SQLite workspace and assert `open_broker` is called once per
     `_doctor_workspace` invocation rather than twice. Verify RED at baseline
     (`open_broker` called twice).
   - **Test 3B (`tests/test_search.py` and `extensions/taut_pg/tests/test_pg_integration.py`)**:
     1. In `tests/test_search.py`, monkeypatch
        `taut.search._sqlite.SEARCH_PROJECTION_VERSION` to `2` in a real
        temporary SQLite workspace test, delete a message via
        `delete_documents` / `_delete_in_generation`, and assert the tombstone
        row in `taut_search_documents` stores `projection_version == 2` (with
        `indexed == 0`) rather than hardcoded `1`.
     2. In `extensions/taut_pg/tests/test_pg_integration.py`, add both:
        (a) an unconditional DSN-independent unit test that monkeypatches
            `taut_pg._search.SEARCH_PROJECTION_VERSION` to `2`, invokes
            `PostgresSearchProvider._delete_in_generation(recording_session, message_ts=10, thread="general", generation=1, revision=5)`,
            and asserts the first `session.run` call binds `(1, 10, "general", 2, 5)`
            into the 8-column `VALUES (?, ?, ?, '', 0, ?, ?, FALSE)` statement; and
        (b) a live PostgreSQL integration test (using the `pg_dsn` fixture) that
            monkeypatches `taut_pg._search.SEARCH_PROJECTION_VERSION` to `2`,
            deletes an indexed message, and queries `taut_search_documents` to
            assert `projection_version == 2` and `indexed is False`.
     Verify RED at baseline (`projection_version == 1`).
   - **Test 3C-1 (`extensions/taut_summon/tests/test_pty_adapter.py`)**:
     Add `test_detach_matcher_completed_enhanced_atom_clears_pending_deadline`
     per `docs/plans/2026-09-24-summon-controlling-terminal-and-live-lane-plan.md:435-437`:
     using `clock = _MatcherClock()` and `matcher = _semantic_matcher(clock)`,
     feed the first enhanced `Ctrl-\` atom (`assert matcher.feed(b"\x1b[92;5u") == (b"", False)`),
     assert `matcher.pending_deadline is None`, advance `clock.now += 0.5`,
     assert `matcher.expire() == b""`, and feed the second atom
     (`assert matcher.feed(b"\x1b[92;5u") == (b"", True)`). Perform the mutation
     check by temporarily removing `self._pending_deadline = None` at
     `extensions/taut_summon/taut_summon/_pty.py:782` and confirming the new
     test fails (`matcher.expire()` flushes the first atom and the second atom
     does not detach), then restore line 782.
   - **Test 3C-2 (`extensions/taut_summon/tests/test_driver.py`)**:
     When initial attach confirmation resolves with `result.value = False`
     (`_pending_setup_recovery_attach` is `False`), assert `_accept_phase_result`
     calls `request_stop()`, clears `_pending_setup_recovery_attach`, and does
     not advance `_owner_phase` to `"spawn-ready"` when `self._shutdown.is_set()`,
     while setup-recovery decline (`_pending_setup_recovery_attach` is `True`
     and `not self._shutdown.is_set()`) still clears `_pending_setup_recovery_attach`
     and advances `_owner_phase` to `"spawn-ready"`.
2. **Implement Slice 3 fixes**:
   - In `taut/_doctor.py:265-272`, reuse `stats.get(PENDING_QUEUE_NAME)` from
     the `stats` dictionary already fetched at line 213 instead of opening a
     second `open_broker(target, config=config)` context.
   - In `taut/search/_sqlite.py:356-373` (`SQLiteSearchProvider._delete_in_generation`),
     change `VALUES (?, ?, ?, '', 0, 1, ?, 0)` to `VALUES (?, ?, ?, '', 0, ?, ?, 0)`
     and bind `(generation, message_ts, thread, SEARCH_PROJECTION_VERSION, revision)`.
   - In `extensions/taut_pg/taut_pg/_search.py:315-331` (`PostgresSearchProvider._delete_in_generation`),
     change `VALUES (?, ?, ?, '', 0, 1, ?, FALSE)` to `VALUES (?, ?, ?, '', 0, ?, ?, FALSE)`
     and bind `(generation, message_ts, thread, SEARCH_PROJECTION_VERSION, revision)`.
   - In `extensions/taut_summon/taut_summon/_driver.py:1058-1066`, keep
     `self._pending_setup_recovery_attach = False` and guard
     `if not self._shutdown.is_set(): self._owner_phase = "spawn-ready"`.
3. **Verify Slice 3**:
   - Run `uv run --extra dev pytest tests/test_system_doctor.py tests/test_search.py`,
     `uv run --directory extensions/taut_summon --extra dev pytest tests/test_driver.py tests/test_pty_adapter.py`,
     `uv run --directory extensions/taut_pg --extra dev pytest`, and
     `uv run pytest-pg`. Both the unconditional `taut_pg` unit test and the live
     PostgreSQL integration regression (`pg_dsn` with `SIMPLEBROKER_PG_TEST_DSN`
     configured, 0 skips on the new test) must execute and pass before Slice 3
     is declared complete; if `SIMPLEBROKER_PG_TEST_DSN` is unavailable, report
     an explicit incomplete-verification blocker rather than claiming Slice 3
     completion.

### Slice 4: Documentation Reference Gate, Plan-Tier Coalescing Counts, and Plan Index Reconciliation

1. **Write RED tests**:
   - **Test 4A (`tests/test_docs_references.py`)**: In
     `test_maintained_markdown_sources_cover_current_routing_surfaces()`, assert
     that `Path("docs/coalescing.md")` and `Path("docs/plans/README.md")` are in
     `{path.relative_to(REPO_ROOT) for path in _markdown_path_sources()}`.
     Verify RED at baseline.
   - **Test 4B (`tests/test_coalesce_check.py`)**: Extend `tests/test_coalesce_check.py`
     with firing tests that:
     1. populate `docs/plans/README.md` with a `## Plan Status Index` table
        covering all 6 allowed statuses — `completed` (`exemplar=yes` and
        `exemplar=no`), `superseded` (`exemplar=yes` and `exemplar=no`),
        `active`, `draft`, `status-review`, and `retired-pending` — and assert
        that `bin/coalesce-check` prints the exact derived plan-tier counts
        (including both `completed` and `superseded` non-exemplar rows in the
        harvest-eligible count) in both normal mode and `--depth 1`
        shallow-clone mode; and
     2. verify that a malformed `## Plan Status Index` table in
        `docs/plans/README.md` causes `bin/coalesce-check` to fail with exit
        code `1` and `BROKEN` in both normal mode and shallow-clone mode (before
        the shallow-history early return).
     Verify RED at baseline.
2. **Implement Slice 4 fixes**:
   - Add `REPO_ROOT / "docs" / "coalescing.md"` and
     `REPO_ROOT / "docs" / "plans" / "README.md"` to `_markdown_path_sources()`
     in `tests/test_docs_references.py` and `_root_sources()` in
     `bin/check-doc-paths`, and set `EXTRA_SOURCES: list[Path] = []` in
     `bin/check-doc-paths` (updating its docstring and `docs/implementation/02-repository-map.md`
     row for `bin/check-doc-paths`).
   - In `bin/coalesce-check`, add `plan_status_counts()` that parses any
     `## Plan Status Index` section in `docs/plans/README.md` using the same
     4-column grammar as `bin/check-plan-status-index`, runs before the
     shallow-clone early return, reports any structural violation in `BROKEN`
     (causing exit 1 even on shallow clones), and prints the derived plan-tier
     counts (`total`, `active`, `draft`, `status-review`, `retired-pending`,
     `completed`, `superseded`, exemplar vs non-exemplar `completed` +
     `superseded` harvest-eligible) in both shallow and full-history modes.
   - Reconcile `docs/plans/README.md` and plan headers:
     - Flip `2026-07-29-taut-chat-pypi-publication-plan.md` from `active` to
       `completed` in `docs/plans/README.md` and in its top-of-file status line
       (its Execution Log at `lines 824-838` already records all 4 passing
       release gates `31048769442`, `31048766907`, `31048764615`, `31048767033`
       and PyPI/GitHub verification for `v0.8.2` at `a12a8fa`).
     - Keep `2026-09-28-simplification-and-hot-path-plan.md`,
       `2026-09-24-identity-claim-boundary-plan.md`, and
       `2026-07-28-taut-mcp-dual-era-sessionless-plan.md` at `active` in
       `docs/plans/README.md` because their completion gates require exact-SHA
       native Windows or hosted OS/Python qualification evidence in their
       Execution Logs that is not yet recorded in those plans.
     - Repair stale transient phrases in the 3 `active` plans whose headers
       contradict git history or `docs/plans/README.md`:
       - `docs/plans/2026-09-23-summon-enhanced-keyboard-detach-plan.md:5`:
         replace `Changes are uncommitted.` with `Implementation landed at bd8ff4e and shipped in v0.9.9 (c894059).`
       - `docs/plans/2026-08-19-tui-setup-recovery-offer-plan.md:5`:
         replace `Status: draft (see docs/plans/README.md status index)` with
         `Status: active (see docs/plans/README.md status index)`.
       - `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md:7`:
         replace `is promoted in the working tree.` with `was promoted at dcf5d0b.`
     - Update `docs/coalescing.md` (`Deferral State` and `Run Log`) with an
       additive run-log entry recording the `bin/coalesce-check`-verified
       plan-tier counts.
3. **Verify Slice 4**:
   - Run `uv run bin/check-plan-status-index && uv run bin/check-plan-status-index --self-test`,
     `uv run bin/check-doc-paths && uv run bin/check-doc-paths --self-test`,
     `uv run bin/check-cli-claims && uv run bin/check-dom15-fixtures`,
     `uv run bin/coalesce-check`, and
     `uv run --extra dev pytest tests/test_coalesce_check.py tests/test_docs_references.py tests/test_cli_claims.py tests/test_ruff_policy.py`.

## Testing Plan and Anti-Mocking Rules

- **Real adapters and state**:
  - Slice 1 tests in `extensions/taut_tui/tests/test_tui_summon.py` must use the
    real `TuiSummonOperations`, real `TuiSummonInteraction` / `_ScopedSummonInteraction`,
    and real `_present_attach_confirmation` with `ConfirmationScreen` instances;
    only the fault-injected second `push_screen` call (invoked asynchronously
    after the initial handler returns) or controlled `run_foreground` / lock
    interleaving barrier is stubbed at the exact seam under test.
  - Slice 2 tests in `extensions/taut_tui/tests/test_tui_selection.py` must run
    against a real `TautApp` and `TautTranscript` under `run_test()` with a
    real SQLite workspace; `Visual.to_strips` is wrapped with an option-recording
    counter that delegates to the real `Visual.to_strips` implementation (never
    returning fake strips).
  - Slice 3 tests in `tests/test_system_doctor.py`, `tests/test_search.py`, and
    `extensions/taut_pg/tests/test_pg_integration.py` must run against real
    temporary SQLite and PostgreSQL workspaces (plus the unconditional
    recording-session unit test in `test_pg_integration.py`); `open_broker` is
    wrapped only with a call counter delegating to the real `open_broker`.
  - Slice 4 tests in `tests/test_coalesce_check.py` and `tests/test_docs_references.py`
    run the real repository gate scripts against temporary git repositories
    (including shallow clones) and the live tree.
- **No `time.sleep` synchronizers**:
  - Use `threading.Event` barriers in Slice 1 concurrency tests and the injected
    `_MatcherClock` (`clock.now += 0.5`) in Slice 3's `_DetachChordMatcher` test.

## Verification and Gates

```bash
uv run --directory extensions/taut_tui --extra dev pytest -n 0 tests/test_tui_summon.py tests/test_tui_selection.py tests/test_tui_textual_contract.py
uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests -n 2 --dist loadfile
uv run --directory extensions/taut_summon --extra dev pytest tests/test_driver.py tests/test_pty_adapter.py
uv run --directory extensions/taut_pg --extra dev pytest
uv run pytest-pg
uv run --extra dev pytest tests/test_system_doctor.py tests/test_search.py tests/test_coalesce_check.py tests/test_docs_references.py tests/test_cli_claims.py tests/test_ruff_policy.py tests/test_ruff_suppression_index.py
uv run --extra dev ruff check .
uv run --extra dev ruff format --check taut tests extensions bin
uv run --extra dev mypy
uv run --directory extensions/taut_tui --extra dev ruff check taut_tui tests
uv run --directory extensions/taut_summon --extra dev ruff check taut_summon tests
uv run --directory extensions/taut_pg --extra dev ruff check taut_pg tests
uv run bin/check-plan-status-index && uv run bin/check-plan-status-index --self-test
uv run bin/check-doc-paths && uv run bin/check-doc-paths --self-test
uv run bin/check-cli-claims
uv run bin/check-dom15-fixtures && uv run bin/check-dom15-fixtures --self-test
uv run bin/coalesce-check
git diff --check
```

Note on TUI parallelism (`docs/implementation/12-taut-tui.md:564-568`,
`bin/record_tui_run.py:430-446`): the canonical retained-lock TUI parallel gate
uses `-n 2 --dist loadfile` (`-n auto` is explicitly forbidden by
`12-taut-tui.md:568`). Note on PostgreSQL (`[TAUT-11]`): live execution of
`uv run --directory extensions/taut_pg --extra dev pytest` and `uv run pytest-pg`
with `SIMPLEBROKER_PG_TEST_DSN` configured (0 skips on the new tombstone test)
is required before Slice 3 completion can be claimed.

## Independent Review Loop

- **Reviewer**: Tier-1 cross-family CLI reviewer (`codex`, outside the authoring
  Gemini family) selected from `docs/implementation/03-agent-inventory.md` and
  invoked in read-only mode per `skills/call-agent/SKILL.md` and
  `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` §2–§5.
- **Brief requirements**: Include the full `[THEORY-5.A1]`–`[THEORY-5.A6]`
  "Rejected alternatives in force" block, both whole-plan review lenses from
  `[DOM-11]` (expert-developer craft and CS/algorithmic principle), and the
  files touched by Slices 1–4.
- **Gate**: Plan flips from `draft` to `active` after the fresh-eyes review and
  independent outside-model plan review complete and all findings are
  dispositioned in the Review Log below. Completed implementation requires a
  second independent review pass before completion.

## Out of Scope

- Implementing the upstream SimpleBroker strict target-discovery seam for
  `[TAUT-3.2]` (owned by `docs/plans/2026-09-24-cli-read-delivery-and-agent-recipes-plan.md`)
  or modifying `../simplebroker`.
- Executing an owner-gated plan-retirement/deletion sweep (`skills/coalescing/SKILL.md` §4):
  Slice 4 updates `bin/coalesce-check` to report accurate plan-tier counts and
  reconciles the status index so the human owner has exact numbers when
  deciding whether to authorize a plan-harvest sweep.
- Unfinished slices or unrecorded hosted qualification gates of other active
  plans (`2026-08-24-command-runtime-findings-remediation-plan.md`,
  `2026-08-24-extension-seams-process-containment-coverage-plan.md`,
  `2026-08-25-semantic-compatibility-hardening-plan.md`,
  `2026-09-28-simplification-and-hot-path-plan.md`,
  `2026-09-24-identity-claim-boundary-plan.md`,
  `2026-07-28-taut-mcp-dual-era-sessionless-plan.md`).

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| None | — | — | — | None |

## Review Log

(append-only)

- 2026-10-15 — **Fresh-Eyes Review** (authoring agent, two-lens pass per
  `[DOM-11]` + path/citation existence check):
  - *Existence check*: Ran `tests.test_docs_references` path and citation
    scanners directly over `docs/plans/2026-10-15-deep-review-remediation-plan.md`.
    Caught `test_doctor.py` (actual file is `tests/test_system_doctor.py`)
    and a capitalization typo (`check-Plan-status-index`); corrected both
    and verified 0 path or citation errors.
  - *Lens 1 (Expert-developer craft)*: Verified `[RUFF-SUP-085]` in
    `docs/specs/01-development-documentation-operating-model.md:580` is pinned
    to `TautApp.on_terminal_attach_confirmation_request` with `BLE001=1`.
    Routing `decide_offer`'s second-step `present()` through a `run_guarded`
    closure defined inside `on_terminal_attach_confirmation_request` reuses that
    single approved `except BaseException` boundary without adding a `# noqa`
    comment or changing the suppression registry. Verified that keeping
    `len(lines) == height` with `""` outside `[start_y, end_y]` in
    `TautTranscript.get_selection` preserves `Selection.extract()` behavior
    across all boundary cases (`start=None`, `end=None`, trailing blank row).
  - *Lens 2 (CS / algorithmic principle)*: Identified that in
    `TuiSummonOperations.stop_owned_and_wait()`, `supervise()` previously read
    `record.handle` and called `record.cancel.set()` outside `self._lock`, and
    `request_owned_stops()` did not set `record.cancel.set()`. Tightened
    Slice 1 so setting `record.cancel.set()` and reading `record.handle` happen
    under `self._lock`, establishing a single mutual-exclusion linearization
    point with `on_ready(handle)`.
- 2026-10-15 — **Tier-1 Independent Plan Review Round 1** (`codex exec -s read-only`,
  non-Gemini family, completed in 252s with verdict **REVISE**, 8 P2 and 2 P3
  findings). All 10 findings verified against the codebase and **Accepted**:
  1. *F1 (P2 — `_DetachChordMatcher` test oracle)*: Accepted. `_pending_deadline`
     is the 100 ms CSI-prefix ambiguity deadline, cleared at
     `extensions/taut_summon/taut_summon/_pty.py:782` when an enhanced-key atom
     completes. Updated Test 3C-1 to use `_MatcherClock` and `_semantic_matcher(clock)`,
     assert `matcher.pending_deadline is None` and `matcher.expire() == b""`
     after advancing `clock.now += 0.5`, assert the second atom detaches, and
     mutation-check removal of `self._pending_deadline = None` at `_pty.py:782`.
  2. *F2 (P2 — Tombstone SQL column/placeholder count and method name)*:
     Accepted. Both methods are named `_delete_in_generation` and insert 8
     columns: `VALUES (?, ?, ?, '', 0, ?, ?, 0)` in `taut/search/_sqlite.py:360`
     and `VALUES (?, ?, ?, '', 0, ?, ?, FALSE)` in
     `extensions/taut_pg/taut_pg/_search.py:319`, binding
     `(generation, message_ts, thread, SEARCH_PROJECTION_VERSION, revision)`.
     Added executed PostgreSQL regression coverage in
     `extensions/taut_pg/tests/test_pg_integration.py` and its verification
     command.
  3. *F3 (P2 — Test 1B synchronous vs. deferred callback schedule)*: Accepted.
     Updated Test 1B to capture `(screen, decide_offer)` on the first
     `push_screen`, let `on_terminal_attach_confirmation_request` return, and
     then invoke `decide_offer(True)` asynchronously so the test fails on
     unchanged code, while `run_guarded` protects prompt construction and both
     modal pushes.
  4. *F4 (P2 — Exact git SHAs)*: Accepted. Corrected full `HEAD` SHA to
     `22468ee291b6d6aec3ce74ebf2a25cc3dd43c983`, `v0.9.9` to `c894059`
     (implementation commits `39179c1` and `bd8ff4e`), `v0.8.2` to `a12a8fa`,
     and `2026-08-25-semantic-compatibility-hardening-plan.md` spec promotion
     commit to `dcf5d0b`.
  5. *F5 (P2 — Completion flips require recorded qualification evidence)*:
     Accepted. Scoped the status-index flip to `completed` solely to
     `2026-07-29-taut-chat-pypi-publication-plan.md` (whose Execution Log at
     `lines 824-838` already records all 4 release gate runs and `v0.8.2`
     verification), while keeping `2026-09-28-simplification-and-hot-path-plan.md`,
     `2026-09-24-identity-claim-boundary-plan.md`, and
     `2026-07-28-taut-mcp-dual-era-sessionless-plan.md` at `active` until their
     hosted Windows/OS/PostgreSQL qualification evidence is recorded in their
     Execution Logs.
  6. *F6 (P2 — `tests/test_coalesce_check.py` firing tests and shallow-clone order)*:
     Accepted. Specified firing tests in `tests/test_coalesce_check.py` for
     normal and shallow-clone plan-count reporting and malformed
     `## Plan Status Index` failure (evaluated before the shallow-clone early
     return), and added `tests/test_coalesce_check.py` to Verification and Gates.
  7. *F7 (P2 — Locking invariant proof, `request_owned_stops()`, and parallel TUI gate)*:
     Accepted. Added Test 1A-2 covering `request_owned_stops()` and lock
     interleaving plus a lock-removal mutation check, and added the parallel
     TUI suite to Verification and Gates.
  8. *F8 (P2 — Per-option render count and `Selection` boundary matrix)*:
     Accepted. Updated Test 2A to count `Visual.to_strips` calls per option and
     assert each overlapped option is rendered once (even when wrapped across
     multiple lines), and added Test 2B covering `start=None`, `end=None`,
     out-of-range `end.y`, wrapped lines, and trailing blank rows.
  9. *F9 (P3 — `TuiSummonInteraction` / `_ScopedSummonInteraction` class names)*:
     Accepted. Replaced the non-existent `_TerminalLeaseCoordinator` name with
     the actual `TuiSummonInteraction` and `_ScopedSummonInteraction` classes.
  10. *F10 (P3 — `SummonDriver._accept_phase_result` diagnostic phase cleanup)*:
      Accepted. Clarified that `_owner_turn()` already checks `self._shutdown.is_set()`
      before spawning, so guarding `if not self._shutdown.is_set(): self._owner_phase = "spawn-ready"`
      after `self._pending_setup_recovery_attach = False` is diagnostic phase-state
      hygiene that preserves setup-recovery decline behavior.
- 2026-10-15 — **Tier-1 Independent Plan Review Round 2** (`codex exec -s read-only`,
  completed in 83s): confirmed F1, F3, F4, F5, F9, and F10 resolved and raised 4
  precision follow-ups on F7, F8, F2, and F6. All 4 verified and **Accepted**:
  1. *R2-1 (P2 on F7 — explicit parallel flags for `taut-tui`)*: Accepted with
     repository-contract alignment. `extensions/taut_tui/pyproject.toml` has no
     default `-n` flag, and `docs/implementation/12-taut-tui.md:564-568` +
     `bin/record_tui_run.py:430-446` specify `-n 2 --dist loadfile` as the
     canonical parallel TUI gate (`-n auto` is prohibited for `taut-tui`).
     Updated Verification and Gates to `uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests -n 2 --dist loadfile`.
  2. *R2-2 (P2 on F8 — 3-row selection across 2 wrapped lines + 1 neighbor)*:
     Accepted. Updated Test 2A to select 3 virtual rows (2 rows of the wrapped
     option + 1 row of its neighbor) while asserting `len(calls) == 2` so the
     test fails if per-option memoization is omitted.
  3. *R2-3 (P2 on F2 — unconditional PG unit proof + non-waivable live PG run)*:
     Accepted. Added an unconditional DSN-independent recording-session unit
     test in `extensions/taut_pg/tests/test_pg_integration.py` AND required live
     PostgreSQL execution (`SIMPLEBROKER_PG_TEST_DSN` set, 0 skips on the new
     integration test) before Slice 3 can be declared complete.
  4. *R2-4 (P3 on F6 — include `superseded` rows in `test_coalesce_check.py`)*:
     Accepted. Added `superseded` (`exemplar=yes` and `exemplar=no`) to the
     Test 4B status-index fixture.
- 2026-10-15 — **Tier-1 Independent Plan Review Round 3** (`codex exec -s read-only`,
  completed in 28s): **Verdict: APPROVE** (0 findings). Confirmed R2-1 through
  R2-4 resolved cleanly against the repository contract.

## Execution Log

(append-only)

- 2026-10-15 — Plan authored at baseline `22468ee291b6d6aec3ce74ebf2a25cc3dd43c983`
  from verified deep-dive review findings across core, `taut-pg`, `taut-summon`,
  `taut-mcp`, `taut-tui`, and repository documentation/coalescing gates.
- 2026-10-15 — Fresh-eyes review completed; all path and citation claims inside
  the plan verified against the working tree.
- 2026-10-15 — Tier-1 outside-model (`codex`) Round-1, Round-2, and Round-3
  plan reviews completed with final verdict **APPROVE**; all findings verified
  against the working tree and incorporated; plan status promoted to `active`.

## Fresh-Eyes Review

Completed on 2026-10-15 before external review dispatch and updated after Round-1
and Round-2 review incorporation. Key risks checked for a new engineer picking up
this plan cold:

1. **Linearization of `on_ready`, `request_owned_stops`, and `stop_owned_and_wait` in Slice 1**:
   Checking `current.cancel.is_set()` inside `on_ready` is necessary but not
   sufficient if `stop_owned_and_wait` or `request_owned_stops` checks
   `record.handle` and sets `record.cancel.set()` outside `self._lock`. Task 2
   centralizes both under `_cancel_and_collect_handles()` holding `self._lock`.
2. **Deferred modal callback schedule and `[RUFF-SUP-085]` in Slice 1**:
   Test 1B must invoke `decide_offer(True)` after
   `on_terminal_attach_confirmation_request` returns so it exercises the
   asynchronous dismissal path, and `run_guarded` reuses the single approved
   `BLE001=1` suppression in `TautApp.on_terminal_attach_confirmation_request`.
3. **Line-index preservation and per-option memoization in Slice 2**:
   `Selection.extract()` indexes into `rendered.splitlines()` by virtual `y`.
   Filling `""` outside `[start_y, end_y]` while keeping `len(lines) == height`
   and memoizing `Visual.to_strips()` by `option_index` renders each selected
   option once (verified by selecting 3 virtual rows spanning 2 rows of a
   wrapped option and 1 row of its neighbor) and preserves exact extraction
   semantics across all boundary cases.
