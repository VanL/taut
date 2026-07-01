# Plan: Split `taut/client.py` into a `taut/client/` package

Date: 2026-06-30
Status: Implemented 2026-07-01; reviewed and updated 2026-07-01 after the
`TautState` refactor and private-submodule naming review.
Risk: Moderate (public import surface preserved; behavior must not change).
Companion runbook: `docs/agent-context/runbooks/hardening-plans.md` (treated as
required input — this touches a public compatibility surface).

## 1. Goal

`taut/client.py` is a single 1,356-line module dominated by one intentionally broad
`TautClient` API surface that owns identity resolution, messaging, reads,
notifications, threads, and rename. The broad public surface is by design:
library users should import one client surface, and that surface should stay
isomorphic to the CLI verb surface. Split it into a `taut/client/` package whose
`__init__.py` is a thin facade (assembling one `TautClient` class from behavior
mixins and re-exporting the public names), with the concerns living in separate
underscore-prefixed private submodules. This is a structural refactor with **no
change to the observable contract**: no change to
public import paths (`from taut.client import X`), method signatures, semantics,
JSON shapes, or exit codes. The model dataclasses live in `_models.py` internally,
but their public `__module__` stays `taut.client` so introspection displays the
facade path (`taut.client.Message`) rather than the implementation path
(`taut.client._models.Message`). Pickle-path preservation is incidental; Taut does
not use or promise pickle compatibility for these value objects. The existing test
suite is the regression oracle for the observable contract and must stay green with
**zero additional test-file edits beyond the preflight dirty-tree baseline**.

## 2. Source Documents

Source specs:
- `docs/specs/02-taut-core.md` [TAUT-8.3] — Python API contract: public exports are
  `TautClient`, `TautWatcher`, `Message`, `Thread`, `Member`, the exception
  hierarchy rooted at `TautError`, and `__version__`; the CLI is a thin layer over
  `TautClient`; every CLI behavior maps to one public client method. The refactor
  must not disturb this.
- `docs/specs/02-taut-core.md` [TAUT-8.1] — the verb surface (`init`, `join`,
  `leave`, `set name`, `say`, `reply`, `read`, `inbox`, `log`, `list`, `watch`,
  `rename`, `who`, `whoami`, `rejoin`) whose semantics live in `TautClient`.

Supporting context:
- Local architecture review artifact (2026-06-30), "Separate identity resolution
  from verb orchestration" (rated **Speculative**, with an explicit
  "avoid premature seam" caution). This plan honors that caution by doing the
  lowest-behavioral-risk mechanical split (mixins that keep one `TautClient` class),
  **not** the heavier collaborator-object redesign (see §9).
- `docs/agent-context/runbooks/testing-patterns.md` rule 5 — TDD default and its
  substitute-proof requirement (see §6).
- `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md` — implemented after this
  split and now owns the storage-layer seam. Storage references in this plan should
  be read through that later state-refactor reality: production client modules use
  `taut.state`, not `taut.schema`.

## 3. Context and Key Files

### The file being split

At the time of implementation, `taut/client.py` contained, in order:
- Missing-backend helpers: `_MISSING_POSTGRES_PLUGIN_ERROR`,
  `_MISSING_POSTGRES_PLUGIN_HINT`, `_raise_with_backend_install_hint`.
- Public dataclasses: `Member`, `Thread`, `Message`, `Notification`, `InitResult`.
- Internal dataclass: `_ResolvedMember`.
- `class TautClient` — `__init__`, classmethod `init`, `queue`, and the verb methods
  plus ~25 private helpers (`_resolve_member`, `_create_member`,
  `_created_resolution`, `_record_claim`, `_ensure_notification_thread`,
  `_capture`, `_require_member`, `_resolve_target`, `_say_chat_thread`, `_say_dm`,
  `_implicit_subthread_membership`, `_write_message`, `_insert_message`,
  `_message_from_body`, `_message_from_decoded`, `_write_mention_notifications`,
  `_write_notification`, `_notification_from_body`, `_thread_from_row`,
  `_member_from_row`, `_resolve_message_id`, `_last_message_ts`, `_unread_count`,
  `_parse_since`, `_ensure_no_incomplete_channel_rename`).
- Module functions: `database_path_from_target`, `_json_dumps`.

### Consumers that constrain the public surface (do NOT edit these)

- `taut/__init__.py:21` → `from taut.client import Member, Message, Notification, TautClient, Thread`.
- `taut/cli.py:29` → `from taut.client import InitResult, Member, Message, Notification, TautClient, Thread`.
- `taut/watcher.py:46` → originally imported `Message`, `Notification`, and
  `TautClient` from `taut.client`, and reached instance internals. At split time
  this was `_meta_queue`, `_notification_from_body`, and `_message_from_body`.
  After the `TautState` refactor, the watcher also reached `self.client._state`
  for membership reads and cursor advancement. The current implementation no
  longer uses that private client surface; it uses `TautWatchRuntime` from
  `docs/plans/2026-07-01-taut-watch-runtime-plan.md`.
