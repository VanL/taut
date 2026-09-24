# CLI Read Delivery and Agent Recipe Corrections Plan

Status: draft — findings verified by reproduction; all owner decisions
recorded (2026-09-24); awaiting independent plan review.

Class: 5 (spec-changing) and risky under [DOM-5]: the change revises the
normative cursor-advance wording in [TAUT-7.2], the [TAUT-8.1] `join` row and
polling idiom, the [TAUT-8.1] exit-class text for a malformed reply suffix,
and the storage-discovery diagnostic under [TAUT-3.2]. CLI shape and public
exit classes are compatibility surfaces, so hardening is required. Not
process-changing.

Plan type: implementation with spec revision.

Owner: implementing engineer. The repository owner decided the three open
questions on 2026-09-24 (see the Execution Log).

## Goal

Make the agent-facing CLI deliver what it claims. Today `taut read` commits
the member's bookmark before any byte reaches stdout, the documented polling
recipe (`taut read -q` in a loop) advances the bookmark while printing
nothing, every repeated `join` writes a fresh "joined" notice, a malformed
reply suffix exits with the empty-result code, the reply-suffix guidance
assumes an id layout SimpleBroker does not produce, and an unusable
`.taut.db` is reported as missing. Each of these was reproduced on
2026-09-23 (see `docs/plans/artifacts/2026-09-23-deep-dive-review.md`,
§1 items 4–5 and §2).

## Requested Outcomes

- [ ] `taut read` advances a thread's cursor only through records that were
  written to stdout; a delivery failure (broken pipe, encoding error) leaves
  the cursor at the last written record.
- [ ] `taut read -q` is a usage error (exit 1, one-line diagnostic naming
  `list -q`): read's output is its effect, so a silent read would only
  advance the bookmark. The kernel, README, and core spec recommend
  `taut list -q` as the polling idiom. `taut inbox -q` is rejected the same
  way (owner decision 2026-09-24), because a silent inbox claims and
  discards pointers.
- [ ] Joining a channel the member already belongs to succeeds without
  writing a notice or moving the cursor.
- [ ] The short-form (suffix) message id is removed: `reply` accepts only
  the full 19-digit id, matching `message show`, `message delete`, and
  `message react`; the human `inbox` action line prints the full id; the
  README Quick Start, kernel, and [TAUT-8.1]/[IAN-7.4] text drop the suffix
  form (owner decision 2026-09-24). Any non-19-digit
  `MSG_ID` is a malformed argument, exit 1. The MCP `reply.msg_id` schema
  tightening lands in the MCP plan; the active command-runtime plan's
  Slice 5 (suffix-window batching) is superseded by this removal.
- [ ] An existing-but-unusable `.taut.db` (unreadable, unwritable, or not a
  SimpleBroker database) produces SimpleBroker's own diagnostic, not the
  "not found / run taut init" hint.
- [ ] The CLI subprocess harness has a companion test that runs without a
  forced `PYTHONIOENCODING`.
- [ ] [IAN-5.2] states that mention parsing is markup-blind — `@name`
  inside backtick spans, fenced blocks, quotes, or paths is a mention — and
  a probe pins it (owner decision 2026-09-24).

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-7.2], [TAUT-7.4],
  [TAUT-8.1], [TAUT-8.2], [TAUT-10]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-5.2] (mention
  grammar), [IAN-7.4] (inbox action line, suffix removal)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10.1], [DOM-15]

Supporting context:

- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` — reproduction
  commands and evidence for every finding here.
- `docs/program-theory.md` [THEORY-2] (the queue is the history; readers
  peek; "read" means "move my bookmark"), [THEORY-5] A1 (notification
  pointers stay consumable — this plan changes no claim semantics; it only
  refuses the silent `inbox -q` form), A5 (cursor advancement last and
  best-effort).
- `docs/agent-context/runbooks/testing-patterns.md` Pattern 7 (the harness
  forces `PYTHONIOENCODING=utf-8` on every CLI subprocess test).
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md` floors 1,
  2, and 5.
