# Taut TUI Action Applicability Authority Plan

Date: 2026-08-14

Status: completed

Owner: Taut maintainers

Class: 5 — normative TUI contract correction with user-visible behavior changes

Plan type: implementation with spec revision

Hardening: required — one semantic decision must remain consistent across palette,
mouse, keyboard, context, and central-dispatch routes

## Goal

Make each non-Summon `ActionInputSpec.context` tuple the sole declaration of
semantic TUI action applicability. A pure evaluator will turn current visual
facts into either an enabled result or the first unmet requirement and its
user-facing reason. The command palette and central dispatcher will consume
that result. Existing mouse controls retain their presentation policy and
cannot bypass the central guard. Route producers and handlers will no longer
maintain per-action applicability policy.

The change closes the current contract gap in which `forms.py` declares that
`message.send` requires both an active target and a draft while
`TautApp._action_disabled_reason()` checks only the active target. It also
promotes channel-only scope and first-failure reason order into explicit,
firing behavior.

## Source Documents

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], and [DOM-15]
- `docs/specs/10-taut-tui.md` [TUI-2.2], [TUI-7.1], and [TUI-13.2]
- `docs/implementation/12-taut-tui.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/plans/2026-08-14-taut-tui-action-route-contract-plan.md`

## Classification and Promotion

This is Class 5 under [DOM-15]. It changes normative applicability semantics,
not just internal structure. It is also risky under the plan-hardening rules:
the same decision crosses independent input routes, changes visible enabled
state and reasons, and must still be rechecked at dispatch time to prevent
stale or programmatic invocations from bypassing the policy.

`docs/specs/10-taut-tui.md` remains the active specification. Use promotion
strategy A from [DOM-5]: review and edit the active spec before implementation.
Do not add implementation links or claim the new contract is shipped until the
firing gates pass.

## Spec Baseline

The exact baseline for the proposed edit to `docs/specs/10-taut-tui.md` is:

`c88c1382952571bb630902357e845946154db0f3`

Before promoting the delta, compare the current spec with that baseline. If
[TUI-2.2], [TUI-7.1], or [TUI-13.2] changed in a way that conflicts with the
text below, stop and revise this plan rather than applying the prose
mechanically.

## Proposed Spec Delta

After the first paragraph of [TUI-2.2], add:

> For every non-Summon action, the action input contract's ordered context
> requirements are the sole TUI declaration of semantic applicability. One
> TUI-owned evaluator maps current visual facts to those requirements and
> returns either enabled or the human reason for the first unmet requirement.
> Palette entries and central dispatch consume that result; route producers and
> handlers do not maintain per-action applicability sets. Existing control
> visibility remains presentation policy and cannot bypass central dispatch.
> Summon package availability remains capability filtering rather than a
> context requirement. Handler checks may defend against stale state or domain
> races, but they must not define a broader applicability policy.

After the first paragraph of [TUI-7.1], add:

> Context requirements are evaluated in declared order. The closed visual facts
> are: selected navigation target, active conversation, active channel,
> selected current message, selected search result, and nonblank draft for the
> active conversation. `message.send` requires an active conversation followed
> by a nonblank draft; channel-context actions require an active channel. The
> first unmet requirement supplies the disabled reason. Layout visibility and
> mode-specific binding eligibility are presentation concerns and do not
> redefine semantic applicability.

Add this firing obligation to [TUI-13.2]:

> - every declared action-context requirement, with satisfied and unsatisfied
>   firing cases; exact per-action requirement tuples driving the pure
>   evaluator; palette enabled/reason state and central dispatch agreeing for
>   the same visual facts; and each existing mouse action control unable to
>   bypass a disabled result;

The owner acceptance gate is explicit: a maintainer must accept this exact
semantic delta before Task 2 edits the active spec. Wording changes are allowed
only if they preserve one declaration authority, ordered first-failure reasons,
central dispatch enforcement, and the separate Summon capability boundary.

## Context and Key Files

Read these files before implementation:

