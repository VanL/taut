# Taut multi-factor review remediation plan

Date: 2026-07-11

Status: implemented and independently reviewed; uncommitted worktree

Plan type: umbrella implementation program with spec revision. Each execution
packet below has its own promotion baseline, red-green evidence, review, and
rollback boundary. This file is the index and shared contract; it is not one
pull request and does not create one serial critical path.

Promotion strategy: **A, in-file requirement text before implementation-link
claims, promoted just in time per execution packet**. Promote only the approved
text owned by the next packet, record that packet's baseline, then implement
against it. Do not activate every future requirement in one speculative spec
commit. Add implementation links and reciprocal code comments only in the
packet that supplies the behavior.

Owner: the integrating engineer owns the whole plan. Work may be delegated by
the landing boundaries below, but one owner reconciles cross-slice contracts,
reruns the full gates, and answers every independent-review finding.

## Goal

Resolve the confirmed correctness, Postgres isolation, watcher delivery,
Summon safety, CLI usability, documentation-drift, and test-measurement issues
from the 2026-07-11 outside review. Preserve intentional Taut semantics where
the review treated a documented tradeoff as a defect, but make those decisions
harder for the next agent to misunderstand through exact spec text, public
README guidance, focused inline comments, and firing tests where a contract is
enumerable.

This plan favors the smallest correct extension of existing paths. It does not
create a second message-write protocol, a second watcher, a generic security
framework, or a new persistence subsystem. Red-green TDD is mandatory for
every behavior change.

## Requested outcomes

- A Taut-authored message cannot receive a timestamp, wait behind sidecar work,
  and later commit below a cursor that has already passed it.
- A sender never advances past another member's concurrent message merely
  because the sender was caught up before writing.
- A piped watcher flushes each record, exits normally on a closed output pipe,
  and never poison-advances chat because the output sink failed.
- Postgres enforces the single route-key namespace for names and aliases under
  concurrency, and concurrent schema initialization converges.
- Corrupt Taut-owned JSON state fails loudly without completing recovery as a
  no-op.
- Failed watcher construction closes the runtime it just acquired.
- Summon's rate audit follows membership changes without identity-claim writes
  or persistent-handle leaks.
- `taut summon` uses normal cwd/config database discovery when `--db` is absent.
- First-summon name exhaustion cannot leave a temp-named zombie member.
- A malformed terminal query cannot grow the PTY responder buffer without a
  bound.
- The trust model states exactly who is authorized to influence a summoned
  agent, especially through a shared Postgres database.
- Reply authors receive a pointer to child-thread activity until they join the
  child thread themselves.
- CLI help is sufficient for an agent to discover arguments, important syntax,
  exit classes, timestamp formats, and the fact that tokens are continuity,
  not authentication.
- User-facing install instructions, dependency floors, changelog history,
  repository maps, and reference gates agree with the release metadata.
- Coverage measures core and Summon honestly, and copied scheduler branches
  have real firing tests.
- Rejected findings have an explicit, durable explanation at the nearest
  useful boundary instead of surviving only in this plan.

## Source documents and baseline

### Governing specs

- `docs/specs/01-development-documentation-operating-model.md` [DOM-3],
  [DOM-4], [DOM-8], [DOM-9], [DOM-10], [DOM-11], [DOM-13]
- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-3.5], [TAUT-4.3],
  [TAUT-7.1] through [TAUT-7.4], [TAUT-8.1] through [TAUT-8.5], [TAUT-9],
  [TAUT-10], [TAUT-11], [TAUT-12.1], [TAUT-12.5]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-2.5], [IAN-4.2]
  through [IAN-4.5], [IAN-5.2], [IAN-6.4], [IAN-7], [IAN-8.3], [IAN-9],
  [IAN-10]
- `docs/specs/04-summon.md` [SUM-3] through [SUM-6], [SUM-7.4], [SUM-8]
  through [SUM-12]

### Existing rationale and prior decisions

- `docs/plans/2026-07-06-evaluation-findings-remediation-plan.md`, especially
  F5 and F6. This plan reopens F5 only because the A1 fix supplies an atomic
  committed write timestamp and the post-write bounded probe removes the race
  without adding a query. F6 remains intentional.
- `docs/plans/2026-07-10-taut-summon-quality-remediation-plan.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- Outside-review source:
  `/Users/van/.codex/attachments/abe74a20-5217-4118-9dc2-5a7810b0fd93/pasted-text.txt`

### Spec baseline

- Repository and spec baseline:
  `06bfc93d57298de06b8ba2baf417a14b8fd0f32d`.
- The outside review and this plan's reproductions use the same baseline.
- Worktree state before plan creation: clean.
- Promotion baseline: the user requested uncommitted implementation, so every
  packet uses `06bfc93d57298de06b8ba2baf417a14b8fd0f32d + worktree diff`.
  Final promoted spec SHA-256 values are: DOM
  `1135f7ca4461ea3a3b53104d16067d659ee7f3972a7e541ce3fc8f5f0da85217`,
  core `a38b07cfd0ede98e8ceb71b1faeda9f42b37cc0cbe6988ef6860fe175f293ae7`,
  identity/notifications
  `5644ab73e880370326a4d033b15dfd462ac7644b24c8d837db9856f65c6feae8`,
  and Summon
  `b4106ed98f7bc3197f28071d351ddab86254650c274c4a7c10209b91a601aaa9`.
- Status mechanism: existing active spec files plus strategy A. Do not
  reclassify an active spec file to stage these paragraph edits.

### Independent workstreams and authority gates

The workstreams below may advance independently once their own spec text is
promoted. A1/A2 alone depend on a new SimpleBroker release.

| Workstream | Packets | Hard dependency |
|---|---|---|
| Broker/core ordering | 0, 2 | maintainer authorizes SimpleBroker publish, selects its version, then authorizes Taut floor bump |
| Watch delivery | 3 | none beyond current baseline |
| Postgres state isolation | 4 | Docker Postgres test lane available |
| Core state/lifecycle cleanup | 5A, 5B, 5C | none beyond current baseline |
| Summon trust/audit/bootstrap | 6, 7, 8A, 8B | paired core/Summon artifact gate where a core API changes |
| Reply and human UX | 9A, 9B, 10 | promoted notification and CLI contracts |
| Release/docs/test infrastructure | 11, 12, 13 | factual runtime/version baseline only |

Planning approval selects the proposed contracts in this document. It does not
authorize publishing SimpleBroker, changing a released dependency floor, or
tagging/pushing artifacts. Those external mutations require an explicit
maintainer go/no-go immediately before the action. An unavailable external
release blocks only packets 0 and 2.

## Findings inventory and dispositions

The implementer must preserve this inventory. If a finding changes disposition
during implementation, add a Deviation Log row before changing code.

| Finding | Disposition | Planned action |
|---|---|---|
| A1 | confirmed major | Tasks 0 and 2: atomic broker write returns its committed ID; delete Taut live exact-ID writes |
| A2 | real, previously accepted | Task 2: revise [TAUT-7.4] and replace the pre-write probe with a bounded post-write probe |
| A3, C2, C3 | confirmed, one root cause | Task 3: flush per watch event; stop on EPIPE without poison advance |
| A4 | confirmed major on Postgres | Task 4: transaction-scoped Postgres advisory locks for route keys and schema initialization |
| A5, B10, C9 | intentional | Tasks 1 and 10: keep claim-consume behavior; add public docs/help warning |
| A6 | partly confirmed | Task 5B: make fallback resolution lazy; document direct `MultiQueueWatcher(db=None)` compatibility |
| A7 | confirmed | Task 5A: strict contextual JSON decoders and corruption tests |
| A8 | confirmed | Task 5B: close a newly created watch runtime if watcher construction fails |
| A9 | confirmed low | Task 5C: one `DELETE ... RETURNING` membership operation |
| A10 | confirmed low | Task 5C: remove repeated parent update and batch one read cursor write per thread |
| A11 | confirmed low | Task 10: distinguish `argv is None` from explicit `[]`; delete unreachable branch |
| A12 | partly confirmed | Task 5C: remove only proven-dead internal protocol/functions; retain used helper |
| B1, D4 | partly confirmed plus trust gap | Task 6: continuation-line framing, persona defense-in-depth, exact SQLite/Postgres trust text |
| B2 | confirmed major late-join gap | Task 7: read-only joined-thread API plus control-thread audit-handle reconciliation |
| B3 | intentional | Task 6: state that control evidence is a staleness fence, not authorization |
| B4 | rejected as major | Task 6 docs: state why cohesive driver/generation state stays together; no size-driven split |
| B5, C12 temp-name half | confirmed | Task 8A: create directly under the final claimed name with fail-not-adopt `--new` semantics |
| B6 | contract mismatch, code behavior deliberate | Task 1: reconcile [SUM-7.4]/[SUM-10]; keep bounded termination fallback |
| B7 | confirmed low | Task 8B: bound incomplete terminal-query retention and prove recovery |
| B8 | partly confirmed | Task 8B: share only release-evidence predicate; document why close machines and STATUS projections differ |
| B9 | intentional PTY residual | Tasks 1 and 6: document first user-turn orientation and ordering |
| C1, C12 id hint, C14 | confirmed UX cluster | Task 10: complete core and Summon argparse help plus meta-tests |
| C4 | confirmed product gap | Task 9A: `reply` notification until parent author joins child |
| C6 | intentional cursor tradeoff | Tasks 1, 2, 10: spec, inline comment, README example |
| C7 | non-contract enhancement | Task 1: clarify JSON success vs stderr diagnostics; do not invent an error schema |
| C8 | already documented | Task 10: reinforce in `--token` help; no authentication work |
| C10 | partly confirmed | Task 9B: friendly DM human label and friendly notification time/id; JSON keeps internal names |
| C11 | intentional arbitrary UTF-8 | no behavior change; inventory is the durable disposition |
| C13 | intentional exit class | Task 10: expose the class in help; no breaking exit-code split |
| D1, D2 | confirmed major docs drift | Task 11: correct pins/floors and add metadata consistency gates |
| D3 | confirmed release-history debt | Task 11: reconstruct nine missing changelog sections from tag ranges |
| D5, D7, D8 | confirmed docs drift | Tasks 11 and 13: repair map, inventory, and skills pointer |
| D6, E4 | confirmed gate blind spot | Task 11: broaden maintained-doc sources and register all code families explicitly |
| D9 | partly confirmed | Task 13: add concrete owner/boundary/verification/action metadata only where missing |
| D10 | partly confirmed; broad archival rejected | Task 13: one canonical startup pointer and a lessons index; no archive/governance redesign |
| D11 | partly confirmed | Task 13: remove duplicated verification prose; retain the lightweight skill template |
| E1 | partly confirmed | Task 12: keep working subprocess coverage; add `taut_summon` to measured sources |
| E2 | confirmed test debt | Task 12: real firing tests for priority and RESERVE; do not delete copied behavior casually |
| E3 | rejected repository defect | no repository change; `coverage.xml` is already ignored and regenerated |
| E5 | partly confirmed | Task 12: replace only named timing assertions with event/step bounds |
| E6 | unsupported as defect | Task 12 comments: retain white-box tests where the internal state machine is the contract |
| E7 | partly confirmed | Task 12 comments: exact CI selectors remain intentional; no YAML dependency |
| E8 | false positive | Task 12 coverage makes the existing adapter tests visible; no adapter rewrite |

## Current architecture and required reading

Read these files before editing. Do not infer behavior from this plan alone.

### Message identity and cursors

- `taut/client/_messaging.py`: `reply`, `_say_chat_thread`, `_say_dm`,
  `_write_message`, `_insert_message`, `read_unread`, `_resolve_message_id`.
  Today, live writes split `generate_timestamp()` from `insert_messages()`.
- `taut/client/_threads.py`: `join` currently uses one preallocated timestamp
  for registry, membership cursor, and the later notice insert.
- `taut/client/_base.py`: abstract write path and queue ownership.
- `docs/specs/02-taut-core.md` [TAUT-7.4], [TAUT-10].
- Sibling SimpleBroker source at `/Users/van/Developer/simplebroker/`:
  `simplebroker/db.py::_do_write_transaction`, `simplebroker/sbqueue.py::Queue.write`,
  `simplebroker/_backend_plugins.py::BrokerConnection`, and
  `extensions/simplebroker_redis/simplebroker_redis/core.py::_write_message`.

Comprehension gate:

1. Why is `insert_messages([(body, ts)])` correct for import/restore but unsafe
   for a live writer that allocated `ts` earlier?
2. Why must the sender's post-write pending probe use the open interval
   `(old_cursor, written_ts)` rather than a plain `has_pending(old_cursor)`?
3. Why may `join` keep a provisional sidecar timestamp but never use it as the
   live notice's message ID?

### Watch delivery

- `taut/cli.py::_cmd_watch`, `_emit_messages`, `_emit_notifications`,
  `_print_json`.
- `taut/watcher.py::TautWatcher._make_taut_handler` and the per-queue error
  handler path inherited from SimpleBroker.
- `tests/test_watcher.py` poison, lifecycle, membership, and real-queue tests.
- `tests/test_cli.py` plus `tests/conftest.py::run_cli`.

Comprehension gate:

1. Which layer knows that `BrokenPipeError` means terminal sink failure rather
   than poison input?
2. Why must ordinary application handler failures retain the existing
   three-strike liveness rule while EPIPE stops after the first attempt?

### SQL state and Postgres

- `taut/state/_sql.py`: all Taut-owned SQL, route checks, schema init,
  membership delete, JSON row decoders, rename apply.
- `taut/state/_dialect.py`: the existing and intentionally narrow place for
  SQLite/Postgres divergence.
- `extensions/taut_pg/tests/test_pg_sidecar.py` and `bin/pytest-pg`.
- [IAN-4.3], [IAN-8.3], [TAUT-12.1].

Comprehension gate:

1. Why do separate UNIQUE constraints on `taut_members.name_key` and
   `taut_member_aliases.alias_key` not enforce one cross-table namespace?
2. Why does SQLite's `BEGIN IMMEDIATE` hide the race while Postgres READ
   COMMITTED exposes it?
3. Why is a transaction-scoped advisory lock a smaller change than a new
   route registry table?

### Summon

- `extensions/taut_summon/taut_summon/_driver.py`: injection framing,
  `_first_summon`, generation lifecycle, watcher ownership.
- `_control.py`: fixed control reactor, rate-audit queues, hard-breach policy.
- `_pty.py`: interruption contract and `_TerminalResponder`.
- `_persona.py`: mandatory prompt sections.
- `_state.py` and `cli.py`: duplicated release-evidence predicate.
- `docs/specs/04-summon.md` and
  `docs/implementation/05-taut-summon-architecture.md`.

Comprehension gate:

1. Why does a normal Taut display name not permit the review's newline-name
   example, while multiline message text still needs unambiguous framing?
2. Why is a persona warning defense-in-depth rather than authorization?
3. Which thread owns rate-audit queue handles, and why must membership changes
   be reconciled on that same owner thread?
4. Why is direct final-name creation safer than deleting a partially visible
   member after failure?

### Documentation, release, and tests

- `README.md`, `CHANGELOG.md`, extension READMEs, and all three
  `pyproject.toml` files.
- `bin/release.py` plus `tests/test_release_script.py`.
- `tests/test_docs_references.py` and `tests/test_github_workflows.py`.
- `.github/workflows/test.yml` coverage job.
- `docs/agent-context/README.md`, `docs/lessons.md`, all runbooks, and
  `docs/implementation/02-repository-map.md` / `03-agent-inventory.md`.

## Critical flows

These diagrams are implementation constraints, not alternate designs.

```text
live chat write
  prior cursor
      |
      v
