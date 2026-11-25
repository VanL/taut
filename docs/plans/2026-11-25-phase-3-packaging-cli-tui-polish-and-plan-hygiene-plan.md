# Phase 3: Separate-Distribution Packaging Polish, Optional-`THREAD` `reply`, TUI Navigation Polish & Plan Hygiene Plan

Date: 2026-11-25
Status: completed
Owner: Taut maintainers
Author model family: Agy / Gemini (Google DeepMind)
Reviewer model family: Claude / Anthropic (`claude 2.1.293`, cross-family Tier-1 per `[DOM-11]` and `docs/implementation/03-agent-inventory.md`)
Class: 5+P (hardened; public `TautClient` + CLI `reply` + shared `[TAUT-8.7]` command syntax + core packaging/entry-point scripts + `bin/release.py` extra-floor sync + `taut-tui` navigation/mirror + `+P` `bin/check-plan-status-index` plan-tier counts & `.github/workflows/test-pg-extension.yml` mypy gate)
Plan type: implementation with spec revision and governance hygiene
Promotion strategy: **A — promote normative spec deltas before implementation code; update implementation mappings, READMEs, coalescing ledger, and lessons with implementation slices**
Promotion baseline identifier: base 6f17b9438e0eaf80a252b987d82143b1e73f1737, spec diff SHA-256 59b054bbc8e97c3a37f20fa2744a6718fe9f9d26097e2532581dcc9f3113d1a7

## Spec Baseline

- `6f17b9438e0eaf80a252b987d82143b1e73f1737` — `docs/specs/02-taut-core.md` and `docs/specs/10-taut-tui.md` at plan authoring time (committed `HEAD`; zero local spec diff before Slice 0).

## Goal

Complete the fifth and final plan of the owner-approved Taut adoption and remediation campaign while keeping every change strictly **taut** (`docs/program-theory.md`: small external surface, zero duplicate target-discovery or validation layers, intact read-cursor and consumable-notification invariants, and separate extension distributions per Owner Q4):

1. **Separate-distribution packaging & discovery polish (Owner Q4, `[TAUT-8.6]`, `[TAUT-12.5]`, `[TUI-3.1]`)**:
   - Keep all five PyPI distributions separate (`taut-chat`, `taut-pg`, `taut-summon`, `taut-mcp`, `taut-tui`).
   - Publish `taut-chat = "taut.cli:main"` alongside `taut = "taut.cli:main"` in root `pyproject.toml` `[project.scripts]` so `uvx taut-chat` and `pipx run taut-chat` invoke the Taut CLI directly without changing the canonical `taut` command name, and verify both `console_scripts` metadata and `taut-chat --version` execution in `bin/check-core-summon-wheel-matrix.py`.
   - Publish `default = ["taut-summon>=0.9.12", "taut-mcp>=0.9.12", "taut-tui>=0.9.12"]` in root `pyproject.toml` `[project.optional-dependencies]` alongside `all` (which additionally installs `taut-pg`), giving single-machine SQLite installs (`pipx install 'taut-chat[default]'`, `uv tool install 'taut-chat[default]'`) the complete local agent + TUI stack without pulling PostgreSQL driver dependencies; wire `sync_root_default_dependencies()` into `bin/release.py` via a shared `_sync_root_extra_floors()` helper (alongside `sync_root_all_dependencies()` and `_print_dry_run_root_dependency_notes()`).
   - Emit an actionable install hint from `taut/commands/_dispatch.py` when uninstalled first-party `tui` or `mcp` is invoked (`unknown command: tui (install taut-tui or 'taut-chat[default]' to enable 'taut tui')` and `unknown command: mcp (install taut-mcp or 'taut-chat[default]' to enable 'taut mcp')`), keeping uninstalled extensions out of `CommandRegistry` and `taut --help` (`[TUI-3.1]`).
2. **Optional-`THREAD` `reply` (`[THREAD] MSG_ID [TEXT|-]`) across `TautClient`, CLI, `syntax.py`, and TUI `:reply`, plus `TautClient` context manager (`[TAUT-8.1]`, `[TAUT-8.3]`, `[TAUT-8.7]`, `[TUI-7.1]`)**:
   - Widen `TautClient.reply(self, thread: str | None, msg_id: str, text: str) -> Message` (no two-argument positional overload or sentinel): after `[TAUT-6.5]` blank-message filtering and `_validate_exact_message_id(msg_id)` (preserving `TypeError` for non-`str` `msg_id` and translating `ValueError` to `MessageIdResolutionError`), `thread=None` locates `exact` across the acting member's joined top-level channels (`kind == "channel"`) via `self._locate_exact_message(exact, candidates)` (`None` -> `MessageIdNotFoundError` exit `2`), sharing `_reply_to_parent()` with explicit-`thread` calls. SimpleBroker's message `ts` primary key is unique across the whole database, so no multi-channel duplicate branch exists.
   - Support `taut reply [THREAD] MSG_ID [TEXT|-]` in `taut/commands/reply.py` and `:reply [THREAD] MSG_ID TEXT` in `taut/commands/syntax.py` + `extensions/taut_tui/taut_tui/{domain,app}.py` using one shared `resolve_reply_positionals` classifier: 3 tokens are `(thread, msg_id, text)`; 2 tokens `(a, b)` are `(a, b, None)` iff `MESSAGE_ID_RE.fullmatch(b)` and not `MESSAGE_ID_RE.fullmatch(a)`, else `(None, a, b)`; 1 token `(a,)` is `(None, a, None)` iff `MESSAGE_ID_RE.fullmatch(a)`, else a syntax/usage error (exit `1`), preventing `stdin=/dev/null` agent subprocesses from misclassifying missing/malformed `MSG_ID` as silent blank exit `2`.
   - Add `__enter__` / `__exit__` context-manager protocol methods to `_ClientBase` (`taut/client/_base.py`) delegating normal exit to `self.close()` and unwinding exit (`exc is not None`) through `capture_cleanup_failure(None, self.close)` + `exc.add_note(...)` so a `with`-body exception is never masked by a cleanup error.
3. **TUI initial & post-refresh navigation highlight persistence (`[TUI-3.3]`, `[TUI-4.2]`, `[TUI-6.1]`)**:
   - In `TautApp._set_navigation_actions` (`extensions/taut_tui/taut_tui/app.py`), capture any prior highlighted target (`self._navigation_targets[navigation.highlighted]` when in bounds, retaining an `ActionId` prior only when the previous list was already populated, i.e. `ActionId.NOTIFICATIONS_OPEN in self._navigation_targets`, so first-run empty-state `ActionId.CHANNEL_JOIN` transitions cleanly to `#general` upon joining) before `clear_options()`, deterministically highlight the first match among `(prior, selected_navigation, active_conversation, "general")` or index `0` under `with navigation.prevent(TautOptionList.OptionHighlighted):`, and guard `visual_state.selected_navigation` with `None if isinstance(selected, ActionId) else selected` in both `_set_navigation_actions` and `on_option_list_option_highlighted` (`app.py:786`, since `ActionId` is a `StrEnum`). Pressing `Enter` on launch immediately activates `#general` (or workspace init / join) and background `refresh_navigation()` calls preserve both channel and populated-list `ActionId` row highlights without auto-opening a watcher, moving read cursors, or claiming notifications.
4. **Plan-tier `bin/check-plan-status-index` counts (`F8`), plan status/header & README hygiene, CI `taut_pg` `conftest.py` type-checking, skill/runbook evaluation, and durable lessons (`[DOM-10.2]`, `[DOM-14]`)**:
   - Extend `bin/check-plan-status-index` (`run()`, tested in `tests/test_plan_status_index.py`) — the single canonical owner of `## Plan Status Index` parsing (`bin/coalesce-check:28-30`, `skills/coalescing/SKILL.md` step 1) — to append derived plan-tier status and harvest-candidate counts to its `OK` summary line with zero duplicate parser in `bin/coalesce-check`.
   - Reconcile `docs/plans/README.md`, plan headers, and `docs/coalescing.md` (`F8`): mark shipped `2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md` (`v0.9.12` at `a4fde51`) and `2026-07-29-taut-chat-pypi-publication-plan.md` (`v0.8.2` at `a12a8fa`, inserting `Status: completed` after `Date: 2026-07-29`) `completed`, repair stale transient header phrases in `2026-09-23-summon-enhanced-keyboard-detach-plan.md`, `2026-08-19-tui-setup-recovery-offer-plan.md`, and `2026-08-25-semantic-compatibility-hardening-plan.md`, and record explicit one-line dispositions for all 10 remaining `active` plans plus `2026-08-14-cross-surface-command-capability-plan.md` (`status-review`) alongside the `bin/check-plan-status-index`-verified counts in `docs/coalescing.md`.
   - Add `extensions/taut_pg/tests/conftest.py` to `.github/workflows/test-pg-extension.yml`'s mypy command (with exact test coverage in `tests/test_github_workflows.py:1351`), update pre-first-PyPI future-tense disclaimers and stale Postgres `init --json` `created: false` prose across `README.md` and `extensions/{taut_pg,taut_summon,taut_mcp,taut_tui}/README.md`, record the campaign's skill/runbook evaluation, and append durable 2026-11-25 lessons in `docs/lessons.md`.