- Tests: `tests/test_client.py`, `tests/test_cli.py`, `tests/test_shared_contract.py`,
  `tests/test_watcher.py` (uses `client._meta_queue` at 388, 404),
  `tests/test_project_config.py`, `tests/test_public_api.py`, and
  `extensions/taut_pg/tests/test_pg_integration.py`, `test_pg_sidecar.py`
  (`from taut.client import TautClient`).

**These import paths are the public contract.** After the split,
`from taut.client import <name>` must work for `TautClient`, `Member`, `Thread`,
`Message`, `Notification`, `InitResult`, and `database_path_from_target`.

The instance-attribute accesses were compatibility constraints, not a desired API.
The split preserved them to avoid behavior drift. The post-state-refactor watcher
dependency on `client._state` was resolved by
`docs/plans/2026-07-01-taut-watch-runtime-plan.md`; do not promote `_state` to a
public or semi-public contract.

### Target package shape

The package facade is the only supported client import surface. Concern modules are
implementation detail and should be underscore-prefixed:

```text
taut/client/
  __init__.py          # public facade and re-export surface
  _base.py            # shared runtime state, target resolution, module helpers
  _models.py          # public value-object definitions, re-exported by facade
  _identity.py        # identity/member/name/rejoin behavior
  _messaging.py       # say/reply/read/log/message helpers
  _notifications.py   # notification inbox/write/parse behavior
  _threads.py         # join/leave/list/rename/thread metadata behavior
```

Why: `taut.client` is intentionally the single API surface, mirroring the CLI. Bare
submodules such as `taut.client.messaging` look importable and stable even when they
are just the implementation layout. Prefixing them with `_` gives users and agents a
clear rule: import `TautClient`, `Message`, and friends from `taut.client`; do not
build on concern-module internals. The model classes still report
`__module__ = "taut.client"` so public object identity stays clean.

### Tooling facts (already verified)

- `pyproject.toml` `[tool.hatch.build] include = ["/taut/**/*.py"]` already globs a
  package directory — converting `client.py` to `client/` is packaging-safe.
- `[tool.mypy] no_namespace_packages = true`, strict (`disallow_untyped_defs`,
  `disallow_incomplete_defs`, `warn_unused_ignores`). `taut/py.typed` exists at the
  package root and continues to cover the subpackage.
- `[tool.ruff.lint.isort] known-first-party = ["taut"]`; line length 88.

### Read first, with comprehension checks

- `taut/client.py` in full (the god-class).
- `taut/watcher.py:527-640` (historically, the `TautWatcher` handlers that
  called client internals before `TautWatchRuntime`).
- `taut/cli.py:29` and the exit-code mapping (how CLI turns client exceptions into
  0/1/2) — confirm it keys off exception *types*, not module locations.

Comprehension checks:
1. Which `TautClient` members are accessed from outside `taut/client.py` today, and
   must therefore stay instance-accessible (not become module-level free
   functions)? Answer — the full inventory (verify with
   `git grep -nE 'client\._[a-z]|\._(state|meta_queue|capture|create_member|message_from_body|notification_from_body)'`):
   - `taut/watcher.py`: currently `_state`, `_message_from_body`,
     `_notification_from_body`; historically `_meta_queue` before the `TautState`
     refactor.
   - `tests/test_watcher.py`: `_meta_queue`.
   - `tests/test_client.py`: `_meta_queue`, **`_capture`**, **`_create_member`**.
   Under the module map, `_meta_queue`/`_capture` live on `_ClientBase`,
   `_create_member` on `IdentityMixin`, `_message_from_body` on `MessagingMixin`,
   `_notification_from_body` on `NotificationsMixin` — all remain instance methods of
   the assembled `TautClient`, so every access above keeps working. `_state` lives on
   `_ClientBase` after the later state refactor, but that is a known layering
   compromise to remove in follow-up work. (An earlier draft listed only the three
   watcher accesses; the `test_client.py` accesses to `_capture` and `_create_member`
   are the reason the module map must keep them as methods, not convert any to free
   functions.)
2. Why does splitting into *mixins on one class* preserve those accesses while
   splitting into free functions would break them? (Answer: mixins contribute
   methods to the single `TautClient` MRO, so `self._x` / `client._x` still
   resolve; free functions would move the callable off the instance.)
3. Does `taut.watcher` create an import cycle? (Answer: no — `TautClient.watch`
   imports `TautWatcher` lazily inside the method; keep it lazy.)

## 4. Invariants and Constraints

Behavior/contract:
- Public import paths unchanged. `taut/__init__.py` and `taut/cli.py` import lines
  are **not edited**; they must keep resolving.
- `TautClient` stays a **single class** with identical method names, signatures,
  and semantics. Same `Message`/`Thread`/`Member`/`Notification`/`InitResult`
  field sets and JSON shapes ([TAUT-8.2]).