- `extensions/taut_tui/taut_tui/forms.py`: owns `ContextRequirement`,
  `ActionInputSpec`, the complete non-Summon input-spec table, and visual
  preflight. This module should become deeper by also owning the pure
  requirement evaluator. Do not add a pass-through applicability module.
- `extensions/taut_tui/taut_tui/actions.py`: owns the closed action vocabulary,
  route eligibility, invocation structure, and `ActionContext`. Route context
  is not the same thing as a snapshot of mutable visual applicability facts.
- `extensions/taut_tui/taut_tui/app.py`: adapts Textual state to the pure facts;
  renders palette and contextual controls; and centrally dispatches all action
  invocations. Its applicability adapter must stay thin.
- `extensions/taut_tui/taut_tui/models.py`: owns `VisualState`, current target,
  selected message, and per-target drafts.
- `extensions/taut_tui/tests/test_tui_forms.py`: currently proves exact declared
  tuples but not their behavior.
- `extensions/taut_tui/tests/test_tui_app.py`: owns real Textual palette and
  mouse-affordance coverage.
- `extensions/taut_tui/tests/test_tui_action_routes.py`: exhaustive
  `ActionId × ActionRoute` producer gate. Preserve its completeness.
- `extensions/taut_tui/tests/test_tui_action_handlers.py`: real domain-handler
  firing gate. Preserve its complete action inventory and SQLite proof.

The current split is:

1. `forms.py` says which context each non-Summon action needs.
2. `_action_disabled_reason()` independently repeats per-action policy for the
   palette and omits `DRAFT`.
3. `_update_context_affordances()` makes a third set of state decisions for
   contextual controls.
4. Handlers contain defensive checks after dispatch.

Only item 1 should remain declarative policy. Items 2 and 3 become consumers of
that policy. Item 4 remains defense against state changes and domain races.

## Required Comprehension Checks

Before editing code, the implementer must record answers to these questions in
the Implementation Log:

1. Why can `message.send` currently appear enabled with a blank draft?
   Expected: its input spec declares `DRAFT`, but the app's hard-coded palette
   policy checks only whether an active conversation exists.
2. Why must `conversation.open` route context be projected before dispatch
   applicability is evaluated? Expected: navigation routes supply a target in
   `ActionContext`; central dispatch currently projects that target into
   `selected_navigation`, which is the fact the input requirement evaluates.
3. Is a handler guard a second applicability authority? Expected: no. It may
   reject stale state or a domain race, but it must not enable behavior that the
   shared evaluator disables or define a broader per-action policy.
4. How are Summon actions handled? Expected: unavailable Summon actions are
   removed by capability filtering. Registered Summon actions stay outside the
   complete non-Summon input-spec table. A missing core input spec is a
   programming error, not an implicit enabled result.

Wrong, uncertain, or unrecorded answers block implementation until the relevant
source and spec sections are reread and the corrected answers are logged.

## Locked Design

Deepen `forms.py` with these concepts; exact private field names may change if
tests preserve the contract:

- Add `ContextRequirement.ACTIVE_CHANNEL`. Channel-only actions declare it
  instead of generic `ACTIVE_TARGET`; satisfying it implies an active target.
- Define `DRAFT` as nonblank text for the active conversation after stripping
  whitespace.
- Add one immutable facts value, such as `ActionApplicabilityFacts`, containing
  only booleans for selected target, active target, active channel, selected
  current message, selected search result, and nonblank active-target draft.
- Add one immutable result, such as `ActionApplicability`, that exposes enabled
  state and, when disabled, the human reason for the first unmet requirement.
- Add one pure `evaluate_action_applicability(action_id, facts)` function. It
  returns enabled for a registered `requires_summon` action because availability
  was already handled by capability filtering. For every other registered
  action, it reads `input_spec(action_id).context` in declared order and
  contains the sole mapping from requirements to facts and reasons. A missing
  non-Summon input spec remains fatal.

Use these stable reasons unless the accepted spec delta changes them:

| Requirement | Disabled reason |
|---|---|
| `SELECTED_TARGET` or `ACTIVE_TARGET` | `Select a conversation first` |
| `ACTIVE_CHANNEL` | `Select a channel first` |
| `SELECTED_MESSAGE` | `Select a message first` |
| `SELECTED_SEARCH_RESULT` | `Select a search result first` |
| `DRAFT` | `Enter a message first` |

`TautApp` gets one thin current-facts adapter. It derives facts from existing
state without expanding `ActionContext`:

- selected target: `visual_state.selected_navigation is not None`
- active target: `visual_state.active_conversation is not None`
- active channel: active target exists and its `_target_kinds` entry is
  `"channel"`
- selected current message: the selected id exists in `_message_rows`
- selected search result: `_selected_search_hit is not None`
- nonblank draft: the active target's stored `DraftState.text.strip()` is not
  empty

The palette reads the shared result. Central dispatch re-evaluates it after any
route-supplied context projection and before opening a form or invoking a shell
or domain handler. Existing mouse-control display rules remain unchanged;
central dispatch is their applicability enforcement and prevents direct or
programmatic bypass. Handler-local guards remain defensive but are not copied
into the evaluator.

## Invariants and Constraints

- The action registry remains the authority for action identity and route
  eligibility. This plan changes context applicability only.
- Every non-Summon action has exactly one `ActionInputSpec`. Completeness stays
  mechanically tested.
- The ordered `context` tuple is executable policy. Requirement order controls
  the first disabled reason.
- Summon availability remains capability filtering through
  `available_action_specs`; it is not encoded as a context requirement.
- A programmatic, keyboard, context, palette, or mouse invocation cannot bypass
  a disabled central-dispatch result.
- Layout visibility and Textual binding eligibility remain presentation policy.
  Existing mouse visibility rules stay unchanged; hidden or directly invoked
  controls cannot make an action semantically applicable.
- `ActionContext` must not absorb mutable draft, message-row, target-kind, or
  search-selection state merely to avoid a small app adapter.
- Selected-message applicability means the selected id is present in the
  current message rows, not merely non-null.
- No command identity, route matrix, confirmation policy, domain behavior,
  persistence schema, dependency, or public extension protocol changes.
- Disabled dispatch must not open a form, invoke a Summon shell action, or call
  a domain handler. It must emit the same reason the palette displays.
- Tests must exercise real evaluator and app composition. A mirror of the
  requirement table in a test helper is not evidence of integration.

## Hidden Couplings and Failure Modes

- `conversation.open` has route-supplied target context. Evaluating too early
  would reject valid navigation and search routes.
- Textual controls can be invoked directly in tests or by code even when their
  presentation is hidden. Central dispatch is the final guard.
- Draft state is per target. Reading only the composer widget or any draft would
  make target switches produce a false enabled result.
- `_target_kinds` may not contain a newly observed target yet. Missing kind must
  fail closed for `ACTIVE_CHANNEL` while still allowing generic active-target
  actions.
- A selected message id can become stale after refresh. Membership in
  `_message_rows` is required at evaluation time.
- Changing button display and disabled state together can cause layout jumps.
  Keep existing display policy unless a real Textual test proves a change is
  required.
- Silently treating an unknown non-Summon input spec as enabled would recreate
  the split authority. Preserve the fatal completeness boundary.

## Rollout, Rollback, and One-Way Doors

This is a single-package behavior correction with no data migration or external
protocol transition. Roll it out atomically in one TUI commit after the spec,
implementation, tests, and docs agree. There is no compatibility window in
which old and new applicability policies should coexist.

Rollback is code-only: revert the implementation commit and its normative spec
delta together. There are no one-way doors, stored-data transforms, or version
negotiation effects. Do not retain a fallback to `_action_disabled_reason()`;
dual policy is the defect this plan removes.

The post-change success signal is deterministic local and CI evidence: the full
TUI suite passes, exhaustive route and handler inventories remain complete,
and focused real-Textual tests show the same enabled state or reason in palette,
mouse controls, and central dispatch. There is no production telemetry for
this local UI behavior.