- `docs/plans/2026-08-24-command-runtime-findings-remediation-plan.md`
  (active): Slice 4 owns `UnrecognizedCallerError` exit mapping and Slice 5
  owns suffix-window batching for inbox rendering. This plan does not touch
  either; it changes only the short-suffix exit class and the human `reply`
  echo.
- `docs/agent-kernel.md` line 23 and `README.md` line 597 (the polling
  recipe), `README.md` "Quick Start" (`reply general 0161024`).

## Spec Baseline

- `c0a4616e76e954e3f9fbea93fbf487c3ee660cbe` — `docs/specs/02-taut-core.md`
  and `docs/specs/03-identity-addressing-notifications.md` at plan authoring
  time; both unchanged through `c894059` (0.9.9 release SHA).
- Promotion baseline identifier: recorded after the spec-promotion slice.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**. Promote
the [TAUT-7.2], [TAUT-8.1], and [TAUT-3.2] text before code; add link claims
and the reciprocal backlink in the final slice.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A | [TAUT-7.2] first bullet; [TAUT-8.1] `join`, `read`, `inbox`, and `reply` rows, the exit-code paragraph, and the help-text paragraph; [TAUT-3.2] discovery diagnostic; `## Related Plans` |
| `docs/specs/03-identity-addressing-notifications.md` | A | [IAN-5.2] markup-blind rule; [IAN-7.4] inbox action line; `## Related Plans` |

### [TAUT-7.2] — replace the first bullet

Current text:

> - `read`, `watch`, and successful `message show` advance it as they display
>   messages.

Proposed text:

> - `read`, `watch`, and successful `message show` advance it as they display
>   messages. For the CLI adapters this is literal: the cursor commits only
>   through records that the adapter has written to its output stream. When
>   delivery fails partway (a closed pipe, an encoding error, or a
>   presentation-policy failure), the cursor remains at the highest record
>   already written and the remaining records stay unread. The Python
>   `read()` and `read_unread()` calls return a whole page to the caller and
>   commit it atomically, because the caller already holds the records when
>   the call returns.

### [TAUT-8.1] — replace the polling sentence in the exit-code paragraph

Current text:

> Exit-code rule, matching SimpleBroker: 0 success, 1 error, 2 "empty /
> nothing matched / not found" — so `taut read -q && process_inbox` and
> polling loops compose in shell.

Proposed text:

> Exit-code rule, matching SimpleBroker: 0 success, 1 error, 2 "empty /
> nothing matched / not found" — so polling loops compose in shell. The
> polling idiom is `taut list -q && handle_new`: `list` never moves a
> cursor, exits 0 only when something is unread, and leaves the messages
> for a following `read`. `read` and `inbox` reject `-q` as a usage error:
> their output is their effect, and a silent invocation would only advance
> a bookmark or discard claimed pointers. The diagnostic names `list -q`.

Also amend the root `-q/--quiet` help sentence (`_dispatch.py:~644`) to
`Suppress ordinary output while preserving exit status; rejected by read
and inbox, whose output is their effect.`

Also replace the later sentence `polling idioms like `taut read -q &&
handle_new` cannot mistake a typo for "nothing new"` with `polling idioms
like `taut list -q && handle_new` cannot mistake a typo for "nothing new"`.

### [TAUT-8.1] — amend the `read` and `inbox` rows