- The preserved public object identity is the facade path. Moving the dataclasses to
  `_models.py` is an internal organization choice; set `Member.__module__`,
  `Thread.__module__`, `Message.__module__`, `Notification.__module__`, and
  `InitResult.__module__` to `"taut.client"` so introspection, docs, notebooks, and
  error output show `taut.client.Message` rather than `taut.client._models.Message`.
  This happens to preserve the pickle-by-reference path, but pickle compatibility is
  not a supported Taut persistence or interchange contract.
- Instance internals used by the watcher/tests remain instance-accessible — the full
  split-time set is `_meta_queue`, `_message_from_body`, `_notification_from_body`
  (watcher + tests) and `_capture`, `_create_member` (`tests/test_client.py`). After
  the `TautState` refactor, `_state` is also reached by `TautWatcher`; this is not an
  endorsed API boundary and should be removed by a follow-up layering fix.
- Exceptions are raised from the same logical points and with the same types (the
  CLI exit-code mapping depends on types).
- Single write path invariant [TAUT-3.5] preserved: still only
  `queue.insert_messages(...)`; no `Queue.write()` introduced.
- No new runtime dependency; argparse/CLI untouched; `_json_dumps` canonical form
  (sorted keys, compact separators) preserved for notification bodies.

Boundaries that must not split into parallel paths:
- One `TautClient`, one `__init__`, one set of instance attributes
  (`config`, `target`, `as_name`, `token`, `identity_capture`,
  `last_created_member`, `last_candidates`, `last_notification_warnings`,
  `_meta_queue`, and after the later state refactor `_state`). Mixins must read
  shared state through a single typed base, not redefine it.

Type design (mypy) — load-bearing, see Task 3:
- All mixins inherit `_ClientBase`; `TautClient` lists the mixins first and
  `_ClientBase` **last** (base-before-subclass is an illegal MRO).
- Cross-mixin `self.` calls type-check only because `_ClientBase(ABC)` declares
  `@abstractmethod` stubs for the four cross-referenced methods (`_resolve_member`,
  `_insert_message`, `_write_message`, `_write_notification`); "single class at
  runtime" does **not** by itself satisfy strict mypy, which checks each mixin body
  standalone. A bare `...` body on a non-abstract method fails strict mypy
  (`[empty-body]`) for non-`None` returns — `@abstractmethod` is the form that
  passes. No `# type: ignore` may be added to make the split compile.
- `_json_dumps`, `_raise_with_backend_install_hint`, and `_MISSING_POSTGRES_PLUGIN_*`
  stay **module-level functions/constants** (they are called as module globals
  today, not `self.`); they move to `_base.py` as module members and are imported by
  the facade / `_notifications.py`, not converted to methods.
- Import direction is one-way: `__init__` → mixins → (`_base`, `_models`,
  `taut.state`/`identity`/`addressing`). No submodule imports `taut.client`.
  Historical references to `taut.schema` in this plan are superseded by the
  `TautState` refactor; production client modules must not import `taut.schema`.

Review gates:
- **No behavior change and no drive-by refactor.** If a change is tempting mid-move
  (rename a method, "fix" a branch), stop — that belongs in a follow-up, not here.
- **Zero additional test-file diffs beyond the preflight dirty-tree baseline.** The
  current branch may already contain modified tests from earlier work; capture that
  baseline before starting. If this plan requires editing tests beyond that
  baseline to pass, behavior drifted — stop and re-evaluate (this is the primary
  safety net; see §6).

One-way door: none. This is a file-structure move, fully revertible from git.
Rollback = revert the commits / `git checkout HEAD -- taut/client.py` (restores the
single module). Because rollback is trivial and behavior-preserving, the safe
rollout is simply "land behind green suite + mypy."

## 5. Tasks

Dependency-ordered; each task is an independently reviewable slice that ends with
the full suite + mypy green and **no additional diff under `tests/` beyond the
preflight baseline**. Do the moves with `git mv` where possible so review shows
moves, not rewrites.

Naming correction: the first implementation landed bare concern-module names
(`base.py`, `models.py`, `identity.py`, `messaging.py`, `notifications.py`,
`threads.py`). Treat those as an implementation artifact, not the target design. If
applying this plan from scratch, use the underscore-prefixed private names in §3.
If starting from the current package, perform Task 9 as a focused follow-up rename.

1. **Create the package with zero behavior change (pure move).**
   - Convert `taut/client.py` → `taut/client/__init__.py` verbatim
     (`mkdir taut/client && git mv taut/client.py taut/client/__init__.py` — the
     directory must exist first or `git mv` errors). No code edits.
   - Reuse: nothing new. Read first: hatch `include` glob (already covers it).
   - Verify: `uv run pytest -q`,
     `uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml`,
     `python -c "from taut.client import TautClient, Member, Thread, Message, Notification, InitResult, database_path_from_target"`.
   - Done signal: suite green, imports resolve, `git diff` shows only a rename.

