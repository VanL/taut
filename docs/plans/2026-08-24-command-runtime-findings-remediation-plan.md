# Command Surface and Runtime Findings Remediation Plan

Class: 5. The work changes the public history-order contract, adds a public
streaming client surface, and changes CLI delivery from pre-materialized output
to incremental output. These are [DOM-5] risky public-contract and
compatibility changes, so the hardening runbook is mandatory.

Plan type: implementation with spec revision.

## Goal

Resolve each independently verified command-surface and runtime finding at its
actual owner. Make unbounded `taut log` use broker-order iteration and bounded
output chunks; retain `TautClient.log()` as the list compatibility surface;
repair the Unicode excerpt bug and repeated inbox rendering work; harden the
unrecognized-caller exit mapping; add an executable grammar-declaration gate;
and make `history_around` use observed broker-adjacent context with bounded
decoding. First obtain and consume a released SimpleBroker contract for
closeable peek-generator lifetime. Preserve the ratified
debug, notification-pointer, mention-fanout, and terminal-policy contracts
where the review proposal conflicts with program theory or current specs.

The endpoint is reviewed code, tests, specs, and implementation notes ready
for an owner-authorized landing. This plan does not authorize a release.

## Finding Register and Decisions

| Finding | Disposition | Required outcome |
|---------|-------------|------------------|
| R1, unbounded `log` | upstream contract, dependency floor, spec revision, and code fix | Broker pending-queue order becomes the explicit history order. Use SimpleBroker 7.4.2's released public close/lifetime contract and coordinated 3.9.2 PostgreSQL backend. Then add a Taut decoding iterator, keep `log()` as a list wrapper, and stream no-limit CLI output in bounded chunks without a full-history sort or list. |
| R2, debug redaction | no action | Preserve [TAUT-13.3.1], program-theory alternative A3, and the existing negative tests. Do not classify `ic_*` claim hashes as secrets or continuity tokens as credentials. |
| R3, mention fanout | spec clarification and contract proof | Preserve independent recipient-specific best-effort writes. Specify and test that a raised middle-recipient write has an outcome-ambiguous delivery boundary, dispatch continues, the source remains successful, and no retry occurs; prove both a pre-write proper subset and write-through-then-raise. Record why one-body `broadcast()` cannot carry recipient-specific mention bodies. |
| R4, exit-code string match | code hardening | Replace exact diagnostic-string matching with an internal `UnrecognizedCallerError(IdentityError)` subtype while preserving public exception compatibility, diagnostics, and exit classes. |
| R5, duplicated command grammar | canonical declaration proof now; derivation deferred | Reflect canonical paths, required child selection, root actions, positionals, options, groups, globals, runtime coercion, and parser policy between the syntax AST and argparse adapters. Explicitly preserve argparse-only unique local and pre-verb root long-option abbreviation plus the reserved Summon compatibility bridge. Do not compare summary prose or build the AST-to-argparse generator in this remediation. |
| R6, inbox claim/render behavior | performance fix; claim order unchanged | Keep claim-before-render. Batch human top-level mention action derivation once per render pass and once per unique source thread instead of repeating workspace and history work per mention. |
| R7, terminal policy discovery | no action | Preserve per-call discovery and immediate edit, deletion, and nearer-config freshness under [TAUT-6.4]. Do not add a stale or ineffective CWD/signature cache. |
| Search excerpt note | code fix | Translate case-folded match positions back to original-string positions before slicing a bounded human excerpt. |
| `history_around` note | spec alignment and bounded decode fix | Make before/after mean rows observed adjacent to the anchor during one authoritative broker-order traversal through SimpleBroker's public generator, retain only bounded raw context, and decode only returned rows. |

New evidence that changes a disposition must enter the Deviation Log before
implementation continues. In particular, neither a hypothetical stronger
security posture nor a hypothetical notification durability goal is evidence
that the ratified current contract changed.

## Source Documents

Governing product and process sources:

- `docs/program-theory.md`, especially [THEORY-5] alternatives A1 and A3
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/lessons.md`
- `docs/lessons.md`, Golden Rules and entries after the coalescing watermark
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-3.5], [TAUT-6.4],
  [TAUT-7.9], [TAUT-8.1], [TAUT-8.3], [TAUT-8.7], [TAUT-13.3.1]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-2.3], [IAN-3.2],
  [IAN-7.2] through [IAN-7.4]
- `docs/specs/06-search.md` [SRCH-5.3]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/09-search-architecture.md`
- `docs/plans/2026-08-17-tui-command-mirror-plan.md`, especially the deferred
  AST-to-argparse migration
- `docs/plans/2026-08-24-extension-seams-process-containment-coverage-plan.md`,
  a concurrent draft that also proposes [TAUT-8.3] and `TautClient` additions;
  promotion and client edits must be rebased and reviewed in an explicit order

Dependency source used to verify the boundary:

- the public `Queue.peek_generator()` and the `broadcast()` method on the
  object returned by public `open_broker()` at the committed minimum, the
  selected lock, and the prerequisite release
- SimpleBroker's public [SB-DELIVERY-4], [SB-DELIVERY-6], [SB-API-1], and
  [SB-API-5] contracts. Version 7.4.1 specified live offset-paged traversal but
  did not promise that `peek_generator()` was closeable. Version 7.4.2 now
  publishes `CloseableIterator`, lazy single-use ownership, and same-thread
  synchronous Queue-operation cleanup. Taut must not import dependency-private
  code

## Spec Baseline

- Original authoring baseline: `0eacc00adf33c0ab8feef46d35b7909c33f8c40e`.
- Dependency-floor commit:
  `a470f8abe28f314c83b1458d916cfa1d91327a16` (`Upgrade SimpleBroker to
  7.4.2`).
- Post-E1 execution/rebase baseline:
  `d5e3be2be15dc909bb73001443df399c967ec50a`
  (`Add public extension activity seams`). The exact overlapping owner blobs
  are `docs/specs/02-taut-core.md`
  `c47e8af502a3c81122b71d507ab142e3864b653a`,
  `docs/specs/03-identity-addressing-notifications.md`
  `548591d6f2c30e76212858d884df3db9fff6bb6a`,
  `taut/client/_base.py` `e2e8bafce37100936bfdd3bfb7265a0f0ef8b49e`,
  and `tests/test_shared_contract.py`
  `b50aa0d3f35b7e75012536cc968380f9569f2592`.
- Authoring content identities:
  - `docs/specs/02-taut-core.md` blob
    `4c835e46f950a95f2cb6856943b67c37072d57d7`
  - `docs/specs/03-identity-addressing-notifications.md` blob
    `362f6c5522d5769f9a2fb5da3b1be3d6eb0da896`
  - `docs/specs/06-search.md` blob
    `d22d111b38231e23638e8801e08f4bd8eeeacaa7`
- Promotion baseline: pending. After the reviewed spec-promotion slice, record
  either its commit SHA or the repository baseline plus exact promoted spec
  blob identities and passing documentation gates.
- Dependency history: committed Taut required SimpleBroker `>=7.3.2`; the first
  unlanded floor refresh selected `7.4.1`. Immutable
  SimpleBroker refs `v7.3.2` (`284059c11c14e82b65cad61cd349beffffc8addb`)
  and `v7.4.1` (`36bc6d4d0c079928ef051ea7129c78245c2ee058`)
  specify live offset-paged traversal but not closeable peek-generator lease
  release.