Append to the `read` row's description cell: `Rejects `-q` (usage error,
exit 1).` Append the same to the `inbox` row.

### [TAUT-8.1] — replace the `join` row

Proposed row:

> | `join THREAD [--as NAME_OR_ALIAS] [--persona TEXT] [--new]` | Register identity if needed (`--new` forces a fresh member), create a channel if needed, add membership (cursor at now, [TAUT-7.4]), write notice. When the acting member already belongs to THREAD, `join` succeeds, applies `--persona` if given, and writes no notice, no membership row, and no cursor change; it prints the thread header so callers see the same shape either way. `--persona` sets/updates the member's persona. | 0; 1 error |

### [TAUT-8.1] — replace the `reply` row's id sentences

Replace `A full 19-digit id resolves exactly. A suffix >= 4 digits resolves
via a bounded public-API scan of the most recent 1,000 message ids of
THREAD; ambiguous -> error listing candidates.` with:

> MSG_ID is the exact 19-digit message id, as for `message show`,
> `message delete`, and `message react`; there is no short form. Any other
> value is a malformed argument.

and make the exit cell read `0 wrote; 1 error, including a malformed
MSG_ID; 2 no such message / unrecognized member`. Remove the `message-id
suffix` mention from the help-text paragraph at line ~1268.

### [IAN-5.2] — add one rule to the list

Append after the `Mentions inside foreign broker bodies are not parsed by
Taut.` bullet:

> - Mention parsing is markup-blind. Taut does not interpret Markdown or
>   any other markup: an `@name` token inside a backtick span, a fenced
>   block, a quotation, or a path is a mention whenever its route key
>   resolves. A false mention costs its recipient one consumable pointer;
>   a missed mention costs a person not being told, so the parser errs
>   toward notifying. The email-shaped exclusion (`x@name.tld`) is the only
>   inert form.

Recorded rejected alternative (owner, 2026-09-24): making mentions inert
inside code spans and fences. Rejected because it adds a second grammar
that must stay consistent with two renderers, suppresses a rare and cheap
false positive, introduces a rarer but worse false negative, and defends
against no threat inside one trust domain. Reconsider when: a real
workspace shows agents notifying each other through pasted code often
enough to be a measured nuisance.

### [IAN-7.4] — amend the inbox action line

Replace the sentence at line ~549 that promises a `source-message suffix
usable with `taut reply`` with: `the exact 19-digit source message id in a
ready-to-run `taut reply <thread> <id>` action`; delete the
`reply-suffix eligibility and uniqueness probes` clause at ~555.

Recorded rejected alternative (owner, 2026-09-24): keep a short id as a
git-like affordance. To be git-like it must satisfy all three properties
git's abbreviated SHA has, none of which the current form has: (1) taut
prints the short form itself wherever human output shows an id (`log -t`,
inbox actions, reply echo), so a user never derives it by hand; (2)
resolution runs over the whole thread, not a 1,000-row window, so a short
id either matches exactly one message or errors — it can never silently
rebind to a newer message; (3) the minimum length reflects the real
entropy of decimal suffixes over ids that are multiples of 4096 (four
digits give 625 values; seven give about 78,000), so the floor is seven
digits. Not adopted because its audience is a human replying by hand at a
bare CLI, which the TUI now serves natively, while agents and scripts use
the full id; the git-like version is more machinery than today's, for a
narrow case. Reconsider when: a human CLI workflow without the TUI needs
hand-typed replies — then implement this version and nothing weaker.

### [TAUT-3.2] — append to the discovery diagnostic paragraph

Locate the paragraph that defines the `No taut database found. Run 'taut
init'` diagnostic (grep for that string). Append:

> When discovery locates a `.taut.db` path that exists but cannot be used —
> unreadable, unwritable, or not a SimpleBroker database — the diagnostic
> names that path and SimpleBroker's own validation reason, exits 1, and
> does not suggest `taut init`. `taut init` on such a path reports the same
> reason and exits 1 rather than reporting `exists:`. Only an absent path is
> "not found".

### `## Related Plans` — add

> - `docs/plans/2026-09-24-cli-read-delivery-and-agent-recipes-plan.md` —
>   makes CLI `read` advance cursors only through delivered records, changes
>   the documented polling idiom to `list -q`, makes repeated `join` silent,
>   corrects the malformed-suffix exit class, and makes unusable-storage
>   diagnostics truthful.

## Context and Key Files

