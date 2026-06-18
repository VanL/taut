from __future__ import annotations

from pathlib import Path

import pytest
from simplebroker import Queue

from taut._constants import META_QUEUE_NAME
from taut._exceptions import EmptyResultError, NotInitializedError
from taut.client import TautClient

pytestmark = pytest.mark.sqlite_only


def client(tmp_path: Path, as_handle: str) -> TautClient:
    TautClient.init(db_path=tmp_path / ".taut.db")
    return TautClient(db_path=tmp_path / ".taut.db", as_handle=as_handle)


def test_explicit_missing_path_does_not_auto_create(tmp_path: Path) -> None:
    with pytest.raises(NotInitializedError):
        TautClient(db_path=tmp_path / ".taut.db")

    assert not (tmp_path / ".taut.db").exists()


def test_join_starts_at_now_and_other_member_message_is_unread(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    claude = TautClient(db_path=tmp_path / ".taut.db", as_handle="claude")
    claude.join("general")

    van.say("general", "hello")
    unread = claude.read("general")

    assert [message.text for message in unread] == ["hello"]
    with pytest.raises(EmptyResultError):
        claude.read("general")


def test_sender_cursor_advances_when_caught_up(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    van.say("general", "self")

    with pytest.raises(EmptyResultError):
        van.read("general")


def test_reply_full_id_creates_subthread(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    first = van.say("general", "root")

    reply = van.reply("general", str(first.ts), "threaded")

    assert reply.thread == f"general.{first.ts}"
    assert van.log(reply.thread)[0].text == "threaded"


def test_guest_read_only_resolution_does_not_generate_timestamp(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    before = queue.refresh_last_ts()

    TautClient(db_path=tmp_path / ".taut.db").who()

    after = queue.refresh_last_ts()
    assert after == before
