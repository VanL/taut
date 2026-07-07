# Taut evaluation findings remediation plan

Date: 2026-07-06

Status: ready for implementation — independent review clean (4 adversarial
rounds, Codex; see §14 Review log)

Plan type: implementation with spec revision (four small deltas, promotion
strategy B per slice — see the delta table).

## 1. Goal

An independent multi-agent evaluation of taut v0.4.5 (2026-07-06) produced a
ranked findings list: one workspace-bricking recovery gap, one exit-code
contract violation verified live, several identity/concurrency weaknesses,
small hygiene defects, CLI-surface test gaps, and post-refactor documentation
drift. This plan fixes every finding that the specs say is a defect, records
with argument the findings the specs already answer, and closes the test and
documentation gaps — in nine independently verifiable slices.

## 2. Findings Inventory and Dispositions

Every evaluation finding, its governing spec text, and what this plan does
with it. The reviewer should check each disposition against the cited spec
section, not against the finding's original wording.

| # | Finding | Governing spec | Disposition |
|---|---------|----------------|-------------|
| F1 | Interrupted `rename` leaves an incomplete marker that blocks nearly every command, including `rename` itself; repair primitives (`mark_channel_rename_state`, `apply_channel_rename_state`) exist but nothing calls them | [IAN-8.3] requires "a later command can finish or report the interrupted rename"; [IAN-9]/[TAUT-10]: "recoverable or loudly reportable" | **Fix (S2)** — spec-compliance gap; today only "report" is implemented, not "finish" |
| F2 | Usage errors (e.g. `taut read --bogus`) exit 2, colliding with the documented "empty / nothing new / not found" class; verified live | [TAUT-8.1] exit-code rule: 0 success, 1 error, 2 empty/not-found. A usage error is an error | **Fix (S1)** with a clarifying delta D1 |
| F3 | Agent identity claims hash mutable fields (`cwd`, `tty`, `pgid`, `session_id`); an anchor process that `chdir()`s makes every later command fail "unrecognized caller" and `join` mints a duplicate. `identity.match_anchor` (stable `(host_id, pid, start_time)` matcher, fully unit-tested) is never called from production | [IAN-3.3] enumerates resolution steps 1–5; no anchor step exists today | **Fix (S3)** with delta D3 adding an agent anchor-match resolution step |
| F4 | Two agents joining simultaneously with the same auto-name seed race `member_names_in_use()` → `insert_member`; the loser gets `IdentityError` instead of the next pool name | [IAN-9]: "Automatic member creation may choose a deterministic fallback" — allows retry; explicit `set name` collisions must still fail | **Fix (S3)** — implementation of an existing allowance, no delta |
| F5 | `say`/`reply` evaluate `caught_up` before generating the message timestamp; a message landing in that window is marked seen without display | [TAUT-7.4]: "The check-then-write race … is accepted as cosmetic: the window is milliseconds and the cost is one message not flagged unread" | **No change — answered by spec.** See §3a |
| F6 | Watch-mode notification queue uses consume-before-dispatch; a raising handler destroys the notification (chat threads get peek + 3-strike poison handling) | [IAN-7.4]: "A failed notification renderer may lose that notification … This tradeoff is intentional"; restated in [TAUT-10] | **No change — answered by spec.** See §3a |
| F7 | Suffix message-id resolution scans the whole queue keeping the newest 1,000 (O(N) work), and a suffix matching one in-window and one older message resolves silently to the recent one | [TAUT-8.1] `reply` row: suffix "resolves via a bounded public-API scan of the most recent 1,000 message ids"; in-window preference is therefore contractual | **Partial (S5)**: error message must name the window; O(N) cost is a SimpleBroker feature gap (newest-N peek), out of scope |
| F8 | A mention of a third party inside a DM sends that non-participant a notification carrying the `dm.d_*` queue name — metadata leak | [IAN-5.2] does not scope mention targets by source-queue membership today | **Fix (S4)** with delta D4 scoping DM mentions to participants |
| F9 | `MultiQueueWatcher.remove_queue` drops persistent `Queue` objects without `close()`; membership churn under a running watcher leaks connections until GC | None (implementation hygiene) | **Fix (S6)** |
| F10 | `update_member_persona` reads the member row outside the write transaction (lost-update window). (`update_member_name` was also flagged; on inspection its read/check/write already share one transaction — no defect) | [IAN-4.4] | **Fix persona only (S6)** |
| F11 | `_hoist_global_options` moves any bare `--json`/`-q`/`-t` token out of positional position, so a message consisting exactly of a global flag can never be sent; no `--` end-of-options support | [TAUT-8.1] global options paragraph (silent on `--`) | **Fix (S1)** with delta D2 |
| F12 | Dead/duplicated code: `apply_channel_rename_sidecar` state alias duplicating `apply_channel_rename_state`, unreachable `EmptyResultError` branch in `TautWatcher.__init__`, `_exit_code_for_exception` testing `TokenError` twice | None | **Fix (S2, S5, S6)** — `mark_channel_rename_state` and `identity.match_anchor` stop being dead by design (S2, S3). Vendored-shape members (`QueueRuntimeConfig.priority`, `QueueMode.RESERVE`) stay — see Out of Scope |
| F13 | Zero CLI-level tests for `leave`, `reply`, `who`, `watch`; `TAUT_AS`, `--persona`, `--new`, `--db`, `--version`, `-q`, stdin `-` untested; no adversarial probes (corrupt db, malformed `.taut.toml`, non-UTF-8 stdin) despite the probe-floor runbook | [TAUT-11], `runbooks/adversarial-acceptance-probes.md`, Definition of Done ("every enumerable contract element … has a firing test") | **Fix (S7)** |
| F14 | Docs drift: implementation docs 02/04 document deleted `taut/schema.py`/`tests/test_schema.py`; `taut/_constants.py` cites retired `[TAUT-5.2]`/`[TAUT-5.4]`; spec 01 backlinks four nonexistent `2026-04-07-*` plans and DOM-4 says "product code has not been added yet"; spec 02 Related Plans labels implemented plans "planned"; repo-map corpus table omits spec 03 and five recent plans | DOM-6/DOM-8 (spec 01) | **Fix (S8)** plus a new automated reference gate |

### 3a. Findings answered by spec (recorded, not fixed)

**F5 (send-time cursor TOCTOU).** The reviewer's framing was "permanently marks
concurrent messages as read," which is accurate — but [TAUT-7.4] names this
exact race and accepts it deliberately: eliminating it requires either an
upper-bounded pending probe between timestamp generation and cursor advance
(one extra broker query on every send) or moving the check after insert (same
query). The spec's judgment — milliseconds-wide window, cost is one message
not flagged unread, never a lost message (history is durable, `log` shows it)
— holds for a coordination chat tool. Recording the disposition here is the
fix; changing it would be a spec revision this plan does not propose.

**F6 (watch-mode notification loss on handler failure).** [IAN-7.4] is
explicit: notifications are wakeups, not durable history, and the
claim-then-render loss window is called out as intentional in two spec
sections. The asymmetry with chat threads (peek + 3-strike poison advance) is
by design: chat cursors must never skip unseen messages, while a lost
notification degrades to "the member reads the thread normally." A
claim-then-ack notification redesign would add per-notification state for no
durable-behavior gain. No change; this paragraph is the recorded rationale.

## 4. Source Documents

- `docs/specs/02-taut-core.md` — [TAUT-7.4], [TAUT-8.1], [TAUT-8.2],
  [TAUT-10], [TAUT-11]