encode once -> Queue.write(body) -> committed own ID
                                    |
                                    v
                         best-effort notifications
                                    |
                                    v
                     peek open interval (prior, own)
                         | empty          | non-empty
                         v                v
                  advance to own ID   leave cursor
```

```text
watch record
  decode -> render -> flush -> handler returns -> advance chat cursor
                    |
                    +-- EPIPE -> StopWatching -> exit 0, no retry, no advance

ordinary handler exception -> failure count 1/2 -> retry
                           -> failure count 3   -> poison advance
```

```text
Postgres route mutation transaction
  advisory lock("taut:route:" + normalized key)
      -> probe member table
      -> probe alias table
      -> insert/rename
      -> commit releases lock

Postgres empty-schema initialization transaction
  advisory lock("taut:schema") as first SQL statement
      -> META_DDL -> remaining DDL -> version read/write -> commit
```

```text
Summon control-owner audit turn
  read joined thread names
      -> add queue at active-window lower bound
      -> keep existing queue/cursor
      -> close queues for departed memberships
      -> audit own posts in the rate window
      -> publish STATUS snapshot
```

Keep the first three diagrams, or a smaller equivalent invariant comment, near
the shared implementation helpers when code changes land. Do not paste the
whole program diagram into unrelated modules.

## Invariants and constraints

### Message and cursor invariants

- A live message ID is allocated and inserted in the same broker transaction.
- Taut uses SimpleBroker public APIs only. No private import, broker-table SQL,
  nonce search, body round-trip, or `latest_pending_timestamp()` guess may be
  used to recover a just-written ID.
- Exact-ID `insert_messages` remains available for imports, fixtures generated
  through production import paths, and deliberate corruption probes. It is not
  a live chat write path.
- Chat history remains append-only and uses peek APIs. Notifications remain the
  explicit claim-consume exception.
- Cursor writes remain monotonic and best-effort after the message commit.
- A sender advances to its own message only when no other timestamp exists in
  `(prior_cursor, own_message_ts)`. Messages above the own timestamp remain
  unread. Existing older unread means the sender's own post may later appear in
  `read`; that is intentional under one high-water cursor.
- Notification failure never rolls back a successful chat write.

### SQL and portability invariants

- All Taut-owned SQL remains in `taut/state/_sql.py`.
- SQLite keeps its current writer serialization. Postgres adds only built-in,
  transaction-scoped advisory locks through the existing dialect marker.
- The advisory-lock key derives deterministically from a namespaced text value
  inside Postgres (`hashtextextended` or the supported equivalent). Do not use
  Python's randomized `hash()`.
- No schema table or version bump is introduced for route locking.
- Corrupt required JSON is fatal and named. Nullable JSON object fields may map
  `NULL` to `{}`, but invalid JSON, wrong top-level types, or malformed rename
  items never silently map to empty state.

### Watch and process invariants

- One output record is flushed before its chat cursor advances.
- A closed output pipe is a normal terminal condition: exit 0, no traceback,
  no retry, no poison count, and no cursor advance for the failed record.
- A message-specific user handler failure keeps the existing three-strike
  poison rule. Do not globally disable liveness handling to fix EPIPE.
- Queue handles are opened, used, reconciled, and closed on their owner thread.
- Bounded joins are checked; cleanup errors do not mask a primary failure.

### Summon and trust invariants

- Taut still has no authentication. Storage access is membership and control
  access. For Summon, it also means authority to supply user-role input to the
  local harness; docs must say this without implying prompt framing is a
  security boundary.
- Message text remains arbitrary UTF-8 and multiline. Frame continuation lines;
  do not strip user content or claim to prevent semantic prompt injection.
- The rate backstop is a per-member rate circuit breaker, not a semantic loop
  detector. It covers every currently joined thread and may miss a loop below
  the configured rate by design.
- A newly discovered audit queue starts no later than the active rate-window
  floor, never at current head. Posts made after join but before reconciliation
  remain visible to the audit. Leaving retains the last audit cursor; rejoining
  cannot reset it. A bounded set of timestamps already counted in the active
  window prevents rename/rejoin double counting.
- The control evidence tuple remains a staleness fence, not a credential.
- PTY orientation remains the first injected user turn because generic PTYs
  have no system-role channel. It must precede watcher startup.
- The PTY soft-interrupt path may terminate the child when Ctrl-C delivery
  itself fails, as already required by the fd-lifecycle contract.
- First summon never adopts an existing member. A direct final-name create is
  atomic: either a new member with that name exists or the attempt fails before
  membership/notice creation.

### Engineering constraints

- No new dependency without explicit maintainer approval. Raising the existing
  SimpleBroker floor is permitted only after the required release exists and
  its artifact passes the paired compatibility gate.
- Reuse existing helpers and state owners. Do not add a repository/service
  layer, generic event bus, route-lock table, custom YAML parser, or second
  watcher abstraction.
- Format with `ruff`; do not hand-reflow unrelated code.
- Tests are typed and run through real Queue, SQLite, Postgres, CLI subprocess,
  and scripted-provider paths. Mock only OS/provider boundaries when a real
  deterministic seam does not exist.
- Every behavior change starts red. Record the failing test command and failure
  reason in this plan's execution log before implementation.

### Stop and re-plan gates

Stop before continuing if any task appears to require:

- a SimpleBroker private import or a Taut-side live-write workaround;
- a new route table or destructive data migration;
- automatic membership of parent authors in every subthread;
- a second rate-audit thread or queue-handle owner;
- treating persona prose as an authorization mechanism;
- deleting chat history or partially created members as cleanup;
- a new third-party docs/YAML/testing dependency;
- weakening exact CI selectors, installed-artifact isolation, cursor monotonicity,
  or the no-traceback gate;
- more than the files named for that task without first recording why in the
  Deviation Log.

## Rollout, compatibility, and rollback

This program has multiple landing boundaries. Do not combine them into one
unreviewable change.

1. Land independent watch, Postgres, state, Summon, UX, and docs packets in any
   dependency-safe order after promoting only their own spec deltas.
2. For A1/A2 only, obtain maintainer approval, publish the SimpleBroker
   timestamp-return contract, record the selected version, and verify SQLite,
   Postgres, and Redis. Existing callers that ignore `Queue.write()`'s return
   stay source-compatible.
3. Promote the A1/A2 Taut text, then land core message/cursor changes with a
   dependency floor that requires the new broker API. Mixed-version Postgres
   workspaces remain vulnerable while an old Taut writer is active; release
   notes must require upgrading all active writers before claiming the race is
   closed.
4. Release core and Summon together for packets that add the read-only joined
   thread API or notification vocabulary. The existing paired-artifact verifier
   must prove compatibility before tag or push.
5. Docs/test-only packets may land independently after their referenced runtime
   behavior exists.

Rollback is by landing slice. No planned change deletes persisted chat or adds
a one-way schema migration. Revert Summon consumption of a new core API before
reverting that core API. Do not roll back the SimpleBroker floor while the Taut
write path expects a returned timestamp. Reply notifications use additive JSON
vocabulary; older readers already treat unknown payloads as malformed pointers,
so paired rollout is preferred even though chat remains intact.

Post-release signals:

- no hidden-message reproduction under forced writer interleaving;
- piped `watch --json` emits before shutdown and exits promptly after `head`;
- Postgres concurrent name/alias claims yield exactly one winner;
- Summon STATUS `thread_count` and rate audit follow join/leave churn;
- cwd-only `taut summon scripted` reaches control readiness;
- no temp-named members after forced name collisions;
- docs-reference and metadata-consistency gates remain green on release bumps;
- coverage contains both `taut` and `taut_summon` source trees.

## Proposed spec delta

Task 1 promotes the following exact intent one execution packet at a time. The
implementer may adjust nearby grammar, but may not weaken these rules without a
Deviation Log entry and new review.

### `docs/specs/02-taut-core.md` [TAUT-3.4], append to SimpleBroker interop

> Every Taut-authored live chat write uses SimpleBroker's ordinary atomic
> write path and receives that committed row's message ID from the same call.
> Taut never allocates a live message ID and later supplies it to
> `insert_messages`; exact-ID insertion is an import/restore surface, not a
> live-write surface. This requirement makes timestamp order and visibility
> order the same for Taut-authored messages.

### `docs/specs/02-taut-core.md` [TAUT-7.4], replace the accepted race paragraph

> Sender catch-up is decided after the sender's message commits. Given the
> cursor value observed before the write and the committed message ID returned
> by SimpleBroker, Taut advances to the sender's ID only when no pending chat
> message exists in the open interval between those values. A message above the
> sender's ID remains unread normally. An older unread message prevents the
> advance, so the sender's own post may later appear in `read`; with one
> high-water cursor Taut cannot hide that post without also hiding the older
> message. This applies to every Taut-authored chat record that may catch up a
> cursor, including join/creation notices after sidecar membership creation.
> This is deliberate.

### `docs/specs/02-taut-core.md` [TAUT-8.3], append to the Python API

> `joined_thread_names()` returns the acting member's current chat-thread names
> through read-only identity resolution. It does not update activity, record an
> identity claim, inspect unread state, or create membership. Long-lived
> extensions use it to reconcile their own thread-scoped resources.

### `docs/specs/02-taut-core.md` [TAUT-8.4], replace the handler-failure paragraph

> A message-specific handler failure leaves the cursor in place and uses the
> three-consecutive-failure poison rule. A terminal delivery failure, including
> a closed CLI output pipe, is not a poison message: it stops the watcher after
> the first failed delivery, leaves the cursor unchanged, and emits no
> traceback. CLI watch flushes each rendered record before successful handler
> return.

### `docs/specs/02-taut-core.md` [TAUT-8.1]/[TAUT-8.2], append CLI clarification

> Help text is part of the agent-usable surface: every option and positional
> names its purpose, message-ID suffix and timestamp forms are discoverable
> from the owning subcommand, and the root help names exit-code classes.
> `--json` defines successful stdout records. Errors and warnings remain concise
> text diagnostics on stderr and are classified by exit code; Taut does not
> define a JSON error envelope. `--token` is described as continuity selection,
> never authentication. With no subcommand, help goes to stderr and exits 1.

### `docs/specs/02-taut-core.md` [TAUT-8.1] and `docs/specs/03-identity-addressing-notifications.md` [IAN-3.3], append fresh explicit-name behavior

> `join(..., new=True)` means create a fresh member and never adopt an existing
> route. When an explicit `as_name` is already a member name or alias, the call
> raises the existing identity-collision error before activity, claim,
> membership, cursor, persona, or notice mutation. The CLI `join --new` has the
> same fail-not-adopt behavior.

### `docs/specs/02-taut-core.md` [TAUT-9], append Summon trust boundary

> When Summon is used, authority is wider than permission to converse: every
> principal that can write the configured Taut storage can supply user-role
> input to the summoned harness and can issue storage-backed control requests.
> In a shared Postgres deployment, a remote database writer can therefore
> influence tools available on the machine hosting the harness. Operators must
> grant database write access only to principals authorized for that effect, or
> run the harness with separately constrained tools. Message framing, personas,
> driver evidence, names, and continuity tokens do not create an authorization
> boundary.

### `docs/specs/03-identity-addressing-notifications.md` [IAN-4.3], append concurrency rule

> The name/alias route-key namespace remains unique under concurrent writes on
> every supported backend. Before checking either route table and inserting or
> renaming a route, a server-backed SQL implementation serializes the normalized
> route key for the current transaction. Per-table UNIQUE constraints remain
> the final same-table backstop; they are not sufficient for cross-table
> uniqueness by themselves.

### `docs/specs/02-taut-core.md` [TAUT-12.1], append Postgres initialization rule

> Concurrent clients may initialize an empty Postgres Taut sidecar. The first
> statement in each initialization transaction acquires the fixed Taut schema
> advisory lock before any DDL or version read/write. Every caller either sees
> or creates one complete supported schema; no caller observes a partial schema
> or fails only because another supported initializer ran concurrently.

### `docs/specs/03-identity-addressing-notifications.md` [IAN-7], add reply notifications

> A `reply` notification points the author of a parent message to activity in
> that message's child thread. Taut emits one for each reply while the parent
> author is not a member of the child thread, except when the author wrote the
> reply or the parent is a foreign message without a stable `from_id`. Once the
> author joins the child, ordinary unread/watch delivery replaces the pointer.
> If the same reply mentions the parent, Taut emits only the reply notification,
> not a duplicate mention pointer. The payload uses `type: "reply"` and the
> existing actor/thread/message fields; `thread` is the child queue. Membership
> is observed after the reply commits and immediately before notification
> dispatch. A concurrent join may therefore leave one stale disposable pointer;
> it never loses or duplicates the durable reply, and later replies use the new
> membership state. After a later leave, reply pointers resume.

### `docs/specs/03-identity-addressing-notifications.md` [IAN-6.4], append human rendering

> Human `list` renders a valid direct message as `DM with <current names>` while
> JSON retains the stable internal `thread` and `members` fields. Missing or
> malformed participant metadata renders `DM <internal-thread> (participants
> unavailable)` and emits no invented identity or extra stderr warning. Human
> notification actions are type-specific: a mention renders `taut log
> <source-thread>` plus the shortest unique source-message suffix usable with
> `taut reply` **when the recipient is a member** (full ID on ambiguity); a
> reply pointer renders `taut log <child-thread>`; `dm_started` renders the DM
> read target and no invented reply ID. `log` is the membership-independent
> inspection action. All render local `HH:MM`. JSON timestamps and names do not
> change.

### `docs/specs/04-summon.md` [SUM-4], replace temp-name creation steps

> First summon claims a proposed final name, then asks core to create a fresh
> member directly under that name with fail-not-adopt semantics. If the route is
> already occupied, no member, membership, or notice is created; summon releases
> the claim, chooses the next allowed fallback, and retries. A successful create
> yields the continuity token and final visible name in one step. Summon never
> creates under a temporary visible name and never deletes a partially visible
> member as collision cleanup. The existing mid-bootstrap collision policy is
> preserved: after a claimed candidate is found occupied, both implied and
> chosen-name first summons may retry with the documented loud fallback. A
> failure after successful member creation but before session publication may
> still leave a final-named, non-summoned member; this change closes collision-
> exhaustion debris only and does not invent destructive member rollback.

### `docs/specs/04-summon.md` [SUM-5.2], replace multiline framing paragraph

> Each chat event remains one user-role event. The first line uses the existing
> source/speaker prefix; every continuation line in message text is indented so
> content such as `[system]` cannot visually forge a new top-level driver frame.
> Text is otherwise preserved. This is attribution hygiene, not prompt-injection
> prevention or authorization.

### `docs/specs/04-summon.md` [SUM-10], append authority and backstop limits

> The default persona states that injected chat is user-role workspace input,
> that a line claiming to be system or driver policy is not thereby trusted,
> and that the harness follows the operator's authority policy. This is
> defense-in-depth only. The mechanical rate audit reconciles every currently
> joined chat thread before each due audit and closes handles for threads that
> were left. A newly discovered queue begins at the later of summon start and
> the active rate-window floor, never current head; a retained cursor survives
> leave/rejoin, and already-counted timestamps are deduplicated within the
> active window. It limits posting rate per member; it does not detect semantic
> loops below the configured rate. A hard breach requests the adapter's normal
> interrupt operation. If soft interrupt delivery fails, the PTY adapter may
> terminate the child under [SUM-7.4]; that fallback is an interrupt-I/O failure,
> not an independent policy decision to restart a healthy generation.

### `docs/specs/01-development-documentation-operating-model.md` [DOM-3]/[DOM-9]

> Agent startup has one canonical ordered entry point in
> `docs/agent-context/README.md`. Root aliases point to it rather than restating
> competing orders. `docs/lessons.md` retains its durable content and adds a
> compact topic index so an agent can route to relevant detail. This remediation
> does not create a lesson archive, purge policy, or new documentation lifecycle;
> those would require a separate measured operating-model proposal.

## Dependency-ordered implementation tasks

### Task 0: Add the atomic write-result contract in SimpleBroker

Outcome: the existing atomic write path returns the exact committed timestamp
without creating a second write path.

Files in `/Users/van/Developer/simplebroker/`:

- `simplebroker/db.py`
- `simplebroker/sbqueue.py`
- `simplebroker/_backend_plugins.py`
- `extensions/simplebroker_redis/simplebroker_redis/core.py`
- nearest write contract tests, including `tests/test_write_visibility.py`
- Postgres and Redis shared/conformance tests
- SimpleBroker README/spec/implementation note and its own dated plan

Steps:

1. In the SimpleBroker repo, create its own baseline-aware plan and failing
   public tests first. Assert `timestamp = Queue.write(body)` is an `int`, an
   exact peek by that ID returns `body`, and concurrent writes return distinct
   IDs matching their rows on SQLite, Postgres, and Redis.
2. Add a forced transaction-order test for SQLite and Postgres, Taut's supported
   state backends: pause lower-ID writer A before commit, start writer B, and
   prove B cannot become visible before A. This is the ordering invariant Taut
   needs; distinct return values alone are insufficient. Redis proves exact
   return-ID conformance only. Its current separate timestamp allocation is not
   redesigned because Redis-backed Taut state is explicitly unsupported; do not
   claim Redis visibility-order closure in either project's docs.
3. Force the SQL timestamp-conflict retry once, then assert the returned ID is
   the successful retry's committed row, not the failed attempt. Exhaust the
   retry budget and assert failure raises without exposing a stale ID. Add the
   equivalent protocol/conformance assertion for backends without that SQL
   retry path.
4. Thread the timestamp return through the existing functions. Make
   `_do_write_transaction`, its retry wrapper, `BrokerCore.write`, the
   `BrokerConnection` protocol, Redis `write`, and `Queue.write` return the
   successful ID. Do not duplicate `_do_write_transaction` or expose a second
   `write_with_timestamp` path.
5. Prove existing callers that ignore the result remain valid. Run the full
   SimpleBroker backend gates and build fresh artifacts.
6. Stop for explicit maintainer approval before publishing. After approval,
   publish the selected version, record it here, verify its artifact, and stop
   again before raising Taut's dependency floor.

Red gate: the public return-value assertion fails because current `Queue.write`
returns `None`.

Done signal: all three backends return the committed ID; SQLite/Postgres forced
visibility ordering and SQL retry tests are green; Redis exact-ID conformance is
green; built wheels pass SimpleBroker's artifact checks; and the approved
released version is recorded in this plan.

Stop if any backend cannot return the same ID its atomic write committed. Do
not compensate in Taut.

### Task 1: Promote each packet's spec delta and backlinks just in time

Files:

- only the spec files owned by the next execution packet
- their `## Related Plans` sections
- this plan's per-packet promotion-baseline table

