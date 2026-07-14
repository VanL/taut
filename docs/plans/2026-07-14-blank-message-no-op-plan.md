# Blank Message No-Op Plan

Date: 2026-07-14

Status: implemented and verified in the worktree; independent final review
passed. Changes remain uncommitted pending repository-owner action.

Plan type: implementation with spec revision.

Class: 5. This changes the public Python and CLI write contract and crosses the
paired core/Summon package boundary. The Unicode classifier itself is
deliberately small and best-effort.

Owner: the implementing engineer owns spec promotion, the core predicate and
write boundary, CLI result mapping, Summon adaptation, real-backend tests, and
documentation reconciliation. The repository owner owns the release-version
choice and any release action.

## 1. Goal

Make empty and conventionally blank Taut-authored chat input a no-op. Use the
running Python's built-in Unicode behavior rather than a pinned Unicode data
table: a string is blank when it is empty or every character is whitespace
under `str.isspace()` or has Unicode general category `Cf` under
`unicodedata.category()`. Direct API calls receive a typed empty result; the
CLI exits 2 silently; Summon terminal mode silently continues.

This is an ergonomic guard for the common mistake, not an exhaustive promise
that every renderer-invisible string will be rejected.

## 2. Decided Behavior

- Blank: `text == ""` or every character satisfies `ch.isspace()` or
  `unicodedata.category(ch) == "Cf"` in the running Python interpreter.
- Common whitespace, zero-width space, zero-width joiner/non-joiner, word
  joiner, BOM/zero-width no-break space, soft hyphen, and bidi format controls
  are therefore blank when they are the whole message.
- A character outside that predicate makes the entire message nonblank. Taut
  stores the original string exactly; it does not trim, normalize, or strip
  the blank-class characters around visible text.
- The set follows the Unicode database shipped with the supported Python
  runtime. Taut does not promise identical edge membership across Python
  versions.
- The rule is intentionally incomplete. Invisible non-`Cf` marks such as a
  standalone variation selector or combining grapheme joiner may pass. Do not
  add a generated table, external Unicode package, display-width dependency,
  or exhaustive code-point fixture in this change.
- `TautClient.say()` and `reply()` raise public
  `BlankMessageError(EmptyResultError)` before target parsing or any
  message-domain work. Their successful return type remains `Message`.
- `taut say` and `taut reply` map that subtype to exit 2 with no stdout,
  stderr, JSON record, warning, or traceback. Exit 0 would falsely claim a
  write; exit 1 would misclassify the no-op as an error.
- Blank-first validation wins over invalid targets, missing reply parents,
  membership failures, and incomplete-rename diagnostics after the public
  method is invoked. CLI parsing, stdin acquisition, storage resolution,
  schema checks, and client construction retain their existing priority.
- No message-domain side effect is allowed: no identity/activity change,
  channel/DM/subthread/membership creation, queue/timestamp/message,
  notification, warning, or cursor movement.
- Existing blank Taut envelopes, raw SimpleBroker bodies, and structural
  join/leave/creation notices remain readable and are not filtered.
- Summon terminal mode catches only `BlankMessageError` before the existing
  `TautError` branch, logs nothing for that event, and keeps running. Other
  posting failures remain errors.

## 3. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-6.1], [TAUT-6.3], [TAUT-6.4],
  [TAUT-8.1], [TAUT-8.2], [TAUT-8.3], [TAUT-10], [TAUT-11], [TAUT-12.5]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-5], [IAN-7.3]
- `docs/specs/04-summon.md` [SUM-6], [SUM-11], [SUM-12]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]

Implementation context:

- `README.md`, especially the current statement that empty messages are valid
- `taut/client/_messaging.py`
- `taut/_exceptions.py`, `taut/__init__.py`
- `taut/commands/_dispatch.py`, `taut/commands/say.py`,
  `taut/commands/reply.py`
- `extensions/taut_summon/taut_summon/_driver.py`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `bin/check-core-summon-wheel-matrix.py`

Process guidance:

- `AGENTS.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`

## 4. Spec Baseline

- Baseline commit: `8575ed294d6f43efe38875254a0609bce6582a98`.
- Authoring began against that commit plus unrelated dirty trusted-identity and
  TUI documentation work. Preserve those user-owned changes.
