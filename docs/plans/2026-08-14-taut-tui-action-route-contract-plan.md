# Taut TUI Action Route Contract Plan

Status: completed. The product owner accepted the independently reviewed spec
delta, requested implementation, and authorized closure and commit on
2026-08-14.

Class: 5 — the work retains the 32-action inventory and its existing
reachability obligation, but it makes route metadata authoritative, defines
the meaning and precedence of each route, and makes palette membership exactly
route-driven. Those are normative and user-visible clarifications to
[TUI-2.2], [TUI-7.1], and [TUI-13.2], so [DOM-6]/[DOM-15] require a reviewed
spec delta before code.

Plan type: implementation with spec revision.

Hardening: N/A — no [DOM-5] risky trigger fires. The change does not alter a
CLI or storage shape, compatibility promise, persistence, cleanup, async
lifecycle, rollout order, or one-way door. Existing TUI background-work and
shutdown behavior are invariants, not edit targets.

## Goal

Make the native action registry executable rather than descriptive. Every
declared `ActionRoute` must constrain a production route, every `ActionId`
must have at least one real user-input route that reaches a concrete handler
or native form, and the command palette must contain exactly the currently
available actions that declare `PALETTE`. In particular, `command.open` must
remain reachable by keyboard and mouse without appearing inside the palette it
opens.

## Source Documents

- `docs/program-theory.md` [THEORY-1], [THEORY-4]
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md` §8, §10, §12, §13
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md` Rules 5–6 and Patterns 5–6
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/lessons.md`
- `docs/lessons.md` Golden Rules 6, 10, 11, and 13, plus entries after the
  current lessons watermark
- `docs/specs/10-taut-tui.md` [TUI-2.2], [TUI-2.3], [TUI-7.1], [TUI-8],
  [TUI-13.1], [TUI-13.2]
- `docs/implementation/12-taut-tui.md`, “Typed Actions and Native Screens”
- `docs/plans/2026-08-12-taut-tui-implementation-plan.md`, Tasks 3–6 and its
  action-shell completion evidence
- `docs/plans/2026-08-14-review-findings-remediation-plan.md`, to preserve the
  subsequently repaired TUI lifecycle behavior

[TUI-2.3] already requires a test that enumerates every action id and proves at
least one reachable gesture. The proposed delta below resolves the ambiguity
the current implementation exposed: what each route means, whether declared
routes are authoritative, and whether palette membership follows them.

## Spec Baseline

- `7ecd6c1f82f04cd3e695f6a68d91bc577fdda36b` —
  `docs/specs/10-taut-tui.md` at plan authoring time.

Promotion baseline: `7ecd6c1f82f04cd3e695f6a68d91bc577fdda36b` plus the
current worktree diff for `docs/specs/10-taut-tui.md`, which applies the exact
reviewed [TUI-2.2], [TUI-7.1], and [TUI-13.2] delta and retains the Related
Plans backlink. Replace this identifier with the landing commit SHA when one
exists.

Implementation after promotion is judged against that promotion baseline. Any
further intended-behavior change requires a Deviation Log row, exact revised
delta, independent delta review, and a new promotion baseline before dependent
code continues.

## Proposed Spec Delta

Promotion strategy: A — edit the active spec in place before implementation.
The new text defines behavior but makes no premature implementation-link
claim. The later code/test/documentation slice adds the reciprocal rationale
and evidence.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/10-taut-tui.md` | A — in-file text before implementation claims | [TUI-2.2], [TUI-7.1], [TUI-13.2] |

### [TUI-2.2] — insert after the first paragraph

> The registry's route set is authoritative composition data. A route names
> the production boundary that emits an action:
>
> - `PALETTE` means selection from the native command palette;
> - `NAVIGATION` means activation of a navigation-row target or navigation
>   empty-state action, regardless of whether Enter or a pointer activated it;
> - `CONTEXT` means activation from a contextual result or transient contextual
>   surface outside navigation and the palette;
> - `KEYBOARD` means a direct key binding or text-input submission owned by the
>   base application; and
> - `MOUSE` means an explicit base-screen mouse-parity action control outside a
>   semantic navigation, palette, or contextual surface, regardless of whether
>   pointer input or keyboard activation presses that focused control.
>
> Semantic surfaces take precedence over physical input provenance: a pointer
> activation in navigation is `NAVIGATION`, not an additional `MOUSE` route.
> A route producer must reject an action-route pair absent from the action's
> registry entry. Every declared pair has a firing producer test, and every
> action retains at least one fired route. Stale, non-required route claims are
> removed rather than satisfied by manufacturing a new affordance.