- `docs/specs/03-identity-addressing-notifications.md` — [IAN-3.3], [IAN-4.4],
  [IAN-5.2], [IAN-7.3], [IAN-7.4], [IAN-8.3], [IAN-9], [IAN-10]
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md` (S7 floors)
- `docs/agent-context/runbooks/testing-patterns.md` (anti-mocking, rule 5)
- Evaluation record: session review of 2026-07-06 (this plan's §2 is the
  durable record of its findings)

## 5. Spec Baseline

- `d0fd368` — docs/specs/02-taut-core.md and
  docs/specs/03-identity-addressing-notifications.md at plan authoring time
  ("Update version", v0.4.6).
- Provenance: the evaluation behind §2 ran against `20191c0` (v0.4.5).
  Between the two, `e15e690` landed the SimpleBroker watcher lifecycle-hooks
  migration (taut/watcher.py lost its `_run_with_retries` clone and
  `_strategy._activity_waiter` reach; `simplebroker>=5.1.0`; `add_queue`/
  `remove_queue` now reset the multi-queue waiter on churn) and touched only
  the [TAUT-8.3]/[TAUT-8.4] region of spec 02. Every spec section this plan
  cites is identical across the two commits, and every §2 finding this plan
  acts on was re-verified present at `d0fd368` (schema.py doc drift,
  `[TAUT-5.x]` cites, `remove_queue` close gap, unreachable
  `EmptyResultError`, exit-code collision, unwired `match_anchor`).

Status mechanism note: this repo uses prose spec text only — there is no
machine spec-classification tooling (no backstitch or equivalent), so
promotion is a plain spec-file edit plus the grep/test gates named below. The
new reference gate in S8 is a pytest, not a traceability scanner.

## 6. Proposed Spec Delta

Promotion strategy per delta (all strategy **B — atomic**: each delta is a
few lines and lands in the same slice as its code and tests; no
intermediate state where spec text exists without its implementation):

| Delta | Spec file | Section | Lands in |
|-------|-----------|---------|----------|
| D1 | docs/specs/02-taut-core.md | [TAUT-8.1] exit-code rule paragraph | S1 |
| D2 | docs/specs/02-taut-core.md | [TAUT-8.1] global options paragraph | S1 |
| D3 | docs/specs/03-identity-addressing-notifications.md | [IAN-3.3] resolution order | S3 |
| D4 | docs/specs/03-identity-addressing-notifications.md | [IAN-5.2] rules list (+ one [IAN-10] proof line) | S4 |

### D1 — [TAUT-8.1], append to the exit-code rule paragraph

> Usage errors — unknown flags, unknown subcommands, missing or malformed
> arguments rejected by the parser — are errors and exit 1, never 2. Exit 2
> is reserved for the empty/not-found class so that polling idioms like
> `taut read -q && handle_new` cannot mistake a typo for "nothing new".
> `--help` and `--version` exit 0.

### D2 — [TAUT-8.1], append to the global options paragraph

> A literal `--` ends option parsing: every later token is positional, so
> message text that looks like an option is sendable
> (`taut say general -- -q` posts the text `-q`). Global options may appear
> before or after the subcommand, but never after `--`.

### D3 — [IAN-3.3], insert between resolution steps 3 and 4 (renumbering the
list; current steps 4 and 5 become 5 and 6)

> 4. Agent anchor match: when no claim hash matches and the capture is an
>    agent capture, resolution may match a stored member anchor by the stable
>    triple (`host_id`, `anchor_pid`, `anchor_start_time`) against the
>    captured ancestor chain. This recovers continuity when a live anchor
>    process changed mutable claim inputs (working directory, tty, process
>    group) without restarting. On a match, the resolver records the current
>    claim hash for that member so subsequent commands resolve at step 3.
>    Anchor match never applies under `join --new`, never overrides steps
>    1–3, and never matches across hosts.

### D4 — [IAN-5.2], append to the rules list

> - Mentions written into a direct-message queue notify only the two DM
>   participants. Mentioning any other member in a DM produces no
>   notification for them: a DM must not leak its existence, queue name, or
>   activity to non-participants.

And amend the [IAN-10] proof line "mentions write exactly one notification
per mentioned member per message" to end: "…per message, scoped to the DM
participants when the source queue is a direct-message queue".

## 7. Context and Key Files

Read before any slice: `docs/specs/02-taut-core.md` §7–§8 and §10,
`docs/specs/03-identity-addressing-notifications.md` §3, §5, §7, §8;
`tests/conftest.py` (the `run_cli` harness — CLI tests spawn the real
entry point via `python -m taut`; the backend-marker collection gate lives
here too).

Current-structure notes per area (verified against v0.4.5 source):

- **CLI** — `taut/cli.py`. `main()` (line 32) parses via
  `build_parser().parse_args(_hoist_global_options(...))` — argparse errors
  raise `SystemExit(2)` *before* `main`'s try block, which is exactly bug F2.
  `_hoist_global_options` (line 529) moves recognized global tokens to the
  front with no `--` awareness. `_exit_code_for_exception` (line 506) maps
  exception types to exit codes and tests `TokenError` twice. Subcommands are
  registered with `sub = parser.add_subparsers(dest="command")` (line 53);
  argparse constructs subparsers with the same class as the parent only when
  `parser_class` is passed to `add_subparsers`.
- **Rename** — `taut/client/_threads.py::rename_channel` (line 120): validates,
  refuses when *any* incomplete marker exists
  (`_ensure_no_incomplete_channel_rename`, `taut/client/_base.py:132`),
  computes `affected` (channel first, then sub-threads, each
  `{"old": ..., "new": ...}`), writes a `started` marker via
  `start_channel_rename`, renames broker queues one at a time inside
  `open_broker(...)`, then applies sidecar updates and marks the row complete
  via `apply_channel_rename_state` in a separate transaction. The marker row
  (`taut_channel_renames`, DDL at `taut/state/_sql.py:118`) stores old name,
  new name, the affected list (JSON), state, and timestamps —
  everything resume needs, exactly as [IAN-8.3] prescribes.
  `mark_channel_rename_state` (`_sql.py:955`) is currently unused by
  production code. `apply_channel_rename_sidecar` (adapter method,
  `_sql.py:361`) duplicates `apply_channel_rename_state` (`_sql.py:376`).
- **Identity** — `taut/client/_identity.py::_resolve_member` (line 108)
  implements [IAN-3.3] steps in order: explicit `--as` → token → claim hash
  (line 164) → human uid fallback (line 174) → guest/create.
  `_create_member` (line 223) chooses a name via `identity.choose_name`
  against a `member_names_in_use()` snapshot (line 233) and rescues
  `IntegrityError` only via claim-hash re-resolution (line 259).
  `identity.match_anchor` (`taut/identity.py:321`) walks the captured chain
  against stored `(host_id, anchor_pid, anchor_start_time)`; unit tests in
  `tests/test_identity.py:391`. `TautClient` accepts an injected
  `identity_capture` (see `_capture`, `taut/client/_base.py:122`), which is
  the client-level seam for synthetic-capture tests; real-chain patterns
  (bash wrappers with `; exit $?`) live in `tests/test_identity.py:1017`.
- **Mentions** — `taut/client/_messaging.py::_write_mention_notifications`
  (line 379) resolves each `@route` and notifies every resolved member except
  the sender, regardless of the source queue class. DM participant ids are
  *not* recoverable from the `dm.d_*` queue name (it is a hash); they are in
  the thread registry row: `taut_threads.meta["members"]` (see
  `_thread_from_row`, `taut/client/_threads.py:182`). `taut/addressing.py`
  owns queue-name classification — check it for an existing "is this a DM
  queue" predicate before writing one.
- **Suffix ids** — `taut/client/_messaging.py::_resolve_message_id`
  (line 399): full 19-digit ids resolve via
  `peek_one(exact_timestamp=...)`; suffixes scan `peek_generator` into a
  `deque(maxlen=1000)` and error messages don't mention the window.
- **State** — `taut/state/_sql.py::update_member_persona` (line 508) calls
  `get_member` (own sidecar session) *before* opening the write transaction;
  the read-modify-write of the `meta` JSON therefore has a lost-update
  window. Compare `update_member_name` (line 527), which does its
  availability check and write inside one `sidecar(transaction=True)` block
  — that is the pattern to copy. Session reads inside a transaction use the
  module's `_one(session, sql, params)` helper.
- **Watcher** — `taut/watcher.py`, post-`e15e690` shape: the watcher now
  uses SimpleBroker 5.1.0's lifecycle hooks (`_create_activity_waiter`,
  `detach_activity_waiter`); there is no local retry-loop clone.
  `remove_queue` (line 204) pops the `QueueRuntimeConfig` and resets the
  multi-queue waiter but never closes `config.queue`. Critical coupling for
  S6: `BaseWatcher`'s `_queue_obj` / data-version queue is the **first**
  configured queue, and generic `MultiQueueWatcher` use can `remove_queue`
  that exact queue — closing it would kill data-version polling.
  (`TautWatcher` is partially shielded because its notification queue is
  configured first and never removed, which is why a TautWatcher-only churn
  test cannot prove the guard.) `TautWatcher.__init__` raises
  `EmptyResultError` when `not memberships and self._thread_filter is not
  None` — but `_current_memberships(strict=True)` already raises
  `MembershipError` for any filtered thread the member is not in, and a
  non-empty filter of joined threads yields non-empty memberships, so the
  branch is unreachable. The file header records vendoring from weft at a
  pinned commit — see Invariants.

Comprehension questions (answer before editing; wrong answers here are the
main implementation risk):

1. In `rename_channel`, which two persistence domains cannot share a
   transaction, and which marker state records the window between them?
   (Broker queue renames vs sidecar tables; the `started` marker.)
2. Why must a resume pass skip the "target queue already exists" precondition
   for queues whose `old` no longer exists? (Because a completed per-queue
   rename leaves exactly that state; re-checking would make resume refuse its
   own progress.)
3. Why does `claim_for_capture` produce a different hash after the anchor
   process calls `chdir()`, and which resolution steps must still win over
   the new anchor-match step? (`cwd` is a claim-hash input per [IAN-3.2];
   explicit `--as`, token, and exact claim-hash match all outrank it.)
4. In the watcher, which queue does `_get_queue_for_data_version()` return,
   and what must `remove_queue` therefore check before closing? (Establish
   this from the source before editing — if the data-version queue can be a
   member of `_queues`, closing it kills polling.)
5. Which member ids participate in a DM queue, and where are they stored,
   given the queue name is a hash? (`taut_threads.meta["members"]`.)

## 8. Invariants and Constraints

- **Exit-code classes are the contract**: after S1, exit 2 means only
  empty/nothing-new/not-found, exit 1 means every error including usage;
  `--help`/`--version` exit 0. No other command's exit mapping moves.
- **[TAUT-7.1] peek invariant**: nothing in this plan may consume, claim, or
  move chat-history messages. Rename recovery operates on queue names and
  sidecar rows only, via `open_broker(...).rename_queue(...)` and
  `queue.sidecar()` — never SQL against broker-owned tables.
- **[TAUT-10] ordering**: sidecar registry/membership writes stay
  authoritative-first; message writes second; cursor advance last and
  best-effort. No slice reorders these.
- **Identity never silently renames**: the anchor-match step must resolve to
  the existing member without touching its display name; [IAN-4.4] stays the
  only rename path. Explicit `set name` collisions still fail loudly (F4's
  retry applies only to automatic first-contact naming).
- **Resolution precedence is fixed**: `--as`/`TAUT_AS` > token > claim hash >
  anchor match > human uid fallback > guest/create. Anchor match is skipped
  entirely under `force_new`.
- **Vendored watcher shape**: `taut/watcher.py` is vendored/adapted from weft
  (header records the source commit) and, as of `e15e690`, already rides the
  SimpleBroker 5.1.0 lifecycle hooks. S6's changes there (close-on-remove,
  unreachable-branch removal in the taut-specific `TautWatcher` class) must
  be minimal and documented in the vendor header as local deviations, so the
  next weft re-vendor can reconcile them. Do not restructure the vendored
  `MultiQueueWatcher` beyond the named edits; do not remove
  `QueueRuntimeConfig.priority` or `QueueMode.RESERVE`.
- **No new dependencies, no schema bump**: every fix uses existing tables and
  existing deps. If a slice appears to need a `taut_meta` schema-version
  change or a new package, stop and re-plan.
- **JSON output shapes are frozen** per [TAUT-8.2]; no slice adds, renames,
  or removes fields.
- **Notification best-effort posture stays**: [IAN-7.3]/[IAN-7.4] semantics
  are untouched (F5/F6 dispositions).
- **Anti-mocking floor**: the broker, sidecar, and CLI entry point are never
  mocked. Synthetic `IdentityCapture` injection is allowed only through the
  public `TautClient(identity_capture=...)` seam, and S3 must include at
  least one real-process-chain proof.

## 9. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-8.1] `init` | S7 probe expected `init` in a read-only directory to fail with a clean invocation error | Pre-fix: stalled ~60s in SimpleBroker's setup phase-lock retry, then failed with a lock-timeout message that buried the underlying `PermissionError`. Fixed in S7a: `TautClient.init` pre-flights target-directory writability and raises a one-line `TautError` (exit 1) before any broker setup | An unwritable target must fail fast with a diagnostic naming the path; a ~60s stall breaks CLI/agent timeouts (probe floor: unwritable output) | n/a — error-path hardening |
| [TAUT-3.2] config | S7 probe expected a malformed `.taut.toml` to produce a diagnostic naming the offending file | Pre-fix: SimpleBroker's target resolution surfaced the raw `TOMLDecodeError` ("Invalid value (at line 1, column 12)") without naming the file. Fixed in S7a: both resolution call sites wrap `TOMLDecodeError` into `TautError("invalid .taut.toml: ...")`, exit class unchanged (1) | Probe floor: every failure diagnostic names the offending input where known | n/a — error-path hardening |
| [TAUT-8.1] `say -` | S7 probe expected non-UTF-8 bytes on piped stdin to fail with a diagnostic naming the input | Pre-fix: raw `UnicodeDecodeError` text ("'utf-8' codec can't decode byte 0xff...") reached stderr without saying stdin was the failing input (exit class already 1, no traceback). Fixed in S7a: `_read_stdin_text` wraps the decode error as "stdin is not valid UTF-8: ..." | Probe floor: diagnostics name the offending input; nothing is posted on the failure (verified by probe) | n/a — error-path hardening |

## 10. Tasks

Slices are dependency-light and individually revertible; the stated order
front-loads contract fixes. Within each slice: red test first, verify it
fails for the stated reason, implement, re-run.

### S1 — CLI exit-code contract and `--` (fixes F2, F11; promotes D1, D2)

- Files: `taut/cli.py`, `tests/test_cli.py`, `docs/specs/02-taut-core.md`
- Read first: [TAUT-8.1]; `cli.py:32-53` and `cli.py:529-587` (current parse
  and hoist flow, described in §7)
- Steps:
  1. Red tests (drive the real entry point via `run_cli`):
     `taut read --bogus` → exit 1, usage text on stderr, nothing on stdout;
     `taut nosuchverb` → exit 1; `taut --help` → exit 0;
     `taut say general -- -q` (after init/join setup) → posts literal `-q`
     (assert via `taut log general --json`); `taut say general -- --json`
     likewise. Expected failure reasons: exit 2 from argparse; hoist eats
     the flag token.
  2. Add a parser subclass overriding `argparse.ArgumentParser.error` to
     print the usage + message to stderr and `self.exit(1, ...)`. Use it for
     the root parser **and** pass `parser_class=` to **every**
     `add_subparsers` call — that includes the nested one under the `set`
     subcommand (`set` has its own `add_subparsers` for `set name`;
     `parser_class` does not propagate to nested calls automatically).
     Add a red test for the nested level too (`taut set bogus` → exit 1).
     `--version` keeps argparse's exit-0 action.
  3. Teach `_hoist_global_options` about `--`: split argv at the first
     bare `--`; hoist only the head; return
     `[*hoisted_head, "--"?, *tail-untouched]` preserving the separator so
     argparse still sees it. `_first_command` must also stop scanning at
     `--`.
  4. Promote D1 + D2 into [TAUT-8.1] in the same change.
- Reuse: existing `run_cli` harness; do not add a second CLI test helper.
- Stop gate: if making subparsers exit 1 requires touching every
  `add_parser` call individually, stop — `parser_class` should cover it;
  per-call surgery signals a wrong approach.
- Done signal: new tests pass; full `tests/test_cli.py` passes; spec text
  landed.
- Compatibility note (for CHANGELOG): scripts that keyed on exit 2 for
  usage errors (unlikely; undocumented) will now see 1. This is the
  documented-contract direction.

### S2 — Rename resume ([IAN-8.3] compliance; fixes F1, part of F12)

- Files: `taut/client/_threads.py`, `taut/client/_base.py`,
  `taut/state/_sql.py`, `taut/state/__init__.py`, `tests/test_client.py`,
  `tests/test_cli.py`, `tests/test_shared_contract.py`
- Read first: [IAN-8.1]–[IAN-8.3]; `rename_channel` and the marker functions
  (§7); the existing crash-window white-box test near
  `tests/test_client.py:504` for the honest-white-box pattern.
- Behavior to implement:
  1. `rename_channel(old, new)` first checks `incomplete_channel_renames()`.
     - No marker → today's path, unchanged.
     - Marker matching `(old, new)` exactly → **resume**: reread the
       marker's `affected` list (not a recomputed one — registry rows may
       already be renamed). Per-item state matrix, exhaustive — resume never
       guesses:
       | `old` exists | `new` exists | Action |
       |---|---|---|
       | yes | no | `rename_queue(old, new)` — the normal pending item |
       | no | yes | skip — this item already completed. Named residual risk: for a source queue that was empty at interruption, a *foreign* queue created at the target name after the original precheck is indistinguishable from completed progress, and resume will adopt it. This is the same race class the fresh path carries between its precheck and its renames; accepted, not solved here |
       | no | no | skip and converge the registry row, **silently** — deliberately mirroring the fresh-rename path, which already skips non-existent queues without comment (`queue_exists(old)` guard): a broker queue exists only while non-empty, so both-absent is the *normal* state for every empty channel or drained sub-thread, and a warning here would fire on routine renames. The residual ambiguity (out-of-band queue deletion looks identical) is exactly the registry/queue-divergence case [TAUT-10] already assigns to a future `doctor` verb — resume must not become a divergence reporter |
       | yes | yes | **abort loudly**, naming the colliding queue — a foreign queue occupies the target; resume must not merge or overwrite ([IAN-8.3] "loudly reportable") |
       After the queue pass: `apply_channel_rename_state(...)` (idempotent
       upserts converge per [TAUT-10]) and completion. Return the renamed
       `Thread`. Note the fresh-rename path's all-targets precheck
       (`_threads.py:146-149`) is exactly the yes/yes row applied before any
       mutation — resume applies it per-item because its own progress
       legitimately produces the no/yes rows.
     - Marker not matching the arguments → error naming the marker pair and
       the exact resume command:
       `incomplete channel rename exists: A -> B; run 'taut rename A B' to
       finish it`.
  2. Update `_ensure_no_incomplete_channel_rename`'s message (every other
     command) to the same actionable text naming `taut rename A B`.
  3. Collapse the duplicated adapter alias: keep
     `apply_channel_rename_state`, delete `apply_channel_rename_sidecar`
     from the adapter and protocol (grep tests for usages first; update
     them). Decide `mark_channel_rename_state`'s fate by use: if resume
     records phase transitions through it, it is now production code; if
     resume completes via `apply_channel_rename_state` alone, delete it and
     its protocol entry rather than leaving it dead.
- Tests (red first):
  - Client-level: construct the interrupted state via **white-box
    crash-window simulation** — direct calls to the state-layer
    `start_channel_rename(...)` with the real affected list, then renaming a
    strict subset of queues via `open_broker(...).rename_queue(...)`. This
    is not public-API-only and must not pretend to be: label the setup
    block as crash-window simulation in a comment, exactly as the existing
    white-box test near `tests/test_client.py:504` does. The *assertions*
    stay public-API (client/CLI behavior). Assert: (a) `say`/`join`/`list` refuse with the
    actionable message; (b) `rename_channel(old, new)` completes: marker
    complete, registry rows renamed, memberships moved, full history
    readable under the new name, message bodies untouched; (c) rerunning
    `rename_channel(old, new)` after completion raises the normal
    channel-not-found error (idempotence of recovery, no marker left).
  - Mismatch: interrupted `a -> b`, then `rename_channel("a", "c")` errors
    naming `a -> b`.
  - CLI-level: `taut rename old new` over an interrupted state exits 0; a
    blocked `taut say` exits 1 with the actionable message.
  - Mark the client-level tests `shared` if they hold on Postgres
    (they should — the marker is a sidecar row); run
    `uv run ./bin/pytest-pg --fast` to confirm.
- Stop gates: needing SQL against broker tables → stop ([TAUT-7.1]).
  Needing a marker-schema change → stop (schema bump is out of scope).
- Done signal: an interrupted rename is finishable by rerunning the same
  rename; all other commands name that command; no dead rename helpers
  remain.

### S3 — Identity continuity: anchor fallback and first-contact naming
(fixes F3, F4; promotes D3)

- Files: `taut/client/_identity.py`, `tests/test_identity.py`,
  `tests/test_client.py`,
  `docs/specs/03-identity-addressing-notifications.md`
- Read first: [IAN-3.2]/[IAN-3.3]; `_resolve_member` and `_create_member`
  (§7); `identity.match_anchor` (`taut/identity.py:321`) and its unit tests;
  the real-chain test patterns at `tests/test_identity.py:1017` (including
  the module docstring explaining the `; exit $?` shell-skip trick).
- Steps:
  1. Anchor fallback: in `_resolve_member`, after the claim-hash step
     (line 164) and before the human-uid fallback, when
     `not force_new and capture.kind == "agent"`:
     `row = identity.match_anchor(capture, self._state.list_members())`;
     on a hit, `_record_claim(row, claim, ts)` (heals future resolution to
     step 3), `update_member_activity`, apply the pending `persona` exactly
     as the claim-hash path does (`if persona is not None:
     row = update_member_persona(...) or row`, mirroring
     `_identity.py:167-171` — otherwise `join --persona` after an anchor
     `chdir()` silently drops the persona, breaking [TAUT-8.1]), and return
     with `rule="anchor match"` (the rule string surfaces in
     `whoami --explain`). Add a test: `join --persona` resolving via anchor
     match sets the persona. The healing
     `_record_claim` can itself race another process claiming the same hash:
     catch `IntegrityError`, re-resolve by claim hash, and if the hash now
     belongs to a **different** member, that claim-hash owner wins (step-3
     semantics outrank anchor match) — return it *with the full step-3
     side effects*: `update_member_activity` and the pending `persona`
     update, exactly as `_identity.py:164-172` does, so `join --persona`
     survives the race branch too. If it resolves to the same member or
     not at all, proceed with the anchor-matched member without the
     healing claim. Reuse `match_anchor` — do not write a
     second matcher; delete `identity.anchor_claimant` only if it remains
     unused after this slice (it is the single-process variant;
     `match_anchor` subsumes it).
  2. First-contact retry: in `_create_member`, only when the name was
     auto-chosen (`name is None` on entry), catch `IntegrityError` from
     `insert_member`, re-attempt the claim-hash rescue as today, and
     otherwise loop — bounded at 5 attempts, then raise `IdentityError`
     naming the last candidate. **Each retry recomputes all three uniques**:
     refresh `member_names_in_use()` and `choose_name` again, mint a fresh
     `random_member_id()`, and mint a fresh `mint_token()` — the collision
     may be on name, member_id, or token, and reusing a stale id/token
     across attempts must be impossible by construction (hoist the mint
     calls into the loop body, not above it). Explicit names (from `--as`)
     keep today's fail-loud behavior.
  3. Promote D3 into [IAN-3.3] in the same change (renumber steps 4→5,
     5→6; check for other references to those step numbers in both specs
     and in code comments).
- Tests (red first):
  - Client-level synthetic captures (via `TautClient(identity_capture=...)`):
    same anchor pid/start_time, different `cwd` → same `member_id`, rule
    `anchor match`, and — critically — a *subsequent* client with the new
    capture resolves via `identity claim` (the healing write worked).
    Negative cases: different host_id → new member; `force_new=True` →
    new member; an **existing** explicit `--as other` still wins (use a
    pre-created member named `other`, or a creating command — bare `--as`
    with an unknown name on a read-only command resolves to
    failure/guest, not a win, per `_identity.py:128-136`).
  - One real-chain proof — and note a shell **cannot** be the anchor:
    `select_anchor()` explicitly skips `SHELL_BASENAMES` and wrappers
    (`taut/identity.py:192`; existing tests assert the anchor is never a
    shell, `tests/test_identity.py:1018`), so a `bash -c` that `cd`s proves
    nothing about anchor `cwd` mutation. Instead spawn a tiny long-lived
    **Python** harness process (non-wrapper basename, so it is selected as
    the anchor): it invokes taut, calls `os.chdir()`, then invokes taut
    **twice** more. Assertions per invocation, via `whoami --explain`
    JSON: invocation 1 establishes the member; invocation 2 (post-chdir)
    resolves to the same `member_id` with rule `anchor match`; invocation 3
    (same cwd) resolves to the same `member_id` with rule `identity claim`
    — the third call is what proves the healing claim was written; the
    second cannot witness its own heal.
  - Concurrency: N=5 simultaneous first-contact joins from N separate
    spawned processes with the same executable basename (distinct pids →
    distinct claims, same name seed), synchronized to overlap (e.g. all
    blocked on a fifo/file barrier before invoking); assert 5 distinct
    member_ids, 5 distinct names, zero failures. Keep the barrier simple;
    if the test cannot be made reliably overlapping, fall back to asserting
    the retry path directly: two clients, second's `insert_member` raced by
    pre-inserting the chosen name between snapshot and insert via the state
    API — and say so in a comment.
- Stop gates: if anchor matching wants fuzzy criteria (executable path,
  fingerprint scoring) — stop; the delta authorizes only the exact triple.
  If the retry loop wants to mutate explicit names — stop.
- Done signal: `chdir` mid-session no longer orphans an agent; concurrent
  same-seed joins all succeed; D3 landed; `whoami --explain` shows the new
  rule.

### S4 — DM mention scoping (fixes F8; promotes D4)

- Files: `taut/client/_messaging.py`, `taut/addressing.py` (only if no DM
  predicate exists), `tests/test_client.py`,
  `docs/specs/03-identity-addressing-notifications.md`
- Read first: [IAN-5.2], [IAN-6.4], [IAN-7.2]; `_write_mention_notifications`
  (§7); how `_thread_from_row` reads `meta["members"]`.
- Steps: in `_write_mention_notifications`, when the source thread is a DM
  queue — detect via `addressing.classify_registered_queue(name) == "dm"`
  (`taut/addressing.py:89-100`; there is **no** dedicated `is_dm_queue_name`
  predicate today — either call `classify_registered_queue` directly or add
  the thin predicate beside it, nothing else) — load the thread row once and
  drop mention targets whose `member_id` is not in `meta["members"]`.
  Missing/malformed `members` meta on a DM row → notify no one and record
  the condition through the client's existing notification-warning channel,
  `last_notification_warnings` (`taut/client/_notifications.py:26-32`).
  One prerequisite refactor, because the CLI currently hardcodes the prefix
  `warning: notification delivery failed:` for every entry
  (`taut/cli.py:290-291`), which would mislabel an intentional suppression:
  move the failure context into the entry strings at their construction
  sites in `_notifications.py` (existing entries become
  `notification delivery failed: …`; the new one reads
  `mention notifications suppressed: direct-message registry row for
  THREAD lacks participant metadata`) and change the CLI emitter to print
  `warning: {entry}` verbatim. Update the existing warning-rendering tests
  in the same change; stderr-only as today, never in stdout JSON. The
  client layer itself never writes to stderr — do not add a `print` there
  ([IAN-7.3] best-effort posture; a mention notification must never fail
  the message write). Promote D4 (both the
  [IAN-5.2] rule and the [IAN-10] proof-line amendment) in the same change.
- Tests (red first): A DMs B mentioning C → C's inbox stays empty, B still
  gets `dm_started` on first message plus a mention notification when
  mentioned; A mentions B in the A↔B DM → B receives exactly **one mention
  notification** for it (a first-message DM legitimately carries *two*
  notifications total — the mention is written during `_insert_message`,
  `dm_started` after it, `_messaging.py:274` — so assert per-type counts,
  not a total); channel mentions unchanged (existing tests keep passing).
- Done signal: no notification row ever carries a `dm.d_*` thread to a
  non-participant.

### S5 — CLI/UX hygiene (fixes F7 partial, F12 partial)

- Files: `taut/client/_messaging.py`, `taut/cli.py`, `tests/test_client.py`,
  `tests/test_cli.py`
- Steps:
  1. `_resolve_message_id` suffix-miss message becomes:
     `message not found in the most recent 1,000 messages of THREAD; use the
     full 19-digit id` (test pins it). In-window-preference behavior is
     already contractual — add a test documenting it: suffix matching an
     old (evicted) and a recent message resolves to the recent one.
  2. Simplify `_exit_code_for_exception`: remove the duplicate `TokenError`
     check and collapse the redundant final tuple-then-fallthrough
     (both return 1). Behavior table unchanged — assert by keeping every
     existing exit-code test green; the `args` parameter stays only if
     still used after the edit.
- Done signal: message text tested; function reads as one ordered mapping.

### S6 — State and watcher hygiene (fixes F9, F10, F12 remainder)

- Files: `taut/state/_sql.py`, `taut/watcher.py`, `tests/test_watcher.py`,
  `tests/test_state_contract.py`
- Steps:
  1. `update_member_persona`: perform the read-modify-write of `meta`
     inside one `sidecar(transaction=True)` session (read via the module's
     `_one` helper), copying `update_member_name`'s shape. **Red-green is
     explicitly waived for this fix** (testing-patterns rule 5 exception):
     the defect is a lost-update *race*, and no test can turn it red
     deterministically without mocking the state layer, which the
     anti-mocking rule forbids. The named substitute proof is (a) the
     transactional shape asserted by inspection in review — the `get_member`
     read must be gone, replaced by a `_one` read inside the write
     transaction — plus (b) a *regression* (not red) state-layer test that
     seeds an extra unknown key into the member's `meta` JSON via a direct
     sidecar write (white-box, labeled) and asserts it survives a persona
     update. That test passes before and after the fix; its job is to pin
     merge-preservation against future rewrites, and the plan must not
     claim it proves F10.
  2. `remove_queue`: close the popped `config.queue` unless it is the
     data-version queue (comprehension question 4 — verify from source
     which object `_get_queue_for_data_version` returns before writing the
     guard). Swallow only the close-time exception classes the file already
     treats as benign (`BrokerError`, `OSError`, `RuntimeError`) with the
     existing debug-log idiom. Document both edits as local deviations in
     the vendor header block.
  3. Delete the unreachable `EmptyResultError` branch in
     `TautWatcher.__init__` (line 566) after adding/confirming a test that a
     thread filter naming an un-joined thread raises `MembershipError`
     (which is what actually fires today).
- Tests: join/leave churn under a live watcher — 10 cycles, then assert the
  process's open handles on the db path (via `psutil.Process().open_files()`)
  did not grow monotonically with cycle count; skip on platforms where
  `open_files` is unreliable, and keep the functional assertion (messages
  still delivered after churn) unconditional. That TautWatcher churn test is
  **not sufficient** for the close guard: TautWatcher's notification queue is
  configured first and never removed, so it never exercises removal of the
  data-version queue. Add a direct `MultiQueueWatcher`-level test: configure
  two queues, `remove_queue` the **first** one (the `_queue_obj` /
  data-version queue), then prove the watcher still dispatches a message
  written to the surviving queue. Dispatch alone is not the whole proof —
  a live multi-queue activity waiter could mask a closed data-version
  queue — so additionally assert, white-box and labeled, that the shared
  first queue is still functional after removal:
  `watcher._get_queue_for_data_version().get_data_version()` (or an
  equivalent call on `_queue_obj`) succeeds without raising. That directly
  pins "the guard did not close the data-version queue".
- Stop gate: if closing on remove breaks mid-watch rejoin (queue reused by
  `add_queue`), stop and check whether `add_queue` constructs fresh `Queue`
  objects — the fix must not introduce use-after-close.
- Done signal: churn test bounded; no unreachable branches; persona update
  transactional.

### S7 — CLI-surface and adversarial test-gap closure (fixes F13; no
production changes expected)

- Files: `tests/test_cli.py` (new sections), possibly a new
  `tests/test_cli_probes.py` for the adversarial floors
- Read first: `runbooks/adversarial-acceptance-probes.md` (the floors),
  [TAUT-8.1] table (expected exit codes per verb)
- Coverage to add (each via `run_cli`, real db in tmp dir):
  1. `leave`: member leaves → exit 0 + notice in log; non-member → exit 2.
  2. `reply`: full-id and ≥4-digit suffix; ambiguous suffix → exit 1
     listing candidates; unknown suffix → exit 2.
  3. `who`: bare and per-thread; unknown thread → exit 2.
  4. `watch`: spawn `taut watch --json` as a subprocess, write via a second
     CLI process, read one JSON line (bounded wait), send SIGINT, assert
     exit 0 ([TAUT-8.1] "0 on clean stop"). Guard with the same
     platform-skip conventions the identity real-chain tests use.
  5. Global surface: `TAUT_AS` env resolves like `--as`; `--db PATH` from
     another cwd; `-q` suppresses stderr messaging on error paths but not
     exit codes; `--persona` set at join visible in `whoami --json`;
     `join --new` mints a second member; `--version` exits 0 and prints the
     version; `say THREAD -` with piped stdin posts stdin (and the
     no-dash pipe-detection branch too).
  6. Probes (assert: correct exit class, one-line stderr diagnostic, **no
     traceback**): truncated/garbage `.taut.db`; `.taut.toml` with invalid
     TOML; `.taut.toml` with unknown keys (document current behavior —
     config honesty floor); non-UTF-8 bytes piped to `say -`; `init` in a
     read-only directory. Harness note for the byte probe: `run_cli` is
     text-mode (`subprocess.run(..., text=True, encoding="utf-8")`,
     `tests/conftest.py:164`) and **cannot** carry invalid bytes — extend it
     with a mutually-exclusive `stdin_bytes: bytes | None` parameter that
     switches that call to binary stdin (keeping one harness), rather than
     scattering one-off `subprocess.run` calls. Shape constraint: the bytes
     branch runs `subprocess.run` with `text=False`, passes `input=bytes`,
     and decodes captured stdout/stderr back to `str` itself (`utf-8`,
     `errors="replace"`), so the harness's `(int, str, str)` return contract
     is identical in both branches and no existing caller churns.
- Rule: these tests pin current intended behavior. If a probe exposes a
  real defect (traceback, wrong exit class beyond F2, hang), do not silently
  fix wide code paths inside S7 — record it in §9 (Deviation Log, with
  `pending` proposal) and fix it in **S7a**, unless the fix is a one-liner
  in the error path.

### S7a — Probe-remediation slice (reserved; may be empty)

- Purpose: probes in S7 are *expected* to expose some real error-path
  defects (that is what probe floors are for). S7a is the pre-declared home
  for those fixes so S7 stays a test-writing slice and the plan cannot end
  with `pending` deviation rows. Scope guard: S7a fixes error-path handling
  only (message quality, exit class, catching a crash) — a probe that
  reveals a *semantic* defect (wrong data written, contract violated beyond
  the error path) triggers stop-and-re-plan, not an S7a fix.
- Done signal: every deviation row opened by S7 is closed (fixed here or
  carrying a named follow-up plan reference instead of `pending`).

- Done signal (S7): every [TAUT-8.1] verb row and every global option/env
  var has at least one firing CLI-level test; probe floors satisfied.

### S8 — Documentation reconciliation and reference gate (fixes F14)

- Files: `docs/implementation/04-taut-architecture.md`,
  `docs/implementation/02-repository-map.md`,
  `docs/implementation/01-documentation-system.md`, `taut/_constants.py`,
  `docs/specs/01-development-documentation-operating-model.md`,
  `docs/specs/02-taut-core.md`, `docs/plans/README.md` (only if it indexes
  plans), new `tests/test_docs_references.py`
- Steps:
  1. Purge `taut/schema.py` / `tests/test_schema.py` references from
     implementation docs 02 and 04 (Key Files, trace tables, change
     guidance) — replace with the `taut/state` reality.
  2. `taut/_constants.py` docstring: retire `[TAUT-5.2]`/`[TAUT-5.4]` cites;
     point at the sections that actually govern its contents (verify:
     likely [IAN-3.2]/[IAN-4.2] for hash inputs and name validation, plus
     [TAUT-3.2] for config translation).
  3. Spec 01: remove the four phantom `2026-04-07-*` Related Plans entries;
     refresh the DOM-4 "product code has not been added yet" snapshot; same
     stale framing in implementation doc 01 line 80.
  4. Spec 02 Related Plans: correct "planned" labels on implemented plans;
     repo-map doc corpus table: add spec 03 and the 2026-06-30/07-01 plans.
  5. New `tests/test_docs_references.py` (the drift gate this repo's own
     DOM-8 failure history argues for). Recognized syntax is fixed up
     front — the scanner matches **only** these two shapes, nothing looser:
     - a markdown link target `](docs/…)` and a backtick-quoted path
       `` `docs/…` `` or `` `taut/…` `` / `` `tests/…` `` / `` `bin/…` ``
       (a path is `[A-Za-z0-9_./-]+` with at least one `/`; strip a
       trailing `:line` suffix before the existence check);
     - a bracketed spec code `[TAUT-\d+(\.\d+)?]` / `[IAN-\d+(\.\d+)?]`.
     Scanning rules:
     - sources scanned: `docs/implementation/*.md`, `docs/specs/*.md`,
       `CLAUDE.md`/`AGENTS.md` for paths; `taut/**/*.py`, `tests/**/*.py`,
       and `docs/implementation/*.md` for spec codes. `docs/plans/` files
       are never scanned as sources (immutable historical records), but a
       plan path referenced *from* a spec must exist;
     - fenced code blocks (``` … ```) are skipped entirely in markdown
       sources — examples and command transcripts are not reference claims;
     - one allowlist constant (path or code → reason) for deliberate
       exceptions; start it empty and add entries only with a reason string;
     - a false positive is fixed by tightening the recognized-syntax rules
       or the allowlist, never by weakening the assertion to a warning.
- Verification: the new gate must fail on the pre-fix tree (run it before
  step 1 to prove it catches F14's known instances) — that is this slice's
  red test.
- Done signal: gate green on the fixed tree, red on the pre-fix tree
  (demonstrated once in the slice record); docs match the code.

### S9 — Closeout

- Update `CHANGELOG.md` under a new Unreleased/next-version section: usage
  errors exit 1 (compat note), `--` separator, rename resume, anchor-match
  continuity, first-contact retry, DM mention scoping, watcher/state
  hygiene, docs gate.
- `docs/implementation/04-taut-architecture.md`: add rename-recovery and
  identity-resolution notes (the *why* — recovery marker lifecycle, anchor
  fallback rationale) in the sections S8 touched.
- Spec backlinks: add this plan under `## Related Plans` in specs 02 and 03.
- Reconcile §9 Deviation Log — no `pending` rows may remain.
- Full gates (below), then the completion checklist from `CLAUDE.md`
  (Definition of Done). On the commit gate, apply the CLAUDE.md carve-out
  precisely: completion is claimed either with committed state verified by
  `git log` (when the user lands the work or asks for it to be committed),
  **or** by explicitly reporting the uncommitted state and the changed-file
  list — the implementing agent must not commit on the user's behalf just
  to satisfy the gate.

## 11. Testing Plan

- Harness: pytest via `uv run pytest`; CLI tests through the existing
  `run_cli` real-entry-point harness in `tests/conftest.py`; backend-shared
  tests marked `shared` and proven on Postgres via
  `uv run ./bin/pytest-pg --fast`.
- Never mocked: the broker (`Queue`, `open_broker`, sidecar sessions), the
  sqlite/postgres backends, the CLI entry point, queue naming, cursor state.
- Allowed seams: synthetic `IdentityCapture` via the public
  `TautClient(identity_capture=...)` parameter (S3), with at least one
  real-process-chain test per new resolution behavior; the documented
  white-box crash-window setup for rename (S2), labeled as such in
  comments, mirroring `tests/test_client.py:504`.
- Contract focus: every slice's primary proof is externally visible —
  exit codes, JSON fields, notification presence/absence, history
  survival across rename, member identity stability across `chdir`.
- Invariants under test: exit-code classes (S1, S7); [TAUT-7.1] peek
  invariant (S2 asserts full history after recovery); resolution precedence
  (S3 negative cases); DM privacy (S4); no-fd-growth (S6).

## 12. Verification and Gates

Per-slice: the slice's named test files plus
`uv run pytest tests/test_cli.py tests/test_client.py -q` (fast core), and
for S2/S3/S4 also `uv run ./bin/pytest-pg --fast`.

Final gates (all must pass before completion is claimed):

```bash
uv run pytest
uv run ./bin/pytest-pg --fast
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv build && uv build extensions/taut_pg
```

Observable success after landing: `taut read --bogus; echo $?` prints 1;
an interrupted rename (simulated per S2's test) is finished by rerunning the
same `taut rename`; `tests/test_docs_references.py` guards drift in CI from
the next push onward.

## 13. Rollout and Rollback

- All slices are additive or behavior-tightening within one release train;
  no storage-format changes, no schema-version bump, no new dependencies —
  each slice reverts independently with `git revert`.
- One-way doors: none. Rename recovery only completes states the current
  code can already produce; the anchor-match step only adds claims (claims
  are append-only associations); D1's exit-code change is revertible text +
  parser class.
- Sequencing: S1 first (contract), S2/S3/S4 in any order, S5/S6 after their
  neighbors to avoid merge noise, S7 (+S7a) after S1–S6 (probes assert final
  behavior), S8/S9 last. The SimpleBroker watcher-hooks migration already
  landed in taut as `e15e690` — S6's watcher edits apply to that post-hooks
  file shape (verified in §7).

## 14. Independent Review Loop

- Reviewer: a different agent family than the author (Codex via the
  `/codex` wrapper), adversarial stance.
- Reviewer reads: this plan in full (especially §2 dispositions, §6 deltas,
  §10 tasks), plus the cited spec sections and the named source files.
- Review prompt (verbatim):

  > Read the plan at docs/plans/2026-07-06-evaluation-findings-remediation-plan.md
  > and its `## Proposed Spec Delta`, including the named promotion strategy.
  > Carefully examine the plan, the proposed spec text, and the associated
  > code. Look for errors, bad ideas, and latent ambiguities. Don't do any
  > implementation, but answer carefully: If asked, could you implement this
  > plan confidently and correctly as written?

- Feedback handling: the author addresses every point explicitly — plan
  edit, reasoned rebuttal recorded in the review log below, or explicit
  out-of-scope entry. Iterate until the reviewer answers the question
  affirmatively with no blocking findings.

### Review log

**Round 1 — Codex (gpt codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — baseline mismatch, watcher first-queue close gap, and
ambiguous rename-resume collision handling need plan edits first."
All 12 points addressed:

1. [P1] Stale baseline (`20191c0`/v0.4.5 vs HEAD `d0fd368`/v0.4.6) —
   **fixed**: §5 re-anchored to `d0fd368` with a provenance note; cited spec
   sections verified identical across the two commits; every acted-on
   finding re-verified at the new HEAD.
2. [P1] Watcher close-guard under-tested (first configured queue *is* the
   data-version queue; TautWatcher churn never removes it) — **fixed**: §7
   watcher note rewritten for the post-`e15e690` shape; S6 now requires a
   direct MultiQueueWatcher test removing the first queue.
3. [P1] Rename-resume target-collision ambiguity — **fixed**: S2 now carries
   an exhaustive per-item `old`/`new` existence matrix, including the loud
   abort on yes/yes.
4. [P2] "Public APIs only" contradiction in S2's test setup — **fixed**:
   relabeled as white-box crash-window simulation with public-API
   assertions.
5. [P2] S4 "stderr warning path" doesn't exist at the client layer —
   **fixed**: routed through `last_notification_warnings` with an explicit
   no-print-in-client rule.
6. [P2] No DM addressing predicate exists — **fixed**: S4 names
   `classify_registered_queue(name) == "dm"`.
7. [P2] Retry loop could reuse stale member_id/token — **fixed**: S3
   requires re-minting name, member_id, and token inside the loop body.
8. [P2] Anchor-match healing `_record_claim` race unhandled — **fixed**: S3
   specifies IntegrityError → re-resolve; claim-hash owner wins.
9. [P2] Persona lost-update proof tested the wrong field (name is not in
   `meta`) — **fixed**: S6 proof now seeds and preserves an unknown `meta`
   key.
10. [P2] S7 probe slice could end the plan with pending deviations —
    **fixed**: reserved S7a probe-remediation slice with a scope guard.
11. [P2] S8 reference scanner under-specified — **fixed**: recognized
    syntax pinned to two shapes, fenced blocks skipped, reasoned allowlist.
12. [P2] S9 commit gate conflicted with the do-not-commit-on-user's-behalf
    rule — **fixed**: closeout now states the CLAUDE.md carve-out
    (committed *or* explicitly-reported-uncommitted).

Also absorbed from the same re-verification: the watcher-hooks migration
landed mid-planning (`e15e690`), so §7, §8 (vendored-shape invariant), §13,
and §15 were updated from "in flight" to "landed".

**Round 2 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the S3, S6, and S7 proof instructions need correction
first." All 6 points addressed:

1. [P1] S3's real-chain proof used a shell as the anchor, but
   `select_anchor()` skips shells (`taut/identity.py:192`) — **fixed**: the
   proof now uses a long-lived non-wrapper Python harness process that
   `os.chdir()`s between two taut invocations.
2. [P1] S6's persona test would pass on the buggy code (not a red test) —
   **fixed**: red-green is now explicitly waived for F10 with the named
   substitute proof (transactional-shape inspection + a regression test
   honestly labeled as regression-only).
3. [P1] S7's non-UTF-8 probe cannot pass bytes through the text-mode
   `run_cli` — **fixed**: the harness gains a `stdin_bytes` mode; no
   one-off subprocess calls.
4. [P2] S6's dispatch-based close-guard proof could be masked by the
   activity waiter — **fixed**: added a direct, labeled white-box assertion
   that the data-version queue still answers `get_data_version()` after
   removal.
5. [P2] The `old=no,new=no` resume row overstated certainty — **fixed**:
   tied to the [TAUT-10] registry/queue-divergence posture with a mandatory
   stderr warning naming each both-absent pair.
6. [P2] `parser_class` does not reach the nested `set` subparser —
   **fixed**: S1 now names every `add_subparsers` call and adds a nested-
   level red test.

**Round 3 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the S3 persona gap and S2 warning-surface ambiguity need
fixing first." All 5 points addressed — four by plan edit, one by reasoned
rebuttal:

1. [P1] Anchor-match path dropped a pending `--persona` — **fixed**: S3 now
   mirrors the claim-hash path's persona update (`_identity.py:167-171`)
   with a dedicated test.
2. [P1] The round-2 "warn on both-absent resume queues" requirement had no
   client warning surface — **resolved by rebuttal, warning withdrawn**:
   both-absent is the *normal* state for empty channels (broker queues
   exist only while non-empty) and the fresh-rename path already skips
   exactly this case silently via its `queue_exists(old)` guard; a resume
   warning would therefore fire on routine renames of quiet channels. The
   out-of-band-deletion ambiguity it aimed at is the registry/queue-
   divergence case [TAUT-10] explicitly defers to a future `doctor` verb.
   S2's matrix row now specifies the silent skip and cites that posture.
3. [P2] The real-chain proof's second invocation cannot witness its own
   healing claim — **fixed**: the harness now makes three invocations and
   asserts the resolution rule per step (`anchor match`, then
   `identity claim`).
4. [P2] `last_notification_warnings` entries all render under a
   "notification delivery failed" prefix, mislabeling intentional DM
   suppression — **fixed**: S4 now moves failure context into entry
   construction and has the CLI print entries verbatim, with the existing
   warning tests updated in the same change.
5. [P2] `run_cli(stdin_bytes=...)` risked changing the harness return
   shape — **fixed**: the bytes branch is pinned to `text=False` +
   manual utf-8/replace decoding, keeping `(int, str, str)` identical.

**Round 4 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: **"Yes, with the P2 clarifications above. None of them changes
the architecture or slice order."** The round-3 rebuttal on both-absent
rename queues was independently confirmed against the code
(`_threads.py:156`). All 4 advisory clarifications applied:

1. [P2] "explicit `--as other` still wins" was ambiguous for read-only
   commands — **fixed**: the negative case now specifies an *existing*
   member (or a creating command).
2. [P2] DM mention-count wording could be misread as one total
   notification — **fixed**: the test now asserts per-type counts and
   notes a first DM legitimately carries `dm_started` + mention.
3. [P2] The anchor-healing race branch could drop `--persona` when the
   claim-hash owner wins — **fixed**: that branch now carries the full
   step-3 side effects.
4. [P2] The `old=no,new=yes` resume row's foreign-queue-adoption residual
   risk was unstated — **fixed**: named in the matrix row, with the note
   that the fresh path carries the same race class.

**Status: plan review-clean.** The independent-review loop's blocker
condition ("reviewer could not implement confidently and correctly") is
cleared as of round 4; the four advisory clarifications were incorporated
after the affirmative verdict, strictly tightening the reviewed text.

**Implementation review — Codex (codex-cli 0.135.0, adversarial, full
uncommitted diff, 2026-07-06).** Verdict: "mostly faithful for S1–S9 …
fix the P1 before landing." Findings and dispositions:

1. [P1] `_dm_participants` accepted any `list[str]`, so a corrupted DM
   registry row with 3+ members would reopen the F8 leak — **fixed**:
   exactly-two-distinct-ids cardinality check ([IAN-6.4]); parametrized
   tests added for zero/one/three/duplicate member lists (all suppress and
   warn).
2. [P2] The real-chain anchor harness ran without `build_cli_env()`, so it
   could import an installed taut instead of the working tree — **fixed**:
   env passed through.
3. [P2] The unknown-`.taut.toml`-key probe pinned silent ignore while
   citing a floor whose default is loud failure, with no spec cover —
   **fixed**: [TAUT-3.2] now states the forward-compatibility posture
   (unknown keys ignored, malformed files loud); the probe cites it.
4. [P2] The reference gate's markdown-link shape silently skipped
   `](path:LINE)` targets that the backtick shape checks — **fixed**: link
   regex now strips a `:LINE` suffix identically.
5. [P2] Landing note, no code change: three files are untracked, not one —
   the plan file, `tests/test_cli_probes.py`, and
   `tests/test_docs_references.py` — and specs/gates depend on all three;
   any landing commit must `git add` them explicitly.

Confirmation round (same reviewer): all five dispositions CONFIRMED against
the code; verdict "Yes — the implementation is now faithful to the plan and
safe to land, modulo the explicit untracked-files note for whoever commits."
Full gates re-run green after the fixes (283+4 tests, ruff, format, mypy,
docs gate).

## 15. Out of Scope

- **F5 and F6 code changes** — spec-accepted behavior; §3a records why.
- **Suffix-scan O(N) cost (F7)** — needs a public newest-N peek in
  SimpleBroker; proposed upstream separately (same channel as
  `latest_pending_timestamp` in 4.8.0). Behavior is contractual and
  unchanged.
- **SimpleBroker watcher-hooks migration and pin raise** — already landed in
  taut as `e15e690` (clone deleted, `detach_activity_waiter` in use,
  `simplebroker>=5.1.0`), owned by
  `../simplebroker/docs/plans/2026-07-06-watcher-embedder-lifecycle-hooks-plan.md`
  Phase C; nothing left for this plan to do there.
- **Vendored watcher shape cleanup** (`QueueRuntimeConfig.priority`,
  `QueueMode.RESERVE`) — vendor parity with weft outweighs dead-code
  removal until the post-hooks re-vendor.
- **Notification claim-then-ack redesign** — rejected in §3a.
- **`skills/` seeding, agent-inventory refresh (DOM-13)** — real gaps, but
  process work orthogonal to these findings; candidates for their own small
  plan.
- **New `doctor` verb** — [TAUT-10] mentions a future doctor for
  registry/queue divergence; rename recovery deliberately rides the
  existing `rename` verb instead, keeping the CLI surface frozen.
- **Speculative refactors** — the shallow `SqlSidecarTautState` adapter
  criticism from the evaluation is acknowledged but not acted on: it is a
  style cost, not a defect, and collapsing it would churn every state
  consumer for no behavior change.

## 16. Fresh-Eyes Check (author, pre-review)

Re-read cold against the writing-plans checklist: invariants precede tasks;
every task names files, read-first material, reuse targets, red tests,
stop gates, and done signals; anti-mocking is explicit per seam; rollback is
trivial by construction and stated; the two spec-status mechanisms question
is answered (prose-only repo); comprehension questions cover the four
riskiest edits (rename resume preconditions, anchor precedence,
data-version queue ownership, DM participant storage). Known soft spot
called out for the reviewer: S3's concurrency test has a fallback if true
overlap proves flaky — the fallback is named in the task rather than left
to the implementer.

## Implementation Record

Slices S1–S9 were implemented on 2026-07-06. The work is uncommitted in the
working tree pending the user's landing decision (the CLAUDE.md commit-gate
carve-out: uncommitted state reported explicitly rather than committed on
the user's behalf).

- S1 — usage errors exit 1 at every parser level (root, subcommands, the
  nested `set` subparser); `--` ends option parsing in both the hoist and
  the command scan; D1 and D2 promoted into [TAUT-8.1].
- S2 — interrupted channel renames resume by rerunning the same
  `taut rename OLD NEW`, driven by the marker's affected list and the
  per-item existence matrix; every other command names that exact resume
  command; the duplicate `apply_channel_rename_sidecar` adapter alias and
  unused `mark_channel_rename_state` were removed.
- S3 — anchor-match resolution ([IAN-3.3] step 4; D3 promoted) with the
  healing claim, race handling, and persona preservation; bounded
  first-contact retry re-minting name, member id, and token per attempt;
  real-chain `chdir()` proof and five-way concurrent-join test.
- S4 — DM mentions notify participants only (D4 promoted);
  `last_notification_warnings` entries carry their own context and the CLI
  prints them verbatim.
- S5 — the suffix-miss message names the 1,000-message window and the
  full-id remedy; `_exit_code_for_exception` collapsed to one ordered
  mapping.
- S6 — `update_member_persona` performs its read-modify-write in one
  transaction (red-green waived per plan; substitute proof applied);
  the vendored watcher closes removed queues except the data-version
  queue; the unreachable `EmptyResultError` branch was deleted.
- S7 — CLI-surface coverage for `leave`/`reply`/`who`/`watch` and the
  global option/env surface, plus adversarial probe floors in the new
  `tests/test_cli_probes.py` with a binary-stdin `run_cli` mode.
- S7a — three probe-exposed error-path defects fixed: unwritable `init`
  target fails fast, `.taut.toml` diagnostics name the file, non-UTF-8
  stdin is named as stdin. Recorded as the three §9 Deviation Log rows;
  no `pending` rows remain.
- S8 — implementation docs reconciled to the `taut/state` reality, stale
  spec-01 plan links and snapshots fixed, and the
  `tests/test_docs_references.py` reference gate added (demonstrated red on
  the pre-fix tree, green after).
- S9 — CHANGELOG entries, architecture-doc rationale (rename recovery,
  anchor match, first-contact retry), spec 02/03 Related Plans backlinks,
  and this record.

Test count: 221 collected pre-plan → 283 collected post-S8, verified via
`uv run pytest --collect-only`.
