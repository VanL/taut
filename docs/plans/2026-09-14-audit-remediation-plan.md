# Audit Remediation Plan

Class: 5+P. The complete unit includes concurrent state changes, auxiliary-failure
semantics, TUI lifecycle work, and material changes to verification guidance.
Plan type: implementation with small spec revisions, promoted atomically with
their owning slices (strategy B).
Owner: implementing engineer; product and durable-policy decisions remain with
the repository owner.

## Goal

Fix the eight reproduced product defects and five test/checker concerns from
the 2026-09-14 audit. Each issue, or tightly related group, lands as a separate
reviewable commit containing its code, regression proof, and documentation.
Prefer removing duplicate paths and using current owners to adding machinery.
This document plans implementation; authoring and reviewing it does not execute
its code slices or authorize publication.

## Source Documents and Baseline

Baseline: `6f5ae8896b30b1965286a9b0cd5cfd936214c015`. All baseline behavior,
findings, and spec references below refer to that revision. After each atomic
spec/code slice, record its commit as the promotion baseline for the named
sections. Rebase this plan against concurrent changes before implementation.

Consulted sources:

- `AGENTS.md`; `docs/agent-context/README.md`; `docs/program-theory.md`
  [THEORY-1]–[THEORY-7]; `docs/specs/product-section-registry.md`.
- Decision hierarchy, principles, engineering principles, testing patterns,
  writing-plans, hardening-plans, adversarial-acceptance-probes, and
  review-loops-and-agent-bootstrap under `docs/agent-context/`; Golden Rules
  and post-watermark entries in `docs/lessons.md`; `docs/coalescing.md`.
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-10.2], [DOM-10.2.1], [DOM-11], [DOM-15].
- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-7.4], [TAUT-8.6],
  [TAUT-10], [TAUT-12.5], [TAUT-13.3.1].
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8];
  `docs/specs/06-search.md` [SRCH-3.1], [SRCH-6.1], [SRCH-9.3];
  `docs/specs/08-persistence-io.md` [PIO-6.1], [PIO-7.1], [PIO-8.2];
  `docs/specs/10-taut-tui.md` [TUI-6.3], [TUI-13].
- `docs/implementation/01-documentation-system.md`,
  `04-taut-architecture.md`, `06-command-extensions.md`,
  `08-complexity-and-suppression-policy.md`, `09-search-architecture.md`,
  `10-persistence-io.md`, and `12-taut-tui.md` in `docs/implementation/`.
- `docs/implementation/03-agent-inventory.md` and
  `skills/call-agent/SKILL.md` for external review mechanics.
- Prior records: `docs/plans/2026-08-10-test-quality-remediation-plan.md`,
  `docs/plans/2026-08-14-review-findings-remediation-plan.md`, and
  `docs/plans/2026-08-24-concurrency-and-schema-contract-alignment-plan.md`.
  This plan owns only the newly reproduced findings below; it does not reopen
  all of those plans or silently supersede their other decisions.

## Investigation Disposition Matrix

| ID | Verified finding and evidence at baseline | Disposition / owner |
|----|--------------------------------------------|---------------------|
| B1 | Dump after a real member/session interleave replaces a prior backup; load dry-run rejects the resulting Summon foreign reference | Fix, S1 |
| B2 | `alpha -> beta -> alpha` makes search report a rename-map cycle; a third rename from alpha raises a unique-key error | Fix retained-marker/source-location design, S4 |
| B3 | A real reply between affected-set capture and marker insertion leaves `general.<id>` with parent `ops`, with rename complete | Fix the demonstrated registry-topology race, S5; broader publication interval discussed separately below |
| B4 | Injected cursor-storage failure makes `say` raise after its message commits; an existing DM test requires that failure | Fix success boundary and test oracle together, S2 |
| B5 | After changing cwd, one relative-path client writes in B using A's identity | Bind path at construction, S3 |
| B6 | TUI rename changes navigation but the next composer send uses the old target and fails | Reconcile local rename state, S7 |
| B7 | Textual TUI delete removes storage but leaves transcript/snapshot rows | Reuse native deletion completion, S6 |
| B8 | An exception containing `password="abc` followed by a backslash produces persisted invalid debug JSON | Fix encoded-character handling, S8 |
| Q1 | Two projection tests pass when the live projection returns no segments; both exercise unused `segment_text` | Remove dead implementation and replace proof, S9 |
| Q2 | Release test passes with `continue-on-error: true` on the pre-upload tag check | Assert fail-stop YAML semantics, S10 |
| Q3 | Exact import census rejects an equivalent public-facade import | Keep runtime dependency floors, remove exact graph, S11 |
| Q4 | Python snapshots duplicate the spec-owned Ruff counts and live/retired IDs | Remove duplicate baselines, retain one approval owner, S12 |
| Q5 | Tilde-fenced citations are treated as live; a fenced plan-index example can be accepted as the index | Share narrow fence exclusion, S13 |

The audit probes used real temporary SQLite databases and, for B6/B7, real
Textual `run_test` sessions. Causal interleaving hooks did not replace storage
operations. Focused existing suites passed. Q2 is a test gap, not an assertion
that the current release workflow permits publication after a failed guard.

### No-action register and scope boundary

- Keep lossy notification pointers, storage-access membership, native backend
  search differences, and post-insert cursor ordering. These are intended.
- Keep the independent stateful client model and real storage tests. No blanket
  removal of mocks, structural checks, or lifecycle machinery is justified.
- Keep the prior-artifact retry import shim until its documented compatibility
  consumer is retired. Lack of current-source callers is insufficient proof.
- Do not claim that theory understanding is machine-testable. DOM-15 fixture
  structure and citation retrieval are lint; observable product invariants and
  human review carry the semantic argument.
- Retain the spec's single approved Ruff inventory. S12 removes a second count
  baseline and retirement ledger, not suppression approval or growth detection.
- Coalescing backlog and the MCP cached display-name observation are separate
  concerns. No archive sweep or MCP cache redesign is included.

## Invariants, Hidden Couplings, and Rollout

1. The workspace remains one storage target. No daemon, lockfile, identity
   service, third-party dependency, or new global retry layer enters this plan.
2. SimpleBroker owns message IDs, queue operations, retries, and storage
   mechanics. Core SQL stays in `taut/state/_sql.py`; PG SQL stays with its
   existing owner. No broker-private SQL or queue operation inside a sidecar
   transaction.
3. Source insertion remains the success point for `say`/`reply`. Cursor failure
   may leave a message unread but must not invite a resend of a committed post.
   Notifications, search indexing, and cursors retain their current ordering.
4. Dump is a validated live logical projection, not a simultaneous cross-store
   snapshot. Invalid assembled state fails before replacing the previous file.
   Load remains quiescent and destructive by contract. No census, lock probe,
   input-copy lifecycle, or speculative concurrent-load defense is added.
5. Channel names are reusable display/address values, not eternal operation
   identities. Search hydrates real source messages; stale work cannot invent
   source truth or change actor visibility. Version-1 job and dump shapes stay
   unchanged unless a separately reviewed deviation proves unavoidable.
