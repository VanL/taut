"""Run the real BaseReactor reentrant-SIGINT regression in an isolated child."""

from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from simplebroker import _broker_session
from simplebroker.ext import PollingStrategy

from taut.client import TautClient
from taut.watcher import BaseReactor


class FakeWaiter:
    def __init__(self) -> None:
        self.close_calls = 0

    def wait(self, timeout: float | None) -> bool:
        del timeout
        return False

    def close(self) -> None:
        self.close_calls += 1


class RecordingPollingStrategy(PollingStrategy):
    def __init__(self, stop_event: threading.Event) -> None:
        super().__init__(stop_event)
        self.start_calls = 0
        self.replacements: list[Any | None] = []

    def start(
        self,
        data_version_provider: Callable[[], int | None] | None = None,
        *,
        on_data_version_change: Callable[[], None] | None = None,
        activity_waiter: Any | None = None,
    ) -> None:
        self.start_calls += 1
        super().start(
            data_version_provider,
            on_data_version_change=on_data_version_change,
            activity_waiter=activity_waiter,
        )

    def replace_activity_waiter(self, activity_waiter: Any | None) -> Any | None:
        self.replacements.append(activity_waiter)
        return super().replace_activity_waiter(activity_waiter)


def _run_probe() -> dict[str, object]:
    installed_waiter = FakeWaiter()
    replacement_waiter = FakeWaiter()
    waiters = iter((installed_waiter, replacement_waiter))
    stop_event = threading.Event()

    class InterruptingStrategy(RecordingPollingStrategy):
        def __init__(self) -> None:
            super().__init__(stop_event)

        def replace_activity_waiter(self, activity_waiter: Any | None) -> Any | None:
            self.replacements.append(activity_waiter)
            displaced = PollingStrategy.replace_activity_waiter(self, activity_waiter)
            # A signal handler that sets this Event deadlocks on its own lock.
            with cast(Any, stop_event)._cond:
                signal.raise_signal(signal.SIGINT)
            return displaced

    class DynamicReactor(BaseReactor):
        _dynamic_topology = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._topology_changed = False
            super().__init__(*args, **kwargs)

        def _process_reactor_turn(self) -> None:
            if not self._topology_changed:
                self._topology_changed = True
                self.add_queue("dynamic.two", lambda *_args: None)

        def _finish_topology_sigint_critical(
            self, *, fatal_error: BaseException | None = None
        ) -> None:
            self.publication_coherent = (
                "dynamic.two" in self._queues
                and self._multi_activity_waiter is replacement_waiter
                and self._multi_activity_waiter_generation == self._queue_generation
            )
            super()._finish_topology_sigint_critical(fatal_error=fatal_error)

        def next_wait_timeout(self) -> float | None:
            return 0.1

    def create_waiter(
        _queues: Sequence[object],
        *,
        stop_event: threading.Event,
    ) -> FakeWaiter:
        del stop_event
        return next(waiters)

    strategy = InterruptingStrategy()
    with tempfile.TemporaryDirectory(prefix="taut-sigint-probe-") as temp_dir:  # noqa: SIM117 approved [DOM-10.2.1] [RUFF-SUP-074] exception
        with patch(
            "taut.watcher.create_activity_waiter_for_queues",
            side_effect=create_waiter,
        ):
            watcher = DynamicReactor(
                queue_configs={"dynamic.one": {"handler": lambda *_args: None}},
                db=Path(temp_dir) / ".taut.db",
                stop_event=stop_event,
                polling_strategy=strategy,
            )
            keyboard_interrupt = False
            try:
                watcher.run()
            except KeyboardInterrupt:
                keyboard_interrupt = True

    return {
        "installed_close_calls": installed_waiter.close_calls,
        "keyboard_interrupt": keyboard_interrupt,
        "publication_coherent": watcher.publication_coherent,
        "waiter_retired": watcher._multi_activity_waiter is None,
        "replacement_close_calls": replacement_waiter.close_calls,
        "replacement_count": len(strategy.replacements),
        "replacement_is_expected": strategy.replacements == [replacement_waiter],
        "start_calls": strategy.start_calls,
        "status": "ok",
    }