2. **Move public dataclasses to `_models.py` (do this before `_base.py`).**
   - Create `taut/client/_models.py` with `Member`, `Thread`, `Message`,
     `Notification`, `InitResult` (pure dataclasses, no client dependency).
   - `__init__.py` imports and re-exports them so `from taut.client import Message`
     etc. still work. `_models.py` must **not** import from `__init__` (avoid a
     cycle).
   - Ordering rationale: `_base.py` (Task 3) annotates
     `last_created_member: Member | None` and its abstract stubs return `Message`, so
     the dataclasses must already have a dependency-free home to import from;
     creating `_base.py` first would force it to import `Member`/`Message` from the
     facade — the exact cycle this refactor avoids.
   - Verify: `tests/test_public_api.py` green; full suite + mypy green; no `tests/` diff.
   - Done signal: dataclasses live in `_models.py`; re-exported unchanged; their
     `__module__` values remain `taut.client`.

3. **Establish the typed base (`_base.py`) — the concrete type design.**
   - Create `taut/client/_base.py` containing, in this order:
     - **Module-level (NOT methods — keep them module functions, call sites unchanged):**
       `_MISSING_POSTGRES_PLUGIN_ERROR`, `_MISSING_POSTGRES_PLUGIN_HINT`,
       `_raise_with_backend_install_hint(...)`, and `_json_dumps(...)`. These are
       module globals in `taut/client.py` today (`_write_notification` calls
       `_json_dumps(payload)`, `init` calls `_raise_with_backend_install_hint(exc)` —
       both as module functions, not `self.`). Moving them onto the class would
       silently change those call sites; do **not**. Import them where used:
       `_notifications.py` does `from ._base import _json_dumps`; the facade
       `__init__.py` does `from ._base import _raise_with_backend_install_hint`.
     - `_ResolvedMember` (the internal dataclass, moved here now — its home must
       precede the mixins that reference it and `_require_member` which is typed
       against it).
     - `class _ClientBase(ABC):` (inherits `abc.ABC`).
   - `_ClientBase` holds, as **real implementations**: `__init__`, all
     instance-attribute annotations (`config`, `target`, `as_name`, `token`,
     `identity_capture`, `last_created_member`, `last_candidates`,
     `last_notification_warnings`, `_meta_queue`), `queue()`, `_resolve_target`,
     `_capture`, `_require_member`, and `_ensure_no_incomplete_channel_rename`
     (shared by nearly every verb — messaging/identity/threads/facade all call it —
     so it lives on the base as a real method and is **not** a `ThreadsMixin` member).
   - **Cross-mixin call contract (the mypy strategy — do not skip; verified below).**
     Under strict mypy each mixin body is checked against its own declared base, not
     the assembled `TautClient`. For every method one mixin calls on `self` but that
     is *defined in a different mixin*, declare it on `_ClientBase` as an
     **`@abstractmethod`** with the identical signature and a `...` body. (Empirically
     confirmed against this repo's `pyproject.toml` mypy config: a bare `...` body on
     a *non-abstract* method fails with `[empty-body] Missing return statement` for
     non-`None` returns; `@abstractmethod` with `...` passes, and `TautClient()` stays
     instantiable because the mixins override every abstract — with the bonus that a
     forgotten override fails loudly at construction instead of silently.) From the
     actual call graph the cross-mixin set is exactly four:
     - `@abstractmethod def _resolve_member(self, *, create: bool, force_new: bool = False, persona: str | None = None, allow_guest: bool = False) -> _ResolvedMember: ...`
       (defined in `IdentityMixin`; called from messaging, threads, notifications).
     - `@abstractmethod def _insert_message(self, *, queue: Queue, thread: str, from_id: str, from_name: str, kind: str, text: str, ts: int, notify_mentions: bool) -> Message: ...`
       (defined in `MessagingMixin`; called from `join`/threads).
     - `@abstractmethod def _write_message(self, *, queue: Queue, thread: str, from_id: str, from_name: str, kind: str, text: str, notify_mentions: bool) -> Message: ...`
       (defined in `MessagingMixin`; called from `leave`/threads).
     - `@abstractmethod def _write_notification(self, *, to_id: str, payload: dict[str, Any]) -> None: ...`
       (defined in `NotificationsMixin`; called from messaging).
     Copy each signature verbatim from `taut/client.py` so mypy's override check
     passes. Facade-only methods (`init`, `watch`, `database_path_from_target`) may
     call anything on `self` because `TautClient` has the full MRO — only *inter-mixin*
     calls need an abstract on the base.
   - **This set of four is derived from the module map in Tasks 4–7.** If you place
     any helper in a different module than this plan specifies, do not assume four —
     recompute the abstract set from the actual cross-module call graph (a method
     called on `self` from a mixin other than its home needs an abstract on the
     base). The mypy step is the check: an unresolved cross-mixin call surfaces as an
     `attr-defined` error, which is the signal to add the missing abstract, never a
     `# type: ignore`.
   - `TautClient` (still the full class in `__init__.py`) is changed to
     `class TautClient(_ClientBase)` for now; move only the listed members out.
   - Reuse: the exact current bodies; do not rewrite logic.
   - Verify: suite + mypy green (strict, no new `# type: ignore`); no additional
     `tests/` diff beyond the preflight baseline.
   - Done signal: `_base.py` has the module functions, `_ResolvedMember`, and
     `_ClientBase(ABC)` with the four `@abstractmethod` stubs; behavior unchanged.

