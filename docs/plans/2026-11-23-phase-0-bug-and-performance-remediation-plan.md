# Phase 0 Bug and Performance Remediation Plan

Date: 2026-11-23

Status: completed (see `docs/plans/README.md` status index)

Class: 4+P (effective 5). This unit remediates verified product defects and
measured runtime bottlenecks across core `taut`, `taut-pg`, `taut-tui`, and
`taut-summon`, and updates repository documentation-reference coverage
(`tests/test_docs_references.py`, `bin/check-doc-paths`). The `+P` modifier
applies because widening `_markdown_path_sources()` in
`tests/test_docs_references.py` changes how future documentation and citation
claims are verified ([DOM-6], [DOM-15]). The hardening checklist
(`docs/agent-context/runbooks/hardening-plans.md`) is mandatory because Slice 2
modifies SQLite and PostgreSQL search-reconciliation batching, provider
discovery validation, and indexing, and Slice 3 touches asynchronous worker
cancellation and two-step modal confirmation lifecycles in `taut-tui` ([DOM-5]).

Plan type: implementation, test, and documentation-gate remediation without
normative product-spec changes (every slice restores or optimizes conformance
with active `[IAN-3.2]`, `[TAUT-6.4]`, `[TAUT-8.5]`, `[SRCH-4.1]`, `[SRCH-6.2]`,
`[SRCH-7]`, `[SRCH-10.1]`, `[SRCH-10.2]`, `[DOCT-4]`, `[SUM-7.4]`, `[SUM-10]`,
`[TUI-5.3]`, `[TUI-6.4]`, `[TUI-8.2]`, `[TUI-11.1]`, `[TUI-11.3]`, `[TUI-12.1]`,
and `[TUI-12.2]` contracts).

Supersedes: `docs/plans/2026-10-15-deep-review-remediation-plan.md` (unexecuted
at `HEAD` `c636e70`; see Inheritance and Disposition Matrix below). Upon review
acceptance (`PASS`) of this plan, this plan's status flips to `active` and
`2026-10-15-deep-review-remediation-plan.md` flips to `superseded` in
`docs/plans/README.md`.

Owner: implementing engineer; durable-policy revisions and `[THEORY-8]`
decisions remain gated on the human repository owner ([DOM-14], [DOM-15]).

## 1. Goal

Eliminate verified functional regressions and first-impression performance
cliffs identified in the 2026-11-23 empirical deep-dive review before layering
new onboarding, MCP, and Summon ergonomics in Phases 1–3:

1. **Slice 1 — Identity & CLI Hot-Path Performance (`[IAN-3.2]`, `[TAUT-8.5]`)**:
   Replace macOS `/usr/sbin/ioreg` subprocess spawning (`13.24 ms/call`) with
   an in-process Darwin `libc.gethostuuid()` query (`~1.5 µs/call`, falling back
   to `/usr/sbin/ioreg` and `hostname:`), reuse captured host identity + a
   selected-member batch alias query (`list_aliases_for_members`) in
   `TautClient.who()`, and lazily cache joined-channel metadata on the first
   eligible human mention in `emit_notifications()` so human `taut inbox` stops
   running `2K` identity captures and `K * T` broker queries without adding any
   lookup on `--json` or ineligible notifications.
2. **Slice 2 — Search Hot-Path Remediation, Provider Compatibility Check & Tombstone Projection Version (`[SRCH-4.1]`, `[SRCH-6.2]`, `[SRCH-7]`, `[SRCH-10.1]`, `[SRCH-10.2]`)**:
   Bind `SEARCH_PROJECTION_VERSION` in SQLite and PostgreSQL deletion tombstones
   (inherited `F5`); add `taut_search_documents_thread_idx (generation, thread, message_ts)`
   in `_DDL` for fresh initializations and schema-1 upgrades while keeping
   schema-2 `ensure_schema()` version-read-only per `[SRCH-6.2]`; retain
   baseline's per-100 `Queue.peek_generator(...)` + `close()` read loop (avoiding
   SimpleBroker's two-page overlap, per `R4-01`) while partitioning each closed
   100-row slice into sub-batches bounded by `<= 100` rows and
   `<= max(2 MiB, largest item)` and reconciling unchanged rows via
   `reconcile_unchanged_batch` with all `projection_segments()` tokenization
   outside write locks; push `before` and `threads` (`scope`) predicates into
   SQL in both providers; and validate explicit named/keyword parameter kinds in
   `taut/search/_discovery.py::_validate_provider()`.
3. **Slice 3 — `taut-tui` Inspector Formatting, Tail-Append Transcript Rendering, Displayed-Row Selection & Summon Lifecycle Fixes (`[TUI-5.3]`, `[TUI-6.4]`, `[TUI-8.2]`, `[TUI-11.1]`, `[TUI-11.3]`, `[TUI-12.1]`, `[TUI-12.2]`)**:
   Repair `TautApp._render_domain_result()` and `:inbox` dispatch using
   field-level `escape_inline_text` / `escape_message_body` `DisplayText`
   builders so `:log`, `:read`, `:inbox`, `:search`, `:message show`,
   `:who` / `Members` (including `[TUI-6.4]` chat presence), and `:list --dms`
   (actor-scoped DM labels) render safe, human-readable records; add a
   tail-only `Option` construction + `add_options()` fast path in
   `TautApp._render_messages()` and skip redundant re-renders in
   `_apply_navigation_result()` when `_reply_threads` is unchanged; extract
   selections directly over displayed virtual rows in
   `TautTranscript.get_selection()` with per-option strip memoization (inherited
   `F3`, also fixing `U+2028`/`U+2029` `splitlines()` coordinate drift); and
   linearize `TuiSummonOperations` cancel/stop with `on_ready()` plus guard
   second-step modal pushes while propagating control-flow `BaseException`s
   (inherited `F1`, `F2`).
4. **Slice 4 — `taut-summon` Persona CLI Syntax Fix, Matcher/Driver Hygiene, Doctor Note Alignment & Doc-Reference Gate (`[SUM-10]`, `[DOCT-4]`)**:
   Fix invalid 1-arg `` `taut reply "..."` `` in `render_default_persona()` to
   valid 3-arg syntax naming the parent channel and illustrative 19-digit
   origin ID, backed by a `parse_command_line(..., syntax=core_command_syntax())`
   test; add the `_DetachChordMatcher` enhanced-atom deadline test and
   `_accept_phase_result` shutdown phase guard (inherited `F6`); align stale
   schema-1 queue-count prose in `docs/implementation/11-system-doctor.md`
   while preserving `[DOCT-4]` two-pass check ordering (inherited `F4`
   disposition); and add `docs/coalescing.md` + `docs/plans/README.md` to
   `tests/test_docs_references.py::_markdown_path_sources()` (inherited `F7`).

## 2. Source Documents and Spec Baseline

Spec baseline: `c636e70249f3d914d5d9c57bad61a86ec2fb7789` (`HEAD` on `main`, one
commit past `v0.9.12` at `a4fde51`). No spec text changes in this plan.

Consulted startup and governing surfaces:

- `AGENTS.md`; `docs/agent-context/README.md`; `docs/program-theory.md`
  `[THEORY-1]`–`[THEORY-8]` and `[THEORY-5.A1]`–`[THEORY-5.A6]`;
  `docs/specs/product-section-registry.md`.
- `docs/agent-context/decision-hierarchy.md`, `principles.md`,
  `engineering-principles.md`, `lessons.md`, `docs/coalescing.md`,
  `docs/lessons.md` (Golden Rules and post-`2026-09-25` entries), and runbooks
  `writing-plans.md`, `hardening-plans.md`, `testing-patterns.md`,
  `adversarial-acceptance-probes.md`, `review-loops-and-agent-bootstrap.md`, and
  `maintaining-traceability.md`.
- Source specs:
  - `docs/specs/01-development-documentation-operating-model.md` `[DOM-5]`,
    `[DOM-6]`, `[DOM-10]`, `[DOM-10.1]`, `[DOM-10.2.1]`, `[DOM-11]`, `[DOM-13]`,
    `[DOM-14]`, `[DOM-15]`
  - `docs/specs/02-taut-core.md` `[TAUT-3.1]`, `[TAUT-3.4]`, `[TAUT-6.4]`,
    `[TAUT-8.5]`
  - `docs/specs/03-identity-addressing-notifications.md` `[IAN-3.2]`, `[IAN-6]`
  - `docs/specs/04-summon.md` `[SUM-7.4]`, `[SUM-10]`, `[SUM-13]`
  - `docs/specs/06-search.md` `[SRCH-4.1]`, `[SRCH-5.2]`, `[SRCH-6.2]`,
    `[SRCH-7]`, `[SRCH-8.3]`, `[SRCH-9.3]`, `[SRCH-10.1]`, `[SRCH-10.2]`
  - `docs/specs/09-system-doctor.md` `[DOCT-4]`, `[DOCT-4.6]`
  - `docs/specs/10-taut-tui.md` `[TUI-5.3]`, `[TUI-6.4]`, `[TUI-7.1]`,
    `[TUI-8.2]`, `[TUI-11.1]`, `[TUI-11.3]`, `[TUI-12.1]`, `[TUI-12.2]`
- Implementation notes:
  `docs/implementation/02-repository-map.md`, `03-agent-inventory.md`,
  `04-taut-architecture.md`, `05-taut-summon-architecture.md`,
  `09-search-architecture.md`, `11-system-doctor.md`, `12-taut-tui.md`.
- Superseded and adjacent plans:
  `docs/plans/2026-10-15-deep-review-remediation-plan.md` (superseded here),
  `docs/plans/2026-09-28-simplification-and-hot-path-plan.md`,
  `docs/plans/2026-09-24-identity-claim-boundary-plan.md`,
  `docs/plans/2026-09-24-tui-text-selection-and-clipboard-plan.md`,
  `docs/plans/2026-08-24-command-runtime-findings-remediation-plan.md` (item R6
  batched mention reply rendering implemented here without altering R1/R5 scope).

### Inheritance and Disposition Matrix for `2026-10-15-deep-review-remediation-plan.md`