6. TUI owns navigation intent and drafts; `TuiSession` owns client/watcher
   lifecycle. Reuse `open_conversation` and its stop/join path. A completed
   mutation is not retried because refreshing its view fails.
7. Redaction remains one shared, lazy, value-only final-text transform under
   [TAUT-13.3.1]. Correct encoded-character recognition without adding a second
   redactor, general JSON-repair layer, or broader secret-detection policy.
8. Test removal must preserve the real invariant. Every unsafe mutation that
   motivated a replacement must fail its new test; a harmless implementation
   variation must pass. Do not freeze helper names, counts, or message wording
   as a substitute for observable behavior.

Rollout: each slice is a green code/test/doc commit. No release, tag, package
version bump, or deployment is part of implementation here. Most slices revert
normally; S4's marker reuse and S5's transaction protocol require coordinated
core rollout before relying on their guarantees. Do not mix old and new core
writers while qualifying those guarantees. Existing incomplete rename markers
remain resumable. No automatic repair of previously corrupted workspaces is
included: observe and report them, and design a repair from their actual state.

Rollback: do not represent reverting code as undoing a completed user rename or
restoring an overwritten backup. Stop affected activity and preserve the
workspace before investigating a regression. S4 must keep logical dump/job
formats readable and carry no schema migration. TUI reversion changes only view
behavior; persisted renames/deletes remain. S12/S13 policy and implementation
are reverted together. No introduced feature requires a cleanup daemon.

### Comprehension checks for the two risky boundaries

Before editing S1 or S4/S5, record answers in the execution log:

- Why does dump not need an MVCC snapshot to fix B1? Expected: validate the
  assembled core/extension references using the existing contributor contract;
  concurrent motion is allowed, an unloadable projection is not.
- Why is a SQL marker check insufficient to promise fully atomic rename and
  message publication? Expected: a sidecar transaction cannot enclose the
  broker queue write; an already-running writer can outlive the registry
  phase. S5's exact boundary must be stated and tested without overstating it.

An incorrect answer means reread the owning contract before editing. These two
checks are the existing runbook's required comprehension record, not a new gate
framework or a requirement to recite the whole documentation corpus.

## Commit Slices

Commit names below are suggested subjects. Complete red/green proof, focused
verification, relevant doc updates, and independent review before each commit.
Commit the exact file list; verify with `git log -1 --oneline` and
`git show --stat`. Do not land red-only tests or bundle unrelated slices. If
review requires changing a slice's design, amend this plan and record why.

### S1 — Validate extension records before publishing a dump

Suggested commit: `fix: validate dump contributors before publication`.
Files: `taut/persistence/_operations.py`,
`tests/test_persistence_io_adversarial.py`,
`extensions/taut_summon/tests/test_persistence.py`,
`docs/implementation/10-persistence-io.md`.

Reuse the existing load-preflight contributor validation loop through one small
plain helper shared by dump and load. Supply the parsed staged file, its active
registered components, and core member IDs from that same parsed file. Finish
all component/version/cross-reference validation before `os.replace`. Do not
rediscover contributors or reproject live state to validate a different object.
Close replay iterators through their existing `finally` ownership.

Red proof: create an initially loadable backup with active Summon schema; gate
between the real core projection and real extension projection; create a real
member and session; dump must now refuse and leave the old backup byte-identical
and loadable, with no staging residue. Add a valid active-component round-trip
case through the same validator. Keep real contributor validation and filesystem
publication; only the phase scheduling hook may be controlled.

Gate: `G1`. Existing [PIO-6.1]/[PIO-8.2] already require this. Stop if the fix
requires source freezing, new file snapshots, or a second persistence parser.

### S2 — Preserve committed-send success on cursor failure

Suggested commit: `fix: keep sender cursor catch-up best effort`.
Files: `taut/client/_messaging.py`, `tests/test_client.py`,
`tests/test_shared_contract.py`, `docs/implementation/04-taut-architecture.md`.

Contain ordinary `Exception` only around the existing post-insert bounded
probe and advance in `_advance_sender_if_no_intervening`. Keep pre-insert
failures fatal and let direct `BaseException` cancellation/termination retain
its normal meaning. Do not retry the send or the auxiliary operation, and do
not misuse notification/search warning lists as a new cursor diagnostic API.
The existing lazy debug-capture helper may receive the auxiliary exception at
this narrow boundary using the already resolved target/config; its own failure
must not affect the committed receipt.

Replace `test_dm_started_notification_precedes_sender_cursor_probe_failure`'s
wrong `raises` oracle. Inject failures into real `Queue.peek_many` and state
`advance_cursor` separately, rather than replacing the whole catch-up helper.
Assert returned receipt, exactly one durable source message, preserved DM
notification, and unchanged cursor. Also prove pre-insert failure still raises,
intervening unread messages still prevent advancement, and a normal send catches
up. Exercise `say`, `reply`, and join/creation notices through their real paths.

Gate: `G2`. [TAUT-10] already makes this best-effort; no new public warning or
result schema. Stop if catch scope reaches source insertion or authorizes a
retry that can duplicate a message.

### S3 — Bind relative workspace paths at client construction

Suggested commit: `fix: resolve client database paths once`.
Files: `taut/client/_base.py`, `tests/test_client.py`,
`docs/implementation/04-taut-architecture.md`.

After expansion, resolve explicit `db_path` and `TAUT_DB` to an absolute path in
`_resolve_target`, before validation and returning it. Preserve explicit-path
precedence and existing missing-file diagnostics. Reuse this resolved target
for all handles; do not add repeated cwd checks or a client reattachment mode.

Red proof: create distinct A/B workspaces with the same relative filename,
construct in A, change cwd to B, then read and send through that same client.
The read and new message must stay in A, with A's member identity; B remains
unchanged. Parameterize explicit argument/environment selection and persistent
versus ordinary handles. Restore cwd in cleanup. Keep SQLite and identity real.

Gate: `G3`. No storage/CLI schema change. Stop if the change broadens into all
path handling, rejects supported symlinks, or changes target precedence.

### S4 — Make reused channel names safe for rename history and search

Suggested commit: `fix: resolve stale search work by message identity`.
Files: `taut/client/_searching.py`, `taut/client/_base.py` only if the existing
exact-message locator needs its abstract typing seam, `taut/state/__init__.py`,
`taut/state/_sql.py`,
`tests/test_client.py`, `tests/test_state_contract.py`,
`tests/test_search_client.py`, `tests/test_persistence_io.py`,
`tests/test_shared_contract.py`, `docs/specs/03-identity-addressing-notifications.md`,
`docs/specs/06-search.md`, `docs/specs/08-persistence-io.md`,
`docs/implementation/04-taut-architecture.md`,
`docs/implementation/09-search-architecture.md`,
`docs/implementation/10-persistence-io.md`.

In `_drain_search_jobs`'s source loader, use `job.thread` as a hint only if it is
currently registered and searchable. Try its exact message ID, then exact-peek
other current registered searchable queues on a miss. Reuse
`_registered_searchable_rows`, canonical decoding and `_locate_exact_message`
where its existing signature suffices; never invoke actor-touching
`show_message` or restrict index maintenance to the current actor's DMs.
Hydration still owns public actor visibility. Remove `_current_search_thread`
and its permanent forwarding map/cycle detector. Remove the newly dead
`completed_channel_renames` state protocol method, wrapper, SQL accessor and
ledger-only tests after confirming no other consumer. Keep marker proof through
`get_channel_rename`, public resume/reuse behavior and persistence records.

