# Plan: Introduce `TautWatchRuntime`

Date: 2026-07-01
Status: Implemented
Risk: Moderate. This is intended to preserve behavior, but it crosses the live
watcher, client facade, state, message decoding, notification decoding, and test
construction seams.
Companion runbook: `docs/agent-context/runbooks/hardening-plans.md` is required
input because this changes a boundary used by background/live-follow behavior.

## 1. Goal

Replace `TautWatcher`'s production dependency on `TautClient` internals with a
narrow internal `TautWatchRuntime` interface. `TautClient.watch()` remains the
supported user-facing construction path. `TautWatcher` should know how to watch
queues, apply cursor rules, and dispatch `Message | Notification`; it should not
know where memberships live, how client state is stored, or which private
decoder methods exist on `TautClient`.

## 2. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-7.2] - cursor advancement is monotonic.
- `docs/specs/02-taut-core.md` [TAUT-8.3] - `TautClient` is the embedding
  surface and the CLI shares that operational model.
- `docs/specs/02-taut-core.md` [TAUT-8.4] - watcher cursor, handler-success,
  poison-message, membership-refresh, and notification behavior.
- `docs/specs/02-taut-core.md` [TAUT-11] - watcher tests use real broker-backed
  queues and real sidecar state; the broker is not mocked.
- `docs/specs/02-taut-core.md` [TAUT-12.2] - all Taut state reads and writes flow
  through one state module.
- `docs/specs/03-identity-addressing-notifications.md` [IAN-7.2], [IAN-7.4] -
  notification payload shape and claim/read behavior.

Supporting context:

- `docs/implementation/04-taut-architecture.md` - current ownership map and
  watcher/client/state rationale.
- `docs/plans/2026-06-30-client-module-split-plan.md` - identifies watcher access
  to `client._state`, `client._message_from_body`, and
  `client._notification_from_body` as remaining layering debt after the client
  package split.
- `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md` - introduced
  `taut.state`; this plan must keep watcher state access behind that state seam.
- `docs/agent-context/runbooks/writing-plans.md`,
  `docs/agent-context/runbooks/hardening-plans.md`,
  `docs/agent-context/runbooks/testing-patterns.md`, and
  `docs/agent-context/runbooks/maintaining-traceability.md`.

## 3. Requested Outcomes

- Production `taut/watcher.py` no longer imports or references `TautClient` for
  its runtime behavior.
- Production `taut/watcher.py` no longer calls any `client._*` member.
- `TautWatcher` no longer sees `TautState`, `MembershipRow`, or sidecar row
  shapes. It sees a watcher-owned value object for watched threads.
- Message and notification decoding are moved to shared internal codec functions
  so the watcher runtime does not hold bound private client methods.
- `TautClient.watch()` remains the public construction path and returns a
  `TautWatcher` with unchanged behavior.
- Existing direct construction as `TautWatcher(client, member_id, handler, ...)`
  remains accepted for compatibility because `TautWatcher` is a public export,
  but it becomes a deprecated constructor-only shim. The preferred construction
  path is still `TautClient.watch()` for users and `TautWatchRuntime` for
  internals/tests that need low-level knobs.
- Existing watcher behavior remains unchanged for SQLite and Postgres:
  peek-after-cursor, cursor-aware pending checks, cursor advancement only after
  successful user handling, three-strike poison-message advancement, live
  membership add/drop, and consumable notification inbox reads.

## 4. Context and Key Files

### Current production coupling

`taut/watcher.py` currently imports `TautClient` and `MembershipRow`. Inside
`TautWatcher`, it reaches into the client for four operations:

- `self.client._state.list_memberships(self.member_id)`
- `self.client._notification_from_body(body, timestamp)`
- `self.client._message_from_body(thread, body, timestamp)`
- `self.client._state.advance_cursor(...)`

That is the remaining improper dependency direction. The watcher needs current
watched threads, message decoding, notification decoding, and cursor
advancement. It does not need the full client object.

### Current owners

- `taut/client/__init__.py` owns the public `TautClient` facade, `TautClient.init`,
  and `TautClient.watch`.
- `taut/client/_base.py` owns resolved target/config/state construction.
- `taut/client/_messaging.py` owns chat message write/read behavior and currently
  contains `_message_from_body` / `_message_from_decoded`.
- `taut/client/_notifications.py` owns notification inbox/write behavior and
  currently contains `_notification_from_body`.
