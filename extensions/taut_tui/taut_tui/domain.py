"""Native TUI actions over public core operations.

This is an embedding adapter, not a CLI adapter. It never renders argparse,
invokes a subprocess, or reconstructs domain validation.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2], [TUI-6], [TUI-7], [TUI-10]
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import TypeVar

from taut import EmptyResultError
from taut.client import (
    Channel,
    DoctorReport,
    DumpReport,
    InitResult,
    Member,
    Message,
    MessageDeletion,
    MessageReaction,
    Notification,
    SearchHit,
    TautClient,
    Thread,
)
from taut_tui.actions import ActionId
from taut_tui.session import ConversationSnapshot, TuiSession
from taut_tui.system import TuiSystemOperations, load_help_command

_ItemT = TypeVar("_ItemT")

CORE_DOMAIN_ACTIONS = frozenset(
    {
        ActionId.WORKSPACE_INITIALIZE,
        ActionId.IDENTITY_REJOIN,
        ActionId.IDENTITY_SHOW,
        ActionId.IDENTITY_SET_NAME,
        ActionId.IDENTITY_SET_PERSONA,
        ActionId.CONVERSATION_OPEN,
        ActionId.CHANNEL_JOIN,
        ActionId.CHANNEL_LEAVE,
        ActionId.DIRECT_MESSAGE_START,
        ActionId.NOTIFICATIONS_OPEN,
        ActionId.MEMBERS_OPEN,
        ActionId.CHANNEL_SHOW_TOPIC,
        ActionId.CHANNEL_SET_TOPIC,
        ActionId.CHANNEL_CLEAR_TOPIC,
        ActionId.CHANNEL_RENAME,
        ActionId.MESSAGE_SEND,
        ActionId.MESSAGE_REPLY,
        ActionId.MESSAGE_REACT,
        ActionId.MESSAGE_DELETE,
        ActionId.SEARCH_OPEN,
        ActionId.SEARCH_OPEN_RESULT,
        ActionId.SYSTEM_DOCTOR,
        ActionId.SYSTEM_DUMP,
        ActionId.SYSTEM_LOAD_HELP,
    }
)


class TuiDomainActions:
    """Typed native operations owned by one TUI session."""

    def __init__(
        self,
        *,
        session: TuiSession,
        system: TuiSystemOperations,
        db_path: str | None,
    ) -> None:
        self._session = session
        self._system = system
        self._db_path = db_path

    def initialize_workspace(self) -> Future[InitResult]:
        return self._system.submit_initialize()

    def rejoin_identity(
        self,
        name_or_alias: str | None = None,
        *,
        token: str | None = None,
    ) -> Future[Member]:
        return self._session.submit_client_operation(
            lambda client: client.rejoin(name_or_alias, token=token)
        )

    def show_identity(self, *, explain: bool = False) -> Future[Member]:
        return self._session.submit_client_operation(
            lambda client: client.whoami(explain=explain)
        )

    def set_name(self, name: str) -> Future[Member]:
        return self._session.submit_client_operation(
            lambda client: client.set_name(name)
        )

    def set_persona(self, persona: str | None) -> Future[Member]:
        return self._session.submit_client_operation(
            lambda client: client.set_persona(persona)
        )

    def open_conversation(
        self,
        target: str,
        *,
        reply_thread: str | None = None,
        intent_token: int | None = None,
    ) -> Future[ConversationSnapshot | None]:
        return self._session.open_conversation(
            target,
            reply_thread=reply_thread,
            intent_token=intent_token,
        )

    def join_channel(
        self,
        channel: str,
        *,
        persona: str | None = None,
        new: bool = False,
    ) -> Future[Message]:
        return self._session.submit_client_operation(
            lambda client: client.join(channel, persona=persona, new=new)
        )

    def leave_channel(self, channel: str) -> Future[Message]:
        return self._session.submit_client_operation(
            lambda client: client.leave(channel)
        )

    def start_direct_message(self, member: str, text: str) -> Future[Message]:
        handle = member.removeprefix("@")
        return self._session.submit_client_operation(
            lambda client: client.say(f"@{handle}", text)
        )

    def notifications(self) -> tuple[Notification, ...]:
        return self._session.notification_feed()

    def members(self, thread: str | None = None) -> Future[list[Member]]:
        return self._session.submit_client_operation(lambda client: client.who(thread))

    def show_topic(self, channel: str) -> Future[Channel]:
        return self._session.submit_client_operation(
            lambda client: client.get_channel(channel)
        )

    def set_topic(self, channel: str, topic: str) -> Future[Channel]:
        return self._session.submit_client_operation(
            lambda client: client.set_channel_topic(channel, topic)
        )

    def clear_topic(self, channel: str) -> Future[Channel]:
        return self._session.submit_client_operation(
            lambda client: client.set_channel_topic(channel, None)
        )

    def rename_channel(self, old_name: str, new_name: str) -> Future[Thread]:
        return self._session.submit_client_operation(
            lambda client: client.rename_channel(old_name, new_name)
        )

    def send_message(self, target: str, text: str) -> Future[Message]:
        return self._session.submit_client_operation(
            lambda client: client.say(target, text)
        )

    def show_message(self, message_id: str) -> Future[Message]:
        return self._session.submit_client_operation(
            lambda client: client.show_message(message_id)
        )

    def reply_message(
        self,
        channel: str,
        message_id: str | int,
        text: str,
    ) -> Future[Message]:
        return self._session.submit_client_operation(
            lambda client: client.reply(channel, str(message_id), text)
        )

    def react_message(
        self,
        message_id: str | int,
        reaction: str,
    ) -> Future[MessageReaction]:
        return self._session.submit_client_operation(
            lambda client: client.react_to_message(str(message_id), reaction)
        )

    def delete_message(self, message_id: str | int) -> Future[MessageDeletion]:
        return self._session.submit_client_operation(
            lambda client: client.delete_message(str(message_id))
        )

    def read_messages(self, thread: str | None = None) -> Future[list[Message]]:
        # [TUI-12.1]: an empty result is a result, not an error.
        return self._session.submit_client_operation(
            lambda client: _empty_ok(lambda: client.read(thread))
        )

    def inbox(self) -> Future[list[Notification]]:
        return self._session.submit_client_operation(
            lambda client: _empty_ok(client.inbox)
        )

    def log_messages(
        self,
        thread: str,
        *,
        since: str | int | None = None,
        limit: int | None = None,
    ) -> Future[list[Message]]:
        return self._session.submit_client_operation(
            lambda client: _empty_ok(
                lambda: client.log(thread, since=since, limit=limit)
            )
        )

    def list_threads(
        self,
        *,
        all_threads: bool = False,
        direct_messages: bool = False,
    ) -> Future[list[Thread]]:
        operation = (
            (lambda client: _empty_ok(client.list_direct_messages))
            if direct_messages
            else (lambda client: client.list_threads(all_threads=all_threads))
        )
        return self._session.submit_client_operation(operation)

    def members_for_thread(self, thread: str | None = None) -> Future[list[Member]]:
        return self._session.submit_client_operation(lambda client: client.who(thread))

    def search(self, query: str, *, limit: int = 50) -> Future[list[SearchHit]]:
        def search_visible(client: TautClient) -> list[SearchHit]:
            joined = set(client.joined_thread_names())
            channels = tuple(
                thread.name
                for thread in client.list_threads(all_threads=True)
                if thread.kind == "channel" and thread.name in joined
            )
            try:
                return client.search(
                    query,
                    channels=channels,
                    all_direct_messages=True,
                    limit=limit,
                )
            except EmptyResultError:
                return []

        return self._session.submit_client_operation(search_visible)

    def open_search_result(
        self,
        hit: SearchHit,
        *,
        before: int = 25,
        after: int = 25,
    ) -> Future[list[Message]]:
        return self._session.submit_client_operation(
            lambda client: client.history_around(
                hit.thread,
                str(hit.ts),
                before=before,
                after=after,
            )
        )

    def doctor(self) -> Future[DoctorReport]:
        return self._system.submit_doctor()

    def dump(
        self,
        output: str | Path,
        *,
        replace_confirmed: bool = False,
    ) -> Future[DumpReport]:
        return self._system.submit_dump(
            output,
            replace_confirmed=replace_confirmed,
        )

    def load_help(self, input_path: str | Path) -> str:
        return load_help_command(input_path=input_path, db_path=self._db_path)


def _empty_ok(operation: Callable[[], list[_ItemT]]) -> list[_ItemT]:
    """Convert core's empty-result signal into the empty collection."""

    try:
        return operation()
    except EmptyResultError:
        return []


__all__ = ["CORE_DOMAIN_ACTIONS", "TuiDomainActions"]
