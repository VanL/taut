"""Strict streaming parser for the composite Taut persistence format.

Spec reference: docs/specs/08-persistence-io.md [PIO-4], [PIO-7.1].
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from simplebroker import format_message_id

from taut import addressing
from taut._constants import (
    CHANNEL_NAME_RE,
    CLAIM_HASH_RE,
    MEMBER_ID_RE,
    MESSAGE_ID_RE,
    route_key,
    validate_member_name,
)
from taut._exceptions import TautError
from taut.state._channel_topics import (
    decode_channel_topic,
    require_topic_compatible_kind,
)

FORMAT: Final = "taut-dump"
VERSION: Final = 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CORE_FIELDS = {
    "member": {
        "type",
        "member_id",
        "display_name",
        "kind",
        "uid",
        "host_id",
        "host_label",
        "token",
        "meta",
        "created_ts",
        "last_active_ts",
    },
    "member_alias": {"type", "alias_key", "member_id", "created_ts"},
    "identity_claim": {
        "type",
        "claim_hash",
        "member_id",
        "claim_kind",
        "host_id",
        "host_label",
        "evidence",
        "first_seen_ts",
        "last_seen_ts",
    },
    "thread": {
        "type",
        "name",
        "kind",
        "parent",
        "origin_ts",
        "created_by",
        "meta",
        "created_ts",
    },
    "membership": {"type", "thread", "member_id", "joined_ts", "last_seen_ts"},
    "channel_rename": {
        "type",
        "old_name",
        "new_name",
        "state",
        "affected",
        "started_ts",
        "updated_ts",
    },
}
_CORE_ORDER = {name: index for index, name in enumerate(_CORE_FIELDS)}
_CORE_TIMESTAMP_FIELDS = {
    "member": ("created_ts", "last_active_ts"),
    "member_alias": ("created_ts",),
    "identity_claim": ("first_seen_ts", "last_seen_ts"),
    "thread": ("origin_ts", "created_ts"),
    "membership": ("joined_ts", "last_seen_ts"),
    "channel_rename": ("started_ts", "updated_ts"),
}
_DM_QUEUE_RE = re.compile(r"dm\.d_[a-z2-7]{26}")


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ComponentSpan:
    name: str
    version: int
    records: int
    payload_start: int
    payload_end: int


@dataclass(frozen=True, slots=True)
class ParsedDump:
    path: Path
    components: tuple[ComponentSpan, ...]
    queues: int
    messages: int

    def component_lines(self, name: str):  # type: ignore[no-untyped-def]
        """Replay exact payload text for one validated component."""

        component = next(part for part in self.components if part.name == name)
        with self.path.open("rb") as stream:
            stream.seek(component.payload_start)
            while stream.tell() < component.payload_end:
                raw = stream.readline()
                yield raw[:-1].decode("utf-8")

    def core_records(self) -> list[dict[str, Any]]:
        """Decode the already validated, bounded-size core component."""

        records = [json.loads(line) for line in self.component_lines("taut-core")]
        for record in records:
            _normalize_core_record(record)
        return records

    def component_records(self, name: str):  # type: ignore[no-untyped-def]
        """Replay decoded records from one already framed component."""

        for line in self.component_lines(name):
            yield json.loads(line)


class _CoreValidator:
    def __init__(self) -> None:
        self.last_key: tuple[int, Any] | None = None
        self.member_ids: set[str] = set()
        self.route_keys: set[str] = set()
        self.tokens: set[str] = set()
        self.aliases: set[str] = set()
        self.claims: set[str] = set()
        self.thread_names: set[str] = set()
        self.memberships: set[tuple[str, str]] = set()
        self.dm_members: dict[str, tuple[str, str]] = {}
        self.rename_names: set[str] = set()
        self.member_refs: list[tuple[int, str, str]] = []
        self.thread_refs: list[tuple[int, str]] = []

    def accept(self, record: dict[str, Any], line_number: int) -> None:
        kind = record.get("type")
        validators = {
            "member": self._accept_member,
            "member_alias": self._accept_alias,
            "identity_claim": self._accept_claim,
            "thread": self._accept_thread,
            "membership": self._accept_membership,
            "channel_rename": self._accept_rename,
        }
        if not isinstance(kind, str):
            raise TautError(
                f"invalid Taut dump at line {line_number}: unknown core record {kind!r}"
            )
        validator = validators.get(kind)
        if validator is None:
            raise TautError(
                f"invalid Taut dump at line {line_number}: unknown core record {kind!r}"
            )
        _exact_fields(record, _CORE_FIELDS[kind], line_number=line_number)
        try:
            _normalize_core_record(record)
        except (TypeError, ValueError):
            self._invalid(line_number, kind.replace("_", " "))
        key = validator(record, line_number)
        order_key = (_CORE_ORDER[kind], key)
        if self.last_key is not None and order_key <= self.last_key:
            raise TautError(
                f"invalid Taut dump at line {line_number}: core records are out of order"
            )
        self.last_key = order_key

    def _accept_member(self, record: dict[str, Any], line_number: int) -> str:
        key = record["member_id"]
        display_name = record["display_name"]
        token = record["token"]
        if not isinstance(key, str) or MEMBER_ID_RE.fullmatch(key) is None:
            self._invalid(line_number, "member")
        try:
            validate_member_name(display_name)
        except (TypeError, ValueError):
            self._invalid(line_number, "member")
        if not isinstance(token, str):
            self._invalid(line_number, "member")
        assert isinstance(key, str)
        assert isinstance(display_name, str)
        assert isinstance(token, str)
        name_key = route_key(display_name)
        valid = all(
            (
                key not in self.member_ids,
                name_key not in self.route_keys,
                record["kind"] in {"human", "agent"},
                _nonnegative_int(record["uid"]),
                isinstance(record["host_id"], str),
                bool(record["host_id"]),
                bool(token),
                token not in self.tokens,
                isinstance(record["meta"], dict),
                _optional_str(record["host_label"]),
                _nonnegative_int(record["created_ts"]),
                _nonnegative_int(record["last_active_ts"]),
            )
        )
        if not valid:
            self._invalid(line_number, "member")
        self.member_ids.add(key)
        self.route_keys.add(name_key)
        self.tokens.add(token)
        return key

    def _accept_alias(self, record: dict[str, Any], line_number: int) -> str:
        key = record["alias_key"]
        valid = isinstance(key, str) and all(
            (
                bool(key),
                route_key(key) == key,
                key not in self.aliases,
                key not in self.route_keys,
                _valid_member_id(record["member_id"]),
                _nonnegative_int(record["created_ts"]),
            )
        )
        if not valid:
            self._invalid(line_number, "alias")
        assert isinstance(key, str)
        self.aliases.add(key)
        self.route_keys.add(key)
        self.member_refs.append((line_number, record["member_id"], "alias"))
        return key

    def _accept_claim(self, record: dict[str, Any], line_number: int) -> str:
        key = record["claim_hash"]
        valid = isinstance(key, str) and all(
            (
                CLAIM_HASH_RE.fullmatch(key) is not None,
                key not in self.claims,
                _valid_member_id(record["member_id"]),
                isinstance(record["claim_kind"], str),
                bool(record["claim_kind"]),
                _optional_str(record["host_id"]),
                _optional_str(record["host_label"]),
                isinstance(record["evidence"], dict),
                _nonnegative_int(record["first_seen_ts"]),
                _nonnegative_int(record["last_seen_ts"]),
            )
        )
        if not valid:
            self._invalid(line_number, "identity claim")
        assert isinstance(key, str)
        self.claims.add(key)
        self.member_refs.append((line_number, record["member_id"], "claim"))
        return key

    def _accept_thread(self, record: dict[str, Any], line_number: int) -> str:
        key = record["name"]
        meta = record["meta"]
        kind = record["kind"]
        try:
            if isinstance(meta, dict) and isinstance(kind, str):
                require_topic_compatible_kind(kind=kind, meta=meta)
                topic = decode_channel_topic(meta)
            else:
                topic = None
        except TautError:
            self._invalid(line_number, "thread")
        valid = isinstance(key, str) and all(
            (
                bool(key),
                key not in self.thread_names,
                record["kind"]
                in {"channel", "subthread", "dm", "notification", "system"},
                _valid_thread_shape(record),
                _valid_member_id(record["created_by"]),
                _optional_str(record["parent"]),
                record["origin_ts"] is None or _positive_int(record["origin_ts"]),
                isinstance(record["meta"], dict),
                _nonnegative_int(record["created_ts"]),
            )
        )
        if not valid:
            self._invalid(line_number, "thread")
        assert isinstance(key, str)
        self.thread_names.add(key)
        self.member_refs.append((line_number, record["created_by"], "thread"))
        if record["kind"] == "dm":
            members = tuple(record["meta"]["members"])
            if key != addressing.dm_queue_name(members[0], members[1]):
                self._invalid(line_number, "direct message")
            self.dm_members[key] = members
            for member_id in members:
                self.member_refs.append((line_number, member_id, "direct message"))
        elif record["kind"] == "notification":
            self.member_refs.append(
                (line_number, record["meta"]["member_id"], "notification")
            )
        if record["parent"] is not None:
            self.thread_refs.append((line_number, record["parent"]))
        if topic is not None:
            self.member_refs.append(
                (line_number, topic["updated_by_id"], "channel topic")
            )
        return key

    def _accept_membership(
        self,
        record: dict[str, Any],
        line_number: int,
    ) -> tuple[str, str]:
        key = (record["thread"], record["member_id"])
        if not all(isinstance(value, str) and value for value in key):
            self._invalid(line_number, "membership")
        valid = all(
            (
                _valid_member_id(record["member_id"]),
                key not in self.memberships,
                _nonnegative_int(record["joined_ts"]),
                _nonnegative_int(record["last_seen_ts"]),
            )
        )
        if not valid:
            self._invalid(line_number, "membership")
        assert isinstance(key[0], str)
        assert isinstance(key[1], str)
        self.memberships.add(key)
        self.member_refs.append((line_number, record["member_id"], "membership"))
        self.thread_refs.append((line_number, record["thread"]))
        return key

    def _accept_rename(self, record: dict[str, Any], line_number: int) -> str:
        key = record["old_name"]
        valid = isinstance(key, str) and all(
            (
                bool(key),
                key not in self.rename_names,
                isinstance(record["new_name"], str),
                bool(record["new_name"]),
                record["state"] == "complete",
                _valid_affected(record["affected"]),
                _nonnegative_int(record["started_ts"]),
                _nonnegative_int(record["updated_ts"]),
            )
        )
        if not valid:
            self._invalid(line_number, "channel rename")
        assert isinstance(key, str)
        self.rename_names.add(key)
        return key

    @staticmethod
    def _invalid(line_number: int, record_type: str) -> None:
        raise TautError(
            f"invalid Taut dump at line {line_number}: invalid {record_type} record"
        )

    def finish(self) -> None:
        for line_number, member_id, context in self.member_refs:
            if member_id not in self.member_ids:
                raise TautError(
                    f"invalid Taut dump at line {line_number}: {context} references "
                    f"missing member {member_id!r}"
                )
        for line_number, thread in self.thread_refs:
            if thread not in self.thread_names:
                raise TautError(
                    f"invalid Taut dump at line {line_number}: missing thread {thread!r}"
                )
        for thread, members in self.dm_members.items():
            actual = {
                member_id
                for membership_thread, member_id in self.memberships
                if membership_thread == thread
            }
            if actual != set(members):
                raise TautError(
                    "invalid Taut dump: direct message membership does not match "
                    f"participants for {thread!r}"
                )


def validate_core_records(records: list[dict[str, Any]]) -> frozenset[str]:
    """Validate one live or dump-neutral core projection."""

    validator = _CoreValidator()
    for record_number, record in enumerate(records, start=1):
        validator.accept(dict(record), record_number)
    validator.finish()
    return frozenset(validator.member_ids)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for key, value in pairs:
        if key in record:
            raise _DuplicateKey(f"duplicate field {key!r}")
        record[key] = value
    return record


def _decode(raw: bytes, line_number: int) -> dict[str, Any]:
    try:
        text = raw[:-1].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TautError(
            f"invalid Taut dump at line {line_number}: input is not valid UTF-8"
        ) from exc
    try:
        value = json.loads(text, object_pairs_hook=_pairs)
    except (_DuplicateKey, json.JSONDecodeError, ValueError) as exc:
        raise TautError(
            f"invalid Taut dump at line {line_number}: malformed JSON ({exc})"
        ) from exc
    if not isinstance(value, dict):
        raise TautError(
            f"invalid Taut dump at line {line_number}: record must be a JSON object"
        )
    return value


def _canonical(record: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _exact_fields(
    record: dict[str, Any],
    expected: set[str],
    *,
    line_number: int,
) -> None:
    if set(record) != expected:
        raise TautError(
            f"invalid Taut dump at line {line_number}: expected fields "
            f"{sorted(expected)!r}"
        )


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _message_id_as_int(value: Any) -> int:
    formatted = format_message_id(value)
    if isinstance(value, str) and value != formatted:
        raise ValueError("message ID string must use the canonical representation")
    return int(formatted)


def _valid_external_message_id(value: Any) -> bool:
    try:
        _message_id_as_int(value)
    except (TypeError, ValueError):
        return False
    return True


def _normalize_core_record(record: dict[str, Any]) -> None:
    kind = record.get("type")
    if not isinstance(kind, str):
        return
    fields = _CORE_TIMESTAMP_FIELDS.get(kind)
    if fields is None:
        return
    for field in fields:
        value = record[field]
        if value is not None:
            record[field] = _message_id_as_int(value)
    if kind != "thread":
        return
    meta = record["meta"]
    if not isinstance(meta, dict):
        return
    topic = meta.get("topic")
    if not isinstance(topic, dict) or "updated_ts" not in topic:
        return
    updated_ts = topic["updated_ts"]
    if updated_ts is not None:
        topic["updated_ts"] = _message_id_as_int(updated_ts)


def _valid_member_id(value: Any) -> bool:
    return isinstance(value, str) and MEMBER_ID_RE.fullmatch(value) is not None


def _optional_str(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _valid_thread_shape(record: dict[str, Any]) -> bool:
    name = record["name"]
    kind = record["kind"]
    parent = record["parent"]
    origin = record["origin_ts"]
    meta = record["meta"]
    if not isinstance(name, str) or any(char in name for char in "*?[]"):
        return False
    if kind == "channel":
        return CHANNEL_NAME_RE.fullmatch(name) is not None and all(
            (parent is None, origin is None)
        )
    if kind == "subthread":
        return (
            isinstance(parent, str)
            and CHANNEL_NAME_RE.fullmatch(parent) is not None
            and _positive_int(origin)
            and MESSAGE_ID_RE.fullmatch(str(origin)) is not None
            and name == f"{parent}.{origin}"
        )
    if kind == "dm":
        members = meta.get("members") if isinstance(meta, dict) else None
        return _DM_QUEUE_RE.fullmatch(name) is not None and all(
            (
                parent is None,
                origin is None,
                isinstance(members, list),
                len(members) == 2 if isinstance(members, list) else False,
                all(_valid_member_id(item) for item in members)
                if isinstance(members, list)
                else False,
                record["created_by"] in members if isinstance(members, list) else False,
                members == sorted(set(members))
                if isinstance(members, list)
                and all(isinstance(item, str) for item in members)
                else False,
            )
        )
    if kind == "notification":
        member_id = meta.get("member_id") if isinstance(meta, dict) else None
        return all(
            (
                parent is None,
                origin is None,
                _valid_member_id(member_id),
                name == f"notify.{member_id}",
                record["created_by"] == member_id,
            )
        )
    return kind == "system" and all(
        (
            name.startswith(("sys.", "taut.")),
            parent is None,
            origin is None,
        )
    )


def _valid_affected(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and all(isinstance(key, str) for key in item)
        and all(isinstance(field, str) for field in item.values())
        for item in value
    )


def _validate_header(
    record: dict[str, Any],
    line_number: int,
    supported_components: dict[str, frozenset[int]],
) -> list[tuple[str, int]]:
    _exact_fields(
        record,
        {"components", "format", "type", "version"},
        line_number=line_number,
    )
    if (
        record["type"] != "header"
        or record["format"] != FORMAT
        or record["version"] != VERSION
    ):
        raise TautError(f"invalid Taut dump at line {line_number}: unsupported header")
    raw_components = record["components"]
    if not isinstance(raw_components, list):
        raise TautError(
            f"invalid Taut dump at line {line_number}: components must be an array"
        )
    components: list[tuple[str, int]] = []
    for raw_component in raw_components:
        if not isinstance(raw_component, dict) or set(raw_component) != {
            "name",
            "version",
        }:
            raise TautError(
                f"invalid Taut dump at line {line_number}: malformed component header"
            )
        name = raw_component["name"]
        version = raw_component["version"]
        if not isinstance(name, str) or not _positive_int(version):
            raise TautError(
                f"invalid Taut dump at line {line_number}: malformed component header"
            )
        components.append((name, version))
    names = [name for name, _version in components]
    expected_names = ["simplebroker", "taut-core", *sorted(names[2:])]
    if names != expected_names or len(set(names)) != len(names):
        raise TautError(
            f"invalid Taut dump at line {line_number}: invalid component order"
        )
    for name, version in components:
        if version not in supported_components.get(name, frozenset()):
            raise TautError(
                f"invalid Taut dump at line {line_number}: unsupported component "
                f"{name!r} version {version}"
            )
    return components


class _DumpValidator:
    """State machine for one pass over a composite dump."""

    def __init__(
        self,
        path: Path,
        supported_components: dict[str, frozenset[int]],
    ) -> None:
        self.path = path
        self.supported_components = supported_components
        self.final_hasher = hashlib.sha256()
        self.declared: list[tuple[str, int]] | None = None
        self.component_index = 0
        self.active: tuple[str, int] | None = None
        self.component_hasher = hashlib.sha256()
        self.component_records = 0
        self.component_start = 0
        self.spans: list[ComponentSpan] = []
        self.ended = False
        self.total_records = 0
        self.message_count = 0
        self.message_queues: set[str] = set()
        self.message_ids: set[int] = set()
        self.last_message_key: tuple[str, int] | None = None
        self.nested_header_seen = False
        self.core_validator = _CoreValidator()

    def accept(
        self,
        record: dict[str, Any],
        raw: bytes,
        *,
        offset: int,
        after_offset: int,
        line_number: int,
    ) -> None:
        if self.ended:
            raise TautError(
                f"invalid Taut dump at line {line_number}: trailing record after end"
            )
        kind = record.get("type")
        if self.declared is None:
            self._accept_header(record, raw, line_number)
        elif self.active is None and kind == "component_start":
            self._accept_component_start(record, raw, after_offset, line_number)
        elif self.active is not None and kind == "component_end":
            self._accept_component_end(record, raw, offset, line_number)
        elif self.active is None and kind == "end":
            self._accept_final(record, raw, line_number)
        elif self.active is None:
            raise TautError(
                f"invalid Taut dump at line {line_number}: record outside a component"
            )
        else:
            self._accept_payload(record, raw, line_number)

    def _accept_header(
        self,
        record: dict[str, Any],
        raw: bytes,
        line_number: int,
    ) -> None:
        self.declared = _validate_header(
            record,
            line_number,
            self.supported_components,
        )
        self._require_canonical(record, raw, line_number, "framing")
        self.final_hasher.update(raw)

    def _accept_component_start(
        self,
        record: dict[str, Any],
        raw: bytes,
        after_offset: int,
        line_number: int,
    ) -> None:
        assert self.declared is not None
        _exact_fields(
            record,
            {"name", "type", "version"},
            line_number=line_number,
        )
        if self.component_index >= len(self.declared):
            raise TautError(f"invalid Taut dump at line {line_number}: extra component")
        expected = self.declared[self.component_index]
        if (record["name"], record["version"]) != expected:
            raise TautError(
                f"invalid Taut dump at line {line_number}: component order mismatch"
            )
        self._require_canonical(record, raw, line_number, "framing")
        self.active = expected
        self.component_hasher = hashlib.sha256()
        self.component_records = 0
        self.component_start = after_offset
        self.nested_header_seen = False
        self.last_message_key = None
        self.final_hasher.update(raw)

    def _accept_component_end(
        self,
        record: dict[str, Any],
        raw: bytes,
        offset: int,
        line_number: int,
    ) -> None:
        assert self.active is not None
        _exact_fields(
            record,
            {"name", "records", "sha256", "type"},
            line_number=line_number,
        )
        digest = record["sha256"]
        valid = (
            record["name"] == self.active[0]
            and record["records"] == self.component_records
            and isinstance(digest, str)
            and _SHA256_RE.fullmatch(digest) is not None
            and digest == self.component_hasher.hexdigest()
        )
        if not valid:
            raise TautError(
                f"invalid Taut dump at line {line_number}: "
                "component count or digest mismatch"
            )
        if self.active[0] == "simplebroker" and not self.nested_header_seen:
            raise TautError(
                f"invalid Taut dump at line {line_number}: missing SimpleBroker header"
            )
        self._require_canonical(record, raw, line_number, "framing")
        self.spans.append(
            ComponentSpan(
                name=self.active[0],
                version=self.active[1],
                records=self.component_records,
                payload_start=self.component_start,
                payload_end=offset,
            )
        )
        self.total_records += self.component_records
        self.active = None
        self.component_index += 1
        self.final_hasher.update(raw)

    def _accept_final(
        self,
        record: dict[str, Any],
        raw: bytes,
        line_number: int,
    ) -> None:
        assert self.declared is not None
        _exact_fields(
            record,
            {"components", "records", "sha256", "type"},
            line_number=line_number,
        )
        digest = record["sha256"]
        valid = (
            self.component_index == len(self.declared)
            and record["components"] == len(self.declared)
            and record["records"] == self.total_records
            and isinstance(digest, str)
            and _SHA256_RE.fullmatch(digest) is not None
            and digest == self.final_hasher.hexdigest()
        )
        if not valid:
            raise TautError(
                f"invalid Taut dump at line {line_number}: final count or digest mismatch"
            )
        self._require_canonical(record, raw, line_number, "framing")
        self.ended = True

    def _accept_payload(
        self,
        record: dict[str, Any],
        raw: bytes,
        line_number: int,
    ) -> None:
        assert self.active is not None
        self.component_hasher.update(raw)
        self.final_hasher.update(raw)
        self.component_records += 1
        if self.active[0] == "simplebroker":
            self._accept_simplebroker(record, line_number)
        elif self.active[0] == "taut-core":
            self._require_canonical(record, raw, line_number, "core record")
            self.core_validator.accept(record, line_number)
        else:
            self._require_canonical(record, raw, line_number, "extension record")

    def _accept_simplebroker(
        self,
        record: dict[str, Any],
        line_number: int,
    ) -> None:
        if not self.nested_header_seen:
            self._accept_simplebroker_header(record, line_number)
            return
        # This is an intentional compatibility pin to SimpleBroker dump format
        # v1 was introduced in 7.0.0 and is retained by the runtime floor. A
        # future upstream
        # field is a format change that needs an explicit Taut load-version
        # decision, not something to accept and then silently discard.
        _exact_fields(
            record,
            {"body", "id", "queue", "type"},
            line_number=line_number,
        )
        try:
            message_id = _message_id_as_int(record["id"])
        except (TypeError, ValueError):
            raise TautError(
                f"invalid Taut dump at line {line_number}: invalid SimpleBroker message"
            ) from None
        queue = record["queue"]
        valid = (
            record["type"] == "message"
            and isinstance(queue, str)
            and isinstance(record["body"], str)
            and _positive_int(message_id)
            and message_id not in self.message_ids
        )
        if not valid:
            raise TautError(
                f"invalid Taut dump at line {line_number}: invalid SimpleBroker message"
            )
        message_key = (queue, message_id)
        if self.last_message_key is not None and message_key <= self.last_message_key:
            raise TautError(
                f"invalid Taut dump at line {line_number}: "
                "SimpleBroker messages are out of order"
            )
        self.last_message_key = message_key
        self.message_ids.add(message_id)
        self.message_queues.add(queue)
        self.message_count += 1

    def _accept_simplebroker_header(
        self,
        record: dict[str, Any],
        line_number: int,
    ) -> None:
        _exact_fields(
            record,
            {"backend", "format", "last_ts", "type", "version"},
            line_number=line_number,
        )
        if (
            record["type"] != "header"
            or record["format"] != "simplebroker-dump"
            or record["version"] != 1
            or not isinstance(record["backend"], str)
            or not _valid_external_message_id(record["last_ts"])
        ):
            raise TautError(
                f"invalid Taut dump at line {line_number}: invalid SimpleBroker header"
            )
        self.nested_header_seen = True

    @staticmethod
    def _require_canonical(
        record: dict[str, Any],
        raw: bytes,
        line_number: int,
        context: str,
    ) -> None:
        if raw != _canonical(record):
            raise TautError(
                f"invalid Taut dump at line {line_number}: noncanonical {context}"
            )

    def finish(self) -> ParsedDump:
        if self.declared is None:
            raise TautError("invalid Taut dump: missing header")
        if not self.ended:
            raise TautError("invalid Taut dump: missing final end record")
        self.core_validator.finish()
        thread_names = self.core_validator.thread_names
        if not self.message_queues.issubset(thread_names):
            missing = sorted(self.message_queues - thread_names)
            raise TautError(
                "invalid Taut dump: broker messages reference unregistered queues: "
                + ", ".join(missing)
            )
        return ParsedDump(
            path=self.path,
            components=tuple(self.spans),
            queues=len(thread_names),
            messages=self.message_count,
        )


def validate_dump(
    path: Path,
    *,
    supported_components: dict[str, frozenset[int]] | None = None,
) -> ParsedDump:
    """Validate a complete dump while retaining only replay offsets and indexes."""

    validator = _DumpValidator(
        path,
        {
            "simplebroker": frozenset({1}),
            "taut-core": frozenset({1}),
            **(supported_components or {}),
        },
    )
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise TautError(f"cannot read Taut dump {path}: {exc}") from exc
    with stream:
        line_number = 0
        while raw := stream.readline():
            line_number += 1
            if not raw.endswith(b"\n"):
                raise TautError(
                    f"invalid Taut dump at line {line_number}: line lacks final LF"
                )
            if raw == b"\n":
                raise TautError(
                    f"invalid Taut dump at line {line_number}: blank lines are forbidden"
                )
            after_offset = stream.tell()
            validator.accept(
                _decode(raw, line_number),
                raw,
                offset=after_offset - len(raw),
                after_offset=after_offset,
                line_number=line_number,
            )
    return validator.finish()