Let `start_channel_rename` replace only an existing completed marker for the
same old name inside its existing transaction. Never overwrite an incomplete
marker. Keep the table key and `ChannelRenameRow`, job and dump record shapes;
the row is the latest retained operation for a name, not an event journal.
Keep `thread_rename` jobs as revision-fenced index hints and ordinary source
reconciliation. Only a missing/stale hint scans other current queues; do not
add an index of historical redirects, schema migration or retention worker.

Capability/cost tradeoff: no user-facing history command is removed; rename,
resume, dump/load and search retain their public roles. Completed markers keep
the latest operation per old name rather than incidental full history. A stale
source hint can require one exact probe per current searchable queue. Accept
that bounded extra work rather than creating another durable location index;
revisit only with an observed performance problem.

Red proof through real clients/providers: `alpha -> beta -> alpha -> gamma`,
search after each rename with initially undrained message jobs; reuse old alpha
as a different new channel and search both; delayed/out-of-order rename jobs;
deleted source does not resurrect; root/child IDs, membership and topic survive;
dump/load and a further rename on the restored workspace succeed. Preserve
incomplete-marker refusal/resume tests. Replace permanent-ledger test assumptions
in `tests/test_state_contract.py` with retained-marker replacement/resume proof.

Gate: `G4/G5` and shared PG coverage. Promote D4 atomically. Do not commit marker
reuse separately from source lookup: old search depends on the lost history.
Stop if a schema/protocol version change, permanent name identity, or a broad
source-discovery framework is proposed. Mixed old/new search workers are not a
supported qualification topology for the revised semantics.

### S5 — Close the demonstrated rename/thread-registration race

Suggested commit: `fix: capture rename topology in the registry transaction`.
Files: `taut/client/_threads.py`, `taut/client/_messaging.py`,
`taut/state/__init__.py`, `taut/state/_sql.py`, `tests/test_client.py`,
`tests/test_state_contract.py`, `tests/test_shared_contract.py`,
`extensions/taut_pg/tests/test_pg_sidecar.py`, `docs/specs/03-identity-addressing-notifications.md`,
`docs/implementation/04-taut-architecture.md`.

The owner selected the narrow scope on 2026-09-14: fix the demonstrated
thread-snapshot race and track the separate in-flight message-write race as R1.
S5 is not a promise of atomic rename versus all chat publication.

Keep public broker target-collision preflight before marker creation. Pass that
preflight's affected-name snapshot into `start_channel_rename` as
`expected_affected`. Inside its existing transaction, acquire the shared topology
key, revalidate source/destination and incomplete markers, and reread the affected
registry rows. If the authoritative pairs differ from the preflight snapshot,
raise a clear retryable invocation error before marker or broker mutation. Do
not automatically retry the command. Otherwise create the marker and return its
authoritative affected list for every subsequent broker move and registry update.

Reuse `_acquire_advisory_lock` and SQLite's existing immediate transaction.
Introduce one new lock-key constant, `taut:chat-topology`, for marker capture
and cooperating registry operations, acquired through the existing helper. The
current global incomplete-rename boundary is a read gate, not an existing lock.
Rename acquires topology before the retained `taut:channel:{name}` topic key;
`set_channel_topic` keeps taking only its current topic key. No reverse lock
order is introduced.
Pass the dialect through the existing state wrappers. Channel/subthread upsert
and membership insertion must check markers and their current parent/target
inside that transaction. Keep notification-thread upsert outside this mechanism.
Do not hold a sidecar transaction over broker calls or add marker cleanup.

Preserve the caller's initially read thread row for delayed registration. Pass
its `created_ts` as expected parent/target identity and compare the stored value
at insertion. This prevents a delayed reply or membership attaching to an
unrelated channel that reused the old name after rename. Reuse that existing
column without treating timestamp order as an identity test. Update the state
protocol signatures and real state fixtures with the prerequisite thread rows.

Red proof: use causal barriers with real SQLite/PG operations and broker calls.
A child committed before preflight is included. A child committed during
preflight causes clean refusal with no new marker, and a subsequent invocation
includes it. Marker-first delayed child/membership registration refuses without
an orphan row. A delayed reply cannot attach to a new old-name incarnation.
Assert names, parents, memberships, marker state and public reachability agree.
Retain broker-only target-collision-before-mutation, topic coordination and
interrupted-resume tests. These cases use S4's reused-name semantics; implement
S4 before S5. A fully published reply before capture moves with its parent.

Gate: `G4/G5` plus PG. Promote D5 atomically. Stop if the implementation adds
operation-wide writer locks, durable leases, timed reclaim, compensating message
moves, or claims its tests cover R1.

#### R1 — Deferred full write/rename coordination

A writer can register its thread, pause before `Queue.write`, and resume after
rename moved the broker/registry. The current public SimpleBroker API has no
portable lock or transaction spanning those phases. A pre-write marker check
or post-write retry does not close the crash/interleaving boundary. This is
pre-existing and remains after S5; do not represent S5 as fully concurrency-safe
rename or as repairing already-stranded queues. Owner: product/repository owner.
Reopens when broader coordination is requested, the retained race occurs in a
real workspace, or a public backend primitive makes a bounded solution possible.
Any such follow-up must choose its contract and prove the paused-writer case;
it may not silently require quiescent rename or introduce a service lifecycle.

### S6 — Reuse deletion completion for the textual TUI command

Suggested commit: `fix: refresh TUI history after textual deletion`.
Files: `extensions/taut_tui/taut_tui/app.py`,
`extensions/taut_tui/tests/test_tui_app.py`,
`extensions/taut_tui/tests/test_tui_action_handlers.py`,
`docs/implementation/12-taut-tui.md`.

Route confirmed textual `message delete` through `_run_deletion`, retaining its
explicit message ID and capturing the current display target and conversation
intent as `_confirm_message_delete` already does. Reuse
`_apply_deletion_result -> _refresh_after_deletion -> open_conversation`.
Do not introduce a second reload implementation or change domain deletion.

Red proof through the real command input and confirmation: the deleted message
vanishes from transcript and session snapshot, and an independent client cannot
find it. Preserve an open reply thread when its parent is deleted; existing
replies and later incoming replies remain visible. Strengthen the native handler
oracle to include transcript removal. Retain cancellation and newer-navigation
checks. Gate: `G6`. [TUI-6.3] owns the existing behavior. Stop if a general
mutation dispatcher or action registry is proposed for this route repair.

### S7 — Continue the open TUI conversation after rename

Suggested commit: `fix: preserve TUI conversation state across rename`.
Files: `extensions/taut_tui/taut_tui/app.py`,
`extensions/taut_tui/taut_tui/models.py` only for a small pure remapping helper,
`extensions/taut_tui/tests/test_tui_app.py`,
`extensions/taut_tui/tests/test_tui_action_handlers.py`,
`docs/specs/10-taut-tui.md`, `docs/implementation/12-taut-tui.md`.

