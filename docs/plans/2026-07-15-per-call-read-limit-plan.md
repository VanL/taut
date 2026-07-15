# Per-Call Read Limit Plan

Date: 2026-07-15

Status: implemented and fully verified. Independent plan, proposed-spec, and
final diff reviews passed. The owner subsequently authorized a targeted
commit; repository history is the commit-state evidence.

Plan type: implementation with spec revision.

Class: 5. The change revises the public `TautClient` contract and the active
core spec. It also fires the [DOM-5] risky trigger because the cursor-mutating
public API crosses the SQLite/PostgreSQL storage boundary. Hardening is
required. This is not a process change.

Owner: the implementing engineer owns spec promotion, core validation and
pagination, real-backend tests, MCP-plan reconciliation, and documentation
traceability. The MCP extension plan continues to own the future protocol
adapter and tool implementation. The repository owner owns version selection,
commit, release, and publication.

## 1. Goal

Make unread page size an explicit per-call keyword argument on
`TautClient.read()` and `read_unread()`. Preserve the core and CLI default of
1,000 messages per selected thread, let adapters such as MCP request a smaller
page without discarding already-consumed results, and keep cursor advancement
limited to the messages actually returned.

## 2. Requested Outcomes and Decided Contract

- [x] `TautClient.read(thread: str | None = None, *, limit: int = 1000)`
  delegates to `read_unread(thread, limit=limit)`.
- [x] `read_unread()` exposes the same keyword-only argument and passes it to
  the existing `Queue.peek_many()` call instead of using a literal `1000`.
- [x] The accepted range is inclusive `1..1000`. A non-`int` value, including
  `bool`, raises `TypeError("limit must be an integer")`; an integer outside
  the range raises `ValueError("limit must be between 1 and 1000")`.
- [x] Validation is the first operation in `read_unread()`. An invalid value
  performs no chat-history peek, decode, implicit sub-thread join, or cursor
  advance. `read()` adds no second validation path.
- [x] For an explicit thread, the call returns the oldest unread page of at
  most `limit` messages. It decodes the complete page before advancing the
  cursor once to the highest timestamp in that returned page.
- [x] A smaller page leaves later unread rows visible to the next call. The
  required 250-message regression yields pages of 100, 100, and 50 with no
  gap, duplicate, or premature cursor advance.
- [x] With `thread=None`, `limit` is applied independently to each joined
  non-notification thread. A call can therefore return more than `limit`
  messages in total. This preserves today's per-thread paging and existing
  flattened membership order.
- [x] Core default calls and the `taut read` command retain the 1,000-per-thread
  behavior. No CLI flag is added.
- [x] The limit is request policy only. Do not add it to `.taut.toml`,
  `TautClient` construction, persistent state, or backend configuration.
- [x] The in-flight MCP plan gives its `read` tool an optional `limit` input
  with default 100 and range `1..1000`, and forwards it to core. It must not
  slice the result of a default core read. The MCP tool keeps `thread`
  required, so one call remains bounded to one thread.

## 3. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-7.1], [TAUT-7.2], [TAUT-7.3],
  [TAUT-8.1], [TAUT-8.3], [TAUT-10], [TAUT-11]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-4],
  [DOM-5], [DOM-6], [DOM-8], [DOM-10], [DOM-11], [DOM-15]

Implementation and related-plan context:

- `taut/client/_messaging.py`
- `taut/commands/read.py`
- `tests/test_client.py`
- `tests/test_shared_contract.py`
- `tests/conftest.py`
- `taut/_scripts.py::pytest_pg_main`
- `docs/implementation/04-taut-architecture.md`
- `README.md`, Python embedding example and Development gate
- `docs/plans/2026-07-14-taut-mcp-extension-plan.md`, especially its proposed
  [MCP-5] `read` tool row and verification obligations. This untracked,
  user-owned in-flight plan is coordination context, not the current core
  contract.

Process guidance:

- `AGENTS.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/lessons.md`, especially Golden Rules 5, 6, 7, 11, and 13 and the
  backend-coverage lesson dated 2026-07-14

## 4. Spec Baseline

- Baseline commit: `32acbf2eb864cf6649b8d77355ebdfcb908a4acc`.
- `docs/specs/02-taut-core.md` and the core implementation are clean at that
  baseline.
- The worktree already contained a user edit to `docs/plans/README.md` and the
  untracked `docs/plans/2026-07-14-taut-mcp-extension-plan.md` before this plan
  was created. Preserve both. The index edit for this plan must be additive.
- The active spec remains canonical until the spec-promotion slice.
- Promotion strategy: **A, in-file requirement text before new implementation
  claims**. Review the exact delta, promote it into the existing active core
  spec, add the Related Plans backlink, run the docs gate, and record a
  promotion baseline before behavior code changes. No machine classification
  or prose status change is needed.
- Promotion baseline: uncommitted worktree based on
  `32acbf2eb864cf6649b8d77355ebdfcb908a4acc`. The promotion adds 44 lines to
  `docs/specs/02-taut-core.md` across [TAUT-7.2], [TAUT-8.3], [TAUT-10],
  [TAUT-11], and Related Plans. At promotion time, the pre-existing MCP plan
  and plan-index edits plus this plan remained uncommitted. Verification:
  `uv run --extra dev pytest tests/test_docs_references.py -q -n0` passed 10
  tests, and `git diff --check` passed.

## 5. Current Structure, Hidden Couplings, and Comprehension Gate

`MessagingMixin.read()` currently delegates to `read_unread(thread)`.
`read_unread()` resolves the member, chooses one explicit membership or all
memberships, then iterates each chat thread. For every eligible thread it calls
`Queue.peek_many(1000, with_timestamps=True,
after_timestamp=last_seen_ts)`, decodes the entire returned page, appends it to
the combined result, and advances that membership cursor once to the maximum
returned timestamp. A decoder failure leaves the current page cursor in place.

SQLite and PostgreSQL share this exact client path. Backend selection changes
the broker and sidecar implementation, not `read_unread()`. The root
`tests/test_shared_contract.py` suite is marked `shared`; ordinary root pytest
runs it against SQLite, while `bin/pytest-pg` reruns it with
`BROKER_TEST_BACKEND=postgres`. A separate PG-only copy would weaken the shared
contract and add maintenance drift.

The core CLI does not own a page-size option. `taut/commands/read.py` calls
`read_unread(args.thread)` and advertises the current 1,000-per-thread default.
Leaving that adapter unchanged is the compatibility proof. The future MCP
adapter is different: it should expose a smaller schema default and pass the
chosen value into core. Result slicing after `read()` is forbidden because
the cursor has already advanced through every fetched row.

Comprehension gate before editing:

1. Why does the limit belong in `read_unread()` before `Queue.peek_many()`
   rather than in `read()`, CLI rendering, or MCP result formatting?
2. Why can `read(limit=100)` return more than 100 rows when `thread=None`, and
   which existing behavior does that preserve?
3. Which timestamp may be written to the cursor after a page, and why would
   advancing to the queue high-water mark lose data?
4. Why must the shared contract test run through both the ordinary SQLite
   suite and `bin/pytest-pg` instead of mocking or duplicating the backend?
5. Which state may already have advanced if a later thread fails during a
   `thread=None` call, and why is this plan not making the multi-thread read
   atomic?

Stop and revise the plan if cold reading shows that SimpleBroker does not
return `peek_many(limit, after_timestamp=...)` in oldest-first order, if a
backend applies the limit after an unbounded scan, or if the MCP `read` tool no
longer requires one thread. Those findings change either correctness or the
context-bound claim.

## 6. Proposed Spec Delta

Promotion strategy: **A**.

| Spec file | Sections touched |
|---|---|
| `docs/specs/02-taut-core.md` | [TAUT-7.2], [TAUT-8.3], [TAUT-10], [TAUT-11], Related Plans |

