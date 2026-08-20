"""Public debug-capture behavior.

Spec references:
- docs/specs/02-taut-core.md [TAUT-13]
- docs/specs/09-system-doctor.md [DOCT-4.7]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import shlex
import subprocess
import sys
import time
from collections.abc import Iterable
from io import StringIO
from pathlib import Path
from typing import cast

import pytest
from simplebroker import Queue

from taut import TautClient
from taut._constants import META_QUEUE_NAME
from taut._exceptions import NotInitializedError, TautError
from taut.debug import capture_exception
from tests.conftest import run_cli

pytestmark = pytest.mark.sqlite_only


def _capture_same_failure(db_path: Path) -> None:
    local_evidence = {"draft": "sensitive diagnostic value"}
    _ = local_evidence
    del _
    try:
        raise ValueError("repeatable failure")
    except ValueError as exc:
        capture_exception(
            exc,
            db_path=db_path,
            surface="test",
            operation="debug.capture",
        )


class _Unrepresentable:
    def __repr__(self) -> str:
        raise RuntimeError("repr failed")


def _capture_bounded_failure(db_path: Path) -> None:
    huge_local = "λ" * 200_000
    bad_local = _Unrepresentable()
    _ = huge_local, bad_local
    del _
    try:
        raise RuntimeError("x" * 10_000)
    except RuntimeError as exc:
        capture_exception(
            exc,
            db_path=db_path,
            surface="test",
            operation="debug.bounds",
        )


def _capture_chained_failure(db_path: Path) -> None:
    try:
        try:
            raise LookupError("inner failure")
        except LookupError as inner:
            raise RuntimeError("outer failure") from inner
    except RuntimeError as exc:
        capture_exception(
            exc,
            db_path=db_path,
            surface="test",
            operation="debug.chain",
        )


def _capture_unicode_failure(db_path: Path) -> None:
    try:
        raise ValueError("Unicode failure: λ 雪")
    except ValueError as exc:
        capture_exception(
            exc,
            db_path=db_path,
            surface="test",
            operation="debug.unicode",
        )


def _capture_secret_failure(db_path: Path) -> None:
    provider_secret = "sk-ant-api03-" + "A" * 93 + "AA"
    database_password = "debug-db-password"
    child_env = {
        "ANTHROPIC_API_KEY": provider_secret,
        "TAUT_TOKEN": "taut-continuity-value",
    }
    dsn = f"postgresql://taut:{database_password}@db.example/taut"
    _ = child_env, dsn
    del _
    try:
        raise RuntimeError('capture failed password="debug exception password"')
    except RuntimeError as exc:
        capture_exception(
            exc,
            db_path=db_path,
            surface="test",
            operation="debug.redaction",
        )


def _capture_deep_failure(db_path: Path) -> None:
    def descend(depth: int) -> None:
        origin_marker = "innermost evidence" if depth == 0 else ""
        _ = origin_marker
        del _
        if depth == 0:
            raise RuntimeError("deep failure")
        descend(depth - 1)

    try:
        descend(50)
    except RuntimeError as exc:
        capture_exception(
            exc,
            db_path=db_path,
            surface="test",
            operation="debug.deep",
        )


def _debug_messages(db_path: Path) -> list[str]:
    queue = Queue("taut.debug", db_path=str(db_path))
    try:
        messages = queue.peek(all_messages=True, include_claimed=True)
        assert messages is not None
        return list(cast(Iterable[str], messages))
    finally:
        queue.close()


def test_debug_capture_setting_is_idempotent_and_visible_in_doctor(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.1] [DOCT-4.7] The public setting drives passive status."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)

    TautClient.set_debug_capture(True, db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    enabled = TautClient.doctor(db_path=db_path)

    assert enabled.checks[-1].name == "debug_capture"
    assert enabled.checks[-1].status == "pass"
    assert enabled.checks[-1].data == {"enabled": True, "sink": "local"}

    TautClient.set_debug_capture(False, db_path=db_path)
    TautClient.set_debug_capture(False, db_path=db_path)
    disabled = TautClient.doctor(db_path=db_path)

    assert disabled.checks[-1].name == "debug_capture"
    assert disabled.checks[-1].status == "pass"
    assert disabled.checks[-1].data == {"enabled": False, "sink": "disabled"}


def test_system_debug_enable_and_disable_are_silent(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.1] The actor-free CLI mutates only the operational setting."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)

    enabled = run_cli(
        "--db",
        str(db_path),
        "system",
        "debug",
        "enable",
        cwd=tmp_path,
    )

    assert enabled == (0, "", "")
    assert TautClient.doctor(db_path=db_path).checks[-1].data == {
        "enabled": True,
        "sink": "local",
    }

    disabled = run_cli(
        "system",
        "debug",
        "disable",
        "--db",
        str(db_path),
        cwd=tmp_path,
    )

    assert disabled == (0, "", "")
    assert TautClient.doctor(db_path=db_path).checks[-1].data == {
        "enabled": False,
        "sink": "disabled",
    }


@pytest.mark.parametrize("malformed_value", ["", "0", " ", "malformed"])
def test_setting_commands_repair_malformed_operational_state(
    tmp_path: Path,
    clean_env: None,
    malformed_value: str,
) -> None:
    """[TAUT-13.1] Enable and disable are the supported repair operations."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
                ("debug_capture", malformed_value),
            )
    finally:
        queue.close()

    malformed = TautClient.doctor(db_path=db_path)
    assert malformed.checks[-1].status == "fail"
    assert malformed.checks[-1].data == {"enabled": None, "sink": None}
    assert (
        next(
            check for check in malformed.checks if check.name == "extension_state"
        ).status
        == "pass"
    )

    TautClient.set_debug_capture(True, db_path=db_path)
    assert TautClient.doctor(db_path=db_path).checks[-1].data == {
        "enabled": True,
        "sink": "local",
    }

    queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_meta SET value = ? WHERE key = ?",
                ("bad-again", "debug_capture"),
            )
    finally:
        queue.close()

    TautClient.set_debug_capture(False, db_path=db_path)
    assert TautClient.doctor(db_path=db_path).checks[-1].data == {
        "enabled": False,
        "sink": "disabled",
    }