- Dependency prerequisite satisfied 2026-08-25: SimpleBroker `v7.4.2`
  (`b8cfa509f8eb373b44416dedbc327b0e66530679`) publishes the reviewed public
  contract, typing, and real SQLite/PostgreSQL proof. PyPI artifact SHA-256:
  wheel `98e777d18f5ba4dbf9a1b2e133040373d5e2f70a0154b2cff907ea51b39cfd0b`;
  sdist `6a85b2ae01305089b083fba3027178b7410689bc03ce10f0493f99124f4f3496`.
  Coordinated SimpleBroker-PG `3.9.2` requires core `>=7.4.2`; artifact SHA-256:
  wheel `36655149d75685dbfd2e78c4c5ee77029d769f50e261bde5993cf7f1a3e4aa38`;
  sdist `1689baabe35ee9bbe4daeef2d79d1465c4af71bbdda6ef94e0fb59eb7fb6d676`.
  Taut's minimums and maintained locks select that pair. The checkout-free
  exact-minimum `iter_log()` lifetime proof remains due after Slice 2.

## Proposed Spec Delta

Promotion strategy: **A, in-file text before link claims**. Promote the
history-order, closeable live-stream, exact-context, grammar-migration, and
mention-fanout requirements in the active specs before code. Add reciprocal
implementation mappings only with code and tests. The promoted text plus the
history/CLI implementation form one publication unit and must not land or
release separately.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A | [TAUT-3.4], [TAUT-7.9], [TAUT-8.1], [TAUT-8.3], [TAUT-8.7], Related Plans |
| `docs/specs/03-identity-addressing-notifications.md` | A | [IAN-7.3], Related Plans |
| `docs/specs/06-search.md` | A, backlink only | Related Plans |

### [TAUT-3.4] broker-order history

Insert after the bullet beginning “Taut must tolerate foreign writes”:

> Pending chat history preserves SimpleBroker queue iteration order. Taut does
> not reorder pending rows by message id. For ordinary Taut-authored live writes,
> [TAUT-3.5] makes queue order and timestamp order coincide. Import and restore
> operations own the order in which they insert exact-id rows. Foreign or
> deliberately out-of-order exact-id writes remain readable in their broker
> order but are not normalized by Taut; a backdated row may remain outside an
> already-advanced timestamp cursor or `since` filter. Tolerance means that a
> foreign body or queue does not break Taut, not that Taut repairs its ordering
> or cursor visibility.

### [TAUT-8.1] `log` row

Replace the `log` table row with:

> | `log THREAD_OR_DM [--since TS] [--limit N]` | Show cursor-neutral pending
> history in SimpleBroker queue order. Ordinary Taut live writes therefore
> appear chronologically. A DM may be `@name-or-alias` or a stable `dm.d_*`
> handle and requires actor access under [IAN-5.3]. `--limit N` selects the
> final N matching rows observed by [TAUT-8.3]'s live traversal, in queue order.
> Without `--limit`, the CLI renders the history incrementally without
> retaining the complete result. Each successful
> NDJSON record write is flushed before the next row is requested; human output
> uses bounded render chunks, flushes after each chunk, and may recompute
> presentation-only sender padding at chunk boundaries. A late read or render
> failure leaves complete prior records. An output-transport failure or process
> termination may additionally truncate the record being written. A nonzero
> exit means every visible prefix is incomplete as an operation result. Quiet
> mode still exhausts the stream with constant Taut-owned decoded retention so
> late read failures keep their existing exit behavior. | 0; 1 error; 2 empty /
> unrecognized member / inaccessible conversation |

### [TAUT-8.3] public history iterator

Insert after the unread method signatures:

> The history signatures are
> `TautClient.iter_log(thread: str, *, since: str | int | None = None,
> limit: int | None = None) -> Generator[Message, None, None]` and
> `TautClient.log(thread: str, *, since: str | int | None = None,
> limit: int | None = None) -> list[Message]`. `iter_log()` performs selector,
> visibility, filter, and limit validation before returning one closeable,
> single-use generator. The generator borrows one ephemeral queue operation;
> creating it enters no broker iteration. Its first advancement establishes the
> stream owner thread. After that point, callers must advance, exhaust, or call
> `close()` on that same thread and must finish before closing the client.
> Closing before first advancement enters no broker operation, makes the
> single-use generator terminal, and causes later advancement to raise
> `StopIteration`. Cross-thread advancement or active close is unsupported.
> Taut's outer generator
> closes the inner SimpleBroker iterator in `finally`, and every Taut-owned
> consumer closes on quiet, output-error, and other early-exit paths on its
> advancing thread. The generator yields decoded pending rows in [TAUT-3.4]
> broker order and yields no rows for an empty selection.
>
> Every traversal, including `limit=N`, inherits SimpleBroker's live offset-
> paged view. It is not a snapshot or an exhaustive-concurrent-traversal
> promise: rows inserted during iteration may appear, while concurrent claim,
> deletion, or movement may cause rows to be skipped. Sustained insertion may
> prevent exhaustion. Callers requiring a complete stable traversal must
> quiesce mutation. Taut adds no rescan, deduplication, or snapshot layer. With
> no limit, Taut retains no decoded full-history collection. With `limit=N`,
> it decodes every matching row observed by that live traversal, performs
> O(total observed matching rows) broker reads, and retains O(limit) decoded
> rows before yielding the final N observed rows, until SimpleBroker exposes a
> portable reverse pending iterator. `log()` is the compatibility wrapper: it
> exhausts and closes `iter_log()`, returns the same queue-ordered list, and
> raises the existing `EmptyResultError("empty")` when the generator yields
> nothing.
>
> Taut preserves an active traversal, decode, or consumer failure when cleanup
> also fails and attaches the cleanup failure as secondary diagnostic context.
> A cleanup failure with no active primary failure is fatal. Taut-owned
> consumers apply the same precedence; cleanup never silently replaces the
> operation failure that caused it.

### [TAUT-7.9] broker-adjacent context

Replace the first paragraph under [TAUT-7.9] with:

> `TautClient.history_around(thread: str, msg_id: str, *, before: int = 25,
> after: int = 25) -> list[Message]` returns the exact pending anchor plus the
> nearest rows observed adjacent to it on either side during one [TAUT-3.4]
> broker-order traversal. The returned page preserves that observed queue
> order. It is the
> embedding seam for opening a search result or otherwise placing an exact
> message in bounded history without applying `show_message`'s read transition.

Replace the final paragraph under [TAUT-7.9] with:

> `history_around()` validates the exact anchor through a public exact peek,
> then walks one public SimpleBroker pending generator in broker order,
> retaining at most `before` raw predecessor rows and stopping after `after`
> successor rows. It
> decodes only the returned bounded page. The traversal inherits [TAUT-8.3]'s
> live, non-snapshot limitation: concurrent mutation may skip the still-present
> anchor or a neighbor because offsets shift. Any scan that does not observe
> the validated anchor produces the ordinary exact miss. No cursor or claim
> state moves.

### [TAUT-8.7] compatibility-era declaration parity

Insert after the paragraph stating that the CLI parser and an approved mirror
consume the syntax contract:

> During the version-1 compatibility migration, hand-written argparse adapters
> remain the CLI parsing owner. “Consume” requires canonical declaration
> equivalence, enforced by structural reflection over command paths, required
> child selection, root actions, positionals, options, exclusivity, globals,
> and parser policy. The reflected value field is runtime coercion: AST
> `PATH` and `STRING` both correspond to argparse's uncoerced string input,
> while `INTEGER` corresponds to `type=int`. `PATH` remains mirror-only
> presentation metadata checked by AST construction tests. The syntax AST does
> not own root-help summary prose, metavars, exact argparse diagnostics, or
> argparse's released unique command-local and pre-verb root long-option
> abbreviations. The CLI may accept such an abbreviation while a mirror rejects
> every undeclared spelling; abbreviated post-verb globals remain invalid. The
> reserved no-extension `summon`/`dismiss` remainder bridge is a compatibility
> transport, not a mirrored command grammar. Direct AST-to-argparse
> construction remains a separately reviewed migration.

