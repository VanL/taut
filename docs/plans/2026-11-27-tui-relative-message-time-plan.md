# TUI Compact Relative Message Timestamps Plan

- **Date:** 2026-11-27
- **Status:** completed (canonical status tracked in `docs/plans/README.md`)
- **Class:** Class 5 (Spec-changing — revises `[TUI-5.3]` and `[TUI-13.2]` in `docs/specs/10-taut-tui.md`; `hardening: N/A — no [DOM-5] risky trigger`: synchronous `taut-tui` presentation formatting only, with no async/worker change, storage change, CLI/API change, or new dependency)
- **Plan type:** implementation with spec revision
- **Reviewed baseline:** `e418e53d30dbb7f4b878c902b60edd92f853557a` (Tier-1 `claude-opus-5-5[1m]` plan review `Verdict: PASS`)

## Goal

Define a pure, deterministic compact relative-time formatter in `taut-tui` that interprets SimpleBroker nanosecond message IDs as timestamps with increasing granularity (`now`, `1m ago`–`50m ago`, `1h ago`, `2h ago`–`24h ago` today, `yesterday`, `Mon`–`Sun`, `1w ago`–`3w ago`, `1mo ago`–`11mo ago`, `Ny ago`), and replace raw 19-digit message IDs across TUI inspector and search read views (selected-message inspector, reply-inspector header and rows, canonical `channel.<origin_ts>` sub-thread labels in inspector/notifications/search results, and reaction/deletion receipts) while preserving `HH:MM` wall-clock timestamps in main transcript rows and retaining exact message/sub-thread IDs in selection state, active send-target labels (`#target-header`, `#composer` placeholder, `#status-line`), and destructive delete confirmations.

## Source Documents

Canonical startup context consulted (`docs/agent-context/README.md`):

- `AGENTS.md`
- `docs/program-theory.md` (`[THEORY-1]`, `[THEORY-3]`, `[THEORY-4]`, `[THEORY-5.A1]`–`[THEORY-5.A6]`)
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/lessons.md` and `docs/lessons.md` (Golden Rules + post-`2026-09-25` watermark entries)
- `docs/coalescing.md`
- `docs/specs/product-section-registry.md`
- `docs/implementation/03-agent-inventory.md` and `skills/call-agent/SKILL.md`

Source specs and implementation docs:

- `docs/specs/10-taut-tui.md` `[TUI-1]`, `[TUI-2.3]`, `[TUI-5.3]`, `[TUI-6.3]`, `[TUI-13.2]`
- `docs/specs/01-development-documentation-operating-model.md` `[DOM-5]`, `[DOM-6]`, `[DOM-10]`, `[DOM-11]`, `[DOM-14]`, `[DOM-15]`
- `docs/implementation/12-taut-tui.md`
- `docs/implementation/02-repository-map.md`

## Spec Baseline

- **Baseline:** `e418e53d30dbb7f4b878c902b60edd92f853557a` — `docs/specs/10-taut-tui.md` at plan authoring time
- **Promotion baseline:** `e418e53d30dbb7f4b878c902b60edd92f853557a` + worktree spec-promotion slice applied to `docs/specs/10-taut-tui.md` (`[TUI-5.3]`, `[TUI-13.2]`, `## Related Plans`), verified by `uv run python bin/check-doc-paths`

## Proposed Spec Delta

Promotion strategy: **A — In-file edit, text before link claims** (`docs/agent-context/runbooks/writing-plans.md` §4d). The spec-promotion slice updates `docs/specs/10-taut-tui.md` (`[TUI-5.3]`, `[TUI-13.2]`, and `## Related Plans`) after independent plan review and before any code slice cites the revised contract.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/10-taut-tui.md` | A — in-file, text before link claims | `[TUI-5.3]` first paragraph; `[TUI-13.2]` bullet list; `## Related Plans` |

### 1. `[TUI-5.3]` — replace first paragraph (`docs/specs/10-taut-tui.md` lines 319–328)

Audit of removed clause (`The exact 19-digit message id remains available through selection and the inspector; it never replaces the time in the row.`):

- `available through selection` -> retained explicitly for internal `VisualState.selected_message_id`, `InspectorState.selected_item`, transcript option IDs, active send-target labels, and destructive confirmation prompts (`[TUI-2.3]`, `[TUI-6.3]`).
- `and the inspector` -> intentionally replaced per owner request so human inspector and sub-thread views display compact relative time rather than raw 19-digit nanosecond IDs.
- `it never replaces the time in the row` -> retained and widened to human inspector summaries.

Replacement (`docs/specs/10-taut-tui.md`):