- `taut/state/` owns membership rows and cursor advancement.
- `taut/watcher.py` owns multi-queue watching, membership refresh timing, chat
  peek cursor semantics, notification queue consumption, handler error behavior,
  and poison-message liveness.

### Files to modify

- Add `taut/_watch_runtime.py`.
- Add `taut/client/_codec.py`.
- Add `taut/client/_watching.py`.
- Update `taut/client/__init__.py`.
- Update `taut/client/_messaging.py`.
- Update `taut/client/_notifications.py`.
- Update `taut/watcher.py`.
- Update `tests/test_watcher.py`.
- Update `tests/test_shared_contract.py`.
- Update `docs/implementation/04-taut-architecture.md`.
- Update `docs/specs/02-taut-core.md` related plans.

### Files to read before editing

- `taut/watcher.py:527-710`. Confirm where memberships are loaded, where cursors
  advance, and why the advance must happen inside the per-queue handler wrapper.
- `taut/client/__init__.py`. Confirm `TautClient.watch()` keeps the lazy
  `TautWatcher` import and remains the user-facing construction path.
- `taut/client/_messaging.py:118-145`, `taut/client/_messaging.py:174-184`, and
  `taut/client/_messaging.py:379-394`. Confirm current read/log/decode paths.
- `taut/client/_notifications.py` in full. Confirm notification reads claim from
  the inbox while watched chat messages only peek.
- `taut/state/__init__.py` and `taut/state/_types.py`. Confirm which row shapes
  must stay state-owned and must not leak into watcher.
- `tests/test_watcher.py` and `tests/test_shared_contract.py`. Confirm where
  tests construct `TautWatcher` directly and why they use low refresh intervals.

Comprehension checks before editing:

1. Why does [TAUT-8.4] require cursor advancement inside the taut per-queue
   handler wrapper instead of after `MultiQueueWatcher` dispatch?
2. Why must notification queues stay in `READ` mode while chat queues stay in
   `PEEK` mode with a per-thread cursor?
3. Which current tests construct `TautWatcher` directly only to control
   refresh timing, and which tests should continue to prove public
   `client.watch(...)` behavior?

## 5. Target Design

### Internal runtime interface

Create `taut/_watch_runtime.py` with a private, typed watcher seam:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from simplebroker import BrokerTarget

if TYPE_CHECKING:
    from taut.client._models import Message, Notification


@dataclass(frozen=True, slots=True)
class WatchedThread:
    name: str
    last_seen_ts: int


class TautWatchRuntime(Protocol):
    @property
    def target(self) -> BrokerTarget | str: ...

    @property
    def config(self) -> Mapping[str, Any]: ...

    def list_watched_threads(self, member_id: str) -> list[WatchedThread]: ...

    def decode_message(self, thread: str, body: str, ts: int) -> Message: ...

    def decode_notification(self, body: str, ts: int) -> Notification: ...

    def advance_cursor(self, *, thread: str, member_id: str, seen_ts: int) -> None: ...
```

Rules:

- `taut/_watch_runtime.py` must not import `taut.client` at runtime. Use
  `TYPE_CHECKING` and deferred annotations for `Message` and `Notification`.
- Do not put `MembershipRow`, `TautState`, or SQL concepts in this interface.
- Do not add backend-specific behavior here. The runtime interface is about
  watcher needs, not storage adapters.

### Shared internal codec

Create `taut/client/_codec.py` with pure functions:

- `message_from_body(thread: str, body: str, ts: int) -> Message`
- `message_from_decoded(thread: str, decoded: DecodedEnvelope, ts: int) -> Message`
- `notification_from_body(body: str, ts: int) -> Notification`

Move the current decode logic from `MessagingMixin` and `NotificationsMixin`
into those functions. Then update client mixins and the watch runtime adapter to
call the functions directly.

Sequencing rule: Task 2 must keep temporary pass-through client methods named
`_message_from_body`, `_message_from_decoded`, and `_notification_from_body` so
the existing watcher remains green until Task 4 rewires it. Those shims must
delegate directly to `taut/client/_codec.py` and must be deleted in Task 4 after
`TautWatcher` no longer calls them. This is a temporary sequencing shim, not a
new interface.

### Client-owned adapter

Create `taut/client/_watching.py` with a client-owned adapter:

```python
@dataclass(frozen=True, slots=True)
class _ClientWatchRuntime:
    target: BrokerTarget | str
    config: Mapping[str, Any]
    state: TautState

    def list_watched_threads(self, member_id: str) -> list[WatchedThread]:
        return [
            WatchedThread(name=row["thread"], last_seen_ts=row["last_seen_ts"])
            for row in self.state.list_memberships(member_id)
        ]

    def decode_message(...): ...
    def decode_notification(...): ...
    def advance_cursor(...): ...
