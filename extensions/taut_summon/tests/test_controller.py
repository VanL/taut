"""Public Summon embedding contract tests ([SUM-13])."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from simplebroker import Queue
from taut_summon._control import control_in_queue_name
from taut_summon._state import (
    capture_driver_evidence,
    ensure_summon_schema,
    record_session,
)
from taut_summon.controller import _status_from_reply

from taut import TautClient
from taut.client import Member

pytestmark = pytest.mark.sqlite_only

PROJECT_ROOT = Path(__file__).resolve().parents[3]

EXPECTED_PUBLIC_EXPORTS = [
    "ActivityEvent",
    "AdapterError",
    "AdapterEvent",
    "AdapterHandle",
    "AssistantTextEvent",
    "DriverUnresponsive",
    "ExitEvent",
    "NothingSummoned",
    "ProviderAdapter",
    "ScriptedAdapter",
    "SessionEvent",
    "ShellSummonInteraction",
    "StopResult",
    "SummonController",
    "SummonInteraction",
    "SummonOperationError",
    "SummonRequest",
    "SummonStatus",
    "SummonedMember",
    "TerminalAvailability",
    "TerminalIntent",
    "TerminalLease",
    "UnknownAdapterError",
    "adapter_names",
    "get_adapter",
]


def _member() -> Member:
    return Member(
        member_id="m_reviewer",
        name="reviewer",
        aliases=(),
        kind="agent",
        presence="active",
        last_active_ts=1,
    )


def _status_reply() -> dict[str, Any]:
    return {
        "command": "STATUS",
        "status": "ok",
        "request_id": "req-1",
        "driver": "alive",
        "provider": "scripted",
        "session_id": "sess-1",
        "thread_count": 1,
        "cursor_lag": {"general": 0},
        "control_health": "ok",
    }


def _create_live_member(db: Path, *, name: str = "reviewer") -> Member:
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name=name)
    try:
        client.join("general")
        member = client.last_created_member
        assert member is not None and member.token is not None
    finally:
        client.close()
    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        pid, start = capture_driver_evidence(os.getpid())
        record_session(
            queue,
            member_id=member.member_id,
            token=member.token,
            provider="scripted",
            driver_pid=pid,
            driver_start_time=start,
            updated_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()
    return member


def test_public_controller_models_have_exact_fields() -> None:
    from taut_summon import (
        DriverUnresponsive,
        NothingSummoned,
        StopResult,
        SummonedMember,
        SummonOperationError,
        SummonRequest,
        SummonStatus,
    )

    assert tuple(field.name for field in fields(SummonRequest)) == (
        "name",
        "threads",
        "terminal",
        "persona",
        "system_prompt_file",
        "rate_limit",
        "attach",
        "detach",
        "provider_flag",
        "takeover",
    )
    assert tuple(field.name for field in fields(SummonedMember)) == (
        "member_id",
        "name",
        "provider",
        "provider_session_id",
    )
    assert tuple(field.name for field in fields(SummonStatus)) == (
        "member_id",
        "name",
        "driver",
        "provider",
        "provider_session_id",
        "thread_count",
        "cursor_lag",
        "details",
    )
    assert tuple(field.name for field in fields(StopResult)) == (
        "member_id",
        "name",
    )
    assert issubclass(NothingSummoned, SummonOperationError)
    assert issubclass(DriverUnresponsive, SummonOperationError)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("thread_count", True),
        ("cursor_lag", {"general": True}),
        ("extra", {"nested": "object"}),
        ("extra", float("nan")),
    ],
)
def test_status_validation_rejects_non_contract_values(
    field: str, value: object
) -> None:
    from taut_summon import SummonOperationError

    reply = _status_reply()
    reply[field] = value

    with pytest.raises(SummonOperationError, match="invalid STATUS"):
        _status_from_reply(_member(), reply)


def test_status_mapping_copies_structured_fields_and_excludes_protocol_keys() -> None:
    reply = _status_reply()

    status = _status_from_reply(_member(), reply)

    assert status.cursor_lag == {"general": 0}
    assert status.details == {"control_health": "ok"}
    raw_lag = reply["cursor_lag"]
    assert isinstance(raw_lag, dict)
    raw_lag["general"] = 9
    reply["control_health"] = "degraded"
    assert status.cursor_lag == {"general": 0}
    assert status.details == {"control_health": "ok"}


def test_controller_provider_names_are_sorted_without_constructing_adapters() -> None:
    from taut_summon import SummonController

    assert SummonController().provider_names() == (
        "claude",
        "claude-stream",
        "coder",
        "codex",
        "grok",
        "kimi",
        "opencode",
        "pi",
        "pty",
        "qwen",
        "scripted",
    )


def test_controller_empty_list_returns_empty_tuple_without_printing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from taut_summon import SummonController

    controller = SummonController(db_path=str(tmp_path / "missing.db"))

    assert controller.list_live() == ()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_controller_lists_live_sessions_as_typed_current_members(
    tmp_path: Path,
) -> None:
    from taut_summon import SummonController, SummonedMember

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    created: list[tuple[str, str]] = []
    for name in ("reviewer", "archivist"):
        client = TautClient(db_path=db, as_name=name)
        try:
            client.join("general")
            member = client.last_created_member
            assert member is not None and member.token is not None
            created.append((member.member_id, member.token))
        finally:
            client.close()
    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        pid, start = capture_driver_evidence(os.getpid())
        record_session(
            queue,
            member_id=created[0][0],
            token=created[0][1],
            provider="scripted",
            provider_session_id="sess-live",
            driver_pid=pid,
            driver_start_time=start,
            updated_ts=queue.generate_timestamp(),
        )
        record_session(
            queue,
            member_id=created[1][0],
            token=created[1][1],
            provider="claude",
            provider_session_id="sess-dead",
            updated_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()

    assert SummonController(db_path=db).list_live() == (
        SummonedMember(
            member_id=created[0][0],
            name="reviewer",
            provider="scripted",
            provider_session_id="sess-live",
        ),
    )


def test_controller_status_and_stop_use_real_correlated_control_plane(
    summon_db: Path,
    driver_factory: Callable[..., Any],
) -> None:
    from taut_summon import StopResult, SummonController, SummonStatus

    driver = driver_factory(summon_db, "reviewer", provider="scripted")
    driver.wait_for_start()
    controller = SummonController(db_path=summon_db)

    first = controller.status("reviewer")

    assert isinstance(first, SummonStatus)
    assert first.name == "reviewer"
    assert first.driver == "alive"
    assert first.provider == "scripted"
    assert first.provider_session_id
    assert first.thread_count == 1
    assert first.cursor_lag == {"general": 0}
    assert first.details == {
        "control_health": "ok",
        "rate_breaches": 0,
        "rate_limited": False,
    }
    first.cursor_lag["general"] = 99
    first.details["control_health"] = "mutated"
    second = controller.status("reviewer")
    assert second.cursor_lag == {"general": 0}
    assert second.details["control_health"] == "ok"

    result = controller.stop("reviewer")

    assert result == StopResult(member_id=first.member_id, name="reviewer")
    assert driver.wait() == 0


@pytest.mark.parametrize("operation", ["status", "stop"])
def test_controller_unresponsive_driver_uses_typed_error_over_real_queues(
    operation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import taut_summon.controller as controller_module
    from taut_summon import DriverUnresponsive, SummonController

    db = tmp_path / ".taut.db"
    _create_live_member(db)
    monkeypatch.setattr(controller_module, "_STATUS_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(controller_module, "_STOP_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(DriverUnresponsive, match="driver did not"):
        getattr(SummonController(db_path=db), operation)("reviewer")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_controller_refuses_error_stop_ack_before_release_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.controller as controller_module
    from taut_summon import SummonController, SummonOperationError

    db = tmp_path / ".taut.db"
    member = _create_live_member(db)
    responder_errors: list[BaseException] = []

    def respond() -> None:
        request_queue = Queue(control_in_queue_name(member.member_id), db_path=str(db))
        try:
            deadline = time.monotonic() + 2.0
            body: str | None = None
            while body is None and time.monotonic() < deadline:
                candidate = request_queue.read_one()
                body = candidate if isinstance(candidate, str) else None
                if body is None:
                    time.sleep(0.01)
            assert body is not None
            request = json.loads(body)
            reply_queue = Queue(request["reply_to"], db_path=str(db))
            try:
                reply_queue.write(
                    json.dumps(
                        {
                            "command": "STOP",
                            "status": "error",
                            "request_id": request["request_id"],
                            "error": "driver slot release could not be confirmed",
                        }
                    )
                )
            finally:
                reply_queue.close()
        except BaseException as exc:
            responder_errors.append(exc)
        finally:
            request_queue.close()

    monkeypatch.setattr(controller_module, "_STOP_TIMEOUT_SECONDS", 2.0)
    responder = threading.Thread(target=respond)
    responder.start()
    try:
        with pytest.raises(
            SummonOperationError, match="driver slot release could not be confirmed"
        ) as caught:
            SummonController(db_path=db).stop("reviewer")
    finally:
        responder.join(timeout=3.0)

    assert type(caught.value) is SummonOperationError
    assert not responder.is_alive()
    assert responder_errors == []


def test_package_facade_is_lazy_and_preserves_introspection() -> None:
    code = """