Steps:

1. Select one execution packet. Apply only its exact intent above without
   implementation-link claims. Do not promote unrelated future packets.
2. Add this plan to each touched spec's Related Plans.
3. Run `uv run pytest -q -n0 tests/test_docs_references.py` and
   `git diff --check`.
4. Record packet, refs, files, and baseline before touching runtime code.

| Packet | Promoted refs/files | Baseline | Status |
|---|---|---|---|
| populate during implementation | | | pending |

Done signal: specs are the sole active contract for that packet and its code
cites only promoted text. Repeat this task immediately before every packet that
changes behavior.

### Task 2: Replace Taut's live exact-ID write path and close sender races

Files:

- `pyproject.toml` and lock/artifact metadata required by the new SimpleBroker floor
- `taut/client/_base.py`
- `taut/client/_messaging.py`
- `taut/client/_notifications.py`
- `taut/client/_threads.py`
- `tests/test_client.py`
- `tests/test_shared_contract.py`
- PG shared-contract configuration where the same tests already run
- `docs/implementation/04-taut-architecture.md`

Steps:

1. Write one deterministic red-green test that runs unchanged before and after
   the fix. Create a third, caught-up observer. A delegating scheduling gate
   pauses writer A immediately before publication (after real allocation on the
   baseline path; before the real atomic `Queue.write` on the new path), lets B
   commit, then releases A. Do not stub a broker operation. Baseline proves a
   lower ID can publish late; the fixed path proves the writer that publishes
   second receives the later ID. The observer must read both in ID order.