Files to modify:

- `taut/commands/read.py` — `ReadCommand.run()` calls
  `client.read_unread(args.thread)` (which advances the cursor inside core
  before returning) and then `emit_messages(...)`. The order is the defect.
- `taut/client/_messaging.py` — `read()` (line ~296) and `read_unread()`
  (line ~336) fetch the page, then call `self._state.advance_cursor(...)`
  (line ~329). `_resolve_message_id()` (line ~792–820): full-id exact path
  plus the suffix scan (`suffix must be at least 4 digits` at ~802,
  `ambiguous message id suffix` at ~815) — the scan and both errors are
  removed; the exact path stays.
- `taut/commands/_rendering.py` — the shortest-unique suffix derivation for
  the inbox action line (line ~900–910) is removed; the action prints the
  full id.
- `taut/commands/reply.py` — help text at lines ~13, ~21, ~30 names the
  suffix form; reword to the exact id.
- `taut/client/_threads.py` — `join()` (line ~80) builds a notice
  (`created #thread` at ~114 or `joined` at ~120), calls
  `self._state.add_membership(...)` (~121, `ON CONFLICT DO NOTHING`), and
  writes the notice unconditionally.
- `taut/client/_base.py` — `_require_target()` (line ~340–360) raises
  `NotInitializedError(NO_DATABASE_MESSAGE)` when SimpleBroker's
  `is_valid_database` returns false for an existing SQLite path.
- `taut/commands/reply.py` — human-mode output after a successful reply
  (currently prints nothing; read it before editing).
- `docs/agent-kernel.md`, `README.md`, `llms.txt` if it restates the poll.
- `tests/conftest.py` `build_cli_env()` (line ~448 sets `PYTHONIOENCODING`)
  and `tests/fixtures/cli_ready.py`.
- `tests/test_cli.py`, `tests/test_client.py`, `tests/test_cli_probes.py`.

Read first:

- [TAUT-7.2], [TAUT-7.4], [TAUT-8.1] in `docs/specs/02-taut-core.md`.
- `taut/commands/watch.py` — the model to copy: `handle()` raises
  `WatcherRejected` on `BrokenPipeError` or policy failure, and the watcher
  wrapper advances the cursor only after the handler returns.
- `taut/commands/_rendering.py` `emit_messages()` (line ~288) — renders a
  list; it has no per-record success signal today.
- SimpleBroker's `_backends/sqlite/validation.py` `is_valid_database`
  (line ~101–107 in the installed 8.4.0 package): it converts "not
  readable/writable" and "not a broker database" into `False`.

Comprehension gate (answers go in the Execution Log before the first edit):

1. **Why does the library `read_unread()` not need render-then-advance?**
   Expected: it returns the page to the caller, who holds the records when
   the call returns; the crash window is only in adapters that serialize to
   a stream after the commit. The CLI is the only such adapter in core;
   `watch` already advances per delivered record.
2. **Why is `list -q` the correct poll and not `read -q`?** Expected:
   `list` asks the broker `has_pending(after_timestamp=cursor)` and never
   writes; `read -q` advances the cursor through the page it suppresses, so
   a loop condition on it consumes the unread view before the handler runs.
3. **Why must the repeated-join notice suppression not touch the cursor?**
   Expected: [TAUT-7.4] places the member's cursor at now only on first
   membership; a rejoin that reset it would skip or replay history.

## Invariants and Constraints

- [THEORY-2]: readers peek. Nothing in this plan consumes chat history. The
  cursor is the only state `read` changes, and it changes it monotonically.
- A1 is untouched: `inbox` keeps claim-on-read. Do not add render-before-claim
  to `inbox` in this plan; if the owner wants that, it is a separate A1
  reconsideration.
- A5 ordering (registry → insert → cursor last, best-effort) is unchanged for
  writers. This plan changes only the reader's commit point.
- The Python API contract of `read()`/`read_unread()` does not change:
  same page semantics, same `limit` validation, same atomic commit.