### [TUI-7.1] — insert after the first paragraph

> Palette entries are exactly the currently available native action specs whose
> declared routes include `PALETTE`; applicability controls whether such an
> entry is enabled, not whether an action from another route is inserted.
> `command.open` is intentionally absent from the palette it opens and remains
> reachable through its direct keyboard and mouse routes.

### [TUI-13.2] — replace the first matrix bullet

> - all action ids in [TUI-2.3], with each id driven from at least one real
>   route to a concrete handler outcome; every declared action-route pair driven
>   through its real producer to the central dispatcher; undeclared pairs
>   rejected; exact route-derived palette membership including exclusion of
>   `command.open`; and every destructive confirmation fired through its native
>   path;

## Context and Key Files

### Files to modify

- `extensions/taut_tui/taut_tui/actions.py`
  - Owns the closed `ActionId` vocabulary, `ActionRoute`, `ActionSpec.routes`,
    gesture registries, and typed invocation construction.
- `extensions/taut_tui/taut_tui/app.py`
  - Owns Textual keyboard, mouse, navigation, palette, and context producers;
    `_dispatch_action_invocation()` is the single convergence point;
    `_palette_entries()` currently ignores `ActionSpec.routes`.
- `extensions/taut_tui/tests/test_tui_actions.py`
  - Owns pure registry and gesture-contract tests. Its current “reachable”
    test proves only exact ids, one spec per id, and nonempty route metadata.
- `extensions/taut_tui/tests/test_tui_app.py`
  - Owns real Textual-pilot routing and public-domain outcome tests.
- `extensions/taut_tui/tests/test_tui_action_routes.py`
  - Owns the exact 54-pair real-producer gate and its inverse all-id route
    assertion.
- `extensions/taut_tui/tests/test_tui_action_handlers.py`
  - Owns the exact 32-id concrete-handler outcome gate, including native
    destructive confirmations and the TUI/Summon compositional proof.
- `extensions/taut_tui/tests/test_tui_forms.py`
  - Owns the closed form/direct input classification and may supply form
    assertions to the firing matrix without duplicating form definitions.
- `extensions/taut_tui/tests/test_tui_summon.py`
  - Owns `TuiSummonOperations` composition and deterministic controller-result
    fixtures. It supplies the TUI-owned side of the Summon action probes.
- `extensions/taut_summon/tests/test_controller.py`
  - Retains the real public `SummonController` plus scripted-child boundary.
    Re-run its focused start/list/status/stop coverage; do not copy its process
    lifecycle into the TUI route matrix.
- `docs/implementation/12-taut-tui.md`
  - Must explain the authoritative route boundary and the exhaustive firing
    gate after implementation.
- `docs/specs/10-taut-tui.md`
  - Receives the reviewed delta in the spec-promotion slice before production
    code changes.
- `docs/plans/README.md`
  - Owns this plan's lifecycle status.

### Current structure and hidden coupling

- `ActionRoute` and `ActionSource` currently contain the same five concepts,
  but only `ActionSource` travels with an invocation. Production code does not
  read `ActionSpec.routes`; only `ActionSpec.__post_init__()` and a static test
  require it to be nonempty.
- `available_action_specs()` filters only Summon availability. Consequently,
  `_palette_entries()` emits all non-Summon actions, including
  `command.open`, whose declared routes are only keyboard and mouse.
- Real route producers are distributed: `resolve_gesture()` owns normal-mode
  keys; `on_button_pressed()` and `on_click()` own explicit mouse controls;
  navigation activation owns navigation actions; `_complete_palette()` owns
  palette dispatch; `_complete_search()` and contextual controls own context
  dispatch. All must continue to converge at `_dispatch_tui_action()` and
  `_dispatch_action_invocation()`.
- Handler ownership is also distributed: native forms, shell actions, simple
  domain actions, context actions, system/Summon actions, and form-completion
  handlers. A registry-membership test cannot prove those branches exist.
- `ActionSpec.routes` is a claim about routes that really exist, not a demand
  to manufacture new controls. When the audit finds stale metadata and the
  spec does not require that route, remove the stale route. When the spec does
  require the route, implement and fire it.

### Required comprehension checks

Record the answers in the implementation log before editing. An incorrect
answer blocks implementation until the cited files are reread.

1. What currently causes `command.open` to appear in the palette?
   Expected: `_palette_entries()` iterates `available_action_specs()`, which
   filters only Summon availability and never checks `ActionRoute.PALETTE`.
2. What must an exhaustive action gate prove beyond registry membership?
   Expected: a real route produces the declared action, central dispatch
   selects a concrete handler or native form, and an observable postcondition
   prevents a no-op implementation from passing.