## Source Documents

Normative specifications:

- `docs/specs/01-development-documentation-operating-model.md` (`[DOM-5]`, `[DOM-10]`, `[DOM-10.1]`, `[DOM-10.2]`, `[DOM-10.2.1]`, `[DOM-11]`, `[DOM-14]`, `[DOM-15]`)
- `docs/specs/02-taut-core.md` (`[TAUT-3.2]`, `[TAUT-4.2]`, `[TAUT-6.4]`, `[TAUT-6.5]`, `[TAUT-7.2]`, `[TAUT-7.6]`, `[TAUT-8.1]`, `[TAUT-8.2]`, `[TAUT-8.3]`, `[TAUT-8.6]`, `[TAUT-8.7]`, `[TAUT-10]`, `[TAUT-12.4]`, `[TAUT-12.5]`)
- `docs/specs/07-agent-theory-and-program-theory.md` (`[AT-REF-2]`)
- `docs/specs/10-taut-tui.md` (`[TUI-2.2]`, `[TUI-3.1]`, `[TUI-3.3]`, `[TUI-4.2]`, `[TUI-5.2]`, `[TUI-6.1]`, `[TUI-6.2]`, `[TUI-7.1]`, `[TUI-8.2]`)

Shared context, theory, skills, and runbooks consulted:

- `AGENTS.md`
- `docs/program-theory.md` (`[THEORY-1]`–`[THEORY-8]`, especially `[THEORY-1]`, `[THEORY-2]`, `[THEORY-5.A1]`)
- `docs/agent-context/README.md`, `decision-hierarchy.md`, `principles.md`, `engineering-principles.md`
- `docs/agent-context/runbooks/writing-plans.md`, `hardening-plans.md`, `writing-specs.md`, `maintaining-traceability.md`, `testing-patterns.md`, `adversarial-acceptance-probes.md`, `review-loops-and-agent-bootstrap.md`
- `skills/coalescing/SKILL.md`, `skills/call-agent/SKILL.md`
- `docs/coalescing.md`, `docs/lessons.md`, `docs/implementation/02-repository-map.md`, `03-agent-inventory.md`, `04-taut-architecture.md`, `06-command-extensions.md`, `12-taut-tui.md`
- `docs/plans/2026-10-15-deep-review-remediation-plan.md` & `docs/plans/2026-11-23-phase-0-bug-and-performance-remediation-plan.md` (`F8` provenance)

## Theory-Versus-Plan Audit (`[AT-REF-2]`, `docs/program-theory.md`)

Every candidate item from the initial Phase 3 outline (and Round 1 Tier-1 Claude review) was audited against `docs/program-theory.md` and owning specs:

| Candidate item | Theory & contract check | Disposition |
|---|---|---|
| Separate distributions + `taut-chat` script alias + `taut-chat[default]` extra + `tui`/`mcp` unknown-command hints | Honors Owner Q4 (`keep separate`) and `[THEORY-1]` ("installable with pipx", dependency-light core `[TAUT-8.6]`). `default` installs the SQLite-ready extension trio (`taut-summon`, `taut-mcp`, `taut-tui`) without `psycopg`; `_dispatch.py` hints guide bare-core callers without bloating `CommandRegistry` or `taut --help` (`[TUI-3.1]`). | **KEPT** |
| Optional `THREAD` on `taut reply [THREAD] MSG_ID [TEXT\|-]`, `TautClient.reply(thread: str \| None, msg_id, text)`, and `:reply` | Matches `message show`, `message delete`, and `message react` (`[TAUT-8.1]`), removing the #1 CLI asymmetry for agents acting on a 19-digit `msg_id` without introducing a two-argument positional overload or sentinel on `TautClient.reply`. | **KEPT (trimmed)** |
| `TautClient` `__enter__` / `__exit__` context manager | Standard Python resource-cleanup protocol over `TautClient.close()` preserving body exceptions via `capture_cleanup_failure` + `add_note`; adds zero new concepts or implicit `persistent=True` switches. | **KEPT** |
| TUI `_set_navigation_actions` highlight persistence (`#general` / retained target) | Pure presentation fix (`with navigation.prevent(OptionHighlighted):` + `ActionId` exclusion): pressing `Enter` on launch opens `#general` immediately while preserving `[THEORY-2]` / `[THEORY-5.A1]` / `[TUI-6.1]` / `[TUI-6.2]`. | **KEPT** |
| Derived plan-tier counts in `bin/check-plan-status-index` | Closes `F8` mental-arithmetic drift directly in the single canonical owner of `## Plan Status Index` (`skills/coalescing/SKILL.md` step 1, `bin/coalesce-check:28-30`) with zero duplicate parser in `bin/coalesce-check`. | **KEPT (single-owner)** |
| **Pruned**: 2-arg `TautClient.reply(msg_id, text)` overload & multi-channel duplicate `msg_id` branch | SimpleBroker's message `ts` primary key is database-unique (`_locate_exact_message`), making duplicate `msg_id` dead code; `thread: str \| None` on the 3-arg method covers omitted `THREAD` without `_MISSING` or `@overload` ceremony. | **PRUNED** |
| **Pruned**: Display/reaction-only `.taut.toml` upward fallback to `.taut.db` | Violates `[TAUT-3.2]` ("taut owns no backend-target search logic of its own. Storage resolution is one call: `simplebroker.resolve_broker_target(cwd, config=cfg)`"; "does not combine project settings from multiple files") and `[TAUT-6.4]`. | **PRUNED** |
| **Pruned**: Auto-opening `#general` watcher on TUI startup & single-click sidebar activation | Opening a conversation starts a `TautWatcher` (`[TUI-6.1]`), claiming the shared consumable notification inbox (`[TUI-6.2]`, `[THEORY-5.A1]`) and advancing bookmarks (`[TAUT-7.2]`). Single-click sidebar activation violates `[TUI-8.2]`. | **PRUNED** |
| **Pruned**: Permanent keybar hints in TUI footer, removing `Ctrl-D` quit, & exit code `2` -> `1` on `NotFoundError`/`MembershipError` | Forbidden by `[TUI-5.2]`, `[TUI-8.1]`, and `[TAUT-8.1]`'s SimpleBroker-aligned `0`/`1`/`2` polling contract. | **PRUNED** |

## Context and Key Files

### Slice 1 — Packaging, `taut-chat` Console Script, `default` Extra, `bin/release.py` Sync & Absent-Extension Hints
- `pyproject.toml` & `uv.lock`:
  - Add `default = ["taut-summon>=0.9.12", "taut-mcp>=0.9.12", "taut-tui>=0.9.12"]` under `[project.optional-dependencies]`.
  - Add `taut-chat = "taut.cli:main"` alongside `taut = "taut.cli:main"` under `[project.scripts]`.
  - Refresh `uv.lock` via `uv lock` so the root lock records the new `default` extra and script metadata cleanly.
- `bin/release.py` & `tests/test_release_script.py`:
  - Extract shared `_sync_root_extra_floors(*, extra: str, owners: tuple[tuple[str, Path], ...], root_pyproject_path: Path) -> dict[str, str]` over `_replace_optional_dependency_floor` and call it from `sync_root_all_dependencies()` (`extra="all"`) and `sync_root_default_dependencies()` (`extra="default"`, owners `("taut-summon", "taut-mcp", "taut-tui")`).
  - Wire `sync_root_default_dependencies()` into `_sync_root_release_dependencies()` and print the `default` extra note in `_print_dry_run_root_dependency_notes()`. Update synthetic `pyproject.toml` fixtures in `tests/test_release_script.py` (`lines 433, 629, 1283`) and add dedicated `sync_root_default_dependencies` tests.
- `taut/commands/_dispatch.py`, `tests/test_command_registry.py`, `tests/test_cli.py`, `extensions/taut_tui/tests/test_tui_launch.py`:
  - Add `_FIRST_PARTY_COMMAND_HINTS = {"mcp": "taut-mcp", "tui": "taut-tui"}` in `taut/commands/_dispatch.py`. When `command_registry.get(verb)` raises `KeyError`, format `unknown command: {verb} (install {pkg} or 'taut-chat[default]' to enable 'taut {verb}')` for `mcp`/`tui`, preserving `"unknown command: tui"` substring compatibility (`test_tui_launch.py:280`) and keeping `tui`/`mcp` absent from `CommandRegistry` and `taut --help` when uninstalled.
- `bin/check-core-summon-wheel-matrix.py` & `tests/test_core_summon_wheel_matrix.py`:
  - Extend `WheelMetadata` with `console_scripts: tuple[tuple[str, str], ...]` parsed from `[console_scripts]` in `.dist-info/entry_points.txt`, require `core.console_scripts == (("taut", "taut.cli:main"), ("taut-chat", "taut.cli:main"))` in `_validate_new_metadata` (updating `_write_wheel` in `tests/test_core_summon_wheel_matrix.py` when `name == "taut-chat"`), and invoke `python.with_name("taut-chat.exe" if os.name == "nt" else "taut-chat")` with `--version` in `_case_new_core`.

