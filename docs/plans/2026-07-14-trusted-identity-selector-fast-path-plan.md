# Trusted Identity Selectors and Conditional Capture Plan

Date: 2026-07-14

Class: 5 — this plan revises the active [IAN-3.2]/[IAN-3.3] identity-capture
contract and changes observable CLI/Python resolution behavior. Hardening is
required under [DOM-5] because the public identity-resolution contract changes.

Plan type: implementation with spec revision.

Owner: the implementing engineer owns the spec promotion, resolver change,
real-state firing tests, documentation alignment, benchmark evidence, and
independent review dispositions.

## 1. Goal

Preserve Taut's automatic process-identity “magic” as the selector-free default
while removing full identity capture when the caller has already supplied a
deterministic selector. Either an existing explicit `as_name`/`--as` name or
alias, or a valid continuity token when no explicit `as` is supplied, selects
the acting member without probing the process chain. A supplied explicit name
that resolves no member may create and record
identity only inside an operation that is already allowed to create a member.
`rejoin` remains the sole explicit command that durably associates the current
process claim with a caller-chosen existing member. Selector-free claim, anchor,
and human-fallback resolution retain their existing continuity and healing
behavior.

The implementation must stay synchronous. It must not move identity capture,
verification, or claim association to a background thread.

## 2. Requested Outcomes

- Preserve selector-free identity inference: ordinary CLI/API use with neither
  `as_name` nor a token still captures current evidence and follows claim,
  anchor, human, and creation rules.
- Trust an existing explicit name or alias as the acting member for the current
  operation. Do not capture local process/session evidence or rewrite that
  member's process claim, anchor, or fingerprint.
- Trust a valid continuity token as the acting member for the current
  operation. Continue recording or refreshing the `continuity_token` claim and
  activity where the current resolver does, but do not capture or associate a
  local process claim.
- Preserve explicit-selector precedence: `as_name` outranks token in the
  ordinary resolver when both are supplied; `rejoin` continues to reject
  ambiguous selectors.
- Preserve creation gating. If a supplied explicit name or alias resolves no
  member and the
  operation may create a member, capture once, create the member, and associate
  the current claim only when unclaimed. If the operation cannot create, fail
  or remain a guest according to the current command contract without probing
  or creating a throwaway member.
- Preserve `rejoin` as the explicit persistence operation for a current process
  claim, whether the target member is selected by name/alias or token.
- Capture current evidence when diagnostics explicitly need it, especially
  `whoami(explain=True)`, without silently persisting that evidence.
- Make the selector-versus-association distinction discoverable in README and
  `rejoin` help. Add no `--persist-identity`, `--claim`, or equivalent global
  flag.
- Prove operation selection with deterministic call-through counters over real
  SQLite state. Use wall-clock timing only as a manual median/IQR benchmark,
  never as a CI threshold.

## 3. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-5], [TAUT-8.1], [TAUT-8.3], [TAUT-9],
  [TAUT-10], [TAUT-11]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-2.2], [IAN-2.3],
  [IAN-3.2], [IAN-3.3], [IAN-3.4], [IAN-9], [IAN-10]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-4],
  [DOM-5], [DOM-6], [DOM-8], [DOM-10], [DOM-11], [DOM-15]

Implementation and user-facing context:

- `docs/implementation/04-taut-architecture.md`, especially identity
  resolution and process-capture boundaries
- `README.md`, identity/rejoin usage and trust-model sections
- `taut/client/_base.py`
- `taut/client/_identity.py`
- `taut/client/_messaging.py`
- `taut/client/_threads.py`
- `taut/identity.py`
- `taut/commands/rejoin.py`
- `taut/commands/_protocol.py`
- `tests/test_client.py`
- `tests/test_identity.py`
- `tests/test_cli.py`
- `tests/test_command_registry.py`
- `tests/test_shared_contract.py`

Required process guidance:

- `AGENTS.md`
- `docs/agent-context/README.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `skills/call-agent/SKILL.md`
- `docs/lessons.md`, especially the identity argv-classification lesson and the
  deterministic-operation-selection performance rule

## 4. Spec Baseline

- `682cc4488959ddb06472c020c27f07fe425eac32` is the committed source, spec,
  implementation-note, and test baseline at plan authoring time.
- Pre-existing worktree state at plan authoring consists of an unrelated
  `docs/plans/README.md` entry and untracked
  `docs/plans/2026-07-14-taut-tui-cross-reference-correction-plan.md`. Preserve
  both verbatim. They are not part of this plan's implementation scope.
- During plan review, the same unrelated TUI work also added its intended
  [TAUT-1]/Related Plans edits to `docs/specs/02-taut-core.md`. Preserve those
  concurrent edits verbatim; they remain outside this plan's diff ownership.
- Plan type: implementation with spec revision.
- Promotion baseline: `8575ed294d6f` plus the exact plan-scoped uncommitted
  worktree diff. `HEAD` advanced from the authoring baseline during
  implementation through an unrelated one-file coalescing-skill commit; it did
  not touch identity code, specs, docs, or tests. The owner has not authorized a
  commit, so this plan records the explicit uncommitted baseline rather than
  making a ready-to-land claim.

## 5. Proposed Spec Delta

Promotion strategy: **B — atomic**. The affected active [IAN-3] section is
already cited by the resolver. Promote the exact requirement text together
with its red/green tests, implementation, implementation-note update, and
reciprocal backlinks so no intermediate state claims that the old resolver
implements the new contract.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | B — atomic | [TAUT-5] selector/inference boundary |
| `docs/specs/03-identity-addressing-notifications.md` | B — atomic | [IAN-3.2], [IAN-3.3], [IAN-3.4], [IAN-9], [IAN-10] |

### 5.1 [TAUT-5] — insert after the current selector/token obligations

> Resolution distinguishes acting-member selection from local identity
> inference and durable process-claim association. For ordinary operations,
> either a resolved explicit `--as` / `TAUT_AS` name or alias, or a valid
> continuity token when no explicit `as` is supplied, selects the acting member
> without capturing local process/session evidence. Explicit `as` remains ahead
> of token in the ordinary resolution order. These selectors do not associate,
> replace, or heal the current process claim, anchor, or
> fingerprint for an existing member. When neither selector is supplied, Taut
> captures local evidence and applies [IAN-3.3]. Member creation, `rejoin`, and
> explicit evidence diagnostics capture when [IAN-3] requires it.

### 5.2 [IAN-3.2] — replace the opening paragraph

Replace:

> Every resolved command captures best-effort local evidence and canonicalizes
> it into an identity claim. The claim hash format is:

With:

> Taut captures best-effort local evidence when it is needed to infer or create
> a member, to associate the current process claim through `rejoin`, or to
> render current evidence through `whoami --explain`. Either a resolved explicit
> name or alias, or a valid continuity token when no explicit `as` is supplied,
> is sufficient to select the acting member for an ordinary operation and does
> not require process/session capture. Whenever local evidence is captured,
> Taut canonicalizes it into an identity claim. Canonicalization computes the
> claim hash in memory; it does not by itself insert or refresh
> `taut_identity_claims`. Persistence follows [IAN-3.3], member creation, or
> `rejoin` only. The claim hash format is:

### 5.3 [IAN-3.3] — replace resolution-order items 1–3

> 1. Explicit `--as NAME_OR_ALIAS` / `TAUT_AS`, if present, is authoritative
>    for the ordinary operation and remains ahead of token and inferred
>    evidence. Taut validates and resolves the current name or alias before
>    capturing local evidence. An existing member is selected without writing
>    the current process claim or changing its anchor or fingerprint. If no
>    member exists and the operation may create one, Taut captures local
>    evidence once, creates the member with that name, and associates the
>    current claim when it is unclaimed. An operation that cannot create a
>    member fails or remains a guest according to its existing contract without
>    probing identity or creating a throwaway member.
> 2. A continuity token, when no explicit `as` selector is present, resolves to
>    its member without capturing local process/session evidence. A
>    state-changing resolution records or refreshes the `continuity_token`
>    claim and activity exactly as before; it does not write the current process
>    claim or change the member anchor or fingerprint. An invalid token fails
>    without falling back to inferred identity.
> 3. When neither deterministic selector is supplied, Taut captures local
>    evidence. A captured claim-hash match resolves to the associated member.

Insert after the numbered resolution order:

> Acting-member selection and process-claim association are separate
> operations. For an existing member, `as` and token selectors affect the
> current operation but do not teach future selector-free resolution a new
> process claim. Selector-free resolution may still resolve through claim-hash
> continuity under item 3 and record process claims through anchor healing and
> human fallback under items 4–5. `rejoin` is the sole explicit command that
> associates the current process claim with a caller-chosen existing member,
> including when its target is selected by token. Taut performs no deferred or
> background identity verification or claim association. A process may
> therefore act as different members through explicit selectors without the
> first selection becoming a silent durable binding.

### 5.4 [IAN-3.4] — clarify rejoin selector ownership

Replace the opening paragraph with:

> `taut rejoin NAME_OR_ALIAS` means "associate the current process claim with
> the member selected by this name or alias." The target may instead be
> selected by a continuity token or by the global `--as` selector. Supplying
> both a name/alias and a token, or otherwise leaving more than one selector
> active, fails as an ambiguous request. Rejoin does not merge message history,
> does not rename the member, and does not rewrite old messages.

### 5.5 [IAN-9] — insert selector-conflict failure rules

> - Explicit-selector and process-claim disagreement: the explicit `as` member
>   or token member wins for the current operation. The existing process claim
>   remains owned by its current member; ordinary selection neither steals nor
>   rewrites it.
> - Missing deterministic selector target: a supplied explicit name with no
>   matching member on a non-creating operation fails or remains a guest under
>   the operation's
>   existing `allow_guest` contract, without local identity inference or member
>   creation. An invalid token fails with the existing token error. Neither
>   case falls back to a different claim-derived member.

### 5.6 [IAN-10] — add required proofs

> - each deterministic selector class independently selects the acting member
>   for an ordinary state-changing operation without requesting local
>   process/session capture: either an existing explicit name or alias, or a
>   valid token when no explicit `as` is supplied
> - existing explicit and token selection do not change process-claim
>   ownership, anchor, or fingerprint; token selection retains its declared
>   `continuity_token` claim/activity effects
> - a missing explicit name captures exactly once when a creation-capable
>   operation creates it, but a non-creating or membership-gated operation
>   creates no throwaway member and does not probe identity
> - selector-free resolution still captures and exercises claim-hash, anchor,
>   human, and allowed-creation behavior
> - `rejoin` captures and associates the current process claim, while
>   `whoami --explain` captures current evidence without silently associating it
> - ordinary selector resolution performs no deferred or background identity
>   verification or claim association

## 6. Current Structure and Key Edit Points

- `taut/client/_base.py::_ResolvedMember` currently requires non-optional
  `capture` and `claim` values. `IdentityMixin.whoami()` is the only production
  consumer of `resolved.capture`; the resolver's returned claim is not consumed
  outside construction. The implementation must represent selector-only
  resolutions explicitly rather than inventing dummy evidence.
- `taut/client/_base.py::_capture()` owns the injected-capture seam and the
  production call to `taut.identity.capture_identity()`. Tests should observe
  calls at this seam while leaving the real resolver, broker, and sidecar in
  place.
- `taut/client/_identity.py::_resolve_member()` currently captures and hashes at
  function entry, before checking `as_name` and token. It also owns activity,
  persona, claim-healing, human fallback, and allowed creation. Reorder this one
  path; do not introduce a second resolver.
- `taut/client/_identity.py::rejoin()` already owns deliberate process-claim
  association and collision failure. Keep it synchronous and reuse it rather
  than adding a persistence modifier to every command.
- `taut/client/_identity.py::_create_member()` records creation evidence,
  notification state, and an unclaimed current claim. It deliberately does not
  steal a claim that already belongs to another member. Keep this function as
  the only member-creation path.
- `taut/client/_messaging.py::say()` permits creation for a direct-message actor
  but not for a membership-gated channel actor. `ThreadsMixin.join()` is the
  ordinary public create-and-join path. Preserve those existing `create=True`
  and `create=False` call-site decisions.
- `taut/client/_identity.py::_member_from_row()` may still obtain local host
  identity to render presence. That is separate from full process/session claim
  capture and is not the measured `say()` bottleneck. Do not silently change
  presence semantics in this plan.
- `taut/commands/_protocol.py::CommandContext.client()` passes `as_name` and
  token to the one shared `TautClient`; the CLI is already thin. No parser,
  command-manifest, environment-variable, or public constructor shape change is
  needed.
- `taut/identity.py` owns the expensive process/host evidence implementation.
  Conditional selection should avoid calling it when unnecessary, not weaken
  or cache the evidence it returns when inference is required.

Comprehension gate before editing:

1. Why may `taut --as Alice join general` create and claim Alice while
   `taut --as Alice say general hello` must not create a throwaway Alice before
   membership failure?
2. Why is `taut rejoin --token TOKEN` required to capture local evidence even
   though ordinary token-selected commands must not?
3. Which current writes remain legal under token selection, and why must they
   not be confused with a process-claim association?
4. Why would a background capture/update turn a successful message into an
   operation with an unreportable later claim-collision failure?

## 7. Invariants and Constraints

### 7.1 Product and identity invariants

- Preserve the “magic” default: absence of `as_name` and token selects the same
  claim, anchor, human fallback, guest, or allowed-creation result as the
  baseline.
- Preserve the weak trust model in [TAUT-9]. `as` and tokens select; none of
  these mechanisms authenticate.
- Preserve ordinary precedence: explicit `as` first, token second, inferred
  evidence only when neither is supplied. Never fall through from an invalid
  explicit selector to a different inferred member.
- Existing explicit-name or alias selection may update activity and an
  explicitly supplied persona exactly where the baseline does. It must not add,
  refresh, steal, or heal a process claim or change anchor/fingerprint state.
- Valid token selection retains the baseline `continuity_token` claim and
  activity behavior when `_touch_activity=True`. Read-only resolution remains
  write-free. Token selection must not capture or associate a process claim.
- Selector-free claim-hash continuity, anchor healing, and human fallback may
  record process claims exactly as the baseline does. `rejoin` remains the sole
  explicit command that binds the current process claim to a caller-chosen
  existing member. Claim collisions remain fatal and name the conflicting
  member. No ordinary selector flag aliases or wraps `rejoin` behavior.
- Creation remains command-gated. `join` may create and join; direct-message
  `say` may create an actor only when the DM can otherwise succeed; channel
  `say`, `reply`, `read`, `leave`, and other membership-gated operations do not
  create a missing member.
- A newly created explicit member records the current claim only when
  unclaimed. It never steals a claim from another member and remains reachable
  by its explicit name and minted token when no process claim can be attached.
- `join(new=True)` with an occupied explicit route still fails before activity,
  claim, membership, cursor, persona, or notice mutation; it also need not
  probe identity before that deterministic failure.
- `whoami(explain=True)` returns current capture evidence and the actual
  selector rule. Diagnostic capture alone does not associate or heal a claim.
- `last_created_member`, emitted creation evidence, notification-thread
  creation, message envelopes, sender cursor advancement, and mention behavior
  remain unchanged.

### 7.2 Implementation and lifecycle constraints

- Extend `_resolve_member()`; do not add a parallel selector resolver, CLI-only
  fast path, or backend-specific branch.
- Add no async, deferred, queued, or background work. The operation completes
  with all of its intended identity side effects known, or it fails
  synchronously.
- Do not cache a complete `IdentityCapture`. Working directory, tty, process
  group, ancestry, and other evidence may change and must remain fresh whenever
  capture is required.
- Do not optimize `taut.identity.capture_identity()` internals, cache `ioreg` or
  `ps` results, change presence computation, or modify process classification in
  this change. Those are separable follow-ups if selector avoidance leaves a
  material inference-path cost.
- Add no dependency, schema change, migration, public Python parameter, global
  CLI flag, environment variable, or compatibility reader.
- Keep SQLite and PostgreSQL on the shared resolver/state path.
- Use optional capture/claim state or a comparably explicit internal result;
  never fabricate empty `IdentityCapture`/`IdentityClaim` objects to satisfy
  existing types.

### 7.3 Failure priorities

- Invalid tokens are fatal under the current token error. A supplied explicit
  name with no matching member fails or remains a guest under the command's
  existing `allow_guest` contract. Both outcomes occur before capture or state
  mutation and never fall back to inferred identity.
- `rejoin` claim collisions and state-integrity failures remain fatal.
- Field-level process evidence remains best-effort only after the resolver has
  selected a path that requires capture.
- There is no best-effort post-command identity association. A successful core
  operation must never be followed by a hidden auxiliary mutation whose failure
  cannot be returned to the caller.

## 8. Rollout, Rollback, and One-Way Doors

- Promotion strategy B keeps spec, code, tests, implementation rationale, and
  backlinks in one atomic implementation slice after plan/delta review.
- There is no storage migration or one-way door. Existing members, process
  claims, token claims, anchors, fingerprints, cursors, and messages retain
  their formats and meanings.
- Rollback is source-only: revert the spec delta, resolver/test changes,
  implementation note, README/help wording, and backlinks together. Data
  written by either version remains readable by the other because the change
  only omits unnecessary capture and process-claim work on deterministic
  selector paths.
- Do not deploy a spec-only or code-only half. If the atomic slice cannot keep
  the full test matrix green, stop and revise the plan rather than weakening
  selector or association semantics.
- Post-deploy success signals are lower latency and zero process-capture calls
  for ordinary existing-`as`/valid-token operations, with unchanged success and
  error results. Selector-free resolution and rejoin failures must not increase.

## 9. Detailed Implementation Design

1. Make selector-only resolution representable.
   - Files: `taut/client/_base.py`, `taut/client/_identity.py`.
   - Allow `_ResolvedMember.capture` and `.claim` to be absent when no local
     evidence was requested. Convert changed constructions to keywords so
     optional evidence cannot be confused positionally.
   - Add a local memoized `ensure_evidence()` helper inside `_resolve_member()`
     or an equivalently narrow private helper. One resolution may request
     capture at most once.
   - Add an internal `_require_capture` argument to `_resolve_member()` only if
     needed for `whoami(explain=True)`. Do not expose it through public API.
   - Stop gate: if optional evidence spreads beyond the resolver and
     `whoami()`, replace it with one narrow internal result helper rather than
     weakening unrelated type contracts.

2. Resolve deterministic selectors before evidence.
   - Files: `taut/client/_identity.py`, `tests/test_client.py`.
   - Validate and resolve `as_name` first. For an existing row, perform the
     baseline activity/persona work and return without `ensure_evidence()`
     unless the caller explicitly requires current diagnostics.
   - For a missing explicit row, preserve `create`/`allow_guest` behavior. Call
     `ensure_evidence()` only on the existing creation path.
   - Resolve token second. Keep token-claim/activity writes under
     `_touch_activity`; do not request local evidence except for explicit
     diagnostics.
   - Only after neither selector is present should the existing claim, anchor,
     human, guest, and creation logic request evidence and continue unchanged.
   - Stop gate: if an implementation tries to fall back from a supplied but
     invalid selector to inferred evidence, or changes a call site's `create`
     flag, stop and re-plan.

3. Preserve deliberate association and diagnostics.
   - Files: `taut/client/_identity.py`, `tests/test_client.py`,
     `tests/test_identity.py`.
   - Keep `rejoin()` on its direct synchronous capture/claim path for both name
     and token targets.
   - Make `whoami(explain=True)` require one current capture and pass it to
     `explain_capture()`. `whoami(explain=False)` may use deterministic
     selection without full process/session capture; existing host-presence
     calculation remains separate and unchanged.
   - Prove that diagnostics do not implicitly record the captured process claim
     for an existing explicit/token-selected member.
   - Stop gate: if preserving explanation requires capture on every ordinary
     selector-selected command, keep explanation explicit rather than restoring
     eager capture.

4. Align product documentation without adding a second explicit association
   surface.
   - Files: `README.md`, `taut/commands/rejoin.py`,
     `docs/implementation/04-taut-architecture.md`, both governing specs, this
     plan, and `docs/plans/README.md`.
   - Explain the three modes: selector-free automatic identity; one-operation
     explicit selection through `as` or token; durable current-process
     association through `rejoin`.
   - State that `--as` may create only when the selected command already permits
     member creation, and that existing-member `as` never rewrites identity.
   - Improve existing `rejoin` help instead of adding a global persistence flag.
   - Update the implementation rationale around explicit-to-inferred order,
     anchor healing, and why deterministic selectors bypass capture.
   - Stop gate: do not imply that `as`, token, claims, or rejoin authenticate.

## 10. Test Matrix and Red-Green Proof

Use real `TautClient`, SQLite broker queues, and sidecar state. The limited
instrumentation may wrap the client's real `_capture()` method as a
call-through counter; it must not replace `_resolve_member`, broker/state work,
claim writes, or queue behavior. The counter proves operation selection, while
state assertions prove that skipped capture did not hide a mutation.

| Scenario | Capture requests | Required state/result proof |
|----------|------------------|-----------------------------|
| existing explicit name, channel `say` | 0 | correct sender; activity/cursor behavior unchanged; process claim/anchor/fingerprint unchanged |
| existing explicit alias | 0 | alias owner selected; no process identity mutation |
| valid token, channel `say` | 0 | token member selected; continuity-token claim/activity retained; no process identity mutation |
| both ordinary `as` and token supplied | 0 | `as` member wins; token member and token claim are untouched by that operation |
| invalid token | 0 | existing `TokenError`; no inferred fallback or state mutation |
| missing explicit name, non-creating operation | 0 | existing error/guest result; no member, notification thread, claim, or message |
| missing explicit name, membership-gated channel `say` | 0 | no throwaway member before membership failure |
| missing explicit name, `join` creation | 1 | member and membership created; unclaimed process claim associated |
| missing explicit name with already-owned process claim | 1 | no claim theft; new member remains reachable by name/token |
| occupied explicit name plus `join(new=True)` | 0 | fail-not-adopt and byte-identical member/claim/membership state |
| no selector, existing claim | 1 | same member selected through the magic path |
| no selector, changed mutable evidence | 1 | anchor fallback and healing behavior unchanged |
| `rejoin NAME` and `rejoin --token TOKEN` | 1 each | current process claim associated or collision fails loudly |
| `whoami(explain=True)` with `as` or token | 1 | current evidence and selector rule returned; no implicit process-claim association |
| read-only selector resolution | 0 full captures | no activity or claim writes; public result unchanged |

Red-green sequence inside the strategy-B atomic slice:

1. Add the existing-`as` and valid-token call-selection tests first. Run them
   against the baseline and record that each fails because `_capture()` is
   called once.
2. Add the remaining mutation, creation-gate, precedence, rejoin, explanation,
   and selector-free invariant tests. Tests describing already-correct
   invariants may be green at baseline; identify them as characterization
   coverage rather than pretending they are regression reds.
3. Implement the resolver change and rerun the two red tests to green.
4. Run the whole matrix and neighboring identity/CLI suites.

## 11. Manual Performance Evidence

Add `tests/test_identity_performance.py`, marked `sqlite_only` and `slow`, as a
manual report rather than a default CI gate. Reuse the repository's
`tests/test_unread_performance.py` median/IQR reporting style.

- Use fresh temporary SQLite state and a persistent `TautClient` per scenario.
- Set up the member, target thread, membership, token, and one warm-up call
  outside timing.
- Time ordinary `say()` batches for existing explicit `as`, valid token, and
  selector-free automatic identity. Use at least eleven samples and report
  median, Q1, Q3, total runtime, platform, Python, psutil, and SimpleBroker
  versions.
- Report deterministic `_capture()` call counts beside timing.
- Do not assert an absolute or ratio threshold. Host process depth and OS
  subprocess latency are variable.
- Keep `cProfile` optional and diagnostic; never sum nested cumulative times.

Manual command:

```bash
uv run --extra dev pytest tests/test_identity_performance.py -m slow -n 0 -s
```

The benchmark answers whether deterministic selectors removed the measured
identity-capture cost and what residual broker/state cost remains. It does not
redefine selector semantics.

## 12. Task Breakdown

1. Review the plan and exact proposed spec delta independently.
   - Reviewer: a different-family read-only invocation selected through
     `skills/call-agent/SKILL.md`. This plan used Grok's OS-enforced read-only
     sandbox after the initial Claude invocation exceeded its bounded timeout.
   - Inputs: this plan, [TAUT-5], [TAUT-9], [IAN-2.2]/[IAN-2.3],
     [IAN-3.2]–[IAN-3.4], [IAN-9]/[IAN-10], implementation rationale, resolver,
     creation path, rejoin path, and closest tests.
   - Done signal: every finding is accepted, rejected with evidence, or marked
     out of scope with reasoning in section 16.

2. Execute the strategy-B atomic red/spec/code/documentation slice.
   - Files: both governing specs, `taut/client/_base.py`,
     `taut/client/_identity.py`, focused tests, README, rejoin help,
     implementation note, plan index/backlinks, and this plan.
   - Observe the two selector call-selection tests fail before implementation.
   - Apply the exact promoted spec text, implementation, tests, docs, and links
     without leaving a spec-only or code-only landing.
   - Record the promotion baseline identifier immediately after the slice.
   - Done signal: focused selector matrix green; no unresolved deviation row.

3. Run the manual identity benchmark and inspect residual cost.
   - File: `tests/test_identity_performance.py`; evidence goes in this plan's
     execution section during implementation.
   - Stop gate: if explicit/token ordinary calls still request full capture,
     diagnose the remaining call path before proposing OS-level caching.
   - Done signal: median/IQR and deterministic counts recorded with no CI timing
     assertion.

4. Run neighboring, full, and cross-backend verification.
   - Run the exact commands in section 13.
   - Inspect selector, creation, claim, anchor, activity, membership, cursor,
     and explanation state, not only message success.
   - Done signal: all required gates pass from the current tree or a blocker is
     recorded precisely.

5. Run independent implementation reviews and reconcile traceability.
   - Review after the atomic identity slice, then again against the final
     plan-scoped diff and recorded evidence.
   - Update spec backlinks, implementation mapping/rationale, plan status,
     deviation log, review dispositions, and promotion baseline.
   - Done signal: reviewer can implement/approve confidently; documentation
     gate has zero failures; no plan-scoped unresolved findings.

## 13. Verification and Gates

Targeted red/green and identity suites:

```bash
uv run --extra dev pytest -q tests/test_client.py -k 'selector_skips_capture' -n 0
uv run --extra dev pytest -q tests/test_client.py tests/test_identity.py -n 0
uv run --extra dev pytest -q tests/test_cli.py tests/test_command_registry.py -n 0
```

Manual performance evidence:

```bash
uv run --extra dev pytest tests/test_identity_performance.py -m slow -n 0 -s
```

Static and documentation gates:

```bash
uv run --extra dev ruff check taut/client/_base.py taut/client/_identity.py taut/commands/rejoin.py tests/test_client.py tests/test_identity.py tests/test_identity_performance.py
uv run --extra dev ruff format --check taut/client/_base.py taut/client/_identity.py taut/commands/rejoin.py tests/test_client.py tests/test_identity.py tests/test_identity_performance.py
uv run --extra dev mypy taut tests --config-file pyproject.toml
uv run --extra dev pytest -q tests/test_docs_references.py -n 0
git diff --check
```

Repository and backend gates:

```bash
uv run --extra dev pytest -q
uv run ./bin/pytest-pg --fast
```

Focused inspection gates:

```bash
rg -n "persist.identity|background.*identity|deferred.*identity" taut tests README.md docs/specs docs/implementation
git diff -- docs/specs/02-taut-core.md docs/specs/03-identity-addressing-notifications.md docs/implementation/04-taut-architecture.md README.md taut/client/_base.py taut/client/_identity.py taut/commands/rejoin.py tests/test_client.py tests/test_identity.py tests/test_identity_performance.py docs/plans/2026-07-14-trusted-identity-selector-fast-path-plan.md docs/plans/README.md
git status --short
```

Success means:

- deterministic tests prove capture selection and every touched state effect
- public CLI/API behavior and error classes remain correct
- selector-free magic, rejoin association, and explanation still fire
- the manual benchmark shows selector paths no longer pay full identity-capture
  cost, without a timing gate
- no schema, dependency, CLI flag, or background lifecycle was added
- spec, implementation note, README/help, code, tests, plan, and backlinks form
  one closed traceability chain

## 14. Independent Review Loop

Plan/delta review uses a different-family, read-only invocation selected from
the current agent inventory through `skills/call-agent/SKILL.md` before
implementation. The reviewer receives the plan and delta verbatim plus the
governing specs, implementation note, resolver, creation/rejoin code, and
closest tests. Review stance:

> You are reviewing; do not implement or modify anything. Find errors, bad
> ideas, latent ambiguity, missing contract cases, and performative
> overengineering. Challenge whether `as`/token selection, allowed creation,
> process-claim persistence, rejoin, explanation, and rollback are specified
> precisely enough for a zero-context implementer. Use [P1]/[P2] findings and
> end with PASS or BLOCKED: could you implement this correctly against the
> atomic promoted delta?

Run the same independent stance after the atomic identity slice and against the
final plan-scoped diff. Findings are claims: reproduce them against source/tests
before editing. Each finding receives an explicit disposition in section 16.

## 15. Out of Scope

- A new `--persist-identity`, `--claim`, `--adopt`, or token/as modifier.
- Background, deferred, or best-effort post-command identity verification.
- Changing `rejoin` claim-collision semantics or adding a second explicit
  caller-chosen association path.
- Changing member-id, claim-hash, token, anchor, fingerprint, schema, or
  message-envelope formats.
- Caching complete captures, host UUIDs, native process start tokens, or psutil
  process objects.
- Changing process classification, wrapper detection, anchor selection, human
  fallback, or presence rendering.
- Changing which commands are creation-capable or membership-gated.
- Turning identity claims, tokens, names, or aliases into authentication.
- Unrelated queue, state, notification, watcher, CLI parser, or packaging work.

## 16. Review Findings and Dispositions

| Reviewer finding | Verification | Disposition |
|------------------|--------------|-------------|
| P1: promoted “sole association” language bans preserved claim healing. | Confirmed in baseline [IAN-3.3] items 4–5 and `taut/client/_identity.py`: anchor match and human fallback call `_record_claim`. | Accepted. Sections 1, 5.3, 7.1, and 15 now distinguish automatic selector-free healing from `rejoin`, the sole explicit command that binds a current process claim to a caller-chosen existing member. |
| P2: proposed [IAN-9] “fail” omits guest outcomes. | Confirmed against `_resolve_member(..., allow_guest=True)` and the unchanged [IAN-3.3] guest rule. | Accepted. Section 5.5 now preserves fail-or-guest behavior under the operation's existing `allow_guest` contract while forbidding capture, creation, and inferred fallback. |
| P2: proposed selector text uses “X and Y” for independent selectors. | Confirmed that ordinary precedence is `as_name` first and token second; either selector is independently sufficient. | Accepted. Sections 5.1, 5.2, and 5.6 now use explicit either/or wording and state that token applies when no explicit `as` is supplied. |
| P2: [IAN-3.2] “canonicalizes into an identity claim” can be misread as persistence. | Confirmed that `identity.claim_for_capture` computes a value while `_record_claim`/`add_identity_claim` persists it. | Accepted. Section 5.2 now says canonicalization is in-memory and names [IAN-3.3], member creation, and `rejoin` as the persistence owners. |
| Initial review verdict and residuals. | Grok returned `BLOCKED` only on the P1 wording; it otherwise approved the structure, creation gates, selector ordering, diagnostics, backend strategy, deterministic capture proof, and rollback. | All four findings were corrected. A focused Grok rereview returned `PASS` with no new P1/P2. Its three non-blocking prose notes were also tightened in sections 1, 5.3, and 7.3. Residuals remain explicit in sections 7 and 15: host-presence capture is separate, PostgreSQL shares the resolver but does not duplicate every counter test, and the injected-capture seam follows lazy-selection semantics. |
| Independent implementation-slice review. | Grok inspected the full plan-scoped diff against `682cc4488959`, the unchanged resolver consumers, focused evidence, and the separate host-presence path. It returned: “No [P1], [P2], or [P3] defects found against the plan-scoped slice.” | `PASS`. The reviewer confirmed all selector/capture/state paths, atomic spec alignment, and source-only rollback. It identified test volume as maintainability cost but not false or missing coverage. Its pending full-root/PostgreSQL residual was closed by the gates in section 18. |
| Final whole-diff review. | Grok attacked the post-gate diff, plan, evidence, unrelated-work attribution, enumerable [IAN-10] proofs, and broad claims. It returned: “No plan-scoped defects found,” with P0/P1/P2/P3 all `None`. | `PASS`; owner-review ready while explicitly uncommitted. Residuals are the documented host-presence path, unchanged human-fallback proof shape, SQLite-primary capture counters over the shared resolver, host-specific benchmark timing, and lack of owner-authorized commit. |
| Release audit P1: an explicit-name creation race could return the member owning the captured process claim, overriding the explicit selector. | Reproduced at both collision windows: an insert/name race returned the prior claim owner, and a post-insert claim race replaced the newly inserted explicit member. | Accepted. `_create_member` now limits claim-owner recovery to selector-free automatic naming. Explicit insertion collisions fail, while a post-insert claim collision keeps the explicit member without stealing the claim. Two deterministic real-state tests fired red and then green. |
| Release audit P2: the 0.6.6 changelog omitted the selector behavior and performance change. | Confirmed against the current 0.6.6 section and the promoted [TAUT-5]/[IAN-3] contract. | Accepted. The changelog now records capture bypass, preserved token activity and claim ownership, and `rejoin` as the explicit association path. |
| Follow-up P2: explicit post-insert recovery treated every claim-write `IntegrityError` as a won race. | A deterministic injected integrity failure with no competing claim row was silently converted into success. | Accepted. Recovery now reads the claim owner first and re-raises when none exists. A real owner permits role-aware recovery; the error class alone is not treated as proof. |
| Final release-readiness rereview. | The independent reviewer inspected both race corrections, all three recovery outcomes, deterministic tests, changelog, and plan dispositions. | `PASS`; no remaining P1/P2/P3 finding. |

## 17. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [IAN-3.4] | The original delta left token/global-`as` rejoin selection as a non-blocking residual. | The atomic promotion clarifies name/alias, token, and global-`as` target selection plus ambiguity failure. | [TAUT-8.1] and the existing CLI already implement these selectors; leaving [IAN-3.4] name-only would break closed traceability for the plan's required token-rejoin proof. | Promoted in section 5.4 without changing runtime behavior. |

## 18. Execution Evidence

Implementation is present as an uncommitted strategy-B worktree slice over
`8575ed294d6f`. The behavioral authoring baseline remains `682cc4488959`; the
intervening commit changes only `skills/coalescing/SKILL.md`. Record red/green
commands, benchmark median/IQR, cross-backend results, implementation-review
outcomes, and residual risk below. A status document is not evidence; every
completion claim must cite a rerun from the current tree.

| Evidence | Command or inspection | Observed result | Residual risk |
|----------|-----------------------|-----------------|---------------|
| Performance/source baseline | Read-only cProfile and subprocess-count probes plus resolver/source inspection at `682cc4488959` | Full capture accounted for about 93% of the reproduced `say()` profile; 50 calls launched 250 `ps` and 50 `ioreg` processes on this host; pre-captured calls were about 0.6 ms/call. Absolute 91 ms/call was not reproduced. | Host/process depth and OS load make absolute timing non-portable; the deterministic call count is the primary proof. |
| Concurrent `HEAD` audit | `git diff --name-status 682cc4488959..8575ed294d6f`; `git show --stat 8575ed294d6f` | The intervening committed change is only `skills/coalescing/SKILL.md`; no identity-plan owner or verification input changed. | Promotion baseline moved to `8575ed294d6f` plus the uncommitted plan-scoped diff. |
| Initial different-family plan review | Claude plan-mode invocation, bounded at 540 seconds; isolated read-only diagnosis after exit 124 | Claude emitted no final response before timeout. Its session log showed 33 repository tool calls over roughly 7.5 minutes; non-streaming output hid progress, and `--allowedTools` did not restrict the available tool set. No repository write occurred. | The `call-agent` Claude row needs a separately authorized maintenance change: an actual `--tools` boundary, streaming output, deterministic plugin/hook posture, and either a longer bound or narrower brief. This plan did not silently edit that skill. |
| Fallback plan review and rereview | Grok with `--sandbox read-only`, `--disable-web-search`, JSON completion gating, and the full plan embedded verbatim | Initial `BLOCKED` found one P1 and three P2 wording defects. All were verified and corrected. Focused rereview returned `PASS`/`EndTurn` with no new P1/P2; three non-blocking prose notes were also tightened. No sandbox fail-open warning or plan-review write was observed. | Closed by the implementation and final whole-diff reviews below. |
| Plan documentation gate | `uv run --extra dev pytest -q tests/test_docs_references.py -n 0`; `git diff --check`; index/backlink `rg` inspection | `10 passed`; whitespace check passed; the plan is indexed and linked from both governing specs. | The worktree also contains unrelated TUI-plan/index/spec edits, preserved and reported separately. |
| Selector red tests | Focused existing-`as` and valid-token tests before the resolver edit | Each failed only because one full `_capture()` request was observed; message, activity, token-claim, and no-rebind assertions otherwise held. | These are deterministic operation-selection reds, not timing failures. |
| Resolver green and identity matrix | `uv run --extra dev pytest -q tests/test_client.py tests/test_identity.py -n 0` | Exit 0 at 100%; existing selector, alias, token precedence, invalid token, creation/guest, DM order, selector-free claim/anchor, rejoin/collision, explain, and read-only cases passed. | Full repository and PostgreSQL gates remain below. |
| CLI and command contract | `uv run --extra dev pytest -q tests/test_cli.py tests/test_command_registry.py -n 0` | Exit 0 at 100%; one Windows-only filename case skipped. The public `as` creation gate and rejoin help contract passed. | Platform-specific Windows behavior was unchanged. |
| Focused static gates | Ruff check/format over seven touched code/test files; `uv run --extra dev mypy taut tests --config-file pyproject.toml` | Ruff passed; seven files formatted; mypy reported no issues in 86 source files. | Extension-specific type lanes remain owned by their normal gates because no extension code changed. |
| Manual identity benchmark | `uv run --extra dev pytest tests/test_identity_performance.py -m slow -n 0 -s` | `3 passed in 14.72s`; explicit median 0.537 ms/call, token 0.686, automatic 24.812; capture counts 0, 0, and 550 across eleven 50-call samples. | macOS 26.5.1 arm64, Python 3.14.4, psutil 7.2.2, SimpleBroker 5.3.2; timings are host-specific and not CI thresholds. |
| Atomic spec/docs gate | `uv run --extra dev pytest -q tests/test_docs_references.py -n 0`; `git diff --check`; forbidden-lifecycle `rg` inspection | `10 passed`; whitespace check passed; no new flag, cache, or deferred/background implementation exists. | [IAN-3.4] clarification is a documented traceability deviation, not a runtime expansion. |
| Independent implementation review | Different-family Grok review of the full plan-scoped diff, baseline, focused evidence, and unchanged consumers under `--sandbox read-only` | `PASS`/`EndTurn`; “No [P1], [P2], or [P3] defects found against the plan-scoped slice.” No sandbox warning or workspace write was observed. | Closed by the final post-gate whole-diff review below. |
| Full root regression | `uv run --extra dev pytest -q` | Exit 0 at 100%; one Windows-only filename test skipped. | Default markers exclude the manual slow benchmark, which passed separately. |
| Fast PostgreSQL regression | `uv run ./bin/pytest-pg --fast` | Shared lane `190 passed in 8.87s`; PG-only lane `14 passed in 3.11s`; exit 0. | Dockerized PostgreSQL 18; deterministic capture counters remain in the SQLite client matrix over shared resolver code. |
| Final whole-diff review | Different-family Grok review after full root/PostgreSQL gates, under `--sandbox read-only` | `PASS`/`EndTurn`; no P0/P1/P2/P3 and no sandbox warning or workspace write. Reviewer judged the slice owner-review ready while explicitly uncommitted. | Commit gate remains intentionally unsatisfied pending owner authorization. |
| Explicit-selector creation-race red | `uv run --extra dev pytest tests/test_client.py -q -n 0 -k 'explicit_name_collision_never_adopts_current_claim_owner or explicit_creation_claim_race_keeps_new_member_authoritative'` before the resolver correction | 2 failed: the name-race case did not raise, and the post-insert claim race returned `owner` instead of `newcomer`. | Deterministic wrappers injected each competing real-state write at the exact collision seam; state and resolver remained real. |
| Explicit-selector creation-race green | Focused rerun including both new tests and the two adjacent explicit-collision tests after the resolver correction | 4 passed. | Full identity, root, PostgreSQL, and release gates remain the broader regression owners. |
| Unowned integrity-failure red/green | Focused `test_explicit_creation_unowned_claim_integrity_failure_remains_fatal` before and after requiring an owner lookup | Red: failed because no `IntegrityError` escaped. Green: the new probe plus four adjacent collision tests all passed. | The injected state method raises through the real creation/resolver path; the test proves recovery requires authoritative owner state. |
| Final race-fix rereview and regression | Independent read-only inspection; five adjacent collision tests; `uv run --extra dev pytest -q`; `uv run ./bin/pytest-pg --fast` | `PASS`; five collision tests passed; full root exited 0 with one Windows-only skip; PostgreSQL reported 192 shared and 14 PG-only passes. | No P1/P2/P3 remained. |

## 19. Fresh-Eyes Checklist

Before final handoff, confirm:

- [x] the plan never conflates acting-member selection with process-claim
  association
- [x] every creation statement names the command-level `create` gate
- [x] ordinary token claim refresh is distinguished from process-claim persistence
- [x] `rejoin` and `whoami --explain` retain capture for different explicit reasons
- [x] no background lifecycle, new selector flag, schema change, or capture cache is
  implied
- [x] tests keep the resolver, broker, state, creation, messaging, and claim paths
  real; only call selection is observed
- [x] rollback is source-only and the strategy-B slice has no intermediate
  spec/code mismatch
- [x] unrelated dirty TUI-plan work remains untouched