### [IAN-7.3] recipient-specific mention failure

Insert after the paragraph ending “rewrite history”:

> A multi-recipient mention uses independent recipient-specific writes because
> each body carries its own `to_id` and `matched` values. A raised write records
> a warning when the surface permits and dispatch continues to later
> recipients. The source operation remains successful. The raised recipient
> write has an outcome-ambiguous delivery boundary: it may have committed
> before raising. Taut does not retry or repair the result, so successful and
> ambiguous writes may leave a proper subset. Process termination during the
> loop may likewise leave a subset, without a delivery receipt. This best-
> effort behavior is distinct from reaction fanout's identical-body atomic
> broadcast.

### Related Plans backlink

Add to each touched spec:

> - `docs/plans/2026-08-24-command-runtime-findings-remediation-plan.md` —
>   broker-order streaming history, command-grammar and exit hardening, bounded
>   inbox/history work, and search-excerpt correction after independent runtime
>   review.

## Context and Key Files

| Area | Current owner and important behavior | Files to change or verify |
|------|--------------------------------------|---------------------------|
| History API | `MessagingMixin.log()` validates visibility, iterates a public broker generator, retains all rows or a bounded tail, then sorts and returns a list. | `taut/client/_messaging.py`, `taut/client/__init__.py`, `taut/__init__.py`, `tests/test_client.py`, `tests/test_shared_contract.py` |
| Log command and rendering | `LogCommand.run()` calls the list API. `emit_messages()` groups a complete list and computes one sender width over each full group. | `taut/commands/log.py`, `taut/commands/_rendering.py`, `tests/test_cli.py`, `tests/test_command_registry.py`, `tests/test_cli_probes.py` |
| Notification action rendering | `emit_notifications()` calls `_mention_reply_id()` once per mention. Each eligible top-level mention repeats membership, all-thread, exact-source, and recent-history work. | `taut/commands/_rendering.py`, `tests/test_cli.py`, `tests/test_command_registry.py` |
| Notification delivery | `_write_mention_notifications()` emits recipient-specific payloads through `_write_notification()`. Reaction fanout can broadcast only because its body omits `to_id`. | `taut/client/_messaging.py`, `taut/client/_notifications.py`, `tests/test_client.py`, `docs/implementation/04-taut-architecture.md` |
| Identity exit class | Four unrecognized-caller sites raise general `IdentityError`; dispatch recognizes one diagnostic string. | `taut/_exceptions.py`, `taut/client/_identity.py`, `taut/client/_base.py`, `taut/commands/_dispatch.py`, `tests/test_client.py`, `tests/test_command_registry.py`, `tests/test_cli.py` |
| Command grammar | `syntax.py` owns the mirror AST while core and Summon adapters still configure argparse. Example tests do not prove structural parity. | `taut/commands/syntax.py`, `taut/commands/_builtins.py`, `taut/commands/_dispatch.py`, every core adapter under `taut/commands/`, `tests/test_command_syntax.py`, `extensions/taut_summon/taut_summon/command_syntax.py`, `extensions/taut_summon/taut_summon/commands/`, extension tests |
| Search excerpt | `_search_excerpt()` searches a case-folded copy and slices the original with the folded offset. | `taut/commands/_rendering.py`, `tests/test_cli.py`, `tests/test_search_cli.py`, `docs/implementation/09-search-architecture.md` |
| Exact history context | `history_around()` currently selects by timestamp filters, decodes every predecessor, and assumes timestamp and broker order coincide. The new contract makes adjacency observed during one physical traversal explicit. | `taut/client/_messaging.py`, `tests/test_client.py`, `tests/test_shared_contract.py`, `docs/implementation/04-taut-architecture.md` |
| Intentionally unchanged policy | Debug redaction, claim-before-render, and per-line terminal-policy discovery already have explicit specs and firing tests. | `taut/_redact.py`, `taut/debug.py`, `taut/terminal.py`, `tests/test_redact.py`, `tests/test_debug_capture.py`, `tests/test_terminal_text.py` |

### Required comprehension gate

Before the spec-promotion slice, the implementer records answers in the
Implementation Log. An incorrect or missing answer blocks code work until the
cited owner is reread.

1. **What owns history order?** Expected answer: SimpleBroker pending queue
   iteration order. [TAUT-3.5] proves ordinary live Taut writes align queue and
   timestamp order; Taut does not normalize deliberate exact-id insertion.
2. **Which API remains materializing?** Expected answer: public
   `TautClient.log()` for compatibility. The new `iter_log()` and the CLI
   no-limit path are streaming; `limit=N` decodes every matching row observed
   by its live traversal, performs O(total observed matching rows) broker reads,
   and retains O(limit) decoded rows until a reverse broker API exists.
3. **Who closes a partial history stream?** Expected answer: the caller that
   does not exhaust it, on the thread that first advanced it. The public return
   is a closeable generator; first advancement establishes owner-thread
   affinity; the outer generator closes the inner SimpleBroker iterator in
   `finally`; every Taut-owned early exit uses same-thread explicit closing
   before client close. Closing before first advancement is terminal and enters
   no broker operation.
4. **What new failure boundary does streaming introduce?** Expected answer: a
   late broker, decoding, terminal-policy, or output failure can occur after a
   flushed prefix is visible. Prior successful record writes are complete, but
   transport failure may truncate the record being written. The nonzero exit
   marks the operation incomplete.
5. **What concurrency does `iter_log()` promise?** Expected answer: every
   traversal, limited or unlimited, has only SimpleBroker's live offset-paged
   behavior. It is not a snapshot; concurrent mutation can add visible rows,
   cause skips, or under sustained insertion prevent exhaustion. Stable
   completeness requires quiescence.
6. **Why is mention fanout not changed to `broadcast()`?** Expected answer:
   current `broadcast()` accepts one body, while mention payloads contain
   recipient-specific `to_id` and `matched`; notifications are auxiliary
   best-effort pointers and source success remains primary.
7. **Why does inbox still claim before rendering?** Expected answer: [IAN-7.4]
   intentionally uses consumptive broker reads. Rendering before claim would
   require a new acknowledgement and concurrency contract and could duplicate
   display.
8. **What does the grammar gate own?** Expected answer: canonical declaration
   parity while argparse remains the compatibility owner, including root
   actions and required child selection. It compares runtime coercion, treating
   AST `PATH` and `STRING` as argparse strings. It excludes summary prose and
   exact diagnostics, and explicitly pins argparse-only local and pre-verb root
   option abbreviations plus the no-extension Summon remainder bridge as
   intentional differences. Tests may load adapters; ordinary syntax-only
   startup may not.

## Invariants and Constraints

- `TautClient.log()` keeps its signature, list return type, visibility rules,
  empty-result exception, cursor neutrality, tolerant decoding, and DM display
  label behavior. Its only intended ordering change is for deliberately
  out-of-order underlying rows.
- `iter_log()` and `log()` share one selector, visibility, filter, and decoding
  implementation. Do not create two history-validation paths.