### Slice 2 — Optional-`THREAD` `reply`, `TautClient` Context Manager & TUI Navigation Highlight Persistence
- `taut/client/_base.py` & `tests/test_client.py`:
  - Add `__enter__(self) -> Self: return self` and `__exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object) -> None`: when `exc is None`, call `self.close()`; when `exc is not None`, call `cleanup_exc = capture_cleanup_failure(None, self.close)` and if `cleanup_exc is not None: exc.add_note(f"client context cleanup failed: {cleanup_exc}")` so `with`-body exceptions are never masked by cleanup failures (`_base.py:265-269`). Does not implicitly mutate `persistent`.
- `taut/client/_messaging.py`, `tests/test_client.py`, `tests/test_shared_contract.py`, `tests/test_command_registry.py`:
  - Change `TautClient.reply(self, thread: str | None, msg_id: str, text: str) -> Message` (updating test subclasses in `tests/test_command_registry.py:3641, 3850`).
  - Enforce `[TAUT-6.5]` blank filtering (`is_blank_message_text(text)` -> `BlankMessageError`) FIRST, then validate `msg_id` via `exact = _validate_exact_message_id(msg_id)` (preserving `TypeError` for non-`str` `msg_id`, and mapping `ValueError` -> `MessageIdResolutionError("message id must be a full 19-digit message id")`). Pass `exact: int` directly to `_resolve_message_id(self, thread: str, exact: int, msg_id: str) -> Message` so `MESSAGE_ID_RE` is not checked twice and explicit-`THREAD` out-of-int64-range IDs (`"9999999999999999999"`) also raise `MessageIdResolutionError`.
  - When `thread is not None`: keep exact existing validation (`addressing.validate_chat_thread_name(thread, allow_subthread=False)`, `_ensure_no_incomplete_channel_rename()`, `get_thread(thread)` -> `NotFoundError`, `_resolve_member(create=False)` -> `_require_member`, `get_membership` -> `MembershipError`, `_resolve_message_id(thread, exact, msg_id)`).
  - When `thread is None`: check `_ensure_no_incomplete_channel_rename()`, resolve existing acting member (`create=False`), build `channel_rows: dict[str, ThreadRow]` from joined memberships whose `get_thread(membership["thread"])` has `kind == "channel"`, and call `located = self._locate_exact_message(exact, channel_rows)`: if `located is None`, raise `MessageIdNotFoundError(f"message not found: {msg_id}")`; otherwise look up `channel_rows[located.message.thread]` and `located.message`.
  - Factor the sub-thread creation, membership, message write, reply/mention notification, and sender-cursor advance body into `_reply_to_parent(self, *, thread: str, parent_thread: ThreadRow, member: MemberRow, parent: Message, text: str) -> Message` so `reply()` stays concise (`C901 <= 10`).
- `taut/commands/reply.py`, `taut/commands/syntax.py`, `tests/test_cli.py`, `tests/test_command_registry.py`, `tests/test_command_syntax.py`:
  - Shared helper `resolve_reply_positionals(items: Sequence[str]) -> tuple[str | None, str, str | None]` in `taut/commands/syntax.py` (importing `MESSAGE_ID_RE` from `taut._constants`, imported in turn by `taut/commands/reply.py`):
    - `len(items) == 3`: `return items[0], items[1], items[2]`
    - `len(items) == 2` (`a, b`): if `MESSAGE_ID_RE.fullmatch(b) is not None and MESSAGE_ID_RE.fullmatch(a) is None`, `return a, b, None` (3-arg piped-stdin form `echo hi | taut reply general 1837025672140161024`, including digit-only channel names like `2026`); otherwise `return None, a, b` (2-arg form `taut reply 1837025672140161024 "hi"`, `taut reply 1837025672140161024 -`, or malformed-id `taut reply 12345 "hi"` / `taut reply general "hi"`).
    - `len(items) == 1` (`a,`): if `MESSAGE_ID_RE.fullmatch(a) is not None`, `return None, a, None` (2-arg piped-stdin form `echo hi | taut reply 1837025672140161024`); otherwise raise `CommandSyntaxError("missing required value: msg_id")`.
    - `len(items) == 0`: raise `CommandSyntaxError("missing required value: msg_id")`; `len(items) > 3`: raise `CommandSyntaxError(f"unexpected value: {items[3]}")`.
  - In `ReplyCommand` (`taut/commands/reply.py`):
    - Update `_USAGE_HINT` to `"; usage: taut reply [THREAD] MSG_ID [TEXT|-] (MSG_ID is the full 19-digit message id)"` (and update existing assertions in `tests/test_cli.py:3192` and `tests/test_command_registry.py:3812, 3818, 3826`).
    - In `configure_parser(self, parser)` (no stored parser state): configure `thread` (`nargs="?"`, `metavar="THREAD"`), `msg_id` (`metavar="MSG_ID"`), and `text` (`nargs="?"`, `metavar="TEXT|-"`).
    - In `run(self, context, args)`: collect `supplied = [item for item in (args.thread, args.msg_id, args.text) if item is not None]`. Inside the `try: ... except MessageIdResolutionError as exc: raise type(exc)(str(exc) + _USAGE_HINT) from exc` block — BEFORE `context.client()` or `read_text_argument(...)` — call `resolve_reply_positionals(supplied)` and translate `except CommandSyntaxError as exc: raise MessageIdResolutionError(str(exc)) from exc`, so missing `MSG_ID` (`taut reply general`) exits `1` cleanly through `_exit_code_for_exception` without raising `SystemExit(1)` from `run()`.
  - In `taut/commands/syntax.py`: declare `reply` positionals as `(_pos("thread", required=False), _pos("msg_id"), _pos("text", required=False))` so `format_command_syntax` renders `reply [THREAD] MSG_ID [TEXT]`, and route `node.path == ("reply",)` in `_assign_positionals` through a small `_assign_reply_positionals` helper calling `resolve_reply_positionals` (`C901 <= 10`).
- `extensions/taut_tui/taut_tui/{domain,app}.py`, `extensions/taut_tui/tests/{test_tui_app,test_tui_domain}.py`:
  - Update `TuiDomainActions.reply_message(self, channel: str | None, message_id: str | int, text: str)` and `TautApp._dispatch_send_command` (`raw_thread = values.get("thread"); channel = str(raw_thread) if raw_thread is not None else None`) so `:reply 1837025672140161024 "ack"` and `:reply general 1837025672140161024 "ack"` both work natively in the TUI.
  - Fix the `StrEnum` `ActionId` guard in `TautApp.on_option_list_option_highlighted` (`extensions/taut_tui/taut_tui/app.py:786`) AND `TautApp._set_navigation_actions` (`app.py:3330-3339`): use `None if isinstance(selected, ActionId) else selected` so `ActionId` rows never pollute `visual_state.selected_navigation`. In `_set_navigation_actions`, read `prior = self._navigation_targets[navigation.highlighted] if navigation.highlighted is not None and 0 <= navigation.highlighted < len(self._navigation_targets) else None` BEFORE `navigation.clear_options()` (discarding `prior` when `isinstance(prior, ActionId) and ActionId.NOTIFICATIONS_OPEN not in self._navigation_targets` so empty-state `ActionId.CHANNEL_JOIN` never shadows `#general` after a first-run join), choose `highlighted` index as the first match in `targets` among `(prior, self.visual_state.selected_navigation, self.visual_state.active_conversation, "general")` (ignoring `None`), falling back to `0` when `targets` is non-empty (else `None`), and set `navigation.highlighted = highlighted` inside `with navigation.prevent(TautOptionList.OptionHighlighted):`.

### Slice 3 — `F8` Plan-Tier `bin/check-plan-status-index` Counts, Plan & README Hygiene, CI `conftest.py`, Runbook Evaluation & Lessons
- `bin/check-plan-status-index` & `tests/test_plan_status_index.py`:
  - Keep `## Plan Status Index` parsing in its single canonical owner (`bin/check-plan-status-index`, leaving `bin/coalesce-check` untouched per `bin/coalesce-check:28-30` and `skills/coalescing/SKILL.md` step 1).
  - Refactor `check()` / `run()` in `bin/check-plan-status-index` so `run()` formats derived counts from the validated `rows` (`Counter` per status in deterministic order + `harvest candidates (completed/superseded non-exemplars): <M>`) directly on the `OK` line (`check-plan-status-index: <index> plan status index OK (<N> total: ...; harvest candidates (completed/superseded non-exemplars): <M>)`), preserving the `"plan status index OK"` substring asserted in `tests/test_plan_status_index.py:73, 224` and adding dedicated count-derivation tests in `tests/test_plan_status_index.py`.