2. Write the A2 red test: pause A after it captures the old cursor, let B say,
   let A say, then assert A reads B and not its own post. Assert `log` contains
   both.
3. Change `_write_message` to encode once, call `queue.write(body)`, use the
   returned ID to build `Message`, and emit best-effort notifications afterward.
   Preserve the current order across callers:
   `write -> build Message -> notifications -> interval probe -> cursor`.
4. Change live notification delivery to `queue.write(payload)` and ignore its
   returned ID; this does not change claim-consume semantics or add an ack.
   Remove `_insert_message` from the client abstract/concrete live path. Keep
   direct `insert_messages` only in explicit import/restore fixtures and
   deliberate corruption probes.
5. For sidecar-first operations (`join`, first reply, first DM), keep a clearly
   named provisional **state** timestamp for registry/membership fields. Write
   the notice/message through `_write_message`; never reuse the provisional ID
   as a broker message ID.
6. Add one shared sender-advance helper. It receives prior cursor and committed
   own ID, performs `peek_many(1, after_timestamp=prior,
   before_timestamp=own_id)`, and advances only when empty. Use it for channel,
   DM, reply, and join notice paths where cursor catch-up applies.
7. Add table-driven real-boundary tests firing the helper through channel say,
   DM creation/send, reply creation/send, and join notice. Force an intervening
   message after sidecar membership/registry creation but before the relevant
   notice; it must remain unread.
8. Add an inline invariant comment at the helper explaining why own messages
   remain unread when older unread exists. Do not add per-message read flags.
9. Run shared SQLite and real Postgres behavior tests before broad gates.

Anti-mocking: use real SimpleBroker, sidecar state, and processes/threads. Do
not mock `Queue.write`, `peek_many`, or cursor state. A scheduling event around
the old seam is allowed only to force the interleaving.

Done signal: both deterministic race tests fail on baseline, pass after the
change, and the existing sender/DM/reply/join contracts remain green.

### Task 3: Make watch output delivery-aware without weakening poison liveness

Files:

- `taut/cli.py`
- `taut/watcher.py`
- `tests/test_cli.py`
- `tests/test_watcher.py`
- [TAUT-8.4] implementation mapping in `docs/implementation/04-taut-architecture.md`

Steps:

1. Add a real CLI subprocess test that starts `watch --json` with a pipe, sends
   one message, and uses a reader-thread/Event readiness proof rather than sleep
   to observe the line before shutdown; POSIX `select` may be supporting proof,
   not the only cross-platform gate. Fire the same shared flush path with a
   notification.
2. Add a real closed-pipe test. Drain the watcher member first, record its exact
   cursor, start watch, and prove the child is alive with no backlog. Close the
   parent read end **before** publishing a unique target message, wait for exit
   0, assert no traceback, then prove the cursor remains below that exact ID.
   Send enough later messages to prove the process did not stay alive poison-
   advancing them.
3. In `_cmd_watch`, flush stdout after each complete Message or Notification
   emission. Keep non-watch commands unchanged; process exit already flushes
   them.
4. On `BrokenPipeError` from render or flush, mark the CLI sink closed and raise
   `StopWatching`. In `TautWatcher._make_taut_handler`, catch `StopWatching`
   before the broad poison counter. Define one Taut default error handler that
   stops for `StopWatching` and delegates every other exception to the existing
   SimpleBroker default. Pass it as `default_error_handler_fn` so it covers the
   notification queue, initial chat queues, and chat queues added during
   membership refresh.
5. Suppress only the final stdout-close EPIPE needed for clean interpreter
   shutdown. Do not suppress other OSError classes.
6. Keep and rerun the three-strike poison test with a non-terminal handler
   exception. Add an EPIPE firing test for a chat queue added after live
   membership refresh.

Done signal: JSON appears while the process is live; `watch | head` terminates;
failed output does not move the cursor; real poison still advances at three.

### Task 4: Serialize Postgres route and schema conflicts

Files:

- `taut/state/_dialect.py`
- `taut/state/_sql.py`
- `tests/test_state_contract.py`
- `extensions/taut_pg/tests/test_pg_sidecar.py`
- `docs/implementation/04-taut-architecture.md`

Steps:

1. Add deterministic real Postgres races for member-create versus alias-create
   and member-rename versus alias-create on the same normalized key. Use a
   pass-through session/SQL barrier that gets both baseline transactions past
   both route probes; after the fix, prove the second blocks at the advisory
   lock. Assert exactly one owner, one expected loser, and valid final routes.
2. Add concurrent schema-init coverage starting from a database with no Taut
   tables. Start multiple constructors together; every caller must succeed and
   the complete schema/version must be valid.
3. Keep the advisory-lock SQL helper in `taut/state/_sql.py`. Pass
   `self.dialect` explicitly from `SqlSidecarTautState` through `ensure_schema`,
   `insert_member`, `update_member_name`, and `add_member_alias`.
   `taut/state/_dialect.py` remains the marker/capability owner and contains no
   SQL. SQLite is a no-op because `BEGIN IMMEDIATE` already serializes writers.
4. Acquire `taut:route:<key>` before either table probe in member insert,
   member rename, and alias insert. Keep per-table UNIQUE constraints.
5. For Postgres schema initialization, open the transaction and make the fixed
   `taut:schema` advisory lock its first SQL statement, before `META_DDL`, every
   other DDL statement, and version inspection/insertion.
6. Make runtime and PG tests pass `POSTGRES_SQL_DIALECT`, not the portable
   marker, when they expect Postgres behavior.

Anti-mocking: use Docker Postgres through `bin/pytest-pg`. A fake session may
test emitted SQL as supporting proof, but cannot replace the two-connection
race.

Done signal: each deterministic lock site fires, the second PG transaction is
observed waiting at the lock, every empty-schema initializer converges, and
SQLite state tests remain unchanged. Repetition is optional stress evidence,
not the red gate.

### Task 5A: Make corrupt owned state fail loudly

Files:

- `taut/state/__init__.py`
- `taut/state/_sql.py`
- `taut/cli.py`
- `tests/test_state_contract.py`, `tests/test_cli.py`, `tests/test_cli_probes.py`
- PG shared state tests

Steps:

1. Add parameterized red decoder tests for member meta, thread meta, claim
   evidence, and rename `affected_json`: invalid JSON syntax, wrong top-level
   type, rename item missing `old`/`new`, and non-string keys. Use real sidecar
   SQL only to create the corrupt fixture; invoke the public reader/resume and
   assert the rename marker remains incomplete.
2. Replace permissive JSON fallback with contextual decoders: nullable object,
   required object, and required rename-list shape. Validate every rename item
   has string `old` and `new`. Do not repair or mark complete silently.
3. Add representative black-box CLI probes for member/thread/claim/rename
   reads: exit 1, exactly one stderr line naming the table/field, no traceback,
   no stdout, and no mutation of the incomplete marker.

Done signal: every corrupt-shape class fails through both Python and shipped CLI
boundaries, names its context, and remains recoverable.

### Task 5B: Close watcher construction leaks and keep DB resolution lazy

Files:

- `taut/client/__init__.py`
- `taut/client/_watching.py`
- `taut/watcher.py`
- `tests/test_watcher.py`, `tests/test_client.py`

Steps:

1. Wrap runtime creation in `TautClient.watch` so any later constructor failure
   closes the exact runtime once. Test with a real runtime captured by a thin
   factory wrapper, then inspect its owned queue is closed. Do not use
   `psutil.open_files()` timing.
2. Make explicit DB selection lazy in `MultiQueueWatcher`: do not resolve cwd
   config when `db` is supplied. Retain the copied Weft `db=None` fallback for
   advanced compatibility and add a vendor-deviation comment that public Taut
   callers use `TautClient.watch`.

Done signal: failed construction closes once and an explicit DB never probes
irrelevant cwd config.

### Task 5C: Land low-risk SQL, cursor, and dead-code cleanup

Files:

- `taut/state/__init__.py`
- `taut/state/_sql.py`
- `taut/client/_messaging.py`
- nearest state/client tests and PG shared state tests

Steps:

1. First prove `DELETE ... RETURNING` on every supported SQLite CI/runtime and
   real Postgres. The baseline documents no SQLite library floor, so do not call
   it portable by assumption. If all supported targets pass, replace membership
   SELECT-then-DELETE with that one statement and derive the boolean from its
   row. If any supported target lacks it, stop and add the smallest dialect-
   owned affected-row mechanism; do not silently raise the SQLite floor for
   this low-severity race. Add a two-caller real race test: one true, one false,
   final absence.
2. Move the loop-invariant parent update outside the channel-rename loop.
3. In `read_unread`, decode one thread page, append its messages, then advance
   once to the highest successfully decoded timestamp. If decoding raises, do
   not advance that page. Add a 1,000-message real test with a delegating state
   counter only as supporting evidence for one cursor call.
4. Remove `membership_threads`, internal `list_thread_memberships` protocol /
   adapter/free function, and the unused adapter wrapper for
   `get_channel_rename`; retain the module helper used by rename start.

Done signal: concurrent delete reports one winner, read cursor writes are
bounded by threads rather than messages, and static checks find no dead imports.

### Task 6: Clarify and harden Summon input/trust framing

Files:

- `extensions/taut_summon/taut_summon/_driver.py`
- `extensions/taut_summon/taut_summon/_persona.py`
- `extensions/taut_summon/tests/test_driver.py`
- `extensions/taut_summon/tests/test_persona.py`
- `README.md`
- `extensions/taut_summon/README.md`
- `docs/implementation/05-taut-summon-architecture.md`