4. **Extract `IdentityMixin` → `_identity.py`.**
   - Members: `_resolve_member`, `_created_resolution`, `_create_member`,
     `_record_claim`, `_ensure_notification_thread`, `_member_from_row`, and the
     identity verbs `whoami`, `rejoin`, `set_name`, `who`. (`_ResolvedMember` already
     in `_base.py` from Task 3.) `class IdentityMixin(_ClientBase)`.
   - Import rule (applies to every mixin): import dataclasses from `._models`,
     `_ResolvedMember` / `_ClientBase` / module helpers from `._base`, and
     collaborators from `taut.state` / `taut.identity` / `taut.addressing` —
     **never** from `taut.client` (the package `__init__` imports the mixins, so
     importing it back is the cycle to avoid).
   - `_resolve_member` provides the concrete override of the `_ClientBase`
     abstractmethod (signature must match verbatim).
   - **Update the facade bases in the same task:** `class TautClient(IdentityMixin, _ClientBase)`
     (mixins first, `_ClientBase` last). This is mandatory, not deferred to Task 7 —
     each extraction moves methods *out* of the facade class body, so the facade must
     inherit the new mixin in the same slice or the moved methods vanish from
     `TautClient` and the per-task green gate fails.
   - Verify: `tests/test_identity.py`, `tests/test_client.py` green; mypy clean.

5. **Extract `MessagingMixin` → `_messaging.py`.**
   - Members: `say`, `reply`, `read`/`read_unread`, `log`, `_say_chat_thread`,
     `_say_dm`, `_implicit_subthread_membership`, `_write_message`,
     `_insert_message`, `_message_from_body`, `_message_from_decoded`,
     `_write_mention_notifications`, `_resolve_message_id`, `_parse_since`.
   - `_message_from_body` must remain reachable as `client._message_from_body`
     (watcher). `_write_mention_notifications` calls `self._write_notification`
     (Notifications mixin) — allowed.
   - **Update the facade bases:** `class TautClient(IdentityMixin, MessagingMixin, _ClientBase)`.
   - Verify: `tests/test_client.py`, `tests/test_shared_contract.py`,
     `tests/test_watcher.py` green.

6. **Extract `NotificationsMixin` → `_notifications.py`.**
   - Members: `inbox`, `_write_notification`, `_notification_from_body`.
   - `_notification_from_body` must remain reachable as
     `client._notification_from_body` (watcher). `_notifications.py` imports the
     module-level `_json_dumps` from `._base`.
   - **Update the facade bases:** `class TautClient(IdentityMixin, MessagingMixin, NotificationsMixin, _ClientBase)`.
   - Verify: watcher + inbox paths green.

7. **Extract `ThreadsMixin` → `_threads.py`; finalize the facade.**
   - Members: `join`, `leave`, `list_threads`, `rename_channel`, `_thread_from_row`,
     `_last_message_ts`, `_unread_count`. (`_ensure_no_incomplete_channel_rename`
     stays on `_ClientBase` from Task 3 — it is called from most verbs across
     identity, messaging, threads, and the facade, e.g. `join`/`leave`/`say`/`reply`/
     `read`/`log`/`list`/`who`/`rename`/`watch` — so it is **not** a ThreadsMixin
     member.)
   - `__init__.py` now contains: imports of the mixins and models, then
     `class TautClient(IdentityMixin, MessagingMixin, NotificationsMixin, ThreadsMixin, _ClientBase)`
     — **`_ClientBase` MUST be last.** Every mixin inherits `_ClientBase`, so listing
     the base before its subclasses is an illegal MRO (`TypeError: Cannot create a
     consistent method resolution order`); base-last makes the linearization
     `TautClient → IdentityMixin → MessagingMixin → NotificationsMixin → ThreadsMixin
     → _ClientBase → object`, so each mixin's concrete method satisfies the base
     abstractmethod. `TautClient` is concrete (all four abstracts are overridden by
     the mixins), so it instantiates normally.
     The facade also keeps the `init` classmethod, `watch` (lazy `from taut.watcher
     import TautWatcher`), `database_path_from_target`, and the `__all__` re-export
     list: `TautClient`, `Member`, `Thread`, `Message`, `Notification`, `InitResult`,
     `database_path_from_target`.
   - Stop-and-re-evaluate gate: if MRO/attribute-resolution issues push you toward
     editing a test or adding `# type: ignore`, stop — the base/mixin boundary or the
     stub set in Task 3 is wrong, and guessing here will change behavior.
   - Verify: full suite + mypy + ruff green; `git diff --stat tests/` matches the
     preflight baseline.