- `docs/plans/README.md`, shipped/active plan headers & `docs/coalescing.md`:
  - Mark `2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md` (`- **Status:** completed`, shipped in `v0.9.12` at `a4fde51`) and `2026-07-29-taut-chat-pypi-publication-plan.md` (inserting `Status: completed` after `Date: 2026-07-29`, shipped in `v0.8.2` at `a12a8fa`) `completed` in both their headers and `docs/plans/README.md`.
  - Repair stale transient header phrases on the three `active` plans:
    - `docs/plans/2026-09-23-summon-enhanced-keyboard-detach-plan.md:5`: `Changes are uncommitted.` -> `Implementation landed at bd8ff4e and shipped in v0.9.9 (c894059).`
    - `docs/plans/2026-08-19-tui-setup-recovery-offer-plan.md:5`: ``Status: draft (see `docs/plans/README.md` status index)`` -> ``Status: active (see `docs/plans/README.md` status index)``
    - `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md:7`: `is promoted in the working tree.` -> `was promoted at dcf5d0b.`
  - Record explicit one-line `F8` dispositions in `docs/coalescing.md` (`Deferral State` and `Run Log`) for all 10 remaining `active` plans (`2026-09-28-simplification-and-hot-path`, `2026-09-24-cli-read-delivery`, `2026-09-24-identity-claim-boundary`, `2026-09-23-summon-enhanced-keyboard-detach`, `2026-09-15-reported-issues-followup`, `2026-08-25-semantic-compatibility-hardening`, `2026-08-24-command-runtime-findings`, `2026-08-24-extension-seams-process-containment-coverage`, `2026-08-19-tui-setup-recovery-offer`, `2026-07-28-taut-mcp-dual-era-sessionless`) AND `2026-08-14-cross-surface-command-capability-plan.md` (`status-review`, retained as owner-deferred quarantine until the first-party root registry reaches 25 verbs), alongside the exact `bin/check-plan-status-index`- and `bin/coalesce-check`-verified counts (including this Phase 3 plan once completed).
- `.github/workflows/test-pg-extension.yml` & `tests/test_github_workflows.py`:
  - Append `extensions/taut_pg/tests/conftest.py` to `.github/workflows/test-pg-extension.yml:89` and update `tests/test_github_workflows.py:1351` to assert `"mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_pg/tests/conftest.py"`.
- `README.md`, `extensions/{taut_pg,taut_summon,taut_mcp,taut_tui}/README.md`, `docs/implementation/{02-repository-map,04-taut-architecture,06-command-extensions,12-taut-tui}.md`, `tests/test_project_metadata_consistency.py`, `docs/lessons.md`:
  - Document `taut-chat` console alias, `taut-chat[default]`, optional-`THREAD` `taut reply`, and `with TautClient(...) as client:`; remove stale pre-first-PyPI future-tense disclaimers across the READMEs while keeping all `tests/test_project_metadata_consistency.py` install commands intact; fix stale `extensions/taut_pg/README.md:80-81` (`created` on Postgres `init --json`); update implementation docs; and append durable 2026-11-25 lessons in `docs/lessons.md`.

## Invariants, Hidden Couplings, and What Must Not Change

1. **Separate distributions & release-file allowlist (`[TAUT-8.6]`, `[TAUT-12.5]`)**:
   - All five PyPI distributions remain separate; `taut-chat` core runtime dependencies remain `simplebroker>=8.8.1` and `psutil>=7.2.2` only.
   - `tests/test_project_metadata_consistency.py` asserts exact install snippets (`pipx install taut-chat`, `uv add taut-chat`, `pipx inject --include-apps taut-chat taut-pg taut-summon taut-mcp taut-tui`, `pipx inject taut-chat taut-pg`, `pipx inject --include-apps taut-chat taut-summon`, `pipx inject --include-apps taut-chat taut-mcp`, `python -m pip install taut-chat taut-tui`); preserve every one of those strings when removing pre-PyPI future-tense prose and adding `taut-chat[default]`.
2. **Blank-message precedence & `/dev/null` stdin safety on `reply` (`[TAUT-6.5]`, `[TAUT-8.1]`, `[TAUT-10]`)**:
   - `TautClient.reply` checks `is_blank_message_text` BEFORE `msg_id` validation, incomplete-rename checks, identity resolution, or queue peeks (`taut reply 1234 "\u200b"` and `taut reply general missing-parent "\u200b"` still exit `2` silently), and preserves `TypeError` when `msg_id` is not a `str`.
   - Non-blank malformed or missing `MSG_ID` (`taut reply general`, `taut reply 1234`, `taut reply 1234 "hi"`, `taut reply general 1234 "hi"`, `taut reply 9999999999999999999 "hi"`) exits `1` even when `stdin` is `/dev/null`.
   - Sub-threads remain strictly one-level under top-level channels (`kind == "channel"`): `thread=None` searches only joined top-level channels, never sub-threads or DMs.
3. **TUI cursor, notification, `ActionId`, mouse, and render-feedback invariants (`[TUI-4.2]`, `[TUI-6.1]`, `[TUI-6.2]`, `[TUI-8.2]`)**:
   - `_set_navigation_actions` sets `navigation.highlighted` inside `with navigation.prevent(TautOptionList.OptionHighlighted):`, never calls `open_conversation` automatically, and excludes `ActionId` (`StrEnum`) values from `visual_state.selected_navigation` (in both `_set_navigation_actions` and `on_option_list_option_highlighted`). Single-click in `#navigation-list` continues to select without activating; `Enter` and double-click activate.
4. **Ruff suppression registry, CLI-claims exemptions, lazy imports & worktree protection**:
   - Keep `bin/ruff_suppression_index.py --check` at zero drift (`C901 <= 10`), avoid unexempted backticked `taut tui`/`taut mcp` claims in `docs/specs/02-taut-core.md` or `docs/plans/README.md` (`tests/test_cli_claims.py`), preserve lazy imports (`tests/test_lazy_imports.py`), and NEVER modify, stage, or revert `skills/call-agent/SKILL.md`.

## Anti-Mocking Guidance

- **Client & CLI `reply` / context manager**: Test against real SQLite and live Docker PostgreSQL (`tests/test_shared_contract.py`, `tests/test_client.py`, `tests/test_cli.py`), including real subprocesses with `stdin=subprocess.DEVNULL` and piped `stdin`.
- **Packaging & console scripts**: Build real wheels via `bin/build-and-check-release-wheels.py` and invoke the installed `taut-chat` executable in a checkout-free `venv`.
- **TUI**: Drive real `TautApp` instances under Textual `run_test()` pilot sessions (`test_tui_app.py`, `test_tui_domain.py`), verifying launch + `Enter` opens `#general` while launch alone leaves unread counts, notification queues, and empty-state `selected_navigation` (`None`) untouched.
- **`bin/check-plan-status-index`**: Execute the real `bin/check-plan-status-index` script against temporary plan directories and the live repository (`tests/test_plan_status_index.py`).

## Rollback, Rollout, and Compatibility Sequencing

- **Zero schema or wire changes**: Core schema (`6`), Summon schema (`4`), search schema, dump format (`v1`), and MCP tool schemas are untouched. Any slice can be reverted cleanly with `git revert` without data migration.
- **Cross-package source & lockfile atomicity**: Root `pyproject.toml`, `uv.lock`, `bin/release.py`, `taut`, and `taut-tui` land together in one commit, verified across all package suites, live PostgreSQL, and freshly built wheels.

## Proposed Spec Delta (Strategy A — Applied in Slice 0)

### 1. `docs/specs/02-taut-core.md`

#### 1a. `[TAUT-8.1]` Optional-`THREAD` `reply` verb summary

Original (`docs/specs/02-taut-core.md`):
```markdown
| `reply THREAD MSG_ID [TEXT\|-]` | Post into the sub-thread of MSG_ID, creating it on first reply. Blank text is filtered before parent resolution under [TAUT-6.5]. Requires membership in THREAD. MSG_ID is the exact 19-digit message id, as for `message show`, `message delete`, and `message react`; there is no short form. Any other value is a malformed argument. | 0 wrote; 1 error, including a malformed MSG_ID; 2 blank filtered / no such message / unrecognized member |
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
| `reply [THREAD] MSG_ID [TEXT\|-]` | Post into the sub-thread of top-level channel message MSG_ID, creating it on first reply. Blank text is filtered before parent resolution under [TAUT-6.5]. When THREAD is supplied, requires membership in THREAD; when THREAD is omitted, locates MSG_ID across the acting member's joined top-level channels. Two positional values are interpreted as `THREAD MSG_ID` (piped stdin) when the second is a 19-digit MSG_ID and the first is not, otherwise as `MSG_ID TEXT\|-`; a single positional value must be a 19-digit MSG_ID (piped stdin) or exits 1 as a usage error. MSG_ID is the exact 19-digit message id within SimpleBroker's signed 64-bit timestamp range, as for `message show`, `message delete`, and `message react`; there is no short form. Any other value is a malformed argument. | 0 wrote; 1 usage or error, including a malformed MSG_ID; 2 blank filtered / no such message / not a member / unrecognized member |
```

#### 1b. `[TAUT-8.1]` Absent first-party `tui`/`mcp` unknown-command hint

Original (`docs/specs/02-taut-core.md`):
```markdown
Root help is registry-backed. It must remain usable when an unrelated installed
command is broken or incompatible. A selected unavailable command exits 1 with
its distribution, entry point, and compatibility failure; it never produces a
traceback. Literal `--`, global-option placement, usage exit 1, and the 0/1/2
exit classes apply equally to built-in and extension command adapters.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
Root help is registry-backed. It must remain usable when an unrelated installed
command is broken or incompatible. A selected unavailable command exits 1 with
its distribution, entry point, and compatibility failure; it never produces a
traceback. Selecting an uninstalled command exits 1 with `unknown command:
<verb>`; for the optional first-party `mcp` and `tui` commands, that one-line
diagnostic appends an install hint naming the owning distribution (`taut-mcp` or
`taut-tui`) and `taut-chat[default]` while keeping uninstalled commands out of
root help. Literal `--`, global-option placement, usage exit 1, and the 0/1/2
exit classes apply equally to built-in and extension command adapters.
```