| Predecessor ID | Summary | Disposition in this plan |
|---|---|---|
| `F1` | `TuiSummonOperations` cancel/handle linearization with `on_ready()` | Inherited & implemented in **Slice 3**. |
| `F2` | Two-step modal push exception containment (`decide_offer`) with control-flow propagation (`[TUI-12.1]`) | Inherited & implemented in **Slice 3**. |
| `F3` | Bounded `TautTranscript.get_selection()` + per-option `Visual.to_strips()` memoization, refined to direct displayed-row slicing (`F08`) | Inherited & implemented in **Slice 3**. |
| `F4` | Proposed merging the two `open_broker` + `list_queue_stats()` calls in `taut/_doctor.py:212, 266` | **Rejected on spec-conformance grounds**: `[DOCT-4]` (`09-system-doctor.md:182`) and `11-system-doctor.md:49-51` require Check 6 (`search_work`) to observe broker stats *after* Check 5 (`extension_state`). Instead, **Slice 4** repairs stale schema-1 prose at `11-system-doctor.md:41`. |
| `F5` | Bind `SEARCH_PROJECTION_VERSION` in SQLite and PostgreSQL `_delete_in_generation()` | Inherited & implemented in **Slice 2**. |
| `F6` | `_DetachChordMatcher` enhanced-atom deadline test + `_driver.py` `_owner_phase = "spawn-ready"` guard when `_shutdown.is_set()` | Inherited & implemented in **Slice 4**. |
| `F7` | Include `docs/coalescing.md` and `docs/plans/README.md` in `tests/test_docs_references.py::_markdown_path_sources()` and reconcile `bin/check-doc-paths` | Inherited & implemented in **Slice 4**. |
| `F8` | `bin/coalesce-check` plan-tier status counts + full plan-index/header sweep | **Cleanly severed & deferred** to **Phase 3 Plan** (`CLI Polish, Packaging & Plan Hygiene`). Why deferred: Phase 3 reconciles all 9 shipped `active`/`promoted` plans together in one dedicated governance sweep; zero tasks in Phases 0–2 depend on `F8`. Reopens when: Phase 3 plan is authored in this sequence (immediately following Phase 2B). |
| `N1`, `N2` | Predecessor no-action / `2026-09-24` ownership items | Unchanged (`N1` already verified identical; `N2` remains owned by `2026-09-24-cli-read-delivery-and-agent-recipes-plan.md`). |

## 3. Context and Key Files

### Slice 1 (Identity & CLI Hot-Path Performance)

- `taut/identity.py`:
  - `capture_host_identity()` (`lines 133-198`, carries `[RUFF-SUP-052]`
    `C901=1`): on `sys.platform == "darwin"`, add `_darwin_gethostuuid() -> str | None`
    using stdlib `ctypes` + `uuid.UUID(bytes=bytes(uuid_buf))` formatted
    uppercase (`str(uuid.UUID(bytes=bytes(buf))).upper()`) to match `ioreg`'s
    exact `XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX` format. Try
    `_darwin_gethostuuid()` first on `darwin`; if it returns `None`, fall back
    to the existing `/usr/sbin/ioreg` subprocess path, then `hostname:`.
    Preserve `capture_host_identity`'s approved `[RUFF-SUP-052]` `C901=1`
    registration verified by `bin/ruff_suppression_index.py --check`.
- `taut/state/__init__.py` (`TautState`, `line 42`) and `taut/state/_sql.py`
  (`SqlSidecarTautState`, `lines 174-260`, and SQL helpers `lines 865-880`):
  - Add `list_aliases_for_members(member_ids: Sequence[str]) -> dict[str, tuple[str, ...]]`
    to `TautState` and `SqlSidecarTautState` (delegating to a helper
    `list_aliases_for_members(queue: Queue, member_ids: Sequence[str])` that
    returns `{}` immediately on empty `member_ids` and queries
    `SELECT member_id, alias_key FROM taut_member_aliases WHERE member_id IN (?, ...) ORDER BY member_id, alias_key`
    in chunks of `<= 500` inside a single `with queue.sidecar():` session so a
    small `who(thread)` roster only fetches aliases for the returned members!).
- `taut/client/_identity.py`:
  - `who(self, thread: str | None = None)` (`lines 101-117`) and
    `_member_from_row()` (`lines 576-601`): capture `resolved = self._resolve_member(...)`
    in `who()`, compute `local_host_id` once (`resolved.capture.host.host_id`
    when `resolved.capture is not None` else `identity.capture_host_identity().host_id`),
    batch-fetch `aliases_by_member = self._state.list_aliases_for_members([row["member_id"] for row in rows])`,
    and pass precomputed `local_host_id=local_host_id` and
    `aliases=aliases_by_member.get(row["member_id"], ())` into `_member_from_row()`.
- `taut/commands/_rendering.py`:
  - `emit_notifications()` (`lines 469-515`) and `_mention_reply_id()`
    (`lines 869-904`): in the **human-only** rendering path (`not json_output`
    and `not quiet`), pass a small lazy `_MentionLookupCache(client)` helper into
    `_mention_reply_id()`. Short-circuit `client is None`, `thread is None`,
    `message_ts is None`, and `DM_SELECTOR_RE.fullmatch(thread) is not None`
    **before** any lookup (preserving 0 lookups on `--json` and DM mentions).
    Populate `joined_names: set[str]` lazily on the first non-DM mention, and
    populate `channels_by_name: dict[str, Thread]` lazily only on the first
    mention whose `thread in joined_names` (preserving 0 `list_threads` calls
    when all mentions are in unjoined/left channels!). Reuse `client.queue(thread).peek_one(exact_timestamp=message_ts)`
    as before.
- Existing tests to read and update:
  - `tests/test_identity.py` (`lines 288-375`), `tests/test_cli.py`
    (`lines 2127-2165` and inbox tests), and `tests/test_identity_performance.py`.

### Slice 2 (Search Hot-Path Remediation, Provider Compatibility Check & Tombstone Projection Version)

- `taut/search/_provider.py` (`lines 37-148`):
  - Define `@dataclass(frozen=True, slots=True) class DocumentCheck`:
    `message_ts: int`, `thread: str`, `text_sha256: str`, `text_bytes: int`
    (pure fixed-size metadata — zero message body text!).
  - Extend `SearchProvider`:
    - `reconcile_unchanged_batch(self, checks: Sequence[DocumentCheck], *, revision: int) -> frozenset[int]`:
      inspects the batch atomically under one `sidecar(transaction=True)` lock.
      **Cross-generation classification rule (`R2-02`)**: before executing any
      `UPDATE`, inspect every writable generation (`current_generation`, plus
      `staging_generation` when `staging is not None and revision >= staging_scan_revision`).
      A `DocumentCheck` is eligible for in-batch reconciliation **if and only if**
      in **every** writable generation either `previous_revision > revision`
      (already superseded) OR the stored row is `indexed` and matches
      `(thread, text_sha256, text_bytes, SEARCH_PROJECTION_VERSION)`. Only
      globally-eligible IDs have `latest_revision = revision` bumped (`WHERE generation = ? AND latest_revision < ? AND message_ts IN (...)`)
      in the writable generation(s) where `previous_revision < revision`. Any ID
      missing, tombstoned, or mismatched in *any* writable generation (with
      `previous_revision <= revision`) is **not** bumped in any generation and is
      returned in `needs_replace` so out-of-lock projection + `replace_document()`
      updates all writable generations atomically in one transaction.
    - `query(self, chunks: tuple[str, ...], *, before: int | None = None, threads: tuple[str, ...] | None = None, limit: int) -> list[SearchCandidate]`.
- `taut/search/_discovery.py` (`lines 100-122`, per `F03`, `R2-04` & `R3-02`):
  - Keep `SEARCH_PROVIDER_API_VERSION = 1` per `[SRCH-7]`. Core `taut-chat` and
    `taut-pg` update in lockstep; to reject an outdated or `**kwargs`-masked
    positional-only provider cleanly at discovery time before any search work
    runs, add `"reconcile_unchanged_batch"` to `required` in `_validate_provider()`
    AND validate both call binding and explicit keyword-accepting `Parameter.kind`
    (`Parameter.KEYWORD_ONLY` or `Parameter.POSITIONAL_OR_KEYWORD`, never
    `POSITIONAL_ONLY` swallowed by `VAR_KEYWORD`):
    - on `provider.reconcile_unchanged_batch`: bind `((), revision=1)` and require
      `"revision"` in `sig.parameters` with kind in `{POSITIONAL_OR_KEYWORD, KEYWORD_ONLY}`;
    - on `provider.query`: bind `((), before=None, threads=None, limit=1)` and
      require each of `("before", "threads", "limit")` in `sig.parameters` with
      kind in `{POSITIONAL_OR_KEYWORD, KEYWORD_ONLY}`
    (catching `TypeError`/`ValueError` and raising
    `SearchProviderUnavailableError(_DIAGNOSTIC)`).
  - Update test doubles in `tests/test_search_discovery.py` (`_CompleteProvider`)
    and `tests/test_search_worker.py` to implement `reconcile_unchanged_batch`
    and `query(..., threads=None, ...)`.
- `taut/search/_sqlite.py` (`lines 56-94, 135-385, 682-745`) and
  `extensions/taut_pg/taut_pg/_search.py` (`lines 44-84, 116-340, 613-659`):
  - Add `CREATE INDEX IF NOT EXISTS taut_search_documents_thread_idx ON taut_search_documents (generation, thread, message_ts)`
    to `_DDL` in both providers so fresh initializations and schema-1 upgrades
    create it; **do not** run DDL when `schema_version() == SEARCH_SCHEMA_VERSION`
    (`F01`, preserving `[SRCH-6.2]` version-read-only steady state).
  - Fix `_delete_in_generation()` (`_sqlite.py:360`, `_search.py:319`) to bind
    `SEARCH_PROJECTION_VERSION` instead of hardcoded literal `1` (`F5`).
  - Implement `reconcile_unchanged_batch(checks, *, revision)` in both providers
    enforcing the cross-generation classification rule (`R2-02`) above.
  - In `query()`: push `before` (`AND d.message_ts < ?` on SQLite, matching PG)
    and `threads` (`AND d.thread IN (?, ...)` when `threads is not None` and
    `0 < len(threads) <= 500`; return `[]` immediately when `threads == ()`).
    On SQLite (`_sqlite.py:697-745`), intersect candidate IDs across all query
    `chunks` **before** sorting and applying `[:limit]`.