```markdown
### [TUI-5.3] Transcript rows

At wide and medium widths, ordinary messages use aligned local wall-clock time
and author metadata with a hanging body indent. The time uses the same public
core formatter as the CLI human renderer (`HH:MM`). At compact widths,
metadata stacks above the body. Selection state, active send-target labels, and
destructive confirmation prompts retain the exact message or sub-thread id
([TUI-2.3], [TUI-6.3]), while inspector and search views replace raw
message-id timestamps (selected-message header, reply-inspector rows, canonical
`channel.<origin_ts>` sub-thread labels formatted as `#channel (thread <age>)`,
and reaction/deletion receipts formatted as `... message sent <age>`) with a
compact relative age derived from the nanosecond message id against current
time: `now` (`< 60s` or future skew), `1m ago`–`50m ago` (`60s`–`3059s`),
`1h ago` (`3060s`–`7199s`), `2h ago`–`24h ago` (`>= 7200s` on the same local
calendar day, including 25-hour fall-back DST days), `yesterday` (`>= 7200s` on
the previous local calendar day), fixed English `Mon`–`Sun` (`2`–`6` local
calendar days prior), `1w ago`–`3w ago` (`7`–`27` days), `1mo ago`–`11mo ago`
(`28`–`364` days, `min(11, max(1, days // 30))`), and `Ny ago` (`>= 365` days,
`days // 365`), where `days` uses local calendar days below `8` elapsed 24-hour
days (`< 691200s`) and `elapsed_seconds // 86400` at or above `8` elapsed
24-hour days. Raw message ids never replace the time in transcript rows or
human inspector summaries.
Notices, warnings, unread boundaries, selected messages, and thread origins
remain structurally distinct without relying on color.
```

### 2. `[TUI-13.2]` — insert relative-age matrix bullet (`docs/specs/10-taut-tui.md` lines 1075–1077)

Replacement (`docs/specs/10-taut-tui.md`):

```markdown
- terminal-control payloads in every user/extension text-bearing widget;
- every compact relative-age bucket boundary in [TUI-5.3] (`now`, future skew,
  `1m ago`–`50m ago`, `1h ago`, same-day `2h ago`–`24h ago`, `yesterday`,
  `Mon`–`Sun`, `1w ago`–`3w ago`, `1mo ago`–`11mo ago`, and `Ny ago`) under an
  explicit clock seam, plus TUI projection across the selected-message
  inspector, reply inspector header and rows, canonical sub-thread target
  labels (including notifications and search results), and reaction/deletion
  receipts while active send-target labels and destructive delete confirmations
  retain exact message/sub-thread ids; and
- mouse drag across three transcript rows and across a wrapped visual line,
```

## Context and Key Files

### Files to Create or Modify

1. `docs/specs/10-taut-tui.md` — promote `[TUI-5.3]` and `[TUI-13.2]` delta and add `## Related Plans` backlink.
2. `extensions/taut_tui/taut_tui/time_format.py` *(new)* — pure TUI-owned relative-age formatter (`format_relative_time`, `format_subthread_label`) with zero Textual dependency and `time.time_ns` default clock.
3. `extensions/taut_tui/tests/test_tui_time_format.py` *(new)* — exhaustive boundary unit tests for `format_relative_time` and `format_subthread_label` using explicit `now_ns` and `ZoneInfo` values (never monkeypatching stdlib `time` or `datetime`).
4. `extensions/taut_tui/taut_tui/app.py` — wire `self._now_ns: Callable[[], int] = time.time_ns` and `self._relative_time(ts_ns)` into `_select_message` (`2095–2102`), `_render_reply_inspector` (`2159–2180`), `_inspector_target_label` (`2864–2882`, covering `:list`, `:log`, `:read`, `:message show`, `:search`, and `:inbox` notification target labels at `3087`), `SearchScreen(..., now_ns=self._now_ns)` (`1032`), and `MessageReaction`/`MessageDeletion` formatting in `_render_domain_result` (`2965–2968`, removing raw-ID `_format_reaction`/`_format_deletion` at `4171–4192`).
5. `extensions/taut_tui/taut_tui/screens.py` — add optional `now_ns: Callable[[], int] = time.time_ns` parameter to `SearchScreen.__init__` (`833–842`) and use `format_subthread_label` in `SearchScreen._apply_results` (`897–903`) so search hits in canonical reply sub-threads (`general.<origin_ts>`) display `#general (thread <age>)` instead of raw `origin_ts`.
6. `extensions/taut_tui/tests/test_tui_app.py`, `extensions/taut_tui/tests/test_tui_screens.py`, `extensions/taut_tui/tests/test_tui_action_handlers.py` — update `test_message_body_structure_does_not_widen_metadata_controls` (`test_tui_app.py:4453–4464`) and add real-`TautApp` / `SearchScreen` assertions with independent literal expectations proving compact relative-time projection and raw-ID absence across selected-message inspector, reply-inspector header/rows, sub-thread labels (including notifications and search results), and reaction/deletion receipts while preserving `HH:MM` in transcript rows and exact IDs in active send targets and delete confirmations.
7. `bin/render-tui-screens` and `docs/implementation/artifacts/tui/taut-tui-{130x34,100x34,64x34,40x15}.svg` — bind `app._now_ns = lambda: 1723400122000000000` (`120s` after `_MESSAGES[2].ts = 1723400002000000000`) so SVG regeneration renders `reviewer  2m ago` instead of `reviewer  1723400002000000000`.
8. `docs/implementation/12-taut-tui.md`, `docs/plans/README.md`, and `docs/coalescing.md` — synchronize implementation rationale, plan status index (`draft` -> `active` -> `completed`), and derived plan-tier harvest-candidate count (`19` -> `20` at closure).