## Dependency-Ordered Tasks

### Task 1: Review and accept the contract delta

Read first:

- `docs/specs/10-taut-tui.md` [TUI-2.2], [TUI-7.1], [TUI-13.2]
- this plan's proposed spec delta, locked design, and invariants

Actions:

1. Compare the active spec to the recorded baseline.
2. Run an independent plan review with a Claude-family agent when available;
   otherwise use a maintainer who did not author the plan and record the
   substitution.
3. Obtain maintainer acceptance of the semantic delta.
4. Record review findings and accepted wording in the Review Log.

Stop gate: unresolved disagreement about declaration ownership, reason order,
Summon filtering, or dispatch enforcement blocks all spec and code edits.

Done signal: accepted wording and review disposition are recorded below.

### Task 2: Promote the active TUI specification

Files:

- `docs/specs/10-taut-tui.md`

Actions:

1. Apply the accepted [TUI-2.2], [TUI-7.1], and [TUI-13.2] delta.
2. Keep the plan backlink and record the exact promotion commit in the
   Implementation Log after commit authorization is given.
3. Run documentation reference gates before behavior work.

Stop gate: broken stable references or an unreviewed semantic change blocks
implementation.

Done signal: the active spec is the unambiguous authority for the red tests.

### Task 3: Add failing applicability tests

Files:

- `extensions/taut_tui/tests/test_tui_forms.py`
- `extensions/taut_tui/tests/test_tui_app.py`
- `extensions/taut_tui/tests/test_tui_action_routes.py`
- `extensions/taut_tui/tests/test_tui_action_handlers.py`

Actions:

1. Extend the exact requirement inventory for `ACTIVE_CHANNEL` and preserve a
   firing case for every declared requirement.
2. Add pure evaluator cases for every requirement satisfied and unsatisfied,
   plus multi-requirement first-failure ordering, registered Summon pass-through,
   and the existing fatal non-Summon completeness gate.
3. Add real Textual cases for no target, active DM, active channel, stale and
   current message selection, missing and present search selection, and blank,
   whitespace-only, and nonblank active-target drafts. Pin a channel-only action
   with no active conversation to `Select a channel first`.
4. Prove palette enabled state/reason and central dispatch agree for the same
   visual facts. A disabled dispatch must not open a form or reach its handler.
5. Preserve existing mouse-control visibility and prove a directly invoked
   control cannot bypass central dispatch. No new per-button disabled-state
   policy is required.
6. For `conversation.open`, prove agreement after the navigation route projects
   its highlighted target; do not compare palette and dispatch snapshots that
   intentionally contain different route facts.
7. Update exhaustive route fixtures only where newly explicit prerequisites
   require it. Do not narrow the route or handler inventories.

Red gate: run the focused command in the Testing Plan against the baseline and
record the expected failures. If the new tests pass before implementation, they
do not prove this defect; strengthen them before proceeding.

Done signal: failures isolate the missing evaluator integration and draft/
channel-policy divergence without unrelated failures.

### Task 4: Implement the pure authority in `forms.py`

Files:

- `extensions/taut_tui/taut_tui/forms.py`
- `extensions/taut_tui/taut_tui/__init__.py` only if the package already exports
  adjacent action-input types there

Actions:

1. Add `ACTIVE_CHANNEL`, the immutable facts/result values, stable reason
   mapping, and pure evaluator.
2. Change channel-only input specs from `ACTIVE_TARGET` to `ACTIVE_CHANNEL`.
3. Preserve the complete non-Summon input-spec assertion and fail closed on a
   missing core spec.
4. Make focused pure tests green before app integration.

Stop gate: any need for Textual objects, domain clients, or mutable app state in
the evaluator means the boundary is wrong; stop and revise the design.

Done signal: pure tests prove every requirement and ordered reason.

### Task 5: Replace app-local policy with thin consumers

Files:

- `extensions/taut_tui/taut_tui/app.py`
- `extensions/taut_tui/taut_tui/models.py` only if an existing read-only draft
  accessor is needed; do not move applicability policy into the model