Steps:

1. Add format tests proving normal multiline content is preserved while every
   continuation line is indented. Include bodies beginning with `[system]`,
   `[notify]`, and a forged speaker prefix. Retain a test proving invalid
   newline member names are rejected at core validation.
2. Implement one shared continuation-framing helper used by chat messages and
   notices where arbitrary text can occur. Do not sanitize or strip content.
3. Extend the real driver/scripted-provider injection round trip so multiline
   forged-frame content reaches the child. Assert the exact one-event payload
   observed by the child; a pure formatter test alone is not wiring proof.
4. Add a mandatory persona section named `## Chat trust and authority`; update
   the exported section tuple and its enumerable test.
5. Update public trust docs for SQLite and Postgres, control staleness evidence,
   notification at-most-once semantics, PTY orientation as first user turn,
   and the fact that rate limiting does not detect low-rate loops.
6. Add an implementation note explaining why `_driver.py` stays cohesive:
   generation, pump, watcher, and bootstrap share one live state machine with
   named fences/tests. Also explain why PTY and stream close machines and STATUS
   reserved/display sets intentionally differ. Do not split files for size.

Done signal: forged frame text is visibly continuation content, the persona
section fires, and no doc claims framing prevents prompt injection.

### Task 7: Reconcile Summon rate audit membership and cwd discovery

Files:

- `taut/client/_threads.py` and public facade/type declarations as needed
- `tests/test_client.py`, `tests/test_shared_contract.py`
- `extensions/taut_summon/taut_summon/_control.py`
- `extensions/taut_summon/taut_summon/_driver.py`
- `extensions/taut_summon/tests/test_control.py`
- `extensions/taut_summon/tests/test_driver.py`
- `extensions/taut_summon/tests/test_summon_cli.py`
- implementation docs for core and Summon

Steps:

1. Add red core tests for `joined_thread_names()`: current names only, no
   activity timestamp change, no claim write, no unread query, no creation.
2. Implement it through `_resolve_member(..., _touch_activity=False)` and the
   existing membership state. Return a deterministic tuple/list sorted by the
   existing state order; document the chosen order.
3. In `_driver.py`, capture one database-wide `audit_start_ts` before the first
   harness spawn, store it in the driver bootstrap/supervision state, and pass
   the integer into every `ControlLoop` generation. Before each due audit, call
   `joined_thread_names()` on the control thread. Because
   `peek_many(after_timestamp=cursor)` is exclusive while the window includes
   `ts >= cutoff`, compute the effective cursor as
   `max(0, audit_start_ts, cutoff - 1, retained_cursor)`. For a never-seen name,
   `retained_cursor` is absent. Never initialize at current head. Clamp old
   retained cursors to the moving `cutoff - 1` floor so a long leave cannot
   force an unbounded historical scan.
4. Retain each thread's last audit cursor after leave. Maintain a bounded set of
   own-message timestamps already counted in the active window so leave/rejoin
   and channel rename cannot reset or double-count the breaker.
5. Add one owner-thread-only `_ControlReactor` helper that evicts an auxiliary
   handle from `_queue_cache` and closes it exactly once. It must refuse the
   control queue and configured topology queues. Reconciliation uses it for
   left threads and `_queue()` to obtain a fresh handle after rejoin. Do not
   mutate reactor topology or touch handles from a watcher callback.
6. Keep reconciliation/open/retire logic in small `ControlLoop`/reactor helpers;
   do not add a manager class. Make `StatusSnapshot.thread_count` use the
   reconciled current set.
7. Remove both `db_path is None` blockers: the early return in `run()` and the
   rejection in `_make_broker_handles()`. Construct
   `TautClient(db_path=self._db_path, token=...)` even when the selector is
   `None`, then pass `client.target` to `_ControlReactor` and owned queues.
8. Split real-process proofs: (a) no-`--db` cwd quickstart reaches PING/STATUS;
   (b) join and post over the limit before first reconciliation, then observe
   the breaker; (c) join, wait for STATUS `thread_count`, leave, rejoin, prove a
   fresh live handle and resumed auditing; (d) force broker-handle recovery with
   `db_path=None` and prove it resolves the same target. Use the scripted
   provider and real SQLite. Run the read-only API through the shared Postgres
   contract lane as well.

Done signal: no identity-claim collision, late threads are audited, left queues
close once, and the README quickstart works verbatim.

### Task 8A: Remove temp-name bootstrap without destructive cleanup

Files:

- `taut/client/_identity.py` and join tests
- `extensions/taut_summon/taut_summon/_driver.py`
- associated core identity, driver, and conformance tests
- `docs/implementation/05-taut-summon-architecture.md`

Steps:

1. Add a core red test that `join(new=True)` with an occupied explicit name
   fails without adopting, moving cursors, or writing a notice. Clarify this as
   fail-not-adopt behavior.
2. Rewrite `_first_summon` as one bounded loop: claim candidate, create directly
   with explicit name plus `new=True`, release and choose fallback on collision,
   then continue with the created final member. Remove temp generation and
   post-create `set_name` branches. Each candidate attempt owns exactly one
   persistent creator client and closes it once in `finally`, on success or
   failure. Release only that attempt's claim. Keep shared cleanup, not six
   bespoke exits.
3. Force every candidate collision in a real database and assert failure leaves
   no new member, membership, notice, claim, or session. Also cover one collision
   then success, concurrent implied summons, and explicit chosen-name behavior.
   Preserve the current loud fallback after a mid-bootstrap collision for both
   implied and chosen names.
4. Add explicit failure-injection tests after successful member creation but
   before session publication. If `last_created_member` exists, the initiating
   terminal's protected creation diagnostic must name the residual final member
   and its continuity token. Document the non-destructive recovery exactly:
   use that token with `taut set name` to move the residual aside, then summon
   again; it cannot be resumed as a summoned session. Do not log the token to a
   shared log, claim the whole bootstrap is atomic, or add destructive rollback.
5. Force multiple collision attempts followed by a post-create failure. Assert
   every retired creator closes exactly once, only the active attempt's claim is
   released, and the diagnostic token can perform the documented rename.

Done signal: collision exhaustion leaves no temp member and direct creation
never adopts. Later bootstrap failures have explicit, tested residual behavior.

### Task 8B: Bound PTY parser state and remove proven DRY drift

Files:

- `extensions/taut_summon/taut_summon/_pty.py`
- `extensions/taut_summon/taut_summon/_state.py`
- `extensions/taut_summon/taut_summon/cli.py`
- associated PTY, state, CLI, and conformance tests
- `docs/implementation/05-taut-summon-architecture.md`

Steps:

1. Export one release-evidence predicate from `_state.py` and make CLI use it.
   Keep STATUS reserved-key sets and PTY/stream close machines separate; add
   comments pointing to their different ownership contracts.
2. Add a finite terminal-response buffer cap. On an oversized incomplete
   CSI/OSC, retain only the bounded suffix beginning at the last plausible ESC,
   or clear it when no prefix can complete. A later valid query must still be
   recognized.
3. Test unterminated CSI and OSC in chunks larger than the cap, bounded retained
   bytes, and later valid query response. Add a test-only deterministic
   scan-step/byte counter and assert work is bounded by a constant multiple of
   total input bytes; do not use a wall-clock performance assertion. Keep
   existing real PTY tests as integration proof.

Done signal: responder memory stays bounded, scan work is linear by operation
count, and a valid query after malformed input still receives a response.

### Task 9A: Add reply discovery pointers

Files:

- `taut/client/_messaging.py`, `_notifications.py`, `_codec.py`, `_models.py`
- `taut/cli.py`
- `tests/test_client.py`, `tests/test_cli.py`, shared backend contract tests
- notification specs and implementation note

Steps:

1. Add red public tests for the exact reply-notification rules in the promoted
   spec, including self reply, foreign parent, already-joined parent, duplicate
   mention suppression, claim-consume loss, two consecutive pre-join replies,
   suppression after join, resumption after leave, and one permitted stale
   pointer when join races post-commit membership observation.
2. Refactor message-id resolution to return the decoded parent Message once;
   derive both child name and stable author from it. Do not perform a second
   full/suffix scan.
3. Emit `reply` notification only after reply commit. Let mention delivery take
   an excluded recipient-ID set and add the stable parent-author member ID, so
   one source message cannot create both reply and mention pointers for that
   recipient. Do not confuse a message ID with a recipient ID.
4. Extend notification decoding/rendering and its enumerable vocabulary tests.
   Unknown foreign notification types remain warning objects, not crashes.

Done signal: a parent discovers replies without automatic child membership;
JSON contracts stay stable except the additive notification type.

### Task 9B: Make human DM and notification labels actionable

Files:

- `taut/client/_models.py`, `taut/client/_threads.py`
- `taut/cli.py`
- `tests/test_client.py`, `tests/test_cli.py`
- [IAN-6.4] implementation note

Steps:

1. Add a human-only `Thread` display label computed from current DM participant
   names. Keep JSON `thread: dm.d_*` and `members` unchanged. For missing or
   malformed participants, render exactly
   `DM <internal-thread> (participants unavailable)` with no invented identity
   and no extra stderr warning.
2. Render notification time and next action by type: mention uses local `HH:MM`,
   `taut log <source-thread>`, and the shortest unique source-message suffix
   usable with `taut reply` only when membership permits (full ID on ambiguity);
   reply uses local `HH:MM` and `taut log <child-thread>` because `log` is
   membership-independent; `dm_started` uses the DM read target and no reply ID.
   Do not add a timezone label to each row; this matches existing local
   message-time rendering.
3. Use field/substr assertions, not full-output goldens. Cover valid DM, guest,
   malformed metadata, suffix collision/full-ID fallback, and midnight/date
   rollover without asserting wall-clock time. Execute each advertised
   unconditional action through the public CLI/API, including a nonmember
   mention recipient and a parent author who left before the reply. Separately
   prove the mention reply suffix works when membership permits. Text-only
   checks are supporting proof.

Done signal: human DM list output no longer exposes only an opaque queue and a
notification contains enough information to issue the next command.

### Task 10: Make both CLIs self-documenting and clarify intentional contracts

Files:

- `taut/cli.py`
- `extensions/taut_summon/taut_summon/cli.py`
- `tests/test_cli.py`, `extensions/taut_summon/tests/test_summon_cli.py`
- `README.md`, extension README, relevant spec implementation snapshots

Steps:

1. Add `description`, subcommand `help`, positional `help`, and option `help`
   to every parser action. Root help names exit classes; subcommands own syntax
   details rather than one giant root epilog.
2. Add a parser meta-test that walks every registered action and fails when a
   non-help action lacks useful help. Add phrase-level tests for reply suffix,
   `log --since`, stdin, token continuity, JSON stderr behavior, and summon DB
   discovery. Do not freeze whole help output.
3. Send no-subcommand help to stderr with exit 1. Preserve `--help` stdout/0.
4. Change `main` to `list(sys.argv[1:] if argv is None else argv)`. Remove the
   unreachable `SystemExit` branch from `_handle_error`.
5. Improve reply-ID errors with the owning usage form and suffix minimum.
6. Add public docs examples for: notifications are disposable pointers; own
   posts can remain unread behind older unread; exit 2 combines empty/not-found;
   empty text remains allowed arbitrary UTF-8; JSON errors stay stderr text.
   For A5/B10, say exactly that a crash after `inbox`/notification watch has
   claimed a pointer can lose that pointer, while the source chat remains
   durable and later *notification-worthy* activity may produce a new pointer.
   Do not promise that every ordinary chat post creates a notification.

