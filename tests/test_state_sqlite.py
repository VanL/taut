from __future__ import annotations

import json
import multiprocessing
from collections.abc import Iterator
from contextlib import contextmanager
from multiprocessing.connection import Connection
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from simplebroker import Queue

from taut import identity
from taut._constants import META_QUEUE_NAME
from taut.state import SQLITE_SQL_DIALECT, SqlSidecarTautState

pytestmark = pytest.mark.sqlite_only


def _update_persona_worker(
    db_path: str,
    member_id: str,
    observer: Connection,
) -> None:
    observer.send(("ready", None))
    queue = Queue(META_QUEUE_NAME, db_path=db_path)

    @contextmanager
    def observed_sidecar(*, transaction: bool = False) -> Iterator[Any]:
        observer.send(("attempt", transaction))
        with queue.sidecar(transaction=transaction) as session:
            yield session
        observer.send(("complete", transaction))

    state = SqlSidecarTautState(
        cast(Queue, SimpleNamespace(sidecar=observed_sidecar)),
        SQLITE_SQL_DIALECT,
    )
    try:
        updated = state.update_member_persona(member_id, "helper")
        observer.send(("result", None if updated is None else updated["meta"]))
    finally:
        queue.close()
        observer.close()


def _recv_worker_event(observer: Connection) -> tuple[str, object]:
    assert observer.poll(3.0), "persona worker stopped making progress"
    kind, payload = observer.recv()
    return str(kind), payload


def test_update_member_persona_preserves_concurrent_unknown_meta_write(
    tmp_path: Path,
) -> None:
    """[TAUT-3.3]/[TAUT-8.3]: concurrent meta updates cannot lose keys."""

    db_path = str(tmp_path / ".taut.db")
    queue = Queue(META_QUEUE_NAME, db_path=db_path)
    state = SqlSidecarTautState(queue, SQLITE_SQL_DIALECT)
    state.ensure_schema()
    member = state.insert_member(
        member_id=identity.random_member_id(),
        display_name="PersonaHolder",
        kind="agent",
        uid=1000,
        host_id="host:test",
        host_label="test-host",
        anchor_pid=None,
        anchor_start_time=None,
        fingerprint=None,
        token="persona-serialization-token",
        meta={},
        created_ts=10,
    )
    member_id = member["member_id"]
    context = multiprocessing.get_context("spawn")
    observer, worker_observer = context.Pipe(duplex=False)
    worker = context.Process(
        target=_update_persona_worker,
        args=(db_path, member_id, worker_observer),
    )
    started = False
    try:
        with queue.sidecar(transaction=True) as writer:
            writer.run(
                "UPDATE taut_members SET meta = ? WHERE member_id = ?",
                (json.dumps({"custom_flag": "committed"}), member_id),
            )
            worker.start()
            started = True
            worker_observer.close()

            assert observer.poll(15.0), (
                "persona worker did not finish interpreter startup "
                f"(exitcode={worker.exitcode})"
            )
            assert observer.recv() == ("ready", None)
            first_event = _recv_worker_event(observer)
            assert first_event[0] == "attempt"
            if first_event == ("attempt", False):
                # A stale-read implementation is allowed to finish that read
                # while the competing write remains uncommitted. The final
                # state assertion below must still reject a lost update.
                assert _recv_worker_event(observer) == ("complete", False)

        while True:
            kind, payload = _recv_worker_event(observer)
            if kind == "result":
                result = payload
                break

        worker.join(timeout=3.0)
        assert not worker.is_alive()
        assert worker.exitcode == 0
        assert result == {
            "custom_flag": "committed",
            "persona": "helper",
        }
        persisted = state.get_member(member_id)
        assert persisted is not None
        assert persisted["meta"] == result
    finally:
        if started and worker.is_alive():
            worker.terminate()
            worker.join(timeout=3.0)
        if started and worker.is_alive():
            worker.kill()
            worker.join(timeout=3.0)
        observer.close()
        worker_observer.close()
        queue.close()