Actions:

1. Add the thin current-facts adapter described in Locked Design.
2. Replace `_action_disabled_reason()` per-action sets with the shared result;
   remove the method if no thin adapter remains useful.
3. Evaluate centrally after route context projection and before form, shell, or
   domain dispatch. Use the evaluator's reason for the rejection notice.
4. Preserve existing mouse-control visibility and rely on the central guard to
   reject any disabled direct invocation.
5. Retain local handler checks only where they guard stale state or domain race.
   Do not duplicate requirement-to-reason policy in handlers.

Stop gate: any per-action applicability set, switch, or reason map remains in
`app.py`; or any route can reach a handler while the evaluator says disabled.

Done signal: focused real Textual, route, and handler tests pass with one policy
source.

### Task 6: Align implementation documentation and close verification

Files:

- `docs/implementation/12-taut-tui.md`
- this plan
- related repository maps only if ownership actually changes

Actions:

1. Explain why ordered input requirements own semantic applicability, why app
   adaptation stays thin, and why handler guards remain defensive.
2. Record implementation commits, red/green evidence, full gate output,
   independent review findings, deviations, and residual risks.
3. Run the complete verification suite and a final independent review.
4. Change the plan index to `completed` only after all gates pass and the
   finished slice is committed with owner authorization.

Stop gate: spec, implementation doc, tests, and code describe different owners
or semantics; or the completed state is uncommitted.

Done signal: all completion gates below are met and `git log` shows the landed
implementation commit.

## Testing Plan

Red-green TDD is required. The substitute-proof exception does not apply.

Use pure unit tests for requirement mapping and ordered reasons. Use real
Textual `App.run_test()` composition for palette, controls, state transitions,
and dispatch. Keep real SQLite/domain paths in handler tests where an effect is
asserted.

Do not mock:

- `ActionInputSpec.context` or the evaluator
- the `TautApp` visual-facts adapter
- palette construction or central dispatch
- route producers in the exhaustive route matrix
- the real domain path in concrete-handler firing tests

A narrow domain spy is allowed only to prove that a disabled invocation made no
domain call. It must sit beyond real palette/dispatch composition and cannot
replace evaluator or route behavior.

Focused red/green command:

```bash
uv run --project extensions/taut_tui --extra dev --locked pytest -q \
  extensions/taut_tui/tests/test_tui_forms.py \
  extensions/taut_tui/tests/test_tui_app.py \
  extensions/taut_tui/tests/test_tui_action_routes.py \
  extensions/taut_tui/tests/test_tui_action_handlers.py \
  -k 'applicab or context or palette or disabled or route'
```

Full TUI and static gates:

```bash
uv run --project extensions/taut_tui --extra dev --locked pytest -q \
  extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev --locked ruff check \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev --locked ruff format --check \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev --locked mypy \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests \
  --config-file extensions/taut_tui/pyproject.toml
```

Documentation and repository gates:

```bash
uv run bin/check-doc-paths
uv run bin/check-cli-claims
uv run bin/check-plan-status-index
uv run --locked pytest -q tests/test_docs_references.py
git diff --check
```

## Verification Evidence Required

Record concrete observed results, not just commands:

- exact changed files
- focused red failures before implementation and green result after it
- full TUI suite count and result
- static and documentation gate results
- palette reason for each unsatisfied requirement
- active DM versus active channel behavior for channel-only actions
- blank, whitespace-only, and nonblank Send behavior for the active target
- stale selected-message behavior
- proof that disabled central dispatch opens no form and invokes no handler
- proof that exhaustive route and concrete-handler action inventories did not
  shrink
- final `git status`, `git diff --check`, and implementation commit from
  `git log`

A short manual smoke may confirm Ctrl-P and visible mouse controls present the
same state, but it cannot replace the real Textual tests.

## Independent Review Loop

