"""Extension-owned background work for actor-free Taut system operations.

Spec references:
- docs/specs/10-taut-tui.md [TUI-10], [TUI-12.3]
"""

from __future__ import annotations

import shlex
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from taut.client import DoctorReport, DumpReport, InitResult, TautClient


class OperationAlreadyRunning(RuntimeError):
    """A mutually exclusive system operation is already active."""


class ReplacementConfirmationRequired(RuntimeError):
    """The selected dump path currently exists and needs visual confirmation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"dump output already exists: {path}")


class TuiSystemOperations:
    """Own one bounded worker for non-chat public system operations."""

    def __init__(self, *, db_path: str | None) -> None:
        self._db_path = db_path
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="taut-tui-system",
        )
        self._lock = threading.Lock()
        self._dump_future: Future[DumpReport] | None = None
        self._closed = False

    def submit_doctor(self) -> Future[DoctorReport]:
        with self._lock:
            self._ensure_open()
        return self._executor.submit(TautClient.doctor, db_path=self._db_path)

    def submit_initialize(self) -> Future[InitResult]:
        with self._lock:
            self._ensure_open()
        return self._executor.submit(TautClient.init, db_path=self._db_path)

    def submit_dump(
        self,
        output: str | Path,
        *,
        replace_confirmed: bool = False,
    ) -> Future[DumpReport]:
        path = Path(output)
        with self._lock:
            self._ensure_open()
            if self._dump_future is not None and not self._dump_future.done():
                raise OperationAlreadyRunning("a workspace dump is already running")
            if path.exists() and not replace_confirmed:
                raise ReplacementConfirmationRequired(path)
            future = self._executor.submit(
                TautClient.dump,
                output=str(path),
                db_path=self._db_path,
            )
            self._dump_future = future
            return future

    def quit_block_reason(self) -> str | None:
        with self._lock:
            if self._dump_future is not None and not self._dump_future.done():
                return "A workspace dump is still running."
        return None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=False)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("system operation owner is closed")


def load_help_command(
    *,
    input_path: str | Path,
    db_path: str | None,
) -> str:
    """Return the exact CLI-only restore shape without inspecting either path."""

    input_argument = shlex.quote(str(input_path))
    if db_path is None:
        return f"taut system load --input {input_argument}"
    return f"taut --db {shlex.quote(db_path)} system load --input {input_argument}"


__all__ = [
    "OperationAlreadyRunning",
    "ReplacementConfirmationRequired",
    "TuiSystemOperations",
    "load_help_command",
]
