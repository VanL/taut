"""Bounded passive workspace diagnosis.

Spec reference: docs/specs/09-system-doctor.md [DOCT-1] through [DOCT-7].
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from simplebroker import Queue, open_broker
from simplebroker.ext import DatabaseError

from taut._constants import META_QUEUE_NAME, SCHEMA_VERSION
from taut._exceptions import TautError
from taut._maintenance import display_target, resolve_existing_target
from taut.client._models import DoctorCheck, DoctorReport
from taut.persistence._components import (
    PersistenceComponentCompatibilityError,
    PersistenceComponentManifestError,
    PersistenceComponentRuntimeError,
    discover_components,
)
from taut.persistence._format import validate_core_records
from taut.search._jobs import (
    CLAIMED_QUEUE_NAME,
    FAILED_QUEUE_NAME,
    PENDING_QUEUE_NAME,
)
from taut.state import (
    DEBUG_CAPTURE_KEY,
    CoreSchemaInspectionError,
    SqlSidecarTautState,
    dialect_for_taut_target,
)

_CORE_COUNTS = (
    "aliases",
    "completed_renames",
    "identity_claims",
    "members",
    "memberships",
    "threads",
)


def _detail(value: object) -> str:
    return " ".join(str(value).splitlines())[:500] or "inspection failed"


def _check(
    name: str,
    status: Literal["pass", "fail", "skip"],
    detail: str,
    data: dict[str, object],
) -> DoctorCheck:
    return DoctorCheck(name, status, _detail(detail), data)


def _nulls(keys: Iterable[str]) -> dict[str, object]:
    return dict.fromkeys(keys)


def _schema_version(meta: dict[str, str]) -> int | None:
    raw = meta.get("schema_version")
    if raw is None or not raw.isascii() or not raw.isdigit():
        return None
    version = int(raw)
    return version if str(version) == raw else None


def _core_counts(records: list[dict[str, Any]]) -> dict[str, object]:
    kinds = {
        "member": "members",
        "member_alias": "aliases",
        "identity_claim": "identity_claims",
        "thread": "threads",
        "membership": "memberships",
        "channel_rename": "completed_renames",
    }
    counts: dict[str, object] = dict.fromkeys(_CORE_COUNTS, 0)
    for record in records:
        kind = record.get("type")
        key = kinds.get(kind) if isinstance(kind, str) else None
        if key is not None:
            current = counts[key]
            assert isinstance(current, int)
            counts[key] = current + 1
    return counts


def _validate_live_core(records: list[dict[str, Any]]) -> frozenset[str]:
    try:
        return validate_core_records(records)
    except TautError as exc:
        message = str(exc).replace("invalid Taut dump at line", "invalid core record")
        raise TautError(message) from exc


def _inspect_core(
    state: SqlSidecarTautState,
) -> tuple[
    list[DoctorCheck],
    dict[str, str] | None,
    list[dict[str, Any]] | None,
    frozenset[str] | None,
]:
    """Run the three ordered core-owned checks and return dependencies."""

    try:
        meta = state.probe_persistence_meta()
    except CoreSchemaInspectionError:
        meta = None
        core_schema = _check(
            "core_schema",
            "fail",
            "required core metadata is missing",
            {"version": None},
        )
    else:
        assert meta is not None
        version = _schema_version(meta)
        try:
            state.probe_persistence_tables()
        except CoreSchemaInspectionError:
            tables_ok = False
        else:
            tables_ok = True
        schema_ok = version == SCHEMA_VERSION and tables_ok
        core_schema = _check(
            "core_schema",
            "pass" if schema_ok else "fail",
            (
                f"core schema version {version} is current"
                if schema_ok
                else (
                    "required core table or column is missing"
                    if version == SCHEMA_VERSION
                    else "core schema version is missing, malformed, or incompatible"
                )
            ),
            {"version": version},
        )
    schema_ok = core_schema.status == "pass"
    checks = [core_schema]
    if meta is None:
        checks.append(
            _check("load_guard", "skip", "core metadata unavailable", {"present": None})
        )
    else:
        guarded = "load_guard" in meta
        checks.append(
            _check(
                "load_guard",
                "fail" if guarded else "pass",
                (
                    "load guard is present; recreate the target"
                    if guarded
                    else "load guard is absent"
                ),
                {"present": guarded},
            )
        )
    if not schema_ok:
        checks.append(
            _check(
                "core_state",
                "skip",
                "core schema unavailable",
                _nulls(_CORE_COUNTS),
            )
        )
        return checks, meta, None, None
    try:
        records = state.doctor_persistence_records()
        member_ids = _validate_live_core(records)
    except (TautError, TypeError, ValueError) as exc:
        checks.append(_check("core_state", "fail", str(exc), _nulls(_CORE_COUNTS)))
        return checks, meta, None, None
    checks.append(
        _check(
            "core_state",
            "pass",
            "core logical state is internally consistent",
            _core_counts(records),
        )
    )
    return checks, meta, records, member_ids


def doctor_workspace(*, db_path: str | Path | None) -> DoctorReport:
    """Run and return the complete fixed seven-check diagnostic report."""

    try:
        return _doctor_workspace(db_path=db_path)
    except DatabaseError as exc:
        raise TautError(
            "system doctor could not access the selected workspace"
        ) from exc


def _doctor_workspace(*, db_path: str | Path | None) -> DoctorReport:
    """Run the checks after the public database-error containment boundary."""

    target, config = resolve_existing_target(db_path)
    queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    try:
        state = SqlSidecarTautState(queue, dialect_for_taut_target(target))
        checks, meta, records, member_ids = _inspect_core(state)

        with open_broker(target, config=config) as broker:
            stats = {item.queue: item for item in broker.list_queue_stats()}

        if records is None:
            checks.append(
                _check(
                    "broker_state",
                    "skip",
                    "validated core thread registry unavailable",
                    _nulls(
                        (
                            "claimed",
                            "observed_nonempty_queues",
                            "pending",
                            "registered_threads",
                        )
                    ),
                )
            )
        else:
            threads = tuple(
                str(record["name"])
                for record in records
                if record.get("type") == "thread"
            )
            selected = tuple(stats[name] for name in threads if name in stats)
            checks.append(
                _check(
                    "broker_state",
                    "pass",
                    "public broker statistics were observed",
                    {
                        "claimed": sum(item.claimed for item in selected),
                        "observed_nonempty_queues": sum(
                            item.total > 0 for item in selected
                        ),
                        "pending": sum(item.pending for item in selected),
                        "registered_threads": len(threads),
                    },
                )
            )

        if member_ids is None or meta is None:
            checks.append(
                _check(
                    "extension_state",
                    "skip",
                    "authoritative core member IDs unavailable",
                    _nulls(("active", "installed", "records")),
                )
            )
        else:
            checks.append(_extension_check(queue, meta, member_ids))

        with open_broker(target, config=config) as broker:
            search_stats = {item.queue: item for item in broker.list_queue_stats()}
        search_totals = {
            "pending": search_stats.get(PENDING_QUEUE_NAME),
            "claimed": search_stats.get(CLAIMED_QUEUE_NAME),
            "failed": search_stats.get(FAILED_QUEUE_NAME),
        }
        search_data: dict[str, object] = {
            key: 0 if item is None else item.total
            for key, item in search_totals.items()
        }
        failed = bool(search_data["failed"])
        checks.append(
            _check(
                "search_work",
                "fail" if failed else "pass",
                (
                    "failed search work requires inspection"
                    if failed
                    else "search work queues have no failed rows"
                ),
                search_data,
            )
        )
        checks.append(_debug_capture_check(meta))
    finally:
        queue.close()

    result = tuple(checks)
    return DoctorReport(
        db=display_target(target),
        healthy=all(check.status == "pass" for check in result),
        checks=result,
    )


def _debug_capture_check(meta: dict[str, str] | None) -> DoctorCheck:
    if meta is None:
        return _check(
            "debug_capture",
            "skip",
            "core metadata unavailable",
            {"enabled": None, "sink": None},
        )
    raw = meta.get(DEBUG_CAPTURE_KEY)
    if raw is None:
        return _check(
            "debug_capture",
            "pass",
            "debug capture is disabled",
            {"enabled": False, "sink": "disabled"},
        )
    if raw != "1":
        return _check(
            "debug_capture",
            "fail",
            "debug capture setting is malformed; run system debug enable or disable",
            {"enabled": None, "sink": None},
        )
    sink = "action" if "TAUT_DEBUG_ACTION" in os.environ else "local"
    return _check(
        "debug_capture",
        "pass",
        f"debug capture is enabled with the {sink} sink",
        {"enabled": True, "sink": sink},
    )


def _extension_check(
    queue: Queue,
    meta: dict[str, str],
    member_ids: frozenset[str],
) -> DoctorCheck:
    try:
        registered = discover_components()
    except PersistenceComponentManifestError as exc:
        return _check(
            "extension_state",
            "fail",
            str(exc),
            _nulls(("active", "installed", "records")),
        )
    except PersistenceComponentRuntimeError as exc:
        raise TautError("persistence contributor discovery failed") from exc
    installed = [item.spec.name for item in registered]
    owners = {key: item for item in registered for key in item.spec.schema_keys}
    unknown = sorted(
        set(meta) - {"schema_version", "load_guard", DEBUG_CAPTURE_KEY} - set(owners)
    )
    active = [item for item in registered if item.spec.schema_keys & set(meta)]
    data: dict[str, object] = {
        "active": [item.spec.name for item in active],
        "installed": installed,
        "records": {},
    }
    if unknown:
        data["records"] = None
        return _check(
            "extension_state",
            "fail",
            "unrecognized durable extension metadata: " + ", ".join(unknown),
            data,
        )
    record_counts: dict[str, int] = {}
    for item in active:
        validate_live = getattr(item.component, "validate_live_schema", None)
        if not callable(validate_live):
            data["records"] = None
            return _check(
                "extension_state",
                "fail",
                f"{item.spec.name} cannot passively validate its live schema; upgrade it",
                data,
            )
        try:
            validate_live(queue)
        except PersistenceComponentCompatibilityError as exc:
            data["records"] = None
            return _check("extension_state", "fail", str(exc), data)
        except Exception as exc:
            raise TautError(f"{item.spec.name} live-schema inspection failed") from exc
        try:
            records = item.component.dump_records(queue)
            item.component.validate_records(
                item.spec.write_version,
                records,
                core_member_ids=member_ids,
            )
        except (TautError, TypeError, ValueError) as exc:
            data["records"] = None
            return _check(
                "extension_state",
                "fail",
                f"invalid {item.spec.name} live records: {exc}",
                data,
            )
        except Exception as exc:
            raise TautError(f"{item.spec.name} live-record inspection failed") from exc
        record_counts[item.spec.name] = len(records)
    data["records"] = record_counts
    return _check(
        "extension_state",
        "pass",
        "installed durable extensions are readable",
        data,
    )