- `read --json` records keep their exact shape ([TAUT-8.2]).
- Exit classes: `read` still exits 2 on nothing unread; the new
  delivery-failure path exits 1 with a one-line diagnostic and no traceback
  (adversarial floor 1).
- `join` output shape is unchanged for first joins; the rejoin case prints
  the same header block with no notice line.
- No new dependency. No second render path: the CLI `read` must reuse
  `emit_messages` with a per-record commit hook, not a parallel renderer.
- Exit 2 for a too-short suffix moves to exit 1; every other `reply` exit
  class is unchanged. Slice 4 of the command-runtime plan (unrecognized
  caller → 2) is not affected.
- Storage discovery: an absent path keeps the exact current "not found"
  message and exit 1; only the existing-but-unusable branch changes.

Hidden couplings:

- `emit_messages` is shared by `read`, `log`, and `message show`. Adding a
  commit hook must be a keyword-only, default-off parameter so `log` stays
  cursor-neutral and `message show` keeps its exact-ts advance.
- `client.last_thread_display_names` is populated by `read_unread`; a
  cursor-neutral fetch must populate it the same way.
- The CLI harness's forced `PYTHONIOENCODING` masks the encoding failure
  mode; removing it globally would change every CLI test's environment.
  Add a companion test instead of changing the default (Pattern 7 says the
  default-path proof is a second test, never a replacement).

Failure policy: a delivery failure is fatal for the command (exit 1) but
must not roll back records already delivered; the cursor commit through the
last written record is the durable outcome.

## Rollout, Rollback, and One-Way Doors

- Every slice is a source revert. No storage format changes.
- The doc changes (kernel, README, spec) land in the promotion slice and are
  independently revertible.
- One-way door: none. Changing the suffix exit class is a public-contract
  change but reversible; it is called out in the CHANGELOG.
- Post-deploy signal: `taut read --json | head -c 0` followed by `taut read
  --json` shows the messages; under `PYTHONIOENCODING=cp1252` with a
  non-encodable message, the second read still shows it.

## Dependency-Ordered Tasks

1. **Independent review of this plan and the spec delta.** Reviewer: a
   different family from the author per
   `docs/implementation/03-agent-inventory.md`. Require PASS/BLOCKED and
   P1/P2 findings. Stop if the reviewer cannot implement the per-record
   commit without guessing the `emit_messages` seam.
2. **Owner decisions** (see Open Questions) recorded in the Execution Log.
3. **Spec-promotion slice.** Apply the delta above to
   `docs/specs/02-taut-core.md` with strategy A; run
   `uv run --extra dev pytest tests/test_docs_references.py
   tests/test_cli_claims.py -n 0`; record the promotion baseline identifier.
4. **Red tests for read delivery.** `tests/test_cli.py`: (a) a subprocess
   test that pipes `read --json` into a closed reader and asserts the next
   `read` still returns the messages; (b) a companion test that runs the CLI
   with `PYTHONIOENCODING=cp1252` (explicitly overriding
   `build_cli_env`) on a message containing U+1F642 and asserts exit 1, a
   one-line diagnostic, no traceback, and that the message remains unread.
   Both must fail at baseline for the stated reason. What stays real: the
   subprocess, the SQLite file, the pipe.
5. **Implement render-then-advance in `taut/commands/read.py`.** Add a
   keyword-only `on_delivered: Callable[[Message], None] | None = None` to
   `emit_messages` that is called after each record's write and flush.
   `ReadCommand.run()` fetches the unread page without committing (add a
   keyword-only `advance: bool = True` to `read_unread()`; when false it
   returns the page and does not call `advance_cursor`), renders with the
   hook, tracks the max ts per thread, and commits each thread through the
   last delivered ts using the existing `advance_cursor` state seam via a
   new public `TautClient.mark_seen(thread, through_ts)` — or, if the
   reviewer prefers not to widen the public API, an underscore client method
   used only by the adapter. Stop and re-plan if this requires a second
   renderer or touches `log`/`message show` behavior.