8. **Docs + backlink.**
   - Update `docs/implementation/02-repository-map.md` and
     `docs/implementation/04-taut-architecture.md` where they describe
     `taut/client.py` as a single module, to reflect the `taut/client/` package and
     its submodules.
   - Add a backlink to this plan under `docs/specs/02-taut-core.md` `## Related
     Plans`, per the writing-plans "Backlink Rule" ([TAUT-8.3] is the touched
     contract).
   - Verify: `git grep -n 'client\.py' docs/implementation` reviewed; references
     updated or intentionally left.

9. **Rename concern modules to private implementation modules.**
   - Files to touch:
     - `taut/client/base.py` → `taut/client/_base.py`
     - `taut/client/models.py` → `taut/client/_models.py`
     - `taut/client/identity.py` → `taut/client/_identity.py`
     - `taut/client/messaging.py` → `taut/client/_messaging.py`
     - `taut/client/notifications.py` → `taut/client/_notifications.py`
     - `taut/client/threads.py` → `taut/client/_threads.py`
     - `taut/client/__init__.py` and internal relative imports
     - implementation docs that list the client package files
   - Use `git mv` for the renames so review preserves file history.
   - Do not add compatibility wrapper modules at the old bare paths. They were never
     documented public API. Adding wrappers would make accidental imports look
     supported and would create a second semi-public surface.
   - Keep public facade imports unchanged:
     `from taut.client import TautClient, Member, Thread, Message, Notification,
     InitResult, database_path_from_target`.
   - Keep public value-object identity unchanged:
     `Member.__module__`, `Thread.__module__`, `Message.__module__`,
     `Notification.__module__`, and `InitResult.__module__` stay `"taut.client"`.
   - Stop and re-evaluate if any README, spec, test, extension, or public example
     imports `taut.client.base`, `taut.client.models`, `taut.client.identity`,
     `taut.client.messaging`, `taut.client.notifications`, or `taut.client.threads`.
     That would mean the bare modules have escaped into a user-facing contract and
     require an explicit compatibility decision.
   - Verify:
     - facade import gate from §7
     - private submodule import gate from §7
     - `rg -n "taut\.client\.(base|models|identity|messaging|notifications|threads)" README.md docs/implementation docs/specs taut tests extensions --glob '*.py' --glob '*.md'`
       returns no public examples or production imports
     - full suite, ruff, format, mypy, and Postgres fast gate if any imports outside
       `taut/client/` changed
   - Done signal: only `taut.client` facade imports are externally visible; internal
     concern modules are clearly private by filename.

## 6. Testing Plan

TDD substitute proof (per testing-patterns rule 5): a behavior-preserving refactor
has no new behavior to express as a failing test first. The named substitute proof
is **the existing suite passing with zero additional edits under `tests/` beyond the
preflight dirty-tree baseline** — any required test edit for this refactor is
treated as a defect signal, not an expected step.

Scope of this oracle (important): the zero-test-diff gate proves the **observable
contract** is unchanged — import paths, method semantics, `--json` shapes, exit
codes, and the instance-accessible private surface the watcher/tests use. It should
also be paired with the §7 import/introspection shell gate so the public value
objects display as facade-owned classes. Pickle compatibility is not a supported
contract; preserving the pickle-by-reference path is only a side effect of keeping
`__module__` aesthetically aligned with the public facade.

- Harness/layer: the existing pytest suite against real `.taut.db` files (broker is
  never mocked — unchanged posture from [TAUT-11]).
- Protective tests that must stay green without edits:
  - `tests/test_public_api.py` — root `taut` exports (`import taut; taut.TautClient`,
    etc.). Note: this file asserts the **root** namespace only; it does **not**
    exercise `from taut.client import ...`. The `taut.client` import surface is
    guarded by the explicit shell import gate in §7, not by this test.
  - `tests/test_client.py`, `tests/test_shared_contract.py` — client semantics and
    `--json`/contract shapes.
  - `tests/test_cli.py` — exit codes 0/1/2 and JSON fields (proves exception types
    and shapes survive).
  - `tests/test_watcher.py` — at split time, exercised `client._meta_queue` and
    the `_message_from_body`/`_notification_from_body` coupling (proving the
    split-time internal surface survived). After the later `TautState` refactor,
    watcher also exercised `client._state`; this internal layering debt was
    resolved by `docs/plans/2026-07-01-taut-watch-runtime-plan.md`.
  - `tests/test_identity.py` — real process-chain identity paths.
  - `extensions/taut_pg/tests/*` — `from taut.client import TautClient` on the PG
    backend.
- Must stay real: the broker and identity capture (no mocking). Do not add mocks to
  "simplify" a moved method.
- New-submodule import check — as a **shell gate, not a test file**. Do **not** add
  a test under `tests/` for this (that would violate the zero-test-diff invariant);
  instead the §7 gate runs
  `python -c "import taut.client._identity, taut.client._messaging, taut.client._notifications, taut.client._threads, taut.client._base, taut.client._models"`.

## 7. Verification and Gates

Per-task (run after every task in §5):
- `uv run pytest -q` → all green.
- `uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml`
  → clean (strict; no new `type: ignore`).