3. Does every declared route require a new UI affordance?
   Expected: no. Route metadata must describe existing or spec-required
   affordances. Stale, non-required claims are removed rather than implemented
   for their own sake.
4. Is a mouse double-click on a navigation row a `MOUSE` route?
   Expected after promotion: no. `NAVIGATION` is the semantic producer and
   takes precedence over the physical pointer input. `MOUSE` is reserved for a
   base-screen mouse-parity action control outside navigation, palette, and
   contextual surfaces; a focused control remains `MOUSE` when Enter presses
   it because Textual exposes the same `Button.Pressed` boundary.

## Invariants and Constraints

- Preserve the exact 32 identifiers and action families in [TUI-2.3]. Summon
  remains conditional on `taut-summon` availability; all core actions remain
  registered.
- Keep one typed invocation and one central dispatcher. Do not add a second
  palette-only or route-specific behavior implementation.
- Route metadata is authoritative in both directions:
  - a producer may emit an action only through a route declared by its spec;
  - a declared route must have a firing producer test or be removed as stale;
  - every action must retain at least one fired route.
- Do not treat route validation as authorization or domain validation. It is
  an internal composition invariant. Applicability, selected-target checks,
  confirmations, and public core/Summon validation remain with their current
  owners.
- The palette contains exactly available specs declaring `PALETTE`. It still
  shows disabled applicable actions with reasons, but it must not show actions
  that do not declare that route.
- `command.open` stays reachable through `:`/Ctrl-P and the command mouse
  affordance. Selecting a palette item must never recursively reopen the
  palette unless a future reviewed contract explicitly declares that route.
- Preserve vi/conventional parity, text-entry shielding, mouse optionality,
  exact-target confirmations, Summon conditionality, and all lifecycle fixes
  landed by the 2026-08-14 remediation plan.
- No new dependency, public extension protocol, generic router framework,
  dynamic plugin contribution surface, key remapping, or command-manifest
  rendering.
- Do not mock the action registry, route producer under test, central
  dispatcher, Textual event path, or SQLite domain operation claimed by a
  firing case. Narrow clocks, input data, terminal size, and external-provider
  behavior may use existing fixtures. Summon uses the explicit compositional
  proof below; neither side may patch away `TuiSummonOperations` or the public
  `SummonController` behavior it separately claims.
- No async ownership or cleanup logic should change. Any need to edit session,
  watcher, executor, reactor, terminal-lease, or Summon shutdown code is a
  stop-and-replan signal.
- Rollout is an ordinary package replacement with no mixed-version state or
  migration. Rollback is a code revert. There is no persistence or one-way
  door. Post-install success is the exact palette membership plus the full
  action firing matrix on the retained TUI environment.

## Action Firing Matrix

The implementation may group cases by fixture, but the gate must enumerate
every `ActionId` as a test parameter with one real route driver and a concrete
postcondition. A separate route-source matrix must fire every route declared
for every action. Existing focused tests may be reused as helpers, but a prose
cross-reference to scattered tests is not the gate.

| Actions | Required representative postcondition |
|---------|---------------------------------------|
| `workspace.initialize` | navigation leaves the uninitialized empty state through the native initialization handler |
| `identity.rejoin`, `identity.set-name`, `identity.set-persona` | the native form opens and successful submission is visible through the public client/session result |
| `identity.show` | the identity inspector renders public identity data |
| `conversation.open` | the selected public conversation becomes active |
| `channel.join`, `direct-message.start` | form submission creates/selects the public target |
| `channel.leave`, `channel.rename` | exact-target confirmation appears; acceptance performs the public mutation |
| `notifications.open`, `members.open` | the owning inspector renders the public result or contract-specific empty state |
| `channel.show-topic`, `channel.set-topic`, `channel.clear-topic` | inspector or public client shows the corresponding topic result |
| `compose.enter` | mode and focus move to the composer without submitting |
| `message.send`, `message.reply`, `message.react`, `message.delete` | real SQLite/public-client state shows the effect; deletion and other destructive paths fire confirmation |
| `search.open` | the native search surface opens |
| `search.open-result` | public `history_around()` result becomes the active anchored transcript without a search-owned cursor move |
| `system.doctor`, `system.dump`, `system.load-help` | the native system handler renders or creates its documented result; load-help does not execute load |
| `command.open`, `help.open` | the correct native surface opens through a declared non-recursive route |
| `application.quit` | the current quit gate is invoked; the test must not bypass active-operation blocking semantics |
| `summon.start` | the palette route opens `SummonStartScreen`; submission crosses the real `TuiSummonOperations.start()` adapter and records the readiness-owned run returned by the deterministic controller fixture |
| `summon.list` | the palette route crosses `TuiSummonOperations.submit_list()` and renders its controller result |
| `summon.status` | the named-action screen submits through `TuiSummonOperations.submit_status()` and renders the named result |
| `summon.dismiss` | the named-action screen renders exact-target confirmation; acceptance crosses `TuiSummonOperations.submit_stop()` and the deterministic controller records that name |

