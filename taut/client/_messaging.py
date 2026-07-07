"""Chat message, read, log, and direct-message behavior for TautClient."""

from __future__ import annotations

from collections import deque
from typing import Any, cast

from simplebroker import Queue
from simplebroker.ext import TimestampError, TimestampGenerator

from taut import addressing
from taut._constants import MESSAGE_ID_RE
from taut._exceptions import (
    AmbiguousMessageError,
    EmptyResultError,
    MembershipError,
    NotFoundError,
    ThreadNameError,
)
from taut.envelope import encode_envelope
from taut.state import MemberRow, MembershipRow

from ._base import _ClientBase
from ._codec import message_from_body
from ._models import Message


class MessagingMixin(_ClientBase):
    def say(self, target: str, text: str) -> Message:
        address = addressing.parse_target(target, allow_dm=True)
        self._ensure_no_incomplete_channel_rename()
        if address.kind == "dm":
            if address.route_key is None:
                raise ThreadNameError("direct message target missing route")
            if self._state.get_member_by_route_key(address.route_key) is None:
                raise NotFoundError(f"member not found: @{address.raw_route}")
            resolved = self._resolve_member(create=True)
            member = self._require_member(resolved)
            return self._say_dm(address, member, text)
        if address.thread is None:
            raise ThreadNameError(f"invalid target: {target}")
        if self._state.get_thread(address.thread) is None:
            raise NotFoundError(f"thread not found: {address.thread}")
        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        return self._say_chat_thread(address.thread, member, text)

    def reply(self, thread: str, msg_id: str, text: str) -> Message:
        thread = addressing.validate_chat_thread_name(thread, allow_subthread=False)
        self._ensure_no_incomplete_channel_rename()
        if self._state.get_thread(thread) is None:
            raise NotFoundError(f"thread not found: {thread}")
        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        parent_membership = self._state.get_membership(
            thread=thread, member_id=member["member_id"]
        )
        if parent_membership is None:
            raise MembershipError(
                f"{member['display_name']} is not a member of {thread}"
            )
        origin = self._resolve_message_id(thread, msg_id)
        child_thread = f"{thread}.{origin}"
        child_queue = self.queue(child_thread)
        ts = child_queue.generate_timestamp()
        if self._state.get_thread(child_thread) is None:
            self._state.upsert_thread(
                name=child_thread,
                kind="subthread",
                parent=thread,
                origin_ts=origin,
                created_by=member["member_id"],
                meta={},
                created_ts=ts,
            )
        membership = self._state.get_membership(
            thread=child_thread, member_id=member["member_id"]
        )
        if membership is None:
            self._state.add_membership(
                thread=child_thread,
                member_id=member["member_id"],
                joined_ts=ts,
                last_seen_ts=ts,
            )
            caught_up = True
        else:
            caught_up = not child_queue.has_pending(
                after_timestamp=membership["last_seen_ts"]
            )
        message = self._insert_message(
            queue=child_queue,
            thread=child_thread,
            from_id=member["member_id"],
            from_name=member["display_name"],
            kind="message",
            text=text,
            ts=ts,
            notify_mentions=True,
        )
        if caught_up:
            self._state.advance_cursor(
                thread=child_thread,
                member_id=member["member_id"],
                seen_ts=message.ts,
            )
        return message

    def read(self, thread: str | None = None) -> list[Message]:
        return self.read_unread(thread)

    def read_unread(self, thread: str | None = None) -> list[Message]:
        self._ensure_no_incomplete_channel_rename()
        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        memberships: list[MembershipRow]
        if thread is not None:
            thread = addressing.validate_chat_thread_name(thread, allow_subthread=True)
            membership = self._state.get_membership(
                thread=thread, member_id=member["member_id"]
            )
            if membership is None:
                membership = self._implicit_subthread_membership(thread, member)
            memberships = [membership]
        else:
            memberships = self._state.list_memberships(member["member_id"])
        messages: list[Message] = []
        for membership in memberships:
            row = self._state.get_thread(membership["thread"])
            if row is None or row["kind"] == "notification":
                continue
            queue = self.queue(membership["thread"])
            raw_messages = cast(
                list[tuple[str, int]],
                queue.peek_many(
                    1000,
                    with_timestamps=True,
                    after_timestamp=membership["last_seen_ts"],
                ),
            )
            for body, ts in raw_messages:
                message = message_from_body(membership["thread"], body, ts)
                messages.append(message)
                self._state.advance_cursor(
                    thread=membership["thread"],
                    member_id=member["member_id"],
                    seen_ts=ts,
                )
        if not messages:
            raise EmptyResultError("nothing unread")
        return messages

    def log(
        self,
        thread: str,
        *,
        since: str | int | None = None,
        limit: int | None = None,
    ) -> list[Message]:
        thread = addressing.validate_chat_thread_name(thread, allow_subthread=True)
        self._ensure_no_incomplete_channel_rename()
        row = self._state.get_thread(thread)
        if row is None:
            raise NotFoundError(f"thread not found: {thread}")
        if row["kind"] == "notification":
            raise ThreadNameError("notification queues are read with inbox")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        after_timestamp = self._parse_since(since)
        queue = self.queue(thread)
        messages: list[Message] | deque[Message]
        if limit is None:
            messages = []
        else:
            messages = deque(maxlen=limit)
        generator = queue.peek_generator(
            with_timestamps=True,
            after_timestamp=after_timestamp,
        )
        for result in generator:
            body, ts = cast(tuple[str, int], result)
            messages.append(message_from_body(thread, body, ts))
        messages = sorted(messages, key=lambda message: message.ts)
        if not messages:
            raise EmptyResultError("empty")
        return messages

    def _say_chat_thread(
        self,
        thread: str,
        member: MemberRow,
        text: str,
    ) -> Message:
        if self._state.get_thread(thread) is None:
            raise NotFoundError(f"thread not found: {thread}")
        membership = self._state.get_membership(
            thread=thread, member_id=member["member_id"]
        )
        if membership is None:
            raise MembershipError(
                f"{member['display_name']} is not a member of {thread}"
            )
        queue = self.queue(thread)
        caught_up = not queue.has_pending(after_timestamp=membership["last_seen_ts"])
        message = self._write_message(
            queue=queue,
            thread=thread,
            from_id=member["member_id"],
            from_name=member["display_name"],
            kind="message",
            text=text,
            notify_mentions=True,
        )
        if caught_up:
            self._state.advance_cursor(
                thread=thread,
                member_id=member["member_id"],
                seen_ts=message.ts,
            )
        return message

    def _say_dm(
        self,
        address: addressing.TargetAddress,
        member: MemberRow,
        text: str,
    ) -> Message:
        if address.route_key is None:
            raise ThreadNameError("direct message target missing route")
        target = self._state.get_member_by_route_key(address.route_key)
        if target is None:
            raise NotFoundError(f"member not found: @{address.raw_route}")
        if target["member_id"] == member["member_id"]:
            raise ValueError("cannot send a direct message to yourself")
        thread = addressing.dm_queue_name(member["member_id"], target["member_id"])
        queue = self.queue(thread)
        ts = queue.generate_timestamp()
        existing = self._state.get_thread(thread)
        created_thread = existing is None
        participants = tuple(sorted((member["member_id"], target["member_id"])))
        if created_thread:
            self._state.upsert_thread(
                name=thread,
                kind="dm",
                parent=None,
                origin_ts=None,
                created_by=member["member_id"],
                meta={"members": list(participants)},
                created_ts=ts,
            )
        actor_membership = self._state.get_membership(
            thread=thread, member_id=member["member_id"]
        )
        if actor_membership is None:
            actor_membership = self._state.add_membership(
                thread=thread,
                member_id=member["member_id"],
                joined_ts=ts,
                last_seen_ts=ts,
            )
            caught_up = True
        else:
            caught_up = not queue.has_pending(
                after_timestamp=actor_membership["last_seen_ts"]
            )
        if (
            self._state.get_membership(thread=thread, member_id=target["member_id"])
            is None
        ):
            self._state.add_membership(
                thread=thread,
                member_id=target["member_id"],
                joined_ts=ts,
                last_seen_ts=0,
            )
        message = self._insert_message(
            queue=queue,
            thread=thread,
            from_id=member["member_id"],
            from_name=member["display_name"],
            kind="message",
            text=text,
            ts=ts,
            notify_mentions=True,
        )
        if caught_up:
            self._state.advance_cursor(
                thread=thread,
                member_id=member["member_id"],
                seen_ts=message.ts,
            )
        if created_thread:
            self._write_notification(
                to_id=target["member_id"],
                payload={
                    "type": "dm_started",
                    "to_id": target["member_id"],
                    "actor_id": member["member_id"],
                    "actor_name": member["display_name"],
                    "thread": thread,
                    "message_ts": message.ts,
                },
            )
        return message

    def _implicit_subthread_membership(
        self,
        thread: str,
        member: MemberRow,
    ) -> MembershipRow:
        row = self._state.get_thread(thread)
        if row is None or row["parent"] is None:
            raise MembershipError(
                f"{member['display_name']} is not a member of {thread}"
            )
        parent_membership = self._state.get_membership(
            thread=row["parent"],
            member_id=member["member_id"],
        )
        if parent_membership is None:
            raise MembershipError(
                f"{member['display_name']} is not a member of {thread}"
            )
        joined_ts = self._meta_queue.generate_timestamp()
        return self._state.add_membership(
            thread=thread,
            member_id=member["member_id"],
            joined_ts=joined_ts,
            last_seen_ts=0,
        )

    def _write_message(
        self,
        *,
        queue: Queue,
        thread: str,
        from_id: str,
        from_name: str,
        kind: str,
        text: str,
        notify_mentions: bool,
    ) -> Message:
        ts = queue.generate_timestamp()
        return self._insert_message(
            queue=queue,
            thread=thread,
            from_id=from_id,
            from_name=from_name,
            kind=kind,
            text=text,
            ts=ts,
            notify_mentions=notify_mentions,
        )

    def _insert_message(
        self,
        *,
        queue: Queue,
        thread: str,
        from_id: str,
        from_name: str,
        kind: str,
        text: str,
        ts: int,
        notify_mentions: bool,
    ) -> Message:
        body = encode_envelope(
            from_id=from_id,
            from_name=from_name,
            kind=cast(Any, kind),
            text=text,
        )
        queue.insert_messages([(body, ts)])
        message = message_from_body(thread, body, ts)
        if notify_mentions and kind == "message":
            self._write_mention_notifications(message, text)
        return message

    def _write_mention_notifications(self, message: Message, text: str) -> None:
        if message.from_id is None:
            return
        mentions = addressing.mentioned_route_keys(text)
        if not mentions:
            return
        participants: set[str] | None = None
        if addressing.classify_registered_queue(message.thread) == "dm":
            # [IAN-5.2]: DM mentions notify only the two participants; a DM
            # must not leak its existence or queue name to non-participants.
            participants = self._dm_participants(message.thread)
            if participants is None:
                self.last_notification_warnings.append(
                    "mention notifications suppressed: direct-message "
                    f"registry row for {message.thread} lacks participant "
                    "metadata"
                )
                return
        for key, matched in mentions:
            target = self._state.get_member_by_route_key(key)
            if target is None or target["member_id"] == message.from_id:
                continue
            if participants is not None and target["member_id"] not in participants:
                continue
            self._write_notification(
                to_id=target["member_id"],
                payload={
                    "type": "mention",
                    "to_id": target["member_id"],
                    "actor_id": message.from_id,
                    "actor_name": message.from_name,
                    "thread": message.thread,
                    "message_ts": message.ts,
                    "matched": matched,
                },
            )

    def _dm_participants(self, thread: str) -> set[str] | None:
        """Return the DM participant ids, or None when the registry row is
        missing or its ``members`` meta is malformed ([IAN-5.2]).

        A direct message has exactly two distinct participants ([IAN-6.4]);
        any other cardinality is corrupt metadata and must scope everyone
        out — treating a 3+-member list as valid would let a corrupted row
        leak the DM's existence to a non-participant.
        """

        row = self._state.get_thread(thread)
        if row is None:
            return None
        raw_members = row["meta"].get("members")
        if not isinstance(raw_members, list) or not all(
            isinstance(item, str) for item in raw_members
        ):
            return None
        participants = set(raw_members)
        if len(raw_members) != 2 or len(participants) != 2:
            return None
        return participants

    def _resolve_message_id(self, thread: str, msg_id: str) -> int:
        queue = self.queue(thread)
        if MESSAGE_ID_RE.fullmatch(msg_id):
            exact = int(msg_id)
            found = queue.peek_one(exact_timestamp=exact, with_timestamps=True)
            if found is None:
                raise NotFoundError(f"message not found: {msg_id}")
            return exact
        if len(msg_id) < 4 or not msg_id.isdigit():
            raise NotFoundError("message id suffix must be at least 4 digits")
        recent: deque[int] = deque(maxlen=1000)
        for result in queue.peek_generator(with_timestamps=True):
            _body, ts = cast(tuple[str, int], result)
            recent.append(ts)
        matches = [ts for ts in recent if str(ts).endswith(msg_id)]
        if not matches:
            raise NotFoundError(
                f"message not found in the most recent 1,000 messages of {thread}; "
                "use the full 19-digit id"
            )
        if len(matches) > 1:
            raise AmbiguousMessageError(
                "ambiguous message id suffix: " + ", ".join(str(ts) for ts in matches)
            )
        return matches[0]

    def _parse_since(self, since: str | int | None) -> int | None:
        if since is None:
            return None
        if isinstance(since, int):
            return since
        try:
            return TimestampGenerator.validate(since)
        except TimestampError as exc:
            raise ValueError(str(exc)) from exc