- `taut/client/_searching.py` (`lines 305-336, 425-550`, per `F02`, `R2-01`, `R3-01` & `R4-01`):
  - Define `_RECONCILE_BATCH_MAX_ROWS = 100` and
    `_RECONCILE_BATCH_MAX_BYTES = 2 * 1024 * 1024` (2 MiB).
  - **Preserving baseline peak source memory and `[SRCH-10.1]` (`R4-01`)**:
    SimpleBroker 8.8.1's `peek_generator()` retains the previous 1,000-row page
    across internal page transitions if kept open continuously (`15.87 MiB` vs
    `8.75 MiB` at baseline). Therefore, **preserve baseline's outer `peek_generator`
    + `list(islice(generator, _RECONCILE_BATCH_MAX_ROWS))` + `finally: close()`
    read loop verbatim** (`_searching.py:516-530`), closing the generator so
    SimpleBroker frees its internal 1,000-row page immediately! Then partition
    and fully process+discard that 100-row `raw_page` **before** opening the
    next `peek_generator(after_timestamp=cursor)`: accumulate `(DocumentCheck, text)`
    into `sub_batch` and flush `sub_batch` before adding an item that would
    exceed `_RECONCILE_BATCH_MAX_BYTES` (`2 MiB`) when `sub_batch` is non-empty
    (so each sub-batch has `<= 100` rows and byte bound `max(2 MiB, largest item)`),
    clearing `raw_page` / `sub_batch` references before the next outer iteration!
  - In both `_reconcile_full_thread()` and incremental `_reconcile_search_thread()`:
    for each bounded sub-batch, call `needs_replace = provider.reconcile_unchanged_batch([check for check, _text in sub_batch], revision=scan_revision)`,
    and **outside any provider write lock**, for each `(check, text)` with
    `check.message_ts in needs_replace`, compute `projection_segments(text, max_segment_bytes=_INDEX_SEGMENT_BYTES)`
    and call `provider.replace_document(IndexedDocument(...), revision=scan_revision)`.
  - In `_query_search_hits()`, return `[]` immediately when `not scope`, pass
    `threads=tuple(sorted(scope))` to `provider.query()`, and break pagination
    when `len(hits) >= request.limit or len(candidates) < _INDEX_QUERY_BATCH`.

### Slice 3 (`taut-tui` Inspector, Tail-Append Transcript, Displayed-Row Selection & Summon Lifecycle)

- `extensions/taut_tui/taut_tui/session.py` (`lines 75-110, 365-395`) and
  `extensions/taut_tui/taut_tui/domain.py` (`lines 208-212`, per `R2-05`, `R3-03` & `R4-02`):
  - Define `_NOTIFICATION_FEED_LIMIT = 200` matching `session.py:86`.
  - Add a shared locked helper `_record_notifications_locked(self, items: Sequence[Notification]) -> None`
    used by **both** live watcher deliveries (`session.py:378`) and manual
    `claim_inbox()`! Because `client.inbox()` commits its claim before JSON
    decoding, a live watcher can claim and append item `201` (`ts=201`) before
    `claim_inbox()` finishes decoding items `1..200` (`ts=1..200`); plain
    `deque.extend` would then evict newer item `201` (`R4-02`). Instead, assign
    each stored entry a monotonic local sequence tie-breaker `_feed_seq` and
    order the merged buffer by `(item.ts is None, item.ts or 0, seq)` (so all
    broker-sourced pointers with monotonic `Notification.ts` sort strictly oldest
    to newest regardless of decode/append interleaving, while synthetic `ts=None`
    items preserve arrival order), retaining the **newest**
    `merged[-_NOTIFICATION_FEED_LIMIT:]` (`200`) entries!
  - Add `claim_inbox(self) -> Future[list[Notification]]` on `TuiSession`: on
    the session worker thread, claims at most `_NOTIFICATION_FEED_LIMIT` (`200`)
    pointers via `_empty_ok(lambda: client.inbox(limit=_NOTIFICATION_FEED_LIMIT))`,
    merges them via `_record_notifications_locked` under `self._state_lock`, and
    returns the newly claimed `list[Notification]` (preserving
    `TuiDomainActions.inbox() -> Future[list[Notification]]` and
    `test_tui_domain.py:177`).
- `extensions/taut_tui/taut_tui/app.py`:
  - Inspector formatting (`_dispatch_history_command` at `line 1538`,
    `_render_domain_result` at `lines 2815-2825`, `_render_notifications` at
    `lines 2918-2932`, and formatters at `lines 3816-3874`, per `F06`, `R2-05` & `R3-03`):
    - Route `invocation.path == ("inbox",)` to a dedicated `_run_inbox_action(domain.inbox())`
      whose UI-thread completion callback validates `future.result()` (reporting
      any error via `_show_error`) and then renders
      **`self._render_notifications(self._session.notification_feed() if self._session else ())`**
      — reading the live `_notification_feed` on the UI thread at render time
      (identically to `ActionId.NOTIFICATIONS_OPEN` at `app.py:1758` and live
      watcher redraws at `app.py:3376`) so a watcher delivery arriving between
      worker claim and UI callback can never be overwritten by an older worker
      snapshot!
    - Build all `_RESULT_FORMATTERS` and list-item formatters returning
      `DisplayText` (`display_text(...)`) using `escape_inline_text(...)` on
      every single-line metadata field (`from_name`, `name`, `display_name`,
      `thread`, `channel`, `persona`, `presence`, `kind`) so embedded `\n` in
      foreign metadata renders as literal `\n` instead of forging a new display
      row, and `escape_message_body(...)` on message/search-hit bodies so
      `[TUI-5.3]` allowlist decoding and tab expansion apply consistently!
    - Format `Member` lists (`:who` / `Members`) with `name`, `presence`,
      `kind`, and optional `persona` (`[TUI-6.4]`); format `Thread` lists
      (`:list`, `:list --dms`) and `SearchHit` targets using
      `self._target_labels.get(name)` (falling back to `thread.display_name` or
      `"Direct message"` for `dm` threads); format `Message` (`message show`,
      `:log`, `:read`) and `SearchHit` (`:search`) records with formatted time,
      inline-escaped author/target header, and `escape_message_body(text)`.
      Empty non-inbox lists continue to render `"No results"`.
  - `_apply_navigation_result()` (`lines 3139-3145`): save
    `previous_reply_threads = self._reply_threads` before assignment and call
    `self._render_messages(self._message_rows)` **only** when
    `self._message_rows and reply_threads != previous_reply_threads`.
  - `_render_messages()` (`lines 3396-3447`, per `F07`): track
    `_rendered_target: str | None`, `_rendered_layout: TranscriptMetadataLayout | None`,
    and `_rendered_reply_keys: frozenset[tuple[str, int]]`. When `prev` is
    non-empty, `len(messages) > len(prev)`, `messages[:len(prev)] == prev`,
    `transcript.option_count == len(prev)`, and `(target, layout, reply_keys)`
    match: construct `Option` instances **only** for the tail slice
    `messages[len(prev):]` and append via `transcript.add_options(...)` without
    calling `transcript.clear_options()` or `_cancel_pending_selection_copy()`.
    On full rebuilds, call `transcript.add_options(...)` once.
  - `on_terminal_attach_confirmation_request()` (`lines 810-822`) and
    `_present_attach_confirmation()` (`lines 3706-3752`, per `F2`, `F05` & `R2-03`):
    define `run_guarded(step: Callable[[], None]) -> None` inside
    `TautApp.on_terminal_attach_confirmation_request` using a **two-clause**
    `try ... except` (`verified exit 0 under Ruff 0.17.4 BLE001,RUF100`):
    ```python
    try:
        step()
    except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
        event.fail(exc)
    except BaseException as exc:
        event.fail(exc)
        raise
    ```
    Ordinary presentation `Exception`s are contained under the single existing
    `[RUFF-SUP-085]` `BLE001=1` directive (no `RUF100` unused-noqa failure and
    zero suppression-ledger drift), while non-`Exception` control-flow
    `BaseException`s (`KeyboardInterrupt`, `SystemExit`, `asyncio.CancelledError`)
    call `event.fail(exc)` first and unconditionally `raise` per `[TUI-12.1]`!
- `extensions/taut_tui/taut_tui/summon.py` (`lines 220-237, 306-315, 332-350`):
  - Add `_cancel_and_collect_handles()` under `self._lock` and check
    `self._closed or current.cancel.is_set()` in `on_ready()` (`F1`).
- `extensions/taut_tui/taut_tui/widgets.py` (`lines 596-631`, per `F3` & `F08`):
  - Implement `TautTranscript.get_selection(self, selection: Selection)` by
    slicing directly over displayed virtual rows `[start_line_index, upper)` via
    `_selection_line(y, strips_by_option)` (memoizing `Visual.to_strips()` per
    `option_index` within the call) instead of joining `height` lines with `"\n"`
    and calling `Selection.extract()`'s `.splitlines()`. This renders each
    selected option at most once and maps virtual `(x, y)` coordinates directly
    to displayed rows even when an option contains Unicode line separators
    (`U+2028` / `U+2029`) that `str.splitlines()` would split despite occupying
    one visual row.

### Slice 4 (`taut-summon` Persona Fix, Matcher/Driver Hygiene, Doctor Note & Doc Gate)