- Relevant pre-plan hashes:
  - `docs/specs/02-taut-core.md`:
    `878f5883bd5aed42516cdaaa52f3e974858787d87250bdcc8d4a643087d9e03b`
  - `docs/specs/04-summon.md`:
    `a27b448803560d88ec99852b0d6309fca2dfd94cee7f12db1a267cbbe88516c2`
  - `docs/implementation/04-taut-architecture.md`:
    `9b0396818423f610d132ad85c03ec0df63b569dd016e72aaa6c4b111f9217fe8`
- The active specs remain canonical until promotion.
- Promotion strategy: **A, in-file requirement text before implementation-link
  claims**. Review the exact delta, promote it, add Related Plans backlinks,
  run the docs gate, and record a promotion baseline before code changes.
- Promotion baseline: canonical requirements were promoted before behavior
  code changed and passed `tests/test_docs_references.py` (10 passed) plus
  `git diff --check`. Post-promotion SHA-256 values:
  - `docs/specs/02-taut-core.md`:
    `47866b37fad50a8d8dc3bf36f65e5836db084636ae1dfec52d5ab615bfbefc7b`
  - `docs/specs/03-identity-addressing-notifications.md`:
    `d607728da527f9d5927fe365136ec9f3429e1e00538b26c85741221b3086c235`
  - `docs/specs/04-summon.md`:
    `ed5409da2b667864b9ae8958495b1c590ec1fef717b88118cfe14dfecad5acb3`

## 5. Current Structure and Risks

- `MessagingMixin.say()` parses targets and may resolve/create identity before
  writing. A first DM can create its thread, two memberships, a message,
  notifications, and cursor state.
- `MessagingMixin.reply()` can create the subthread and membership before
  `_write_message`. Therefore `_write_message` is too late for validation. It
  also writes structural notices from `_threads.py`, which must stay exempt.
- Add one small private `taut/_message_text.py` predicate and call it as the
  first operation of both public methods. CLI and Summon translate the typed
  result but never duplicate the predicate.
- The dispatcher currently renders every non-quiet exception. It needs a
  narrow silent branch for `BlankMessageError`; other exit-2 diagnostics stay
  unchanged.
- Summon terminal mode currently catches every `TautError` from `mouth.say()`
  and logs `terminal-mode post failed`. Catch the exact new subtype first. Do
  not catch all `EmptyResultError`, because `NotFoundError` is one of them.
- New Summon imports a new core export, so its release metadata must require the
  first core version containing that export. The version slice is coupled by
  `tests/test_project_metadata_consistency.py`: `pyproject.toml`,
  `taut/_constants.py`, `extensions/taut_pg/pyproject.toml`,
  `extensions/taut_summon/pyproject.toml`,
  `extensions/taut_summon/uv.lock`, `README.md`,
  `extensions/taut_pg/README.md`, and
  `extensions/taut_summon/README.md` must agree on the applicable package
  versions and dependency floors. `CHANGELOG.md` records the compatibility
  change. Core and Summon 0.6.5 are already published; recheck release state
  and use the next unpublished paired version during release preparation.

Comprehension gate before editing:

1. Why are `say()` and `reply()` entry points the first shared side-effect-free
   boundary, and why is `_write_message` too late?
2. Which blank call side effects must remain absent for channel, first DM, and
   first reply paths?
3. Why does a typed empty exception preserve `-> Message` better than returning
   `None`?
4. Why must CLI silence and Summon silence match only the new subtype?
5. Which invisible non-`Cf` strings are intentionally outside this small rule?

## 6. Proposed Spec Delta

Promotion strategy: **A**.

| Spec file | Sections touched |
|---|---|
| `docs/specs/02-taut-core.md` | [TAUT-6.4], new [TAUT-6.5], [TAUT-8.1], [TAUT-8.2], [TAUT-8.3], [TAUT-10], [TAUT-11], Related Plans |
| `docs/specs/03-identity-addressing-notifications.md` | [IAN-7.3], Related Plans |
| `docs/specs/04-summon.md` | [SUM-6], [SUM-12], Related Plans |

### [TAUT-6.4] — replace the opening paragraph