If one row cannot name a stable concrete postcondition without mocking the
handler it claims to prove, stop and split that action into a focused
real-boundary test before continuing. Do not downgrade the matrix to “method
was called” assertions.

Summon uses a narrow compositional proof because this plan changes TUI routing,
not Summon process lifecycle. The TUI matrix uses real `TuiSummonOperations`
with the existing deterministic controller-result fixture; it must observe
owned-run/readiness state or rendered controller results, not a patched app
method. The focused real `SummonController` scripted-child tests in
`extensions/taut_summon/tests/test_controller.py` independently fire
start/readiness, list/status, and stop. Both sides run in the final gate. A new
TUI-owned real child per action would duplicate lifecycle coverage without
strengthening the route-to-handler claim.

## Tasks

### 1. Promote the reviewed route contract before production edits

- Files: `docs/specs/10-taut-tui.md`, this plan, and the existing Related
  Plans backlink.
- Apply the exact `## Proposed Spec Delta` with promotion strategy A after the
  independent plan/delta review passes.
- Run `uv run bin/check-doc-paths`, the reference tests, the plan-index gate,
  and `git diff --check`. Record the promotion baseline identifier in
  `## Spec Baseline`.
- Do not add implementation-link claims or edit code in this slice. If the
  promoted wording differs materially from the reviewed delta, log and review
  that revision before continuing.
- Done: the active spec defines route meanings, semantic precedence, palette
  membership, and the declared-pair firing matrix; the promotion baseline is
  recorded and all documentation gates pass.

### 2. Record the failing contract before production edits

- Files: `extensions/taut_tui/tests/test_tui_actions.py`,
  `extensions/taut_tui/tests/test_tui_app.py`,
  `extensions/taut_tui/tests/test_tui_action_routes.py`, and
  `extensions/taut_tui/tests/test_tui_action_handlers.py`.
- Add a live palette assertion that the emitted ids equal the available specs
  declaring `PALETTE`; explicitly assert `command.open` is absent while its
  keyboard and mouse entry points remain present.
- Add a no-op-prevention test that dynamically enumerates production
  `ACTION_SPECS` and, for every `ActionRoute`, compares the route-aware query
  with the predicate `route in spec.routes`. Do not mutate/monkeypatch the
  registry and do not introduce a second expected-route manifest. A hard-coded
  `command.open` exclusion is not acceptable.
- Add an invocation test proving an undeclared source is rejected before
  central dispatch. It should fail on the current source-blind invocation
  constructor.
- Run the focused test selection and record the expected RED failures. If all
  tests pass on the baseline, the tests did not fire the reported defect and
  must be corrected before production changes.
- Done: the observed palette leak and source-blind invocation each have a
  distinct failing assertion.

### 3. Make route data authoritative at the production boundary

- Files: `extensions/taut_tui/taut_tui/actions.py`,
  `extensions/taut_tui/taut_tui/app.py`, and affected focused tests.
- Give `available_action_specs()` an explicit route filter or replace it with
  one clearly named route-aware query; retain Summon availability filtering in
  the same helper.
- Replace the duplicate internal `ActionSource` enum with `ActionRoute` and
  update every repository consumer. [TUI-2.2] owns an internal registry and
  defines no public contribution protocol; repository search at the baseline
  finds consumers only in `actions.py`, `app.py`, and the named TUI tests, so
  no compatibility alias is retained.
- Put undeclared-pair validation in `ActionInvocation.__post_init__()` so direct
  construction cannot bypass it. Keep `invoke_action()` as the ordinary
  constructor wrapper, not as a second policy owner.
- Remove `_dispatch_tui_action()`'s default source so every caller states its
  actual route. Update production and test call sites accordingly.
- Make `_palette_entries()` consume the route-aware registry query. Do not add
  an action-id exception or a second palette allowlist.
- Preserve current disabled-reason and scope calculation after filtering.
- Stop and re-evaluate if route checking must be bypassed for an internal call;
  that indicates the call's route or the metadata is wrong.
- Done: both RED regressions are GREEN, `command.open` remains keyboard/mouse
  reachable, and no production route can emit an undeclared action/source pair.