- `uv run ruff check taut tests bin` and `uv run ruff format --check taut tests bin`
  → clean.
- `git diff --stat tests/` → unchanged from the preflight dirty-tree baseline.

Final gates before completion:
- Full `uv run pytest -q` and `uv run ./bin/pytest-pg --fast` (client rides the
  shared backend path, so exercise both SQLite and Postgres).
- Import stability check:
  `python -c "import taut; from taut.client import TautClient, Member, Thread, Message, Notification, InitResult, database_path_from_target; print(taut.TautClient is TautClient)"`
  → prints `True`.
- Public value-object identity check:
  `python -c "from taut.client import Message; print(Message)"`
  → prints `<class 'taut.client.Message'>`, not the implementation module path.
- New-submodule import gate (shell, not a test file):
  `python -c "import taut.client._base, taut.client._models, taut.client._identity, taut.client._messaging, taut.client._notifications, taut.client._threads"`
  → exits 0.
- No bare concern-module import gate:
  `rg -n "taut\.client\.(base|models|identity|messaging|notifications|threads)" README.md docs/implementation docs/specs taut tests extensions --glob '*.py' --glob '*.md'`
  → returns no public examples or production imports.
- MRO sanity check (guards against the base-before-subclass trap):
  `python -c "from taut.client import TautClient; print([c.__name__ for c in TautClient.__mro__])"`
  → lists the mixins before `_ClientBase` and does not raise.
- `uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml`
  clean.
- `git diff` on **code** (`taut/`) shows mechanical moves + re-exports only, with no
  signature or logic changes; **docs** diffs (Task 8: `docs/implementation/*`,
  `docs/specs/02-taut-core.md` backlink) are expected and separate.

Post-change success signal: CI test workflow green; no consumer (cli, watcher, pg
extension) required any edit. Rollback: revert the commits; the single
`taut/client.py` returns intact — no data or migration involved.

## 8. Independent Review Loop

- Reviewer: a different agent family than the author (per `CLAUDE.md` / [DOM-11]),
  ideally after Task 3 (the base/mixin seam is the load-bearing decision) and again
  before completion — per the "review after each meaningful slice" rule.
  If the active tool session does not allow sub-agent delegation without explicit
  user authorization, use the repository fallback: perform a strict fresh-eyes
  review, state that limitation, and do not claim independent-agent review occurred.
- Files to read: the new `taut/client/` package, `taut/watcher.py:527-640`,
  `taut/cli.py`, `tests/test_public_api.py`, `tests/test_watcher.py`, this plan,
  and, for current storage-layer context,
  `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md`.
- Review prompt: "Read the plan at
  `docs/plans/2026-06-30-client-module-split-plan.md`, the later state-refactor
  plan, and the code. Is the base-class/mixin decomposition sound under strict
  mypy? Does anything in the split risk changing behavior, an exit code, a JSON
  shape, or an import path? Could you implement this confidently and correctly?"
- Feedback handling: address each point by updating the plan, defending the choice,
  or marking it out of scope with reasoning. If the reviewer cannot confidently
  implement, treat it as a blocker until resolved.

## 9. Out of Scope

- **Collaborator-object redesign** (a separate `IdentityResolver` /
  `MessageService` the client *holds* rather than *is*). The architecture review
  rated this Speculative and warned against a premature seam; revisit only if
  identity code keeps churning. This plan deliberately does the mixin split
  instead.
- Any change to public method signatures, semantics, JSON shapes, or exit codes.
- Supporting pickle as a persistence or interchange format for public value objects.
  The dataclasses keep `__module__ = "taut.client"` for public-object aesthetics, not
  because Taut promises pickle compatibility.
- Splitting `taut/schema.py` or introducing the [TAUT-12.2] state interface was out
  of scope for this split. It was implemented afterward by
  `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md`; this plan should not be
  used as current storage-layer guidance.
- CLI (`taut/cli.py`) restructuring; watcher changes; new tests (the new-submodule
  check is a shell import gate in §7, not a test file).
- The CI/assets fix (separate plan:
  `docs/plans/2026-06-30-assets-reference-cleanup-plan.md`).

## 10. Fresh-Eyes Review

- The single biggest implementation hazard — strict-mypy complaints from mixins
  referencing methods defined in sibling mixins — is pre-empted by Task 3's concrete
  design: `_ClientBase(ABC)` declares `@abstractmethod` stubs for the four
  cross-referenced methods (`_resolve_member`, `_insert_message`, `_write_message`,
  `_write_notification`) — verified against this repo's mypy config, since bare `...`
  bodies fail `[empty-body]` — and `_ClientBase` is ordered **last** in the bases so
  the concrete mixin methods satisfy the abstracts in the MRO. The implementer never
  reaches for `# type: ignore`.
- Circular-import risks are named: `_models.py` must not import the facade, and
  `watch` keeps its lazy `TautWatcher` import.