import json
import sys

import taut_summon

before = sorted(name for name in sys.modules if name.startswith("taut_summon"))
all_visible = set(taut_summon.__all__) <= set(dir(taut_summon))
request_type = taut_summon.SummonRequest
after_request = sorted(name for name in sys.modules if name.startswith("taut_summon"))
controller_type = taut_summon.SummonController
after_controller = sorted(name for name in sys.modules if name.startswith("taut_summon"))
print(json.dumps({
    "before": before,
    "all_visible": all_visible,
    "request_module": request_type.__module__,
    "after_request": after_request,
    "controller_module": controller_type.__module__,
    "after_controller": after_controller,
}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["before"] == ["taut_summon"]
    assert payload["all_visible"] is True
    assert payload["request_module"] == "taut_summon.models"
    assert payload["after_request"] == ["taut_summon", "taut_summon.models"]
    assert payload["controller_module"] == "taut_summon.controller"
    assert "taut_summon._driver" not in payload["after_controller"]


def test_package_facade_preserves_exact_public_exports_and_object_identity() -> None:
    import taut_summon
    from taut_summon import _adapter, _scripted
    from taut_summon.controller import SummonController
    from taut_summon.interaction import ShellSummonInteraction, TerminalLease
    from taut_summon.models import SummonRequest

    assert taut_summon.__all__ == EXPECTED_PUBLIC_EXPORTS
    assert taut_summon.ActivityEvent is _adapter.ActivityEvent
    assert taut_summon.ScriptedAdapter is _scripted.ScriptedAdapter
    assert taut_summon.adapter_names is _adapter.adapter_names
    assert taut_summon.get_adapter is _adapter.get_adapter
    assert taut_summon.SummonController is SummonController
    assert taut_summon.SummonRequest is SummonRequest
    assert taut_summon.ShellSummonInteraction is ShellSummonInteraction
    assert taut_summon.TerminalLease is TerminalLease
    missing_name = "missing_public_name"
    with pytest.raises(AttributeError, match="missing_public_name"):
        getattr(taut_summon, missing_name)


def test_static_typing_rejects_unknown_summon_export(tmp_path: Path) -> None:
    probe = tmp_path / "unknown_summon_export.py"
    probe.write_text(
        "import taut_summon\n\ncontroller = taut_summon.SummonControllr\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(PROJECT_ROOT / "pyproject.toml"),
            str(probe),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert 'Module has no attribute "SummonControllr"' in result.stdout


def test_command_manifest_has_exact_lightweight_specs_and_import_floor() -> None:
    script = """
import json
import sys
from taut_summon.command_manifest import dismiss, summon

def shape(spec):
    return {
        "api": spec.command_api_version,
        "name": spec.name,
        "summary": spec.summary,
        "globals": sorted(item.value for item in spec.post_verb_globals),
        "implementation": spec.implementation,
    }

print(json.dumps({
    "summon": shape(summon),
    "dismiss": shape(dismiss),
    "loaded": sorted(sys.modules),
}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summon"] == {
        "api": 1,
        "name": "summon",
        "summary": "Start or resume a summoned agent harness.",
        "globals": ["db"],
        "implementation": "taut_summon.commands.summon:create_command",
    }
    assert payload["dismiss"] == {
        "api": 1,
        "name": "dismiss",
        "summary": "Stop one live summoned agent harness.",
        "globals": ["db"],
        "implementation": "taut_summon.commands.dismiss:create_command",
    }
    loaded = set(payload["loaded"])
    assert "taut_summon.command_manifest" in loaded
    assert "taut_summon.controller" not in loaded
    assert "taut_summon._adapter" not in loaded
    assert "taut_summon._control" not in loaded
    assert "taut_summon._driver" not in loaded
    assert "taut_summon._pty" not in loaded
    assert "taut_summon._state" not in loaded
    assert "taut_summon.commands.summon" not in loaded
    assert "taut_summon.commands.dismiss" not in loaded


def test_extension_metadata_registers_both_official_command_manifests() -> None:
    metadata = tomllib.loads(
        (PROJECT_ROOT / "extensions/taut_summon/pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert metadata["project"]["entry-points"]["taut.commands"] == {
        "summon": "taut_summon.command_manifest:summon",
        "dismiss": "taut_summon.command_manifest:dismiss",
    }


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["run", "--help"],
        ["stop", "--help"],
        ["status", "--help"],
    ],
)
def test_standalone_help_does_not_import_runtime_subsystems(argv: list[str]) -> None:
    code = f"""
import contextlib
import io
import json
import sys

from taut_summon.cli import main

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    try:
        rc = main({argv!r})
    except SystemExit as exc:
        rc = exc.code
loaded = sorted(name for name in sys.modules if name.startswith(("taut", "simplebroker")))
print(json.dumps({{"rc": rc, "loaded": loaded}}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["rc"] == 0
    loaded = payload["loaded"]
    forbidden = (
        "simplebroker",
        "taut.client",
        "taut.state",
        "taut_summon._adapter",
        "taut_summon._control",
        "taut_summon._driver",
        "taut_summon._pty",
        "taut_summon._state",
        "taut_summon.controller",
        "taut_summon.interaction",
    )
    assert not [name for name in loaded if name.startswith(forbidden)]