> Body size and content limits for accepted messages are SimpleBroker's (10 MB
> default). Taut adds no storage-size limit of its own. Except for new blank
> `say` and `reply` attempts filtered under [TAUT-6.5], `text` may otherwise
> contain arbitrary UTF-8, including newlines and terminal control characters.
> Storage, Python API objects, and `--json` output preserve the exact content of
> every accepted or already-stored message.

### Insert [TAUT-6.5] after [TAUT-6.4]

> ### [TAUT-6.5] Blank user messages
>
> A proposed user message is blank when its text is empty or every character
> returns true from `str.isspace()` or has Unicode general category `Cf` from
> `unicodedata.category()` in the running supported Python interpreter. This is
> a best-effort chat-input guard, not an exhaustive renderer-visibility or
> Unicode `Default_Ignorable_Code_Point` contract. Its edge membership may
> change when Taut's supported Python runtime changes.
>
> `TautClient.say()` and `TautClient.reply()` filter blank text as their first
> operation and raise public `BlankMessageError`, a subclass of
> `EmptyResultError`. The check precedes target parsing, incomplete-rename
> checks, identity/activity work, queue/timestamp work, and all thread,
> membership, message, notification, and cursor mutation. Blank filtering thus
> wins over later target, parent-message, membership, and rename failures.
> Parsing, text acquisition, storage/schema bootstrap, and client construction
> that occur before the method call keep their existing priority. For human
> CLI output, terminal-policy preflight occurs before command execution; an
> unavailable policy therefore retains its existing diagnostic exit 1 and
> wins over blank filtering.
>
> If any character is outside the predicate, Taut stores the complete original
> string exactly, including surrounding whitespace and `Cf` characters. It
> does not trim, normalize, or strip. Existing stored messages, foreign broker
> bodies, envelope decoding, and structural join/leave/creation notices remain
> readable and are not filtered.

### [TAUT-8.1] — revise the `say`/`reply` rows and exit rule

Replace the two rows with:

> | `say TARGET [TEXT\|-]` | Post a message (stdin with `-` or when piped and TEXT omitted). Blank text is filtered before routing under [TAUT-6.5]. `TARGET` may be a channel, sub-thread, or `@name` direct-message target ([IAN-5]). Channel and sub-thread targets require membership. Prints message id with `-t` only when a message is written. | 0 wrote; 1 error; 2 blank filtered / not a member / no such member |
> | `reply THREAD MSG_ID [TEXT\|-]` | Post into the sub-thread of MSG_ID, creating it on first reply. Blank text is filtered before parent resolution under [TAUT-6.5]. Requires membership in THREAD. A full 19-digit id resolves exactly. A suffix >= 4 digits resolves via a bounded public-API scan of the most recent 1,000 message ids of THREAD; ambiguous -> error listing candidates. | 0 wrote; 1 error (including ambiguous suffix); 2 blank filtered / no such message / not a member |

Append this exact exit rule:

> A blank `say` or `reply` filtered under [TAUT-6.5] is an empty-result exit 2,
> not success and not an error. It emits no stdout or stderr in human, JSON, or
> quiet mode because no record or diagnostic was produced. Human-mode terminal
> policy preflight retains priority: if the policy is unavailable, the command
> exits 1 with its existing fixed diagnostic before blank filtering runs.

### [TAUT-8.2] — revise the writing-verbs bullet

Replace the writing-verbs bullet with:

> - writing verbs (`say`, `reply`) echo the message object they wrote, with the
>   same fields as read messages. A blank attempt filtered under [TAUT-6.5]
>   writes no message, emits no human or JSON record, and exits 2. For a
>   successful write, the robust id-capture idiom remains
>   `taut say t "x" --json | jq -r 'select(has("ts")).ts'`, because a first-ever
>   use may emit a leading creation line with no `ts`;

### [TAUT-8.3] — add the public typed outcome

Replace the public-export sentence with:

> Public exports from `taut`: `TautClient`, `TautWatcher`, `Message`, `Thread`,
> `Member`, the exception hierarchy rooted at `TautError` including
> `BlankMessageError`, `escape_terminal_text`, and `__version__`.

Append:

> `BlankMessageError` is a public subclass of `EmptyResultError`. It is the
> Python API result for a filtered [TAUT-6.5] `say` or `reply`, allowing both
> methods to retain `Message` as their success type. No message id or related
> domain state exists after this exception.