- `iter_log()` validates before returning a closeable generator. That generator
  owns deterministic close propagation to the inner SimpleBroker iterator.
  Creating it enters no broker iteration; first advancement establishes its
  owner thread. Every later advance, exhaustion, or close is on that same
  thread. Closing before first advancement enters no broker operation and makes
  the generator terminal. Taut-owned consumers exhaust or close it on the
  advancing thread before client shutdown; abandoned or cross-thread-used
  public generators are caller misuse, not a garbage-collection cleanup plan.
- Every limited or unlimited iteration is a live offset-paged view, not a
  snapshot. Do not add a rescan, deduplication set, copied database, or
  completeness claim under concurrent mutation. Sustained insertion may keep
  either form live indefinitely.
- No-limit CLI history must not retain the complete decoded history or sort it.
  The log renderer owns `_LOG_RENDER_CHUNK_MAX_MESSAGES = 64` and
  `_LOG_RENDER_CHUNK_MAX_CHARS = 262_144`. The character counter is
  `sum(len(message.text))` over messages retained in the active chunk; escaped
  or fully rendered output length does not define this decoded-retention bound.
  The renderer may admit one oversized message and retain at most one separate
  lookahead item. An unbounded grouping or width prepass is forbidden.
- `--limit N` means the final N matching broker-order rows observed by that
  live traversal. Preserve the existing decoder-failure surface by decoding
  every observed matching row and retaining the O(limit) decoded tail; broker
  reads are O(total observed matching rows).
- Human log output prints one thread heading, computes sender padding per
  bounded chunk, and flushes after each chunk. JSON keeps the same schema,
  writes one serialized record at a time, and flushes each successful record.
- Exit 2 for an empty log remains exact in human, JSON, and quiet modes. Quiet
  mode exhausts and closes the stream with constant decoded retention so a
  late broker or decode failure keeps its current exit behavior.
- A late streaming failure is fatal. Successful prior writes are not retracted;
  an output failure may truncate the record in progress. Do not buffer the
  whole operation to recover the old all-or-nothing presentation property.
- When an operation and generator cleanup both fail, preserve the active
  operation failure and attach the cleanup failure as secondary diagnostic
  context. A close-only failure is fatal. This precedence applies inside the
  public outer generator and at every Taut-owned consumption boundary.
- `UnrecognizedCallerError` remains an `IdentityError`. Existing callers that
  catch `IdentityError`, the diagnostic `unrecognized caller`, and all other
  exception-to-exit mappings remain compatible.
- The grammar declaration comparison normalizes representation differences,
  especially an
  absent false-valued mirror option versus argparse's stored `False`. It must
  not compare summary/help prose, metavars, exact diagnostics, abbreviation
  acceptance, or private argparse object identity.
- The grammar test must not be imported by production discovery. Lazy adapter
  and syntax-provider startup isolation remains unchanged.
- Inbox optimization changes neither claim timing nor notification output.
  JSON, quiet, DM, sub-thread, missing-source, left-channel, and suffix-
  collision behavior remain exact. The expensive human top-level-channel work
  is once per pass or once per unique source thread, never once per mention.
- Batching may reduce incidental repeated activity touches to one pass-level
  touch. Exact touch count is not a public contract; source chat cursors,
  notification claim state, and rendered order remain the observable gates.
- Mention notification writes remain recipient-specific and best-effort. A
  raised notification write may have committed before raising, cannot roll
  back or downgrade the source message, and is not retried.
- Search hits, ranking, JSON text, and terminal escaping remain unchanged. Only
  the human excerpt anchor is corrected for length-changing Unicode folds. A
  folded offset inside a multi-character expansion maps to the original code
  point whose folded span contains that offset.
- `history_around()` returns the exact anchor and rows observed adjacent to it
  during one broker-order traversal, moves no cursor, claims nothing, and
  decodes only the bounded returned page. Concurrent offset shifts may skip a
  still-present anchor or neighbor; an unobserved validated anchor is the
  ordinary exact miss. Do not add timestamp sorting or direct SQL.
- Debug redaction and terminal-policy resolution receive no runtime edits in
  this plan. Their existing negative and freshness tests remain regression
  gates.
- Other than the prerequisite SimpleBroker close-contract floor, no new
  dependency, persistence field, background task, retry loop, cache, broker-
  private import, or SQL against SimpleBroker-owned tables is authorized.

## Rollout, Rollback, and Operational Signals

The concurrent
`2026-08-24-extension-seams-process-containment-coverage-plan.md` E1 public-
API/spec slice is the first shared-owner slice. Its immutable identifier and
overlapping owner blobs are recorded in the Spec Baseline above. Rebase this
plan's spec/code baseline over its [TAUT-8.3], `TautClient`,
`_base.py`, shared-contract-test, and Related Plans edits, and rerun plan review
before this plan edits a shared owner. The extension plan carries the reciprocal
serialization gate. Neither plan may overwrite the other's public methods,
tests, spec paragraphs, or backlink.

The upstream SimpleBroker close-contract release and Taut floor update are
complete and recorded in the Spec Baseline and Implementation Log. The E1
shared-owner baseline is also complete; repeat review remains the final gate
before this plan's spec promotion.

After those prerequisites, promote this plan's reviewed spec text first in the
implementation worktree. The promotion plus history iterator, exact-context
change, and streaming CLI are contiguous Slices 1 through 3 and form one
atomic publication unit even though red/green checkpoints remain separate.
Then land targeted runtime corrections, the grammar declaration gate, and
traceability reconciliation. Independent review repeats after the history/CLI
unit, after runtime corrections, and after the grammar unit.

There is no storage migration or one-way data change. Rollback follows
dependencies:

1. CLI streaming may be reverted while retaining `iter_log()` and broker-order
   `log()`; remove only this plan's incremental-render, flush, and partial-
   output text from [TAUT-8.1].
2. `iter_log()` rollback first removes CLI use, then removes only this plan's
   history-iterator paragraph from [TAUT-8.3]. `history_around()` already owns
   its direct public SimpleBroker traversal and may remain. Never remove the
   extension plan's `peek_identity()` or `notification_activity_queue()`
   additions.
3. Broker-order-authority rollback removes dependent log/context behavior and
   only this plan's broker-order text in [TAUT-3.4], [TAUT-7.9], and the
   remaining broker-order/final-N parts of [TAUT-8.1]. It does not revert an
   unrelated [TAUT-8.3] addition.
4. The SimpleBroker floor may be lowered only after every remaining Taut
   consumer no longer relies on the released close contract.
5. Runtime correction and grammar slices are independently revertible with
   their tests and owned spec/implementation text.

The old `log()` signature remains throughout, so no staged consumer migration
is required.

Post-landing success signals are: a large no-limit CLI log begins emitting
before the broker iterator is exhausted and the pipe receives a flush; decoded
memory does not grow with total no-limit history; deliberate exact-id fixtures
appear in broker order;
50 same-thread human mentions perform one membership/thread snapshot and one
recent-history scan; and existing terminal freshness and debug negative tests
remain green. No new telemetry surface is required.

Stop and re-plan if SimpleBroker 7.4.2 fails its released close contract in
Taut's exact-minimum integration proof, if close propagation cannot be proven
with real handles, if human output cannot stay within the dual chunk bounds,
if parser reflection requires a production import cycle, or if batching mention
actions changes claim or cursor state.

## Dependency-Ordered Implementation Slices

Every behavior change starts with a failing regression test. A proof-only test
for already-specified behavior records that it starts green and names the
contract it closes; it is not misreported as red-green TDD.

### Slice 0: upstream close contract, release, floor, and shared-owner order