### 4. Audit and fire every declared route

- Files: `actions.py`, `app.py`, and the action-contract test owner selected in
  Task 2.
- Derive an exact `ActionId × ActionRoute` expectation from `ACTION_SPECS`.
  For each pair, drive the corresponding real producer: Textual pilot key,
  explicit mouse/control event, navigation activation, palette selection, or
  contextual surface/completion.
- Assert that each producer reaches the central dispatcher with the same
  action id and route. This route-source test may observe the typed invocation
  at the dispatcher boundary, but it must not construct the invocation
  directly.
- Remove stale route declarations when no producer exists and the spec does
  not require one. Implement a missing producer only when [TUI-8] or another
  active requirement requires it.
- Add the inverse gate: every `ActionId` has at least one fired route. This
  replaces the misleading `all(spec.routes)` reachability claim; keep the
  exact-id and duplicate-prevention assertions.
- Done: the parametrized route matrix contains no missing, extra, or no-op
  pairs, and deleting a producer or adding an unfired route makes the suite
  fail.

### 5. Fire every action through a concrete handler

- Files: the action-contract test owner, `test_tui_app.py`,
  `test_tui_forms.py`, and `test_tui_summon.py` only where their existing
  fixtures own the real boundary.
- Implement the `Action Firing Matrix` above as executable parametrized cases.
  The case registry itself must assert exact key equality with `set(ActionId)`
  so adding an enum member cannot silently omit proof.
- Drive each case from one route proved in Task 4, continue through
  `_dispatch_action_invocation()`, and assert the listed handler postcondition.
  Reuse real SQLite, public `TautClient`, Textual pilot, and the explicit
  Summon compositional proof defined above.
- Existing focused tests can supply helpers or be parametrized, but the exact
  case registry must remain mechanically enumerable. Do not satisfy a case by
  citing a test name in prose or by patching the handler method to append to a
  list.
- Fire every destructive confirmation through the native screen, including
  exact target text and both cancel/no-mutation and accept/mutation behavior.
- Characterization cases for already-correct actions may be GREEN on their
  first run. Record them as proof completion, not red-green evidence. Any
  behavior changed in Tasks 3–4 must retain a clean RED-before-GREEN record.
- Done: every id reaches a handler through a real route, and replacing any
  handler with the existing unhandled fallback or a no-op fails its case.

### 6. Reconcile durable documentation and close the review loop

- Files: `docs/implementation/12-taut-tui.md`, this plan,
  `docs/plans/README.md`, and the existing Related Plans backlink in
  `docs/specs/10-taut-tui.md`.
- Update the implementation note to explain route authority, route/source
  validation, palette filtering, and the two complementary gates: declared
  route reachability and concrete handler effects.
- Do not alter normative TUI text beyond the promoted delta unless a new
  deviation and independent delta review are recorded first.
- Inspect whether the defect yields a new durable lesson. Add one only if it is
  not already fully captured by Golden Rule 13 and engineering principle §12;
  duplication is not maintenance.
- Run all final gates, obtain independent completed-work review, resolve every
  finding, then record evidence and change the status index to `completed` only
  after the implementation is committed with owner authorization. Otherwise
  leave the plan `active` and report the uncommitted state honestly.
- Done: code, tests, implementation rationale, backlinks, status, and review
  evidence agree.

## Testing Plan

### Required real boundaries

- Textual's real `App.run_test()` and pilot for keyboard, mouse, navigation,
  palette, context, modal, and focus behavior.
- Real SQLite plus public `TautClient`/TUI domain owners for core action
  effects. Do not patch core methods whose effect is the case postcondition.
- Real `TuiSummonOperations` plus the deterministic controller-result fixture
  for the TUI-owned side of Summon actions, paired with the focused real
  `SummonController` scripted-child tests named above. Do not substitute a
  patched app handler on either side.
- Pure registry construction may stay a unit test, but it cannot substitute
  for a live route or handler case.

### Targeted red-green commands

Run from the repository root with the retained TUI environment:

```bash
extensions/taut_tui/.venv/bin/pytest -q \
  extensions/taut_tui/tests/test_tui_actions.py \
  extensions/taut_tui/tests/test_tui_app.py \
  extensions/taut_tui/tests/test_tui_action_routes.py \
  extensions/taut_tui/tests/test_tui_action_handlers.py \
  -k 'action or route or palette'
```

Record the exact failing node ids before Task 3 and the matching GREEN rerun
afterward. Keep both exhaustive gate owners in every focused run.

### Slice gates