Done signal: an agent handed only either binary can discover every flag and the
load-bearing command rules; parser inventory tests fire for every action.

### Task 11: Repair release/docs drift and turn it into executable gates

Files:

- `README.md`, extension READMEs, `CHANGELOG.md`, manifests
- `bin/release.py`, `tests/test_release_script.py`
- `tests/test_docs_references.py`
- new focused `tests/test_project_metadata_consistency.py` only if the checks do
  not belong cleanly in existing release/docs tests
- `docs/implementation/02-repository-map.md`

Steps:

1. Correct core, PG, and Summon install examples to the current coordinated
   version and correct artifact/tag names. Correct the SimpleBroker floor.
2. Extend release version updates to update the exact README pins. Add a
   pre-mutation gate requiring a changelog heading for the target version.
   Add a non-mutating `--checks-only` mode that executes the same precheck
   commands and exits before version writes, artifact publication, tag, or push.
   Keep `--dry-run` as a command preview and never count it as executed proof.
3. Reconstruct missing changelog sections from each adjacent tag range. Use
   `git log --first-parent OLD..NEW` plus release plans; do not infer content
   from the 0.5.2 summary alone. Review each section against the tag tree.
4. Expand maintained path-reference sources to root/extension READMEs,
   agent-context current routing/lessons/runbooks, skills, specs,
   implementation, and root agent aliases. Continue excluding historical
   plans, changelog, and any future archived incident bodies as scanners.
5. Generalize code detection to all bracketed families. Map TAUT/IAN/SUM/DOM
   to local spec files. Register CC/SB explicitly as external provenance
   families with reasons and allowed source scope. Define concrete-citation
   grammar so instructional placeholders and fenced/inline examples such as
   `[API-4]`, `[ABC-2]`, and `[REF-4]` do not become claims. Any unknown family
   used as a real citation fails until registered. Add scanner self-tests for a
   local citation, external provenance, unknown real citation, placeholder,
   wildcard, inline sample, and fenced sample.
6. Add metadata gates asserting manifest versions, the core package constant,
   README pins, extension artifact examples, and dependency floors agree.
7. Refresh the repository map from actual files/plans and correct plan status.

Done signal: deliberately reverting any corrected pin/floor/path/code family
causes a focused test to fail; release `--checks-only` refuses a missing
changelog.

### Task 12: Make coverage and scheduler tests honest without test theater

Files:

- `pyproject.toml`
- `.github/workflows/test.yml`
- `tests/test_github_workflows.py`
- `tests/test_watcher.py`
- named Summon timing tests in `extensions/taut_summon/tests/`
- coverage/release docs

Steps:

1. Begin red with a coverage probe that runs one real CLI child and one scripted
   Summon provider child, then queries coverage data for lines reachable only
   in those children. Package presence at 0% is not evidence.
2. Keep `COVERAGE_PROCESS_START`, parallel files, and `coverage combine`, and
   enable Coverage 7's native subprocess patch in `[tool.coverage.run]` (the
   baseline uses Coverage 7.15). Do not add a custom `sitecustomize` hook unless
   the supported native patch fails the red probe.
3. Add `taut_summon` to configured coverage sources. Run separate fresh-process
   coverage invocations matching the existing release lanes: root/core,
   Summon normal, Summon live-harness, and Summon local-LLM selectors. Let each
   write parallel data, then combine. Do not collapse SQLite/PTY lanes into one
   pytest process.
4. Gate on executed lines in `taut_summon/_driver.py`, `_control.py`, Summon CLI,
   and the known subprocess-only probes, plus the existing report. Do not use
   “package appears in XML” or one aggregate percentage as the collection gate.
5. Add real `MultiQueueWatcher`/`BaseReactor` tests for multiple priorities and
   RESERVE. Write real queues, run a bounded process turn, assert high priority
   drains first and reserve moves the row into the named reserve queue.
6. Keep whole-copy vendor behavior. If a branch is intentionally retained only
   for parity, its firing test is still required.
7. Replace the named `<3s` and fixed negative sleep assertions with Events,
   barriers, bounded step counts, or product readiness signals. Do not perform a
   broad private-test rewrite.
8. Add comments to workflow tests that exact selector/order strings are
   load-bearing SQLite/PTY isolation contracts. Retain exact checks; do not add
   PyYAML or weaken them to key existence.
9. Document that internal monkeypatches are allowed when the named state machine
   itself is the contract, but real subprocess/backend proof remains required at
   the boundary.
10. Remove ignored local `coverage.xml` only as developer cleanup if desired; no
   repository task or test treats its presence as debt.

Done signal: child-only probes and critical Summon files have executed lines in
combined data; RESERVE/priority tests fail if their branches no-op; timing tests
use deterministic completion signals.

### Task 13: Repair factual documentation routing without a governance redesign

Files:

- `AGENTS.md`, `docs/agent-context/README.md`, `docs/README.md`
- `docs/specs/01-development-documentation-operating-model.md`
- `docs/lessons.md`
- all nine runbooks missing explicit operating metadata
- `docs/implementation/03-agent-inventory.md`
- `docs/implementation/04-taut-architecture.md`
- `skills/README.md` and `docs/agent-context/runbooks/skills-lifecycle.md`

Steps:

1. Establish `docs/agent-context/README.md` as the one canonical startup order.
   Root and newcomer docs link to it and add only role-specific supplements.
2. Add a compact topic index to `docs/lessons.md` without moving, deleting, or
   reclassifying incident text. Reject the outside review's archive/compaction
   prescription for this remediation: there is no measured read-cost baseline
   or approved retention policy. A future redesign needs its own plan and proof.
3. Fix `../skills/` to `../../skills/`.
4. Add tailored Owner, Boundary, Verification, and Required action blocks to
   runbooks that lack them. Do not paste generic boilerplate.
5. Refresh agent inventory with actual read-only probes and label each result
   present, verified usable, or blocked with date/error. State how to refresh.
6. Keep `skills/README.md` and `_template` as the cheap extension point; do not
   invent a skill merely to populate the directory. Mark the lifecycle optional
   until a real reusable workflow graduates.
7. Keep the full verification block in one canonical owner. Replace the second
   copy in architecture docs with a pointer plus area-specific deltas.

Done signal: one startup pointer, every lesson remains in place and becomes
easier to route by topic, factual inventory/pointers are current, and duplicated
commands cannot drift independently.

### Task 14: Final traceability, adversarial acceptance, and release readiness

Files:

- all touched specs' Related Plans and implementation snapshots
- this plan's status, promotion baselines, execution log, deviation log, and
  review report
- `docs/lessons.md` only for genuinely new reusable corrections

Steps:

1. Reconcile spec sections, plan tasks, implementation docs, code comments, and
   firing tests. No plan-only requirement remains after promotion.
2. Run the targeted gates below, then the full release gates from current
   README/release helper. Record commands and observed results, not assertions.
3. Run an independent completed-work review after each major landing boundary
   and once over the assembled program. Reproduce every finding before acting.
4. Exercise black-box probes: broken pipe, invalid JSON state, concurrent
   writers, concurrent PG routes, no-db summon quickstart, malformed PTY query,
   help/exit codes, stale README pin mutation.
5. Build fresh core, PG, and Summon artifacts and run paired compatibility.
6. Update plan status only after the relevant work is committed and verified by
   `git log`. If the user requests uncommitted review, report it as uncommitted
   rather than ready to land.

## Test plan and exact gates

### Per-slice red-green discipline

For each runtime task:

1. Add the smallest failing regression through the real production boundary.
2. Run only that test with `-n0 -vv` and record the expected failure.
3. Implement the smallest shared-path change.
4. Rerun the red test, then the nearest file/suite.
5. Run `ruff`, `ruff format --check`, and `mypy` over touched source and tests.

No task may begin with a mock-call-count assertion as its primary proof.

### Targeted commands

```bash
uv run pytest -q -n0 tests/test_client.py tests/test_shared_contract.py
uv run pytest -q -n0 tests/test_watcher.py tests/test_cli.py
uv run pytest -q -n0 tests/test_state_contract.py
uv run ./bin/pytest-pg extensions/taut_pg/tests/test_pg_sidecar.py tests/test_shared_contract.py
uv run pytest -q -n0 extensions/taut_summon/tests/test_persona.py
uv run pytest -q -n0 extensions/taut_summon/tests/test_control.py
uv run pytest -q -n0 extensions/taut_summon/tests/test_pty_adapter.py
uv run pytest -q -n0 extensions/taut_summon/tests/test_driver.py
uv run pytest -q -n0 extensions/taut_summon/tests/test_summon_cli.py
uv run pytest -q -n0 tests/test_docs_references.py
uv run pytest -q -n0 tests/test_release_script.py tests/test_github_workflows.py
```

The implementer must confirm `uv run ./bin/pytest-pg --help` selector syntax
before assuming multiple paths are accepted; split invocations if required.

### Static and full gates

Use the current canonical commands at implementation time. At this baseline:

```bash
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev mypy taut tests extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
uv run pytest -q
uv run pytest extensions/taut_summon/tests -m "not xdist_group"
uv run pytest extensions/taut_summon/tests -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 1 --dist loadgroup
uv run pytest extensions/taut_summon/tests/test_live_harness.py -n 1 --dist loadgroup
uv run pytest extensions/taut_summon/tests/test_live_local_llm.py -n 1 --dist loadgroup
uv run ./bin/pytest-pg --fast
uv build
uv build extensions/taut_pg
uv build extensions/taut_summon
uv run python bin/verify-reactor-release-artifacts.py
uv run python bin/release.py all --checks-only
git diff --check
```

`uv run pytest -q` covers the root `tests/` only because of configured
`testpaths`; it is never shorthand for the Summon lanes. `--dry-run` is useful
for previewing release mutations but does not execute prechecks and is not a
verification gate.

### Coverage collection gate

After Task 12 updates the configuration, preserve the separate process lanes:

```bash
export COVERAGE_PROCESS_START="$PWD/pyproject.toml"
export COVERAGE_FILE="$PWD/.coverage"
python -m coverage erase
python -m coverage run --parallel-mode -m pytest tests -m "not slow"
python -m coverage run --parallel-mode -m pytest extensions/taut_summon/tests -m "not xdist_group"
python -m coverage run --parallel-mode -m pytest extensions/taut_summon/tests -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 1 --dist loadgroup
python -m coverage run --parallel-mode -m pytest extensions/taut_summon/tests/test_live_harness.py -n 1 --dist loadgroup
python -m coverage run --parallel-mode -m pytest extensions/taut_summon/tests/test_live_local_llm.py -n 1 --dist loadgroup
python -m coverage combine
python bin/verify-coverage-evidence.py
python -m coverage report --show-missing
python -m coverage xml
```

The first full run proved that pytest-cov and native subprocess patching
conflicted over data-file ownership and left the scripted provider at 0%.
That red child-line probe was preserved; the final commands above select
Coverage itself as the sole owner. `bin/verify-coverage-evidence.py` queries
Coverage's data API for named child-only and critical Summon lines rather than
grepping XML or trusting the aggregate percentage.

Success means zero test, lint, format, type, docs-reference, metadata, build, or
artifact errors. Coverage percentages alone do not satisfy enumerable contract
proof.

### What must remain real