6. **Red test then fix for repeated `join`.** `tests/test_client.py` and
   `tests/test_cli.py`: join twice, assert one notice in `log`, unchanged
   cursor, exit 0, header printed. Implement in `_threads.py` by checking
   membership before composing the notice.
7. **Red tests then removal of the suffix form.** Red: `reply general
   4976 hi` exits 1 as malformed with the bookmark unchanged; the human
   inbox action line contains the full 19-digit id; a full-id reply still
   works. Remove the suffix scan and its two error paths in
   `_resolve_message_id`, the shortest-unique derivation in `_rendering.py`,
   and the help wording in `reply.py`; delete the suffix-collision and
   too-short tests (`test_cli_reply_too_short_suffix_names_usage_and_minimum`
   and the collision cases in `tests/test_cli.py`/`test_client.py`) and
   replace them with the malformed-argument test. Stop if any other verb
   turns out to accept a suffix; the review found none.
8. **Docs.** README Quick Start (`reply general 0161024` becomes the full
   id from the preceding `log -t` line), README command table, and
   `docs/agent-kernel.md` (the message-id bullet) state the one id form;
   append a supersession note to the active command-runtime plan's
   Execution Log (append-only) that Slice 5's suffix-window batching is
   moot once suffix derivation is removed.
9. **Storage discovery diagnostic.** In `_base.py` `_require_target()`,
   when the SQLite path exists and validation fails, raise
   `NotInitializedError` with SimpleBroker's reason and the path instead of
   `NO_DATABASE_MESSAGE`; make `init` on such a path report the same reason
   with exit 1. Red tests in `tests/test_cli_probes.py`: `chmod 444`
   (skip on Windows), a foreign SQLite file, and a directory. Stop if
   SimpleBroker exposes no public reason and the only way is to parse a
   message string; in that case record the limitation and propose an
   upstream change instead of parsing.
9b. **Mention grammar probe.** Red: none (behavior already matches);
    substitute proof per testing-patterns Rule 5 is the promoted [IAN-5.2]
    sentence plus a new probe in `tests/test_cli_probes.py` that sends
    `` `@bob` ``, a fenced block containing `@bob`, a quoted sample, and
    `path/@bob/x`, and asserts one pointer each in bob's inbox, with the
    email form producing none. Enumerates the runbook's grammar-mimicry
    floor for this parser.
10. **Reject `-q` on `read` and `inbox`; recipe swap.** Red: `taut read
    -q` and `taut inbox -q` exit 1 with a one-line diagnostic naming
    `list -q`, no cursor movement, no pointer claim (assert the bookmark
    and the notification queue are unchanged). Implement in the two
    adapters' `run()` before any client call (the dispatcher already
    parsed `-q`; the adapter refuses it). Update the root help sentence.
    Replace the `read -q` poll with `list -q` in `docs/agent-kernel.md`,
    `README.md` (two places), and any `llms.txt` restatement; run
    `bin/check-cli-claims` and `bin/check-doc-paths`. Stop if refusing the
    flag requires changing the shared global-option parser rather than the
    two adapters.
11. **Traceability reconciliation.** Add the [TAUT-7.2]/[TAUT-8.1] link
    claims, update `docs/implementation/04-taut-architecture.md` (read
    path section) with the commit-point rationale, add the CHANGELOG entry,
    and record the promotion baseline in this plan.
12. **Completed-work review** by the same independent family, then flip the
    status-index row.

## Testing Plan

- Layer: real CLI subprocesses through `run_cli`/`build_cli_env` for exit
  and delivery proofs; real `TautClient` over a real SQLite file for cursor
  proofs; no mocks on the cursor path.
- Files: `tests/test_cli.py`, `tests/test_client.py`,
  `tests/test_cli_probes.py`, `tests/test_command_registry.py` (in-process
  `StringIO` assertions for the reply echo).