### Current Structure and Load-Bearing Behavior

- **SimpleBroker message ID encoding:** SimpleBroker 64-bit hybrid timestamps (`ts: int`) store Unix nanoseconds directly (`time.time_ns()` with the bottom 12 bits carrying the logical counter, max ~4.095 microseconds), matching `taut.terminal.format_message_time(ts)` (`taut/terminal.py:79–81`). Integer floor division `ts_ns // 1_000_000_000` yields exact whole Unix seconds without IEEE-754 float rounding.
- **TUI surfaces currently showing raw message IDs:**
  - `TautApp._select_message` (`extensions/taut_tui/taut_tui/app.py:2098`): renders `(escape_inline_text(message.from_name), "bold"), f"  {message.ts}\n"`.
  - `TautApp._render_reply_inspector` (`app.py:2160–2179`): header renders `"Replies to ", escape_inline_text(snapshot.reply_thread or ""), "\n"` (where canonical reply threads are `f"{channel}.{origin_ts}"`), and each reply row renders `f"{message.ts}  ", escape_inline_text(message.from_name), "  ", escape_message_body(message.text)`.
  - `TautApp._inspector_target_label` (`app.py:2864–2882`, also used by `_render_notifications` at `3087`) and `SearchScreen._apply_results` (`screens.py:898–903`): fall through to raw `name` / `result.thread` for sub-threads (`general.<origin_ts>`), exposing the 19-digit `origin_ts`.
  - `_format_reaction` and `_format_deletion` (`app.py:4171–4181`): render `f"Reaction {escape_inline_text(value.reaction)} added to {value.message_ts}"` and `f"Deleted message {value.ts}"`.
- **Helpers to reuse:**
  - `taut.addressing.parse_target(name, allow_dm=False)` and `taut.ThreadNameError` (already public on `taut` and `taut.addressing`) to parse canonical `channel.<origin_ts>` sub-threads while returning `None` on non-subthread or malformed/hostile strings.
  - `escape_inline_text`, `escape_message_body`, and `display_text` in `extensions/taut_tui/taut_tui/widgets.py`.

## Invariants and Constraints

1. **Main transcript and existing `HH:MM` timestamps do not change:** `TautApp._message_prompt` (`app.py:3933, 3941`), `_format_domain_item` message/search item timestamps (`app.py:2896, 2914`), and `_render_notifications` notification timestamps (`app.py:3102`) continue to use `taut.terminal.format_message_time` (`HH:MM`). Note that `_render_notifications` target labels (`app.py:3087`) route through `_inspector_target_label`, so notifications targeting a canonical sub-thread gain `#channel (thread <age>)` target labels while keeping `HH:MM` notification event times. Core `taut/terminal.py`, CLI output, JSON output, `taut-mcp`, and `taut-summon` are untouched (`[TUI-1]`).
2. **Active send-target chrome stays exact (`[TUI-5.3]`):** When opening a search result inside a sub-thread makes `hit.thread` (`general.<origin_ts>`) the active conversation (`app.py:3160–3164`), `#target-header` (`app.py:3542–3543`), `#composer` placeholder (`app.py:3582`), and `#status-line` (`app.py:2557`) retain the exact public target name so two sub-threads in the same channel started minutes apart can never be confused as send targets.
3. **Internal selection, anchor, and domain-operation IDs remain exact:** `VisualState.selected_message_id: int | None`, `InspectorState(InspectorKind.MESSAGE, selected_item=str(message.ts))`, transcript option IDs `f"{message.thread}:{message.ts}"`, `self._reply_threads[(channel, origin_ts)]`, `TranscriptViewport` message anchors, and `TuiDomainActions.{reply_message,react_message,delete_message,open_search_result}` continue to pass exact integer/19-digit IDs.
4. **Destructive delete confirmation keeps exact target ID (`[TUI-2.3]`, `[TUI-6.3]`):** `TautApp._confirm_message_delete` (`app.py:1953–1965`) and `:message delete` (`app.py:1543–1552`) continue to pass `str(message_id)` to `ConfirmationScreen` (`Delete message <exact_id>?`).
5. **Non-canonical / hostile target strings remain safe:** When `reply_thread` or `name` is not a valid `channel.<origin_ts>` sub-thread (for example synthetic control-character payloads like `"root\nthread\tlabel"` in `test_tui_app.py:4435` or ANSI escape payloads in `test_tui_screens.py:571`), `format_subthread_label` catches `ThreadNameError` and returns `None`, falling back to existing `escape_inline_text` / Textual plain-text escaping without raising.
6. **Total, locale-independent, cross-platform time math without fallback chains:**
   - Weekday names use the fixed English tuple `("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[msg_date.weekday()]`, never locale-dependent `strftime("%a")`.
   - Calendar date conversion runs **only** when `7200 <= elapsed_seconds < 8 * 86400` (`691200s`); at or above `8` elapsed 24-hour days, `days = elapsed_seconds // 86400` handles weeks (`7–27`), months (`28–364`), and years (`>= 365`) purely by integer arithmetic, so old synthetic IDs (`ts=1`, `ts=2`) under real wall-clock time never call `fromtimestamp(0)` on any platform. Inside `< 8 * 86400`, UTC epoch + `timedelta` converted via `.astimezone(local_tz)` (which defaults to system local timezone when `local_tz is None`) handles any timestamp cleanly on Windows and POSIX alike.
