"""Thread, channel membership, list, and rename behavior for TautClient."""

from __future__ import annotations

from simplebroker import Queue, open_broker

from taut import addressing
from taut._exceptions import (
    EmptyResultError,
    MembershipError,
    NotFoundError,
    TautError,
    ThreadNameError,
)
from taut.state import ChannelRenameRow, MembershipRow, ThreadRow

from ._base import _ClientBase, _incomplete_channel_rename_message
from ._models import Message, Thread


class ThreadsMixin(_ClientBase):
    def joined_thread_names(self) -> tuple[str, ...]:
        """Return this member's joined chat-thread names without side effects.

        State returns memberships in lexical thread order.  Keep that order as
        the public deterministic contract used by long-lived extensions for
        resource reconciliation ([TAUT-8.3]).
        """

        resolved = self._resolve_member(create=False, _touch_activity=False)
        member = self._require_member(resolved)
        return tuple(
            row["thread"] for row in self._state.list_memberships(member["member_id"])
        )

    def join(
        self,
        thread: str,
        *,
        persona: str | None = None,
        new: bool = False,
    ) -> Message:
        """Join a channel, creating it if needed."""

        thread = addressing.validate_chat_thread_name(thread, allow_subthread=False)
        self._ensure_no_incomplete_channel_rename()
        resolved = self._resolve_member(create=True, force_new=new, persona=persona)
        member = self._require_member(resolved)
        queue = self.queue(thread)
        ts = queue.generate_timestamp()
        existing_thread = self._state.get_thread(thread)
        created_thread = existing_thread is None
        if created_thread:
            self._state.upsert_thread(
                name=thread,
                kind="channel",
                parent=None,
                origin_ts=None,
                created_by=member["member_id"],
                meta={},
                created_ts=ts,
            )
            notice_text = f"{member['display_name']} created #{thread}"
        else:
            assert existing_thread is not None
            if existing_thread["kind"] != "channel":
                raise ThreadNameError(f"not a channel: {thread}")
            notice_text = f"{member['display_name']} joined"
        self._state.add_membership(
            thread=thread,
            member_id=member["member_id"],
            joined_ts=ts,
            last_seen_ts=ts,
        )
        if persona is not None:
            updated = self._state.update_member_persona(member["member_id"], persona)
            if updated is not None:
                member = updated
        message = self._write_message(
            queue=queue,
            thread=thread,
            from_id=member["member_id"],
            from_name=member["display_name"],
            kind="notice",
            text=notice_text,
            notify_mentions=False,
        )
        self._advance_sender_if_no_intervening(
            queue=queue,
            thread=thread,
            member_id=member["member_id"],
            prior_cursor=ts,
            own_message_ts=message.ts,
        )
        return message

    def leave(self, thread: str) -> Message:
        thread = addressing.validate_chat_thread_name(thread, allow_subthread=True)
        self._ensure_no_incomplete_channel_rename()
        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        if self._state.get_thread(thread) is None:
            raise NotFoundError(f"thread not found: {thread}")
        if not self._state.remove_membership(
            thread=thread, member_id=member["member_id"]
        ):
            raise MembershipError(
                f"{member['display_name']} is not a member of {thread}"
            )
        queue = self.queue(thread)
        return self._write_message(
            queue=queue,
            thread=thread,
            from_id=member["member_id"],
            from_name=member["display_name"],
            kind="notice",
            text=f"{member['display_name']} left",
            notify_mentions=False,
        )

    def list_threads(self, *, all_threads: bool = False) -> list[Thread]:
        self._ensure_no_incomplete_channel_rename()
        resolved = self._resolve_member(create=False, allow_guest=True)
        if all_threads or resolved.row is None:
            rows = self._state.list_threads()
            member_id = resolved.row["member_id"] if resolved.row else None
            memberships = self._state.list_memberships(member_id) if member_id else []
        else:
            memberships = self._state.list_memberships(resolved.row["member_id"])
            thread_names = {row["thread"] for row in memberships}
            rows = [
                row for row in self._state.list_threads() if row["name"] in thread_names
            ]
        by_thread = {row["thread"]: row for row in memberships}
        result = [
            self._thread_from_row(row, by_thread.get(row["name"])) for row in rows
        ]
        if not all_threads and not any(thread.unread for thread in result):
            raise EmptyResultError("no unread threads")
        return result

    def rename_channel(self, old_name: str, new_name: str) -> Thread:
        old_name = addressing.validate_chat_thread_name(old_name, allow_subthread=False)
        new_name = addressing.validate_chat_thread_name(new_name, allow_subthread=False)
        incomplete = self._state.incomplete_channel_renames()
        if incomplete:
            marker = incomplete[0]
            if marker["old_name"] == old_name and marker["new_name"] == new_name:
                return self._resume_channel_rename(marker)
            raise TautError(_incomplete_channel_rename_message(marker))
        old = self._state.get_thread(old_name)
        if old is None or old["kind"] != "channel":
            raise NotFoundError(f"channel not found: {old_name}")
        if self._state.get_thread(new_name) is not None:
            raise ValueError(f"target channel already exists: {new_name}")
        rows = [
            row
            for row in self._state.list_threads(include_internal=True)
            if row["name"] == old_name or row["parent"] == old_name
        ]
        affected = [
            {
                "old": row["name"],
                "new": new_name
                if row["name"] == old_name
                else f"{new_name}.{row['origin_ts']}",
            }
            for row in sorted(
                rows, key=lambda item: (item["parent"] is not None, item["name"])
            )
        ]
        started_ts = self._meta_queue.generate_timestamp()
        with open_broker(self.target, config=self.config) as broker:
            for item in affected:
                if broker.queue_exists(item["new"]):
                    raise ValueError(f"target queue already exists: {item['new']}")
            self._state.start_channel_rename(
                old_name=old_name,
                new_name=new_name,
                affected=affected,
                started_ts=started_ts,
            )
            for item in affected:
                if broker.queue_exists(item["old"]):
                    broker.rename_queue(
                        item["old"],
                        item["new"],
                        retarget_aliases=False,
                    )
        updated_ts = self._meta_queue.generate_timestamp()
        self._state.apply_channel_rename_state(
            old_name=old_name,
            new_name=new_name,
            affected=affected,
            updated_ts=updated_ts,
        )
        renamed = self._state.get_thread(new_name)
        if renamed is None:
            raise RuntimeError("renamed channel could not be read back")
        return self._thread_from_row(renamed, None)

    def _resume_channel_rename(self, marker: ChannelRenameRow) -> Thread:
        """Finish an interrupted rename from its marker ([IAN-8.3]).

        The marker's affected list is authoritative — queues may already
        reflect partial progress — so each item's action is decided by
        which of its queue names exist instead of the fresh path's global
        target precheck (which would refuse resume's own progress):

        - old exists, new missing: the normal pending item; rename it.
        - old missing, new exists: already completed; skip.
        - both missing: the normal broker state for an empty channel or
          drained sub-thread (queues exist only while non-empty); skip
          silently, exactly as the fresh path's ``queue_exists(old)``
          guard does, and let the sidecar apply converge the registry.
        - both exist: a foreign queue occupies the target; abort loudly
          before mutating anything ([IAN-8.3] "loudly reportable").
        """

        affected = marker["affected"]
        with open_broker(self.target, config=self.config) as broker:
            pending: list[dict[str, str]] = []
            for item in affected:
                old_exists = broker.queue_exists(item["old"])
                if old_exists and broker.queue_exists(item["new"]):
                    raise TautError(
                        "cannot finish channel rename "
                        f"{marker['old_name']} -> {marker['new_name']}: "
                        f"target queue already exists: {item['new']}"
                    )
                if old_exists:
                    pending.append(item)
            for item in pending:
                broker.rename_queue(item["old"], item["new"], retarget_aliases=False)
        updated_ts = self._meta_queue.generate_timestamp()
        self._state.apply_channel_rename_state(
            old_name=marker["old_name"],
            new_name=marker["new_name"],
            affected=affected,
            updated_ts=updated_ts,
        )
        renamed = self._state.get_thread(marker["new_name"])
        if renamed is None:
            raise RuntimeError("renamed channel could not be read back")
        return self._thread_from_row(renamed, None)

    def _thread_from_row(
        self,
        row: ThreadRow,
        membership: MembershipRow | None,
    ) -> Thread:
        queue = self.queue(row["name"])
        unread_count = self._unread_count(queue, membership)
        raw_members = row["meta"].get("members")
        members: tuple[str, ...] = ()
        if isinstance(raw_members, list) and all(
            isinstance(item, str) for item in raw_members
        ):
            members = tuple(raw_members)
        display_name: str | None = None
        if row["kind"] == "dm":
            distinct_members = set(members)
            if len(members) == 2 and len(distinct_members) == 2:
                visible_ids = list(members)
                if membership is not None and membership["member_id"] in visible_ids:
                    visible_ids.remove(membership["member_id"])
                visible_rows = [self._state.get_member(item) for item in visible_ids]
                if all(item is not None for item in visible_rows):
                    display_name = "DM with " + ", ".join(
                        item["display_name"]
                        for item in visible_rows
                        if item is not None
                    )
            if display_name is None:
                display_name = f"DM {row['name']} (participants unavailable)"
        return Thread(
            name=row["name"],
            kind=row["kind"],
            parent=row["parent"],
            unread=unread_count > 0,
            last_ts=self._last_message_ts(queue),
            unread_count=unread_count,
            members=members,
            display_name=display_name,
        )

    def _last_message_ts(self, queue: Queue) -> int | None:
        return queue.latest_pending_timestamp()

    def _unread_count(
        self,
        queue: Queue,
        membership: MembershipRow | None,
        *,
        cap: int = 1000,
    ) -> int:
        if membership is None:
            return 0
        rows = queue.peek_many(
            cap,
            with_timestamps=True,
            after_timestamp=membership["last_seen_ts"],
        )
        return len(rows)