def _run_held_event_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="taut-held-event-") as temp_dir:
        watcher = BaseReactor(
            {"input": {"handler": lambda *_: None}}, db=Path(temp_dir) / "test.db"
        )
        previous = signal.signal(signal.SIGINT, watcher._sigint_handler)
        interrupted = False
        try:
            with cast(Any, watcher._stop_event)._cond:
                signal.raise_signal(signal.SIGINT)
            assert not watcher._resources_closed
            try:
                watcher.run_until_stopped()
            except KeyboardInterrupt:
                interrupted = True
        finally:
            signal.signal(signal.SIGINT, previous)
            watcher.stop(join=False)
        return {
            "status": "ok",
            "interrupted": interrupted,
            "resources_closed": watcher._resources_closed,
        }


def _run_broker_io_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="taut-broker-io-sigint-") as temp_dir:
        db = Path(temp_dir) / "test.db"
        TautClient.init(db_path=db)
        client = TautClient(db_path=db, as_name="van")
        client.join("general")
        watcher = client.watch(lambda _item: None)
        assert watcher._broker_session is not None
        process_session = watcher._broker_session._process_session
        original_release = (
            _broker_session._ProcessBrokerSession.release_current_thread_connection
        )
        signal_delivered = False

        def interrupting_release(
            session: _broker_session._ProcessBrokerSession,
            *,
            active_failure: BaseException | None = None,
        ) -> None:
            nonlocal signal_delivered
            if session is process_session and not signal_delivered:
                signal_delivered = True
                os.kill(os.getpid(), signal.SIGINT)
            original_release(session, active_failure=active_failure)

        interrupted = False
        interrupt_notes: tuple[str, ...] = ()
        with patch.object(
            _broker_session._ProcessBrokerSession,
            "release_current_thread_connection",
            interrupting_release,
        ):
            try:
                watcher.run_forever()
            except KeyboardInterrupt as exc:
                interrupted = True
                interrupt_notes = tuple(getattr(exc, "__notes__", ()))

        cleanup_error: str | None = None
        try:
            watcher.stop(join=False)
        except Exception as exc:  # noqa: BLE001 - structured child-process evidence
            cleanup_error = f"{type(exc).__name__}: {exc}"
        try:
            client.close()
        except Exception as exc:  # noqa: BLE001 - structured child-process evidence
            if cleanup_error is None:
                cleanup_error = f"client close: {type(exc).__name__}: {exc}"

        return {
            "cleanup_error": cleanup_error,
            "interrupt_notes": list(interrupt_notes),
            "interrupted": interrupted,
            "resources_closed": watcher._resources_closed,
            "signal_delivered": signal_delivered,
            "status": "ok",
        }


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=(
            "probe",
            "broker-io",
            "held-event",
            "hang",
            "startup-hang",
            "early-exit",
            "invalid-startup",
            "unexpected-startup",
        ),
        default="probe",
    )
    args = parser.parse_args()

    if args.mode == "early-exit":
        return 7
    if args.mode == "invalid-startup":
        print("not-json", flush=True)
        return 0
    if args.mode == "unexpected-startup":
        _emit({"status": "unexpected"})
        return 0
    if args.mode == "startup-hang":
        threading.Event().wait()
        raise AssertionError("unreachable")
    if args.mode == "hang":
        _emit({"status": "hanging"})
        threading.Event().wait()
        raise AssertionError("unreachable")

    _emit({"status": "ready"})
    try:
        if args.mode == "broker-io":
            result = _run_broker_io_probe()
        elif args.mode == "held-event":
            result = _run_held_event_probe()
        else:
            result = _run_probe()
        _emit(result)
        if args.mode == "broker-io" and result.get("cleanup_error") is not None:
            # A regressed open operation can stall interpreter finalizers. The
            # structured result above is the proof; contain the broken child.
            os._exit(0)
    except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
        _emit(
            {
                "error": str(exc),
                "error_type": type(exc).__name__,
                "status": "error",
            }
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