### [TAUT-7.2] — append after the cursor bullet list

> Public unread reads are bounded per call. `TautClient.read()` and
> `TautClient.read_unread()` accept a keyword-only `limit` with an inclusive
> range of 1 through 1,000 and a core default of 1,000. The value is request
> policy, not project, client-construction, or persistent configuration.
> Validation precedes chat-history peeking, decoding, implicit membership, and
> cursor movement. A non-integer value, including `bool`, raises `TypeError`;
> an integer outside the range raises `ValueError`. The exact messages are
> `limit must be an integer` and `limit must be between 1 and 1000`,
> respectively.
>
> For an explicit thread, the limit bounds the oldest unread page. Taut decodes
> that whole page before advancing its membership cursor once to the highest
> timestamp among the returned messages. Messages beyond the page stay unread
> for a later call. With no thread argument, the same limit applies
> independently to every joined chat thread, so the combined return may exceed
> the numeric limit.
>
> Callers that need a smaller page must pass the limit into core. They must not
> fetch a larger page, slice the returned list, and discard the rest, because
> the larger read has already marked every fetched message seen.

### [TAUT-8.3] — append after the opening Python API paragraph

> The unread signatures are
> `TautClient.read(thread: str | None = None, *, limit: int = 1000) ->
> list[Message]` and
> `TautClient.read_unread(thread: str | None = None, *, limit: int = 1000) ->
> list[Message]`. `read()` delegates to `read_unread()` and exposes no second
> pagination or validation path. The CLI continues to call the core default;
> adapters may choose a smaller surface default and pass it explicitly.

### [TAUT-10] — add one failure-mode bullet

> - Invalid unread limit: reject before any chat-history read, implicit
>   membership, decode, or cursor mutation. Wrong runtime type raises
>   `TypeError` with `limit must be an integer`; an integer outside 1 through
>   1,000 raises `ValueError` with `limit must be between 1 and 1000`.

### [TAUT-11] — add one verification requirement

> - One shared public-client contract test runs on real SQLite and PostgreSQL,
>   creates 250 unread messages, and reads them with a limit of 100 as exact
>   oldest-first pages of 100, 100, and 50. It proves each cursor stops at the
>   last returned message and the next page has no gap or duplicate. Focused
>   core tests prove range boundaries, both public entry points, invalid values
>   with no broker peek/cursor write/implicit membership, and the per-joined-
>   thread rather than aggregate meaning of a no-thread limit. The broker and
>   sidecar state remain real in every case.

### Related Plans — add

> - `docs/plans/2026-07-15-per-call-read-limit-plan.md` — bounded per-call
>   unread pages, exact cursor advancement, shared SQLite/PostgreSQL proof, and
>   a smaller MCP surface default without post-read slicing.

## 7. Invariants, Compatibility, Rollback, and Operational Signals

Invariants:

- Chat history remains peek-only under [TAUT-7.1]. This change cannot claim,
  delete, or rewrite broker messages.
- Cursor writes remain monotonic and per member/per thread. The highest
  timestamp in the fully decoded returned page is the only new cursor value.
- A page is oldest-first. A limit of 100 over 250 unread rows means the first
  100, not the most recent 100.
- `thread=None` means up to `limit` for each joined chat thread, never an
  aggregate cap. Notification queues remain excluded.
- Core and CLI defaults stay 1,000. Existing calls without the keyword retain
  behavior and return type.
- `read()` remains a thin alias. Validation and paging have one owner in
  `read_unread()`.
- Validation is side-effect-free and precedes queue access. No invalid call
  may create an implicit sub-thread membership or resolve enough work to move a
  cursor.
- A decode failure retains the current whole-page-before-cursor behavior.
- SQLite and PostgreSQL use the same production path and shared test. No
  backend-specific pagination implementation is introduced.
- No config key, constructor field, schema, migration, dependency, cache, or
  alternate read path is added.
- MCP passes its chosen limit into core. It never slices after a cursor-moving
  read.