```

Add `_watch_runtime_for_client(client: _ClientBase) -> TautWatchRuntime` in the
same module. `TautClient.watch()` should use this helper to build the runtime.
This keeps access to `_state` inside the `taut.client` package instead of making
`taut/watcher.py` reach into client internals.

Do not expose `_ClientWatchRuntime` from `taut.client.__all__`.

### Watcher construction

Change `TautWatcher.__init__` to accept:

```python
runtime: TautWatchRuntime
member_id: str
handler: Callable[[Message | Notification], None]
...
```

`TautWatcher` stores this as `self._runtime`, uses `runtime.target` and
`runtime.config` when constructing `MultiQueueWatcher`, and uses runtime methods
for membership listing, decoding, and cursor persistence.

Cursor ownership stays split deliberately:

- `TautWatcher` owns the in-memory `_cursors` dictionary. Fetch and pending
  checks continue to read that local dictionary.
- `WatchedThread.last_seen_ts` seeds local cursor state at construction and
  refresh time only.
- `runtime.advance_cursor(...)` is persistence only. It must not become the
  owner of local cursor state.
- `_advance()` keeps the current ordering unless a failing test forces a
  re-plan: update local `_cursors` first, then persist through
  `runtime.advance_cursor(...)`.

`TautClient.watch()` remains:

```python
return TautWatcher(_watch_runtime_for_client(self), member["member_id"], handler, threads=threads)
```

Because `TautWatcher` is exported from `taut`, preserve direct construction as a
compatibility shim:

```python
def __init__(
    self,
    runtime: TautWatchRuntime | TautClient,
    member_id: str,
    handler: Callable[[Message | Notification], None],
    ...,
) -> None: ...
```

Runtime behavior:

- Use a concrete client check first. In a private constructor helper, lazily
  import `_ClientBase` and `_watch_runtime_for_client`; if the first argument is
  an `_ClientBase`, emit `DeprecationWarning` with `stacklevel=2` and convert it
  to a runtime.
- Treat every non-client first argument as `TautWatchRuntime`. Do not use
  `@runtime_checkable` / `isinstance(arg, TautWatchRuntime)` as the primary
  discriminator. Runtime-checkable protocols check attribute names, not
  signatures, so a future client method named `advance_cursor` or
  `list_watched_threads` could otherwise silently bypass the compatibility
  conversion.
- Do not let the compatibility path leak into handler execution, membership
  refresh, decoding, or cursor persistence. After construction, `TautWatcher`
  operates only on `self._runtime`.
- Prefer the union first-argument annotation above over overlapping overloads.
  Use `TYPE_CHECKING` imports for `TautClient` if needed, and keep runtime
  imports lazy to avoid cycles. Do not use broad `Any` or type ignores for the
  compatibility path.

## 6. Invariants and Constraints

- `from taut import TautWatcher` and `from taut.watcher import TautWatcher` keep
  working. The class remains exported.
- `TautClient.watch(handler, threads=...)` keeps its current public signature
  and behavior.
- `TautWatcher(client, member_id, handler, ...)` keeps working for now as a
  deprecated compatibility path. It may warn, but it must not access
  `client._state` or private decoder methods from watcher runtime code.
- The CLI surface does not change.
- No new dependency is added.
- `TautWatcher` must not import `TautClient`, `_ClientBase`, `TautState`,
  `MembershipRow`, or `taut.schema` for runtime watch behavior. `TautClient` /
  `_ClientBase` references are allowed only in `TYPE_CHECKING` annotations and the
  single constructor-only compatibility conversion.
- `TautWatcher` must not access any `client._*` member.
- `TautWatcher` must not gain SQL or sidecar knowledge.
- Chat queues remain peek-based and cursor-aware. Notification queues remain
  claim/read inboxes.
- Cursor advancement remains monotonic and occurs only after the user handler
  returns, except the existing three-strike poison-message path.
- A failing handler leaves the cursor in place until the poison-message rule
  fires.
- Explicit watch filters still fail at construction when the member lacks an
  initial watched thread, but missing memberships during refresh are convergence
  events and drop queues.
- The interval refresh remains independent of queue message presence.
- Tests must keep real broker-backed queues and real sidecar state. Do not mock
  `Queue`, `TautState`, `TautWatchRuntime`, or broker activity for watcher
  contract proof.
- No compatibility wrapper may infer backend dialect from `Queue.db_target`.
  This plan should not touch dialect detection.
- No drive-by cleanup of test private `_meta_queue` assertions. They are
  adjacent test debt, not the production layering concern this plan resolves.

## 7. Rollback and Rollout

No data migration, schema change, storage-format change, or one-way door is
introduced. Rollback is a code revert of the runtime adapter, codec extraction,
watcher constructor change, and related tests/docs.

Because `TautClient.watch()` is the intended construction path and
`TautWatcher(client, ...)` remains accepted through a deprecated shim, rollout is
ordinary release sequencing: land the code and docs together, run SQLite and
Postgres gates, then rely on normal CI. A later release may remove the
compatibility constructor only after a separate plan/spec update.

Post-change success signal: CI green, no production grep hits for watcher
private client access, and no reported change in `taut watch` / `client.watch`
behavior.

## 8. Tasks

1. Record the current failing layering gate and baseline watcher behavior.
   - Files to touch: none.
   - Read first: `taut/watcher.py:527-710`, `tests/test_watcher.py`.
   - Run:
     ```bash
     rg -n "client\\._state|client\\._message_from_body|client\\._notification_from_body|from taut.client import .*TautClient|MembershipRow" taut/watcher.py
     uv run pytest tests/test_watcher.py tests/test_shared_contract.py -q
     ```
   - Expected pre-change result: the `rg` command finds the known private-surface
     violations; targeted tests pass or any baseline failure is recorded before
     editing.
   - Stop and re-evaluate if targeted watcher behavior is already failing.
   - Done signal: the red layering gate and behavior baseline are recorded in the
     implementation notes or final change summary.

2. Extract message and notification decoding into `taut/client/_codec.py`.
   - Files to touch: `taut/client/_codec.py`, `taut/client/_messaging.py`,
     `taut/client/_notifications.py`.
   - Move logic, do not rewrite payload semantics.
   - Reuse `taut.envelope.decode_envelope`, `DecodedEnvelope`, and existing
     `Notification` validation logic.
   - Update `MessagingMixin.read_unread`, `MessagingMixin.log`, and
     `MessagingMixin._insert_message` to call codec functions.
   - Update `NotificationsMixin.inbox` to call `notification_from_body`.
   - Keep `_message_from_body`, `_message_from_decoded`, and
     `_notification_from_body` as temporary thin shims that delegate to the new
     codec functions. Do not delete them in this task; `TautWatcher` still calls
     them until Task 4.
   - Tests:
     ```bash
     uv run pytest tests/test_envelope.py tests/test_client.py tests/test_watcher.py -q
     uv run --extra dev mypy taut tests/test_envelope.py tests/test_client.py tests/test_watcher.py --config-file pyproject.toml
     ```
   - Stop and re-evaluate if the codec functions need `self`, `_state`, target
     resolution, or queue access. Decoding should stay pure.
   - Done signal:
     ```bash
     rg -n "def _message_from_body|def _message_from_decoded|def _notification_from_body" taut/client
     rg -n "self\\.client\\._message_from_body|self\\.client\\._notification_from_body" taut/watcher.py
     ```
     The first command must show only the temporary thin shims. The second
     command is expected to still show the current watcher calls until Task 4.
     If the tests or mypy gate fail here because watcher calls deleted client
     methods, the implementer deleted the shims too early.

3. Add the watcher runtime interface and client adapter.
   - Files to touch: `taut/_watch_runtime.py`, `taut/client/_watching.py`.
   - Implement `WatchedThread`, `TautWatchRuntime`, `_ClientWatchRuntime`, and
     `_watch_runtime_for_client`.
   - `_ClientWatchRuntime` is the only new code that translates
     `TautState.list_memberships()` rows into `WatchedThread`.
   - `_ClientWatchRuntime.advance_cursor()` delegates to
     `TautState.advance_cursor()`.
   - `_ClientWatchRuntime` calls codec functions for decoding.
   - Tests:
     ```bash
     uv run --extra dev mypy taut tests --config-file pyproject.toml
     ```
   - Stop and re-evaluate if the adapter starts exposing state rows, SQL, or
     client methods directly to watcher.
   - Import-order smoke tests:
     ```bash
     python -c "import taut; from taut import TautClient, TautWatcher; print(taut.TautWatcher is TautWatcher)"
     python -c "import taut.watcher; import taut.client._watching; import taut.client._codec"
     python -c "from taut.client import TautClient; from taut.watcher import TautWatcher; print(TautClient, TautWatcher)"
     ```
   - Done signal: `taut/_watch_runtime.py` has no runtime import from
     `taut.client`, `_ClientWatchRuntime` is not re-exported from `taut.client`,
     and the import-order smoke tests pass.

4. Rewire `TautClient.watch()` and `TautWatcher`.
   - Files to touch: `taut/client/__init__.py`, `taut/watcher.py`.
   - Keep the lazy import of `TautWatcher` inside `TautClient.watch()`.
   - Build the runtime inside `TautClient.watch()` using
     `_watch_runtime_for_client(self)`.
   - Change `TautWatcher` to store `_runtime` instead of `client`.
   - Replace membership reads with `runtime.list_watched_threads(member_id)`.
   - Replace decode calls with `runtime.decode_message(...)` and
     `runtime.decode_notification(...)`.
   - After watcher no longer calls client decoder methods, delete the temporary
     `_message_from_body`, `_message_from_decoded`, and `_notification_from_body`
     shims from the client mixins.
   - Keep local cursor ownership in `TautWatcher._cursors`; replace only the
     persistent cursor write with `runtime.advance_cursor(...)`.
   - Keep `_advance()` ordering: local `_cursors` update first, runtime
     persistence second.
   - Add the deprecated `TautWatcher(client, ...)` compatibility path with a
     typed union first-argument signature and a single lazy conversion helper.
   - Keep existing thread filter semantics and `EmptyResultError` /
     `MembershipError` behavior.
   - Tests:
     ```bash
     uv run pytest tests/test_watcher.py tests/test_shared_contract.py -q
     ```
   - Stop and re-evaluate if making existing tests pass requires direct
     `client._*` access, `TautState`, `MembershipRow`, or SQL in
     `taut/watcher.py`.
   - Done signal:
     ```bash
     rg -n "client\\._|MembershipRow|taut\\.schema|TautState" taut/watcher.py
     rg -n "TautClient|_ClientBase|_watch_runtime_for_client" taut/watcher.py
     rg -n "def _message_from_body|def _message_from_decoded|def _notification_from_body|self\\._message_from_body|self\\._notification_from_body|self\\.client\\._message_from_body|self\\.client\\._notification_from_body" taut/client taut/watcher.py
     ```
     The first command returns no matches. The second command is an inspection
     gate: matches are allowed only for `TYPE_CHECKING` annotations and the
     constructor-only deprecated compatibility conversion.
     The third command returns no matches.

5. Update tests to use the intended construction seams.
   - Files to touch: `tests/test_watcher.py`, `tests/test_shared_contract.py`,
     `tests/test_public_api.py`.
   - Public-path tests that do not require constructor-only knobs must use
     `client.watch(...)`.
   - Keep or add these public-path proofs:
     - one live chat watch delivery test through `client.watch(...)`
     - one notification watch/claim test through `client.watch(...)`
     - one explicit `threads=[...]` construction/filter test through
       `client.watch(...)`
   - Add a public API assertion that `TautWatcher` remains exported from
     `taut.__all__` and importable from `taut`.
   - Add one compatibility test for `TautWatcher(client, member_id, handler, ...)`
     that asserts the `DeprecationWarning` and proves it still constructs a
     working watcher.
   - Tests that need `membership_refresh_interval`, `stop_event`, or a
     `TautWatcher` subclass should construct `TautWatcher` with
     `_watch_runtime_for_client(client)`.
   - Do not widen `TautClient.watch()` just for tests.
   - Do not mock the runtime. These tests are proving the real watcher/client/
     state integration.
   - Tests:
     ```bash
     uv run pytest tests/test_watcher.py tests/test_shared_contract.py tests/test_public_api.py -q
     ```
   - Stop and re-evaluate if tests start asserting on runtime internals instead
     of public behavior or durable cursor state.
   - Done signal: no test constructs `TautWatcher` with a `TautClient` object
     except the single explicit compatibility test. Verify by reviewing every
     `TautWatcher(` match in `tests/` and `taut/`, not only by checking common
     variable names.

6. Update architecture and traceability docs.
   - Files to touch: `docs/implementation/04-taut-architecture.md`,
     `docs/specs/02-taut-core.md`, this plan.
   - Update the architecture rationale to say `TautClient.watch()` builds a
     client-owned `TautWatchRuntime`, and `TautWatcher` depends on that runtime
     rather than client internals after construction.
   - Update the owner table or spec-code trace to include
     `taut/_watch_runtime.py`, `taut/client/_watching.py`, and
     `taut/client/_codec.py`.
   - Add this plan to [TAUT-8.4] related plans.
   - Update [TAUT-8.4] or nearby implementation docs to say direct
     `TautWatcher(client, ...)` construction is a deprecated compatibility path;
     the preferred public construction path is `TautClient.watch()`.
   - If implementation materially changes a public construction contract, update
     [TAUT-8.3] / [TAUT-8.4] explicitly instead of hiding it in implementation
     docs.
   - Verification:
     ```bash
     rg -n "client\\._state|_message_from_body|_notification_from_body|watcher.*client internals" docs taut
     ```
     Review every match and update stale documentation or record why it remains
     historical.
   - Done signal: spec, implementation doc, and plan agree on ownership.

7. Run the final gates.
   - Commands:
     ```bash
     uv run pytest tests/test_public_api.py tests/test_client.py tests/test_cli.py tests/test_watcher.py tests/test_shared_contract.py -q
     uv run pytest
     uv run ./bin/pytest-pg --fast
     uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
     uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
     uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
     uv build
     uv build extensions/taut_pg
     python -c "import taut; from taut import TautClient, TautWatcher; print(taut.TautWatcher is TautWatcher)"
     python -c "import taut.watcher; import taut.client._watching; import taut.client._codec"
     python -c "from taut.client import TautClient; from taut.watcher import TautWatcher; print(TautClient, TautWatcher)"
     ```
   - Final grep gates:
     ```bash
     rg -n "client\\._|MembershipRow|taut\\.schema|TautState" taut/watcher.py
     rg -n "TautClient|_ClientBase|_watch_runtime_for_client" taut/watcher.py
     rg -n "def _message_from_body|def _message_from_decoded|def _notification_from_body|self\\._message_from_body|self\\._notification_from_body|self\\.client\\._message_from_body|self\\.client\\._notification_from_body" taut/client taut/watcher.py
     rg -n "TautWatcher\\(" tests taut
     ```
     The first command must return no matches. The `TautClient` command is an
     inspection gate: matches are allowed only for `TYPE_CHECKING` annotations and
     the constructor-only deprecated compatibility conversion. The final command
     is also an inspection gate: every remaining direct construction must use
     `TautWatchRuntime`, call `client.watch(...)`, or be the single explicit
     compatibility test.
   - Done signal: commands pass or every skipped command and residual risk is
     reported explicitly.

## 9. Testing Plan

Red-green posture:

- The first red proof is the source-level layering gate in Task 1. It fails
  today because `taut/watcher.py` uses `client._state`,
  `client._message_from_body`, and `client._notification_from_body`.
- Runtime behavior is a refactor, not new user behavior. Existing watcher tests
  are the behavioral regression suite and must stay real.

What must stay real:

- Real `Queue` objects against real `.taut.db` files.
- Real `TautState` through the SQL sidecar adapter.
- Real `TautClient` identity, join, say, inbox, read, and watch paths.
- Real `TautWatcher` start/stop loops in live tests.

What may be mocked:

- Nothing on the watcher/client/state core path. If a test needs bounded timing,
  use the existing low `membership_refresh_interval` pattern and `_wait_until`.

Regression names protected:

- "Watcher no longer depends on client private storage or decoder methods."
- "Cursor advance still happens only after handler success."
- "Watcher local cursor state remains watcher-owned; runtime cursor advancement
  is persistence only."
- "Failed handler re-sees the message until the poison-message threshold."
- "Mid-watch join adds a queue; mid-watch leave drops a queue."
- "Notification watch claims inbox messages without touching chat history."
- "Idle peek queues do not busy-spin after cursor advance."
- "Public `client.watch(...)` remains tested for chat delivery, notification
  delivery, and explicit thread filters."
- "Deprecated direct `TautWatcher(client, ...)` construction still works for one
  compatibility test."

## 10. Verification and Gates

Per-task verification is listed in Section 8. Final completion requires:

- All commands in Section 8, task 7 pass.
- No production watcher grep hits for `client._*`, `MembershipRow`,
  `TautState`, `taut.schema`, or SQL. `TautClient` may appear only in
  `TYPE_CHECKING` annotations or the deprecated constructor compatibility shim.
- No stale docs claim watcher reaches client internals as the current design.
- The plan's independent review loop is complete, or the lack of an available
  independent reviewer is recorded with the limitation.
- Any implementation divergence from this plan is recorded in this plan before
  the implementation is considered done.

## 11. Independent Review Loop

Before implementation, run an independent plan review.

Preferred reviewer: a different agent family if available. If not available, use
a same-family agent in a strict read-only review role. If no separate reviewer is
available, perform a strict fresh-eyes review and record the limitation.

Reviewer should read:

- This plan.
- `docs/specs/02-taut-core.md` [TAUT-7.2], [TAUT-8.3], [TAUT-8.4], [TAUT-11],
  [TAUT-12.2].
- `docs/specs/03-identity-addressing-notifications.md` [IAN-7].
- `docs/implementation/04-taut-architecture.md`.
- `taut/watcher.py`.
- `taut/client/__init__.py`.
- `taut/client/_messaging.py`.
- `taut/client/_notifications.py`.
- `tests/test_watcher.py`.
- `tests/test_shared_contract.py`.

Review prompt:

> Read `docs/plans/2026-07-01-taut-watch-runtime-plan.md` and the associated
> source files. Look for errors, bad ideas, and latent ambiguities. Do not
> implement anything. Answer carefully: Could you implement this confidently and
> correctly if asked? Pay special attention to public `TautWatcher`
> compatibility, import cycles, mypy behavior, local cursor ownership, public
> `client.watch` test coverage, and whether the runtime seam is deep enough to
> justify itself.

The authoring agent must answer every review point by updating the plan,
rejecting it with reasoning, or marking it out of scope with reasoning. If the
reviewer cannot implement confidently, the plan is blocked until fixed or the
limitation is explicit.

## 12. Out of Scope

- Changing CLI commands, output, JSON field names, or exit codes.
- Adding public methods to `TautClient`.
- Widening `TautClient.watch()` for test-only constructor knobs.
- Removing direct construction compatibility for
  `TautWatcher(client, member_id, handler, ...)`. This plan preserves it as a
  deprecated constructor-only shim because `TautWatcher` is exported.
- Redis/Valkey state mapping.
- Cursor batching or delayed flushes.
- Reworking `MultiQueueWatcher`.
- Removing `taut/schema.py` compatibility wrappers.
- Cleaning up all test private `_meta_queue`, `_capture`, or `_create_member`
  usage.
- Adding dependencies.

## 13. Fresh-Eyes Review

Self-check before implementation:

- The plan names exact files to touch and read.
- The production seam is clear: watcher depends on `TautWatchRuntime`, not
  client, state rows, or SQL.
- The adapter ownership is clear: `taut.client` may adapt `_state` to a runtime;
  `taut/watcher.py` may not.
- The codec extraction prevents a shallow "bound private method" wrapper.
- The direct `TautWatcher(client, ...)` compatibility question is explicit:
  preserve it with a deprecated constructor-only shim, but keep handler/runtime
  behavior on `TautWatchRuntime`.
- The tests are real integration tests, not mocks of the seam being proven.
- Rollback is a code revert; there is no storage migration or one-way door.
- The grep gates are stricter than the prose and should catch accidental drift.

## 14. Review Appendix

Independent review completed 2026-07-01.

Findings accepted and addressed:

- Public `TautWatcher` constructor compatibility was under-specified. Resolution:
  preserve `TautWatcher(client, ...)` as a deprecated constructor-only shim with
  a typed union constructor argument, while `TautClient.watch()` and internal
  tests use `TautWatchRuntime` directly where possible.
- Import-cycle proof was implicit. Resolution: add root/client/watcher/internal
  import smoke tests to Task 3 and final gates, and require a public API test for
  `TautWatcher` export.
- `TautClient.watch()` could have become under-tested. Resolution: require live
  chat, notification, and explicit-filter public-path proofs.
- Cursor ownership across the runtime seam was under-specified. Resolution:
  explicitly keep `_cursors` in `TautWatcher`; runtime cursor advancement is
  persistence only.
- Section 10 referenced "Task 8" ambiguously. Resolution: changed to
  "Section 8, task 7".

Follow-up review completed 2026-07-01 after the fixes above. Result: no
blocking findings. Residual implementation risks are constructor typing and
client/runtime detection in the compatibility constructor, especially avoiding
broad `Any` and top-level import cycles. The plan now names those risks and has
explicit gates for them.

Outside review follow-up received 2026-07-01 and accepted:

- Task 2's original done signal deleted client decoder helpers before Task 4
  rewired watcher, so Task 2 could not pass its own watcher tests and mypy gate.
  Resolution: Task 2 keeps temporary thin codec shims; Task 4 deletes them after
  watcher no longer calls them.
- Runtime/client dispatch was structurally fragile because
  `@runtime_checkable` protocol checks depend on attribute names. Resolution:
  dispatch now checks `_ClientBase` first and treats non-client inputs as
  `TautWatchRuntime`.
- Overlapping overloads were an avoidable mypy risk. Resolution: use a union
  first-argument annotation for the constructor instead of overloads.

## 15. Implementation Notes

Implemented 2026-07-01.

Changed production files:

- `taut/_watch_runtime.py` - new internal `TautWatchRuntime` protocol and
  `WatchedThread` value object.
- `taut/client/_codec.py` - shared message and notification decoding helpers.
- `taut/client/_watching.py` - client-owned adapter from `_ClientBase` /
  `TautState` to `TautWatchRuntime`.
- `taut/client/__init__.py` - `TautClient.watch()` now builds a watch runtime
  before constructing `TautWatcher`.
- `taut/watcher.py` - `TautWatcher` now stores `_runtime`; direct
  `TautWatcher(client, ...)` construction is converted immediately through a
  deprecated compatibility path.
- `taut/client/_messaging.py` and `taut/client/_notifications.py` - decoding now
  uses `_codec`; temporary client decoder shims were removed after watcher was
  rewired.

Changed tests and docs:

- `tests/test_watcher.py` - runtime-based internal watcher construction,
  public-path chat/notification/filter coverage, and one deprecated constructor
  compatibility test.
- `tests/test_shared_contract.py` - project watcher shared test now uses
  `TautClient.watch()`.
- `tests/test_public_api.py` - asserts `TautWatcher` remains a public export.
- `docs/specs/02-taut-core.md`,
  `docs/implementation/04-taut-architecture.md`, and
  `docs/plans/2026-06-30-client-module-split-plan.md` - traceability and stale
  private-surface wording updated.

Verification evidence:

- Baseline before edits:
  `rg -n "client\\._state|client\\._message_from_body|client\\._notification_from_body|from taut.client import .*TautClient|MembershipRow" taut/watcher.py`
  found the expected private-surface references.
- Baseline before edits:
  `uv run pytest tests/test_watcher.py tests/test_shared_contract.py -q` passed.
- Task 2:
  `uv run pytest tests/test_envelope.py tests/test_client.py tests/test_watcher.py -q`
  passed.
- Task 2:
  `uv run --extra dev mypy taut tests/test_envelope.py tests/test_client.py tests/test_watcher.py --config-file pyproject.toml`
  passed.
- Task 3 import and typing gates passed:
  `uv run --extra dev mypy taut tests --config-file pyproject.toml`,
  `python -c "import taut; from taut import TautClient, TautWatcher; print(taut.TautWatcher is TautWatcher)"`,
  `python -c "import taut.watcher; import taut.client._watching; import taut.client._codec"`,
  and
  `python -c "from taut.client import TautClient; from taut.watcher import TautWatcher; print(TautClient, TautWatcher)"`.
- Task 4/5:
  `uv run pytest tests/test_watcher.py tests/test_shared_contract.py tests/test_public_api.py -q`
  passed.
- Task 4/5:
  `uv run --extra dev mypy taut tests/test_watcher.py tests/test_shared_contract.py tests/test_public_api.py --config-file pyproject.toml`
  passed.
- Final targeted suite:
  `uv run pytest tests/test_public_api.py tests/test_client.py tests/test_cli.py tests/test_watcher.py tests/test_shared_contract.py -q`
  passed.
- Full suite:
  `uv run pytest` passed, 163 tests.
- Postgres gate:
  `uv run ./bin/pytest-pg --fast` passed, shared 18 tests and pg-only 8 tests.
- Static gates passed:
  `uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests`,
  `uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests`,
  and
  `uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml`.
- Build gates passed:
  `uv build` and `uv build extensions/taut_pg`.
- Final grep gates were reviewed. `taut/watcher.py` has no production
  `client._*`, `MembershipRow`, `taut.schema`, or `TautState` references.
  `TautClient`, `_ClientBase`, and `_watch_runtime_for_client` appear only in
  `TYPE_CHECKING` annotations or the deprecated constructor compatibility
  conversion. Client decoder methods are gone. Remaining `TautWatcher(` matches
  are runtime-based tests, `TautClient.watch()`, the class declaration, and the
  single compatibility test.