- `extensions/taut_summon/taut_summon/_persona.py` (`lines 85-88`, per `F10`):
  - Replace invalid `` `taut reply "..."` `` with
    `` `taut reply {default_thread} 1786032926849409024 "..."` (substituting the parent channel and the origin message's full 19-digit ID for the illustrative ID) ``.
- `extensions/taut_summon/tests/test_persona.py` (`F10`):
  - Extract every inline backticked `` `taut ...` `` command in
    `render_default_persona(...)`, strip the leading `"taut "` prefix, and call
    `parse_command_line(command_body, syntax=core_command_syntax())` directly on
    the command string!
- `extensions/taut_summon/taut_summon/_driver.py` (`lines 1068-1076`) and
  `extensions/taut_summon/tests/test_pty_adapter.py` + `tests/test_driver.py`:
  - Guard `if not self._shutdown.is_set(): self._owner_phase = "spawn-ready"` and
    add `test_detach_matcher_completed_enhanced_atom_clears_pending_deadline` (`F6`).
- `docs/implementation/11-system-doctor.md` (`line 41`):
  - Replace `"the three exact search-work queue totals"` with
    `"the pending search-work queue total"`.
- `tests/test_docs_references.py` (`lines 110-125`) and `bin/check-doc-paths`
  (`lines 50-56, 107-125`):
  - Add `docs/coalescing.md` and `docs/plans/README.md` to
    `_markdown_path_sources()` and `_root_sources()`, setting
    `EXTRA_SOURCES: list[Path] = []` (`F7`).
- `docs/implementation/02-repository-map.md` and `03-agent-inventory.md`:
  - Align `bin/check-doc-paths` note and record today's `codex-cli 0.170.0`
    read-only + denied-write containment verification (`[DOM-13]`).

### Comprehension Questions (Answer in Execution Log Before Editing)

1. **Why must reconciliation close each `peek_generator()` after 100 rows while partitioning each slice into `<= max(2 MiB, largest item)` sub-batches with `projection_segments()` outside the write transaction and cross-generation classification before advancing `latest_revision`?**
   - *Expected answer*: SimpleBroker's `peek_generator()` retains the prior 1,000-row page across internal page transitions unless closed after each 100-row `islice`, and `[TAUT-6.4]` allows messages up to 10 MB. Closing `peek_generator()` every 100 rows preserves baseline peak source memory, sub-batching at `max(2 MiB, largest item)` bounds Taut's decoded check/text batch, keeping `projection_segments()` outside `sidecar(transaction=True)` avoids holding writer/generation locks during tokenization, and classifying every ID across `current_generation` and active `staging_generation` before bumping prevents a stale in-flight job from being rejected by `current` while accepted by `staging`.
2. **Why must `emit_notifications()` initialize `joined_names` and `channels_by_name` lazily inside the human-only mention branch rather than eagerly at function entry?**
   - *Expected answer*: `InboxCommand` calls `emit_notifications()` *after* `client.inbox()` has irreversibly claimed notification pointers, passing `client` in both `--json` and human modes. Eagerly calling `joined_thread_names()` / `list_threads()` would perform unnecessary database queries in `--json` mode and on DM-only or left-channel mentions, risking a post-claim exception that drops already-claimed JSON output.
3. **Why does `TautTranscript.get_selection()` slice displayed virtual rows directly instead of joining rows with `"\n"` and calling `Selection.extract()`?**
   - *Expected answer*: `Selection.extract()` splits its input with Python's `str.splitlines()`, which splits Unicode line/paragraph separators (`U+2028`, `U+2029`) even when Textual rendered them on a single visual row, shifting subsequent virtual `y` coordinates. Slicing `_selection_line(y, strips_by_option)` directly by virtual row `y` maps `(x, y)` 1-to-1 to displayed strips and avoids allocating `height` placeholder rows while memoizing `Visual.to_strips()` per selected option.

## 4. Invariants, Constraints, and Hidden Couplings

### What Must Not Change

1. **Program theory & adopted alternatives (`[THEORY-1]`–`[THEORY-5]`, `[THEORY-5.A1]`–`[THEORY-5.A6]`)**:
   No daemon, background indexer, lockfile, or altered storage permission model.
2. **Host identity wire format (`[IAN-3.2]`)**:
   macOS `capture_host_identity()` returns `HostIdentity(f"ioplatformuuid:{uuid}", label, "macOS IOKit platform UUID")`
   with the exact uppercase dashed UUID string produced by `IOPlatformUUID` in
   `ioreg`.
3. **Search schema, version-read steady state, manifest API version & producer contract (`[SRCH-4.1]`, `[SRCH-6.2]`, `[SRCH-7]`, `[SRCH-8.3]`)**:
   `_enqueue_search_job()` remains unconditional (`[SRCH-8.3]`).
   `SEARCH_SCHEMA_VERSION = 2`, `SEARCH_PROJECTION_VERSION = 1`, and
   `SEARCH_PROVIDER_API_VERSION = 1` remain unchanged; `schema_version() == SEARCH_SCHEMA_VERSION`
   performs zero installation DDL (`[SRCH-6.2]`); incompatible `taut-pg`
   providers fail closed in `load_search_provider()` with `SearchProviderUnavailableError`
   before search work starts.
4. **System doctor observation order (`[DOCT-4]`)**:
   `taut/_doctor.py` continues to observe `search_work` *after* `extension_state`.
5. **TUI inline vs body escaping & control-flow propagation (`[TUI-5.3]`, `[TUI-12.1]`, `[TUI-12.2]`, `[TAUT-6.4]`)**:
   Single-line inspector metadata uses `escape_inline_text`, message bodies use
   `escape_message_body`, `get_selection()` extracts exact displayed virtual
   rows, and control-flow `BaseException`s (`not isinstance(exc, Exception)`)
   propagate after `event.fail(exc)` releases any waiting worker.
6. **Ruff suppression inventory (`[DOM-10.2.1]`)**:
   Preserve exact approved suppression counts, specifically `[RUFF-SUP-052]`
   (`taut/identity.py::capture_host_identity`, `C901=1`) and `[RUFF-SUP-085]`
   (`TautApp.on_terminal_attach_confirmation_request`, `BLE001=1`).
7. **Pre-existing dirty file preservation**:
   Never modify, revert, or stage `skills/call-agent/SKILL.md`.

### Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## 5. Rollout, Rollback, and One-Way Doors

- **Rollout sequencing**: Core `taut-chat` and `taut-pg` ship in lockstep (per
  repository release policy `taut-chat==X.Y.Z`), and `_validate_provider()`
  fails closed with the install-or-upgrade diagnostic if mismatched in an
  editable/custom environment. Slices 1 -> 2 -> 3 -> 4 land together on `main`.
- **One-way doors**: None. `SEARCH_SCHEMA_VERSION` stays `2`; `taut_search_documents_thread_idx`
  on new/upgraded workspaces is an additive index ignored harmlessly by older
  versions (`[SRCH-6.2]`).
- **Rollback**: Clean `git revert` of the commit across the monorepo.
- **Observable post-deploy signals**:
  - `taut who` on macOS spawns zero `/usr/sbin/ioreg` child processes.
  - Warm `taut search --channel <small>` alongside an indexed `10,000`-message
    channel completes in `<50 ms` on SQLite (note: cold first search and
    `--reindex` still perform full generation rebuilds).
  - TUI `:log`, `:read`, `:inbox`, `:search`, `:message show`, `:list --dms`,
    and `Members` render formatted, escaped domain content.

## 6. Dependency-Ordered Tasks

### Slice 1: Identity & CLI Hot-Path Performance

1. **Write RED tests**:
   - In `tests/test_identity.py`:
     - Native Darwin test (`@pytest.mark.skipif(sys.platform != "darwin", ...)`):
       assert `identity._darwin_gethostuuid()` matches `/usr/sbin/ioreg -rd1 -c IOPlatformExpertDevice`'s
       `IOPlatformUUID` byte-for-byte, and `identity.capture_host_identity()`
       succeeds when `identity.subprocess.run` raises `AssertionError`.
     - Unit tests covering: (a) `_darwin_gethostuuid` primary path without
       spawning `ioreg`, (b) `/usr/sbin/ioreg` fallback when `_darwin_gethostuuid`
       returns `None`, and (c) `hostname:` fallback when both fail (updating
       `tests/test_cli.py:2127` as well).
     - `test_who_batches_selected_member_aliases_and_reuses_host_identity`:
       create 12 workspace members (each with 2 aliases in non-insertion order)
       where only 3 belong to `#ops`; spy on `identity.capture_host_identity`,
       `SqlSidecarTautState.list_member_aliases`, and wrap the underlying
       `Queue.sidecar` session on `client._meta_queue` to record executed SQL
       statements and bound parameters targeting `taut_member_aliases` (`R2-07`);
       assert `who("ops")` calls `capture_host_identity` at most once, calls
       `list_member_aliases` **0** times, executes **exactly 1**
       `SELECT ... FROM taut_member_aliases` SQL statement binding **only** the
       3 `#ops` `member_id`s, and returns exact sorted `aliases` and accurate
       `presence` (`here`/`gone`) (`F11`, `R2-07`).
   - In `tests/test_cli.py`:
     - `test_human_inbox_lazily_batches_thread_metadata_and_skips_json_or_ineligible`:
       (a) with 8 joined-channel `@bob` mentions across 3 channels, human `inbox`
       calls `joined_thread_names` once and `list_threads` once; (b) `--json`
       `inbox` calls `joined_thread_names` **0** times and `list_threads` **0**
       times; (c) human `inbox` with only DM notifications calls both **0**
       times; and (d) human `inbox` with mentions only in a left channel calls
       `joined_thread_names` once and `list_threads` **0** times (`F04`).
2. **Implement Slice 1**:
   - Update `taut/identity.py`, `taut/state/__init__.py`, `taut/state/_sql.py`,
     `taut/client/_identity.py`, and `taut/commands/_rendering.py` per §3 Slice 1.
3. **Stop-and-re-evaluate gate**:
   - Stop if `_darwin_gethostuuid()` differs from `ioreg`'s UUID formatting or
     if `bin/ruff_suppression_index.py --check` fails on `[RUFF-SUP-052]`.
4. **Verify Slice 1**:
   - `uv run --extra dev pytest tests/test_identity.py tests/test_cli.py tests/test_identity_performance.py -m "slow or not slow" -k "host_identity or who or inbox"`
   - `uv run --no-sync --extra dev python bin/ruff_suppression_index.py --check`

### Slice 2: Search Hot-Path Remediation, Provider Compatibility Check & Tombstone Projection Version

1. **Write RED tests**:
   - In `tests/test_search_discovery.py` (`F03`, `R2-04`, `R3-02`, `R4-03`):
     - Add tests proving `_validate_provider()` rejects: (a) a provider missing
       `reconcile_unchanged_batch`, (b) a provider missing `threads` on `query()`,
       and (c) parametrized positional-only + `**kwargs` providers covering **all
       four** validated parameter names — `revision` on `reconcile_unchanged_batch`,
       and `before`, `threads`, and `limit` on `query()` — raising
       `SearchProviderUnavailableError` with the install-or-upgrade diagnostic
       before search work runs.
   - In `tests/test_search.py` and `extensions/taut_pg/tests/test_pg_integration.py`
     (`F5`, `F01`, `F02`, `F09`, `R2-01`, `R2-02`, `R2-06`, `R3-01`, `R4-01` — kept in
     `pg_only`-collected `test_pg_integration.py` so `.github/workflows/test-pg-extension.yml`
     and `uv run ./bin/pytest-pg` execute every PG test in CI!):
     - Tombstone `SEARCH_PROJECTION_VERSION` (`F5`, `R2-06`): monkeypatch
       `SEARCH_PROJECTION_VERSION` to `2` in `taut.search._sqlite` and
       `taut_pg._search`, drive the pending-job drain directly via
       `taut.search._worker.process_one(...)` (before any reconciliation scan
       runs!) as well as direct `provider.delete_document(...)` and a
       recording-session unit assertion in `test_pg_integration.py`, asserting
       the drain itself writes `projection_version == 2` and `indexed == 0`/`False`!
     - Index DDL, schema-1 upgrade & pre-fix schema-2 no-DDL test (`F01`, `R2-06`):
       assert (a) fresh initialization creates `taut_search_documents_thread_idx`
       (`EXPLAIN QUERY PLAN` on `indexed_message_ids("general")` uses
       `taut_search_documents_thread_idx`), (b) upgrading a `schema_version == 1`
       workspace to schema 2 creates `taut_search_documents_thread_idx`, and
       (c) a pre-fix `schema_version == 2` database from which
       `taut_search_documents_thread_idx` has been dropped continues to search
       cleanly with **zero** `CREATE INDEX` DDL executed (`taut_search_documents_thread_idx`
       stays absent in `sqlite_master` / `pg_indexes`).
     - Bounded per-100 generator close, sub-batch byte cap & cross-generation
       fence tests (`F02`, `F09`, `R2-01`, `R2-02`, `R3-01`, `R4-01`):
       1. Row-cap, generator-close, small-to-large & oversized-singleton test
          (`R4-01`, `R5-01`): seed 110 small (`100 B`) messages followed by 3 x
          `900 KiB` messages and 1 x `2.5 MiB` singleton message (`114` total),
          wrap `Queue.peek_generator` to track `open_generators` count and
          verify each generator yields at most `100` items and is **already
          closed (`open_generators == 0`) at the moment `reconcile_unchanged_batch`
          and `projection_segments` execute** (`R5-01`), spy on
          `reconcile_unchanged_batch` to assert every batch has `len(checks) <= 100`
          (the first 100 small messages flush at the 100-row cap!) and
          `sum(c.text_bytes) <= max(2 MiB, max(c.text_bytes for c in checks))`
          (the `2.5 MiB` singleton forms a 1-item batch while the `900 KiB`
          items never exceed `2 MiB` together), and assert `projection_segments`
          is never called while a `sidecar(transaction=True)` session is active!
       2. Quiescent fast path + cross-generation fence tests on **both** SQLite
          and live PG (`R2-02`):
          - 300 unchanged messages -> `0` `projection_segments` calls, `<= 6`
            write transactions (3 batches of 100 + cursor step),
            `latest_revision == scan_revision`.
          - Newer tombstone (`latest_revision > scan_revision`) -> neither
            resurrected nor downgraded.
          - Matching `current_generation` + matching active `staging_generation`
            (`scan_revision >= staging_scan_revision`) -> both generations
            advance `latest_revision = scan_revision` with `0` projections.
          - **Mixed `current_generation` match + mismatched/missing active
            `staging_generation`** (`R2-02`): assert `reconcile_unchanged_batch`
            does **not** bump `current_generation` prematurely, returns the ID
            in `needs_replace` (`len(needs_replace) == 1`), and subsequent
            `replace_document(..., revision=scan_revision)` updates both
            `current_generation` and `staging_generation` atomically so an
            interleaved older job (`job_revision < scan_revision`) is rejected
            in **both** generations!
     - SQL predicate pushdown test (`F09`): spy on executed SQL + bound params
       in `SQLiteSearchProvider.query()` and `PostgresSearchProvider.query()` to
       prove `d.thread IN` and `d.message_ts <` execute in SQL and return exact
       matching candidate IDs (including multi-chunk intersection before `limit`).
2. **Implement Slice 2**:
   - Update `taut/search/_provider.py`, `taut/search/_discovery.py`,
     `taut/search/_sqlite.py`, `extensions/taut_pg/taut_pg/_search.py`,
     `taut/client/_searching.py`, `tests/test_search_discovery.py`, and
     `tests/test_search_worker.py` per §3 Slice 2.
3. **Stop-and-re-evaluate gate**:
   - Stop if `projection_segments()` runs inside an open `sidecar(transaction=True)`,
     if a `peek_generator` stays open across `> 100` items, if Taut's sub-batch
     exceeds `100` rows or `max(2 MiB, largest item)`, or if
     `reconcile_unchanged_batch` mutates `current_generation` for an ID that
     needs repair in `staging_generation`.
4. **Verify Slice 2**:
   - `uv run --extra dev pytest tests/test_search.py tests/test_search_client.py tests/test_search_discovery.py tests/test_search_worker.py`
   - `uv run ./bin/pytest-pg`

### Slice 3: `taut-tui` Inspector, Tail-Append Transcript, Displayed-Row Selection & Summon Lifecycle

1. **Write RED tests**:
   - In `extensions/taut_tui/tests/test_tui_app.py` and `test_tui_action_handlers.py`
     (`F06`, `R2-05`, `R3-03`, `R4-02`):
     - Test `:log general --limit 2`, `:read general`, `:message show <ts>`,
       `:search <term>` (including a DM search hit asserting actor-scoped DM
       label), `:who`, `Members` (`ActionId.MEMBERS_OPEN` asserting `here`/`gone`
       presence per `[TUI-6.4]`), and `:list --dms`.
     - Test unified `:inbox` session feed, 200-item claim cap, monotonic `ts`
       retention & interleaving freshness (`R2-05`, `R3-03`, `R4-02`):
       (a) empty session `:inbox` shows `"No notifications claimed this session."`
           and `domain.inbox().result()` returns `[]` (`test_tui_domain.py:177`);
       (b) with 250 pending notification pointers in `notify.<member_id>`,
           `session.claim_inbox().result()` claims exactly `200`
           (`_NOTIFICATION_FEED_LIMIT`), leaving `50` unclaimed in the queue;
       (c) **claim-to-append interleaving eviction test (`R4-02`)**: simulate or
           barrier `claim_inbox()` after claiming older pointers `1..200`
           (`ts=1..200`) so watcher delivery `201` (`ts=201`) appends and renders
           first, then let `claim_inbox()` append `1..200` and render -> assert
           item `201` (`ts=201`) is **retained** at the tail of
           `session.notification_feed()` (oldest item `1` is evicted instead of
           newer item `201`!) and remains visible in `#inspector-body`;
       (d) post-append callback interleaving: watcher delivery `N2` arriving
           between worker `claim_inbox()` (`N1`) and UI callback leaves **both
           `N1` and `N2`** visible; and after watcher claims `N1`, `:inbox` on
           an empty queue still displays `N1`.
     - Test hostile metadata/body escaping: foreign message/notification with
       `from_name="alice\ninjected-header"` and body containing `\t` and `\n`
       plus ANSI CSI escapes -> assert `from_name`'s `\n` is escaped inline on
       one line while body `\n` breaks lines and `\t` expands cleanly!
     - Test tail-only `Option` construction (`F07`): in a tail-pinned
       30-message `#general` view, deliver 1 live message and assert
       `clear_options` is not called and `_message_prompt` runs once; also
       verify `HISTORY` viewport anchor preservation, search-anchor open,
       selection preservation, and that `_apply_navigation_result()` skips
       `_render_messages()` when `reply_threads` is unchanged.
   - In `extensions/taut_tui/tests/test_tui_selection.py` (`F3`, `F08`):
     - Add `test_transcript_get_selection_renders_only_selected_options_once`,
       `test_transcript_get_selection_boundary_matrix`, and
       `test_transcript_get_selection_preserves_displayed_row_after_unicode_line_separator`
       (row 0 contains `"alpha\u2028beta"` rendered on 1 visual row, row 1
       contains `"gamma"`; selecting row 1 returns exact literal `"gamma"`).
   - In `extensions/taut_tui/tests/test_tui_summon.py` (`F1`, `F2`, `F05`, `R2-03`):
     - Add `test_stop_owned_and_wait_stops_handle_arriving_at_on_ready`,
       `test_stop_owned_and_request_owned_stops_linearize_with_on_ready_under_lock`,
       `test_setup_recovery_offer_second_modal_push_failure_fails_request`, and
       `test_setup_recovery_offer_second_modal_push_propagates_control_flow_after_failing_request`
       (raising `asyncio.CancelledError` on the deferred second `push_screen`
       marks `event.resolved.is_set()` with `event.error` AND propagates
       `CancelledError`).
2. **Implement Slice 3**:
   - Update `extensions/taut_tui/taut_tui/session.py`, `domain.py`, `app.py`,
     `summon.py`, and `widgets.py` per §3 Slice 3.
3. **Stop-and-re-evaluate gate**:
   - Stop if Ruff `BLE001`/`RUF100` or `bin/ruff_suppression_index.py --check`
     reports any change on `[RUFF-SUP-085]`, or if any viewport/resize test in
     `extensions/taut_tui/tests/` fails.
4. **Verify Slice 3 (including P1 mutation checks)**:
   - `uv run --project extensions/taut_tui --extra dev ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests`
   - `uv run --no-sync --extra dev python bin/ruff_suppression_index.py --check`
   - `uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests -n 2 --dist loadfile`
   - Run one-line mutation checks on `or current.cancel.is_set()`, `with self._lock:`,
     and `run_guarded` in `decide_offer`, restoring all three afterward.

### Slice 4: `taut-summon` Persona Fix, Matcher/Driver Hygiene, Doctor Note & Doc Gate

1. **Write RED tests**:
   - In `extensions/taut_summon/tests/test_persona.py` (`F10`):
     - Extract inline `` `taut ...` `` snippets from `render_default_persona(...)`,
       strip leading `"taut "`, and call
       `parse_command_line(snippet, syntax=core_command_syntax())` on each;
       verify RED failure at baseline (`missing required value: msg_id`) and
       assert the rendered text explicitly notes substituting the parent channel
       and real 19-digit origin ID.
   - In `extensions/taut_summon/tests/test_pty_adapter.py` and `tests/test_driver.py`:
     - Add `test_detach_matcher_completed_enhanced_atom_clears_pending_deadline`
       (with mutation check on `_pty.py:782`) and
       `test_initial_attach_decline_does_not_advance_owner_phase_after_shutdown`
       (`F6`).
   - In `tests/test_docs_references.py`:
     - Assert `Path("docs/coalescing.md")` and `Path("docs/plans/README.md")`
       are in `_markdown_path_sources()` (`F7`).
2. **Implement Slice 4**:
   - Update `extensions/taut_summon/taut_summon/_persona.py:86`,
     `extensions/taut_summon/taut_summon/_driver.py:1075`,
     `docs/implementation/11-system-doctor.md:41`,
     `docs/implementation/02-repository-map.md`,
     `docs/implementation/03-agent-inventory.md`,
     `docs/implementation/04-taut-architecture.md`,
     `docs/implementation/09-search-architecture.md`,
     `docs/implementation/12-taut-tui.md`,
     `tests/test_docs_references.py`, and `bin/check-doc-paths`.
3. **Verify Slice 4**:
   - `uv run --directory extensions/taut_summon --extra dev pytest tests/test_persona.py tests/test_driver.py tests/test_pty_adapter.py`
   - `uv run bin/check-doc-paths && uv run bin/check-doc-paths --self-test`
   - `uv run bin/check-cli-claims && uv run bin/check-plan-status-index && uv run bin/check-plan-status-index --self-test`
   - `uv run --extra dev pytest tests/test_docs_references.py tests/test_cli_claims.py tests/test_system_doctor.py`

## 7. Testing Plan and Anti-Mocking Rules

- Real temporary SQLite databases and real Docker PostgreSQL 18
  (`uv run ./bin/pytest-pg`, running `pg_only`-marked
  `extensions/taut_pg/tests/test_pg_integration.py` on the exact CI lane).
- Real Textual `TautApp` / `TautTranscript` / `ConfirmationScreen` under
  `run_test()`.
- No `time.sleep` synchronizers; use `threading.Event` barriers and
  `_MatcherClock`.

## 8. Final Verification and Gates

Run the full CI workflow gates plus the stricter `bin/release.py` precheck
type-check targets (`PG_MYPY_PATHS` including `extensions/taut_pg/tests/conftest.py`
and TUI `mypy`, per `F12` & `R2-07`):

```bash
uv run --extra dev ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev ruff format --check taut tests extensions bin
uv run --project extensions/taut_tui --extra dev ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_mcp --extra dev ruff check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --no-sync --extra dev python bin/ruff_suppression_index.py --check
uv run --extra dev mypy taut tests bin/release.py bin/release-artifact.py bin/require-green-workflows.py --config-file pyproject.toml
uv run --extra dev mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_pg/tests/conftest.py --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_summon/tests/conftest.py --config-file pyproject.toml
uv run --project extensions/taut_tui --extra dev mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests --config-file extensions/taut_tui/pyproject.toml
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
uv run bin/check-plan-status-index && uv run bin/check-plan-status-index --self-test
uv run bin/check-doc-paths && uv run bin/check-doc-paths --self-test
uv run bin/check-cli-claims && uv run bin/check-dom15-fixtures
uv run bin/coalesce-check
uv run --extra dev pytest -m "not installed_wheel"
uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests -n 2 --dist loadfile
uv run --directory extensions/taut_summon --extra dev pytest -m "not requires_live_harness and not requires_local_llm"
uv run --directory extensions/taut_mcp --extra dev pytest -m "not pg_only and not installed_wheel"
uv run ./bin/pytest-pg
git diff --check
```

## 9. Out of Scope

- New CLI commands or flags (`taut onboard`, `taut whoami --show-token`,
  `taut join --recent`, `taut say --join`, `taut mcp --workspace/--token`,
  `taut summon` provider flags) — owned by Phases 1, 2A, 2B, and 3.
- Cold-search / `--reindex` rebuild batching (noted in Round-1 observations;
  warm reconciliation is the hot path addressed here).
- Upstream SimpleBroker `Queue.peek_generator()` internal 1,000-row page sizing
  (`PEEK_BATCH_SIZE = 1000`); Phase 0 preserves baseline's per-100
  `peek_generator()` + `close()` read loop verbatim so peak source memory stays
  at or below baseline (`R4-01`), while partitioning each 100-row slice into
  `max(2 MiB, largest item)` sub-batches.
- Changing `[SRCH-8.3]` unconditional `taut.search_index` enqueueing on source
  writes, `[DOCT-4]` two-pass observation ordering, or `[TAUT-5]` exit codes.
- `bin/coalesce-check` plan-tier counts and full zombie-plan status sweep (`F8`,
  deferred cleanly to Phase 3).
- Modifying or staging `skills/call-agent/SKILL.md`.

## 10. Independent Review Loop

- **Author family**: Gemini (`Antigravity`).
- **Reviewer family**: OpenAI (`codex`, `codex-cli 0.170.0`, verified read-only +
  OS-sandboxed write-denial containment on `2026-11-23`).
- **Rejected alternatives in force**: `[THEORY-5.A1]` through `[THEORY-5.A6]`
  in `docs/program-theory.md`.

## 11. Fresh-Eyes Review

Re-read in full on 2026-11-23 after incorporating all Round-1 (`F01`–`F12`) and
Round-2 (`R2-01`–`R2-07`) `codex` findings:

1. Confirmed source scans use adaptive `Queue.peek_many` starting at `limit=8`
   instead of `Queue.peek_generator`'s 1,000-item buffer (`R2-01`), and
   `reconcile_unchanged_batch` classifies across all writable generations before
   applying any revision bump (`R2-02`).
2. Confirmed the two-clause `except Exception` (`# noqa: BLE001`) +
   `except BaseException` (`raise`) handler passes Ruff 0.17.4 `BLE001,RUF100`
   with zero suppression-count change (`R2-03`), `_validate_provider()` binds
   actual call shapes (`R2-04`), and `TuiSession.claim_inbox()` unifies manual
   `:inbox` and live watcher notifications into one session feed (`R2-05`).
3. Confirmed all PG search tests live in `pg_only`-executed `test_pg_integration.py`
   with direct `process_one` drain and pre-fix schema-2 coverage (`R2-06`), and
   `who(thread)` asserts exact sidecar SQL statement count and bound params
   (`R2-07`). *(Addendum after Round 4 `R4-01`: point 1's `peek_many` approach was
   superseded by baseline's per-100 `peek_generator()` + `close()` loop plus
   `<= max(2 MiB, largest item)` sub-batches; see §3 Slice 2 and §12 Round 4.)*

## 12. Review Log

### Round 1 — Pre-Implementation Plan Review (`codex-cli 0.170.0`, 2026-11-23)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase0_plan_review_msg.txt --json - < phase0_plan_review_prompt.txt`
- **Verdict**: `BLOCKED` (12 findings: `F01`–`F02` `[P1]`, `F03`–`F10` `[P2]`, `F11`–`F12` `[P3]`).
- **Dispositions**:
  - `F01` (`[P1]`, schema-2 index backfill vs `[SRCH-6.2]`): **Accepted — fixed in plan** (§1, §3 Slice 2, §4, §6 Slice 2). Dropped runtime schema-2 DDL backfill; `taut_search_documents_thread_idx` is created in `_DDL` during fresh init and schema-1 upgrades only.
  - `F02` (`[P1]`, 250-row memory bound + tokenization inside write lock): **Accepted — fixed in plan** (§1, §3 Slice 2, §6 Slice 2; further tightened in Round 2 `R2-01` & `R2-02`).
  - `F03` (`[P2]`, cross-package `SearchProvider` discovery mismatch): **Accepted — fixed in plan** (§3 Slice 2, §5, §6 Slice 2; tightened in Round 2 `R2-04`).
  - `F04` (`[P2]`, eager `inbox` lookup in `--json` and DM/left mentions): **Accepted — fixed in plan** (§3 Slice 1, §6 Slice 1). Lazy human-only `_MentionLookupCache` with zero lookups on `--json` and DM-only cases, and 1 membership lookup + 0 `list_threads()` calls on left-channel mentions.
  - `F05` (`[P2]`, control-flow `BaseException` swallowing in `decide_offer`): **Accepted — fixed in plan** (§3 Slice 3, §4, §6 Slice 3; Ruff-compatible two-clause handler verified in Round 2 `R2-03`).
  - `F06` (`[P2]`, inspector LF injection, body tab/escape decoding, DM labels, empty `:inbox`): **Accepted — fixed in plan** (§3 Slice 3, §6 Slice 3; session-feed unification added in Round 2 `R2-05`).
  - `F07` (`[P2]`, `O(delta)` overclaim on `_render_messages`): **Accepted — fixed in plan** (§1, §3 Slice 3, §6 Slice 3).
  - `F08` (`[P2]`, `U+2028` `splitlines()` coordinate drift in `get_selection`): **Accepted — fixed in plan** (§3 Slice 3, §6 Slice 3).
  - `F09` (`[P2]`, search test gaps): **Accepted — fixed in plan** (§6 Slice 2; CI lane & drain proof refined in Round 2 `R2-06`).
  - `F10` (`[P2]`, `parse_command_line` signature & illustrative `msg_id` note in `_persona.py`): **Accepted — fixed in plan** (§3 Slice 4, §6 Slice 4).
  - `F11` (`[P3]`, `who(thread)` workspace-wide alias fetch & weak spy): **Accepted — fixed in plan** (§3 Slice 1, §6 Slice 1; sidecar SQL spy added in Round 2 `R2-07`).
  - `F12` (`[P3]`, full `HEAD` SHA, line anchors, missing `test_notifications.py`, `mypy` targets): **Accepted — fixed in plan** (§2, §3 Slice 1, §6 Slice 1, §8; CI vs release-gate notes clarified in Round 2 `R2-07`).

### Round 2 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-23)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase0_plan_review_r2_msg.txt --json - < phase0_plan_review_r2_prompt.txt`
- **Verdict**: `FAIL` (`R2-01`–`R2-03` `[P1]`, `R2-04`–`R2-06` `[P2]`, `R2-07` `[P3]`).
- **Dispositions**:
  - `R2-01` (`[P1]`, `Queue.peek_generator()` buffers 1,000 items inside SimpleBroker): **Accepted — fixed in plan** (§3 Slice 2, §6 Slice 2). Replaced `peek_generator()` with adaptive `Queue.peek_many(limit=...)` starting at `limit=8` and clamping subsequent pages by `_RECONCILE_BATCH_MAX_BYTES // max_page_item_bytes`.
  - `R2-02` (`[P1]`, premature `current_generation` bump when `staging_generation` mismatches): **Accepted — fixed in plan** (§3 Slice 2, §6 Slice 2). `reconcile_unchanged_batch()` classifies every ID across all writable generations before executing any `UPDATE`, deferring mixed `current`/`staging` mismatches to atomic `replace_document()`.
  - `R2-03` (`[P1]`, Ruff 0.17.4 `RUF100` on conditional `raise` inside `# noqa: BLE001`): **Accepted — fixed in plan** (§3 Slice 3, §6 Slice 3). Replaced with a two-clause `except Exception` (`# noqa: BLE001`) + `except BaseException` (`event.fail(exc); raise`), empirically verified exit 0 under Ruff 0.17.4 `BLE001,RUF100`.
  - `R2-04` (`[P2]`, positional-only `threads` bypasses parameter-name check): **Accepted — fixed in plan** (§3 Slice 2, §6 Slice 2). `_validate_provider()` binds actual call shapes via `inspect.signature(...).bind(...)`.
  - `R2-05` (`[P2]`, `domain.inbox()` claims separately from `TuiSession._notification_feed`): **Accepted — fixed in plan** (§3 Slice 3, §6 Slice 3). Added `TuiSession.claim_inbox()` appending claimed pointers into `_notification_feed` under `_state_lock` and returning the unified session feed.
  - `R2-06` (`[P2]`, unmarked PG module outside CI, drained-delete vs reconciliation proof, pre-fix schema-2 without index test): **Accepted — fixed in plan** (§6 Slice 2, §7). Kept all PG search tests in CI-executed `test_pg_integration.py`, drove `process_one()` directly for tombstone proof, and added explicit pre-fix schema-2 without-index + schema-1 upgrade index tests.
  - `R2-07` (`[P3]`, sidecar SQL count spy on `list_aliases_for_members`, CI vs release-gate `mypy` labeling, `F04` log wording): **Accepted — fixed in plan** (§6 Slice 1, §8, §12).

### Round 3 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-23)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase0_plan_review_r3_msg.txt --json - < phase0_plan_review_r3_prompt.txt`
- **Verdict**: `FAIL` (`R2-02`, `R2-03`, `R2-07` passed; 4 remaining items `R3-01`–`R3-04`).
- **Dispositions**:
  - `R3-01` (`[P1]`, `peek_many(limit=250)` small-to-large `2.44 GiB` page & `[SRCH-10.1]` `peek_generator()` contract): **Accepted — fixed in plan** (§1, §3 Slice 2, §6 Slice 2, §9). Restored single-stream `closing(queue.peek_generator(...))` per `[SRCH-10.1]` (eliminating baseline's 10x reopen amplification and declaring SimpleBroker's pre-existing `PEEK_BATCH_SIZE = 1000` upstream behavior unchanged/out-of-scope), kept Taut's own batch row cap at `<= 100` (matching baseline) + `<= 2 MiB`, and added a small-to-large transition batch test.
  - `R3-02` (`[P2]`, positional-only parameter + `**kwargs` bypasses `signature.bind()`): **Accepted — fixed in plan** (§3 Slice 2, §6 Slice 2). `_validate_provider()` checks `sig.parameters[name].kind in {POSITIONAL_OR_KEYWORD, KEYWORD_ONLY}` in addition to `sig.bind(...)`, with `**kwargs` positional-only rejection tests.
  - `R3-03` (`[P2]`, `client.inbox()` 1,000-claim cap vs 200-item `_notification_feed`, UI render race, and `test_tui_domain.py` `list[Notification]` return type): **Accepted — fixed in plan** (§3 Slice 3, §6 Slice 3). `TuiSession.claim_inbox()` claims `limit=_NOTIFICATION_FEED_LIMIT` (`200`), returns `list[Notification]`, and `_run_inbox_action` reads `self._session.notification_feed()` on the UI thread at render time, with 250-item cap and interleaved watcher/callback tests.
  - `R3-04` (`[P2]`, `uv run ./bin/pytest-pg` path): **Accepted — fixed in plan** (§6 Slice 2, §7, §8). Replaced `uv run pytest-pg` with `uv run ./bin/pytest-pg`.

### Round 4 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-23)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase0_plan_review_r4_msg.txt --json - < phase0_plan_review_r4_prompt.txt`
- **Verdict**: `FAIL` (`R3-04` passed; 3 remaining items `R4-01`–`R4-03`).
- **Dispositions**:
  - `R4-01` (`[P1]`, continuous `peek_generator()` retains two 1,000-row pages in SimpleBroker 8.8.1 + `max(2 MiB, largest item)` singleton bound + 100-row test): **Accepted — fixed in plan** (§1, §3 Slice 2, §6 Slice 2, §9). Preserved baseline's per-100 `peek_generator()` + `islice(..., 100)` + `close()` loop verbatim (freeing SimpleBroker's internal page before the next fetch), partitioned each 100-row slice into `<= max(2 MiB, largest item)` sub-batches cleared before the next outer iteration, and updated the test to 114 items covering the 100-row cap, per-100 generator close, `900 KiB` byte flush, and `2.5 MiB` singleton.
  - `R4-02` (`[P2]`, older manual `claim_inbox` batch `1..200` appended after watcher item `201` evicts newer item `201`): **Accepted — fixed in plan** (§3 Slice 3, §6 Slice 3). Added `_record_notifications_locked()` ordering merged entries by `(item.ts is None, item.ts or 0, seq)` and retaining `merged[-200:]` so older batch appends evict item `1` instead of newer watcher item `201`, with a dedicated claim-to-append interleaving test.
  - `R4-03` (`[P3]`, missing firing positional-only + `**kwargs` tests for `before` and `limit`): **Accepted — fixed in plan** (§6 Slice 2). Parametrized the rejection test across all four validated parameter names (`revision`, `before`, `threads`, `limit`).

