"""Exact source-owned Summon observations for tests, with no polling driver."""

from __future__ import annotations

import os
from threading import Event, Lock
from types import TracebackType
from typing import Any, Self

import pytest
from _completion import Completion, CompletionKey, CompletionScope


def request_phase(
    scope: CompletionScope,
    patch: pytest.MonkeyPatch,
    request: Any,
    event_name: str,
) -> Completion[Any]:
    """Register before the request's real Event transition."""

    record = scope.expect(CompletionKey(request, event_name, request))
    event = getattr(request, event_name)
    if event.is_set():
        raise ValueError("register request phase before its transition")
    original = event.set
    publication_lock = Lock()
    published = False

    def completed() -> None:
        nonlocal published
        original()
        with publication_lock:
            if published:
                return
            published = True
            error = getattr(request, "error", None)
            if error is not None:
                record.fail(record.key, error)
            else:
                record.succeed(record.key, getattr(request, "decision", None))

    patch.setattr(event, "set", completed)
    return record


class SummonObservations:
    """One app's single attach presentation, bound through its real callbacks."""

    def __init__(self, app: Any, patch: pytest.MonkeyPatch) -> None:
        from _screen_completion import ScreenCompletions

        from taut_tui import app as app_module

        self.scope = CompletionScope()
        self.app = app
        self.screens = ScreenCompletions(app, self.scope, patch)
        self.presented: list[Any] = []
        self.request: Any = None
        self.decision: Completion[Any] | None = None
        self._active_request: Any = None
        self.ready_started_at: float | None = None
        self.ready: Completion[Any] | None = None
        self.returned: Completion[Any] | None = None
        self.ready_handoff: Completion[Any] | None = None
        self._run_armed = False
        self._run_starting = False
        self._run_token: str | None = None
        self._run_future: Any = None
        self._run_lock = Lock()
        self._early_ready: dict[str, float] = {}
        self.first = self.scope.expect(CompletionKey(app, "attach.offer", self))
        self.second = self.scope.expect(
            CompletionKey(app, "attach.acknowledgement", self)
        )
        original_present = app_module._present_attach_confirmation
        original_push = app.push_screen

        def present(owner: Any, request: Any, **kwargs: Any) -> None:
            if owner is not app:
                original_present(owner, request, **kwargs)
                return
            if self.request is not None and self.request is not request:
                raise AssertionError("one attach request per observation scope")
            self.request = request
            self.decision = request_phase(self.scope, patch, request, "resolved")
            self._active_request = request
            try:
                original_present(owner, request, **kwargs)
            finally:
                self._active_request = None

        def push(screen: Any, callback: Any = None, *args: Any, **kwargs: Any) -> Any:
            request = self._active_request
            if request is None:
                return original_push(screen, callback, *args, **kwargs)
            if len(self.presented) >= 2:
                raise AssertionError(
                    "attach presentation exceeded offer/acknowledgement"
                )

            def applied(value: Any) -> Any:
                self._active_request = request
                try:
                    return callback(value) if callback is not None else None
                finally:
                    self._active_request = None

            result = original_push(screen, applied, *args, **kwargs)
            record = self.first if not self.presented else self.second
            self.presented.append(screen)
            record.succeed(record.key, screen)
            return result

        patch.setattr(app_module, "_present_attach_confirmation", present)
        patch.setattr(app, "push_screen", push)
        self._install_owned_callbacks(app, patch)

    def _install_owned_callbacks(self, app: Any, patch: pytest.MonkeyPatch) -> None:
        original_accept_ready = app._accept_summon_ready_from_worker
        original_ready = app._apply_summon_ready
        original_return = app._apply_summon_return

        def accept_ready(run: Any) -> Any:
            self._record_ready_handoff(run.token)
            return original_accept_ready(run)

        def ready(run: Any) -> Any:
            was_owned = run.token in app._owned_summon_tokens
            value = original_ready(run)
            if self.ready is not None and run.token == self._run_token:
                if was_owned:
                    self.ready.succeed(self.ready.key, run)
                else:
                    self.ready.supersede(self.ready.key)
            return value

        def returned(token: str, future: Any) -> Any:
            value = original_return(token, future)
            if (
                self.returned is not None
                and token == self._run_token
                and future is self._run_future
            ):
                if future.cancelled():
                    self.returned.cancel(self.returned.key)
                elif future.exception() is not None:
                    self.returned.fail(self.returned.key, future.exception())
                else:
                    self.returned.succeed(self.returned.key, (token, future))
            return value

        patch.setattr(app, "_accept_summon_ready_from_worker", accept_ready)
        patch.setattr(app, "_apply_summon_ready", ready)
        patch.setattr(app, "_apply_summon_return", returned)
        self._install_owned_start(app, patch)

    def _install_owned_start(self, app: Any, patch: pytest.MonkeyPatch) -> None:
        from taut_tui.summon import TuiSummonOperations

        original_start = TuiSummonOperations.start

        def start(owner: Any, request: Any, interaction: Any) -> Any:
            if not self._run_armed or owner is not app._summon:
                return original_start(owner, request, interaction)
            with self._run_lock:
                if self._run_starting or self._run_future is not None:
                    raise AssertionError("one owned start per observation scope")
                self._run_starting = True
            try:
                token, future = original_start(owner, request, interaction)
                self._bind_owned_run(token, future, request)
                return token, future
            finally:
                with self._run_lock:
                    self._run_starting = False
                    self._early_ready.clear()

        patch.setattr(TuiSummonOperations, "start", start)

    def _bind_owned_run(self, token: str, future: Any, request: Any) -> None:
        with self._run_lock:
            self._run_token, self._run_future = token, future
            self.ready = self.scope.expect(
                CompletionKey(self.app, "summon.ready_applied", request)
            )
            self.returned = self.scope.expect(
                CompletionKey(self.app, "summon.return_applied", future)
            )
            self.ready_handoff = self.scope.expect(
                CompletionKey(self.app, "summon.ready_handoff", request)
            )
            origin = self._early_ready.get(token)
            if origin is not None:
                self.ready_started_at = origin
                self.ready_handoff.succeed(self.ready_handoff.key, origin)

    def _record_ready_handoff(self, token: str) -> None:
        with self._run_lock:
            if token == self._run_token and self.ready_handoff is not None:
                if self.ready_started_at is None:
                    self.ready_started_at = self.scope.now()
                    self.ready_handoff.succeed(
                        self.ready_handoff.key, self.ready_started_at
                    )
            elif (
                self._run_starting
                and self._run_token is None
                and token not in self._early_ready
            ):
                # The real worker may call ready before start returns its token.
                # Retain only this active start's bounded admission window, then
                # select its returned token and discard unrelated callbacks.
                if len(self._early_ready) >= 16:
                    raise AssertionError("early ready handoff capacity exceeded")
                self._early_ready[token] = self.scope.now()

    def observe_owned_run(self) -> None:
        if self._run_armed:
            raise AssertionError("owned run observation already armed")
        self._run_armed = True

    async def confirmation(self, *, deadline: float, replacing: Any = None) -> Any:
        record = self.first if replacing is None else self.second
        if replacing is not None and (
            not self.presented or replacing is not self.presented[0]
        ):
            raise AssertionError("acknowledgement must replace this request's offer")
        screen = await record.wait(deadline=deadline, description="attach presentation")
        return await self.screens.ready(screen, deadline=deadline)

    async def settled(self, request: Any, *, deadline: float) -> Any:
        if self.request is not request or self.decision is None:
            raise AssertionError("decision belongs to another request")
        return await self.decision.wait(
            deadline=deadline, description="attach decision"
        )

    def close(self) -> None:
        try:
            self.scope.raise_if_invalid()
        finally:
            self.scope.close()
            self.screens.close()
            self.presented.clear()