- Existing user changes in the plan index and MCP plan remain intact.

Fatal failures are validation, broker read, decode, and cursor-write failures
already surfaced by the core method. There is no new best-effort auxiliary
operation. Do not catch or downgrade them in this change.

Compatibility and rollout:

- Calls that omit `limit` are source- and behavior-compatible.
- A caller that passes `limit` requires the first core version containing this
  API. The future MCP package must set its core dependency floor accordingly
  during its own release preparation; this plan does not choose that version.
- Promote the spec first, land core and shared tests together, then let the MCP
  plan depend on the new API. Do not land an MCP implementation that passes
  `limit` against an older core.
- There is no data migration, storage-format change, destructive action, or
  one-way door. Existing cursors remain valid.

Rollback is one coordinated code/spec/docs revert. Because no stored state
shape changes, reverting restores the fixed 1,000 page size. Cursors advanced
by valid smaller reads remain ordinary valid high-water marks and need no
repair. If MCP were later released against this API, roll back or pin MCP
before rolling core below its declared dependency floor.

Post-deploy or pre-release success is observable through public behavior: an
explicit 100-row page returns promptly, the next call starts at row 101, and
default CLI reads still drain 1,000 per thread. There is no new metric or log.
Any gap at row 101, total-limit behavior across two threads, or MCP response
truncation with a cursor beyond the last returned id is a rollback blocker.

## 8. Dependency-Ordered Tasks

### Task 0: Review and promote the contract

1. Give an independent reviewer this plan, its exact Proposed Spec Delta,
   `docs/specs/02-taut-core.md`, `taut/client/_messaging.py`,
   `tests/test_client.py`, `tests/test_shared_contract.py`,
   `docs/implementation/04-taut-architecture.md`, and the in-flight MCP plan.
2. Require a finding-first [P1]/[P2] review and a PASS/BLOCKED verdict. Resolve
   every finding in the review disposition table below.
3. Promote the exact delta with strategy A and add the core spec backlink.
   Run `tests/test_docs_references.py` and `git diff --check`; record the
   promotion baseline before behavior changes.

Done signal: the delta is canonical in the spec tree, the docs gate is green,
and no unresolved review blocker remains.

Stop if review changes the range, exception classes, per-thread meaning, core
default, or MCP default. Revise and rereview the exact delta rather than
silently implementing the new decision.

### Task 1: Prove and implement one explicit-thread page red-green

1. Add the 250-message regression to `tests/test_shared_contract.py` through
   real `TautClient` calls. Join a reader and writer, catch the reader up, write
   250 uniquely numbered messages through `say()`, then call
   `read(thread, limit=100)` three times.
2. Assert literal page lengths `100`, `100`, `50`; exact numbered text and
   timestamp slices; cursor equality with each page's last id; no duplicate or
   gap; and `EmptyResultError` after the third page.
3. Run the single test against SQLite and retain the failing output. The
   expected initial failure is that `read()` does not accept `limit`; a
   different failure requires diagnosis before implementation.
4. Change only `MessagingMixin.read()` and `read_unread()` signatures and pass
   the caller-supplied limit into the existing `peek_many()` call. Keep
   full-page decode and one cursor write. Do not add a second paginator or
   storage helper; first-operation validation belongs to Task 2.
5. Rerun the single SQLite test to green, then run it through `bin/pytest-pg`
   before starting the next behavior slice.

Done signal: the same public regression passes on real SQLite and PostgreSQL,
and the retained red evidence proves the test would fail against the baseline.

Stop if 250 production writes make the shared PG test operationally excessive.
Measure first. If it is excessive, preserve public client setup and cursor
reads but propose the narrowest real-broker fixture change for review; do not
silently replace the path with a mocked queue or fabricated state.

### Task 2: Close validation, boundary, alias, and per-thread contracts

Use vertical red-green cycles, one behavior at a time:

1. In `tests/test_client.py`, add invalid-limit cases for `0`, `1001`, `True`,
   `1.0`, and `"1"` through both public entry points as appropriate. Snapshot
   the membership cursor and unread ids. Use a narrow `Queue.peek_many` spy
   only as supporting evidence that no peek occurred; keep the real queue and
   sidecar as the primary proof. Add one unjoined sub-thread case with an
   invalid limit and assert that it creates no implicit membership, performs no
   peek, and writes no cursor. Implement the first-operation validation in
   `read_unread()`.
2. Add successful boundary cases for `1` and explicit `1000`. Preserve the
   existing no-argument 1,000-row test as the default regression.
3. Add a two-thread no-argument-thread case: create at least two unread rows in
   each thread, call `read(limit=1)`, and prove one oldest row and one exact
   cursor advance per thread. A second call returns the next row from each.
   Assert by thread rather than inventing a new aggregate ordering contract.
4. Call `read_unread(limit=...)` directly in at least one firing case so the
   public delegate and implementation entry point cannot drift.
5. Preserve the current decode-failure test and make it use a non-default limit
   if that strengthens the whole-page-before-cursor proof without obscuring
   its original purpose.

Done signal: every range boundary and invalid class fires, `thread=None` is
provably per thread, and the neighboring cursor/decode suite is green.

Stop if validation requires config, client state, a public helper, or an
exception-hierarchy change. Those are outside the requested API and require a
new contract decision.

### Task 3: Reconcile the future MCP contract without implementing MCP

1. Carefully edit the existing user-owned
   `docs/plans/2026-07-14-taut-mcp-extension-plan.md`; preserve all unrelated
   plan content and review history.
2. In its Proposed Spec Delta, replace the fixed-bound `read` row with an
   optional integer `limit`, schema default 100, accepted range `1..1000`, and
   an explicit call to core `read(thread, limit=limit)`. Keep `workspace` and
   `thread` required.
3. Replace any statement or test obligation that says MCP `read` is fixed at
   1,000. Add a firing obligation for omitted-default 100, explicit 1 and
   1,000, invalid 0 and 1,001, and two consecutive pages with no skipped
   cursor range. State that post-read slicing is forbidden.
4. Mark the design-lens finding about the fixed 1,000-record MCP `read` page as
   accepted and point its disposition to the revised [MCP-5] row and firing
   obligations; do not leave that finding `Pending` after the contract has
   been decided.
5. Keep the core `thread=None` per-thread semantics in the core plan/spec. Do
   not broaden the MCP tool to an optional thread; its required thread is the
   MCP context-economy bound.
6. The MCP plan's own independent review must reconsider the revised [MCP-5]
   delta before its later promotion. This task does not promote or implement
   the MCP spec.

Done signal: the two plans no longer contradict each other, MCP has a bounded
100-message default, and no MCP code or dependency has been added.

Stop if the user-owned MCP plan changes concurrently in the same rows. Re-read
and reconcile with the owner rather than overwriting the newer decision.

### Task 4: Reconcile durable documentation and final evidence

1. Update `docs/implementation/04-taut-architecture.md` to explain that
   `read_unread()` validates one per-call limit, uses it at the existing
   bounded peek, fully decodes each page, and advances only to the returned
   page high-water mark. Update its spec-code/test map if the named tests move.
2. Update the README Python example to show the keyword only if one concise
   comment can make the per-thread meaning clear. Do not change the CLI example
   or imply a 100-message core default.
3. Leave `taut/commands/read.py` unchanged unless a test shows its existing
   1,000-per-thread help is stale. The CLI gets no new option.
4. Reconcile the core spec backlink, plan index, implementation mapping, and
   MCP-plan dependency statement. Evaluate the heavily used planning/testing
   guidance; update it only if this work exposes a reusable omission.
5. Run focused and full gates below from the current worktree. Run an
   independent final diff review, reproduce each finding, update or reject it
   with reasoning, reconcile the deviation log, and report changed files,
   commands, results, residual risk, and commit state. Do not commit without
   owner authorization.