Run one review after the spec and red tests, and another after the integrated
green slice. Use a Claude-family agent when available; otherwise use a
maintainer who did not author the plan and record why the substitution was
necessary. The reviewer must read this plan, including Proposed Spec Delta,
`docs/specs/10-taut-tui.md`, `extensions/taut_tui/taut_tui/forms.py`,
`extensions/taut_tui/taut_tui/app.py`, and the four TUI test modules named in
Context and Key Files.

Review prompt:

> Review the Taut TUI action-applicability change against [TUI-2.2], [TUI-7.1],
> [TUI-13.2], and the locked design in
> `docs/plans/2026-08-14-taut-tui-action-applicability-authority-plan.md`.
> Look for duplicated per-action policy, incorrect requirement order, route
> context evaluated too early, Summon capability conflation, stale visual facts,
> mouse or programmatic dispatch bypasses, weakened exhaustive matrices, and
> mocks that replace the contract under test. Report findings by severity with
> exact paths and lines; state explicitly if none remain.

The owner must disposition every finding as accepted and fixed, rejected with
evidence, or deferred with an explicit residual risk. A finding that exposes a
contract ambiguity returns the work to Task 1.

## Out of Scope

- redesigning command identity, families, or route eligibility
- changing CLI command applicability or broker/domain semantics
- redesigning the TUI layout or making every binding dynamically disappear
- moving mutable visual facts into `ActionContext`
- making Summon package availability an `ActionInputSpec` requirement
- replacing handler defenses against races with optimistic assumptions
- adding telemetry, persistence, dependencies, or extension APIs

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| | | | | |

Any implementation deviation that changes authority, semantics, rollout, or
test realism requires plan and spec review before code proceeds.

## Review Log

| Date | Reviewer | Scope | Findings and disposition |
|---|---|---|---|
| 2026-08-14 | Author fresh-eyes pass | Plan structure, current ownership, spec delta, test and rollback design | No blocking issue found. The pass chose a deeper `forms.py` module over a new pass-through module and separated semantic applicability from layout visibility. Limitation: no second-agent reviewer was available during plan authorship; maintainer acceptance and an independent implementation review remain required. |
| 2026-08-14 | Claude 2.1.207, read-only plan review | Proposed delta, live seams, exhaustive route/handler matrices, and implementation sequence | PASS. Accepted P2-1: preserve mouse visibility and enforce at central dispatch, avoiding inert disabled wiring. Accepted P2-2: result exposes enabled/reason only. Accepted P2-3: pin no-target channel reason. Accepted P2-4: test `conversation.open` agreement after route projection. No P1 or blocker. |
| 2026-08-14 | Claude 2.1.207, read-only implementation review attempt 1 | Final uncommitted code, tests, docs, and verification evidence; 15-minute bound | No verdict. Provider failed after about three minutes with `API Error: Connection closed mid-response`; no findings were returned or inferred. One bounded retry authorized by the review runbook follows. |
| 2026-08-14 | Claude 2.1.207, read-only implementation review attempt 2 | Final uncommitted code, tests, docs, and verification evidence; 15-minute bound | No blocker and no P1/P2. F1 (`conversation.open` palette projection) is verified pre-existing and out of scope. F2 accepted: the closed `ActionId` enum plus exact non-Summon set equality makes a missing core spec structurally fatal. F3 accepted: remove the unreachable duplicate conversation reason branch. F4 accepted: add a direct same-facts palette-reason versus dispatch-output assertion. Round-2 review is limited to F3/F4. |
| 2026-08-14 | Claude 2.1.207, read-only implementation review round 2 | Accepted F3/F4 fixes only | PASS for both findings; no new defects. The central guard makes the `conversation.open` target assertion safe, and the real Textual test now proves the same blank-draft facts produce the palette reason and dispatch rejection without reaching the send handler. |

## Fresh-Eyes Review

The 2026-08-14 author pass reread the plan against the required plan sections
and hardening checklist. It corrected the execution-log requirement for the
comprehension gate, restored the prescribed spec-deviation table shape, named a
concrete independent reviewer family and fallback, and verified that every
task has a stop gate and observable done signal. No scope or architecture
change was needed. The later read-only Claude review closed that limitation
with a PASS and the four accepted refinements recorded above.

