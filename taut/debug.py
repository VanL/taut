"""Best-effort capture for exceptions reaching Taut containment boundaries.

This module owns the complete failure-prone path: state lookup, bounded event
construction, local deduplication, and action transport. Its public operation
is deliberately total and returns no result.

Spec reference: docs/specs/02-taut-core.md [TAUT-13].
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import threading
import traceback as traceback_module
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from simplebroker import BrokerTarget, Queue, ResolvedConfig

from taut._constants import META_QUEUE_NAME, __version__
from taut._maintenance import display_target, resolve_existing_target
from taut._redact import redact_sensitive_text
from taut.state import (
    DEBUG_CAPTURE_KEY,
    SqlSidecarTautState,
    dialect_for_taut_target,
)

DEBUG_QUEUE_NAME = "taut.debug"
DEBUG_ACTION_ENV = "TAUT_DEBUG_ACTION"
DEBUG_ACTION_ACTIVE_ENV = "TAUT_DEBUG_ACTION_ACTIVE"

_EVENT_VERSION = 1
_ACTION_TIMEOUT_SECONDS = 2.0
_MAX_TEXT = 4_096
_MAX_TRACEBACK = 65_536
_MAX_FRAMES = 32
_MAX_LOCALS_PER_FRAME = 32
_MAX_LOCAL_REPR = 2_048
_MAX_EVENT_BYTES = 131_072
_LOCAL_CAPTURE_LOCK = threading.Lock()


@dataclass(slots=True)
class _TruncationState:
    occurred: bool = False


def capture_exception(
    exc: Exception,
    *,
    surface: str,
    operation: str,
    db_path: str | Path | None = None,
    broker_target: BrokerTarget | str | None = None,
    broker_config: ResolvedConfig | None = None,
) -> None:
    """Capture ``exc`` if enabled, without ever raising to the caller."""

    if not isinstance(exc, Exception) or DEBUG_ACTION_ACTIVE_ENV in os.environ:
        return
    try:
        target, config = _resolve_capture_target(
            db_path=db_path,
            broker_target=broker_target,
            broker_config=broker_config,
        )
        if not _capture_enabled(target, config):
            return
        event = _build_event(
            exc,
            target=target,
            surface=surface,
            operation=operation,
        )
        payload = _serialize_event(event)
        if DEBUG_ACTION_ENV in os.environ:
            _send_to_action(payload)
        else:
            _write_local(payload, event["sentinel"], target, config)
    except BaseException:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-090] exception
        return


def _resolve_capture_target(
    *,
    db_path: str | Path | None,
    broker_target: BrokerTarget | str | None,
    broker_config: ResolvedConfig | None,
) -> tuple[BrokerTarget | str, ResolvedConfig]:
    if broker_target is None and broker_config is None:
        return resolve_existing_target(db_path)
    if broker_target is None or broker_config is None or db_path is not None:
        raise ValueError(
            "resolved debug capture requires broker_target and broker_config"
        )
    return broker_target, broker_config


def _capture_enabled(
    target: BrokerTarget | str,
    config: ResolvedConfig,
) -> bool:
    queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    try:
        state = SqlSidecarTautState(queue, dialect_for_taut_target(target))
        return state.persistence_meta().get(DEBUG_CAPTURE_KEY) == "1"
    finally:
        queue.close()


def _build_event(
    exc: Exception,
    *,
    target: BrokerTarget | str,
    surface: str,
    operation: str,
) -> dict[str, Any]:
    truncation = _TruncationState()
    frames = _frames(exc.__traceback__, truncation)
    fingerprint_material = {
        "exception": _qualified_type(exc),
        "message": _safe_text(exc, _MAX_TEXT, truncation),
        "frames": [
            [frame["file"], frame["function"], frame["line"]] for frame in frames
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_material,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    event = {
        "type": "taut_debug_event",
        "version": _EVENT_VERSION,
        "captured_at": datetime.now(UTC).isoformat(),
        "target": _bounded(display_target(target), _MAX_TEXT, truncation),
        "surface": _bounded(str(surface), 256, truncation),
        "operation": _bounded(str(operation), 512, truncation),
        "exception": {
            "type": _qualified_type(exc),
            "message": _safe_text(exc, _MAX_TEXT, truncation),
        },
        "traceback": _formatted_traceback(exc, truncation),
        "frames": frames,
        "runtime": {
            "taut_version": __version__,
            "python": _bounded(sys.version, 512, truncation),
            "platform": _bounded(platform.platform(), 512, truncation),
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "thread_name": _bounded(
                threading.current_thread().name,
                512,
                truncation,
            ),
            "executable": _bounded(sys.executable, _MAX_TEXT, truncation),
            "cwd": _safe_cwd(truncation),
        },
        "fingerprint": fingerprint,
        "sentinel": f"taut-debug:{fingerprint}",
        "truncated": False,
    }
    event["truncated"] = truncation.occurred
    return event


def _frames(
    tb: TracebackType | None,
    truncation: _TruncationState,
) -> list[dict[str, Any]]:
    traceback_frames: list[TracebackType] = []
    while tb is not None:
        traceback_frames.append(tb)
        tb = tb.tb_next
    if len(traceback_frames) > _MAX_FRAMES:
        truncation.occurred = True
        head_count = _MAX_FRAMES // 2
        traceback_frames = [
            *traceback_frames[:head_count],
            *traceback_frames[-(_MAX_FRAMES - head_count) :],
        ]

    captured: list[dict[str, Any]] = []
    for tb in traceback_frames:
        frame = tb.tb_frame
        local_values: dict[str, str] = {}
        for name in sorted(frame.f_locals, key=str)[:_MAX_LOCALS_PER_FRAME]:
            local_values[_bounded(str(name), 256, truncation)] = _safe_repr(
                frame.f_locals[name],
                _MAX_LOCAL_REPR,
                truncation,
            )
        if len(frame.f_locals) > _MAX_LOCALS_PER_FRAME:
            truncation.occurred = True
        captured.append(
            {
                "file": _bounded(frame.f_code.co_filename, _MAX_TEXT, truncation),
                "function": _bounded(frame.f_code.co_name, 512, truncation),
                "line": tb.tb_lineno,
                "locals": local_values,
            }
        )
    return captured


def _formatted_traceback(
    exc: Exception,
    truncation: _TruncationState,
) -> str:
    try:
        value = "".join(
            traceback_module.format_exception(type(exc), exc, exc.__traceback__)
        )
    except BaseException:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-090] exception
        value = f"{_qualified_type(exc)}: {_safe_text(exc, _MAX_TEXT, truncation)}"
    return _bounded(value, _MAX_TRACEBACK, truncation)


def _qualified_type(value: object) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _safe_text(
    value: object,
    limit: int,
    truncation: _TruncationState,
) -> str:
    try:
        rendered = str(value)
    except BaseException as failure:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-090] exception
        rendered = f"<unprintable {_qualified_type(value)}: {_qualified_type(failure)}>"
    return _bounded(rendered, limit, truncation)


def _safe_repr(
    value: object,
    limit: int,
    truncation: _TruncationState,
) -> str:
    try:
        rendered = repr(value)
    except BaseException as failure:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-090] exception
        rendered = (
            f"<unrepresentable {_qualified_type(value)}: {_qualified_type(failure)}>"
        )
    return _bounded(rendered, limit, truncation)


def _bounded(
    value: str,
    limit: int,
    truncation: _TruncationState | None = None,
) -> str:
    if len(value) <= limit:
        return value
    if truncation is not None:
        truncation.occurred = True
    return value[: max(0, limit - 1)] + "…"


def _safe_cwd(truncation: _TruncationState) -> str:
    try:
        return _bounded(os.getcwd(), _MAX_TEXT, truncation)
    except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-090] exception
        return f"<unavailable: {_qualified_type(exc)}>"


def _serialize_event(event: dict[str, Any]) -> str:
    payload = _json_payload(event)
    if len(payload.encode("utf-8")) <= _MAX_EVENT_BYTES:
        return payload

    event["truncated"] = True
    event["traceback"] = _bounded(str(event["traceback"]), 8_192)
    for frame in event["frames"]:
        local_items = list(frame["locals"].items())[:8]
        frame["locals"] = {
            _bounded(name, 128): _bounded(value, 512) for name, value in local_items
        }
    payload = _json_payload(event)
    if len(payload.encode("utf-8")) <= _MAX_EVENT_BYTES:
        return payload

    event["traceback"] = _bounded(str(event["traceback"]), 2_048)
    event["exception"]["message"] = _bounded(
        str(event["exception"]["message"]),
        1_024,
    )
    event["frames"] = [
        {
            "file": _bounded(str(frame["file"]), 512),
            "function": _bounded(str(frame["function"]), 256),
            "line": frame["line"],
            "locals": {},
        }
        for frame in event["frames"]
    ]
    return _json_payload(event)


def _json_payload(event: dict[str, Any]) -> str:
    return redact_sensitive_text(
        json.dumps(
            event,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _write_local(
    payload: str,
    sentinel: str,
    target: BrokerTarget | str,
    config: ResolvedConfig,
) -> None:
    with _LOCAL_CAPTURE_LOCK:
        queue = Queue(DEBUG_QUEUE_NAME, db_path=target, config=config)
        try:
            duplicate = False
            try:
                duplicate = bool(
                    queue.find_message_ids(
                        body_contains=sentinel,
                        limit=1,
                        include_claimed=True,
                    )
                )
            except BaseException:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-090] exception
                duplicate = False
            if not duplicate:
                queue.write(payload)
        finally:
            queue.close()


def _send_to_action(payload: str) -> None:
    try:
        argv = shlex.split(os.environ[DEBUG_ACTION_ENV], posix=True)
        if not argv:
            return
        env = os.environ.copy()
        env[DEBUG_ACTION_ACTIVE_ENV] = "1"
        subprocess.run(
            argv,
            input=payload + "\n",
            text=True,
            encoding="utf-8",
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=_ACTION_TIMEOUT_SECONDS,
            check=False,
        )
    except BaseException:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-090] exception
        return


__all__ = ["DEBUG_QUEUE_NAME", "capture_exception"]