Use one rename-specific success handler from native and textual confirmation
wrappers. Before submission capture old target and `_conversation_intent`.
After successful public rename, use returned `Thread.name` to remap exact old
root and `old + '.'` descendants in target-keyed drafts and affected UI state.
Preserve text, scalar editing cursor, revision, selected message ID and scroll
anchor; leave unrelated drafts unchanged. A nonempty destination draft must
not be overwritten: reject that local draft collision before submitting rename
and let the user keep/edit the drafts. No alias chain or draft ledger.

If the captured navigation intent is still current and the active conversation
is affected, advance conversation intent and reopen the mapped conversation and
reply target through `TuiSession.open_conversation`. That owner stops/joins the
old watcher and opens the new one. A newer unrelated navigation wins; only
navigation projections and retained affected drafts are refreshed in that case.
A view-reopen error reports a view failure without retrying or relabeling the
already-successful database rename.

Red proof through both real native/textual routes: rename with a multiline
draft, retain editing position, send afterward, and observe the new-name history
and incoming watcher delivery. Include an open reply surface, inactive-channel
rename, cancellation/core collision, and delayed real completion after newer
navigation. The draft-collision case verifies no rename occurs and both texts
remain. Gate: `G6`. Promote D1 atomically. Stop if watcher internals, a generic
mutation framework, or persistent alias tracking enter the fix.

### S8 — Preserve JSON structure during credential redaction

Suggested commit: `fix: preserve complete JSON escapes during redaction`.
Files: `taut/_redact.py`, `tests/test_redact.py`,
`tests/test_debug_capture.py`, `docs/implementation/04-taut-architecture.md`.

Correct the escaped-label and escaped-assignment rules so delimiters distinguish
embedded escaped quotes from an outer JSON closing quote following a literal
backslash. Consume complete encoded characters; a secret span cannot end between
paired backslashes or inside an escape. Share the narrow escape atom where the
two affected rules need the same semantics. An unterminated quoted value is not
permission to consume surrounding JSON structure.

Red proof: the exact audited incomplete assignment with one and multiple
trailing backslashes, valid closed escaped assignments, neighboring unaffected
fields, and non-ASCII text. Add a bounded property test over synthetic strings
with quotes/backslashes/newlines: `json.loads(redact_sensitive_text(json.dumps
(event)))` succeeds and preserves the event's structural keys/types. Use an
independent structural oracle, not the same regex. Keep firing secret-removal
cases so a no-op redactor cannot pass. Run real local capture and the existing
action fixture, parsing both payloads. No real credentials or external sink.

Gate: `G8`. Existing [TAUT-13.3.1] governs. Do not add a generic repair/fallback
pass or change the redaction boundary as a speculative redesign. If correct
escape recognition cannot preserve the existing contract, stop and bring a
specific alternative with an exact spec delta back to review.

### S9 — Delete the dead segmenter and test production projection

Suggested commit: `test: replace obsolete search segmentation proof`.
Files: `taut/search/_projection.py`, `taut/search/__init__.py`,
`taut/client/_searching.py`, `tests/test_search.py`,
`docs/implementation/09-search-architecture.md`.

Delete test-only `segment_text`, `_next_segment_end`, and their internal
re-export. Delete `_registered_source_documents` only after rechecking its lack
of callers. Replace the two misleading tests with direct `projection_segments`
proof: literal expected Unicode normalization/order, many distinct canonical
chunks crossing physical segment boundaries, and one oversized Unicode chunk
retained intact. The large-input case must use independently generated distinct
lowercase tokens, not repeat four deduplicated tokens or derive its oracle via
`query_chunks`. Kill the empty-projection mutation. Keep real public search
integration coverage and backend-native lexical behavior.

Gate: `G9`; liveness search must find no removed symbol references in production
or tests. [SRCH-3.1]/[SRCH-6.1] already own this. No new public API or promise of
raw-body reconstruction or strict bounds on indivisible lexemes.

### S10 — Prove release safeguards stop publication

Suggested commit: `test: verify release tag checks are fail stop`.
Files: `tests/test_github_workflows.py`; production workflows only if the new
semantic assertion exposes a current defect, which requires a reported scope
change before editing them. Documentation: brief rationale in the existing
release section of `docs/implementation/04-taut-architecture.md`.

Reuse `_workflow_data` and `_named_steps`. Inspect parsed YAML for every current
release target: tag recheck precedes upload, binds the expected commit, has the
publisher's existing publication condition, and has no truthy/expression-valued
`continue-on-error`. Keep existing artifact/provenance/permission assertions.
Add local loaded-document mutations for a nonfatal check and a disabled check;
both must fail. Locate steps through their relevant command/action where
possible instead of making a human step title contractual.

Gate: `G10`. No network calls, actual publication, workflow simulator, or new
policy framework. [TAUT-12.5] already owns the fail-closed contract.

### S11 — Replace exact import maps with runtime dependency floors

Suggested commit: `test: check lazy command boundaries without import snapshots`.
Files: `tests/test_architecture_boundaries.py`, `tests/test_lazy_imports.py`,
`docs/implementation/06-command-extensions.md`.

Remove `_RuntimeImportVisitor` and its exact import matrix. Retain separate
broker-private-surface and terminal-sink checks. Extend `_probe_modules`'s
fresh-process help probes over built-in commands from
`CommandRegistry(entry_points=())`, asserting forbidden heavy runtime loading
rather than exact allowed helper imports. Retain selected-command behavioral
and installed-artifact proofs. The public-facade import mutation must pass;
an eager client/broker import into help must fail.

Gate: `G11`. [TAUT-8.6] owns lazy loading. Stop if removal loses a named forbidden
boundary, adds timing thresholds, or merely replaces the matrix with another
exact import census.

### S12 — Remove duplicate Ruff count and retirement snapshots

Suggested commit: `test: keep Ruff approval inventory in one owner`.
Files: `tests/test_ruff_policy.py`,
`docs/specs/01-development-documentation-operating-model.md`,
`docs/implementation/08-complexity-and-suppression-policy.md`.

Remove `RAW_RULE_COUNTS`, `RETIRED_GROUP_NUMBERS`, and their exact Python
snapshot assertions. Keep real `run(..., write=False)` reconciliation against
the one spec-owned registry and aggregate. Retain generator mutation proofs for
an unapproved added directive, wrong rule, stale generated index and global
inventory mismatch. Do not change approved counts into ceilings, weaken
ungrouped-noqa detection, or introduce a replacement ledger.

Gate: `G12`. Promote D2 atomically. This deliberately fixes duplicated approval
state rather than undertaking a broader lint-policy redesign. Stop if a new
baseline file, parser, approval bypass, or blanket suppression enters the slice.

### S13 — Share fenced-example exclusion between documentation checkers

Suggested commit: `fix: share fence parsing across documentation checks`.
Files: new `bin/markdown_fences.py`; `bin/check-dom15-fixtures`,
`bin/check-plan-status-index`, `tests/test_docs_references.py`,
`tests/test_plan_status_index.py`,
`docs/specs/01-development-documentation-operating-model.md`,
`docs/implementation/01-documentation-system.md`,
`docs/implementation/02-repository-map.md`.