```bash
extensions/taut_tui/.venv/bin/pytest -q \
  extensions/taut_tui/tests/test_tui_actions.py \
  extensions/taut_tui/tests/test_tui_action_routes.py \
  extensions/taut_tui/tests/test_tui_action_handlers.py \
  extensions/taut_tui/tests/test_tui_forms.py \
  extensions/taut_tui/tests/test_tui_domain.py \
  extensions/taut_tui/tests/test_tui_app.py \
  extensions/taut_tui/tests/test_tui_summon.py
extensions/taut_summon/.venv/bin/pytest -q \
  extensions/taut_summon/tests/test_controller.py \
  -k 'foreground_ready_callback_is_once or controller_empty_list or controller_lists_live or controller_status_and_stop'
extensions/taut_tui/.venv/bin/ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests
extensions/taut_tui/.venv/bin/ruff format --check extensions/taut_tui/taut_tui extensions/taut_tui/tests
extensions/taut_tui/.venv/bin/mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests
```

### Final gates

```bash
extensions/taut_tui/.venv/bin/pytest -q extensions/taut_tui/tests
extensions/taut_summon/.venv/bin/pytest -q \
  extensions/taut_summon/tests/test_controller.py \
  -k 'foreground_ready_callback_is_once or controller_empty_list or controller_lists_live or controller_status_and_stop'
extensions/taut_tui/.venv/bin/ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests
extensions/taut_tui/.venv/bin/ruff format --check extensions/taut_tui/taut_tui extensions/taut_tui/tests
extensions/taut_tui/.venv/bin/mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests
bin/check-plan-status-index
uv run bin/check-doc-paths
.venv/bin/pytest -q tests/test_docs_references.py tests/test_project_metadata_consistency.py
git diff --check
```

Success means all 32 ids are present exactly once in the firing case registry,
every declared route pair fires through a real producer, every action case
reaches its concrete postcondition, no undeclared source is accepted,
`command.open` is absent from palette results but opens from keyboard and
mouse, and the full retained TUI suite plus static/doc gates exit zero.

## Verification and Operational Evidence

- Per-task evidence records exact changed files, command, exit status, and
  observed result in the Implementation Log.
- Before completion, inspect the final diff specifically for:
  - hard-coded palette exclusions or duplicate route allowlists;
  - direct `invoke_action()` construction inside route tests;
  - handler tests that only assert a patched method was called;
  - new defaults or bypasses around route validation;
  - unrelated lifecycle or domain changes.
- Post-install success signal: on the retained installed TUI environment,
  Ctrl-P opens a palette with exactly `PALETTE` actions and no `command.open`;
  `:` and the command affordance still open it; the exhaustive action matrix
  passes against the installed package path if the release workflow already
  provides that lane. Do not add a new release lane solely for this fix.
- Rollback: revert the action-route implementation and its tests/docs as one
  unit. No data rollback, version skew protocol, or migration exists.

## Independent Review Loop

### Plan review

Use a different agent from the author. The reviewer reads this plan,
`docs/specs/10-taut-tui.md` [TUI-2.2], [TUI-2.3], [TUI-8], [TUI-13],
`docs/implementation/12-taut-tui.md`, `actions.py`, `app.py`, and the four TUI
test owners named above. Review stance:

> Verify that the plan closes the enumerable-contract gap with firing evidence,
> not duplicate manifests or performative test volume. Check whether route
> validation has one production owner, whether stale route claims are handled
> without inventing UI, whether every id can reach a concrete postcondition,
> and whether the anti-mocking and stop gates protect the real Textual/domain
> boundaries. Answer PASS or BLOCKED: could you implement this confidently and
> correctly, and would it avoid degrading the TUI?

Record every finding in the Review Log. Apply accepted corrections, explain
declined items, and request a scoped round-two review of accepted fixes. A
BLOCKED verdict prevents implementation.

### Slice and completed-work review

- Review after Task 3 checks only route authority, source validation, and the
  palette regression before the exhaustive matrix grows around it.
- Review after Task 5 checks the exact `ActionId × ActionRoute` matrix and all
  32 handler cases for real firing evidence and over-mocking.
- Final review checks the complete diff, all verification evidence, the
  implementation note, deviation log, and status claim. No completion claim
  precedes resolution of its findings.

## Out of Scope

- Changing the 32 action ids, labels, families, required version-1 inventory,
  or destructive-action policy.
- Adding actions, gestures, contextual menus, rich extension contributions, or
  a public TUI plugin protocol unless an existing spec requirement is found to
  be unimplemented and the plan is explicitly revised.
