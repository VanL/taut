# Routine Release Classification Plan

Date: 2026-07-14

Class: 5+P. This changes normative [DOM-5]/[DOM-15] classification guidance
and materially changes how future release work is planned and reviewed.

Plan type: spec-authoring with an executable process-gate update.

Hardening: N/A. The guidance change does not alter release machinery, package
artifacts, runtime behavior, storage, compatibility, or publication state.

## Goal

Classify an explicitly requested release through the repository's unchanged
normal release machinery as Class 2, with no dated plan. Keep Class 1 reserved
for work with no observable effect. Preserve normal escalation for changes to
release machinery, gate bypasses, retagging, manual publication, or recovery
that departs from the established path.

## Source Documents

- User instruction in this session: normal release execution should be a
  Class 1 or 2 item and should not require a plan.
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-12.5]
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/implementation/01-documentation-system.md`
- `bin/check-dom15-fixtures`

## Spec Baseline

- `8575ed294d6f43efe38875254a0609bce6582a98` is the committed baseline for
  `docs/specs/01-development-documentation-operating-model.md`.
- The worktree contains unrelated user-owned product, plan, and documentation
  changes. This slice touches only the operating-model guidance and its direct
  traceability/gate owners; it must not rewrite or revert those other changes.
- Promotion baseline: the [DOM-5]/[DOM-15] delta is applied in the current
  worktree against committed base
  `8575ed294d6f43efe38875254a0609bce6582a98`; inspect it with
  `git diff 8575ed294d6f43efe38875254a0609bce6582a98 -- docs/specs/01-development-documentation-operating-model.md`.

## Context and Key Files

- `docs/specs/01-development-documentation-operating-model.md` owns task
  classification. Add the exception after the [DOM-15] class table and add its
  fixture to that section's table.
- `docs/specs/02-taut-core.md` [TAUT-12.5] owns the established release path,
  including resumable `all` batches and fail-closed reruns.
- `bin/check-dom15-fixtures` owns the structural fixture contract. Require the
  stable marker ``routine release through unchanged `bin/release.py```; do not
  try
  to parse or prove the exception's semantics.
- The two planning runbooks and the documentation-system implementation note
  explain how the exception changes plan selection without changing release
  verification.

## Proposed Spec Delta

Promotion strategy: B, atomic. The normative exception, its classification
fixture, and the fixture gate land together so the active spec never advertises
an unchecked classification rule.

### [DOM-5] trigger qualification

Add this exact paragraph after the risky-trigger list:

> The narrow routine-release exception in [DOM-15] overrides the non-trivial
> and risky trigger lists above only for execution of the established release
> path itself. The exception does not transfer to product changes, preparation
> outside `bin/release.py`, release-machinery changes, disabled gates, override
> flags, manual publication, or ad hoc recovery that cannot be completed by
> reinvoking the unchanged release path. Classify those as separate work against
> the normal triggers.

### [DOM-15] Class 2 routine-release exception

Add this normative rule after the class table. It is the only exception to the
Class 2 reversibility and no-[DOM-5]-trigger requirements:

> Routine release execution is the sole Class 2 exception to Class 2's
> reversibility and no-[DOM-5]-trigger requirements. It applies only when the
> user explicitly requests a release and the agent invokes the documented
> `bin/release.py` path for the requested target without changing the release
> machinery or disabling any normal gate required by [TAUT-12.5]. The
> abbreviated Class 2 preflight records the requested target and version,
> release invariants, and the exact normal verification command; no dated
> release plan is created.
> Publication is observable and irreversible, so this is never Class 1.
> Product changes and preparation outside `bin/release.py` are separate units
> of work and do not inherit the exception. `--skip-checks`, `--retag`, tag
> movement, manual tag or artifact publication, and any recovery that departs
> from the unchanged `bin/release.py` path are outside the exception and are
> classified against [DOM-5]/[DOM-6] normally. Reinvoking the same normal
> command after a failed or partially completed release remains inside the
> exception when [TAUT-12.5]'s built-in resumable path is sufficient; classify
> any separate corrective change before that rerun.

Add this Class 2 fixture:

> Explicit user request is intent evidence for a routine release through
> unchanged `bin/release.py`; every [TAUT-12.5]-required normal gate remains
> enabled; the [DOM-15] routine-release exception overrides reversibility and
> [DOM-5] triggers for release execution only; no bypass, retag, manual
> publication, or recovery outside that unchanged path is involved; built-in resumable
> reinvocation under [TAUT-12.5] remains the same routine release.

## Invariants and Constraints

- Class 1 continues to mean no observable behavior or external-state change.
- The exception is Class 2 because publication is observable. It is the sole
  explicit override of Class 2's reversibility and no-[DOM-5]-trigger rules,
  not a general waiver for one-way or multi-surface operations.
- `release.py` and all current test, artifact, tag, and observer gates remain
  unchanged.
- `--skip-checks`, `--retag`, manual tag/asset actions, and release recovery
  outside the built-in resumable path are outside the exception.
- Dirty or uncommitted product work never becomes Class 2 merely because the
  user wants to release it. Classify, verify, review, and land that work first;
  only the later clean-tree release invocation receives the exception.
- The release completion claim still requires local gates, exact-SHA CI,
  matching tags, and uploaded artifact evidence.
- Do not edit unrelated dirty-tree changes.

## Tasks

1. Independently review this plan and exact delta before promotion.
2. Promote [DOM-5]/[DOM-15] and add the release classification fixture.
3. Red-green the structural checker so removal of the release fixture is a
   detected contract violation; keep its no-traceback and exit-code contract.
4. Align `writing-plans.md`, `hardening-plans.md`, the documentation-system
   implementation note, and the durable lessons ledger.
5. Run the focused process/documentation gates and independent completed-work
   review, then close the guidance slice. Start the requested release as a
   separate Class 2 unit only after its product inputs are classified, verified,
   reviewed, committed, and the tree is clean.

Stop and re-evaluate if this requires changing `release.py`, weakening any
release gate, creating a manual publication path, or broadening the exception
beyond unchanged normal machinery.

## Testing and Verification

The proof is structural and process-focused. Product runtime tests are out of
scope. Do not mock or synthesize the spec text; run the real checker against the
real operating-model spec.

```bash
bin/check-dom15-fixtures --self-test
bin/check-dom15-fixtures
uv run --extra dev pytest tests/test_docs_references.py -n 0 -q
uv run --extra dev ruff check bin/check-dom15-fixtures
uv run --extra dev ruff format --check bin/check-dom15-fixtures
uv run --extra dev mypy bin/check-dom15-fixtures --config-file pyproject.toml
git diff --check
```

TDD posture: after spec promotion, first extend the checker's self-test with a
mutation that removes the routine-release fixture and observe failure. Then
teach the checker to require that fixture and rerun both self-test and the real
spec gate.

### Verification evidence

- Red: `bin/check-dom15-fixtures --self-test` exited 1 with
  `mutation not caught: missing routine release fixture` before enforcement.
- Green: the self-test and real spec gate both exited 0 after the bounded marker
  check was added.
- `tests/test_docs_references.py`: 10 passed.
- Ruff check/format and mypy passed for `bin/check-dom15-fixtures`.
- `git diff --check` passed.

## Rollout and Rollback

Land the spec, checker, runbooks, implementation note, lesson, and plan in one
commit before using the new classification. Rollback is a normal revert of
that commit before the release. After the release, do not move tags; correct a
guidance defect in a later commit and use the release machinery's existing
patch-forward rule for artifact defects.

Success signal: the checker accepts the new fixture and detects its removal in
self-test. A later release may use Class 2 only after this guidance slice and
its product inputs are landed, while retaining every normal gate and exact-SHA
publication proof.

## Independent Review

Before promotion, a separate review agent reads this plan, [DOM-5], [DOM-15],
the two planning runbooks, and `bin/check-dom15-fixtures`. It challenges whether
the exception is narrow, whether Class 2 rather than Class 1 is correct, and
whether bypass/recovery paths still escalate. A second review examines the
completed diff and verification evidence before commit.

### Plan review disposition

The first independent review returned `BLOCKED`.

- Accepted: the original text contradicted Class 2's reversibility rule. The
  proposed [DOM-15] text now names this as the sole override.
- Accepted: qualifying only the one-way-door trigger left other [DOM-5]
  triggers active. The proposed [DOM-5] text now overrides both trigger lists
  for release execution only.
- Accepted: “normal machinery” was too vague. The rule now names
  `bin/release.py`, [TAUT-12.5]-required gates, and excluded flags and manual
  paths.
- Revised after the second review: recovery is bounded by path, not by whether
  one tag already exists. An unchanged built-in resumable reinvocation remains
  Class 2; recovery that departs from that path falls outside the exception.
- Accepted: dirty product work could be laundered through the release class.
  It is now an explicit separate unit that must be landed first.
- Accepted with a boundary: the checker will enforce one stable fixture marker,
  not attempt to encode policy meaning in regular expressions. Independent
  review remains the semantic gate.
- Accepted: Class 2 leaves author fresh-eyes as the review floor. This is a
  deliberate residual risk; the release machinery, required local gates,
  exact-SHA CI, tags, and artifact evidence are the control plane.

The second independent review also returned `BLOCKED`: the proposed blanket
exclusion of partial-publication recovery contradicted [TAUT-12.5]'s built-in
resumable `all` path. Accepted. The exact delta now keeps any unchanged
`bin/release.py` reinvocation inside Class 2 when that documented resumable
path is sufficient, while recovery that needs flags, machinery changes, tag
movement, or manual publication remains outside the exception.

The third review checked that boundary against [TAUT-12.5] and returned
`PASS`: normal resumable reinvocation stays inside the exception without
admitting override flags, tag movement, manual publication, machinery changes,
or ad hoc recovery.

The independent completed-work review returned `PASS`. It found two
non-blocking wording drifts, both accepted: [DOM-15]'s checker description now
names the routine-release fixture-presence check, and the plan-index summary
now limits escalated recovery to work outside the built-in resumable path.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Out of Scope

- Changing release commands, tests, workflows, artifacts, signing, or package
  versions as part of this guidance slice.
- Reclassifying manual publication or arbitrary irreversible operations.
- Editing the unrelated dirty-tree feature work that will be released later.

## Fresh-Eyes Review

- Can a normal release use the exception if any [TAUT-12.5]-required normal
  gate is disabled? No.
- Can a change to release machinery use the exception? No.
- Does the rule incorrectly call publication Class 1? No.
- Is there a concrete firing gate for the new fixture? Yes, task 3.