#### 1c. `[TAUT-8.3]` `TautClient` context manager and optional-`thread` `reply`

Original (`docs/specs/02-taut-core.md`):
```markdown
`escape_terminal_text`, and `__version__`. The package ships typed
(`py.typed`) and includes `taut/defaults.toml` and `taut/agent-kernel.md` in
both source and wheel distributions.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
`escape_terminal_text`, and `__version__`. `TautClient` supports the context-manager
protocol (`with TautClient(...) as client:`), calling `close()` on exit (attaching
any cleanup error as a note when unwinding a body exception) without implicitly
changing `persistent`, and `TautClient.reply(thread, msg_id, text)` accepts
`thread: str | None`, resolving `msg_id` across the acting member's joined
top-level channels when `thread` is `None`. The package ships typed
(`py.typed`) and includes `taut/defaults.toml` and `taut/agent-kernel.md` in
both source and wheel distributions.
```

#### 1d. `[TAUT-8.6]` & `[TAUT-8.7]` `default`/`all` extras, `reply` positional grammar, and `taut-chat` console alias

Original (`docs/specs/02-taut-core.md`):
```markdown
The core distribution publishes an `all` optional-dependency extra containing
the compatible `taut-pg`, `taut-summon`, `taut-mcp`, and `taut-tui`
distributions. It is a
convenience bundle, not a merger of package ownership: each extension remains
separately versioned and directly installable, and core does not import or
initialize an extension until its registered surface is selected.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
The core distribution publishes an `all` optional-dependency extra containing
the compatible `taut-pg`, `taut-summon`, `taut-mcp`, and `taut-tui`
distributions, a `default` optional-dependency extra containing the local
SQLite-ready `taut-summon`, `taut-mcp`, and `taut-tui` distributions, and a
`tui` extra containing `taut-tui`. They are
convenience bundles, not a merger of package ownership: each extension remains
separately versioned and directly installable, and core does not import or
initialize an extension until its registered surface is selected.
```

Original (`docs/specs/02-taut-core.md`):
```markdown
The root syntax wrapper owns pre-verb global options, post-verb declarations,
root actions such as `--help` and `--version`, and the released precedence
rules. These are part of the shared grammar rather than ad hoc surface logic.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
The root syntax wrapper owns pre-verb global options, post-verb declarations,
root actions such as `--help` and `--version`, and the released precedence
rules, including `reply`'s shared `[THREAD] MSG_ID [TEXT]` positional
disambiguation rule from [TAUT-8.1]. These are part of the shared grammar
rather than ad hoc surface logic.
```

Original (`docs/specs/02-taut-core.md`):
```markdown
The core distribution's normalized installed owner is `taut-chat`; the import
package and console command remain `taut`. Static built-in command diagnostics
use `taut-chat` as their distribution provenance. The reserved first-party
`summon` and `dismiss` owner remains the separately installed `taut-summon`
distribution.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
The core distribution's normalized installed owner is `taut-chat`; the import
package remains `taut`, and the distribution installs both `taut` (canonical)
and `taut-chat` (distribution-matching console alias) bound to `taut.cli:main`.
Static built-in command diagnostics use `taut-chat` as their distribution
provenance. The reserved first-party `summon` and `dismiss` owner remains the
separately installed `taut-summon` distribution.
```

#### 1e. `[TAUT-12.5]` Release helper `taut-chat` alias and `default` extra sync

Original (`docs/specs/02-taut-core.md`):
```markdown
- `core` (aliases: `root`, `taut`) releases distribution `taut-chat` from the
  repository root with a `vX.Y.Z` tag and
  `.github/workflows/release-gate.yml`. It continues to install import package
  and console command `taut`.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
- `core` (aliases: `root`, `taut`) releases distribution `taut-chat` from the
  repository root with a `vX.Y.Z` tag and
  `.github/workflows/release-gate.yml`. It continues to install import package
  `taut` and console commands `taut` and `taut-chat`.
```

Original (`docs/specs/02-taut-core.md`):
```markdown
  The PG, Summon, MCP, and TUI manifests respectively own the four version floors
  in the root `all` extra; normal release preparation reconciles all four on
  every invocation after selected manifest versions are written.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
  The PG, Summon, MCP, and TUI manifests respectively own the four version floors
  in the root `all` extra, and the Summon, MCP, and TUI manifests own the three
  version floors in the root `default` extra; normal release preparation
  reconciles both extras on every invocation after selected manifest versions
  are written.
```

#### 1f. `## Related Plans`

Original (`docs/specs/02-taut-core.md`):
```markdown
- `docs/plans/2026-11-24-phase-2b-summon-providers-and-attach-ergonomics-plan.md` —
  adds `agy` automatic-name pool entries in `taut/_constants.py`, [TAUT-8.7]
  ordered post-verb global/local option-value slot classification and
  `root.db_path`-scoped load-failure debug capture across
  `taut/commands/_dispatch.py` and `taut/commands/syntax.py`, and updates the
  [TAUT-8.1] `summon` summary for `--status` parity under spec 04 while keeping
  `summon` `post_verb_globals` pinned to `{GlobalOption.DB}`.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
- `docs/plans/2026-11-25-phase-3-packaging-cli-tui-polish-and-plan-hygiene-plan.md` —
  adds the `taut-chat` console script alias, `taut-chat[default]` convenience
  extra (synchronized in `bin/release.py`), `mcp`/`tui` absent-extension
  unknown-command hints, optional-`THREAD` `reply` across `TautClient`, CLI, and
  `[TAUT-8.7]` command syntax, and `TautClient` context-manager support.

- `docs/plans/2026-11-24-phase-2b-summon-providers-and-attach-ergonomics-plan.md` —
  adds `agy` automatic-name pool entries in `taut/_constants.py`, [TAUT-8.7]
  ordered post-verb global/local option-value slot classification and
  `root.db_path`-scoped load-failure debug capture across
  `taut/commands/_dispatch.py` and `taut/commands/syntax.py`, and updates the
  [TAUT-8.1] `summon` summary for `--status` parity under spec 04 while keeping
  `summon` `post_verb_globals` pinned to `{GlobalOption.DB}`.
```

### 2. `docs/specs/10-taut-tui.md`

#### 2a. `[TUI-3.1]` `taut-chat[default]` extra and absent-`tui` install hint

Original (`docs/specs/10-taut-tui.md`):
```markdown
The TUI implementation ships in the separate first-party distribution
`taut-tui`, import package `taut_tui`. Textual is its required terminal
framework and is not a core `taut-chat` runtime dependency. The convenience
extras `taut-chat[tui]` and `taut-chat[all]` install `taut-tui`; they do not
move its implementation or dependency ownership into core.

Normal imports, `taut --version`, root help, ordinary commands, and
`taut tui --help` do not import Textual or initialize TUI state. Only actual
TUI execution loads the framework. Without the extension, `tui` is an ordinary
unknown command and root help does not list it. An incomplete `taut-tui`
installation missing Textual produces one actionable reinstall diagnostic and
no traceback. A broken installed Textual dependency is reported as the actual
import failure, not mislabelled as a missing dependency.
```

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
The TUI implementation ships in the separate first-party distribution
`taut-tui`, import package `taut_tui`. Textual is its required terminal
framework and is not a core `taut-chat` runtime dependency. The convenience
extras `taut-chat[tui]`, `taut-chat[default]`, and `taut-chat[all]` install
`taut-tui`; they do not move its implementation or dependency ownership into
core.

Normal imports, `taut --version`, root help, ordinary commands, and
`taut tui --help` do not import Textual or initialize TUI state. Only actual
TUI execution loads the framework. Without the extension, root help does not
list `tui`, and `taut tui` exits 1 as `unknown command: tui` with a one-line
install hint naming `taut-tui` and `taut-chat[default]`. An incomplete `taut-tui`
installation missing Textual produces one actionable reinstall diagnostic and
no traceback. A broken installed Textual dependency is reported as the actual
import failure, not mislabelled as a missing dependency.
```

#### 2b. `[TUI-3.3]` Deterministic navigation highlight without auto-opening a watcher

Original (`docs/specs/10-taut-tui.md`):
```markdown
On an initialized workspace, startup resolves the acting identity through the
ordinary public client and enters the last session's in-memory default only;
version 1 writes no TUI preference file. On an absent local workspace, the
empty state offers `workspace.initialize` for the resolved local target. On an
unrecognized identity, it offers native join or rejoin flows. Backend,
configuration, permission, and malformed-target failures do not masquerade as
an uninitialized local workspace.
```

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
On an initialized workspace, startup resolves the acting identity through the
ordinary public client and enters the last session's in-memory default only;
version 1 writes no TUI preference file. Populating or refreshing the navigation
list highlights the retained navigation target, the active conversation,
`#general` when joined, or the first navigation item without emitting synthetic
highlight feedback or auto-opening a conversation, so pressing Enter immediately
opens the highlighted item while unread counts and consumable notifications
remain untouched until explicit activation. On an absent local workspace, the
empty state offers `workspace.initialize` for the resolved local target. On an
unrecognized identity, it offers native join or rejoin flows. Backend,
configuration, permission, and malformed-target failures do not masquerade as
an uninitialized local workspace.
```

#### 2c. `[TUI-7.1]` `:reply [THREAD] MSG_ID TEXT` mirror parity

Original (`docs/specs/10-taut-tui.md`):
```markdown
The CLI's omitted-text and `-` stdin forms for `say` and `reply`, project-file
`onboard`, `join --recent`, and `whoami --show-token` are syntax-recognized but
CLI-only in the TUI. The TUI has no process-stdin command source, opens full
channel history natively, and keeps continuity tokens out of shared interactive
chrome; explicit `say ... --join` executes through the native send binding and
refreshes navigation.
```

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
The CLI's omitted-text and `-` stdin forms for `say` and `reply`, project-file
`onboard`, `join --recent`, and `whoami --show-token` are syntax-recognized but
CLI-only in the TUI. The TUI has no process-stdin command source, opens full
channel history natively, and keeps continuity tokens out of shared interactive
chrome; explicit `say ... --join` and both `:reply THREAD MSG_ID TEXT` and
`:reply MSG_ID TEXT` execute through the native bindings (`say --join` refreshes
navigation).
```