Extract the existing DOM-15 fence transition logic into a small iterator of
original `(line_number, line)` prose lines. Use it in DOM-15, `_prose_lines`,
and plan-status extraction. Use the existing repository-root import bootstrap
for directly executed tools. Preserve each consumer's own claims/table grammar.
Do not migrate the CLI-claim parser, which intentionally examines fenced
commands, or Ruff's byte-offset rewrite parser, whose contract differs.

Reuse DOM-15's backtick/tilde/mismatched/unclosed cases. Add firing checker-level
regressions: a tilde-fenced invalid citation is inert; a status index consisting
only of a fenced example fails; adjacent real prose still fires with its original
line number. Exercise each actual CLI and its existing exit classes. Apply the
relevant parser floors from adversarial-acceptance-probes without creating a
new general parser test framework. Gate: `G13`; promote D3 atomically.

## Proposed Spec Delta

Only D1–D5 are proposed changes. Use strategy
B: promote the exact owned text, implementation, tests and reciprocal links in
that slice's commit. No global spec-promotion commit forces unrelated fixes to
wait. Baseline contracts continue to govern all other slices.

### D1 — [TUI-6.3], add after the existing deletion/reply-context paragraph

> After a successful channel rename initiated in the TUI, an affected open
> conversation and reply surface continue under their new public targets.
> Affected drafts retain their text and editing position. A newer navigation
> intent is not replaced by rename completion. The replacement watcher uses
> the normal stop-and-join conversation-open path. If remapping would overwrite
> a nonempty destination draft, the TUI rejects that local rename before
> submission and preserves both drafts. A post-rename view failure does not
> change or retry the successful domain operation.

### D2 — [DOM-10.2] and [DOM-10.2.1]

Replace the paragraph beginning “A separate movement-stable global
raw-diagnostic inventory” in [DOM-10.2]:

> The global raw-diagnostic inventory in [DOM-10.2.1] records every diagnostic
> exposed by `--ignore-noqa` under the active repository rule set, including
> reasoned local suppressions outside the grouped registry. That spec-owned
> inventory is the sole approved aggregate by rule code. Tests verify it through
> `bin/ruff_suppression_index.py`; they do not maintain another count baseline
> or a census of live and retired group IDs. This inventory does not claim that
> disabled rule families are audited. Per-file ignores, unreviewed global
> ignores beyond `E501` and `B008`, blanket file directives, threshold inflation,
> and baseline allowlists are not permitted as alternatives to review.

Replace the sentence beginning “Group IDs are unique” in [DOM-10.2.1]:

> Group IDs are unique, match `RUFF-SUP-[0-9]{3}`, and are never reused after
> retirement. The checker validates the current registry and its source
> references. Reviewers check retirement history in Git when assigning a group
> ID; tests do not maintain a second retirement ledger.

Retain the following existing sentence verbatim after that replacement:
“A temporary group also names the active plan task that removes or re-evaluates
it.”

### D3 — [DOM-10], insert before [DOM-10.1]

> Documentation path/citation checks, plan-status extraction, and DOM-15 fixture
> extraction share `bin/markdown_fences.py` for excluding fenced examples. The
> iterator preserves original line numbers and recognizes backtick or tilde
> fences indented by at most three spaces. A closing fence uses the opening
> character, is at least as long, and has no trailing content except whitespace.
> An unclosed fence extends to the end of the input. This helper owns fence
> exclusion only; each checker retains its existing claim or table grammar.

### D4 — Reusable rename markers and exact search-source identity

Replace the [SRCH-9.3] paragraph beginning “Before source lookup” through
“Both relative orderings and a two-rename chain require real tests”:

> For message jobs, the thread name is a source-location hint, not an identity.
> The worker first exact-peeks that name if it is currently a registered
> searchable queue. On a miss it exact-peeks the other current registered
> searchable queues for the immutable message ID. A found message is projected
> under its current registered thread; absent source is marked deleted through
> the normal revision fence. Completed rename markers are recovery bookkeeping,
> not a permanent redirect graph; name reuse and cycles in retained rename
> history are valid. The `thread_rename` job remains a revision-fenced index
> hint. Source hydration and reconciliation retain authority over current
> location and visibility. Tests cover delayed jobs, both rename/job orderings,
> repeated renames, and a different channel reusing an old name.

Append to [IAN-8.3]:

> A completed marker keyed by an old channel name may be replaced by a later
> rename from that name. An incomplete marker remains the authority for its
> existing recovery operation and must not be overwritten. Marker retention is
> not a complete channel history or a source-location identity mechanism.

Insert after the [PIO-4.4] core-record table:

> A `channel_rename` record contains the latest retained operation for its
> `old_name`, not a complete historical event log. This does not change the
> version-1 record fields, ordering, or incomplete-rename refusal.

### D5 — [IAN-8.1]/[IAN-8.3] registry-topology boundary

Insert after the [IAN-8.1] topic/serialization paragraph:

> Rename validates and records one affected topology atomically against
> cooperating registry and membership changes. If topology changes between
> broker preflight and marker creation, the operation fails before marker or
> broker mutation and may be retried. Incomplete markers block cooperating
> topology mutation. Registration verifies the originally selected parent or
> target still exists as that same thread, including when names are reused.
> Registry application changes names, parents and memberships consistently.
> This protection does not serialize a message publication already in flight
> across broker rename. A writer paused after authoritative sidecar work may
> still publish under an old queue name. That existing publication race is
> tracked separately.

Append to [IAN-8.3]:

> The marker's captured affected list owns subsequent broker moves and registry
> application. Broker target-collision checks precede marker creation; a changed
> topology invalidates that preflight rather than partially starting a rename.

## Testing Plan and Commands

Use prepared retained environments without dependency resolution. The commands
below are from repository root. Record exact selected test names during red
proof; newly proposed tests need not already exist. A test name alone is not
evidence: record red failure, green result, and the durable/user-visible oracle.

| Gate | Exact command |
|------|---------------|
| G1 | `.venv/bin/python -m pytest -q -n 0 tests/test_persistence_io.py tests/test_persistence_io_adversarial.py extensions/taut_summon/tests/test_persistence.py` |
| G2 | `.venv/bin/python -m pytest -q -n 0 tests/test_client.py tests/test_shared_contract.py -k 'cursor or sender or reply or dm_started or join'` |
| G3 | `.venv/bin/python -m pytest -q -n 0 tests/test_client.py tests/test_project_config.py` |
| G4/G5 | `.venv/bin/python -m pytest -q -n 0 tests/test_client.py tests/test_state_contract.py tests/test_search_client.py tests/test_persistence_io.py -k 'rename or search'` |
| G6 | `extensions/taut_tui/.venv/bin/python -m pytest -q -o addopts= extensions/taut_tui/tests/test_tui_app.py extensions/taut_tui/tests/test_tui_action_handlers.py extensions/taut_tui/tests/test_tui_chat.py -n 2 --dist loadfile` |
| G8 | `.venv/bin/python -m pytest -q -n 0 tests/test_redact.py tests/test_debug_capture.py` |
| G9 | `.venv/bin/python -m pytest -q -n 0 tests/test_search.py tests/test_search_client.py` |
| G10 | `.venv/bin/python -m pytest -q -n 0 tests/test_github_workflows.py -k release` |
| G11 | `.venv/bin/python -m pytest -q -n 0 tests/test_architecture_boundaries.py tests/test_lazy_imports.py -k 'not installed and not sdist'` |
| G12 | `.venv/bin/python -m pytest -q -n 0 tests/test_ruff_policy.py tests/test_ruff_suppression_index.py` |
| G13 | `.venv/bin/python -m pytest -q -n 0 tests/test_docs_references.py tests/test_plan_status_index.py` |

