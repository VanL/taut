"""Watcher-thread ↔ UI marshaling bridge for the Taut TUI.

Plan Task 4; spec 04 [TUI-10.5], core [TAUT-8.4]. Pure lifecycle contract
with no Textual knowledge so its threading behavior is testable without a
running App.

Acknowledgment contract (review findings 4, R2-1, R2-2, R3-9):

- **Message** — the watch runtime advances the chat cursor immediately
  after the handler returns (``watcher.py:642``), so the handler hands the
  item to the UI **synchronously** and lets any exception propagate: a
  failed UI update leaves the cursor unmoved and the message is
  redelivered (at-least-once display, INV-8).
- **Notification** — already consumed by the watch runtime (READ-mode
  queue); display is best-effort after consumption ([TAUT-10], [IAN-7.4]). A
  render failure is logged, never raised: raising would burn watcher
  retries for an item that cannot be redelivered anyway.
- **Shutdown** — ``stop()`` sets the watcher stop event FIRST, then the
  ``stopping`` flag, then joins off the caller's thread budget. A Message
  arriving after ``stopping`` raises :class:`ShutdownNonAck` so an
  undisplayed message is never acked; stop-event-first ordering means the
  loop exits via ``StopWatching`` instead of refetching, so the same
  message cannot accumulate three raises and be poison-advanced
  (``watcher.py:631-638``). Do not reorder.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from taut.client import Message, Notification, TautClient
from taut.watcher import TautWatcher

logger = logging.getLogger(__name__)


class ShutdownNonAck(Exception):
    """Raised by the watch handler during shutdown so the in-flight chat
    message is NOT acknowledged; it is redelivered on the next session."""


class WatchBridge:
    """Owns one watcher and its thread for the lifetime of a TUI session.

    ``deliver`` is the synchronous UI hand-off (the App wraps it in
    ``call_from_thread``); it runs on the watcher's thread and must block
    until the UI has accepted the item, raising on failure.
    """

    def __init__(
        self,
        *,
        client: TautClient,
        deliver: Callable[[Message | Notification], None],
    ) -> None:
        self._client = client
        self._deliver = deliver
        self._stopping = threading.Event()
        self._watcher: TautWatcher | None = None
        # Strong reference: the base watcher only keeps a weakref to the
        # thread run_in_thread() created, and stop(join=True) can only
        # join what it can still dereference (review finding 5).
        self._thread: threading.Thread | None = None

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def start(self) -> None:
        if self._watcher is not None:
            raise RuntimeError("bridge already started")
        self._watcher = self._client.watch(self.handle, threads=None)
        self._thread = self._watcher.run_in_thread()

    def handle(self, item: Message | Notification) -> None:
        """The watch handler; runs on the watcher's own loop thread."""

        if isinstance(item, Notification):
            if self._stopping.is_set():
                return
            try:
                self._deliver(item)
            except Exception:
                # Best-effort by contract: the notification was consumed on
                # read; source chat history remains the durable record.
                logger.warning("notification display failed", exc_info=True)
            return
        if self._stopping.is_set():
            # Returning normally would let the runtime mark an undisplayed
            # message seen (finding R2-1). Raise instead: not acked, and
            # redelivered next session.
            raise ShutdownNonAck(f"shutting down; not acking {item.thread}")
        self._deliver(item)

    def stop(self, *, timeout: float = 5.0) -> None:
        """Ordered shutdown. Call from a worker thread, never from inside
        the UI event loop a pending ``deliver`` may be waiting on."""

        watcher = self._watcher
        if watcher is None:
            return
        self._watcher = None
        # (1) Stop event first: the loop stops fetching (StopWatching)...
        watcher.stop(join=False)
        # (2) ...then the stopping flag: any already-fetched Message raises
        # ShutdownNonAck instead of acking undisplayed content.
        self._stopping.set()
        # (3) Bounded join; liveness wins if the thread does not stop.
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("watcher thread did not stop within %ss", timeout)
