"""Public TautClient API.

Spec references:
- docs/specs/02-taut-core.md [TAUT-3], [TAUT-4], [TAUT-5], [TAUT-7], [TAUT-8.3]
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from simplebroker import (
    BrokerTarget,
    Queue,
    resolve_broker_target,
    target_for_directory,
)
from simplebroker.ext import TimestampError, TimestampGenerator

import taut.identity as identity
import taut.schema as schema
from taut._constants import (
    HANDLE_RE,
    MESSAGE_ID_RE,
    META_QUEUE_NAME,
    NO_DATABASE_MESSAGE,
    ROOM_NAME_RE,
    load_config,
    validate_handle,
)
from taut._exceptions import (
    AmbiguousMessageError,
    BackendNotSupportedError,
    EmptyResultError,
    IdentityError,
    MembershipError,
    NotFoundError,
    NotInitializedError,
    ThreadNameError,
    TokenError,
)
from taut.envelope import DecodedEnvelope, decode_envelope, encode_envelope

if TYPE_CHECKING:
    from taut.watcher import TautWatcher


@dataclass(frozen=True, slots=True)
class Member:
    """Public member object."""

    handle: str
    kind: str
    presence: str
    last_active_ts: int
    persona: str | None = None
    token: str | None = None
    explain: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Thread:
    """Public thread object."""

    name: str
    parent: str | None
    unread: bool
    last_ts: int | None
    unread_count: int = 0


@dataclass(frozen=True, slots=True)
class Message:
    """Public message object."""

    thread: str
    ts: int
    from_handle: str
    kind: str
    text: str
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class InitResult:
    """Result of ``taut init``."""

    db: str
    created: bool


@dataclass(slots=True)
class _ResolvedMember:
    row: schema.MemberRow | None
    capture: identity.IdentityCapture
    created: bool = False
    created_token: str | None = None
    candidates: list[tuple[schema.MemberRow, list[str]]] | None = None
    rule: str = "guest"


class TautClient:
    """Embedding surface for taut.

    The CLI is a renderer over this class; command semantics live here.
    """

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        as_handle: str | None = None,
        token: str | None = None,
        identity_capture: identity.IdentityCapture | None = None,
    ) -> None:
        self.config = load_config()
        self.target = self._resolve_target(db_path)
        self.as_handle = as_handle or os.environ.get("TAUT_AS")
        self.token = token or os.environ.get("TAUT_TOKEN")
        self.identity_capture = identity_capture
        self.last_created_member: Member | None = None
        self.last_candidates: list[tuple[str, list[str]]] = []
        self._meta_queue = self.queue(META_QUEUE_NAME)
        schema.ensure_schema(self._meta_queue)

    @classmethod
    def init(
        cls,
        *,
        db_path: str | Path | None = None,
    ) -> InitResult:
        """Create a taut database and install sidecar schema."""

        config = load_config()
        explicit = db_path or os.environ.get("TAUT_DB")
        if explicit is not None:
            path = Path(explicit).expanduser()
            target: BrokerTarget | str = str(path)
            db_file = path
        else:
            target_obj = target_for_directory(Path.cwd(), config=config)
            if target_obj.backend_name != "sqlite":
                raise BackendNotSupportedError(
                    f"backend '{target_obj.backend_name}' is not supported in taut v0.1"
                )
            target = target_obj
            db_file = Path(target_obj.target)
        created = not db_file.exists()
        queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
        schema.ensure_schema(queue)
        return InitResult(db=str(db_file), created=created)

    def queue(self, name: str, *, persistent: bool = False) -> Queue:
        """Return a queue bound to this client's resolved target."""

        return Queue(
            name, db_path=self.target, persistent=persistent, config=self.config
        )

    def whoami(self, *, explain: bool = False) -> Member:
        resolved = self._resolve_member(create=False)
        if resolved.row is None:
            raise IdentityError("unrecognized caller")
        member = self._member_from_row(
            resolved.row,
            capture=resolved.capture,
            explain=identity.explain_capture(resolved.capture, resolved.rule)
            if explain
            else None,
        )
        return member

    def join(
        self,
        thread: str,
        *,
        persona: str | None = None,
        new: bool = False,
    ) -> Message:
        """Join a room, creating it if needed."""

        self._validate_thread_name(thread, allow_subthread=False)
        resolved = self._resolve_member(create=True, force_new=new, persona=persona)
        member = self._require_member(resolved)
        queue = self.queue(thread)
        ts = queue.generate_timestamp()
        existing_thread = schema.get_thread(self._meta_queue, thread)
        created_thread = existing_thread is None
        if created_thread:
            schema.upsert_thread(
                self._meta_queue,
                name=thread,
                parent=None,
                origin_ts=None,
                created_by=member["handle"],
                created_ts=ts,
            )
            notice_text = f"{member['handle']} created #{thread}"
        else:
            notice_text = f"{member['handle']} joined"
        schema.add_membership(
            self._meta_queue,
            thread=thread,
            member=member["handle"],
            joined_ts=ts,
            last_seen_ts=ts,
        )
        if persona is not None:
            updated = schema.update_member_persona(
                self._meta_queue, member["handle"], persona
            )
            if updated is not None:
                member = updated
        return self._insert_message(
            queue=queue,
            thread=thread,
            from_handle=member["handle"],
            kind="notice",
            text=notice_text,
            ts=ts,
        )

    def leave(self, thread: str) -> Message:
        self._validate_thread_name(thread, allow_subthread=True)
        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        if schema.get_thread(self._meta_queue, thread) is None:
            raise NotFoundError(f"thread not found: {thread}")
        if not schema.remove_membership(
            self._meta_queue, thread=thread, member=member["handle"]
        ):
            raise MembershipError(f"{member['handle']} is not a member of {thread}")
        queue = self.queue(thread)
        return self._write_message(
            queue=queue,
            thread=thread,
            from_handle=member["handle"],
            kind="notice",
            text=f"{member['handle']} left",
        )

    def say(self, thread: str, text: str) -> Message:
        self._validate_thread_name(thread, allow_subthread=True)
        resolved = self._resolve_member(create=True)
        member = self._require_member(resolved)
        if schema.get_thread(self._meta_queue, thread) is None:
            raise NotFoundError(f"thread not found: {thread}")
        membership = schema.get_membership(
            self._meta_queue, thread=thread, member=member["handle"]
        )
        if membership is None:
            raise MembershipError(f"{member['handle']} is not a member of {thread}")
        queue = self.queue(thread)
        # [TAUT-7.4] accepts the check-then-write race as cosmetic; do not lock.
        caught_up = not queue.has_pending(after_timestamp=membership["last_seen_ts"])
        message = self._write_message(
            queue=queue,
            thread=thread,
            from_handle=member["handle"],
            kind="message",
            text=text,
        )
        if caught_up:
            schema.advance_cursor(
                self._meta_queue,
                thread=thread,
                member=member["handle"],
                seen_ts=message.ts,
            )
        return message

    def reply(self, thread: str, msg_id: str, text: str) -> Message:
        self._validate_thread_name(thread, allow_subthread=False)
        resolved = self._resolve_member(create=True)
        member = self._require_member(resolved)
        if schema.get_thread(self._meta_queue, thread) is None:
            raise NotFoundError(f"thread not found: {thread}")
        parent_membership = schema.get_membership(
            self._meta_queue, thread=thread, member=member["handle"]
        )
        if parent_membership is None:
            raise MembershipError(f"{member['handle']} is not a member of {thread}")
        origin = self._resolve_message_id(thread, msg_id)
        child_thread = f"{thread}.{origin}"
        child_queue = self.queue(child_thread)
        ts = child_queue.generate_timestamp()
        if schema.get_thread(self._meta_queue, child_thread) is None:
            schema.upsert_thread(
                self._meta_queue,
                name=child_thread,
                parent=thread,
                origin_ts=origin,
                created_by=member["handle"],
                created_ts=ts,
            )
        membership = schema.get_membership(
            self._meta_queue, thread=child_thread, member=member["handle"]
        )
        if membership is None:
            schema.add_membership(
                self._meta_queue,
                thread=child_thread,
                member=member["handle"],
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
            from_handle=member["handle"],
            kind="message",
            text=text,
            ts=ts,
        )
        if caught_up:
            schema.advance_cursor(
                self._meta_queue,
                thread=child_thread,
                member=member["handle"],
                seen_ts=message.ts,
            )
        return message

    def read(self, thread: str | None = None) -> list[Message]:
        return self.read_unread(thread)

    def read_unread(self, thread: str | None = None) -> list[Message]:
        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        memberships: list[schema.MembershipRow]
        if thread is not None:
            self._validate_thread_name(thread, allow_subthread=True)
            membership = schema.get_membership(
                self._meta_queue, thread=thread, member=member["handle"]
            )
            if membership is None:
                membership = self._implicit_subthread_membership(thread, member)
            memberships = [membership]
        else:
            memberships = schema.list_memberships(self._meta_queue, member["handle"])
        messages: list[Message] = []
        for membership in memberships:
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
                message = self._message_from_body(membership["thread"], body, ts)
                messages.append(message)
                schema.advance_cursor(
                    self._meta_queue,
                    thread=membership["thread"],
                    member=member["handle"],
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
        self._validate_thread_name(thread, allow_subthread=True)
        if schema.get_thread(self._meta_queue, thread) is None:
            raise NotFoundError(f"thread not found: {thread}")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        after_timestamp = self._parse_since(since)
        queue = self.queue(thread)
        messages: list[Message] | deque[Message]
        messages = [] if limit is None else deque(maxlen=limit)
        generator = queue.peek_generator(
            with_timestamps=True,
            after_timestamp=after_timestamp,
        )
        for result in generator:
            body, ts = cast(tuple[str, int], result)
            messages.append(self._message_from_body(thread, body, ts))
        messages = list(messages)
        if not messages:
            raise EmptyResultError("empty")
        return messages

    def list_threads(self, *, all_threads: bool = False) -> list[Thread]:
        resolved = self._resolve_member(create=False, allow_guest=True)
        if all_threads or resolved.row is None:
            rows = schema.list_threads(self._meta_queue)
            member_handle = resolved.row["handle"] if resolved.row else None
            memberships = (
                schema.list_memberships(self._meta_queue, member_handle)
                if member_handle
                else []
            )
        else:
            memberships = schema.list_memberships(
                self._meta_queue, resolved.row["handle"]
            )
            thread_names = {row["thread"] for row in memberships}
            rows = [
                row
                for row in schema.list_threads(self._meta_queue)
                if row["name"] in thread_names
            ]
        by_thread = {row["thread"]: row for row in memberships}
        result = [
            self._thread_from_row(row, by_thread.get(row["name"])) for row in rows
        ]
        if not all_threads and not any(thread.unread for thread in result):
            raise EmptyResultError("no unread threads")
        return result

    def who(self, thread: str | None = None) -> list[Member]:
        self._resolve_member(create=False, allow_guest=True)
        if thread is not None:
            self._validate_thread_name(thread, allow_subthread=True)
            if schema.get_thread(self._meta_queue, thread) is None:
                raise NotFoundError(f"thread not found: {thread}")
            rows = schema.list_thread_members(self._meta_queue, thread)
        else:
            rows = schema.list_members(self._meta_queue)
        return [self._member_from_row(row) for row in rows]

    def rejoin(self, handle: str | None = None, *, token: str | None = None) -> Member:
        if token is not None and self.token is not None:
            raise IdentityError("provide exactly one rejoin selector")
        if handle is not None and (token is not None or self.token is not None):
            raise IdentityError("provide exactly one of handle or token")
        if handle is None and token is None:
            if self.as_handle and self.token:
                raise IdentityError("provide exactly one rejoin selector")
            if self.as_handle:
                handle = self.as_handle
            elif self.token:
                token = self.token
            else:
                raise IdentityError("provide exactly one of handle or token")
        capture = self._capture()
        if capture.anchor is None or capture.anchor.start_time is None:
            raise IdentityError("current process chain has no rejoinable anchor")
        selector = (
            schema.get_member_by_token(self._meta_queue, token)
            if token is not None
            else schema.get_member(self._meta_queue, cast(str, handle))
        )
        if selector is None:
            raise NotFoundError("member not found")
        members = schema.list_members(self._meta_queue)
        claimant = identity.anchor_claimant(
            members,
            host_id=capture.host.host_id,
            anchor=capture.anchor,
        )
        if claimant is not None and claimant["handle"] != selector["handle"]:
            raise IdentityError(
                f"current anchor already belongs to {claimant['handle']}"
            )
        active_ts = self._meta_queue.generate_timestamp()
        updated = schema.update_member_anchor(
            self._meta_queue,
            handle=selector["handle"],
            host_id=capture.host.host_id,
            host_label=capture.host.host_label,
            anchor_pid=capture.anchor.pid,
            anchor_start_time=capture.anchor.start_time,
            fingerprint=identity.fingerprint_for_process(capture.anchor) or "{}",
            active_ts=active_ts,
        )
        return self._member_from_row(updated)

    def watch(
        self,
        handler: Callable[[Message], None],
        *,
        threads: list[str] | None = None,
    ) -> TautWatcher:
        from taut.watcher import TautWatcher

        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        return TautWatcher(self, member["handle"], handler, threads=threads)

    def _resolve_target(self, db_path: str | Path | None) -> BrokerTarget | str:
        explicit = db_path or os.environ.get("TAUT_DB")
        if explicit is not None:
            path = Path(explicit).expanduser()
            if not path.exists():
                raise NotInitializedError(NO_DATABASE_MESSAGE)
            return str(path)
        target = resolve_broker_target(Path.cwd(), config=self.config)
        if target is None:
            raise NotInitializedError(NO_DATABASE_MESSAGE)
        if target.backend_name != "sqlite":
            raise BackendNotSupportedError(
                f"backend '{target.backend_name}' is not supported in taut v0.1"
            )
        if not Path(target.target).exists():
            raise NotInitializedError(NO_DATABASE_MESSAGE)
        return target

    def _resolve_member(
        self,
        *,
        create: bool,
        force_new: bool = False,
        persona: str | None = None,
        allow_guest: bool = False,
    ) -> _ResolvedMember:
        self.last_created_member = None
        self.last_candidates = []
        capture = self._capture()
        active_ts: int | None = None

        def next_active_ts() -> int:
            nonlocal active_ts
            if active_ts is None:
                active_ts = self._meta_queue.generate_timestamp()
            return active_ts

        explicit = self.as_handle
        if explicit:
            validate_handle(explicit)
            row = schema.get_member(self._meta_queue, explicit)
            if row is None:
                if not create and not allow_guest:
                    raise NotFoundError(f"member not found: {explicit}")
                if not create:
                    return _ResolvedMember(None, capture, rule="guest")
                row = self._create_member(
                    capture,
                    handle=explicit,
                    persona=persona,
                    allow_anchor=True,
                    active_ts=next_active_ts(),
                )
                return self._created_resolution(row, capture, "explicit --as")
            schema.update_member_activity(
                self._meta_queue, row["handle"], next_active_ts()
            )
            if persona is not None:
                row = (
                    schema.update_member_persona(
                        self._meta_queue, row["handle"], persona
                    )
                    or row
                )
            return _ResolvedMember(row, capture, rule="explicit --as")

        if self.token:
            row = schema.get_member_by_token(self._meta_queue, self.token)
            if row is None:
                raise TokenError("TAUT_TOKEN does not match a taut member")
            schema.update_member_activity(
                self._meta_queue, row["handle"], next_active_ts()
            )
            return _ResolvedMember(row, capture, rule="continuity token")

        members = schema.list_members(self._meta_queue)
        if not force_new:
            row = identity.match_anchor(capture, members)
            if row is not None:
                schema.update_member_activity(
                    self._meta_queue, row["handle"], next_active_ts()
                )
                if persona is not None:
                    row = (
                        schema.update_member_persona(
                            self._meta_queue, row["handle"], persona
                        )
                        or row
                    )
                return _ResolvedMember(row, capture, rule="nearest stored anchor")

        if capture.kind == "human" and not force_new:
            row = schema.get_member_by_uid(
                self._meta_queue,
                host_id=capture.host.host_id,
                uid=capture.uid,
            )
            if row is not None:
                schema.update_member_activity(
                    self._meta_queue, row["handle"], next_active_ts()
                )
                return _ResolvedMember(row, capture, rule="human uid fallback")
            if create:
                row = self._create_member(
                    capture,
                    handle=None,
                    persona=persona,
                    allow_anchor=False,
                    active_ts=next_active_ts(),
                )
                return self._created_resolution(row, capture, "human uid fallback")

        if not create:
            return _ResolvedMember(None, capture, rule="guest")

        candidates = identity.rank_candidates(capture, members)
        row = self._create_member(
            capture,
            handle=None,
            persona=persona,
            allow_anchor=True,
            active_ts=next_active_ts(),
        )
        resolved = self._created_resolution(row, capture, "new identity")
        resolved.candidates = candidates
        self.last_candidates = [
            (candidate["handle"], reasons) for candidate, reasons in candidates
        ]
        return resolved

    def _created_resolution(
        self,
        row: schema.MemberRow,
        capture: identity.IdentityCapture,
        rule: str,
    ) -> _ResolvedMember:
        member = self._member_from_row(row, capture=capture, token=row["token"])
        self.last_created_member = member
        return _ResolvedMember(
            row=row,
            capture=capture,
            created=True,
            created_token=row["token"],
            rule=rule,
        )

    def _create_member(
        self,
        capture: identity.IdentityCapture,
        *,
        handle: str | None,
        persona: str | None,
        allow_anchor: bool,
        active_ts: int,
    ) -> schema.MemberRow:
        taken = schema.handles_in_use(self._meta_queue)
        if handle is None:
            seed = (
                capture.anchor.basename if capture.anchor is not None else capture.login
            )
            fallback = "agent" if capture.kind == "agent" else "human"
            handle = identity.choose_handle(seed=seed, taken=taken, fallback=fallback)
        elif HANDLE_RE.fullmatch(handle) is None:
            raise IdentityError(f"invalid handle: {handle}")
        anchor = capture.anchor if allow_anchor and capture.kind == "agent" else None
        if anchor is not None:
            claimant = identity.anchor_claimant(
                schema.list_members(self._meta_queue),
                host_id=capture.host.host_id,
                anchor=anchor,
            )
            if claimant is not None and claimant["handle"] != handle:
                anchor = None
        meta = {"persona": persona} if persona is not None else {}
        return schema.insert_member(
            self._meta_queue,
            handle=handle,
            kind=capture.kind,
            uid=capture.uid,
            host_id=capture.host.host_id,
            host_label=capture.host.host_label,
            anchor_pid=anchor.pid if anchor is not None else None,
            anchor_start_time=anchor.start_time if anchor is not None else None,
            fingerprint=identity.fingerprint_for_process(anchor),
            token=identity.mint_token(),
            meta=meta,
            created_ts=active_ts,
        )

    def _implicit_subthread_membership(
        self,
        thread: str,
        member: schema.MemberRow,
    ) -> schema.MembershipRow:
        row = schema.get_thread(self._meta_queue, thread)
        if row is None or row["parent"] is None:
            raise MembershipError(f"{member['handle']} is not a member of {thread}")
        parent_membership = schema.get_membership(
            self._meta_queue,
            thread=row["parent"],
            member=member["handle"],
        )
        if parent_membership is None:
            raise MembershipError(f"{member['handle']} is not a member of {thread}")
        joined_ts = self._meta_queue.generate_timestamp()
        return schema.add_membership(
            self._meta_queue,
            thread=thread,
            member=member["handle"],
            joined_ts=joined_ts,
            last_seen_ts=0,
        )

    def _write_message(
        self,
        *,
        queue: Queue,
        thread: str,
        from_handle: str,
        kind: str,
        text: str,
    ) -> Message:
        ts = queue.generate_timestamp()
        return self._insert_message(
            queue=queue,
            thread=thread,
            from_handle=from_handle,
            kind=kind,
            text=text,
            ts=ts,
        )

    def _insert_message(
        self,
        *,
        queue: Queue,
        thread: str,
        from_handle: str,
        kind: str,
        text: str,
        ts: int,
    ) -> Message:
        body = encode_envelope(
            from_handle=from_handle,
            kind=cast(Any, kind),
            text=text,
        )
        queue.insert_messages([(body, ts)])
        decoded = decode_envelope(body)
        return self._message_from_decoded(thread, decoded, ts)

    def _message_from_body(self, thread: str, body: str, ts: int) -> Message:
        return self._message_from_decoded(thread, decode_envelope(body), ts)

    def _message_from_decoded(
        self,
        thread: str,
        decoded: DecodedEnvelope,
        ts: int,
    ) -> Message:
        return Message(
            thread=thread,
            ts=ts,
            from_handle=decoded.from_handle,
            kind=decoded.kind,
            text=decoded.text,
            warning=decoded.warning,
        )

    def _thread_from_row(
        self,
        row: schema.ThreadRow,
        membership: schema.MembershipRow | None,
    ) -> Thread:
        queue = self.queue(row["name"])
        unread_count = self._unread_count(queue, membership)
        return Thread(
            name=row["name"],
            parent=row["parent"],
            unread=unread_count > 0,
            last_ts=self._last_message_ts(queue),
            unread_count=unread_count,
        )

    def _member_from_row(
        self,
        row: schema.MemberRow,
        *,
        capture: identity.IdentityCapture | None = None,
        token: str | None = None,
        explain: dict[str, Any] | None = None,
    ) -> Member:
        local_host_id = (
            capture.host.host_id
            if capture
            else identity.capture_host_identity().host_id
        )
        meta = row["meta"]
        persona = meta.get("persona") if isinstance(meta.get("persona"), str) else None
        return Member(
            handle=row["handle"],
            kind=row["kind"],
            presence=identity.member_presence(row, local_host_id),
            last_active_ts=row["last_active_ts"],
            persona=persona,
            token=token,
            explain=explain,
        )

    def _resolve_message_id(self, thread: str, msg_id: str) -> int:
        queue = self.queue(thread)
        if MESSAGE_ID_RE.fullmatch(msg_id):
            exact = int(msg_id)
            found = queue.peek(message_id=exact, with_timestamps=True)
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
            raise NotFoundError(f"message not found: {msg_id}")
        if len(matches) > 1:
            raise AmbiguousMessageError(
                "ambiguous message id suffix: " + ", ".join(str(ts) for ts in matches)
            )
        return matches[0]

    def _last_message_ts(self, queue: Queue) -> int | None:
        last_ts: int | None = None
        for result in queue.peek_generator(with_timestamps=True):
            _body, ts = cast(tuple[str, int], result)
            last_ts = ts
        return last_ts

    def _unread_count(
        self,
        queue: Queue,
        membership: schema.MembershipRow | None,
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

    def _parse_since(self, since: str | int | None) -> int | None:
        if since is None:
            return None
        if isinstance(since, int):
            return since
        try:
            return TimestampGenerator.validate(since)
        except TimestampError as exc:
            raise ValueError(str(exc)) from exc

    def _capture(self) -> identity.IdentityCapture:
        if self.identity_capture is not None:
            return self.identity_capture
        return identity.capture_identity()

    def _require_member(self, resolved: _ResolvedMember) -> schema.MemberRow:
        if resolved.row is None:
            raise IdentityError("unrecognized caller")
        return resolved.row

    def _validate_thread_name(self, name: str, *, allow_subthread: bool) -> None:
        if "." in name:
            if not allow_subthread:
                raise ThreadNameError("sub-thread names are not valid room names")
            room, dot, origin = name.partition(".")
            if not dot or "." in origin:
                raise ThreadNameError("sub-threads support exactly one level")
            if ROOM_NAME_RE.fullmatch(room) is None or not origin.isdigit():
                raise ThreadNameError(f"invalid thread name: {name}")
            if room == "taut" or room.startswith("taut."):
                raise ThreadNameError("taut is reserved")
            return
        if ROOM_NAME_RE.fullmatch(name) is None:
            raise ThreadNameError(f"invalid room name: {name}")
        if name == "taut":
            raise ThreadNameError("taut is reserved")


def database_path_from_target(target: BrokerTarget | str) -> str:
    """Return a display path for a resolved target."""

    if isinstance(target, str):
        return target
    return target.target