1. In the SimpleBroker repository, create and independently review the required
   public-contract plan. The exact contract must say that the object returned by
   `Queue.peek_generator()` is closeable; exhaustion or explicit early
   `close()` synchronously exits the active queue operation and releases its
   connection/operation lease; and a caller that may stop early owns `close()`.
   Update the public return typing so consumers need no private cast or
   implementation assumption.
2. Add real SQLite and PostgreSQL firing tests for exhaustion, early close,
   iteration failure, and close-only failure. Include a typing/API contract
   test. Preserve [SB-DELIVERY-4]'s live offset-paged semantics; do not turn
   peek into a snapshot or transactional claim stream.
3. Run SimpleBroker's required release gates, publish the reviewed release, and
   record its immutable tag, commit, wheel/sdist hashes, and exact public spec
   references in this plan. An unreleased branch or local editable checkout
   does not satisfy the prerequisite.
4. Raise Taut's SimpleBroker minimum in `pyproject.toml` and synchronized README
   claims to the released close-contract version; update `uv.lock` to that exact
   selected release. Build a Taut wheel, install it with the exact minimum
   SimpleBroker artifact in a checkout-free temporary environment, and run the
   focused public `iter_log()` lifetime tests there after Slice 2. Also run the
   normal selected-lock gates. Record both installed version reports. The floor
   update landed at `a470f8abe28f314c83b1458d916cfa1d91327a16`.
5. Let the extension-seams plan's E1 public-API/spec slice land before this
   plan's subsequent shared-owner behavioral edits. Its immutable identifier is
   `d5e3be2be15dc909bb73001443df399c967ec50a`. Rebase this plan over the
   released dependency and E1 commits, then rerun the complete plan/delta review
   before shared edits.

Done signal: a released dependency contract, immutable artifact evidence,
reciprocal plan order, and Taut minimum/lock make deterministic close a public
dependency fact rather than an implementation inference.

### Slice 1: independent review and spec promotion

1. Independently review this plan, the exact Proposed Spec Delta, all named
   code paths, the no-action dispositions for R2 and R7, and the explicit
   best-effort clarification for R3.
2. Verify the Slice 0 identifiers, reciprocal shared-owner order, and public
   traversal/close semantics at both Taut's new released minimum and selected
   lock. A mismatch blocks promotion.
3. Apply the exact [TAUT-3.4], [TAUT-7.9], [TAUT-8.1], [TAUT-8.3], [TAUT-8.7],
   and [IAN-7.3] text with Related Plans backlinks. Do not add implementation-
   link claims yet.
4. Run the documentation, plan-index, path, and whitespace gates. Record the
   promotion baseline identifier in this plan.
5. Stop if review finds that SimpleBroker queue iteration is not the intended
   visible order for ordinary Taut writes or that exact-id restore cannot own
   insertion order.

Done signal: promoted text and backlinks pass documentation gates; the
promotion baseline is recorded; no code cites unpromoted requirements.

### Slice 2: broker-order iterator and list compatibility

1. In `tests/test_client.py`, add failing public-client tests for:
   - `iter_log()` yielding ordinary and deliberately out-of-order exact-id rows
     in public broker iteration order;
   - `log()` returning the same ordered list;
   - an empty iterator yielding no rows while `log()` retains
     `EmptyResultError("empty")`;
   - `limit=N` choosing the final N matching queue-order rows without sorting;
   - `since`, DM selectors, validation, tolerant foreign bodies, and cursor
     neutrality remaining shared rather than forked;
   - invalid selector, `since`, and limit failures occurring at the
     `iter_log()` call rather than first `next()`;
   - exhaustion and explicit `close()` releasing the inner generator and real
     SQLite operation lease on the same thread that first advanced it;
   - close before first advancement entering no broker operation, making the
     stream terminal, and causing later `next()` to raise `StopIteration`;
   - a recording iterator proving every Taut-owned advance, exhaustion, and
     early close stays on one owner thread; cross-thread use is not supported;
   - a deterministic page-boundary live append showing that the stream is not
     a snapshot in both unlimited and `limit=N` paths, without claiming
     exhaustive concurrent traversal;
   - a primary decode failure plus a failing inner close preserving the decode
     failure with cleanup as secondary context, and a close-only failure
     remaining fatal.
2. Refactor `MessagingMixin.log()` into one eager validation/selection owner
   plus a closeable `Generator[Message, None, None]`. Expose `iter_log()` on
   `TautClient`, close the inner broker generator in `finally`, and keep
   `log()` as the exhausting list/empty-error wrapper. Do not hand an active
   iterator to a worker, finalizer, or background cleanup thread.
3. For `limit=None`, yield decoded rows as the broker generator advances. For
   `limit=N`, decode every observed matching row and retain the decoded tail in
   one bounded deque, then yield that tail in observed queue order. This
   preserves excluded-row decoder failures. Do not call `sorted()`.
4. Update typing only where the method signature requires it. A second stream
   class or context manager is out of scope; failure to prove generator
   `close()` propagation triggers re-planning.
5. Test caller misuse explicitly: closing the client before the generator is
   exhausted is unsupported; the supported obligation is exhaust-or-close
   before client close.
6. Add failing `history_around()` regressions with deliberately out-of-order
   exact IDs before and after the anchor in physical insertion order. Require
   the rows observed adjacent to the anchor, not timestamp-nearest rows. Add a
   second real queue with more than 100 predecessors and `before=1`; the
   decoder runs only for the retained predecessor, anchor, and requested
   successors.
7. Add two controlled-race tests around real queue operations: remove the
   anchor after exact validation but before scan, and delete an earlier row at
   a page boundary so offsets skip a still-present anchor. Both scans that do
   not observe the validated anchor raise the ordinary exact miss and leave
   cursor/claim state unchanged.
8. After exact-anchor validation, scan one public SimpleBroker
   `Queue.peek_generator()` from the start, maintain a bounded raw predecessor
   deque, identify the anchor by exact ID, collect the requested raw successors,
   then stop and close. Do not route the scan through decoded `iter_log()`.
   Decode only the returned page. Do not use timestamp before/after filters,
   sort by ID, query direct SQL, or claim stable adjacency under concurrent
   mutation.
9. Update `docs/implementation/04-taut-architecture.md` with broker-order,
   bounded-decode, observed-adjacency, and close/failure-precedence rationale.
10. Run focused client and shared-contract tests at the selected lock and in
    Slice 0's checkout-free exact-minimum environment.

Done signal: the new iterator and old list API share validation and decoding;
out-of-order fixtures prove broker order; no-limit iteration has no full-
history collection; exact context decodes only its observed bounded page.

### Slice 3: chunked CLI log output

1. Add failing renderer/command tests proving:
   - no-limit human output writes the first bounded chunk before a sentinel
     iterator permits exhaustion;
   - no-limit JSON writes and flushes each successful record before requesting
     the next;
   - human output flushes after each chunk and the renderer retains at most 64
     messages, `sum(len(message.text)) <= 262_144` for an ordinary active
     chunk, one oversized message, and one separate lookahead;
   - one heading is emitted and human sender alignment is correct inside each
     chunk;
   - empty human, JSON, and quiet commands still exit 2 with the existing
     diagnostic contract;
   - quiet mode exhausts and closes with O(1) Taut-owned decoded retention and
     still surfaces a late iterator failure;
   - an iterator failure after one record produces a nonzero command result,
     preserves complete prior records, and emits no traceback;
   - an iterator/output primary failure plus generator-close failure preserves
     the primary with close as secondary diagnostic context, while a close-only
     failure is fatal;
   - a controlled output transport can accept part of the next record and fail,
     proving that the final record may be truncated while prior flushed records
     remain complete.