7. **Clock seam discipline (`testing-patterns.md` Pattern 9):** Tests never monkeypatch stdlib `time` or `datetime`; they pass explicit `now_ns` / `local_tz` to `format_relative_time` or set `app._now_ns` / `SearchScreen(..., now_ns=...)` (defaulting directly to `time.time_ns`).
8. **Quality and dirty-tree hygiene:** Keep McCabe complexity `<= 10` on every function (target `<= 6` via helper decomposition), introduce zero `# noqa` suppressions (`uv run python bin/ruff_suppression_index.py --check`), add no dependencies, add no agent self-attribution, and never touch the pre-existing unstaged edit in `skills/call-agent/SKILL.md`.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Tasks

### Spec-Promotion Slice: Promote `[TUI-5.3]` and `[TUI-13.2]` in `docs/specs/10-taut-tui.md` (Completed)

- **Outcome:** `docs/specs/10-taut-tui.md` reflects the reviewed `[TUI-5.3]` and `[TUI-13.2]` contract and links this plan under `## Related Plans`; `docs/plans/README.md` flips this plan from `draft` to `active`; `Promotion baseline` is recorded in this plan.
- **Files touched:** `docs/specs/10-taut-tui.md`, `docs/plans/2026-11-27-tui-relative-message-time-plan.md`, `docs/plans/README.md`.
- **Done signal:** `uv run python bin/check-doc-paths` and `uv run python bin/check-plan-status-index` both exit `0`.

### Task 1: Implement `taut_tui.time_format` via Red-Green TDD (Completed)