### [TAUT-10] — add one failure-mode bullet

> - Blank `say` or `reply`: raise `BlankMessageError` before route/state work;
>   the CLI exits 2 silently and no message-domain side effect occurs.

### [TAUT-11] — add verification requirements

> - Predicate tests cover empty text, ASCII and non-ASCII whitespace, common
>   `Cf` zero-width/format characters, mixtures, and visible text containing
>   such characters without claiming exhaustive Unicode visibility. A named
>   invisible non-`Cf` counterexample remains accepted to pin the boundary.
> - Real client and CLI tests prove channel, first-DM, and first-reply blank
>   attempts leave identity/activity, thread, membership, queue, message,
>   notification, and cursor state unchanged; CLI modes exit 2 silently; and
>   accepted text remains exact. Shared coverage runs on SQLite and PostgreSQL.

### [IAN-7.3] — prepend

> A blank attempt filtered under [TAUT-6.5] never becomes a source message and
> never enters mention, reply, or `dm_started` notification dispatch.

### [SUM-6] — append to terminal-mode behavior

> A terminal-mode assistant event rejected by core with `BlankMessageError` is
> a silent no-op: Summon writes no chat row, logs no terminal-mode post failure,
> and continues the same generation. Every other posting failure retains the
> existing error and supervision behavior.

### [SUM-12] — append

> - A real scripted-provider process emits a blank assistant event followed by
>   visible text in terminal mode. Against a real broker and driver, the blank
>   event creates no message or error log, the visible event posts exactly, and
>   STOP remains responsive.

### Related Plans — add to all touched specs

> - `docs/plans/2026-07-14-blank-message-no-op-plan.md` — built-in Unicode
>   blank-input guard, typed empty result, silent CLI exit 2, and Summon
>   terminal-mode adaptation.

## 7. Invariants, Rollback, and Compatibility

Invariants:

- one pure predicate owned by core; no CLI/Summon copy;
- first-line validation in both public write methods;
- no trimming or normalization of accepted text;
- no read-side filtering or notice/foreign-body change;
- only `BlankMessageError` becomes silent;
- no new dependency, Unicode data file, generator, or schema;
- no claim of exhaustive invisible-character coverage;
- unrelated dirty-worktree changes remain untouched.

Stop and re-plan if implementation requires a Unicode table/dependency,
display-width logic, validation after a state operation, a broad
`EmptyResultError` catch, a second predicate, or any history/schema change.

There is no data migration. Existing blank records remain readable. A filtered
attempt has no record to reconstruct, which is intentional. Rollback restores
future blank writes but does not reinterpret history.

Paired compatibility:

| Core | Summon | Result |
|---|---|---|
| new | new | silent blank no-op in core and terminal mode |
| new | old 0.6.5 | core filters; old Summon remains alive but logs its generic post failure |
| old 0.6.5 | new | unsupported; dependency metadata must prevent installation |

Roll out core as the new Summon's immediate dependency, then canary the paired
wheels before announcement. Roll back old Summon before old core. The release
metadata slice uses the next unpublished owner-selected version; no remote
action is authorized by this plan.

Implementation metadata selection: local and remote tag inspection found
0.6.5 published for core, Taut-PG, and Summon and no 0.6.6 tag. The source and
derived metadata slice therefore advances all three packages to 0.6.6. This is
release preparation only; no commit, tag, push, or publication is authorized.

## 8. Dependency-Ordered Tasks

### Task 0: Review and promote the contract

1. Independently review this plan and exact delta, especially the deliberately
   non-exhaustive predicate, blank-first precedence, silent exit 2, and paired
   floor.
2. Resolve [P1]/[P2] findings.
3. Promote the spec delta, add backlinks, run
   `tests/test_docs_references.py`, run `git diff --check`, and record the
   promotion baseline before code changes.

### Task 1: Add the predicate and typed public result red-first

1. Add failing focused tests for empty, ASCII whitespace, NBSP/Unicode space,
   U+200B, U+200C, U+200D, U+2060, U+FEFF, soft hyphen/bidi `Cf` controls, and
   mixtures. Test visible text plus ZWJ and an emoji ZWJ sequence as accepted
   and exact. Pin one invisible non-`Cf` case, such as U+FE0F, as accepted so a
   later change cannot silently claim exhaustiveness.