@pytest.mark.parametrize("output_mode", ["--json", "--quiet"])
def test_system_debug_success_is_silent_in_every_output_mode(
    tmp_path: Path,
    clean_env: None,
    output_mode: str,
) -> None:
    """[TAUT-13.1] Output globals do not synthesize a success record."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)

    result = run_cli(
        "system",
        "debug",
        "enable",
        output_mode,
        "--db",
        str(db_path),
        cwd=tmp_path,
    )

    assert result == (0, "", "")


@pytest.mark.parametrize(
    "args",
    [
        ("--as", "van", "system", "debug", "enable"),
        ("--token", "secret", "system", "debug", "enable"),
        ("--timestamps", "system", "debug", "enable"),
        ("system", "debug", "enable", "--as", "van"),
        ("system", "debug", "enable", "extra"),
    ],
)
def test_system_debug_rejects_identity_timestamps_and_extra_arguments(
    tmp_path: Path,
    clean_env: None,
    args: tuple[str, ...],
) -> None:
    """[TAUT-13.1] The setting operation stays actor-free and closed."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    expanded = (*args, "--db", str(db_path)) if args[0] == "system" else args

    rc, out, err = run_cli(
        *expanded,
        cwd=tmp_path,
        env={"TAUT_DB": str(db_path)},
    )

    assert rc == 1
    assert out == ""
    assert err
    assert "Traceback" not in err
    assert TautClient.doctor(db_path=db_path).checks[-1].data["enabled"] is False