- SimpleBroker SQLite, Postgres, and Redis write paths
- Taut sidecar tables and cursor rows
- CLI/watch subprocess pipes
- Docker Postgres concurrent transactions
- scripted Summon provider as a real child process
- PTY parser integration tests where fd behavior matters
- release artifacts built from fresh explicit paths

Acceptable limited fakes:

- `threading.Event` barriers that force a deterministic race;
- pure parser byte chunks for `_TerminalResponder`;
- OS process evidence fakes already required for cross-platform branches;
- delegating counters around a real state object as secondary performance proof.

## Failure-mode and coverage map

```text
Queue.write return
  +-- ordinary commit [SQLite + PG + Redis] -> exact returned row
  +-- timestamp retry [backend-specific] -> successful retry ID
  +-- exhausted retry [backend-specific] -> raises, no stale ID
  +-- blocked lower ID [SQLite + PG only] -> cannot publish after higher ID
      (Redis visibility ordering is outside unsupported Redis Taut state)

Taut live write [shared backend contract]
  +-- say / DM / reply / join -> atomic write ID
  +-- open interval empty -> sender cursor advances
  +-- intervening row -> sender cursor stays; observer reads both
  +-- notification failure -> chat remains committed

Watch [real child process]
  +-- message/notification render + flush -> delivery then cursor advance
  +-- EPIPE initial/refreshed queue -> exit 0, no advance/no poison
  +-- ordinary handler error x3 -> existing poison liveness

Postgres [real two-connection barrier]
  +-- create vs alias / rename vs alias -> one lock winner
  +-- empty-schema constructors -> all converge

Summon [real scripted provider + owned queues]
  +-- multiline forged frame -> one indented user event
  +-- late join before reconcile -> included in rate window
  +-- leave/rejoin -> fresh handle, retained cursor, no double count
  +-- cwd open/reopen -> same discovered target
  +-- name collision exhaustion -> no collision-created member
  +-- post-create failure -> named residual, no destructive rollback
  +-- oversized CSI/OSC -> bounded bytes and scan steps, later recovery

Reply/CLI/docs [public API + black-box CLI]
  +-- reply pointer rules -> repeated/join/leave/race cases
  +-- DM/notification labels -> valid and malformed metadata
  +-- corrupt JSON -> one-line error, no mutation
  +-- help/reference/version gates -> mutation tests fire
  +-- coverage -> known child-only lines have hits
```

| Production failure | Required handling | Primary proof | User-visible result |
|---|---|---|---|
| Broker returns failed-attempt ID | return only after successful commit | forced retry integration | write succeeds with usable ID or raises |
| Sender probe fails after commit | leave cursor unchanged; chat survives | backend fault injection around real queue | error/warning, later read recovers |
| Notification write fails | never roll back chat | real queue failure seam | warning; durable chat remains |
| Output pipe closes mid-record | stop immediately, no cursor/poison | child pipe test | exit 0, no traceback |
| PG route contenders collide | serialize normalized key | deterministic two-session race | one clear identity error |
| PG init races on empty DB | schema lock before first DDL | concurrent constructors | all callers get valid schema |
| Owned JSON is malformed | contextual fatal error, no auto-repair | real corrupt row + CLI | one-line named error |
| Watch construction fails | close newly owned runtime once | delegating factory over real runtime | original error, no leaked handle |
| New audit thread appears late | scan active window, not head | post-before-reconcile process test | breaker still fires |
| Audit thread leaves/rejoins | retire cached handle; retain cursor | join/leave/rejoin process test | current STATUS, no skipped/double posts |
| Cwd-only handles reopen | rediscover same target | forced recovery process test | control remains available |
| Final-name collision exhausts | fail before member creation | real collision loop | clear error, no temp member |
| Failure after final member create | preserve non-destructive residual | injected bootstrap failures | clear recovery guidance |
| PTY emits unterminated control bytes | cap retained suffix and scan work | parser counter + PTY integration | harness stays bounded and responsive |
| Reply membership changes concurrently | allow one stale disposable pointer | barrier around observation | durable reply remains; pointer may be stale |
| Coverage config lists but never runs package | gate on known executed lines | coverage-data query | CI fails clearly |

No row may be closed with a mock-call-count test alone. The primary proof must
observe durable state, a real process boundary, or a real supported backend.

## Landing boundaries, parallel lanes, and review cadence

Each numbered packet is a separate commit/PR unless its diff is trivial and
shares exactly the same owner, rollback, and tests as an adjacent packet.

| Packet | Modules | Depends on |
|---|---|---|
| 0 | sibling SimpleBroker core/backends | maintainer publish approval |
| 2 | core messaging/threads | 0 release and A1/A2 promotion |
| 3 | core CLI/watcher | its promotion only |
| 4 | core SQL/PG extension | its promotion; Docker PG |
| 5A | core SQL/CLI corruption | its promotion |
| 5B | core watcher/client lifecycle | its promotion |
| 5C | core SQL/messaging cleanup | 5A if decoder helpers overlap |
| 6 | Summon driver/persona/docs | its promotion |
| 7 | core read API/Summon control | paired core/Summon promotion |
| 8A | core identity/Summon bootstrap | fail-not-adopt promotion |
| 8B | Summon PTY/state/CLI | none beyond its promotion |
| 9A | core notification/messaging/CLI | reply-notification promotion |
| 9B | core thread model/CLI | human-rendering promotion |
| 10 | core and Summon CLI/docs | relevant intentional-contract promotion |
| 11 | release/docs gates | runtime/version facts established |
| 12 | CI/coverage/watcher tests | selector contracts from 11 if changed |
| 13 | agent/docs routing | DOM promotion only |
| 14 | cross-cutting release proof | all packets selected for the release |

Parallel execution:

- Lane A: 0 -> 2. This is the only cross-repo critical chain.
- Lane B: 3 -> 5B. Both touch watcher ownership and should be sequential.
- Lane C: 4 -> 5A -> 5C. These share SQL/state files.
- Lane D: 6 -> 7 -> 8A. These share Summon driver/control lifecycle; 8B may run
  in parallel after 6 if `_state.py` does not conflict.
- Lane E: 9A -> 9B -> 10. These share CLI/models and should be sequential.
- Lane F: 11 -> 12 -> 13. Factual docs changes may start early, but final gates
  wait for runtime packets.

Launch independent lanes in separate worktrees only after each lane's own spec
promotion. Lane A does not block B-F. Merge overlapping core/Summon package
changes before paired-artifact verification. If a diff touches a module owned by
another live lane, serialize or rebase and rerun that module's red/green proof.

After packets 2, 4, 7, 8A, 9A, 13, and 14, give an independent reviewer the
promoted specs, this plan, relevant implementation doc, diff, and targeted test
evidence. The reviewer must answer: "Can this slice be reverted independently,
and did it preserve every named invariant outside its scope?"

## Out of scope

- Authentication, message signing, encryption, per-user ACLs, or prompt-
  injection prevention claims
- A semantic two-agent loop detector
- Automatic membership of parent authors in all subthreads
- Per-device notification queues or claim-then-ack notification persistence
- A unified route-key table or schema migration unless advisory locks fail the
  real PG proof and the plan is explicitly revised
- Redis Taut state support, except verifying the SimpleBroker return contract
- Splitting `SummonDriver`, PTY/stream unification, or generic status schema
- Rewriting all private-state tests or adding YAML dependencies
- Rejecting empty messages or changing exit-2 classes
- Treating local ignored `coverage.xml` as repository work
- Creating a placeholder skill merely to populate `skills/`
- Lesson archival, purge/compaction policy, or a new documentation governance
  lifecycle; the review supplied no measured baseline for that redesign
- Opportunistic refactors outside the exact files and invariants named here

## Deviation log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| Task 11 metadata inventory | Treat a root `VERSION` file as a release source and gate it | No `VERSION` file exists or is created; manifests, `taut/_constants.py`, README pins, and dependency floors are gated | A second version file would be redundant state with no current consumer; creating it only to satisfy the plan violates YAGNI | None; this is a plan-source correction, not a product-spec change |
| Task 9B DM mention action | Render `taut log <source-thread>` for every mention source | Direct execution proved internal `dm.*` names are intentionally invalid `log` operands; DM mentions render bare `taut read`, while channels/subthreads retain `log` | Preserves the DM privacy boundary and makes the advertised action executable | [IAN-6.4] was corrected before completion |
| Task 12 coverage owner | Use pytest-cov invocations plus Coverage's native subprocess patch | Coverage's first full run exposed a corrupt parallel shard and 0% scripted-provider child coverage; CI now uses `python -m coverage run --parallel-mode -m pytest` as the sole owner through the setup-python interpreter where `.[dev]` was installed, and the scripted adapter launches its installed provider module | One coverage owner removes data-file contention; avoiding `uv run` prevents it from creating a runtime-only project environment without Coverage; module launch remains a real child and makes the installed source measurable | No product-spec change; workflow tests and named-line verifier encode the gate |
| Task 14 commit gate | Mark completion only after a commit | Implementation remains intentionally uncommitted because the user did not request a commit | Repository policy forbids committing merely to satisfy the completion gate; handoff reports the exact uncommitted state | None |
| Task 0 step 2 / [TAUT-3.4] | Forced transaction-order test (pause lower-id writer A pre-commit, prove B cannot publish first) for SQLite and Postgres, upstream in SimpleBroker | Not added; upstream keeps the pre-existing `tests/test_write_visibility.py` (sqlite_only) and declines the forced-order test as YAGNI. SQLite ordering is covered probabilistically there; PG ordering has no dedicated forced-order proof | SimpleBroker's atomic write commits id-allocation and row-insert in one transaction, so return-id order equals commit order by construction; the taut-side A2 real-race test exercises the property that matters to taut (a concurrently-committed intervening message blocks the sender advance). The residual PG-only gap is the visibility-ordering guarantee under a paused writer, unproven by a dedicated test | None; if a future backend weakens single-transaction write atomicity, add the forced-order test then |
| Task 2 step 1 / R3 | Dedicated A1 test: pause writer A before publication, let B commit, third caught-up observer reads both in id order | Not added as a separate test. The A1 property (second-publisher receives the later id, no lower id publishes late) is exercised only incidentally by the A2 race test `test_sender_does_not_skip_message_published_during_its_write` | The A1 root cause — a pre-allocated timestamp committing below an advanced cursor — is eliminated structurally by removing the live exact-id insert path entirely (`_write_message` now uses `queue.write` and the returned id), so there is no pre-publication window left for a third observer to expose. The A2 test still exercises real concurrent commit ordering | Low; a dedicated third-observer test would harden against regression if the atomic-write path is ever reworked |
| Task 3 step 6 / Task 2 step 2 | Literal wording: EPIPE firing through the CLI sink on a refresh-added queue; A2 test asserts sender reads B "and not its own post" plus `log` contains both | EPIPE-on-refreshed-queue is proven by raising `StopWatching` directly from the in-process handler (CLI-sink EPIPE→StopWatching proven separately in the pre-existing-membership subprocess test); the A2 test asserts the sender reads `["intervening", "response"]` (own post included) | The promoted [TAUT-7.4] states own posts may reappear in `read` under one high-water cursor, so "not its own post" is inconsistent with the promoted contract; the delivered assertions match the spec. The composed EPIPE coverage exercises the same StopWatching path | None; test-shape substitution, behavior matches promoted spec |

## Execution evidence log

