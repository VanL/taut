"""Single-owner Summon delivery proofs ([SUM-5.4])."""

from __future__ import annotations

import threading
from contextlib import closing
from pathlib import Path
from typing import Any, cast

import pytest
from simplebroker import Queue
from taut_summon._reactor import PreparedInjection, SummonReactor

from taut.client import TautClient


def test_retained_active_row_is_not_refetched_while_delivery_is_pending(
    summon_db: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    with closing(TautClient(db_path=str(summon_db), as_name="listener")) as listener:
        listener.join("general")
        with closing(TautClient(db_path=str(summon_db), as_name="peer")) as peer:
            peer.join("general")
            peer.say("general", "retained")

        def deliver(item: object) -> None:
            calls.append(str(item))
            entered.set()
            assert release.wait(5)

        class Handle:
            def inject(self, text: str) -> None:
                deliver(text)

            def request_close(self) -> None:
                release.set()

        reactor = listener.watch(lambda _item: None, watcher_type=SummonReactor)
        assert isinstance(reactor, SummonReactor)
        reactor.prepare_delivery = lambda item: PreparedInjection(
            cast(Any, Handle()), str(item), None
        )
        try:
            reactor.process_once()
            assert entered.wait(2)
            cursors = dict(reactor._cursors)
            notification = Queue(
                reactor._notification_queue_name, db_path=str(summon_db)
            )
            notification.write("unclaimed sentinel")
            for _ in range(4):
                reactor.process_once()
            assert len(calls) == 1
            assert reactor._cursors == cursors
            assert notification.read_one() == "unclaimed sentinel"
            notification.close()
            release.set()
            assert reactor._delivery_thread is not None
            reactor._delivery_thread.join(2)
            reactor.process_once()
            assert reactor._cursors != cursors
        finally:
            release.set()
            reactor.stop(join=False)


@pytest.mark.parametrize("cancelled", [False, True])
def test_unsuccessful_injection_preserves_retained_cursor(
    summon_db: Path,
    cancelled: bool,
) -> None:
    from taut_summon._adapter import AdapterError, AdapterWriteCancelled

    from taut import WatcherRejected

    with closing(TautClient(db_path=str(summon_db), as_name="listener")) as listener:
        listener.join("general")
        with closing(TautClient(db_path=str(summon_db), as_name="peer")) as peer:
            peer.join("general")
            peer.say("general", "retained")

        def deliver(_item: object) -> None:
            if cancelled:
                raise AdapterWriteCancelled("cancelled write")
            raise AdapterError("failed write")

        class Handle:
            def inject(self, text: str) -> None:
                deliver(text)

        reactor = listener.watch(lambda _item: None, watcher_type=SummonReactor)
        assert isinstance(reactor, SummonReactor)
        reactor.prepare_delivery = lambda item: PreparedInjection(
            cast(Any, Handle()), str(item), None
        )
        try:
            initial = dict(reactor._cursors)
            reactor.process_once()
            assert reactor._delivery_thread is not None
            reactor._delivery_thread.join(2)
            with pytest.raises(WatcherRejected, match="injection failed"):
                reactor.process_once()
            assert reactor._cursors == initial
        finally:
            reactor.stop(join=False)


def test_owner_preparation_failure_stops_once_with_cursor_unchanged(
    summon_db: Path,
) -> None:
    with closing(TautClient(db_path=str(summon_db), as_name="listener")) as listener:
        listener.join("general")
        with closing(TautClient(db_path=str(summon_db), as_name="peer")) as peer:
            peer.join("general")
            listener.read_unread("general")
            sent = peer.say("general", "retained")
        owner = threading.get_ident()
        attempts: list[int] = []

        def malformed(_item: object) -> None:
            attempts.append(threading.get_ident())
            raise ValueError("formatting failed")

        reactor = listener.watch(lambda _item: None, watcher_type=SummonReactor)
        assert isinstance(reactor, SummonReactor)
        reactor.prepare_delivery = malformed
        initial = dict(reactor._cursors)
        try:
            with pytest.raises(ValueError, match="formatting failed"):
                reactor.process_once()
            assert attempts == [owner]
            assert reactor._cursors == initial
            assert reactor._delivery_pending is False
        finally:
            reactor.stop(join=False)

        injected: list[str] = []

        class Handle:
            def inject(self, text: str) -> None:
                injected.append(text)

        restarted = listener.watch(lambda _item: None, watcher_type=SummonReactor)
        assert isinstance(restarted, SummonReactor)
        restarted.prepare_delivery = lambda item: PreparedInjection(
            cast(Any, Handle()), str(item), None
        )
        try:
            restarted.process_once()
            worker = restarted._delivery_thread
            assert worker is not None
            worker.join(2)
            restarted.process_once()
            assert len(injected) == 1
            assert restarted._cursors["general"] >= sent.ts
        finally:
            restarted.stop(join=False)


def test_worker_start_failure_does_not_leave_delivery_gated(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with closing(TautClient(db_path=str(summon_db), as_name="listener")) as listener:
        listener.join("general")
        with closing(TautClient(db_path=str(summon_db), as_name="peer")) as peer:
            peer.join("general")
            peer.say("general", "retained")

        class Handle:
            def inject(self, _text: str) -> None:
                pass

        reactor = listener.watch(lambda _item: None, watcher_type=SummonReactor)
        assert isinstance(reactor, SummonReactor)
        reactor.prepare_delivery = lambda item: PreparedInjection(
            cast(Any, Handle()), str(item), None
        )
        try:
            with monkeypatch.context() as patch:

                def fail_start(_thread: threading.Thread) -> None:
                    raise RuntimeError("cannot create worker")

                patch.setattr(threading.Thread, "start", fail_start)
                from simplebroker.ext import StopWatching

                with pytest.raises(StopWatching):
                    reactor.process_once()
            assert reactor._delivery_pending is False
            assert reactor._delivery_thread is None
            assert reactor._delivery_cursor is None
        finally:
            reactor.stop(join=False)


@pytest.mark.parametrize("still_injecting", [False, True])
def test_source_close_interrupts_only_a_live_injection_worker(
    summon_db: Path,
    still_injecting: bool,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    interrupted: list[bool] = []

    class Handle:
        def inject(self, _text: str) -> None:
            entered.set()
            assert release.wait(5)

        def request_close(self) -> None:
            interrupted.append(True)
            release.set()

    with closing(TautClient(db_path=str(summon_db), as_name="listener")) as listener:
        listener.join("general")
        with closing(TautClient(db_path=str(summon_db), as_name="peer")) as peer:
            peer.join("general")
            peer.say("general", "retained")
        reactor = listener.watch(lambda _item: None, watcher_type=SummonReactor)
        assert isinstance(reactor, SummonReactor)
        reactor.prepare_delivery = lambda item: PreparedInjection(
            cast(Any, Handle()), str(item), None
        )
        try:
            reactor.process_once()
            assert entered.wait(2)
            worker = reactor._delivery_thread
            assert worker is not None
            if not still_injecting:
                release.set()
                worker.join(2)
                assert not worker.is_alive()
            # Deliberately do not consume the published completion: recovery
            # must not mistake an unapplied owner result for a live native write.
            reactor.stop(join=False)
            assert not worker.is_alive()
            assert interrupted == ([True] if still_injecting else [])
        finally:
            release.set()
            reactor.stop(join=False)


def test_retired_injection_leaves_record_for_successor(summon_db: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    injections: list[str] = []
    first_generation = object()
    second_generation = object()
    active_generation = first_generation

    class Handle:
        def __init__(self, *, blocked: bool) -> None:
            self.blocked = blocked

        def inject(self, text: str) -> None:
            if self.blocked:
                entered.set()
                assert release.wait(5)
                return
            injections.append(text)

        def request_close(self) -> None:
            release.set()

    first_handle = Handle(blocked=True)
    second_handle = Handle(blocked=False)
    with closing(TautClient(db_path=str(summon_db), as_name="listener")) as listener:
        listener.join("general")
        with closing(TautClient(db_path=str(summon_db), as_name="peer")) as peer:
            peer.join("general")
            listener.read_unread("general")
            sent = peer.say("general", "retained")
        reactor = listener.watch(lambda _item: None, watcher_type=SummonReactor)
        assert isinstance(reactor, SummonReactor)
        reactor.prepare_delivery = lambda item: PreparedInjection(
            cast(
                Any,
                first_handle
                if active_generation is first_generation
                else second_handle,
            ),
            str(item),
            active_generation,
        )
        try:
            reactor.process_once()
            assert entered.wait(2)
            reactor.retire_delivery_generation(first_generation)
            assert reactor._delivery_pending is False
            assert reactor._cursors["general"] < sent.ts

            active_generation = second_generation
            reactor.process_once()
            worker = reactor._delivery_thread
            assert worker is not None
            worker.join(2)
            reactor.process_once()
            assert len(injections) == 1
            assert reactor._cursors["general"] >= sent.ts
        finally:
            release.set()
            reactor.stop(join=False)