class LeaseOrStop:
    """One wake for a test-owned acquisition source and stop request."""

    def __init__(self) -> None:
        self._wake = Event()
        self._lock = Lock()
        self.acquired = False
        self.stopped = False

    def set(self) -> None:
        with self._lock:
            self.acquired = True
        self._wake.set()

    def stop(self) -> None:
        with self._lock:
            self.stopped = True
        self._wake.set()

    def wait(self) -> bool:
        self._wake.wait()
        with self._lock:
            return self.acquired and not self.stopped


class ProviderConsumption:
    """Observe one orientation handoff and echo through its existing reader."""

    def __init__(self, patch: pytest.MonkeyPatch, marker: str, cap: float) -> None:
        from taut_summon._driver import SummonDriver

        self.scope = CompletionScope()
        self.started = self.scope.expect(
            CompletionKey(self, "orientation.started", self)
        )
        self._closed = False
        self._cap = cap
        self._buffer = b""
        self._lock = Lock()
        self._bound: Any = None
        self._operation_error: BaseException | None = None
        needle = marker.encode("utf-8")
        if not needle or len(needle) > 256:
            raise ValueError("provider marker must be bounded and nonempty")
        original_start = SummonDriver._start_phase_operation

        def start(driver: Any, name: str, operation: Any) -> None:
            if (
                self._closed
                or name != "orientation"
                or marker not in driver._owner_prompt
            ):
                original_start(driver, name, operation)
                return
            if self._bound is not None:
                raise AssertionError("one orientation handoff per provider observation")
            handle = driver._owner_running.handle
            self._bound = handle
            consumed = self.scope.expect(
                CompletionKey(handle, "provider.consumed", driver)
            )
            origin = self.scope.now()

            owner = handle if os.name == "nt" else handle._terminal
            method = "_observe_output" if os.name == "nt" else "observe_output"
            original_output = getattr(owner, method)

            def output(data: bytes, *, answer_queries: bool = True) -> Any:
                value = original_output(data, answer_queries=answer_queries)
                self._observe(consumed, handle, needle, data)
                return value

            patch.setattr(owner, method, output)
            self.started.succeed(self.started.key, (origin, consumed))

            original_start(driver, name, lambda: self._orient(operation, consumed))

        patch.setattr(SummonDriver, "_start_phase_operation", start)

    def _orient(self, operation: Any, consumed: Completion[Any]) -> Any:
        try:
            return operation()
        except BaseException as error:
            with self._lock:
                self._operation_error = error
                if consumed.snapshot() is None:
                    consumed.fail(consumed.key, error)
            raise

    def _observe(
        self, consumed: Completion[Any], handle: Any, needle: bytes, data: bytes
    ) -> None:
        with self._lock:
            if self._closed or consumed.snapshot() is not None:
                return
            self._buffer = (self._buffer + data.replace(b"\r", b""))[-32768:]
            while b"\nchat> " in self._buffer:
                frame, _, self._buffer = self._buffer.partition(b"\nchat> ")
                prefix = frame.find(b"\necho:")
                if prefix >= 0 and needle in b" ".join(frame[prefix + 6 :].split()):
                    self._buffer = b""
                    consumed.succeed(consumed.key, handle)
                    return

    def wait_sync(self, *, deadline: float) -> Any:
        origin, consumed = self.started.wait_sync(
            deadline=deadline, description="orientation handoff"
        )
        return consumed.wait_sync(
            deadline=min(deadline, origin + self._cap),
            description="provider consumption",
        )

    async def wait(self, *, deadline: float) -> Any:
        origin, consumed = await self.started.wait(
            deadline=deadline, description="orientation handoff"
        )
        return await consumed.wait(
            deadline=min(deadline, origin + self._cap),
            description="provider consumption",
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        with self._lock:
            self._closed = True
            self._buffer = b""
            operation_error = self._operation_error
        self.scope.__exit__(kind, error, traceback)
        if error is None and operation_error is not None:
            raise operation_error