Rows below record verification actually run against the current working tree
and the red-first results retained by each packet owner. Where an aggregate red
command was not retained, the row says so; later acceptance-only additions are
not relabeled as product reds.

| Slice | Red command/result | Green command/result | Commit/baseline | Residual risk |
|---|---|---|---|---|
| Atomic IDs and sender interval (Tasks 0/2/9) | `pytest -n0 tests/test_client.py` with the new write/interleaving tests failed against the pre-write probe; later shared acceptance additions were baseline-green because the behavior was already fixed | Final root coverage lane: `493 passed`; `pytest-pg --fast`: `83` shared + `13` PG-only passed; reply claim/join/leave/race and read-only membership gates included | `06bfc93 + uncommitted worktree` | Redis uses the released SimpleBroker contract but has no Taut sidecar lane in this repository |
| Watch delivery/lifecycle (Tasks 3/5B) | Seven focused watcher/CLI regressions initially failed on missing per-record flush, EPIPE classification, late-queue stop policy, and construction cleanup | Full root lane passed; the formerly flaky late-queue test was corrected to wait for queue installation and passed five repeated focused runs | same | Real EPIPE probe is POSIX-only; Windows retains in-process/reader-thread coverage and CI matrix coverage |
| SQL state and Postgres isolation (Tasks 4/5A/5C) | Corrupt JSON and concurrent route/schema probes failed before strict decoding/advisory locks; exact aggregate red output was not retained | Full Docker gate passed: `83` shared and `13` PG-only; release checks repeated the same result | same | `DELETE ... RETURNING` relies on the supported Python/SQLite and Postgres versions exercised by the matrix |
| Summon framing/audit/bootstrap/PTY (Tasks 6-8) | Focused tests failed on continuation framing, late membership audit, final-name failures, residual recovery, and PTY retention; the independent review added acceptance tests after some behavior was already green | Normal Summon lane `192 passed`; process lane `187 passed`; strict live-harness lane `18 passed`; strict local-LLM lane `6 passed`; real collision exhaustion, post-insert token recovery, leave/rejoin audit, silent bootstrap, and bounded PTY gates passed | same | Provider-specific onboarding remains an external prerequisite outside strict configured release runs |
| Human UX and both CLIs (Tasks 9B/10) | Core CLI packet began with 9 failures and 51 missing help entries; Summon packet began with 6 failures and 20 missing help entries; executable DM action test caught the invalid initial `log dm.*` proposal | Final root/Summon suites and release checks passed; parser inventories, suffix collision, member/nonmember/DM/subthread actions, and no-command exits fire | same | Human text is intentionally additive; JSON records stayed stable except the specified `reply` notification type |
| Release/docs metadata (Tasks 11/13) | Initial metadata/docs packet had 3 stale-pin/sync/path failures plus scanner/reference failures; root Summon wheel mutation later supplied an additional red gate | `63` focused release/metadata/docs tests passed before integration; final root `493` and release checks passed | same | Historical plans retain their historical version text by design |
| Coverage and scheduler proof (Task 12) | First full coverage run exposed pytest-cov/native-patch contention and failed named evidence because `scripted_provider.py` was 0% | Sole-owner rerun: root `493`, Summon `192`/`187`, live `10 passed, 8 skipped` in the non-strict collection, local LLM `5 passed, 1 skipped`; named child/driver/control/CLI lines present; aggregate `91%`. Strict release runs separately passed `18` live + `6` local-LLM | same | Non-strict coverage collection records configured skips; strict release gates prove the available live/provider lanes |
| Final release readiness (Task 14) | Independent implementation review found and reproduced DSN exposure, incomplete CLI help/actions, stale specs/pins, missing shared gates, bootstrap audit pollution, residual creation evidence, and empty evidence log | `ruff`/format clean; mypy `78` files clean; three packages built at `0.5.3`; paired artifact compatibility passed all four cases; `python bin/release.py all --checks-only` ended `Checks passed` without mutations | same | Worktree is uncommitted and therefore not claimed ready to land under repository policy |
| Review remediation: `\r` framing bypass ([SUM-5.2]) | `pytest test_driver.py::test_format_carriage_return_bodies_cannot_escape_indentation` → FAILED (unindented `[system]` line after lone `\r`) | Same test after normalizing `\r\n`/`\r`→`\n` in `_indent_continuation_lines` → passed; `-k "format or injection_round_trip"` → 12 passed | uncommitted, baseline 06bfc93 | None; adapter paste path still maps `\r`→`\n`, now after indentation |
| Review remediation: CLI `join --new` refusal ([IAN-3.3]) | (no prior CLI-level test existed for the occupied-name refusal) | `pytest test_cli.py::test_cli_join_new_refuses_occupied_explicit_name` → passed (exit 1, one stderr line, no traceback, single `van` remains) | uncommitted, baseline 06bfc93 | None |
| CI remediation: control owner-thread fixture ([SUM-9]/[SUM-10]) | GitHub Linux Python 3.13/3.14 repeatedly failed `test_control_loop_constructs_and_closes_persistent_handles_on_owner_thread`: its invented token lost a race to the immediate audit, which correctly raised `TokenError` and closed the reactor | Fixture now creates a real token-selected member before starting the owner thread and retains the published reactor locally before signaling shutdown, so teardown cannot invalidate the request-stop call; the focused xdist test passed 20 consecutive invocations and the complete `not xdist_group` lane passed (`192` tests) | uncommitted, baseline 06bfc93 | Test-only correction; production invalid-token failure semantics are unchanged |
| CI remediation: Coverage interpreter selection (Task 12) | CI raised `ModuleNotFoundError: coverage`; local clean-environment reproduction `uv run --isolated --no-dev python -c 'import coverage'` failed because `uv run` built a runtime-only environment instead of using the setup-python interpreter provisioned by `uv pip install --system -e ".[dev]"` | Workflow now uses `python -m coverage` and direct `python` for the evidence checker; the workflow regression and plain-child subprocess probe pass. A fresh temporary venv installed with the workflow's `.[dev]` + Summon command then ran the core CLI and real first-summon driver under direct `python -m coverage`; combine succeeded and every named child/driver/control/CLI line was present | uncommitted, baseline `c7266dd` | Coverage subprocess startup remains opt-in through the job environment; children without Coverage safely skip the defensive `.pth` hook instead of being made less isolated. Dependency hygiene remains: `pytest-cov>=4.0` does not guarantee the Coverage 7 native-patch floor; changing dependency floors requires maintainer approval |

## Fresh-eyes checklist

- [x] Every task names exact current owners and files.
- [x] Every behavior change has a red test that exercises a real boundary.
- [x] All spec changes are promoted just in time before citing code.
- [x] No task introduces a parallel write, watcher, route, or control path.
- [x] Fatal, recoverable, and best-effort failures remain distinct.
- [x] Rollout and rollback order account for paired packages and mixed writers.
- [x] Rejected findings have a nearby durable explanation or an explicit
      no-change rationale.
- [x] Docs/process cleanup does not delete historical knowledge.
- [x] Full gates use current commands, not copied historical claims.
- [x] Independent review findings are incorporated or answered below.

## GSTACK REVIEW REPORT

### Runs

| Run | Reviewer | Scope | Status |
|---|---|---|---|
| 1 | source-audit agents | original A-E findings against code/spec/tests | complete |
| 2 | plan author | architecture, code quality, tests, performance, scope | issues fixed |
| 3 | external Codex outside voice | hidden assumptions, simpler alternatives, drift | 8 issues reviewed |
| 4 | independent architecture reviewer | concurrency, ownership, rollout, public contracts | issues fixed |
| 5 | independent test reviewer | red-green durability, real boundaries, commands, false-green gates | issues fixed |
| 6 | final architecture/test re-review | revised plan, P0/P1 blockers only | clean after final two corrections |
| 7 | independent completed-work reviewer | assembled runtime, security, docs, tests, coverage, and release gates | findings reproduced and fixed; final behavioral re-review clean |
| 8 | independent final-delta reviewer | sole-owner coverage, module child launch, evidence log, and uncommitted handoff | clean; no blocker or unsupported product claim |
| 9 | independent CI-fixture reviewer | real token setup and owner-thread teardown race | clean after retaining the published reactor locally |
| 10 | independent coverage-CI reviewer | setup-python interpreter selection, child bootstrap safety, workflow regression | clean; direct Coverage floor noted as non-blocking dependency hygiene |

### Findings

| ID | Finding | Disposition | Plan change |
|---|---|---|---|
| R1 | SimpleBroker release falsely blocked unrelated work | accepted, 10/10 | independent workstreams, per-packet promotion, explicit publish/floor gates |
| R2 | Redis ordering would require an out-of-scope Lua redesign | accepted, 10/10 | SQLite/PG ordering proof; Redis exact returned-ID conformance only |
| R3 | A1 red test depended on a seam the fix deletes | accepted, 10/10 | unchanged delegating publication gate plus third observer |
| R4 | Postgres schema lock started after first DDL and route tests missed sites | accepted, 10/10 | lock is first SQL; create/rename/alias deterministic barriers |
| R5 | Dynamic audit used current head, leaked cached handles, and missed both no-DB guards | accepted, 10/10 | active-window cursor math, dedup, cache eviction, open/reopen tests |
| R6 | `join(new=True)` fail-not-adopt was an unpromoted public change | accepted, 10/10 | exact TAUT/IAN delta and side-effect-free collision tests |
| R7 | Direct final-name create overstated atomicity and omitted creator ownership | accepted, 9/10 | per-attempt close/claim ownership and token-based residual recovery |
| R8 | Watch EPIPE test could pass on backlog or after successful target flush | accepted, 10/10 | drain first, close pipe before target, exact-ID cursor assertion, refreshed queue coverage |
| R9 | Coverage and release gates could be green without executing child/release checks | accepted, 10/10 | native child patch probe, isolated lanes, executed-line query, `--checks-only` |
| R10 | Mixed-risk Tasks 5/8/9 were not independently revertible | accepted, 9/10 | split into 5A-C, 8A-B, and 9A-B packets |
| R11 | Human notification “next action” failed for valid nonmember states | accepted, 10/10 | membership-independent `log`; conditional reply suffix; executable operand tests |
| R12 | Broad lesson archive/governance redesign was performative scope growth | rejected from this program, 9/10 | keep content, add topic index, defer redesign pending measured need |
| R13 | Docs scanner would treat instructional examples as live citations | accepted, 9/10 | concrete-citation grammar, example exclusions, scanner self-tests |
| R14 | A5 was being treated as delivery loss rather than pointer loss | original finding rejected as code defect, 10/10 | preserve claim-consume; README/help name durable chat and later notification-worthy activity |

### What already exists and is reused

- SimpleBroker's existing atomic SQL write transaction and Redis write path;
  only the public result is threaded through. No second write API.
- Taut's one high-water cursor, TautWatcher, SqlDialect marker, state owner,
  notification queue, and Summon control thread. The plan extends these owners.
- Existing generation fences, PTY/stream close machines, STATUS projections,
  release selectors, and docs/traceability tests. Rejected split/unification
  proposals are documented instead of rebuilt.

### Review verdict

READY FOR IMPLEMENTATION AS INDEPENDENT PACKETS. Packet 0 publication, the
Taut dependency-floor mutation, and release/tag/push remain explicit maintainer
authority gates. They do not block unrelated packets. No technical or product
choice is left for an implementing engineer to invent mid-task.

NO UNRESOLVED DECISIONS