For S13 also run `.venv/bin/python bin/check-dom15-fixtures --self-test`,
`.venv/bin/python bin/check-dom15-fixtures`,
`.venv/bin/python bin/check-doc-paths`, and
`.venv/bin/python bin/check-plan-status-index`.

Final integration runs the affected gate union once, the full TUI suite in its
retained environment, and `TAUT_PG_UV_NO_SYNC=1 .venv/bin/python bin/pytest-pg --fast tests/test_shared_contract.py
extensions/taut_pg/tests -n 2 --dist loadgroup`. That existing harness provisions
a temporary Docker PostgreSQL instance and selects shared/PG cases. Add the new
backend-neutral regressions to the shared file so this command actually runs
them; root-only SQLite tests do not count as PG proof. Docker and prepared
root/PG development dependencies are prerequisites. Run normal Ruff and formatter
checks on changed paths; run `.venv/bin/python -m mypy taut tests bin/release.py bin/release-artifact.py bin/require-green-workflows.py --config-file pyproject.toml` plus
`extensions/taut_tui/.venv/bin/python -m mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests --config-file extensions/taut_tui/pyproject.toml`. Do not run live model harnesses or
publication machinery merely because the plan touches tests.

Final docs gates: `.venv/bin/python bin/check-doc-paths`,
`.venv/bin/python bin/check-plan-status-index`, DOM-15 current-corpus/self-test,
`tests/test_docs_references.py`, and `git diff --check`. Run the canonical Ruff
suppression check with the project environment on PATH. Any necessary registry
change must be reasoned and reviewed; do not generate approvals from counts.

Observe success through public continuation: backup loads; rename/reuse searches
succeed; a failed cursor update still returns the committed post; cwd does not
change workspace; TUI continues sending/receiving and drops deleted rows; both
debug sinks receive valid JSON. These are acceptance probes, not a new permanent
monitoring or telemetry system.

## Independent Review Loop and Fresh-Eyes Review

Plan review has two independent roles: a fresh-eyes in-session reviewer who did
not author the plan and a different-family external model through
`skills/call-agent/SKILL.md`. Both receive the full plan including proposed spec
text, fixed baseline, relevant source/test paths, and the audit evidence.
Existence-check named files, flags, helpers and references before judging.

Use this stance for plan review and every later slice review:

> You are reviewing this remediation plan or its specified implementation slice;
> do not implement or modify files. Check correctness, completeness, independent
> commit boundaries and whether the tests prove the claimed observable behavior.
> Also actively look for over-armoring and over-engineering against hypothetical
> scenarios. For every proposed guard, abstraction, persisted state, retry,
> compatibility path or process gate, identify the observed failure it prevents.
> Prefer removing machinery or reusing an existing owner when that provides the
> same proof. Do not demand authentication, delivery guarantees, cross-backend
> lexical equality, a frozen dump snapshot, or general rename serialization that
> the approved slice does not claim. Existing unrelated defects are observations
> unless this change worsens them. Give suggested dispositions, not mandates.
> Scope expansions belong in a separate non-actionable observations section.
> Answer PASS or BLOCKED: could a zero-context engineer implement the defined
> slice confidently and correctly, and would it materially degrade the system?
> Every block must answer one of those questions with concrete source evidence.

After each meaningful slice, a separate reviewer checks the actual diff and
red/green evidence before its commit. External review repeats for the risky
rename changes and the final integrated result; other slice reviews may use a
separate in-session reviewer. Every review uses the anti-complexity stance.
Do not add more review rounds solely because a harmless alternative exists.

The author reproduces findings, records accept/reject/defer with reasons, and
revises the plan. Follow-up reviews examine accepted fixes and new defects from
them, not declined scope. Author fresh-eyes also checks source paths, commands,
failure priority, real test boundaries, and whether a smaller fix suffices.

## Completion and Commit Record

A slice's record includes commit SHA, changed files, red/green commands and
observed result, review dispositions and residual risk. Keep code/test/docs
aligned within that slice; a final documentation-only reconciliation commit is
needed only if integration leaves genuine cross-slice debt. No ceremonial empty
closeout commit. Update plan status after implementation and verification, not
after merely approving this plan.

Before claiming the implementation complete, all B/Q rows must have their
specified proof and verified commit, no unresolved accepted review finding may
remain, and any broader rename limitation must match the explicit owner scope
choice. Release qualification/publication is separate work.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

### Initial fresh-eyes review, 2026-09-14

Reviewer: separate Codex role `/root/fresh_plan_review`, which did not author
the plan. Reviewed initial plan content SHA-256 recorded with the external
review below, and the same repository baseline. Verdict: PASS on both plan
comprehension and material-degradation gates; no blocking P1/P2 findings.

| ID | Suggested disposition | Author disposition |
|----|-----------------------|--------------------|
| F1 | Remove the newly dead `completed_channel_renames` API in S4 | Accepted. S4 now removes the protocol/wrapper/SQL accessor and ledger-only tests while keeping real marker/reuse/resume/persistence proof. |
| F2 | Prefix PG gate with existing no-sync setting | Accepted. Command now uses `TAUT_PG_UV_NO_SYNC=1`. |

Review text (formatting normalized):