#### 2d. `## Related Plans`

Original (`docs/specs/10-taut-tui.md`):
```markdown
- `docs/plans/2026-11-24-phase-2b-summon-providers-and-attach-ergonomics-plan.md` —
  extends `SummonStartScreen`, `TuiSummonOperations.build_request`, and the
  `:summon` mirror with `provider_args` (while removing the stale nonexistent
  `terminal` start-form noun from [TUI-11.1] and recording `--status` and
  `--json` on `summon` as CLI-only).
```

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
- `docs/plans/2026-11-25-phase-3-packaging-cli-tui-polish-and-plan-hygiene-plan.md` —
  highlights the default/retained navigation row across startup and refreshes
  without auto-opening a watcher, extends `:reply` with optional `THREAD`, and
  records `taut-chat[default]` and the absent-`tui` install hint in [TUI-3.1].

- `docs/plans/2026-11-24-phase-2b-summon-providers-and-attach-ergonomics-plan.md` —
  extends `SummonStartScreen`, `TuiSummonOperations.build_request`, and the
  `:summon` mirror with `provider_args` (while removing the stale nonexistent
  `terminal` start-form noun from [TUI-11.1] and recording `--status` and
  `--json` on `summon` as CLI-only).
```

## Dependency-Ordered Implementation Slices

### Slice 0 — Normative Spec Promotion (Strategy A)
- Apply all `Replacement` blocks (`1a`–`1f`, `2a`–`2d`) to `docs/specs/02-taut-core.md` and `docs/specs/10-taut-tui.md`.
- Compute `shasum -a 256` of `git diff -- docs/specs/02-taut-core.md docs/specs/10-taut-tui.md`, update `Promotion baseline identifier` and `Status: promoted` in this plan and `docs/plans/README.md`, and verify `bin/check-plan-status-index`, `bin/check-doc-paths`, and `bin/check-cli-claims`.

### Slice 1 — Packaging (`taut-chat` Script Alias, `default` Extra, `bin/release.py` Sync) & Absent-Extension Hints
- Write RED tests first in `tests/test_command_registry.py`, `tests/test_cli.py`, `tests/test_release_script.py`, and `tests/test_core_summon_wheel_matrix.py`:
  - `dispatch(["tui"])` and `dispatch(["mcp"])` without installed extensions exit `1` with `unknown command: tui (install taut-tui or 'taut-chat[default]' to enable 'taut tui')` and `unknown command: mcp (install taut-mcp or 'taut-chat[default]' to enable 'taut mcp')`, while `taut --help` still omits uninstalled `tui`/`mcp` and `dispatch(["bogus"])` emits plain `unknown command: bogus`.
  - `release.sync_root_default_dependencies()` / `release._sync_root_release_dependencies()` updates `taut-summon`, `taut-mcp`, and `taut-tui` floors inside `[project.optional-dependencies].default` via the shared `_sync_root_extra_floors()` helper (updating `tests/test_release_script.py:433, 629, 1283`).
  - `pyproject.toml` exposes `taut-chat = "taut.cli:main"` and `default` extra; `bin/check-core-summon-wheel-matrix.py` rejects core wheels missing the `taut` + `taut-chat` `console_scripts` pair and executes `taut-chat --version` in `_case_new_core`.
- Implement in `pyproject.toml`, `uv.lock`, `bin/release.py`, `taut/commands/_dispatch.py`, and `bin/check-core-summon-wheel-matrix.py`; verify GREEN.

### Slice 2 — Optional-`THREAD` `reply`, `TautClient` Context Manager & TUI Navigation Highlight Persistence
- Write RED tests first in `tests/test_client.py`, `tests/test_shared_contract.py`, `tests/test_cli.py`, `tests/test_command_registry.py`, `tests/test_command_syntax.py`, and `extensions/taut_tui/tests/{test_tui_app,test_tui_domain}.py`:
  - `with TautClient(db_path=..., persistent=True) as client:` returns `client`, closes `_session` on normal and exceptional block exit, attaches cleanup failure as a note rather than masking a `with`-body exception, and does not force `persistent=True` when constructed with default `persistent=False`.
  - `TautClient.reply(None, msg_id, text)` on SQLite and PostgreSQL (`test_shared_contract.py`): posts into `f"{channel}.{msg_id}"` when joined to the parent channel; raises `BlankMessageError` before `msg_id` validation on blank/Cf text; raises `TypeError` on non-`str` `msg_id`; raises `MessageIdResolutionError` on non-19-digit or out-of-int64-range (`"9999999999999999999"`) `msg_id`; raises `MessageIdNotFoundError` when `msg_id` is absent, in an unjoined channel, in a sub-thread, or in a DM.
  - CLI `taut reply`: 2-arg `taut reply MSG_ID "text"`, 2-arg `taut reply MSG_ID -` (stdin), 1-arg `taut reply MSG_ID` (piped stdin), 3-arg `taut reply THREAD MSG_ID "text"`, 3-arg out-of-range `taut reply general 9999999999999999999 "hi"` (exit `1`), 2-arg `taut reply THREAD MSG_ID` (piped stdin, including digit-only channel `2026`), updated `[THREAD] MSG_ID [TEXT|-]` usage hint in `test_cli.py:3192` and `test_command_registry.py:3812-3826`, and real subprocess `stdin=subprocess.DEVNULL` probes (`taut reply general`, `taut reply 12345`, `taut reply 12345 "hi"`, and `taut reply general "hi"` all exit `1` with `"SystemExit" not in err`, never silent exit `2`).
  - `parse_command_line` & TUI `:reply`: `:reply MSG_ID "text"` and `:reply THREAD MSG_ID "text"` dispatch natively; `:reply MSG_ID` and `:reply THREAD MSG_ID` report `CLI-only in TUI: reply with stdin`; `:reply general` fails syntax parsing with `missing required value: msg_id`.
  - TUI navigation highlight: on `TautApp` launch with joined channels `("ops", "general")`, `navigation.highlighted` is set to `#general`'s index with `visual_state.selected_navigation == "general"`, `active_conversation is None`, unread counts intact, and pressing `Enter` immediately opens `general` without pressing `Down`/`j` first; subsequent `refresh_navigation()` preserves both channel and populated-list `ActionId` row (`ActionId.NOTIFICATIONS_OPEN`) highlights; empty-state uninitialized/unrecognized launches set `navigation.highlighted == 0` while keeping `visual_state.selected_navigation is None` (and joining `general` from the unrecognized empty state transitions the highlight to `#general` with `selected_navigation == "general"`, not `"  Join channel"`).
- Implement in `taut/client/_base.py`, `taut/client/_messaging.py`, `taut/commands/syntax.py`, `taut/commands/reply.py`, and `extensions/taut_tui/taut_tui/{domain,app}.py`; verify GREEN.

### Slice 3 — `F8` `bin/check-plan-status-index` Plan-Tier Counts, Plan & README Hygiene, CI `conftest.py`, Skill/Runbook Evaluation & Lessons
- Write RED tests first in `tests/test_plan_status_index.py` and `tests/test_github_workflows.py`:
  - `bin/check-plan-status-index` prints derived plan-tier counts across allowed statuses (`draft`, `active`, `promoted`, `status-review`, `completed`, `superseded`, `retired-pending`, plus `harvest candidates (completed/superseded non-exemplars)`) on its `OK` summary line while keeping `"plan status index OK"` intact.
  - `tests/test_github_workflows.py:1351` asserts `mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_pg/tests/conftest.py` in `.github/workflows/test-pg-extension.yml`.
- Implement count reporting in `bin/check-plan-status-index`, reconcile `docs/plans/README.md`, plan headers (`2026-11-10`, `2026-07-29`, `2026-09-23`, `2026-08-19`, `2026-08-25`), and `docs/coalescing.md` (with explicit dispositions for all 10 remaining `active` plans and `2026-08-14` `status-review`), add `extensions/taut_pg/tests/conftest.py` to `.github/workflows/test-pg-extension.yml`, update `README.md`, `extensions/*/README.md`, `tests/test_project_metadata_consistency.py`, `docs/implementation/{02-repository-map,04-taut-architecture,06-command-extensions,12-taut-tui}.md`, and record durable 2026-11-25 lessons in `docs/lessons.md`.