2. Add `taut/_message_text.py` with a typed predicate using only
   `str.isspace()` and `unicodedata.category()`.
3. Add `BlankMessageError(EmptyResultError)` and its root export. Update
   `tests/test_public_api.py` and lazy-import tests.
4. Run focused tests, Ruff, and mypy. Do not add a performance benchmark unless
   normal 10 MB correctness inspection exposes a real issue.

### Task 2: Enforce the rule before every message-domain operation

1. Add real SQLite client tests for channel `say`, first DM, and first `reply`.
   Snapshot history and relevant identity/activity/thread/membership/
   notification/cursor state before and after.
2. Add blank-first precedence tests for a missing target, missing parent id,
   and incomplete rename.
3. Add one shared-contract test for real SQLite/PostgreSQL execution.
4. Call the predicate as the literal first operation of `say()` and `reply()`;
   raise the typed exception. Do not edit `_write_message` or `_threads.py`.
5. Prove visible-plus-`Cf` text round-trips exactly and historical blank Taut
   envelopes, foreign blank bodies, and notices remain readable.

### Task 3: Make the CLI a silent exit-2 no-op

1. Add black-box `tests/test_cli.py` cases for `say` and `reply`, explicit empty
   argument, Unicode blank mixture, `-` stdin, omitted piped stdin, human,
   `--json`, and `--quiet` modes. Assert exit 2, empty stdout/stderr, no
   traceback, and unchanged durable state.
2. Add missing-target/parent precedence probes and preserve existing parser,
   TTY-input, bootstrap, and other exit-2 diagnostics. Add a blank human-input
   probe with an unavailable terminal policy; assert that preflight still exits
   1 with its fixed diagnostic before the client method runs. JSON mode does
   not run that human-output preflight and still reaches silent blank exit 2.
3. Add a narrow dispatcher branch returning 2 before rendering only for
   `BlankMessageError`. Update `say`/`reply` help to describe the no-op. Do not
   classify characters in command adapters.

### Task 4: Adapt Summon and paired artifacts

1. Extend the existing real terminal-mode driver test: scripted provider emits
   a blank `Cf`/whitespace event, then visible text. Assert no blank row/log,
   exact visible post, live generation, responsive STOP.
2. Catch public `BlankMessageError` before `TautError` in `_pump_event`. Retain
   a firing test for a real nonblank posting failure.
3. Add an installed-pair assertion that the exception imports and subclasses
   `EmptyResultError`; no new wheel-matrix topology is needed.
4. Before release readiness, use the owner-selected next version so Summon's
   exact `taut>=` floor names the first core containing the exception. Recheck
   rather than assume 0.6.6. Reconcile the whole enforced version slice:
   `pyproject.toml`, `taut/_constants.py`,
   `extensions/taut_pg/pyproject.toml`,
   `extensions/taut_summon/pyproject.toml`,
   `extensions/taut_summon/uv.lock`, `README.md`,
   `extensions/taut_pg/README.md`, and
   `extensions/taut_summon/README.md`. Preserve Taut-PG's exact core floor and
   record the compatibility change in `CHANGELOG.md`.

### Task 5: Reconcile docs and run final gates

1. Update `README.md` to replace the valid-empty example with the concise
   built-in predicate, silent exit 2, limitation, and exact accepted-text rule.
2. Update `docs/implementation/02-repository-map.md`,
   `docs/implementation/04-taut-architecture.md`, and
   `docs/implementation/05-taut-summon-architecture.md` with owners,
   boundaries, rationale, and reciprocal spec/code/test mappings.
3. Update `CHANGELOG.md` with the human-authored compatibility note during
   release preparation. Update the Summon README only if its terminal-mode
   posting text needs correction.
4. Run focused tests, docs references, fast PostgreSQL, metadata/wheel checks,
   then the complete `README.md` Development block. Apply the CLI adversarial
   probes through the real entry point. Do not increase timeouts or add retries.
5. Run an independent final diff review, reconcile the deviation log, and
   report exact changed files, commands, results, residual version-dependent
   Unicode behavior, and commit state. Do not commit without owner authority.

## 9. Testing and Anti-Mocking Boundary

