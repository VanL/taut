"""Run the real BaseReactor reentrant-SIGINT regression in an isolated child."""

from __future__ import annotations

import argparse
import json
import signal
import tempfile
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

from simplebroker.ext import PollingStrategy

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
            self.reenter_on_notify = False

        def replace_activity_waiter(self, activity_waiter: Any | None) -> Any | None:
            self.replacements.append(activity_waiter)
            displaced = PollingStrategy.replace_activity_waiter(self, activity_waiter)
            self.reenter_on_notify = True
            signal.raise_signal(signal.SIGINT)
            return displaced

        def notify_activity(self) -> None:
            if self.reenter_on_notify:
                self.reenter_on_notify = False
                signal.raise_signal(signal.SIGINT)
            super().notify_activity()

    class DynamicReactor(BaseReactor):
        _dynamic_topology = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._topology_changed = False
            super().__init__(*args, **kwargs)

        def _process_reactor_turn(self) -> None:
            if not self._topology_changed:
                self._topology_changed = True
                self.add_queue("dynamic.two", lambda *_args: None)

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
    with tempfile.TemporaryDirectory(prefix="taut-sigint-probe-") as temp_dir:
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
        "multi_generation_matches": (
            watcher._multi_activity_waiter_generation == watcher._queue_generation
        ),
        "multi_waiter_is_replacement": (
            watcher._multi_activity_waiter is replacement_waiter
        ),
        "replacement_close_calls": replacement_waiter.close_calls,
        "replacement_count": len(strategy.replacements),
        "replacement_is_expected": strategy.replacements == [replacement_waiter],
        "start_calls": strategy.start_calls,
        "status": "ok",
        "strategy_generation_matches": (
            watcher._strategy_generation == watcher._queue_generation
        ),
    }


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("probe", "hang"), default="probe")
    args = parser.parse_args()

    if args.mode == "hang":
        _emit({"status": "hanging"})
        threading.Event().wait()
        raise AssertionError("unreachable")

    try:
        _emit(_run_probe())
    except BaseException as exc:
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