- Do not mock `emit_messages`, `advance_cursor`, or the pipe. The only
  permitted control is the environment (`PYTHONIOENCODING`) and closing the
  reader end of a real pipe.
- Mutation check before closing: remove the per-record commit and confirm
  the pipe test fails; restore.
- Invariants protected: [TAUT-7.2] monotonic cursor; [TAUT-7.4] first-join
  cursor placement; [TAUT-8.1] exit classes.

## Verification and Gates

Per-task: the named test file with `-n 0`.

Final:

```bash
uv run --extra dev pytest -n auto --dist loadgroup
uv run --extra dev ruff check taut tests && uv run --extra dev ruff format --check taut tests
uv run --extra dev mypy taut tests
bin/check-cli-claims && bin/check-doc-paths && bin/check-plan-status-index
```

Success: all green; the two new delivery tests pass without the forced
encoding; `taut list -q` documented in all three places.

## Independent Review Loop

Reviewer: Claude (Opus) or Grok per the agent inventory, using the
read-only invocation recorded there. Inputs: this plan, the proposed spec
delta, `taut/commands/read.py`, `taut/commands/watch.py`,
`taut/client/_messaging.py`, `taut/client/_threads.py`,
`tests/conftest.py`. Prompt: the standard plan-review prompt from
`docs/agent-context/runbooks/writing-plans.md` §8 plus: "Could you
implement the per-record commit against `emit_messages` without adding a
second renderer?" Dispositions are recorded in the Review Log.

## Out of Scope

- `inbox` claim ordering (A1) and the `inbox | head` hazard; noted for the
  owner, not changed here (only the silent `-q` form is refused).
- Any markup-aware mention parsing; the spec now states parsing is
  markup-blind.
- `say --json` returning the written record (enhancement; separate plan).
- `message react` silent exit 2 on an empty audience (react plan intent;
  owner may reopen).
- Windows stdout encoding reconfiguration at the CLI entry (alternative
  fix); this plan chooses render-then-advance.
- Any change to the Python `read()` page semantics.

## Assumptions and Open Questions

1. **Resolved 2026-09-24 (owner):** `read -q` is an oxymoron; read is
   defined as providing stdout, so `-q` on `read` is a usage error.
   **Resolved 2026-09-24 (owner):** the same rule applies to `inbox -q`,
   whose silent form would claim and discard pointers.
2. **Resolved 2026-09-24 (owner): remove the short-form message id
   altogether.** A human clicks in the TUI; an agent or CLI user uses the
   whole id. The git-like alternative is recorded under the [IAN-7.4] delta
   as the design to implement if the affordance is ever wanted back.
3. **Resolved 2026-09-24 (owner): parse everything and state it in the
   spec.** No code change; [IAN-5.2] gains the markup-blind rule and the
   probe pins it.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

## Execution Log

(append-only; comprehension-gate answers first)

- 2026-09-24 — Owner decision: `taut read -q` becomes a usage error. "Read
  is defined as providing stdout. Don't want output? Don't call it."
  Extension to `inbox -q` confirmed by the owner the same day.
- 2026-09-24 — Owner decision: remove the short-form message id
  altogether. Rationale: a human clicks (TUI); an agent or CLI user uses
  the whole id. The current form lacks all three properties that make
  git's abbreviated SHA safe; the git-like version is recorded as the only
  acceptable alternative if reconsidered.
- 2026-09-24 — Owner decision: mention parsing stays markup-blind; state
  it in [IAN-5.2] and pin it with a probe.

## Fresh-Eyes Review

Re-read as a new engineer: every file named exists at the cited line
ranges as of the baseline; the `emit_messages` hook is the one seam that
could be guessed wrong, so task 5 names it and forbids a second renderer;
the harness encoding change is scoped to one companion test; the three
owner decisions are separated from the mechanical work so the plan can be
reviewed before they are answered.