Keep real: SQLite/PostgreSQL queues and sidecar state, public client, CLI
dispatcher/streams, Summon driver and scripted-provider processes, STOP
control, and installed wheels. Small pure predicate tests may call
`unicodedata` directly. Do not mock `_write_message`, state, Queue, CLI client,
or `mouth.say` as the only proof.

Focused commands:

```bash
uv run --extra dev pytest tests/test_message_text.py tests/test_public_api.py -q -n0
uv run --extra dev pytest tests/test_client.py tests/test_cli.py tests/test_shared_contract.py -q -n0
uv run --extra dev pytest extensions/taut_summon/tests/test_driver.py -q -n0
uv run --extra dev pytest tests/test_docs_references.py tests/test_project_metadata_consistency.py tests/test_core_summon_wheel_matrix.py -q -n0
uv run ./bin/pytest-pg --fast
git diff --check
```

The final gate is the full Development block in `README.md`, including both
mypy runs and all three builds.

## 10. Rejected Alternatives and Named Limitations

- `Message | None`: wider public success type and weaker caller discipline.
- Exit 0 or 1: respectively claims a write or claims an error; exit 2 already
  means nothing was produced.
- `^\s*$`: misses common `Cf` zero-width characters and has anchor edge cases.
- Exact `Default_Ignorable_Code_Point`: requires a table/dependency because
  Python's built-in `unicodedata` does not expose it. That ceremony is not
  justified for this ergonomic guard.
- A hand-maintained exhaustive zero-width list or generated UCD fixture: false
  precision and maintenance cost beyond the requested error class.
- `wcwidth`, font, or renderer tests: presentation-dependent and broader than
  chat input validation.
- Trimming/normalizing: corrupts accepted exact content.
- Read-side cleanup: changes history and foreign input rather than future Taut
  writes.

Named residual: an invisible character outside whitespace and `Cf`, including
some marks and variation selectors, can still produce an apparently blank
message. That is accepted by design. The rule captures the common error type,
not every Unicode visibility edge.

## 11. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [TAUT-3.4], [TAUT-8.3], [IAN-8.2] | No dependency-floor change owned by this feature | Reconciled canonical dependency text to the already-present SimpleBroker 5.3.3 and SimpleBroker-PG 3.2.2 manifest floors | The metadata gate required propagation of concurrent manifest changes; leaving the specs at 5.3.2/3.2.1 would preserve a known adjacent inconsistency | Promoted the exact current floors and their upstream fixed-behavior rationale |

## 12. Independent and Fresh-Eyes Review

Pre-promotion review record:

- Claude review timed out without a verdict; Grok exited before returning a
  verdict. Neither produced findings used as a gate.
- An independent repository-context review found incomplete exact replacement
  rows, omitted Taut-PG version coupling, invalid multiline table rows, and an
  omitted human terminal-policy preflight precedence case.
- The plan now supplies exact valid table rows, names the enforced metadata
  slice, and pins terminal-policy precedence with a firing regression test.
- The same independent reviewer re-ran the gate and returned `PASS` before
  spec promotion.
- Final implementation review found missing firing coverage for membership
  precedence and mention/reply notification absence, plus three stale ownership
  descriptions. Compact real-client tests and wording fixes resolved every
  finding. The reviewer re-ran the affected checks and returned `PASS` with no
  remaining P0-P2 finding.
- Release audit found that the original failing-test result was not retained.
  Accepted. The plan does not infer or fabricate historical red evidence and
  records an explicit TDD exception. Substitute proof: a controlled mutation
  made `is_blank_message_text()` return `False`; the real predicate suite then
  exited 1 with eight blank cases failing and four nonblank cases passing.
  Restoring the specified predicate produced 12 passes. This proves the tests
  fire on the classifier contract, but it does not claim the missing historical
  order.

The pre-promotion reviewer and final reviewer must verify:

- the spec does not overclaim Unicode exhaustiveness;
- common whitespace and `Cf` cases fire while visible-plus-format text stays
  exact;
- blank validation precedes every domain side effect;
- only the new subtype is silent in CLI and Summon;
- real SQLite, PostgreSQL, CLI, process, and artifact seams remain real;
- paired dependency/rollback order is explicit;
- specs, implementation docs, README, changelog, plan index, and backlinks
  agree;
- unrelated dirty work remains untouched.
