from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from simplebroker.ext import DatabaseError

from taut._broker_retry import broker_retry, is_transient_broker_error
from taut._constants import META_QUEUE_NAME
from taut._queue import RetryingQueue
from taut.client import TautClient
from taut.state import SQLITE_SQL_DIALECT, SqlSidecarTautState

pytestmark = pytest.mark.sqlite_only


def test_broker_retry_recovers_magic_mismatch_connection_open() -> None:
    attempts = 0

    def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError(
                "Failed to get database connection: Database magic string mismatch. "
                "Expected 'simplebroker-v1', found 'm_example'."
            )
        return "ok"

    assert broker_retry(flaky, what="test") == "ok"
    assert attempts == 2


def test_broker_retry_classifies_simplebroker_none_timestamp_parse() -> None:
    assert is_transient_broker_error(
        TypeError(
            "int() argument must be a string, a bytes-like object or a real number, "
            "not 'NoneType'"
        )
    )
    assert is_transient_broker_error(ValueError("invalid literal for int()"))
    assert is_transient_broker_error(DatabaseError("database disk image is malformed"))
    assert not is_transient_broker_error(ValueError("bad command"))


def test_retrying_queue_retries_sidecar_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    queue = RetryingQueue(META_QUEUE_NAME, db_path=str(db))
    state = SqlSidecarTautState(queue, SQLITE_SQL_DIALECT)
    original_get_connection = queue.get_connection
    calls = 0

    @contextmanager
    def flaky_get_connection() -> Iterator[Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(
                "Failed to get database connection: Database magic string mismatch. "
                "Expected 'simplebroker-v1', found 'm_example'."
            )
        with original_get_connection() as connection:
            yield connection

    monkeypatch.setattr(queue, "get_connection", flaky_get_connection)

    assert state.get_schema_version() == 2
    assert calls == 2


def test_retrying_queue_retries_queue_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    queue = RetryingQueue("general", db_path=str(db))
    original_get_connection = queue.get_connection
    calls = 0

    @contextmanager
    def flaky_get_connection() -> Iterator[Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TypeError(
                "int() argument must be a string, a bytes-like object or a real "
                "number, not 'NoneType'"
            )
        with original_get_connection() as connection:
            yield connection

    monkeypatch.setattr(queue, "get_connection", flaky_get_connection)

    assert queue.has_pending() is False
    assert calls == 2