## Skill and Runbook Evaluation (`AGENTS.md` Definition of Done)

Heavily used skills and runbooks across Phases 0–3 were evaluated for completeness:

1. `skills/call-agent/SKILL.md` (read-only evaluation; worktree has owner edits so file is untouched): the non-interactive read-only review recipes (`claude -p --permission-mode plan --tools Glob,Grep,Read --strict-mcp-config` and `codex exec -s read-only`) worked reliably with zero write-denial loops. No process change required.
2. `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` & `docs/program-theory.md`: Phase 2B and Phase 3 proved that passing `docs/program-theory.md` (`[THEORY-1]`–`[THEORY-5.A6]`) as an explicit primary lens in plan and completed-work review briefs catches wrapper/overload/duplicate-gate over-engineering that pure defect-hunting reviews miss. Recorded as a durable 2026-11-25 lesson in `docs/lessons.md`.
3. `docs/agent-context/runbooks/adversarial-acceptance-probes.md` & `testing-patterns.md`: `stdin=subprocess.DEVNULL` subprocess probes and POSIX PTY `SIG_IGN` `SIGHUP` reset / `TIOCGWINSZ` attach sync (alongside the existing 2026-07-12 `TCSADRAIN` master-drain rule) exposed real CLI/PTY edge cases; captured as concrete 2026-11-25 lessons in `docs/lessons.md`.
4. `skills/coalescing/SKILL.md`: Emitting derived plan-tier counts directly from `bin/check-plan-status-index` in Slice 3 closes the mental-arithmetic drift gap (`F8`) at step 1 without adding a second parser in `bin/coalesce-check`.

## Testing Plan

- `tests/test_command_registry.py`, `tests/test_cli.py`, `extensions/taut_tui/tests/test_tui_launch.py`: absent `tui`/`mcp` hints, `taut reply` 1/2/3-arg + `2026` digit-channel + `DEVNULL` (`"SystemExit" not in err`) + piped-stdin + blank/malformed/out-of-range matrix.
- `tests/test_client.py` & `tests/test_shared_contract.py`: `with TautClient(...) as client:` normal/exceptional lifecycle and `TautClient.reply(None, msg_id, text)` across SQLite and live Docker PostgreSQL.
- `tests/test_command_syntax.py`, `extensions/taut_tui/tests/test_tui_app.py`, `test_tui_domain.py`, `test_tui_action_routes.py`: `:reply` 2-arg/3-arg mirror and `_set_navigation_actions` startup/refresh/empty-state/`ActionId`-row highlight persistence without `ActionId` pollution or cursor/notification side effects.
- `tests/test_release_script.py`, `tests/test_project_metadata_consistency.py`, `tests/test_core_summon_wheel_matrix.py`, `tests/test_plan_status_index.py`, `tests/test_github_workflows.py`: `default` extra sync, `taut-chat` console script metadata + wheel execution, README metadata consistency, `bin/check-plan-status-index` plan-tier counts, and `test-pg-extension.yml` `conftest.py` mypy check.

## Verification and Gates

```bash
# 1. Plan, path, CLI-claim, coalescing, self-tests, kernel sync & Ruff suppression gates
uv run python bin/check-plan-status-index && \
uv run python bin/check-plan-status-index --self-test && \
uv run python bin/check-doc-paths && \
uv run python bin/check-doc-paths --self-test && \
uv run python bin/check-cli-claims && \
uv run python bin/check-dom15-fixtures && \
uv run python bin/coalesce-check && \
uv run python bin/ruff_suppression_index.py --check && \
cmp -s docs/agent-kernel.md taut/agent-kernel.md

# 2. Ruff lint, Ruff format check & Mypy across root and all four extensions (incl. taut_pg conftest.py)
uv run ruff check . && \
uv run ruff format --check taut tests bin extensions && \
uv run mypy taut tests bin/release.py bin/release-artifact.py bin/require-green-workflows.py --config-file pyproject.toml && \
uv run --extra dev mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_pg/tests/conftest.py --config-file pyproject.toml && \
uv run mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_summon/tests/conftest.py --config-file pyproject.toml && \
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml && \
uv run --project extensions/taut_tui --extra dev ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests && \
uv run --project extensions/taut_tui --extra dev mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests --config-file extensions/taut_tui/pyproject.toml

# 3. Full behavioral pytest suites (root, summon, TUI, MCP, and live Docker PostgreSQL) + Fresh release-wheel matrix
uv run pytest -q -m "not pg_only" && \
TAUT_SUMMON_LIVE_HARNESS=0 TAUT_SUMMON_LOCAL_LLM=0 uv run --project extensions/taut_summon --extra dev pytest extensions/taut_summon/tests -q -m "not xdist_group and not requires_live_harness and not requires_local_llm and not windows_only" && \
TAUT_SUMMON_LIVE_HARNESS=0 TAUT_SUMMON_LOCAL_LLM=0 uv run --project extensions/taut_summon --extra dev pytest extensions/taut_summon/tests -q -m "xdist_group and not requires_live_harness and not requires_local_llm and not windows_only" -n auto --dist load && \
uv run --directory extensions/taut_tui pytest -q -n 2 --dist loadfile && \
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -q -m "not pg_only" && \
uv run ./bin/pytest-pg && \
uv run ./bin/pytest-pg extensions/taut_mcp/tests && \
uv run python bin/build-and-check-release-wheels.py
```

## Independent Review Loop (`[DOM-5]`, `[DOM-11]`)

- **Author family**: Agy / Gemini (`Google DeepMind`).
- **Reviewer family**: Claude / Anthropic (`claude 2.1.293`, cross-family Tier-1 read-only review via `skills/call-agent/SKILL.md`).
1. **Plan & Program-Theory Review (before Slice 0)**:
   - Round 1 (`claude-opus-5-5`, 86 read calls, `Verdict: BLOCKED`): surfaced 4 `[P1]` and 6 `[P2]` findings — all 10 accepted to remove dead/over-engineered branches and tighten invariants: (1) dropped unreachable duplicate-`msg_id` branch (`SimpleBroker` `ts` PK is database-unique) and reused `_locate_exact_message` + `_reply_to_parent`; (2) fixed `ActionId` (`StrEnum`) guard to `None if isinstance(selected, ActionId) else selected` in both `_set_navigation_actions` and `app.py:786`; (3) rejected non-19-digit single-positional `taut reply <arg>` as exit `1` usage error before `stdin` read (`DEVNULL` safe) and specified `ReplyCommand.configure_parser`; (4) kept `bin/coalesce-check` plan-tier counts strictly informational so `bin/check-plan-status-index` remains the sole structural gate; (5) dropped 2-arg `TautClient.reply(msg_id, text)` positional overload in favor of `reply(thread: str | None, msg_id: str, text: str)`; (6) reused `_validate_exact_message_id` (preserving `TypeError` for non-`str`); (7) dropped `not a.isdigit()` from 2-token `reply` classification (preserving digit-only channel names like `2026`) and documented the grammar in `[TAUT-8.1]` and `[TAUT-8.7]`; (8) generalized `bin/release.py` extra sync via `_sync_root_extra_floors()`; (9) specified `WheelMetadata.console_scripts` + `python.with_name(...)` wheel-matrix check; (10) updated `test_github_workflows.py:1351`, guarded `__exit__` unwinding via `capture_cleanup_failure` + `add_note`, fixed backticks on `2026-08-19` header target, listed `test_command_registry.py` overrides/usage lines, added `Original` spans, and added explicit `F8` dispositions for all remaining `active` plans.
   - Round 2 (`claude-opus-5-5`, 66 read calls, `Verdict: BLOCKED` on `P1-A` + `P2-B`/`P2-C`/`P2-D`): confirmed all 10 Round 1 fixes and all 13 `Original` spec spans, and caught 4 remaining items — all 4 accepted: (`P1-A`) dropped `self._parser.error(...)` from `ReplyCommand.run()` (which would emit `SystemExit(1)` through `_dispatch.py:777`) in favor of `except CommandSyntaxError as exc: raise MessageIdResolutionError(str(exc)) from exc` before `context.client()`; (`P2-B`) moved derived plan-tier counts onto `bin/check-plan-status-index` (`run()`) so `## Plan Status Index` has one parser and one owner (`bin/coalesce-check` untouched); (`P2-C`) preserved `prior = self._navigation_targets[navigation.highlighted]` (including `ActionId` rows) across `refresh_navigation()` while keeping `selected_navigation` `None` for `ActionId`; (`P2-D` + observations) specified inserting `Status: completed` into `2026-07-29`, added `2026-08-14` (`status-review`) disposition, passed `exact: int` into `_resolve_message_id`, and added explicit-`THREAD` out-of-range `MSG_ID` test.
   - Round 3 (`claude-opus-5-5`, 30 read calls, `Verdict: BLOCKED` on `P2-C` empty-state-to-populated `ActionId.CHANNEL_JOIN` carry-over): verified `P1-A`, `P2-B`, and `P2-D`, and caught that carrying `prior == ActionId.CHANNEL_JOIN` from the unrecognized-identity empty state into the first populated list after joining `general` would highlight `"  Join channel"` instead of `#general`; fixed by retaining an `ActionId` `prior` only when the previous list was already populated (`ActionId.NOTIFICATIONS_OPEN in self._navigation_targets`), adding the unrecognized-launch -> join `general` -> `#general` highlight test, and renaming the `bin/check-plan-status-index` label to `harvest candidates (completed/superseded non-exemplars)`.
   - Round 4 scoped verification (`claude-opus-5-5`, 7 read calls, `Verdict: PASS`): verified the `P2-C` empty-state-to-populated `ActionId` guard across all six navigation state transitions and the `harvest candidates` label.