```text
PASS. No blocking [P1] or [P2] findings.

Gate 1, implement confidently and correctly: PASS. The plan names workable
owners, real proof boundaries, ordered dependencies, exact spec deltas, and
stop conditions.
Gate 2, avoid material degradation: PASS. The proposed changes preserve the
accepted product limits. I found no requirement that depends on solving R1.

The key design judgments hold:

S4: source lookup and retained markers: Implementable without a schema change.
_locate_exact_message already accepts an exact ID and candidate queues
(taut/client/_messaging.py:801). _registered_searchable_rows supplies the
maintenance scope without borrowing actor-visible show_message. Replacing
completed markers is safe only when this source lookup changes in the same
commit, as the plan requires. The miss-path queue scan is a reasonable cost for
avoiding a second location index.

S5: topology transaction: The preflight comparison closes the demonstrated
stale affected-list failure: the client currently captures children before
start_channel_rename, while that SQL function stores the supplied list without
rereading topology (taut/client/_threads.py:239, taut/state/_sql.py:1279).
Sharing the existing short transaction/advisory-lock path with registration is
proportionate. Checking the captured created_ts prevents the new name-reuse
semantics from attaching delayed registration to a different incarnation. No
operation-wide lock or lease is needed for this defined guarantee.

S7: drafts and watcher ownership: The remapping fits existing DraftState/
VisualState; no new persistent identity is required. Draft collision refusal
protects text that the new remap could otherwise overwrite. Reopening through
TuiSession.open_conversation reuses the owner already used by deletion refresh
(app.py:2496). The navigation-intent and post-success view-failure rules correctly
prevent a stale completion from taking control or inviting a second rename.

Other product slices: S1 reuses actual contributor validation before publication;
S2 contains only post-commit cursor work; S3 resolves the target once; S6 removes
a duplicate completion path; S8 targets encoded-character boundaries rather than
adding JSON repair. These mechanisms address the stated failures.

Test/checker slices: S9–S13 replace misleading or duplicated proof with checks of
the actual contract. They preserve meaningful runtime, publication, approval,
and parser boundaries. The proposed fence helper is narrowly shared; excluding
the CLI-claim and byte-offset rewrite parsers is correct.

Suggested nonblocking simplifications

1. Remove the newly dead completed_channel_renames accessor during S4. My
liveness check confirms that _current_search_thread is its sole production
consumer. Once that helper goes, the accessor survives only in the state
protocol/wrapper/SQL implementation and ledger-oriented tests. Remove those
surfaces and retain focused tests through get_channel_rename, marker replacement/
resume, and persistence. Add taut/state/__init__.py to S4’s file list. This
supports the plan’s subtraction goal; keeping the accessor would not materially
degrade the system.

2. Apply the author’s queued PG command correction. Prefixing the final PG
command with TAUT_PG_UV_NO_SYNC=1 makes the command match its prepared-environment/
no-resolution instruction. This is a command clarification, not an architectural
issue.

D1–D5 have existing insertion/replacement anchors and match their owning slices.
Atomic promotion is appropriate. S4 must precede S5; source lookup and marker
reuse must remain together. The other slices can remain separate commits, with
S12/S13’s policy text changing alongside their checks. No extra closeout commit
or review round is warranted without new debt or a changed design.

Observations, not actionable this pass: stale-job lookup can scan the current
queue set on a miss; this is the explicit tradeoff for removing historical
redirects. R1 remains a real publication race, but the plan states it honestly
and cleanly severs its remediation. Neither warrants adding machinery here.

Read-only review against HEAD 6f5ae8896b30b1965286a9b0cd5cfd936214c015; no files
changed and no implementation test results claimed. Consulted startup guidance,
program theory, Golden Rules/post-watermark lessons, relevant review/planning/
testing runbooks, the full plan and D1–D5, named governing spec sections,
implementation ownership notes, and relevant source/tests. Path checks found
only the explicitly proposed new bin/markdown_fences.py missing.
```


### External model review, 2026-09-14

Reviewer: Claude Opus 4.8 through the verified local CLI, separate family from
the author. Initial full plan SHA-256: `6bf30fc6a4fb43533010db45156d0aef6822d7f402978fa4a91c4862a374c35e`.
Repository baseline: `6f5ae8896b30b1965286a9b0cd5cfd936214c015`.
Invocation: read-only tool surface (`Read,Grep,Glob`), plan permissions, safe
mode, no MCP or subagents, 540-second timeout. Completed in 377 seconds, exit 0,
`success`, `is_error=false`, `end_turn`. No unexpected repository writes.
Full plan and review stance were embedded verbatim. Overall PASS, both gates
PASS. The review explicitly examined hypothetical defenses and simplification.

| ID | Suggested disposition | Author disposition |
|----|-----------------------|--------------------|
| C1 / P2-1 | Clarify topology lock-key provenance and order | Accepted. S5 explicitly introduces `taut:chat-topology` through the existing helper; distinguishes the current read gate; states topology-before-topic and unchanged topic-only acquisition. |
| C2 / P2-2 | Preserve the adjacent temporary-group requirement | Accepted. D2 now explicitly retains that sentence verbatim. |
| O1 | Local draft conflict can block an otherwise valid rename | Acknowledged tradeoff. Preventing loss of existing unsent text justifies the small preflight guard; no new draft storage or recovery workflow. |
| O2 | Document stale-source lookup cost | Accepted. S4 names the miss-only cost and owns the architecture-doc update. No extra index is proposed. |
| O3 | Topology fix touches cooperating registry writers | Acknowledged. The shared check is necessary for the demonstrated interleave; its boundary explicitly excludes R1. |

F1/F2 were applied while this independent review ran. C1/C2 and the explicit
capability/cost note are wording/deletion clarifications, not new architecture.
The author checked their final placement against the source. No accepted finding
remains open; no extra round is required for these nonblocking clarifications.

Verbatim external review:

````text
I've validated the plan's claims against the repository at the stated baseline. Every named symbol, file, command, and spec anchor I checked exists as described, and the reproduced-defect mechanisms (B3 topology race in `rename_channel`, B7 textual-delete bypass of `_run_deletion`, B2 unique-key `INSERT` in `start_channel_rename`, Q1 dead `segment_text` tests) are real. Here is my review.

---

# Plan Review — 2026-09-14 Audit Remediation Plan

## Verification summary (existence + mechanism)

- **S1**: `_preflight_load` (`taut/persistence/_operations.py:467`) holds the reusable contributor loop (`validate_records` with `core_member_ids`, lines 492–507); `dump_workspace` calls `validate_dump` before `os.replace` (line 430) but does **not** run the contributor loop — exactly the B1 gap. Sharing the loop and feeding it `parsed`/`active_components`/parsed core member IDs is feasible and additive. ✅
- **S2**: `_advance_sender_if_no_intervening` (`_messaging.py:677`) is a pure post-insert probe (`queue.peek_many`) + `advance_cursor`; wrapping only its body in `except Exception` matches the plan. Test `test_dm_started_notification_precedes_sender_cursor_probe_failure` exists in `tests/test_client.py`. ✅
- **S3**: `_resolve_target` (`_base.py:286`) reads `db_path or os.environ.get("TAUT_DB")` (line 303). Absolutizing after expansion is a local change. ✅
- **S4**: `_drain_search_jobs`/`_current_search_thread`/`_registered_searchable_rows` (`_searching.py:137/214/404`) confirmed; `start_channel_rename` uses a bare `INSERT` (no `ON CONFLICT`, `_sql.py:1302`) keyed on `old_name`, which is the exact B2 unique-key failure. `_locate_exact_message` lives in `_messaging.py:801` (not `_base.py`) with signature `(exact, candidates)` suitable for cross-queue exact peek — the plan correctly flags a possible `_base.py` typing seam rather than misplacing the symbol. `_registered_source_documents` has no callers (safe to delete). ✅
- **S5**: `_acquire_advisory_lock` (`_sql.py:1750`) is Postgres-only; `created_ts` is a real `taut_threads` column (SELECT at `_sql.py:1293`); the affected-set capture (`_threads.py:238–253`) precedes marker insert (259) — the demonstrated B3 window. ✅
- **S6/S7**: Textual `message delete` (`app.py:1409–1413`) calls `domain.delete_message` directly, bypassing `_run_deletion`→`_apply_deletion_result`→`_refresh_after_deletion` that the native path (`_confirm_message_delete`, `app.py:1785`) uses — confirms B7 and the S6 reuse remedy. `DraftState` is target-keyed with `text`/`cursor_position`/`revision` and unique targets (`models.py:80–94,162–164`), grounding S7's remap and draft-collision design. ✅
- **S8**: `_redact.py` rules `labeled_json_escaped`/`labeled_json_escaped_assignment` (lines 89–112) are the escaped-quote-terminated rules the B8 backslash case defeats; single shared, lazy, value-only transform confirmed. ✅
- **S9–S13**: `segment_text`/`_next_segment_end` dead (tests-only + re-export); the two Q1 tests (`test_search.py:63,1166`) do exercise `segment_text`, and the large case dedups to ~4 chunks as the plan warns. `_RuntimeImportVisitor`/`_probe_modules`/`CommandRegistry(entry_points=())`, `RAW_RULE_COUNTS`/`RETIRED_GROUP_NUMBERS`, `_workflow_data`/`_named_steps`, `_prose_lines`, `bin/check-dom15-fixtures`, `bin/check-plan-status-index`, `bin/ruff_suppression_index.py`, `tests/test_ruff_suppression_index.py` all exist; `bin/markdown_fences.py` correctly does **not** exist (new). No `continue-on-error` in any workflow — consistent with the plan's own framing of Q2 as a *test gap*, not a live hole. ✅
- **Spec deltas**: all anchors verified exact — D1 `[TUI-6.3]` (`10-taut-tui.md:373`), D2 "A separate movement-stable global…" (`01-…md:358`) and "Group IDs are unique" (`:388`), D3 `[DOM-10]`, D4 `[SRCH-9.3]` "Before source lookup"→"…require real tests" (`06-search.md:566–575`) + `[IAN-8.3]` + `[PIO-4.4]` table (`08-…md:333`), D5 `[IAN-8.1]` topic/serialization paragraph (`03-…md:723–731`) + `[IAN-8.3]` (`:761`). ✅