- The invariant that actually protects correctness — **zero `tests/` diff** — is
  stated as both an invariant (§4) and the TDD substitute proof (§6), and is a
  per-task gate (§7), so drift is caught immediately rather than at the end.
- Every submodule's member list is enumerated by name, so the implementer does not
  have to infer where a helper goes or invent a new abstraction boundary.
- This split intentionally keeps `TautClient` as the single public facade. That is
  the right API shape for a CLI-isomorphic library surface, but it is not by itself
  deeper domain layering. Deeper layering should happen behind the facade, as with
  `taut.state`, without forcing API users to import multiple service objects.
- Bare concern-module names (`taut.client.messaging`, `taut.client.models`, etc.)
  are a weak signal because users and agents may treat them as stable submodule APIs.
  Prefixing them with `_` makes the intended layering visible in Python's normal
  naming language: only `taut.client` is public.
- The later watcher dependency on `client._state` was outside this plan's original
  split-time contract. It has been resolved by
  `docs/plans/2026-07-01-taut-watch-runtime-plan.md`, which gives watcher a narrow
  client-owned runtime adapter instead of direct access to client storage internals.

## 11. Implementation Notes

Implemented 2026-07-01.

Initial resulting package before Task 9:
- `taut/client/__init__.py` — facade, `TautClient` assembly, `init`, `watch`,
  public re-exports, and `database_path_from_target`
- `taut/client/base.py` — shared state, module-level helpers, `_ResolvedMember`,
  `_ClientBase`, and abstract cross-mixin method contract
- `taut/client/models.py` — public dataclasses
- `taut/client/identity.py` — identity/member/name/rejoin behavior
- `taut/client/messaging.py` — say/reply/read/log/message helpers
- `taut/client/notifications.py` — notification inbox/write/parse behavior
- `taut/client/threads.py` — join/leave/list/rename/thread metadata behavior

Target package after the private-module naming correction in Task 9:
- `taut/client/__init__.py` — the only supported client import surface
- `taut/client/_base.py`
- `taut/client/_models.py`
- `taut/client/_identity.py`
- `taut/client/_messaging.py`
- `taut/client/_notifications.py`
- `taut/client/_threads.py`

Task 9 implemented 2026-07-01. The current package uses the target private
submodule names above; no compatibility wrappers were added for the old bare
module names.

Verification evidence:
- `uv run pytest -q`
- `uv run pytest -m shared -q`
- `uv run ./bin/pytest-pg --fast`
- `uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml`
- `uv run ruff check taut tests bin`
- `uv run ruff format --check taut tests bin`
- import stability, submodule import, and MRO shell gates from §7
- `uv build`
- `uv build extensions/taut_pg`

The preflight test diff baseline was unchanged after implementation:
`tests/test_cli.py`, `tests/test_client.py`, `tests/test_envelope.py`,
`tests/test_github_workflows.py`, `tests/test_identity.py`,
`tests/test_project_config.py`, `tests/test_public_api.py`,
`tests/test_schema.py`, `tests/test_shared_contract.py`, and
`tests/test_watcher.py` remained the only modified test files.

Review update on 2026-07-01:
- The subsequent `TautState` refactor changed the storage dependency named in this
  plan. Current production client mixins depend on `taut.state`, not `taut.schema`.
- The external private surface changed after this split: `TautWatcher` reached
  `client._state` for membership reads and cursor advancement. That was not an
  intended public or semi-public layer. It was resolved by
  `docs/plans/2026-07-01-taut-watch-runtime-plan.md`, which introduced the
  internal `TautWatchRuntime` adapter and moved watcher runtime behavior off
  client private state.
- The zero-test-diff proof should record the exact preflight test-file baseline when
  used in a dirty worktree. The implemented baseline was the ten test files listed
  immediately above.

Task 9 verification evidence:
- `python -c "import taut; from taut.client import TautClient, Member, Thread, Message, Notification, InitResult, database_path_from_target; print(taut.TautClient is TautClient); print(Message)"` -> `True` and `<class 'taut.client.Message'>`
- `python -c "import taut.client._base, taut.client._models, taut.client._identity, taut.client._messaging, taut.client._notifications, taut.client._threads"`
- `python -c "from taut.client import TautClient; print([c.__name__ for c in TautClient.__mro__])"`
- `rg -n "taut\.client\.(base|models|identity|messaging|notifications|threads)" README.md docs/implementation docs/specs taut tests extensions --glob '*.py' --glob '*.md'` -> no matches
- `uv run pytest tests/test_public_api.py tests/test_client.py tests/test_cli.py tests/test_watcher.py -q` -> 57 passed
- `uv run pytest` -> 162 passed
- `uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests`
- `uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests`
- `uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml`
- `uv run ./bin/pytest-pg --fast` -> shared 18 passed, pg-only 8 passed
- `uv build`
- `uv build extensions/taut_pg`

Independent-agent review limitation: this session's tool rules did not allow
sub-agent delegation without explicit user authorization, so completion used the
repository fallback: a strict fresh-eyes self-review plus the full verification
gates above.