- **Outcome:** `extensions/taut_tui/taut_tui/time_format.py` provides `format_relative_time` and `format_subthread_label`, backed by exhaustive deterministic boundary tests in `extensions/taut_tui/tests/test_tui_time_format.py`.
- **Files to touch:** `extensions/taut_tui/tests/test_tui_time_format.py` *(new)*, `extensions/taut_tui/taut_tui/time_format.py` *(new)*.
- **Read first:** `docs/specs/10-taut-tui.md` `[TUI-5.3]`, `taut/addressing.py` (`parse_target`), `taut/__init__.py` (`ThreadNameError`), `taut/terminal.py` (`format_message_time`).
- **Tests to write first (RED):**
  - `test_format_relative_time_bucket_boundaries`: table-driven assertions across fixed `local_tz` (`ZoneInfo("America/Chicago")`) covering future skew (`-1ns`, `-3600s` -> `now`), `0s` and `59s` -> `now`, `60s` -> `1m ago`, `3059s` -> `50m ago`, `3060s` and `7199s` -> `1h ago`, `7200s` and `23h` same local calendar day -> `2h ago` and `23h ago`, 25-hour fall-back DST day (`2026-11-01` `00:15` CDT -> `23:30` CST, `elapsed = 24h 15m`, `day_delta = 0`) -> `24h ago`, sub-2-hour across midnight (`23:50` -> `00:10` -> `20m ago`; `23:10` -> `00:30` -> `1h ago`), `>= 7200s` on previous local calendar day (`22:00` yesterday -> `00:30` today, and `09:00` yesterday -> `18:00` today) -> `yesterday`, `2`–`6` local calendar days across all seven weekday names (`Mon`–`Sun`), the `6 -> 7` calendar-day transition (`23:59` Day 0 -> `00:01` Day 7 -> `1w ago` rather than repeating today's weekday), `7`/`13`/`14`/`20`/`21`/`27` elapsed days -> `1w ago`/`1w ago`/`2w ago`/`2w ago`/`3w ago`/`3w ago`, `28`/`59`/`60`/`330`/`364` elapsed days -> `1mo ago`/`1mo ago`/`2mo ago`/`11mo ago`/`11mo ago`, `365` and `730` elapsed days -> `1y ago` and `2y ago`, and default `local_tz=None` with synthetic `ts=1` under current wall-clock `now_ns`.
  - `test_format_subthread_label_cases`: canonical `"general.1723400000000000000"` with parent-channel entry in `target_labels` (`{"general": "#general"}` -> `"#general (thread 5m ago)"`), custom parent-channel label (`{"general": "#main"}` -> `"#main (thread 5m ago)"`), empty `target_labels` (`{}` -> `"#general (thread 5m ago)"`), top-level channel `"general"` -> `None`, DM `"dm.d_..."` -> `None`, and malformed / control-character strings (`"root\nthread\tlabel"`, `"general.notanid"`) -> `None`.
- **Implementation details:**
  - Split into `format_relative_time`, `_format_calendar_window`, and `_format_elapsed_days` so each function stays at McCabe complexity `<= 5`.
  - `ref_ns = time.time_ns() if now_ns is None else now_ns`; `elapsed_ns = ref_ns - ts_ns`; if `elapsed_ns < 60_000_000_000`: return `"now"`.
  - `elapsed_seconds = elapsed_ns // 1_000_000_000`.
  - `< 3060`: `f"{elapsed_seconds // 60}m ago"`; `< 7200`: `"1h ago"`.
  - `< 8 * 86400`: compute local dates via `(EPOCH_UTC + timedelta(seconds=sec)).astimezone(local_tz).date()`; `day_delta <= 0` -> `f"{elapsed_seconds // 3600}h ago"`, `day_delta == 1` -> `"yesterday"`, `2 <= day_delta <= 6` -> `_WEEKDAY_NAMES[msg_date.weekday()]`, else `_format_elapsed_days(max(day_delta, elapsed_seconds // 86400))`.
  - `>= 8 * 86400`: `_format_elapsed_days(elapsed_seconds // 86400)` (`< 28` -> `f"{days // 7}w ago"`, `< 365` -> `f"{min(11, max(1, days // 30))}mo ago"`, else `f"{days // 365}y ago"`).
  - `format_subthread_label`: parse via `parse_target(name, allow_dm=False)` catching `ThreadNameError`; for `kind == "subthread"`, look up parent channel `channel_label = target_labels.get(parsed.channel, f"#{parsed.channel}")` and return `f"{channel_label} (thread {age})"`.
- **Done signal:** Observe initial `pytest` RED (`ModuleNotFoundError`), then GREEN on `uv run --project extensions/taut_tui --extra dev pytest extensions/taut_tui/tests/test_tui_time_format.py`, plus clean `ruff` and `mypy`.

### Task 2: Wire Relative Timestamps into `TautApp`, `SearchScreen`, and Deterministic SVGs via Red-Green TDD (Completed)

- **Outcome:** Selected-message inspector, reply-inspector header and rows, canonical sub-thread labels in inspector/notifications/`SearchScreen`, reaction/deletion receipts, and regenerated TUI visual-review SVGs display compact relative timestamps instead of raw 19-digit IDs, while transcript rows keep `HH:MM` and active send targets + delete confirmations keep exact IDs.
- **Files to touch:**
  - `extensions/taut_tui/tests/test_tui_app.py`
  - `extensions/taut_tui/tests/test_tui_screens.py`
  - `extensions/taut_tui/tests/test_tui_action_handlers.py`
  - `extensions/taut_tui/taut_tui/app.py`
  - `extensions/taut_tui/taut_tui/screens.py`
  - `bin/render-tui-screens`
  - `docs/implementation/artifacts/tui/taut-tui-{130x34,100x34,64x34,40x15}.svg`
- **Read first:** `extensions/taut_tui/taut_tui/app.py` (`373–422`, `1025–1040`, `2085–2180`, `2864–2985`, `3080–3116`, `4170–4195`), `extensions/taut_tui/taut_tui/screens.py` (`833–905`), `extensions/taut_tui/tests/test_tui_app.py` (`4416–4466`), `extensions/taut_tui/tests/test_tui_action_handlers.py` (`658–701`), `bin/render-tui-screens`.
- **Tests to write/update first (RED):**
  - Update `test_message_body_structure_does_not_widen_metadata_controls` (`test_tui_app.py:4416–4466`) to pin `app._now_ns = lambda: 120_000_000_001` with `ts=1` (`120s` elapsed -> literal `"2m ago"`) so it verifies `selected.startswith(r"ali\nce\tname  2m ago" + "\n")`, `r"Replies to root\nthread\tlabel"` (non-canonical escape preservation), and `r"2m ago  ali\nce\tname  "` in reply rows.
  - Add `test_inspector_and_receipts_use_relative_time_instead_of_raw_message_ids` in `test_tui_app.py` using fixed realistic 19-digit nanosecond IDs (`origin_ts = 1_723_400_000_000_000_000`, `reply_ts = origin_ts + 180_000_000_000`, `app._now_ns = lambda: origin_ts + 300_000_000_000`) and asserting independent string literals `"5m ago"` and `"2m ago"` (never calling `format_relative_time` in the test):
    - Transcript row still renders `format_message_time(origin_ts)` (`HH:MM`) and never raw `str(origin_ts)`.
    - Selected-message inspector renders `"alice  5m ago\n"` and does **not** contain `str(origin_ts)`, while `app.visual_state.selected_message_id == origin_ts` and `app.visual_state.inspector.selected_item == str(origin_ts)`.
    - Reply inspector header renders `"Replies to #general (thread 5m ago)\n"` and reply row renders `"2m ago  bob  "`, containing neither `str(origin_ts)` nor `str(reply_ts)`.
    - `_inspector_target_label` via `_render_domain_result(Thread(...))` and `_render_notifications((Notification(..., thread=f"general.{origin_ts}", message_ts=reply_ts),))` renders `"#general (thread 5m ago)"` (plus `format_message_time(reply_ts)` on the notification) without `str(origin_ts)` or `str(reply_ts)`.
    - `_render_domain_result(MessageReaction(thread="general", message_ts=origin_ts, reaction="ack", from_id="m_alice", from_name="alice"))` renders `"Reaction ack added to message sent 5m ago"` without `str(origin_ts)`.
    - `_render_domain_result(MessageDeletion(thread="general", ts=origin_ts, deleted_by="m_alice"))` renders `"Deleted message sent 5m ago"` without `str(origin_ts)`.
  - Add `test_search_results_format_canonical_subthread_labels_with_relative_time` in `test_tui_screens.py` proving `SearchScreen` renders `"#general (thread 5m ago)  Bob  reply hit"` without exposing the 19-digit `origin_ts`.
  - Tighten `_message_react` and `_message_delete` in `test_tui_action_handlers.py` (`664, 694`) to also assert `str(context.message_ts) not in _inspector(context)` after reaction/deletion completion while `_cancel_confirmation` / `_accept_confirmation` at lines `682, 692` continue proving exact `str(context.message_ts)` in the confirmation modal.
- **Implementation details:**
  - `TautApp.__init__`: set `self._now_ns: Callable[[], int] = time.time_ns` and add `def _relative_time(self, ts_ns: int) -> str: return format_relative_time(ts_ns, now_ns=self._now_ns())`.
  - `TautApp._select_message`: replace `f"  {message.ts}\n"` with `f"  {self._relative_time(message.ts)}\n"`.
  - `TautApp._inspector_target_label`: before returning raw `name`, check `subthread = format_subthread_label(name, self._target_labels, now_ns=self._now_ns())` and return `subthread` when non-`None`.
  - `TautApp._render_reply_inspector`: format `reply_label = self._inspector_target_label(snapshot.reply_thread) if snapshot.reply_thread else ""` in `"Replies to ", escape_inline_text(reply_label), "\n"`, and replace `f"{message.ts}  "` with `f"{self._relative_time(message.ts)}  "`.
  - `TautApp._render_domain_result`: handle `MessageReaction` (`f"Reaction {escape_inline_text(result.reaction)} added to message sent {self._relative_time(result.message_ts)}"`) and `MessageDeletion` (`f"Deleted message sent {self._relative_time(result.ts)}"`), removing raw-ID `_format_reaction` and `_format_deletion` from `_RESULT_FORMATTERS`.
  - `TautApp` search-open call (`app.py:1032`) and `SearchScreen` (`screens.py:833–904`): pass `now_ns=self._now_ns` to `SearchScreen`; in `_apply_results`, format canonical sub-threads via `format_subthread_label(result.thread, self._target_labels, now_ns=self._now_ns())`.
  - `bin/render-tui-screens`: set `app._now_ns = lambda: 1723400122000000000` before `app._select_message(2)` and regenerate the four SVGs via `PYTHONPATH=extensions/taut_tui uv run --project extensions/taut_tui --extra dev python bin/render-tui-screens`.
- **Stop-and-re-evaluate gate:** Stop if any existing action-route, selection, viewport, or destructive confirmation test regresses.
- **Done signal:** Observe initial RED on the new/updated tests, then full `extensions/taut_tui` pytest, ruff, and mypy pass, and `git diff docs/implementation/artifacts/tui/` replaces `1723400002000000000` with `2m ago`.

### Task 3: Traceability Reconciliation, Full Verification Gates, and Independent Completed-Work Review (Completed)

- **Outcome:** `docs/implementation/12-taut-tui.md`, `docs/plans/README.md`, and `docs/coalescing.md` are aligned; all CI static/doc/test gates pass from the current tree; Tier-1 cross-family completed-work review returns `PASS` / `no blocker`.
- **Files to touch:** `docs/implementation/12-taut-tui.md`, `docs/plans/2026-11-27-tui-relative-message-time-plan.md`, `docs/plans/README.md`, `docs/coalescing.md`.
- **Read first:** `docs/implementation/12-taut-tui.md` (`66–81`, `345–356`, `414–424`), `docs/coalescing.md` (`115–132`).
- **Done signal:** Every command in `## Verification and Gates` exits `0`, Tier-1 completed-work review findings are dispositioned, and `docs/plans/README.md` records `completed`.

## Testing Plan

- **Unit boundary (`extensions/taut_tui/tests/test_tui_time_format.py`):** Direct unit tests over `format_relative_time` and `format_subthread_label` with explicit `now_ns` and `ZoneInfo("America/Chicago")` (including DST transition dates, midnight crossovers, weekday names, `6 -> 7`-day transition, month/year boundaries, and malformed targets). Nothing mocked.
- **Real TUI integration boundary (`extensions/taut_tui/tests/test_tui_app.py`, `test_tui_screens.py`, `test_tui_action_handlers.py`):** Real `TautApp` under Textual `run_test`, real SQLite workspace via `TautClient`, real `SearchScreen`, and real action palette/form/confirmation flows, overriding only `app._now_ns` (never broker I/O, client routing, or stdlib clock functions) and asserting independent literal strings.

## Verification and Gates

### Per-Task Verification

```bash
uv run python bin/check-doc-paths && uv run python bin/check-plan-status-index
uv run --project extensions/taut_tui --extra dev pytest extensions/taut_tui/tests/test_tui_time_format.py
uv run --project extensions/taut_tui --extra dev pytest extensions/taut_tui/tests/test_tui_app.py -k "message_body_structure or relative_time"
```

### Final Completion Gates

```bash
uv run python bin/check-plan-status-index && uv run python bin/check-plan-status-index --self-test
uv run python bin/check-doc-paths && uv run python bin/check-doc-paths --self-test
uv run python bin/check-cli-claims
uv run python bin/check-dom15-fixtures
uv run bin/coalesce-check
uv run python bin/ruff_suppression_index.py --check
uv run ruff check taut tests bin extensions
uv run ruff format --check taut tests bin extensions
uv run --project extensions/taut_tui --extra dev mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev pytest extensions/taut_tui/tests -n 2 --dist loadfile
uv run pytest tests/test_docs_references.py tests/test_cli_claims.py tests/test_ruff_policy.py
```

## Independent Review Loop

- **Author family:** Gemini (Antigravity)
- **Reviewer family:** Claude (`claude-opus-5-5[1m]` via `/opt/homebrew/bin/claude` Tier-1 read-only plan-mode invocation in `skills/call-agent/SKILL.md`: `claude -p "$PROMPT" --safe-mode --permission-mode plan --tools "Read,Grep,Glob" --allowedTools "Read,Grep,Glob" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --no-session-persistence --output-format stream-json --verbose < /dev/null`).
- **Standing `[THEORY-5]` rejected alternatives in force:** `[THEORY-5.A1]`–`[THEORY-5.A6]` checked; none directly restrict TUI timestamp formatting, and `[THEORY-3]`/`[TUI-1]` place human-first presentation formatting inside `taut-tui` rather than core.

## Out of Scope

- Changing main transcript row timestamps (`HH:MM` via `taut.terminal.format_message_time`), `:log`/`:read`/`:message show`/`:search`/`:inbox` `HH:MM` event timestamps, or any CLI / JSON / MCP / Summon surface.
- Compressing active send-target chrome (`#target-header`, `#composer` placeholder, `#status-line`) when a sub-thread search result is opened as the active target — kept exact per `[TUI-5.3]` send-target safety so two sub-threads in the same channel started minutes apart cannot be mistaken for one another when sending.
- Adding background periodic timers to re-render idle inspector text every minute (violates `[THEORY-3]`/`[REV-THEORY-002]`'s no-extra-timer discipline; relative age renders cleanly on selection/open/update).
- Changing destructive delete confirmation prompts away from exact message-id target confirmation (`[TUI-2.3]`, `[TUI-6.3]`).

## Fresh-Eyes Review

Checked before and after external review with both lenses:

1. **Expert-developer craft:** Placing `format_relative_time` and `format_subthread_label` in a small stdlib-only `taut_tui/time_format.py` module keeps `app.py` and `screens.py` decoupled, uses `time.time_ns` directly as the default clock, names whose age is shown on receipts (`... message sent <age>`) and sub-thread labels (`#channel (thread <age>)`), and preserves deterministic relative-age output in `bin/render-tui-screens` via `app._now_ns`.
2. **Algorithmic & calendar edge cases:** Restricting calendar-date calculation to `< 8` elapsed 24-hour days (`< 691200s`) via UTC epoch + `timedelta` and handling `>= 8` elapsed days with pure `elapsed_seconds // 86400` arithmetic eliminates platform `fromtimestamp` fallback chains, preserves exact midnight/`yesterday`/weekday/DST behavior, and keeps every helper at McCabe complexity `<= 5`.

## Review Log

### Plan Review — Round 1 (2026-11-27, Tier-1 `claude-opus-5-5[1m]`)

- **Invocation:** `/opt/homebrew/bin/claude -p ... --safe-mode --permission-mode plan --tools "Read,Grep,Glob" --allowedTools "Read,Grep,Glob" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --no-session-persistence --output-format stream-json --verbose < /dev/null` (exit `0`, `tools=['Glob', 'Grep', 'Read']`, `mcp_servers=[]`, `permissionMode='plan'`, `38` read-only tool calls, `terminal_reason='completed'`, `is_error=False`).
- **Gate answers & Verdict:** Q1 = Yes, Q2 = No, **`Verdict: PASS`** (zero blockers; 4 `P2` + 6 `P3` refinements).
- **Dispositions:**

| ID | Severity | Disposition | Resolution |
|----|----------|-------------|------------|
| F1 | P2 | `fixed in plan` | Verified `app.py:3160–3164`, `3542–3543`, `3582`, `2557`: kept `#target-header`, `#composer` placeholder, and `#status-line` exact when a sub-thread search hit is opened as the active conversation per `[TUI-5.3]` send-target disambiguation, and recorded the boundary in `## Goal`, `[TUI-5.3]`, `## Invariants and Constraints` (#2), and `## Out of Scope`. |
| F2 | P2 | `fixed in plan` | Removed the unreachable `1 << 62` and redundant explicit-`ZoneInfo` fallback cases after adopting F3, replacing them with the `6 -> 7` calendar-day transition test and a `local_tz=None` `ts=1` wall-clock test. |
| F3 | P2 | `fixed in plan` | Restricted calendar-date computation to `7200 <= elapsed_seconds < 8 * 86400` (`691200s`, using UTC epoch + `timedelta` `.astimezone(local_tz)`) and used pure `elapsed_seconds // 86400` for `>= 8` elapsed 24-hour days, eliminating the two-step fallback chain and clarifying the day unit in `[TUI-5.3]`. |
| F4 | P2 | `fixed in plan` | Disambiguated whose age is displayed: canonical sub-thread labels format as `#channel (thread <age>)`, reaction receipts format as `Reaction <name> added to message sent <age>`, and deletion receipts format as `Deleted message sent <age>` (grammatical across all 9 buckets including `now`, `yesterday`, and `Mon`–`Sun`). |
| F5 | P3 | `fixed in plan` | Documented `_render_notifications` target-label formatting (`app.py:3087`) in `## Context and Key Files`, `## Invariants and Constraints` (#1), `[TUI-13.2]`, and Task 2's integration test. |
| F6 | P3 | `fixed in plan` | Specified parent-channel lookup `target_labels.get(parsed.channel, f"#{parsed.channel}")` in Task 1 with mapped, custom, and empty `target_labels` test cases. |
| F7 | P3 | `fixed in plan` | Specified fixed `origin_ts` / `reply_ts` / `now_ns` offsets in Task 2's integration test and independent string literal assertions (`"5m ago"`, `"2m ago"`). |
| F8 | P3 | `fixed in plan` | Replaced private `_now_ns` wrapper with `time.time_ns` directly as default on `format_relative_time`, `TautApp._now_ns`, and `SearchScreen`. |
| F9 | P3 | `fixed in plan` | Split `time_format.py` into `format_relative_time`, `_format_calendar_window`, and `_format_elapsed_days` so each function stays at McCabe complexity `<= 5`. |
| F10 | P3 | `fixed in plan` | Clarified local calendar days (`< 8` elapsed 24h days) vs `elapsed_seconds // 86400` (`>= 8` elapsed 24h days) directly in `[TUI-5.3]`. |

### Completed-Work Review — Round 1 (2026-11-27, Tier-1 `claude-opus-5-5[1m]`)

- **Invocation:** `/opt/homebrew/bin/claude -p ... --safe-mode --permission-mode plan --tools "Read,Grep,Glob" --allowedTools "Read,Grep,Glob" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --no-session-persistence --output-format stream-json --verbose < /dev/null` (exit `0`, `tools=['Glob', 'Grep', 'Read']`, `mcp_servers=[]`, `permissionMode='plan'`, `33` read-only tool calls, `terminal_reason='completed'`, `is_error=False`).
- **Verdict:** **`no blocker`** (zero `P1`s, zero `P2`s; 2 `P3`s + 4 `nit`s).
- **Dispositions:**

| ID | Severity | Disposition | Resolution |
|----|----------|-------------|------------|
| F1 | nit | `fixed` | Simplified `_format_calendar_window` fallback line to `_format_elapsed_days(day_delta)` in `extensions/taut_tui/taut_tui/time_format.py` (`day_delta >= 7` while `elapsed_seconds // _DAY_SECONDS <= 7`). |
| F2 | nit | `fixed` | Added `_HOUR_SECONDS = 3_600` in `extensions/taut_tui/taut_tui/time_format.py` and used it in `_TWO_HOURS_SECONDS` and same-day hour formatting. |
| F3 | P3 | `fixed` | Moved the relative-age inspector paragraph in `docs/implementation/12-taut-tui.md` directly after the hanging-text renderer paragraph so `"That renderer wraps..."` binds unambiguously to the hanging-text renderer. |
| F4 | P3 | `fixed` | Updated `test_search_results_format_canonical_subthread_labels_with_relative_time` in `extensions/taut_tui/tests/test_tui_screens.py` to map `"general": "#main"` and assert `"#main (thread 5m ago)  Bob  reply hit"` so `target_labels` threading is non-default verified. |
| F5 | nit | `fixed` | Removed unused `tz` and `fold` parameters from `_local_ns` in `extensions/taut_tui/tests/test_tui_time_format.py`. |
| F6 | nit | `deferred` | Kept `SearchScreen(search, target_labels, *, now_ns=...)` signature intact so existing `SearchScreen` callers remain unchanged; reconsider only if a third sub-thread label consumer appears. |