2. **Completed-Work & Program-Theory Review (after all verification gates pass)**:
   - Round 1 (`claude-opus-5-5`, 71 read calls, `Verdict: BLOCKED` on `P1-1` doc lesson + 4 actionable `P2` items): confirmed zero code `P1`s and verified all program-theory invariants (`[THEORY-5.A1]`, `[THEORY-5.A4]`, `[TAUT-6.5]`, `[TAUT-7.2]`, `[TUI-3.1]`), and surfaced: (`P1-1`) accepted — rewrote the 4th `2026-11-25` lesson in `docs/lessons.md` to drop the inaccurate `TCSANOW` claim; (`P2-1`) accepted — made `exact: int` required on `_resolve_message_id` and deleted the dead `exact is None` branch; (`P2-2`) accepted — cached `channel_rows: dict[str, ThreadRow]` in `_locate_joined_channel_message` and eliminated the duplicate `get_thread` query/branch; (`P2-3`) accepted — derived `ALLOWED_STATUSES = frozenset(STATUS_DISPLAY_ORDER)` and shared `_check_rows()` in `bin/check-plan-status-index` so `run()` parses `index_text` once; (`P2-4`) accepted — asserted exact `type(...) is MessageIdResolutionError` in `tests/test_shared_contract.py` and added both channel-row refresh highlight persistence (`"alpha"`) and a fresh-launch -> immediate `Enter` -> `active_conversation == "general"` case in `extensions/taut_tui/tests/test_tui_app.py`; (`P2-5`) declined for this unit (reviewer-labeled scope expansion / owner decision: `taut/commands/_summon_compat.py`'s `pipx inject taut-chat taut-summon` wording is pinned by `docs/specs/04-summon.md` and `tests/test_core_summon_wheel_matrix.py:1403`).
   - Round 2 (`claude-opus-5-5`, 15 read calls, `Verdict: BLOCKED` on `P1-R2-1` + `P2-R2-1`/`P2-R2-2`): verified `P2-1`, `P2-2`, `P2-3`, and `P2-4`, and caught (`P1-R2-1`) that the rewritten `2026-11-25` PTY lesson named `preexec_fn` instead of `_CONTROLLING_TERMINAL_TRAMPOLINE` in `extensions/taut_summon/taut_summon/_process_domain_posix.py` (`SIG_IGN` inheritance across `os.execvpe` + continuous `TIOCGWINSZ` sync across the attach loop), plus (`P2-R2-1`/`P2-R2-2`) stale pre-`P2-2` plan prose and `test_tui_app.py` comment; all three accepted and updated.
   - Round 3 (`claude-opus-5-5`, 12 read calls, `Verdict: PASS`): verified `P1-R2-1`, `P2-R2-1`, and `P2-R2-2` against `_process_domain_posix.py`, `_pty_posix.py`, `docs/lessons.md`, `test_tui_app.py`, and this plan, with zero open findings and all standing boundaries intact.

## Out of Scope

- Merging the five PyPI distributions into one wheel (explicitly declined by Owner Q4 until/unless the `taut` PyPI namespace is acquired for a separate fat distribution).
- Making `thread` optional on `taut-mcp`'s JSON-RPC `reply` tool (`[MCP-5]` keeps explicit structured `thread` + `msg_id` properties on the MCP wire surface).
- Taut-owned upward fallback for presentation-only `.taut.toml` (`[TAUT-3.2]`: SimpleBroker owns target discovery).
- Auto-opening a live `TautWatcher` on TUI startup, single-click navigation activation, or permanent footer keybars (`[THEORY-2]`, `[THEORY-5.A1]`, `[TUI-5.2]`, `[TUI-6.1]`, `[TUI-8.2]`).
- Physical deletion or unverified soft-retirement of plans whose harvest gates require separate owner-gated spec/runbook amendments (`skills/coalescing/SKILL.md` §4).

## Fresh-Eyes Review

Checked against baseline `6f17b9438e0eaf80a252b987d82143b1e73f1737`:
1. Every `Original` and `Replacement` block in `## Proposed Spec Delta` matches exact verbatim target spans in `docs/specs/02-taut-core.md` and `docs/specs/10-taut-tui.md`, and avoids unexempted backticked `taut tui`/`taut mcp` claims in `02-taut-core.md`.
2. `resolve_reply_positionals` rejects non-19-digit 1-token invocations (`taut reply general`) as exit `1` usage errors before reading `stdin` (`DEVNULL` safe), preserves digit-only channel names (`2026`) in 2-token piped-stdin calls, and `TautClient.reply(thread: str | None, msg_id: str, text: str)` avoids positional reinterpretation and dead duplicate-id code.
3. `_set_navigation_actions` preserves `prior = self._navigation_targets[navigation.highlighted]` across refreshes, wraps `navigation.highlighted = ...` in `with navigation.prevent(TautOptionList.OptionHighlighted):`, and uses `None if isinstance(selected, ActionId) else selected` (fixing `app.py:786` as well, since `ActionId` is a `StrEnum`).
4. `bin/check-plan-status-index` prints derived plan-tier counts directly from its validated `rows` without adding a second parser in `bin/coalesce-check`.
5. `skills/call-agent/SKILL.md` remains untouched in the working tree.

## Execution Log

- `2026-11-25`: Authored Class 5+P hardened Phase 3 plan (`Author family: Agy / Gemini`) after auditing all candidate items against `docs/program-theory.md`, Owner Q4, `[TAUT-3.2]`/`[TAUT-8.1]`/`[TAUT-12.5]`, and `[TUI-3]`–`[TUI-8]`.
- `2026-11-25`: Completed Round 1 Tier-1 `claude-opus-5-5` read-only plan & program-theory review (`READ_TOOL_CALLS: 86`); accepted all 10 findings (`4 P1`, `6 P2`) to simplify `TautClient.reply`, fix `ActionId` `StrEnum` guarding, close the 1-arg `DEVNULL` `reply` edge case, and keep `bin/coalesce-check` plan counts informational.
- `2026-11-25`: Completed Round 2 Tier-1 `claude-opus-5-5` read-only plan review (`READ_TOOL_CALLS: 66`); accepted `P1-A` (`MessageIdResolutionError` instead of `parser.error` inside `ReplyCommand.run`), `P2-B` (single-owner plan-tier counts in `bin/check-plan-status-index`), `P2-C` (`ActionId` row highlight preservation across `refresh_navigation`), and `P2-D` (`2026-07-29` status insertion + `2026-08-14` `status-review` disposition).
- `2026-11-25`: Completed Round 3 Tier-1 `claude-opus-5-5` scoped verification (`READ_TOOL_CALLS: 30`); verified `P1-A`, `P2-B`, `P2-D` and refined `P2-C` so `ActionId` `prior` is retained only across already-populated lists (`ActionId.NOTIFICATIONS_OPEN in self._navigation_targets`), preventing empty-state `ActionId.CHANNEL_JOIN` from shadowing `#general` after a first-run join.
- `2026-11-25`: Completed Round 4 Tier-1 `claude-opus-5-5` scoped verification (`READ_TOOL_CALLS: 7`, `Verdict: PASS`), applied Slice 0 spec promotion (`docs/specs/02-taut-core.md` and `docs/specs/10-taut-tui.md`, diff SHA-256 `59b054bbc8e97c3a37f20fa2744a6718fe9f9d26097e2532581dcc9f3113d1a7`), and verified `bin/check-plan-status-index`, `bin/check-doc-paths`, and `bin/check-cli-claims`.
- `2026-11-25`: Implemented Slices 1–3 via Red-Green TDD across root, `taut_tui`, `bin/release.py`, `bin/check-core-summon-wheel-matrix.py`, `bin/check-plan-status-index`, `.github/workflows/test-pg-extension.yml`, READMEs, implementation docs, `docs/coalescing.md`, and `docs/lessons.md`; passed all doc/CLI/DOM-15/coalesce/Ruff-suppression/kernel gates, Ruff lint/format, Mypy across root and all four extensions, full `pytest` across root/`taut_summon`/`taut_tui`/`taut_mcp`, live Docker PostgreSQL (`./bin/pytest-pg` and `./bin/pytest-pg extensions/taut_mcp/tests`), and `bin/build-and-check-release-wheels.py`.
- `2026-11-25`: Completed 3-round Tier-1 `claude-opus-5-5` completed-work & program-theory review (`71` + `15` + `12` read calls, `Verdict: PASS`); incorporated all accepted Round 1–2 code, test, and lesson precision fixes, re-verified gates, and marked plan `completed`.