The implementation fresh-eyes pass compared every plan task with the current
diff and executable evidence. It confirmed there is no second applicability
set in `app.py`, the facts adapter contains no policy, Summon short-circuits
before the non-Summon table, route projection precedes evaluation, existing
mouse visibility is unchanged, and route/handler inventories did not shrink.
No reusable correction to the codebase-design or reviewer skills was exposed.

## Implementation Log

| Date | Commit | Slice | Verification |
|---|---|---|---|
| 2026-08-14 | uncommitted worktree based on `c88c138` | Maintainer acceptance and comprehension gate | User instruction `Please implement per plan` accepts the proposed semantic delta. Answers: Send is currently palette-enabled with a blank draft because app-local policy omits `DRAFT`; `conversation.open` must project its route target before evaluation; handler guards defend stale/domain state rather than own policy; unavailable Summon actions are capability-filtered while registered Summon actions bypass the non-Summon input table and a missing core spec remains fatal. |
| 2026-08-14 | promotion baseline: `c88c138` plus the uncommitted `docs/specs/10-taut-tui.md` worktree delta | Strategy A spec promotion | Accepted [TUI-2.2], [TUI-7.1], and [TUI-13.2] text promoted before behavior code; independent Claude plan review returned PASS with four accepted refinements. |
| 2026-08-14 | uncommitted | Pure applicability authority | Red: `test_tui_forms.py` failed collection because the evaluator interface did not exist. Green: all 17 form/input tests pass, including exact requirement tuples, all six satisfied/unsatisfied firing cases, first-failure order, and registered Summon pass-through. |
| 2026-08-14 | uncommitted | Textual consumers and central guard | Red: focused app tests reproduced the no-target channel reason drift and blank-draft mouse bypass. Green: the 75-case focused cross-route command passes; the full TUI suite reaches 100% with exhaustive route and handler matrices intact. Two old compose tests were corrected to establish their already-declared active-target prerequisite. |
| 2026-08-14 | uncommitted | Pre-review local verification | Full TUI suite passed from that code state. Ruff and format passed over 31 files; strict mypy passed over 31 source files; doc paths, CLI claims, plan index, 11 doc-reference tests, and `git diff --check` passed. Independent implementation review was pending at this checkpoint. |
| 2026-08-14 | uncommitted | Independent implementation review | First attempt returned no verdict after a provider disconnect. Bounded retry returned no blocker and no P1/P2; accepted F3/F4 cleanup passed targeted tests and read-only round-2 review with no new defects. Final-state suite and documentation gates are rerun after this log update. |
| 2026-08-14 | uncommitted | Post-review closure verification | Full TUI suite reached 100% after F3/F4. Ruff and format passed over 31 files; strict mypy passed over 31 source files; doc paths, CLI claims, plan index, 11 doc-reference tests, untracked-plan whitespace, `git diff --check`, and `coalesce-check` all passed. Worktree inspection found only the eight planned files and no remaining `_action_disabled_reason`. |
| 2026-08-14 | closure commit containing this plan | Owner-authorized closure | User instruction `Close and commit` authorizes the verified eight-file slice. The commit is verified through `git log` immediately after creation. |

## Completion Gate

Do not mark this plan completed until:

- the accepted normative delta is present in the active spec
- exact declared requirements drive one pure evaluator
- palette and central dispatch consume that result; existing mouse controls
  cannot bypass it
- handler checks are demonstrably defensive rather than policy authorities
- every requirement and listed edge case has a firing test
- exhaustive action-route and concrete-handler inventories remain intact
- focused red and green evidence, full TUI/static/doc gates, and residual risks
  are recorded
- implementation documentation explains ownership, boundaries, and tradeoffs
- independent review findings are closed or explicitly accepted
- the finished slice is committed with owner authorization and verified through
  `git log`

Current state: completed. Implementation, documentation, tests, independent
review, and owner-authorized commit closure are satisfied by the commit that
contains this plan.