2. Add one log-specific iterable renderer in
   `taut/commands/_rendering.py`. Keep `emit_messages()` for existing bounded
   read and other list call sites unless a shared iterable core reduces code
   without changing their grouping behavior.
3. Change `LogCommand.run()` to consume `client.iter_log()` and map an empty
   stream to the existing exit-2 path. Use an explicit cleanup helper or
   `try/finally` that preserves the active primary error and attaches a cleanup
   error; raw `contextlib.closing()` is insufficient if its exit path replaces
   the primary. Every success, quiet return, and exception closes the generator
   before `CommandContext` closes the client. Do not materialize merely to reuse
   `emit_messages()`.
4. Update command description/help from unconditional “chronological” wording
   to broker-order wording that explains ordinary chronological writes without
   teaching foreign-write internals in root help.
5. Add a real SQLite CLI regression with exact IDs inserted out of order. The
   CLI must emit queue order in both human and JSON modes.
6. Run the applicable adversarial CLI probes: exact exit class, no traceback,
   complete successfully flushed NDJSON records, a permitted truncated final
   record on transport failure, and default invocation. Use a flush-sensitive
   stream plus a blocked sentinel iterator as the automated proof; retain a
   real subprocess pipe as manual acceptance. Record that partial prefix output
   on a late failure is the promoted contract, not a failed no-partial-output
   invariant.

Done signal: no-limit CLI output is incremental and bounded; list API
compatibility remains; help and spec wording agree.

Independent checkpoint: a fresh reviewer verifies close propagation, live-view
wording, pipe-visible flushes, truncated-final-record handling, rollback order,
and the atomic publication unit before later slices build on history behavior.

### Slice 4: identity exit hardening

1. Add a failing mapper test demonstrating that an unrecognized-caller subtype
   maps to exit 2 independently of diagnostic text. Add negative controls for
   general `IdentityError`, `TokenError`, and `NotFoundError`.
2. Add internal `UnrecognizedCallerError(IdentityError)` in
   `taut/_exceptions.py`; do not add a root public export.
3. Raise it at every current exact semantic site in `taut/client/_identity.py`
   and `taut/client/_base.py`. Map it by type in `_dispatch.py`.
4. Preserve the current `unrecognized caller` text and existing client tests
   that catch the broader `IdentityError`.

Done signal: arbitrary subtype wording still yields exit 2, all broader catch
sites pass, and no other exit mapping moves.

### Slice 5: batched mention action derivation and accepted fanout proof

1. Add a failing real-client human-rendering test with 50 top-level-channel
   mention pointers in one source thread. Instrument the real public methods
   around real SQLite state and require one joined-membership snapshot, one
   all-thread snapshot, one recent-history traversal for that source thread,
   and one exact source check per distinct source ID.
2. Add cases for multiple source threads, duplicate source IDs, deleted/stale
   sources, a valid source older than the 1,000-row suffix window, suffix
   collision, a left channel, sub-thread mention, DM mention, JSON, and quiet.
   Add a real-dispatch batch-preparation failure after claim: pointers remain
   consumed, source chat cursors do not move, and no stale partial action is
   rendered.
3. Replace per-notification `_mention_reply_id()` state traversal with one
   renderer-owned batch preparation pass. Resolve membership and registered
   thread metadata once, group eligible mentions by source thread, load each
   recent suffix window once, and calculate each distinct message's suffix
   from the shared ID set. Preserve output order.
4. Do not move this presentation-derived action policy into a new public client
   API. Stop if the renderer must inspect private sidecar state or if caching
   survives beyond one `emit_notifications()` call.
5. Add a green-at-baseline contract-proof test for [IAN-7.3] with one actor and
   at least three mentioned recipients. Inject a pre-write failure only for the
   middle recipient's notification write. Require the first and third pointers,
   no middle pointer in this controlled proper-subset case, a readable source
   message, successful source result, one warning, continued dispatch, and no
   retry. Keep the real source queue and state; control only the failing write
   seam.
6. Add a write-through-then-raise middle-recipient test. Require the middle
   pointer to exist despite the warning, later dispatch to continue, the source
   to remain successful, and no retry. This proves that a raised write is
   outcome-ambiguous rather than evidence of nondelivery.
7. Update `docs/implementation/04-taut-architecture.md` to record both the
   per-render batch boundary and the reason mention bodies cannot use the
   one-body reaction broadcast API.

Done signal: output and claim semantics are unchanged; expensive work scales
with the pass and unique source threads rather than mention count; the accepted
best-effort delivery boundary has a firing test.

### Slice 6: Unicode excerpt correction

1. Add a failing pure excerpt regression with at least 200 preceding `ß`
   characters and another length-changing fold such as `İ`. Assert the bounded
   human excerpt contains the first matched token. Add an inside-expansion case
   such as original `ßa`, folded `ssa`, and query `sa`: folded offset 1 maps to
   the original `ß` code point whose folded span contains it. Keep ASCII
   behavior and exact JSON hydrated text as controls.
2. Translate the matched folded start with an O(1)-extra-space scan over the
   original code points. Map a folded offset to the first original code point
   whose half-open folded span contains it; a boundary offset maps to the next
   code point. Do not allocate an index map proportional to a potentially 10 MB
   body. Keep search query parsing, ranking, hydration, and terminal escaping
   unchanged.
3. Update `docs/implementation/09-search-architecture.md` with the casefold-
   offset rationale.

Done signal: Unicode expansion cannot displace the human excerpt, including a
match that begins inside one original code point's folded expansion.

Independent checkpoint: a fresh reviewer compares the batched notification
implementation with [IAN-7], including the after-claim failure and both
notification outcome fixtures, and checks the Unicode span rule.

### Slice 7: structural grammar parity gate

1. In `tests/test_command_syntax.py`, build a test-only normalized projection
   of every mirrored core AST node and configured argparse leaf. Compare:
   - the core mirrored command-path set, with an explicit inventory exclusion
     for reserved compatibility-only `summon` and `dismiss`;
   - root pre-verb global spellings, destinations, value-taking behavior,
     runtime coercion, defaults, and root `--help`/`--version` actions;
   - top-level manifest name and post-verb globals, but not summary prose;
   - required child-subcommand selection for every child-bearing parser;
   - positional name, required/optional arity, multiplicity, and runtime
     coercion;
   - option spellings, destination, value-taking arity, requiredness,
     repeatability, normalized default, type, and choices;
   - mutually exclusive groups and their requiredness;
   - intermixed and literal-remainder policy.
2. Normalize argparse's absent `store_true=False` against the mirror parser's
   omitted local false value. Normalize AST `PATH` and `STRING` to argparse's
   no-coercion string class and `INTEGER` to `type=int`; keep `PATH` presentation
   semantics in separate AST construction tests. Do not compare help prose,
   metavars, argparse action class identity, summary text, exact diagnostics,
   or abbreviation acceptance unless an existing contract independently owns
   them.
3. Mutation-prove the gate in test development: alter one fixture projection
   or adapter option locally, observe the parity test fail, then revert the
   mutation. Record the red evidence in the Implementation Log; do not leave a
   mutation helper in production.
4. Add a differential invocation corpus proving the intended language split:
   unique command-local long-option abbreviations are accepted by argparse and
   rejected by the exact-spelling mirror; unique pre-verb root abbreviations
   are accepted by the CLI and rejected by the mirror; abbreviated post-verb
   globals and ambiguous abbreviations are rejected by the CLI.
