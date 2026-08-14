"""Actor-free dump/load orchestration over public broker and sidecar seams.

Spec reference: docs/specs/08-persistence-io.md [PIO-2], [PIO-5], [PIO-6].
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any, BinaryIO

from simplebroker import (
    BrokerTarget,
    Queue,
    ResolvedConfig,
    dump_lines,
    format_message_id,
    load_lines,
    open_broker,
    target_for_directory,
)

from taut._constants import MESSAGE_ID_RE, META_QUEUE_NAME, load_config
from taut._exceptions import TautError
from taut._maintenance import resolve_existing_target
from taut.client._models import DumpReport, LoadReport, PersistenceComponentReport
from taut.state import SqlSidecarTautState, dialect_for_taut_target

from ._components import RegisteredPersistenceComponent, discover_components
from ._format import (
    _CORE_TIMESTAMP_FIELDS,
    FORMAT,
    VERSION,
    ParsedDump,
    _canonical,
    validate_dump,
)


def _resolve_source(
    db_path: str | Path | None,
) -> tuple[BrokerTarget | str, ResolvedConfig]:
    return resolve_existing_target(db_path)


def _resolve_destination(
    db_path: str | Path | None,
) -> tuple[BrokerTarget | str, ResolvedConfig]:
    config = load_config()
    explicit = db_path or os.environ.get("TAUT_DB")
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.parent.is_dir():
            raise TautError(f"cannot create {path}: parent is not a directory")
        return str(path), config
    try:
        return target_for_directory(Path.cwd(), config=config), config
    except tomllib.TOMLDecodeError as exc:
        raise TautError(f"invalid project configuration: {exc}") from exc
    except RuntimeError as exc:
        raise TautError(str(exc)) from exc


def _sqlite_path(target: BrokerTarget | str) -> Path | None:
    if isinstance(target, str):
        return Path(target)
    if target.backend_name == "sqlite":
        return Path(target.target)
    return None


def _same_path_or_file(left: Path, right: Path) -> bool:
    if left.resolve(strict=False) == right.resolve(strict=False):
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def _reject_storage_alias(output: Path, target: BrokerTarget | str) -> None:
    sqlite_path = _sqlite_path(target)
    if sqlite_path is None:
        return
    companions = (
        sqlite_path,
        Path(f"{sqlite_path}-wal"),
        Path(f"{sqlite_path}-shm"),
    )
    if any(_same_path_or_file(output, candidate) for candidate in companions):
        raise TautError("dump output must not be the SQLite database, WAL, or SHM file")


def _reject_input_alias(input_path: Path, target: BrokerTarget | str) -> None:
    sqlite_path = _sqlite_path(target)
    if sqlite_path is None:
        return
    companions = (
        sqlite_path,
        Path(f"{sqlite_path}-wal"),
        Path(f"{sqlite_path}-shm"),
    )
    if any(_same_path_or_file(input_path, candidate) for candidate in companions):
        raise TautError("load input must not be the SQLite database, WAL, or SHM file")


def _write(stream: BinaryIO, hasher: Any, raw: bytes) -> None:
    stream.write(raw)
    hasher.update(raw)


def _component(
    stream: BinaryIO,
    final_hasher: Any,
    *,
    name: str,
    version: int,
    payload: Iterable[bytes],
) -> tuple[int, int]:
    _write(
        stream,
        final_hasher,
        _canonical({"name": name, "type": "component_start", "version": version}),
    )
    component_hasher = hashlib.sha256()
    records = 0
    messages = 0
    for raw in payload:
        stream.write(raw)
        component_hasher.update(raw)
        final_hasher.update(raw)
        records += 1
        if name == "simplebroker" and records > 1:
            messages += 1
    _write(
        stream,
        final_hasher,
        _canonical(
            {
                "name": name,
                "records": records,
                "sha256": component_hasher.hexdigest(),
                "type": "component_end",
            }
        ),
    )
    return records, messages


def _core_payload(records: list[dict[str, Any]]) -> Iterable[bytes]:
    for record in records:
        external = dict(record)
        kind = external.get("type")
        if not isinstance(kind, str):
            raise TautError(f"unsupported Taut core persistence record {kind!r}")
        fields = _CORE_TIMESTAMP_FIELDS.get(kind)
        if fields is None:
            raise TautError(f"unsupported Taut core persistence record {kind!r}")
        for field in fields:
            value = external[field]
            if value is not None:
                external[field] = format_message_id(value)
        if kind == "thread":
            meta = external["meta"]
            if isinstance(meta, dict) and isinstance(meta.get("topic"), dict):
                external_meta = dict(meta)
                topic = dict(meta["topic"])
                updated_ts = topic.get("updated_ts")
                if updated_ts is not None:
                    topic["updated_ts"] = format_message_id(updated_ts)
                external_meta["topic"] = topic
                external["meta"] = external_meta
        yield _canonical(external)


def _extension_payload(records: list[dict[str, Any]]) -> Iterable[bytes]:
    for record in records:
        yield _canonical(record)


def _broker_header(line: str) -> int:
    try:
        header = json.loads(line)
        header_last_ts = header["last_ts"]
        if (
            not isinstance(header_last_ts, str)
            or MESSAGE_ID_RE.fullmatch(header_last_ts) is None
        ):
            raise ValueError
        high_water = int(format_message_id(header_last_ts))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise TautError("SimpleBroker emitted an invalid dump header") from exc
    if header.get("type") != "header":
        raise TautError("SimpleBroker emitted an invalid dump header")
    return high_water


def _selected_broker_lines(
    lines: Iterable[str],
    *,
    header_line: str,
    allowed: set[str],
    high_water: int,
) -> Iterable[bytes]:
    seen_ids: set[int] = set()
    yield header_line.encode("utf-8") + b"\n"
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - upstream contract
            raise TautError(f"SimpleBroker emitted malformed dump JSON: {exc}") from exc
        kind = record.get("type")
        if kind == "alias":
            continue
        if kind != "message":
            raise TautError(f"SimpleBroker emitted unsupported dump record {kind!r}")
        if record.get("queue") not in allowed:
            raise TautError("SimpleBroker emitted a message outside the Taut registry")
        try:
            raw_message_id = record["id"]
            if (
                not isinstance(raw_message_id, str)
                or MESSAGE_ID_RE.fullmatch(raw_message_id) is None
            ):
                raise ValueError
            message_id = int(format_message_id(raw_message_id))
        except (KeyError, TypeError, ValueError) as exc:
            raise TautError("SimpleBroker emitted an invalid message ID") from exc
        if message_id > high_water:
            raise TautError(
                "SimpleBroker emitted a message above its snapshot boundary"
            )
        if message_id in seen_ids:
            continue
        seen_ids.add(message_id)
        yield line.encode("utf-8") + b"\n"


def _broker_payload(
    broker: Any,
    queue_names: tuple[str, ...],
) -> tuple[int, Iterable[bytes]]:
    lines = iter(dump_lines(broker, include=queue_names or ("\0",)))
    try:
        header_line = next(lines)
    except StopIteration as exc:  # pragma: no cover - upstream contract
        raise TautError("SimpleBroker emitted a dump without a header") from exc
    high_water = _broker_header(header_line)
    return high_water, _selected_broker_lines(
        lines,
        header_line=header_line,
        allowed=set(queue_names),
        high_water=high_water,
    )


def _clamp_core_cursors(
    records: list[dict[str, Any]],
    high_water: int,
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for record in records:
        copied = dict(record)
        if copied.get("type") == "membership":
            copied["last_seen_ts"] = min(copied["last_seen_ts"], high_water)
        projected.append(copied)
    return projected


def dump_workspace(
    *,
    output: str | Path,
    db_path: str | Path | None,
) -> DumpReport:
    """Write one verified composite dump and atomically publish it."""

    target, config = _resolve_source(db_path)
    output_path = Path(output)
    _reject_storage_alias(output_path, target)
    queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    temp_path: Path | None = None
    try:
        state = SqlSidecarTautState(queue, dialect_for_taut_target(target))
        state.ensure_schema()
        meta = state.persistence_meta()
        registered = discover_components()
        key_owners = {key: item for item in registered for key in item.spec.schema_keys}
        unknown_meta = set(meta) - {"schema_version"} - set(key_owners)
        if unknown_meta:
            raise TautError(
                "unrecognized durable extension metadata: "
                + ", ".join(sorted(unknown_meta))
            )
        core_records = state.persistence_records()
        active_components = tuple(
            item for item in registered if item.spec.schema_keys & set(meta)
        )
        queue_names = tuple(
            record["name"] for record in core_records if record["type"] == "thread"
        )
        try:
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                dir=output_path.parent,
            )
        except OSError as exc:
            raise TautError(
                f"cannot create dump staging file for {output_path}: {exc}"
            ) from exc
        temp_path = Path(temp_name)
        os.chmod(temp_path, 0o600)
        components: list[PersistenceComponentReport] = []
        with (
            os.fdopen(fd, "wb") as stream,
            open_broker(target, config=config) as broker,
        ):
            high_water, broker_payload = _broker_payload(broker, queue_names)
            core_records = _clamp_core_cursors(core_records, high_water)
            extension_records = {
                item.spec.name: item.component.dump_records(queue)
                for item in active_components
            }
            claimed = sum(
                item.claimed
                for item in broker.list_queue_stats()
                if item.queue in set(queue_names)
            )
            final_hasher = hashlib.sha256()
            header = _canonical(
                {
                    "components": [
                        {"name": "simplebroker", "version": 1},
                        {"name": "taut-core", "version": 1},
                        *[
                            {
                                "name": item.spec.name,
                                "version": item.spec.write_version,
                            }
                            for item in active_components
                        ],
                    ],
                    "format": FORMAT,
                    "type": "header",
                    "version": VERSION,
                }
            )
            _write(stream, final_hasher, header)
            broker_records, messages = _component(
                stream,
                final_hasher,
                name="simplebroker",
                version=1,
                payload=broker_payload,
            )
            core_count, _unused = _component(
                stream,
                final_hasher,
                name="taut-core",
                version=1,
                payload=_core_payload(core_records),
            )
            for item in active_components:
                extension_count, _unused = _component(
                    stream,
                    final_hasher,
                    name=item.spec.name,
                    version=item.spec.write_version,
                    payload=_extension_payload(extension_records[item.spec.name]),
                )
                components.append(
                    PersistenceComponentReport(
                        item.spec.name,
                        item.spec.write_version,
                        extension_count,
                    )
                )
            stream.write(
                _canonical(
                    {
                        "components": 2 + len(active_components),
                        "records": broker_records
                        + core_count
                        + sum(part.records for part in components),
                        "sha256": final_hasher.hexdigest(),
                        "type": "end",
                    }
                )
            )
            stream.flush()
            os.fsync(stream.fileno())
            components.extend(
                (
                    PersistenceComponentReport("simplebroker", 1, broker_records),
                    PersistenceComponentReport("taut-core", 1, core_count),
                )
            )
        components.sort(
            key=lambda part: (
                0
                if part.name == "simplebroker"
                else 1
                if part.name == "taut-core"
                else 2,
                part.name,
            )
        )
        validate_dump(
            temp_path,
            supported_components={
                item.spec.name: item.spec.load_versions for item in active_components
            },
        )
        os.replace(temp_path, output_path)
        temp_path = None
        return DumpReport(
            path=str(output_path),
            format=FORMAT,
            version=VERSION,
            components=tuple(components),
            queues=len(queue_names),
            messages=messages,
            omitted_claimed_messages=claimed,
        )
    finally:
        queue.close()
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def _load_report(parsed: Any, *, dry_run: bool, applied: bool) -> LoadReport:
    return LoadReport(
        path=str(parsed.path),
        format=FORMAT,
        version=VERSION,
        components=tuple(
            PersistenceComponentReport(part.name, part.version, part.records)
            for part in parsed.components
        ),
        queues=parsed.queues,
        messages=parsed.messages,
        dry_run=dry_run,
        destination_checked=applied,
        applied=applied,
    )


def _preflight_load(
    path: Path,
) -> tuple[
    ParsedDump,
    list[RegisteredPersistenceComponent],
    list[dict[str, Any]],
]:
    registered = discover_components()
    by_name = {item.spec.name: item for item in registered}
    parsed = validate_dump(
        path,
        supported_components={
            item.spec.name: item.spec.load_versions for item in registered
        },
    )
    file_components: list[RegisteredPersistenceComponent] = []
    for part in parsed.components[2:]:
        item = by_name.get(part.name)
        if item is None:
            raise TautError(f"persistence component {part.name!r} is not installed")
        file_components.append(item)
    core_records = parsed.core_records()
    core_member_ids = frozenset(
        record["member_id"] for record in core_records if record["type"] == "member"
    )
    for item in file_components:
        part = next(part for part in parsed.components if part.name == item.spec.name)
        records = parsed.component_records(item.spec.name)
        try:
            item.component.validate_records(
                part.version,
                records,
                core_member_ids=core_member_ids,
            )
        except Exception as exc:
            raise TautError(
                f"invalid {item.spec.name} persistence component: {exc}"
            ) from exc
        finally:
            records.close()
    return parsed, file_components, core_records


def load_workspace(
    *,
    input_path: str | Path,
    db_path: str | Path | None,
    dry_run: bool,
) -> LoadReport:
    """Preflight or apply one complete composite dump to a fresh target."""

    path = Path(input_path)
    parsed, file_components, core_records = _preflight_load(path)
    target, config = _resolve_destination(db_path)
    _reject_input_alias(path, target)
    if dry_run:
        return _load_report(parsed, dry_run=True, applied=False)

    queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    try:
        state = SqlSidecarTautState(queue, dialect_for_taut_target(target))
        state.ensure_schema()
        for item in file_components:
            item.component.ensure_schema(queue)
            if not item.component.is_fresh(queue):
                raise TautError("load destination is not fresh")
        with open_broker(target, config=config) as broker:
            if broker.list_aliases() or any(
                stats.total for stats in broker.list_queue_stats()
            ):
                raise TautError("load destination is not fresh")
        allowed_meta_keys = frozenset(
            key for item in file_components for key in item.spec.schema_keys
        )
        state.acquire_load_guard(allowed_meta_keys=allowed_meta_keys)
        with queue.sidecar(transaction=True) as session:
            state.load_persistence_records_in(session, core_records)
            for item in file_components:
                records = parsed.component_records(item.spec.name)
                try:
                    item.component.load_records(session, records)
                finally:
                    records.close()
    finally:
        queue.close()

    with open_broker(target, config=config) as broker:
        broker_lines = parsed.component_lines("simplebroker")
        try:
            result = load_lines(broker, broker_lines, config=config)
        finally:
            broker_lines.close()
        if result.aliases != 0 or result.messages != parsed.messages:
            raise TautError("SimpleBroker load result did not match dump preflight")

    queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    try:
        state = SqlSidecarTautState(queue, dialect_for_taut_target(target))
        state.ensure_schema(allow_load_guard=True)
        state.clear_load_guard()
    finally:
        queue.close()
    return _load_report(parsed, dry_run=False, applied=True)