Done signal: the traceability chain is closed, all gates are current reruns,
the final review has no unresolved P1/P2 finding, and the handoff does not call
uncommitted work complete.

## 9. Testing Plan and Anti-Mocking Boundary

Keep real: `TautClient`, project resolution, SQLite/PostgreSQL broker queues,
sidecar membership/cursor state, message encoding/decoding, and the
`bin/pytest-pg` shared-suite routing. The 250 messages are written through the
public production `say()` path. Do not mock `read()`, `read_unread()`,
`Queue.peek_many()`, state, cursor writes, or a backend as the primary proof.
A narrow call spy is allowed only in the invalid-input test to prove the
forbidden peek did not happen; the unchanged real cursor and subsequent full
read remain the behavior proof.

Red-green sequence:

1. Shared 250-message explicit-thread pagination, SQLite red then green.
2. The same test on PostgreSQL before another slice.
3. Invalid values and no-side-effect precedence, one case class at a time.
4. Boundary values and no-argument 1,000 default.
5. `thread=None` per-thread limit and direct `read_unread()` forwarding.
6. Neighboring decode-failure and default CLI regressions.

Only the 250-message pagination/cursor contract is required to fire on both
backends. The remaining focused cases exercise backend-neutral control flow in
`read_unread()` under the real SQLite broker and sidecar; [TAUT-11] does not
claim they rerun under PostgreSQL. If implementation introduces any backend
branch, this split becomes invalid and the affected cases move to the shared
suite before completion.

The key expected values are independent literals: page lengths 100/100/50 and
the known numbered-message slices 0..99, 100..199, and 200..249. Do not compute
expected pages by calling the same paging helper under test.

Targeted commands:

```bash
uv run --extra dev pytest tests/test_shared_contract.py::test_project_read_limit_paginates_without_skipping -q -n0
uv run ./bin/pytest-pg tests/test_shared_contract.py -k read_limit_paginates_without_skipping -q -n0
uv run --extra dev pytest tests/test_client.py -k 'read and (limit or cursor or decoding)' -q -n0
uv run --extra dev pytest tests/test_shared_contract.py -q -n0
uv run --extra dev pytest tests/test_public_api.py tests/test_docs_references.py -q -n0
```

The first targeted SQLite invocation must be retained once as RED evidence and
rerun as GREEN evidence. The PG invocation is a firing acceptance test, not a
substitute for the initial red observation.

## 10. Verification, Rollout Gates, and Completion Evidence

Per-task gates are the done signals in section 8. Final focused gates:

```bash
uv run --extra dev pytest tests/test_client.py tests/test_shared_contract.py tests/test_public_api.py tests/test_docs_references.py -q -n0
uv run ./bin/pytest-pg --fast
uv run ruff check taut/client/_messaging.py tests/test_client.py tests/test_shared_contract.py
uv run ruff format --check taut/client/_messaging.py tests/test_client.py tests/test_shared_contract.py
uv run --extra dev mypy taut tests --config-file pyproject.toml
git diff --check
```

Before any completion or release-readiness claim, run the full Development
block in `README.md`, including root and Summon tests, PostgreSQL fast tests,
both mypy partitions, Ruff checks, and all three builds. Do not weaken this to
focused tests because the public method is consumed by extensions and typed
callers.

Completion evidence must record:

- changed files and the contract each owns;
- the retained failing test command/output from the baseline behavior;
- current green SQLite and PostgreSQL pagination results;
- exact invalid-value, boundary, default, and per-thread test results;
- current docs, Ruff, mypy, full-suite, and build results;
- spec promotion baseline and final traceability reconciliation;
- independent plan/delta and final-diff review dispositions;
- MCP-plan reconciliation status;
- residual risk and whether the changes remain uncommitted.

No post-deploy observation can be marked complete until a package containing
the API is actually released. Local completion records the intended canary:
two consecutive 100-row calls over a backlog larger than 100, followed by the
remaining page, plus an unchanged default CLI read.

Current final evidence:

- Baseline RED:
  `uv run --extra dev pytest tests/test_shared_contract.py::test_project_read_limit_paginates_without_skipping -q -n0`
  failed because `MessagingMixin.read()` did not accept `limit`.
- The same targeted test passed on SQLite and through `bin/pytest-pg`; the
  first attempted cursor assertion was corrected because it observed every
  page only after all three reads, then both backends passed with the cursor
  sampled immediately after each call.
- The focused client/shared/public/docs gate passed 168 tests. The dedicated
  limit/cursor/decode selection passed 17 tests. PostgreSQL fast verification
  passed 193 shared and 14 PG-only tests.
- The full root suite passed 1,083 tests with one Windows-only skip. The full
  Summon suite passed 489 tests.
- Full Ruff checks passed and 136 files were format-clean. The PostgreSQL mypy
  partition passed 93 source files; the Summon partition passed 124. Core,
  PostgreSQL, and Summon source distributions and wheels all built
  successfully. `git diff --check` passed.
- The owner subsequently authorized a targeted commit. The pre-existing MCP
  plan and additive plan-index work were preserved; this change reconciles only
  the MCP `read` limit rows and their associated review/test obligations.

## 11. Rejected Alternatives, Scope Boundaries, and Residual Risk

Rejected:

- MCP-side slicing after `read()`: loses unread rows because core has already
  advanced through the larger page.
- A `.taut.toml` key or `TautClient` constructor setting: page size varies by
  caller and call; persistent/client policy creates stale hidden state.
- An aggregate limit for `thread=None`: breaks existing up-to-1,000-per-thread
  behavior and needs a new cross-thread ordering/fairness contract.
- A second MCP-only read implementation or direct queue access: duplicates
  cursor, membership, decoding, and backend semantics outside core.
- A CLI `--limit` flag: not requested and unnecessary to enable the MCP
  adapter. The CLI default remains deliberate.
- Storage/schema changes or a backend-specific SQL limit: core already uses
  the public broker page bound on both backends.
- Refactoring `log(limit=...)`, notification `inbox(limit=...)`, unread-count
  saturation, watcher batch sizes, or reply-suffix scan windows: those limits
  have different contracts.

Out of scope:

- MCP package implementation, SDK selection, or MCP spec promotion;
- changing MCP `thread` from required to optional;
- a total cross-thread context budget or interleaved/fair global pagination;
- a cursor token, continuation object, or new return type;
- config, schema, migration, dependency, release version, tag, push, or
  publication changes;
- unrelated cleanup in `_messaging.py`, shared tests, or the user-owned MCP
  plan.

Residual risk: the Python method iterates threads sequentially, so
`thread=None` is not an atomic snapshot. A concurrent writer can add messages
while the call runs, and an error on a later thread does not undo cursor
advances for earlier completed threads. This is existing behavior and remains
explicitly preserved. MCP's required single thread avoids that multi-thread
shape but a 100-message default is not a hard token budget because message
sizes vary.

## 12. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| None | Implement the promoted contract without scope expansion. | No behavior deviation identified through final review. | N/A | None. |

## 13. Independent Review and Fresh-Eyes Record

Review path: use the verified read-only Grok reviewer from
`docs/implementation/03-agent-inventory.md`, following
`skills/call-agent/SKILL.md`. The reviewer receives the baseline spec, this
plan and exact delta, relevant implementation/tests, implementation note, and
the in-flight MCP plan. The reviewer must not implement or edit.

Review prompt stance:

> Look for errors, bad ideas, latent ambiguities, cursor-loss paths, backend
> coverage gaps, and performative overengineering. Check the exact spec text
> against current code and the MCP plan. Recommend removals as readily as
> additions. Return explicit [P1]/[P2] findings and PASS or BLOCKED. Could a
> zero-context engineer implement this confidently and correctly after the
> delta is promoted?

Disposition table:

| Review finding | Reproduction/evidence | Disposition | Plan change |
|---|---|---|---|
| [P1] Proposed [TAUT-11] text claimed dual-backend validation, boundaries, and `thread=None` proof, but those cases were placed in `sqlite_only` `tests/test_client.py`. | Verified from module markers and `pytest_pg_main`: only `shared` tests run in the PostgreSQL shared lane. | Accepted. Dual-backend proof is required for the 250-message pagination/cursor regression; backend-neutral focused cases remain real SQLite tests unless code branches by backend. | Narrowed [TAUT-11], section 9, and the completion evidence to match the actual runner boundary. |
| [P2] Invalid-limit tests on an already joined thread would not prove validation precedes implicit sub-thread membership creation. | `_implicit_subthread_membership()` writes membership before the current `peek_many()` site. | Accepted. | Task 2 now requires an unjoined sub-thread invalid-limit firing case with no membership, peek, or cursor write. |
| [P2] Exact exception strings appeared only in the plan, not the promotable spec. | Strategy A makes the spec tree canonical after promotion. | Accepted. | Added both exact messages to proposed [TAUT-7.2] and [TAUT-10]. |
| [P2] Task 1 said “validated limit” although Task 2 owns validation. | The task order would invite horizontal implementation or premature scope. | Accepted. | Task 1 now passes the caller-supplied value; Task 2 owns first-operation validation. |
| Optional: the proposed delta codified existing multi-thread partial-failure behavior without adding a firing test. | The behavior is existing, not required for per-call pagination, and remains described as residual risk. | Accepted as scope reduction. | Removed the partial-failure sentence from the normative delta; retained the current-behavior warning outside the proposed contract. |
| Optional: the MCP design-lens `read limit` finding must not remain pending after reconciliation. | Section 16.3 of the MCP plan currently marks it `Pending (authoring session)`. | Accepted. | Task 3 now requires an accepted disposition tied to revised [MCP-5] text and tests. |

First review record: Grok read-only sandbox, session
`019f6639-5973-7840-b018-343dc84b2dcd`, `EndTurn`, verdict `BLOCKED`. No
sandbox fail-open warning or repository write was observed. A closure pass is
required after the accepted edits above.

Closure review record: the same read-only Grok session re-read the complete
revised plan and returned `EndTurn`, verdict `PASS`, with no new P1/P2 issue.
It verified every tabled disposition against the revised delta and tasks and
confirmed that a zero-context engineer can implement the plan confidently and
correctly after promotion. The reviewer noted, without making it a finding,
that the plan's “first operation” rule is slightly stricter than the promoted
spec's explicit list of forbidden prior effects; Task 2 and its unjoined-
subthread firing test make that stricter implementation order executable.

Final implementation review record: a fresh read-only Grok session
`019f664a-2919-78c2-ae9a-fb2ab7c295cf` inspected the final plan, tracked diff,
selected MCP-plan clauses, current implementation/tests, CLI adapter, and
SimpleBroker retrieval path. It returned `EndTurn`, verdict `PASS`, with no P1
or P2 finding. It specifically confirmed SQL-bounded oldest-first retrieval,
validation before every forbidden operation, immediate per-page cursor
sampling in the 100/100/50 shared test, accurate SQLite/PostgreSQL coverage
claims, unchanged CLI/config/schema boundaries, and MCP limit forwarding
without slicing. Local plugin, hook, and unavailable optional-MCP warnings were
non-sandbox environment noise; no sandbox fail-open warning or repository
write occurred.

Fresh-eyes checklist before declaring the plan ready:

- every file owner and unchanged boundary is named;
- exact exception, range, default, and per-thread semantics are testable;
- the 250-message proof checks order and cursor, not only length;
- invalid values prove no peek and no cursor movement;
- shared coverage demonstrably fires under SQLite and PostgreSQL;
- MCP default 100 is forwarded, not sliced, while its thread stays required;
- rollback, dependency ordering, stop gates, and post-release canary are
  explicit;
- no task invents config, storage, CLI, aggregate paging, or release scope;
- dirty user work is preserved;
- the final traceability and review loops are executable.