5. Test Summon in two configurations: core-only registry retains the reserved
   `REMAINDER` compatibility bridge and has no mirror provider nodes; installed
   official Summon compares its `summon`/`dismiss` provider declarations with
   the adapters selected by root `taut`. This does not cover the separate
   `taut-summon` CLI's `run`, `status`, or default grammar. Exclude TUI-local
   `q`/`quit`, which intentionally have no CLI adapter.
6. Update `docs/implementation/06-command-extensions.md`: argparse remains the
   compatibility owner for now; structural reflection is the drift gate; the
   AST-to-argparse builder remains a separate migration with its own plan.

Done signal: every mirrored core and installed-root-Summon canonical
declaration has an executable structural counterpart; compatibility-only
accepted-language differences have firing tests; one-option mutation fails.

Independent checkpoint: a fresh reviewer mutation-checks one core declaration
and one installed Summon declaration and confirms that summary prose, the
reserved bridge, and abbreviation differences are neither silently normalized
nor falsely claimed as parity.

### Slice 8: traceability, full verification, and completed-work review

1. Update the three specs' Related Plans links, the core implementation mapping,
   command-extension and search implementation notes, and any maintained CLI
   help/README claim changed by the implementation.
2. Re-run the explicit no-change regression gates for R2 and R7. Record that
   continuity-token/claim-hash redaction and per-call terminal freshness did not
   move.
3. Run focused, static, documentation, root, and applicable PostgreSQL/shared-
   contract gates from the current implementation identifier.
4. Request a fresh independent completed-work review. Disposition every finding
   in the Review Log and close every Deviation Log row.
5. Update this plan's index row to `completed` only after implementation,
   verification, review, documentation alignment, and an owner-authorized
   landing are all recorded. Do not commit merely to satisfy the completion
   gate without owner authorization.

Done signal: code, specs, docs, and tests agree; no pending deviation remains;
the index status matches the evidence.

## Testing Plan

Use red-green TDD for R1, R4, R6 performance/failure behavior, the search
excerpt, and broker-adjacent `history_around()`. The R3 proper-subset test is
proof completion for one controlled behavior that already conforms to the
promoted [IAN-7.3] clarification, so its expected initial state is green; record
that exception honestly. The R3 write-through-then-raise case may start red if
the controlled failure seam does not yet preserve outcome ambiguity; it must not
change production retry policy merely to make the fixture easy. Canonical
grammar reflection is also proof completion when the normalized baseline
agrees; its mutation run supplies the required red evidence for the new gate.

What must stay real:

- SimpleBroker SQLite queue creation, exact-id insertion, pending iteration,
  source message writes, close/lifetime ownership, and client visibility at the
  released minimum and selected lock
- public `TautClient` selector, history, notification, and cursor paths
- actual command dispatch for exit classes, human output, JSON, and quiet mode
- the terminal text renderer on positive CLI integration paths
- real core and Summon adapter parser construction for grammar reflection

Permitted controlled seams:

- a sentinel iterator or recording stream to prove output occurs before
  exhaustion, flush visibility, final-record truncation, and chunk consumption
- a close-propagation spy paired with real SQLite lease behavior; the broker-
  order and lifetime integration cases still use the real public generator
- an inner close that raises after a controlled primary failure, solely to prove
  primary/cleanup error precedence
- a counting wrapper around real client methods for the mention batching
  complexity proof
- one pre-write notification failure and one write-through-then-raise failure
  after a real source commit; both retain real recipient queues
- a decoder spy for the internal `history_around()` decode-count optimization,
  paired with real broker rows and public returned behavior
- controlled interposition between real exact peek and real pending traversal
  to delete the anchor or an earlier page-boundary row

Do not mock the broker generator when proving broker order, the source queue
when proving notification failure subordination, the parser adapters when
proving grammar parity, or the terminal policy when proving human output.

## Verification and Gates

Focused commands by slice:

```bash
uv run --locked pytest -q -n 0 tests/test_client.py -k 'log or history_around or notification'
uv run --locked pytest -q -n 0 tests/test_cli.py tests/test_command_registry.py tests/test_cli_probes.py -k 'log or inbox or unrecognized or excerpt'
uv run --locked pytest -q -n 0 tests/test_search_cli.py -k 'excerpt or unicode'
uv run --locked pytest -q -n 0 tests/test_command_syntax.py
uv run --locked --extra dev --project extensions/taut_summon pytest -q -n 0 extensions/taut_summon/tests -k 'syntax or summon_cli'
```

Static and documentation gates:

```bash
uv run --locked ruff check taut tests
uv run --locked ruff format --check taut tests
uv run --locked mypy taut tests
uv run --locked --extra dev ruff check extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --locked --extra dev ruff format --check extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --locked --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
uv run --locked pytest -q -n 0 tests/test_docs_references.py tests/test_architecture_boundaries.py
uv run --locked bin/check-doc-paths
uv run --locked bin/check-cli-claims
bin/check-plan-status-index
git diff --check
```

Final root and shared-contract gates:

```bash
uv run --locked pytest -q
uv run --locked pytest -q -n 0 tests/test_shared_contract.py -k 'log or history_around or notification'
uv run --locked bin/pytest-pg --fast
```

The PostgreSQL harness is mandatory because the touched shared history and
notification contracts are backend parity surfaces. The grammar, renderer-
only batching, exit subtype, and pure excerpt mapping do not independently add
more PostgreSQL cases. Record the exact harness outcome rather than claiming
generic backend coverage.

Manual acceptance after automated gates:

1. Populate a temporary real SQLite channel with enough messages to span
   multiple render chunks.
2. Run human and `--json` no-limit `taut log` through a pipe that observes a
   flushed first chunk/record before process completion; confirm records stay
   in queue order.
3. Run `--limit`, `--since`, `--quiet`, and an empty selection; confirm exit
   classes and no cursor movement.
4. Insert a deliberate exact-id row out of timestamp order through public
   SimpleBroker and confirm Taut does not normalize it.

Success is positive evidence of incremental delivery and queue order, not an
unversioned RSS threshold. If memory still scales with total no-limit history,
implementation is blocked even when functional tests pass.

## Independent Review Loop

Before spec promotion, use a review-eligible agent family different from the
author when available. The reviewer reads this complete plan, especially the
Proposed Spec Delta, plus program theory, [TAUT-3.4], [TAUT-3.5], [TAUT-7.9],
[TAUT-8.1], [TAUT-8.3], [TAUT-8.7], [IAN-7], [SRCH-5.3], the concurrent
[TAUT-8.3] plan, the current code owners, and SimpleBroker's released public
signatures and traversal/lifetime specs at Taut's new minimum and selected
lock.

Review stance:

> Check every named surface. Challenge whether broker order is the correct
> history authority, whether the iterator/list split has one validation owner,
> whether partial streaming output is specified honestly, whether mention
> batching preserves claim and cursor semantics, and whether any no-action
> disposition conflicts with program theory. Look for unnecessary abstraction,
> missing firing tests, hidden resource lifetimes, and work that belongs in
> SimpleBroker rather than Taut. Could a zero-context engineer implement this
> confidently and correctly after the delta is promoted?

The author records each point in the Review Log as accepted, rejected with
evidence, or out of scope with a reconsideration condition. A reviewer who
cannot implement the plan confidently blocks promotion.