### Round 5 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-23)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase0_plan_review_r5_msg.txt --json - < phase0_plan_review_r5_prompt.txt`
- **Verdict**: `FAIL` (`R4-02` and `R4-03` passed; 1 test-assertion tightening `R5-01` on `R4-01`).
- **Disposition**:
  - `R5-01` (assert `peek_generator` is already closed when `reconcile_unchanged_batch` and `projection_segments` execute, rather than only before the next generator opens): **Accepted — fixed in plan** (§6 Slice 2). Both spies assert `open_generators == 0`.

### Round 6 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-23)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase0_plan_review_r6_msg.txt --json - < phase0_plan_review_r6_prompt.txt`
- **Verdict**: **`PASS`** (`R5-01` verified resolved; no new defects). Plan promoted to `active` and predecessor `2026-10-15-deep-review-remediation-plan.md` marked `superseded`.

### Post-Implementation Review Round 1 (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase0_impl_review_msg.txt --json - < phase0_impl_review_prompt.txt`
- **Verdict**: `BLOCKED` (`blocker: F1, F2, F3`; 3 `[P2]` findings `F1`–`F3`, 4 `[P3]` findings `F4`–`F7`).
- **Dispositions**:
  - `F1` (`[P2]`, `extensions/taut_tui/taut_tui/app.py:3315` unchanged navigation refresh called `_render_messages`, advancing `viewport.generation` and scheduling `HISTORY` prompt height rebuilds): **Accepted — fixed in code & tests**. Restored `if self._message_rows and reply_threads != previous_reply_threads:` in `_apply_navigation_result()`, updated `extensions/taut_tui/tests/test_tui_chat.py` to seed a genuine reply-thread change when testing navigation-triggered reply badge updates, and updated `extensions/taut_tui/tests/test_tui_app.py` (`test_transcript_tail_append_skips_clear_options_and_redundant_nav_rerender`) to flush scheduled refreshes in `HISTORY` mode and assert `render_calls == 0`, `prompt_calls == 0`, and unchanged `viewport.generation` (verified with a 1-line mutation kill `rc=1`).
  - `F2` (`[P2]`, `extensions/taut_tui/tests/test_tui_action_handlers.py` depended on test-runner process ancestry for member presence/kind): **Accepted — fixed in tests**. Added `_deterministic_alice_bob_captures()` seeding deterministic `human` (`alice`, live PID -> `active`) and `agent` (`bob`, dead PID -> `gone`) `IdentityCapture` evidence in both `test_every_action_reaches_a_concrete_handler` (`MEMBERS_OPEN`) and `test_inspector_formats_domain_records_and_escapes_hostile_metadata` (`:who`), asserting exact `"alice  active  human"` and `"bob  gone  agent"` rows.
  - `F3` (`[P2]`, `extensions/taut_tui/tests/test_tui_app.py` inserted directly via `_record_notifications_locked` instead of driving the real `TautWatcher`): **Accepted — fixed in tests**. Both session and UI subcases in `test_inbox_command_unifies_session_feed_caps_at_200_and_retains_newest_ts` now open `#general` and drive live `@alice` deliveries (`charlie`, `charlie-live`) through the real `TautWatcher` while `TautClient.inbox` is fenced (verified with a 1-line mutation kill `rc=1` restoring `self._notification_feed.append(item)` in `session.py:418`).
  - `F4` (`[P3]`, `tests/test_search.py` and `extensions/taut_pg/tests/test_pg_integration.py` checked only final row's `latest_revision`): **Accepted — fixed in tests**. Both warm-scan tests now assert `{row["latest_revision"] for row in rows} == {scan_rev}` across all 300 seeded message IDs.
  - `F5` (`[P3]`, `tests/test_cli.py` DM subcase sent `"hello in dm"`, creating a DM-start pointer rather than a DM mention): **Accepted — fixed in tests**. Updated DM body to `"hello @bob in dm"` while preserving zero-lookup assertions.
  - `F6` (`[P3]`, `docs/implementation/09-search-architecture.md` omitted SQLite `> 500` Python thread-filter cutoff): **Accepted — fixed in docs**. Documented SQLite `<= 500` SQL `IN (...)` pushdown + `> 500` Python fallback alongside PostgreSQL `IN` / `= ANY(...)` pushdown.
  - `F7` (`[P3]`, §13 Execution Log ended at Pre-Edit Comprehension Check): **Accepted — fixed in plan** (§13 below).

### Post-Implementation Review Round 2 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase0_impl_review_r2_msg.txt --json - < phase0_impl_review_r2_prompt.txt`
- **Verdict**: `FAIL` (`F1`, `F2`, `F6` passed with zero production defects; test-only tightenings requested on `F3`, `F4`/`F7`, and `F5`).
- **Dispositions**:
  - `F3` (watcher gate installed after `open_conversation` / `CONVERSATION_OPEN` allowed an in-progress turn to race `hold_watcher.clear()`, and UI waits did not assert return value): **Accepted — fixed in tests**. Installed `BaseReactor.process_once` gate before watcher startup in both session and UI subcases, serialized `orig_process_once` under a turn lock (`watcher_turn_lock` / `ui_turn_lock`) when clearing `hold_watcher`, and added `assert` on both `asyncio.to_thread(...)` event waits.
  - `F4` / `F7` (`rev_by_ts` checked uniform `after_rev > before_rev` rather than comparing against the exact `scan_rev` allocated by `META_QUEUE_NAME.generate_timestamp()`): **Accepted — fixed in tests**. Both `tests/test_search.py` and `extensions/taut_pg/tests/test_pg_integration.py` now capture `allocated_revisions` from `Queue.generate_timestamp` on `META_QUEUE_NAME` during `client.search(...)` and assert `len(allocated_revisions) == 1` and `set(rev_by_ts.values()) == {scan_rev}`.
  - `F5` (assert rendered mention line in DM subcase stdout): **Accepted — fixed in tests**. Added `assert "alice mentioned you in dm." in out.getvalue()` in `tests/test_cli.py`.

### Post-Implementation Review Round 3 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase0_impl_review_r3_msg.txt --json - < phase0_impl_review_r3_prompt.txt`
- **Verdict**: **`PASS`** (`F3`, `F4`/`F7`, and `F5` verified resolved; no new defects). Plan status promoted to `completed`.

## 13. Execution Log

### Pre-Edit Comprehension Check (2026-11-23)

1. **Q1 (`reconcile_unchanged_batch` batching, generator close, out-of-lock projection & cross-generation classification)**:
   SimpleBroker 8.8.1's `peek_generator()` retains the prior 1,000-row page across internal page transitions unless closed after each 100-row `islice`, and `[TAUT-6.4]` allows messages up to 10 MB. Closing `peek_generator()` every 100 rows preserves baseline peak source memory, sub-batching at `<= max(2 MiB, largest item)` bounds Taut's decoded check/text batch, keeping `projection_segments()` outside `sidecar(transaction=True)` avoids holding SQLite's writer lock or PostgreSQL's singleton `FOR UPDATE` lock during CPU tokenization, and classifying each ID across `current_generation` and active `staging_generation` before applying any `latest_revision` bump prevents an interleaved stale job (`job_revision < scan_revision`) from being rejected by `current` while accepted by `staging`.
2. **Q2 (`emit_notifications` lazy human-only metadata lookup)**:
   `InboxCommand` calls `emit_notifications()` *after* `client.inbox()` has irreversibly claimed pointers, passing `client` in both `--json` and human modes. Lazily populating `joined_names` only on the first human non-DM mention and `channels_by_name` only when `thread in joined_names` preserves 0 extra lookups on `--json` and DM-only claims (and 0 `list_threads` calls on left-channel mentions) while collapsing `K` joined-channel mentions to 1 lookup each.
3. **Q3 (`TautTranscript.get_selection` direct displayed-row slicing)**:
   `Selection.extract()` calls `str.splitlines()`, which splits Unicode `U+2028`/`U+2029` line/paragraph separators even when Textual rendered them on one visual row, shifting subsequent virtual `y` coordinates. Slicing `_selection_line(y, strips_by_option)` directly by virtual row `y` maps `(x, y)` 1-to-1 to displayed rows and memoizes `Visual.to_strips()` per selected option.

### Slice Implementation & Verification Evidence (2026-11-23 to 2026-11-24)

1. **Slice 1 (Identity & CLI Hot-Path Performance)**:
   - Implemented `_darwin_gethostuuid()` via stdlib `ctypes` in `taut/identity.py` (`15.2x` speedup on selector-free `TautClient.say`: `15.402 ms/call` -> `1.014 ms/call` in `tests/test_identity_performance.py`), `StateRepository.list_aliases_for_members()` in `taut/state/` + `taut/client/_identity.py` (`who(thread)` reduced to 1 `capture_host_identity()` call and 1 batched `IN (?, ...)` alias query), and lazy human-only `_MentionLookupCache` in `taut/commands/_rendering.py`.
   - Verified with `pytest tests/test_identity.py tests/test_identity_performance.py tests/test_who.py tests/test_cli.py tests/test_notifications.py` (all passed).
2. **Slice 2 (Search Hot-Path, Discovery & Tombstone Fencing)**:
   - Implemented `DocumentCheck`, `SearchProvider.reconcile_unchanged_batch()`, and `query(..., threads=...)` across `taut/search/_provider.py`, `taut/search/_sqlite.py`, `extensions/taut_pg/taut_pg/_search.py`, and `taut/client/_searching.py`; tightened `taut/search/_discovery.py` parameter-kind + signature binding validation; added `SEARCH_PROJECTION_VERSION` predicate to delete tombstones; added `taut_search_documents_thread_idx` to fresh/schema-1 `_DDL` without schema-2 runtime DDL.
   - Verified across SQLite (`pytest tests/test_search.py tests/test_search_discovery.py tests/test_search_worker.py`) and live Docker PostgreSQL 18 (`./bin/pytest-pg`, 289 shared + 53 `pg_only` = 342 passed).
3. **Slice 3 (`taut-tui` Inspector, Unified Session Inbox, Incremental Tail Render, Selection & Summon Lifecycle)**:
   - Implemented `TuiSession.claim_inbox()` + monotonic `_record_notifications_locked()` (`_NOTIFICATION_FEED_LIMIT = 200`), inline-escaped vs body-escaped `DisplayText` inspector formatters, `allow_incremental=True` tail append + unchanged-`reply_threads` navigation skip in `TautApp`, direct virtual-row slicing + `Visual.to_strips` memoization in `TautTranscript.get_selection`, locked `_cancel_and_collect_handles()` + `or current.cancel.is_set()` in `SummonCoordinator`, and two-clause `run_guarded` in `on_terminal_attach_confirmation_request` (`decide_offer`).
   - **Targeted Mutation Kills (5/5 killed with `rc=1` and restored)**:
     - `summon.py`: removing `or current.cancel.is_set()` -> failed `test_stop_owned_and_wait_stops_handle_arriving_at_on_ready` (`rc=1`).
     - `summon.py`: removing `with self._lock:` in `_cancel_and_collect_handles()` -> failed `test_stop_owned_and_request_owned_stops_linearize_with_on_ready_under_lock` (`rc=1`).
     - `app.py`: removing `run_guarded` in `decide_offer` -> failed `test_setup_recovery_offer_second_modal_push_failure_fails_request` (`rc=1`).
     - `app.py`: removing `and reply_threads != previous_reply_threads` (`F1`) -> failed `test_transcript_tail_append_skips_clear_options_and_redundant_nav_rerender` (`rc=1`).
     - `session.py`: restoring `self._notification_feed.append(item)` in watcher (`F3`) -> failed `test_inbox_command_unifies_session_feed_caps_at_200_and_retains_newest_ts` (`rc=1`).
4. **Slice 4 (`taut-summon` Persona/Driver/Matcher & Documentation Gates)**:
   - Updated `extensions/taut_summon/taut_summon/_persona.py` (`3`-arg `reply` example validated against `parse_command_line`), `_driver.py` (`_accept_confirm` shutdown guard), `bin/check-doc-paths` (`EXTRA_SOURCES = []`), `tests/test_docs_references.py`, and `docs/implementation/{02-repository-map,03-agent-inventory,04-taut-architecture,09-search-architecture,11-system-doctor,12-taut-tui}.md`.
   - Verified `_pty.py:782` (`self._pending_deadline = None`) mutation kill (`rc=1` on `test_detach_matcher_completed_enhanced_atom_clears_pending_deadline`).
5. **Full Gate Matrix Results**:
   - Ruff lint + `ruff format --check` + `bin/ruff_suppression_index.py --check`: **0 issues, 0 suppression drift**.
   - `mypy` across all 5 packages (`155` core/PG/bin + `23` summon + `56` TUI + `14` MCP source files): **0 issues**.
   - `bin/check-plan-status-index` (`--self-test`), `bin/check-doc-paths` (`--self-test`), `bin/check-cli-claims`, `bin/check-dom15-fixtures`, `bin/coalesce-check`, `git diff --check`: **all passed (exit 0)**.
   - Pytest suites: Core (`not installed_wheel`), `taut-tui` (`-n 2 --dist loadfile`, including retained `_mutation_probe_child.py` gates), `taut-summon` (unit + POSIX PTY process lanes with `SIGHUP=SIG_DFL`), `taut-mcp`, and `./bin/pytest-pg` (`342 passed`): **all passed (exit 0)**.
