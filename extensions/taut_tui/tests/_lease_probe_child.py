"""Owned subprocess for the intentionally blocking headless-lease mutant."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from _completion import CompletionKey, CompletionScope
from _screen_completion import ScreenCompletions

from taut.client import TautClient
from taut_tui import app as app_module
from taut_tui import summon as summon_module
from taut_tui.app import TautApp
from taut_tui.summon import TerminalLeaseRequest, TuiSummonInteraction


def _lease_worker(
    operation: Any, release: threading.Event, record: Callable[[str], None]
) -> None:
    from taut_summon import TerminalAttachNotice

    try:
        accepted = operation.confirm_terminal_attach(
            TerminalAttachNotice(
                member="probe", provider="scripted", detach_hint="detach"
            )
        )
        assert accepted
        record("confirmed")
        with operation.terminal_lease():
            # Only the pilot is allowed to release this barrier.
            release.wait()
    finally:
        operation.release_current_worker()


def _join_lease_threads(app: Any) -> None:
    for lease_thread in app.lease_threads:
        lease_thread.join(5)
        assert not lease_thread.is_alive()


def main(directory: Path, block_loop: bool) -> None:
    # Import the actual recovery fixture. The mutant changes only its headless
    # post seam; the production lease deliberately blocks while suspended.
    from test_tui_summon import _gate_app

    db = directory / "lease.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="van")
    client.join("general")
    client.close()
    journal = directory / "phases.jsonl"
    lock = threading.Lock()

    def record(phase: str) -> None:
        with lock:
            with journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"phase": phase}) + "\n")
                stream.flush()
            # Textual redirects sys.stdout through its message queue. The
            # parent handshake must remain observable when that queue blocks.
            print(phase, file=sys.__stdout__, flush=True)

    async def exercise() -> None:
        with pytest.MonkeyPatch.context() as patch, CompletionScope() as scope:
            app = _gate_app(db)
            screens = ScreenCompletions(app, scope, patch)
            presented: Future[Any] = Future()
            presentation = scope.observe_future(
                presented, owner=app, phase="confirmation.presented"
            )
            acquired = scope.expect(
                CompletionKey(app, "lease.acquired", request=object())
            )
            restored = scope.expect(
                CompletionKey(app, "lease.restored", request=object())
            )
            release_worker = threading.Event()
            original_present = app_module._present_attach_confirmation
            original_post = app.post_message

            def present(*args: Any, **kwargs: Any) -> None:
                original_present(*args, **kwargs)
                presented.set_result(app.screen)

            def post(message: Any) -> bool:
                if isinstance(message, TerminalLeaseRequest):
                    original_acquire = message.acquired.set
                    original_restore = message.restored.set

                    def did_acquire() -> None:
                        original_acquire()
                        record("acquired")
                        acquired.succeed(acquired.key, message)

                    def did_restore() -> None:
                        original_restore()
                        record("restored")
                        restored.succeed(restored.key, message)

                    patch.setattr(message.acquired, "set", did_acquire)
                    patch.setattr(message.restored, "set", did_restore)
                    if block_loop:
                        return TautApp.post_message(app, message)
                return bool(original_post(message))

            patch.setattr(app_module, "_present_attach_confirmation", present)
            patch.setattr(app, "post_message", post)
            patch.setattr(summon_module, "_standard_terminal_is_suitable", lambda: True)
            interaction = TuiSummonInteraction(app, timeout=5)
            operation = interaction.operation_scope()

            executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="probe-foreground"
            )
            try:
                async with app.run_test(size=(100, 30)):
                    deadline = scope.now() + 5
                    worker = executor.submit(
                        _lease_worker, operation, release_worker, record
                    )
                    screen = await presentation.wait(
                        deadline=deadline, description="confirmation"
                    )
                    await screens.ready(screen, deadline=deadline)
                    screen.dismiss(True)
                    await acquired.wait(
                        deadline=deadline, description="lease acquisition"
                    )
                    record("pilot-release")
                    release_worker.set()
                    await restored.wait(
                        deadline=scope.now() + 5, description="lease restoration"
                    )
                    worker.result(timeout=5)
                    _join_lease_threads(app)
                    record("retired")
            finally:
                release_worker.set()
                interaction.close()
                executor.shutdown(wait=True)
                _join_lease_threads(app)
                screens.close()

    asyncio.run(exercise())


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] == "block")