After implementation, a fresh reviewer repeats the code/spec/test comparison,
checks the grammar mutation proof, and verifies that no rejected R2/R7 policy,
atomic/retrying R3 redesign, or render-before-claim behavior entered through
adjacent cleanup.

## Out of Scope

- Default `log` caps, pagination, `--all`, or a reverse SimpleBroker iterator
- Changing `TautClient.log()` to return an iterator
- Reordering or repairing foreign/exact-id broker rows
- Timestamp-nearest `history_around()` semantics for deliberately out-of-order
  exact-ID rows; context follows adjacency observed in one authoritative broker
  traversal
- AST-to-argparse generation or changes to exact argparse help/error prose
- Atomic multi-body mention fanout, notification retries, or a delivery ledger
- Render-before-claim, acknowledgement state, per-device inboxes, or pointer
  repair
- New debug redaction rules, capture-local deny lists, or a safe-to-share debug
  promise
- Terminal-policy TTLs, filesystem watchers, or per-command freshness changes
- Search ranking, indexing, query casefolding, or JSON hit text
- Direct SQL against SimpleBroker tables or any dependency change beyond the
  prerequisite close-contract floor

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Implementation Log

Append comprehension answers, red/green evidence, promotion baseline, slice
identifiers, verification commands, and observed results here during execution.

### 2026-08-25: Slice 0 dependency-contract portion

- Red interface probe at the prior selected SimpleBroker 7.4.1 artifact:
  package-root `CloseableIterator` import raised `ImportError`, and
  `get_type_hints(Queue.peek_generator)["return"]` was ordinary
  `Iterator[str | tuple[str, int]]`.
- Updated Taut's maintained minimums and four locks to SimpleBroker 7.4.2 and
  the coordinated SimpleBroker-PG 3.9.2 release. Immutable tag, commit, and
  artifact hashes are recorded in the Spec Baseline above. The Taut floor
  update landed at `a470f8abe28f314c83b1458d916cfa1d91327a16`.
- Green interface probe at the locked 7.4.2 artifact: package-root
  `CloseableIterator` imports; `Queue.peek_generator()` and high-level
  `peek(all_messages=True)` expose it; unstarted and advanced iterators close
  terminally; and both ephemeral and persistent queues are immediately reusable
  after same-thread early close.
- Verification: all four `uv lock --check` gates passed; metadata/release tests
  passed; client/shared-contract tests passed; mypy passed for 137 source files;
  plan-index, documentation-path, documentation-reference, and whitespace gates
  passed; the full root suite passed with one expected Windows-only skip; and
  `uv run --locked bin/pytest-pg --fast` passed 292 shared plus 37 PostgreSQL-
  extension tests.
- The extension E1 shared-owner slice landed at
  `d5e3be2be15dc909bb73001443df399c967ec50a`; the exact overlapping owner blobs
  are recorded in the Spec Baseline. The checkout-free exact-minimum
  `iter_log()` lifetime test cannot fire until Slice 2 adds that public Taut
  method.
- Independent slice review initially blocked because the proposed Taut stream
  omitted SimpleBroker 7.4.2's first-advance thread ownership. The accepted
  correction now makes creation lazy, pre-first close terminal, active
  advance/exhaust/close same-thread, cross-thread use unsupported, and every
  Taut-owned cleanup owner-thread-bound. The focused re-review returned PASS.

## Review Log

| Date | Review | Result | Disposition |
|------|--------|--------|-------------|
| 2026-08-24 | Three independent read-only plan passes: implementation feasibility, program-theory/testing, and zero-context reader testing | BLOCK before revision | Accepted every blocker: closeable generator ownership; live non-snapshot traversal; broker-adjacent [TAUT-7.9]; flush-visible chunks and truncated final transport record; dependency-aware rollback; canonical declaration rather than summary parity; argparse abbreviation and reserved Summon bridge differences; explicit multi-recipient proper-subset notification contract; after-claim batch failure proof; minimum-version and concurrent-plan gates; extension static and PostgreSQL verification. Also replaced the full Unicode offset map with O(1)-space translation and corrected [THEORY-5]. |
| 2026-08-24 | Three independent revised-plan passes | BLOCK before second revision | Accepted the remaining blockers: SimpleBroker 7.4.1 has no public early-close lease contract; all limited and unlimited traversals are live; context adjacency is only among rows observed by one traversal; history work belongs inside the contiguous publication unit; rollback is owned-delta-specific; extension E1 goes first with a reciprocal gate; raised notification delivery is outcome-ambiguous; root abbreviations and PATH coercion need exact grammar treatment; anchor-offset races, primary/cleanup failure precedence, inside-expansion Unicode offsets, and decoded chunk accounting need firing rules. |
| 2026-08-24 | Three independent second-revision passes: feasibility, program-theory/testing, and zero-context reader testing | PASS | No planning blocker remains. Reviewers confirmed the upstream release and extension E1 identifiers are explicit Slice 0 prerequisites, not hidden design gaps; every prior close, traversal, adjacency, rollback, notification, grammar, failure-precedence, Unicode, and chunk-accounting blocker is resolved. Re-review remains mandatory after the Slice 0 baseline rebase and before spec promotion. |
| 2026-08-25 | SimpleBroker 7.4.2 dependency-slice review | BLOCK, then PASS after correction | The first pass found that Taut's proposed iterator omitted upstream first-advance thread ownership. Accepted and propagated lazy creation, terminal pre-first close, same-thread active advance/exhaust/close, unsupported cross-thread use, and owner-thread Taut cleanup through the proposed spec, comprehension gate, invariants, Slice 2 tests, implementation instructions, and fresh-reader question. Re-review found no remaining blocker. |
| 2026-08-25 | Slice 0 post-E1 baseline re-review | BLOCK before correction | The first pass found that the rebase baseline omitted Taut dependency-floor commit `a470f8a`, Slice 0 listed E1 and the floor update in an order contradicted by Git ancestry, and the fresh-eyes status still awaited an identifier already recorded. Accepted: record the original, dependency, and post-E1 baselines separately; align the task order with `a470f8a` then `d5e3be2`; reserve E1-first ordering for subsequent shared-owner behavioral edits; and mark Slice 0 complete before repeat review. |
| 2026-08-25 | Corrected Slice 0 post-E1 re-review | PASS | The reviewer confirmed that the original, dependency-floor, and post-E1 baselines are explicit; task order matches Git ancestry `a470f8a` then `d5e3be2`; E1-first ordering is limited to later shared-owner behavior; and Slice 0 is complete. No blocker remains before Slice 1. |

## Fresh-Eyes Review

Reader testing asks a zero-context engineer these questions:

1. Which findings change behavior, which only add proof, and which are rejected?
2. What exact order owns `log()` and `history_around()`?
3. Who closes `iter_log()`, on which thread, and what concurrent traversal does
   it promise?
4. When can CLI output be partial or a final record be truncated?
5. Why do claim-before-render and recipient-specific mention writes remain?
6. What does canonical grammar declaration parity exclude deliberately?
7. Which slice can roll back independently, and which rollback is dependent?
8. What evidence blocks implementation or promotion?

The first fresh-reader pass failed questions 2 through 8; the revised pass
answered the questions but found six remaining contradictions and blocked
promotion. Both sets of accepted corrections are recorded in the Review Log
and incorporated above. The second-revision pass answered all eight from the
document alone and returned PASS. The plan may be `active`. Slice 0 is
complete: the released dependency, Taut floor commit, E1 shared-owner commit,
exact overlapping blobs, and execution order are recorded. The corrected
post-E1 repeat review passed; execution may enter Slice 1 spec promotion.