## Findings

**[P2-1] S5 "topology key" wording implies a nonexistent existing global lock.**
S5 says "acquire the shared topology key … matching the existing global incomplete-rename boundary" (plan:293,300–303). There is no existing *global* advisory lock: `_acquire_advisory_lock` is only ever called with per-key strings — `taut:channel:{old_name}` for rename (`_sql.py:1289`) and `taut:channel:{name}` for topic (`_sql.py:1116`); the "global incomplete-rename boundary" is a *read* gate (`_ensure_no_incomplete_channel_rename`), not a lock. A zero-context engineer may hunt for a preexisting global topology lock and stall, or conflate the new key with the existing `taut:channel:{old_name}` key (which is in fact the per-channel *topic* key the plan says to "retain … after the topology key"). *Smallest remedy:* state plainly that S5 introduces a **new** shared topology lock-key constant, acquired via the existing `_acquire_advisory_lock` mechanism, ordered before the retained per-channel `taut:channel:{name}` topic key; note the lock hierarchy (topology ⊃ topic) so `set_channel_topic` need not change.

**[P2-2] D2 second replacement boundary is ambiguous about the trailing sentence.**
"Replace the sentence beginning 'Group IDs are unique'" (plan:559) targets one sentence, but the current source has a following sentence in the same run: "A temporary group also names the active plan task that removes or re-evaluates it." (`01-…md:389–390`). The replacement block does not mention it, so it's unclear whether that temporary-group requirement survives. *Smallest remedy:* one clause stating the "A temporary group also names…" sentence is retained verbatim after the replacement (assuming intent is to keep it — dropping it would silently relax the temporary-group naming rule).

Neither is a correctness defect in the code design; both are documentation-precision risks on the two slices with the highest coordination cost. I found **no [P1]**.

## Over-engineering / simplification scan (all clear)
- Every guard I examined maps to a concrete, reproduced failure, not a hypothetical: S1 prevents overwriting a loadable backup with an unloadable dump; S7's draft-collision rejection prevents silent loss of unsent draft text under the real `unique targets` invariant (`models.py:164`); S5's preflight/re-read prevents the demonstrated orphaned-child topology. R1 is correctly **deferred**, not armored against.
- The plan actively *removes* machinery: dead segmenter (S9), exact import matrix (S11), duplicate Ruff snapshots (S12), duplicated fence logic (S13), and the transitive rename-redirect map + cycle detector (`_current_search_thread`, S4). These are net simplifications, not new abstractions.
- No new daemon/lockfile/lease/retry-loop/repair-worker is introduced; the R1 boundary and "no automatic repair of corrupted workspaces" language hold the line the owner set.

## Non-actionable observations (owner awareness, do not implement)
- **S7 UX tradeoff:** rejecting a valid domain `rename_channel` because of a *local* destination-draft collision is slightly surprising (a UI state condition blocking a persistent operation). It is the minimal data-loss-free choice and is codified in D1, so I raise it only for owner visibility, not as a change request.
- **S4 fallback cost:** on a hint miss, exact-peeking every registered searchable queue is O(queues) per unresolved job. Bounded and only on miss, but worth a comment in `09-search-architecture.md` so a future reader doesn't mistake it for a per-job full scan.
- **S5 breadth:** marker checks inside `upsert_thread`/`add_membership` plus threading `created_ts` through the state protocol touches core write paths broadly for a narrow race; this is inherent to the chosen fix and consistent with the owner's scope, not an expansion request.

## Gate answers
1. **Could a zero-context engineer implement this confidently and correctly?** **PASS.** The two [P2] wording clarifications (S5 topology-key provenance; D2 sentence boundary) are the only spots where an implementer could hesitate; both are one-line documentation fixes, and the red/green oracles, file lists, and gate commands are otherwise concrete and verified.
2. **Would it materially degrade the system?** **PASS.** Changes are net-safer (S1 fail-before-replace, S2 no-resend, S4 no lost-history cycle error), reduce duplication, introduce no data-loss/false-success/visibility regression, and preserve the accepted risks and version-1 job/dump shapes.

## Overall: **PASS**
The plan is accurate against baseline `6f5ae88`, respects the owner's narrow R1 scope without overstating S5's guarantees, and consistently prefers deletion/reuse over new machinery. Address the two [P2] documentation clarifications before implementing S5 and promoting D2; no blocking changes required.

*(Review-only: I made no repository writes, ran no code, and did no external research.)*
````

## Execution Log

### Plan authoring and review, 2026-09-14

Prepared this plan, its draft-status index row, six spec backlinks, and the
required Claude probe inventory refresh. No product code, tests, workflow,
active normative spec text, or dependencies changed. No implementation slice
has started and no commit was created; these documentation changes are left
uncommitted for owner review.

Verification: the new plan first made `bin/check-plan-status-index` fail with
its missing-row diagnostic; adding the draft row made it pass. Final checks:
`tests/test_docs_references.py` and `tests/test_plan_status_index.py` (32 tests),
`bin/check-doc-paths`, `bin/check-plan-status-index`, DOM-15 current-corpus and
self-test, and `git diff --check`. The implementation gates in this plan are
future work, not claimed results. Named-file inspection found only the
explicitly new `bin/markdown_fences.py` absent.

`skills/call-agent/SKILL.md` was evaluated during use. The existing inventory's
matched tool-availability/approval guidance was sufficient; refreshed probes
are recorded there. No new review framework or runbook change was needed.

Record subsequent implementation evidence here by slice.