@pytest.mark.parametrize("action", ["", "collector --token=hunter2"])
def test_doctor_reports_action_from_its_own_environment(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    """[DOCT-4.7] Presence, even empty, selects the advisory action sink."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    monkeypatch.setenv("TAUT_DEBUG_ACTION", action)

    report = TautClient.doctor(db_path=db_path)

    assert report.healthy is True
    assert report.checks[-1].data == {"enabled": True, "sink": "action"}
    assert "hunter2" not in repr(report)


@pytest.mark.parametrize("value", [1, 0, None, "true"])
def test_public_setting_requires_exact_bool(tmp_path: Path, value: object) -> None:
    """[TAUT-13.1] Integers and truthy values do not silently toggle state."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)

    with pytest.raises(TypeError, match="enabled must be a bool"):
        TautClient.set_debug_capture(value, db_path=db_path)  # type: ignore[arg-type]

    assert TautClient.doctor(db_path=db_path).checks[-1].data == {
        "enabled": False,
        "sink": "disabled",
    }


@pytest.mark.parametrize("existing_file", [False, True])
def test_setting_requires_initialized_workspace(
    tmp_path: Path,
    clean_env: None,
    existing_file: bool,
) -> None:
    """[TAUT-13.1] Setting mutation never initializes a target as a side effect."""

    db_path = tmp_path / "workspace.db"
    if existing_file:
        db_path.touch()

    with pytest.raises(NotInitializedError, match="No taut database found"):
        TautClient.set_debug_capture(True, db_path=db_path)


def test_logical_dump_omits_debug_state_and_load_preserves_destination_setting(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[PIO-5] [PIO-7] Debug state is operational, not restored content."""

    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    dump_path = tmp_path / "workspace.tautdump"
    TautClient.init(db_path=source)
    TautClient.set_debug_capture(True, db_path=source)

    TautClient.dump(output=dump_path, db_path=source)

    assert b"debug_capture" not in dump_path.read_bytes()

    TautClient.init(db_path=destination)
    TautClient.set_debug_capture(True, db_path=destination)
    report = TautClient.load(input_path=dump_path, db_path=destination)

    assert report.applied is True
    assert TautClient.doctor(db_path=destination).checks[-1].data == {
        "enabled": True,
        "sink": "local",
    }


def test_logical_dump_rejects_malformed_debug_state_without_replacing_output(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[PIO-5] Malformed operational state fails before atomic publication."""

    source = tmp_path / "source.db"
    dump_path = tmp_path / "workspace.tautdump"
    TautClient.init(db_path=source)
    dump_path.write_bytes(b"preserve me")
    queue = Queue(META_QUEUE_NAME, db_path=str(source))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
                ("debug_capture", "malformed"),
            )
    finally:
        queue.close()

    with pytest.raises(TautError, match="debug capture setting is malformed"):
        TautClient.dump(output=dump_path, db_path=source)

    assert dump_path.read_bytes() == b"preserve me"


def test_load_rejects_malformed_destination_debug_state(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[PIO-7] Load accepts only absent or exactly enabled destination state."""

    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    dump_path = tmp_path / "workspace.tautdump"
    TautClient.init(db_path=source)
    TautClient.dump(output=dump_path, db_path=source)
    TautClient.init(db_path=destination)
    queue = Queue(META_QUEUE_NAME, db_path=str(destination))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
                ("debug_capture", "malformed"),
            )
    finally:
        queue.close()

    with pytest.raises(TautError, match="load destination is not fresh"):
        TautClient.load(input_path=dump_path, db_path=destination)

    assert TautClient.doctor(db_path=destination).checks[-1].status == "fail"


def test_logical_dump_omits_retained_debug_events(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[PIO-5] Diagnostic events are local operational data."""

    source = tmp_path / "source.db"
    dump_path = tmp_path / "workspace.tautdump"
    sentinel = "taut-debug:not-logical-content"
    TautClient.init(db_path=source)
    queue = Queue("taut.debug", db_path=str(source))
    try:
        queue.write(sentinel)
    finally:
        queue.close()

    TautClient.dump(output=dump_path, db_path=source)

    assert sentinel.encode() not in dump_path.read_bytes()


@pytest.mark.parametrize("claimed", [False, True])
def test_retained_debug_event_makes_load_destination_nonfresh(
    tmp_path: Path,
    clean_env: None,
    claimed: bool,
) -> None:
    """[PIO-7] Pending and claimed diagnostic events both block logical load."""

    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    dump_path = tmp_path / "workspace.tautdump"
    TautClient.init(db_path=source)
    TautClient.dump(output=dump_path, db_path=source)
    TautClient.init(db_path=destination)
    queue = Queue("taut.debug", db_path=str(destination))
    try:
        queue.write("taut-debug:retained")
        if claimed:
            assert queue.read_one() == "taut-debug:retained"
    finally:
        queue.close()

    with pytest.raises(TautError, match="load destination is not fresh"):
        TautClient.load(input_path=dump_path, db_path=destination)


def test_local_capture_writes_versioned_sensitive_event_and_deduplicates(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.2] [TAUT-13.3] Local capture uses the public broker boundary."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)

    _capture_same_failure(db_path)
    _capture_same_failure(db_path)

    messages = _debug_messages(db_path)
    assert len(messages) == 1
    event = json.loads(messages[0])
    assert event["type"] == "taut_debug_event"
    assert event["version"] == 1
    assert event["truncated"] is False
    assert event["surface"] == "test"
    assert event["operation"] == "debug.capture"
    assert event["exception"]["type"].endswith("ValueError")
    assert event["exception"]["message"] == "repeatable failure"
    assert "_capture_same_failure" in event["traceback"]
    assert any(
        "sensitive diagnostic value" in value
        for frame in event["frames"]
        for value in frame["locals"].values()
    )
    assert event["sentinel"] == f"taut-debug:{event['fingerprint']}"
    assert event["sentinel"] in messages[0]
    assert event["captured_at"].endswith("+00:00")
    assert set(event["runtime"]) == {
        "cwd",
        "executable",
        "pid",
        "platform",
        "python",
        "taut_version",
        "thread_id",
        "thread_name",
    }


def test_fingerprint_changes_with_message_or_failure_stack(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.3] Fingerprints are deterministic over failure identity."""

    from taut import debug as debug_module
    from taut._maintenance import resolve_existing_target

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    target, _config = resolve_existing_target(db_path)

    def event_for(message: str) -> dict[str, object]:
        try:
            raise ValueError(message)
        except ValueError as exc:
            return debug_module._build_event(
                exc,
                target=target,
                surface="test",
                operation="fingerprint",
            )

    first = event_for("one")
    repeat = event_for("one")
    changed_message = event_for("two")
    try:
        raise ValueError("one")
    except ValueError as exc:
        changed_stack = debug_module._build_event(
            exc,
            target=target,
            surface="test",
            operation="fingerprint",
        )

    assert first["fingerprint"] == repeat["fingerprint"]
    assert first["fingerprint"] != changed_message["fingerprint"]
    assert first["fingerprint"] != changed_stack["fingerprint"]


def test_local_dedup_includes_claimed_rows_and_delete_allows_replay(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.3] Dedup lasts exactly as long as a matching row is retained."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    _capture_same_failure(db_path)
    queue = Queue("taut.debug", db_path=str(db_path))
    try:
        first = queue.peek(with_timestamps=True)
        assert isinstance(first, tuple)
        body, message_id = first
        assert queue.read_one() == body
    finally:
        queue.close()

    _capture_same_failure(db_path)
    assert len(_debug_messages(db_path)) == 1

    queue = Queue("taut.debug", db_path=str(db_path))
    try:
        assert queue.delete(message_id=message_id) is True
    finally:
        queue.close()
    _capture_same_failure(db_path)
    assert len(_debug_messages(db_path)) == 1


def test_event_bounds_remain_valid_json_and_mark_truncation(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.3] Large and hostile locals cannot break the event envelope."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)

    _capture_bounded_failure(db_path)

    messages = _debug_messages(db_path)
    assert len(messages) == 1
    assert len(messages[0].encode("utf-8")) <= 131_072
    event = json.loads(messages[0])
    assert event["truncated"] is True
    assert any(
        "unrepresentable" in value
        for frame in event["frames"]
        for value in frame["locals"].values()
    )


def test_formatted_traceback_preserves_exception_chain(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.3] Cause and context evidence remains in the bounded traceback."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)

    _capture_chained_failure(db_path)

    event = json.loads(_debug_messages(db_path)[0])
    assert "inner failure" in event["traceback"]
    assert "outer failure" in event["traceback"]
    assert "direct cause" in event["traceback"]


def test_deep_stack_retains_innermost_frame_evidence(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.3] Frame bounds retain both entry context and failure origin."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)

    _capture_deep_failure(db_path)

    event = json.loads(_debug_messages(db_path)[0])
    assert event["truncated"] is True
    assert len(event["frames"]) == 32
    assert any(
        "innermost evidence" in value
        for frame in event["frames"]
        for value in frame["locals"].values()
    )


def test_disabled_capture_and_action_descendant_marker_do_nothing(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.2] [TAUT-13.4] Disabled and recursive calls are inert."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    _capture_same_failure(db_path)
    assert _debug_messages(db_path) == []

    TautClient.set_debug_capture(True, db_path=db_path)
    monkeypatch.setenv("TAUT_DEBUG_ACTION_ACTIVE", "1")
    _capture_same_failure(db_path)
    assert _debug_messages(db_path) == []


def test_action_sink_receives_json_and_replaces_local_storage(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.4] Action transport uses POSIX argv parsing and stdin."""

    db_path = tmp_path / "workspace.db"
    action_dir = tmp_path / "action path"
    action_dir.mkdir()
    output = action_dir / "captured event.json"
    fixture = Path(__file__).parent / "fixtures" / "debug_action.py"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    # Force the Windows failure mode on every platform. The action transport is
    # UTF-8 even when a Python action inherits a non-UTF-8 text-codec default.
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.setenv(
        "TAUT_DEBUG_ACTION",
        " ".join(
            shlex.quote(value) for value in (sys.executable, str(fixture), str(output))
        ),
    )

    _capture_unicode_failure(db_path)

    event = json.loads(output.read_text(encoding="utf-8"))
    assert event["sentinel"].startswith("taut-debug:")
    assert event["exception"]["message"] == "Unicode failure: λ 雪"
    assert output.read_bytes().endswith(b"\n")
    assert output.with_suffix(".marker").read_text(encoding="utf-8") == "1"
    assert _debug_messages(db_path) == []


def test_local_and_action_sinks_receive_same_redacted_json(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.3.1] Both real sinks share final-text value redaction."""

    db_path = tmp_path / "workspace.db"
    output = tmp_path / "action.json"
    fixture = Path(__file__).parent / "fixtures" / "debug_action.py"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)

    _capture_secret_failure(db_path)
    local_payload = _debug_messages(db_path)[0]

    monkeypatch.setenv(
        "TAUT_DEBUG_ACTION",
        " ".join(
            shlex.quote(value) for value in (sys.executable, str(fixture), str(output))
        ),
    )
    _capture_secret_failure(db_path)
    action_payload = output.read_text(encoding="utf-8").rstrip("\n")

    for payload in (local_payload, action_payload):
        event = json.loads(payload)
        assert event["exception"]["message"] == ('capture failed password="<redacted>"')
        assert "ANTHROPIC_API_KEY" in payload
        assert "TAUT_TOKEN" in payload
        assert "taut-continuity-value" in payload
        assert "debug exception password" not in payload
        assert "debug-db-password" not in payload
        assert "sk-ant-api03-" + "A" * 93 + "AA" not in payload

    local_event = json.loads(local_payload)
    action_event = json.loads(action_payload)
    local_event.pop("captured_at")
    action_event.pop("captured_at")
    assert action_event == local_event


def test_redaction_failure_drops_event_without_sink_fallback(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.5] Redaction failure is contained and disclosure-fail-closed."""

    db_path = tmp_path / "workspace.db"
    output = tmp_path / "action-must-not-exist.json"
    fixture = Path(__file__).parent / "fixtures" / "debug_action.py"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)

    def fail_redaction(text: str) -> str:
        raise RuntimeError("redaction failed")

    monkeypatch.setattr("taut.debug.redact_sensitive_text", fail_redaction)
    _capture_secret_failure(db_path)
    assert _debug_messages(db_path) == []

    monkeypatch.setenv(
        "TAUT_DEBUG_ACTION",
        " ".join(
            shlex.quote(value) for value in (sys.executable, str(fixture), str(output))
        ),
    )
    _capture_secret_failure(db_path)
    assert not output.exists()


def test_redaction_expansion_is_bounded_before_delivery() -> None:
    """[TAUT-13.3.1] Replacement growth participates in event-size fitting."""

    from taut import debug as debug_module

    event = {
        "type": "taut_debug_event",
        "version": 1,
        "captured_at": "2026-08-20T00:00:00+00:00",
        "target": ".taut.db",
        "surface": "test",
        "operation": "debug.redaction.bounds",
        "exception": {"type": "RuntimeError", "message": "password=x"},
        "traceback": "password=x;" * 20_000,
        "frames": [],
        "runtime": {},
        "fingerprint": "a" * 64,
        "sentinel": "taut-debug:" + "a" * 64,
        "truncated": False,
    }

    payload = debug_module._serialize_event(event)

    assert len(payload.encode("utf-8")) <= 131_072
    assert json.loads(payload)["truncated"] is True
    assert "password=x" not in payload
    assert "password=<redacted>" in payload


@pytest.mark.parametrize(
    "action",
    ["", "definitely-not-a-real-debug-action", '"unterminated'],
)
def test_action_failure_has_no_local_fallback(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    action: str,
) -> None:
    """[TAUT-13.4] Action presence owns failures as well as successes."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    monkeypatch.setenv("TAUT_DEBUG_ACTION", action)

    _capture_same_failure(db_path)

    assert capfd.readouterr() == ("", "")
    assert _debug_messages(db_path) == []


def test_action_windows_style_quoted_executable_becomes_plain_argv_zero(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.4] Universal POSIX parsing removes Windows path quotes."""

    from taut import debug as debug_module

    calls: list[tuple[list[str], dict[str, object]]] = []

    def record_run(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setenv(
        "TAUT_DEBUG_ACTION",
        r'"C:\Program Files\Taut Action\collector.exe" --label "snow λ"',
    )
    monkeypatch.setattr(debug_module.subprocess, "run", record_run)

    debug_module._send_to_action("{}")

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [
        r"C:\Program Files\Taut Action\collector.exe",
        "--label",
        "snow λ",
    ]
    assert kwargs["shell"] is False
    assert kwargs["encoding"] == "utf-8"


def test_local_search_failure_still_attempts_real_queue_write(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.3] Dedup lookup failure does not discard the evidence."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    real_find = Queue.find_message_ids

    def fail_debug_search(queue: Queue, **kwargs: object) -> list[int]:
        if queue.name == "taut.debug":
            raise RuntimeError("search unavailable")
        return real_find(queue, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Queue, "find_message_ids", fail_debug_search)

    _capture_same_failure(db_path)

    assert len(_debug_messages(db_path)) == 1


def test_same_process_concurrent_capture_writes_one_retained_event(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.3] The process lock closes the local search/write race."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_capture_same_failure, db_path) for _ in range(16)]
        for future in futures:
            future.result()

    assert len(_debug_messages(db_path)) == 1


@pytest.mark.parametrize("failure_kind", ["write", "close"])
def test_local_sink_failure_is_contained(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    """[TAUT-13.5] Queue write and close failures never escape capture."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    real_write = Queue.write
    real_close = Queue.close

    def fail_write(queue: Queue, message: str, **kwargs: object) -> object:
        if queue.name == "taut.debug":
            raise RuntimeError("debug write failed")
        return real_write(queue, message, **kwargs)

    def fail_close(queue: Queue) -> None:
        real_close(queue)
        if queue.name == "taut.debug":
            raise RuntimeError("debug close failed")

    with monkeypatch.context() as scoped:
        if failure_kind == "write":
            scoped.setattr(Queue, "write", fail_write)
        else:
            scoped.setattr(Queue, "close", fail_close)
        _capture_same_failure(db_path)

    expected = 0 if failure_kind == "write" else 1
    assert len(_debug_messages(db_path)) == expected


def test_capture_setup_and_format_failures_return_without_evidence(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.5] Resolution, malformed state, and formatting are best effort."""

    missing = tmp_path / "missing.db"
    _capture_same_failure(missing)
    assert not missing.exists()

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
                ("debug_capture", "malformed"),
            )
    finally:
        queue.close()
    _capture_same_failure(db_path)
    assert _debug_messages(db_path) == []

    TautClient.set_debug_capture(True, db_path=db_path)

    def fail_event(*args: object, **kwargs: object) -> object:
        raise RuntimeError("event formatting failed")

    monkeypatch.setattr("taut.debug._build_event", fail_event)
    _capture_same_failure(db_path)
    assert _debug_messages(db_path) == []


@pytest.mark.parametrize("mode", ["nonzero", "noisy"])
def test_action_nonzero_and_output_are_ignored_without_local_fallback(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    """[TAUT-13.4] Child status and output cannot alter the caller's surface."""

    db_path = tmp_path / "workspace.db"
    fixture = Path(__file__).parent / "fixtures" / "debug_action.py"
    output = tmp_path / f"{mode}.json"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    monkeypatch.setenv(
        "TAUT_DEBUG_ACTION",
        " ".join(
            shlex.quote(value)
            for value in (sys.executable, str(fixture), str(output), mode)
        ),
    )

    _capture_same_failure(db_path)

    captured = capfd.readouterr()
    assert captured == ("", "")
    assert json.loads(output.read_text(encoding="utf-8"))["version"] == 1
    assert _debug_messages(db_path) == []


def test_action_inherits_environment_and_working_directory(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.4] The no-shell child inherits the current process context."""

    db_path = tmp_path / "workspace.db"
    fixture = Path(__file__).parent / "fixtures" / "debug_action.py"
    output = tmp_path / "context.json"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TAUT_DEBUG_ACTION_PROBE", "inherited")
    monkeypatch.setenv(
        "TAUT_DEBUG_ACTION",
        " ".join(
            shlex.quote(value) for value in (sys.executable, str(fixture), str(output))
        ),
    )

    _capture_same_failure(db_path)

    context = json.loads(output.with_suffix(".context").read_text(encoding="utf-8"))
    assert context == {"cwd": str(tmp_path), "probe": "inherited"}


def test_existing_taut_debug_variable_does_not_enable_capture_or_run_action(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.4] TAUT_DEBUG remains separate broker configuration."""

    db_path = tmp_path / "workspace.db"
    output = tmp_path / "must-not-exist.json"
    fixture = Path(__file__).parent / "fixtures" / "debug_action.py"
    TautClient.init(db_path=db_path)
    monkeypatch.setenv("TAUT_DEBUG", "1")
    monkeypatch.setenv(
        "TAUT_DEBUG_ACTION",
        " ".join(
            shlex.quote(value) for value in (sys.executable, str(fixture), str(output))
        ),
    )

    _capture_same_failure(db_path)

    assert not output.exists()
    assert _debug_messages(db_path) == []


def test_action_timeout_is_bounded_and_has_no_local_fallback(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-13.4] A stuck real child is terminated after the fixed request."""

    db_path = tmp_path / "workspace.db"
    fixture = Path(__file__).parent / "fixtures" / "debug_action.py"
    output = tmp_path / "must-not-exist.json"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    monkeypatch.setenv(
        "TAUT_DEBUG_ACTION",
        " ".join(
            shlex.quote(value)
            for value in (sys.executable, str(fixture), str(output), "sleep")
        ),
    )

    started = time.monotonic()
    _capture_same_failure(db_path)
    elapsed = time.monotonic() - started

    assert 1.5 <= elapsed < 5.0
    assert not output.exists()
    assert _debug_messages(db_path) == []


def test_command_execution_boundary_captures_before_preserving_diagnostic(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.2] The core command boundary retains and renders one failure."""

    from taut.commands import CommandContext
    from taut.commands._dispatch import _PreparedInvocation, _run_prepared_invocation

    class FailingCommand:
        def run(self, context: object, args: argparse.Namespace) -> int:
            command_local = "boundary evidence"
            _ = command_local
            del _
            raise RuntimeError("command boundary exploded")

    db_path = tmp_path / "workspace.db"
    stderr = StringIO()
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    context = CommandContext(
        db_path=str(db_path),
        as_name=None,
        continuity_token=None,
        json=False,
        timestamps=False,
        quiet=False,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )
    prepared = _PreparedInvocation(
        verb="fixture",
        command=FailingCommand(),
        args=argparse.Namespace(),
        context=context,
    )

    result = _run_prepared_invocation(prepared)

    assert result == 1
    assert stderr.getvalue() == "command boundary exploded\n"
    events = [json.loads(message) for message in _debug_messages(db_path)]
    assert len(events) == 1
    assert events[0]["surface"] == "cli"
    assert events[0]["operation"] == "command.run:fixture"
    assert any(
        "boundary evidence" in value
        for frame in events[0]["frames"]
        for value in frame["locals"].values()
    )


def test_command_load_boundary_captures_and_preserves_selected_diagnostic(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.2] Adapter-load failures use the same core handler."""

    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry
    from tests.test_command_registry import _Distribution, _EntryPoint

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "tests.test_command_registry:_create_configure_failure_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stderr = StringIO()

    result = dispatch(
        ["--db", str(db_path), "fixture"],
        registry=registry,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 1
    assert "configure exploded" in stderr.getvalue()
    events = [json.loads(message) for message in _debug_messages(db_path)]
    assert len(events) == 1
    assert events[0]["operation"] == "command.load:fixture"


def test_command_cleanup_boundary_captures_only_when_no_primary_failure(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.2] Cleanup keeps the established primary-error priority."""

    from taut.commands import CommandContext
    from taut.commands._dispatch import _PreparedInvocation, _run_prepared_invocation

    class CloseFailureClient:
        def close(self) -> None:
            cleanup_local = "cleanup evidence"
            _ = cleanup_local
            del _
            raise RuntimeError("cleanup boundary exploded")

    class UsesClientCommand:
        def run(self, context: CommandContext, args: argparse.Namespace) -> int:
            context.client()
            return 0

    db_path = tmp_path / "workspace.db"
    stderr = StringIO()
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    context = CommandContext(
        db_path=str(db_path),
        as_name=None,
        continuity_token=None,
        json=False,
        timestamps=False,
        quiet=False,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
        _client_factory=lambda **_kwargs: CloseFailureClient(),  # type: ignore[arg-type]
    )

    result = _run_prepared_invocation(
        _PreparedInvocation(
            verb="fixture",
            command=UsesClientCommand(),
            args=argparse.Namespace(),
            context=context,
        )
    )

    assert result == 1
    assert stderr.getvalue() == "cleanup boundary exploded\n"
    events = [json.loads(message) for message in _debug_messages(db_path)]
    assert len(events) == 1
    assert events[0]["operation"] == "command.cleanup:fixture"


def test_command_boundary_does_not_capture_direct_base_exception(
    tmp_path: Path,
    clean_env: None,
) -> None:
    """[TAUT-13.2] Direct BaseException subclasses remain outside capture."""

    from taut.commands import CommandContext
    from taut.commands._dispatch import _PreparedInvocation, _run_prepared_invocation

    class ProcessSignal(BaseException):
        pass

    class SignalledCommand:
        def run(self, context: object, args: argparse.Namespace) -> int:
            raise ProcessSignal("stop")

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    context = CommandContext(
        db_path=str(db_path),
        as_name=None,
        continuity_token=None,
        json=False,
        timestamps=False,
        quiet=True,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    result = _run_prepared_invocation(
        _PreparedInvocation(
            verb="fixture",
            command=SignalledCommand(),
            args=argparse.Namespace(),
            context=context,
        )
    )

    assert result == 1
    assert _debug_messages(db_path) == []


@pytest.mark.parametrize("failure_kind", ["broken-pipe", "terminal-policy"])
def test_command_boundary_excludes_transport_and_terminal_policy_failures(
    tmp_path: Path,
    clean_env: None,
    failure_kind: str,
) -> None:
    """[TAUT-13.2] Expected outer transport policy signals are not events."""

    from taut.commands import CommandContext
    from taut.commands._dispatch import _PreparedInvocation, _run_prepared_invocation
    from taut.commands._rendering import _TerminalOutputPolicyError

    failure: Exception = (
        BrokenPipeError("downstream closed")
        if failure_kind == "broken-pipe"
        else _TerminalOutputPolicyError()
    )

    class FailingCommand:
        def run(self, context: object, args: argparse.Namespace) -> int:
            raise failure

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    TautClient.set_debug_capture(True, db_path=db_path)
    context = CommandContext(
        db_path=str(db_path),
        as_name=None,
        continuity_token=None,
        json=False,
        timestamps=False,
        quiet=True,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=StringIO(),
    )
    prepared = _PreparedInvocation(
        verb="fixture",
        command=FailingCommand(),
        args=argparse.Namespace(),
        context=context,
    )

    if failure_kind == "terminal-policy":
        with pytest.raises(_TerminalOutputPolicyError) as caught:
            _run_prepared_invocation(prepared)
        assert caught.value is failure
    else:
        assert _run_prepared_invocation(prepared) == 1

    assert _debug_messages(db_path) == []