- Redesigning applicability/disabled-reason policy, forms, navigation,
  search semantics, domain operations, Summon lifecycle, responsive layout,
  or shutdown.
- Generalizing the registry for third parties or exporting it as a public API.
- Release, tagging, dependency changes, or unrelated 0.9.0 remediation.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

| Date | Reviewer and baseline | Verdict/findings | Disposition |
|------|-----------------------|------------------|-------------|
| 2026-08-14 | Independent Codex plan review of the first draft at `7ecd6c1` plus the plan-authoring worktree | BLOCKED. AR-1: route authority and palette exclusion were unacknowledged spec changes. AR-2: route meanings and semantic/physical precedence were undefined. AR-3: `ActionSource` compatibility was left to implementer inference. AR-4: the Summon proof named a real fixture the TUI suite does not own. AR-5: the proposed route-filter no-op test could conflict with the no-registry-mocking rule. | AR-1/AR-2 accepted: reclassified to Class 5, added exact [TUI-2.2]/[TUI-7.1]/[TUI-13.2] delta and promotion slice, and defined semantic route precedence. AR-3 accepted: replace the internal duplicate with `ActionRoute`, validate in `ActionInvocation.__post_init__()`, and retain no alias. AR-4 accepted: specified the TUI/Summon compositional proof and exact postconditions, plus focused real-controller gates. AR-5 accepted: specified dynamic predicate comparison without mutation or a second manifest. Scoped round-two verification requested. |
| 2026-08-14 | Same reviewer, scoped round two over AR-1–AR-5 | FAIL. AR-1, AR-3, AR-4, and AR-5 passed. R2-1 found that defining `MOUSE` as pointer-only contradicted Textual `Button.Pressed`, which is also emitted when Enter activates a focused button. | Accepted. Defined `MOUSE` as the semantic base-screen mouse-parity control surface regardless of pointer versus keyboard activation, kept navigation/palette/context precedence, and aligned the comprehension check. Scoped round-three verification requested. |
| 2026-08-14 | Same reviewer, scoped round three over R2-1 | PASS. The semantic `MOUSE` definition now matches the shared Textual `Button.Pressed` boundary; navigation, palette, and context keep precedence; no new defect was introduced. | Review loop closed. Plan remains draft until the product owner accepts the proposed spec delta. |
| 2026-08-14 | Product owner | Accepted the reviewed spec delta by requesting implementation per this plan. | Plan activated; exact delta promoted before production edits. |
| 2026-08-14 | Independent Task 3 slice review of the route-authority worktree | BLOCKED. T3-1: the exact palette test assumed Summon was absent although the retained environment loaded it. T3-2: the rejection test used the wrapper and did not directly prove dataclass construction was gated. | Both accepted. Expected palette ids now use the running app's actual Summon availability; the rejection test directly constructs `ActionInvocation`. Scoped round-two review requested. |
| 2026-08-14 | Same reviewer, scoped Task 3 round two | PASS. Exact palette membership and direct-construction rejection now fire; focused tests, mypy, Ruff, and `git diff --check` passed. | Task 3 review loop closed; exhaustive route and handler gates remain in progress. |
| 2026-08-14 | Independent Task 4/5 review of the 54-pair route and 32-case handler gates | BLOCKED. T45-1: `message.react` proved only the rendered receipt, not the retained public-client/SQLite notification effect required by the action matrix. All other route, handler, destructive-confirmation, and Summon composition evidence passed review. | Accepted. The case now retains presentation proof and uses an independent `bob` client plus non-consuming `peek_inbox()` to assert the exact message id and `ack` reaction. Scoped round-two review requested. |
| 2026-08-14 | Same reviewer, scoped Task 4/5 round two | PASS. The reaction case proves both the rendered receipt and exact retained public notification through an independent client; focused tests and static gates passed. | Task 4/5 review loop closed. |
| 2026-08-14 | Independent final whole-diff review | BLOCKED on documentation reconciliation only. FCR-1: the implementation note lacked the reciprocal plan backlink. FCR-2: the plan's key-file inventory and slice commands omitted the two implemented exhaustive gate owners and retained a stale hypothetical filename. Code, all executable gates, concurrent-change preservation, and prior review records passed. | Both accepted. Added the implementation backlink; named both gate owners in context, Task 2, targeted runs, and slice gates; removed the stale hypothetical instruction. Final scoped rereview requested. |
| 2026-08-14 | Same reviewer, final scoped round two | PASS. The reciprocal backlink, gate-owner inventory, executable commands, review record, and 296-test collection reconcile; documentation gates and `git diff --check` passed. | Final review loop closed. The implementation is ready for uncommitted owner review; plan and index remain active until an owner-authorized commit exists. |

## Implementation Log

| Date/slice | Evidence | Result |
|------------|----------|--------|
| Plan authoring | Live probe at `7ecd6c1` reported `command.open` routes `keyboard, mouse` while `_palette_entries()` included it; focused existing inventory/palette tests passed, demonstrating the proof gap. | Baseline defect and false-green gate confirmed; no production implementation performed. |
| 2026-08-14, comprehension gate | `_palette_entries()` consumes the Summon-only `available_action_specs()` filter; reachability requires a real producer, central dispatch, and observable handler outcome; stale non-required routes are removed; navigation has semantic precedence over pointer provenance while base-screen `Button.Pressed` controls remain `MOUSE`. | All four required answers match the reviewed plan; implementation may proceed. |
| 2026-08-14, spec promotion | Product owner accepted the independently reviewed delta. Applied the exact [TUI-2.2], [TUI-7.1], and [TUI-13.2] text before production edits and recorded the worktree promotion baseline. | Active implementation contract now defines route meanings, semantic precedence, route-derived palette membership, and both exhaustive firing gates. |
| 2026-08-14, RED contract probes | `test_command_palette_excludes_command_open_action` failed because the live palette contained `command.open`; `test_invocation_rejects_an_undeclared_route` failed because no exception was raised; `test_empty_state_actions_use_the_navigation_route` failed because `workspace.initialize` did not declare the route its real navigation row emitted. | Three distinct false claims were observed before their production corrections: palette membership, source-blind construction, and undeclared existing navigation producers. |
| 2026-08-14, route-authority slice | Replaced `ActionSource` with authoritative `ActionRoute`, validated in `ActionInvocation.__post_init__()`, removed the dispatch-source default, filtered palette queries by route, added `NAVIGATION` to the two existing empty-state producers, and removed twelve stale route claims. `pytest -q test_tui_actions.py test_tui_app.py -k 'action or route or palette'` passed 44 tests; focused Ruff and format checks passed. | The registry now describes 54 observed production pairs: 31 palette, 6 navigation, 1 context, 7 keyboard, and 9 base-screen mouse-parity producers. Independent Task 3 round-two review passed. |
| 2026-08-14, exhaustive route gate | Added `test_tui_action_routes.py`, deriving all declared pairs from `ACTION_SPECS` and driving real Textual palette, navigation, search-result context, keyboard/composer, and base-control producers through a forwarding central-dispatch spy. The focused file passed 55 tests; Ruff, format, mypy, and `git diff --check` passed. | All 54 declared pairs fire, the driver inventory has no missing or extra pair, and its inverse assertion covers all 32 ids. These already-correct cases are recorded as proof completion rather than behavioral RED/GREEN changes. |
| 2026-08-14, exhaustive handler gate | Added `test_tui_action_handlers.py` with an exact-keyed 32-case registry. Each case starts from a real palette or keyboard producer and asserts a concrete native-screen, real SQLite/public-client, system-file, quit, or `TuiSummonOperations` controller outcome. Leave, rename, delete, dump replacement, and Summon dismissal fire cancel/no-mutation and accept/mutation. The focused file passed 33 tests; Ruff, format, and mypy passed. | Every `ActionId` reaches a concrete handler postcondition. Fixture corrections retained public state assertions; no new production handler defect was found. Independent Task 4/5 round-two review passed after reaction proof added the exact retained public notification. |
| 2026-08-14, final verification | The full retained TUI suite passed all 296 collected tests. Focused public `SummonController` start/readiness, list, status, and stop tests passed 4 tests. Full TUI Ruff, format, and mypy gates passed. Plan-index, documentation-path, 15 reference/metadata tests, and `git diff --check` passed. | Implementation and documentation gates are green; final whole-diff round-two review passed. The worktree remains intentionally uncommitted and this plan remains active. |
| 2026-08-14, closure | Product owner requested “Close and commit.” The final action-route diff is isolated from the separately landed display-sink change at `73a3fa9`; all completion evidence above remains green. | Owner-authorized completion status and index closure are recorded in the implementation commit. |

## Completion Gate

This plan may move from `draft` to `active` only after independent plan/delta
review passes, every finding is resolved, and the product owner accepts the
proposed spec delta. It may become `completed` only after the
RED-before-GREEN defect proofs, exact declared-route matrix, all-32 handler
firing matrix, retained TUI suite, static/doc gates, traceability reconciliation,
independent completed-work review, and an owner-authorized commit are recorded.
If implementation remains uncommitted for review, keep the plan active and
report the changed files and evidence without calling the work complete.
