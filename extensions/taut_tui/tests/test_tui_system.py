"""TUI extension wrappers for public actor-free system operations.

Spec references:
- docs/specs/10-taut-tui.md [TUI-10], [TUI-12.3]
"""

from __future__ import annotations

from pathlib import Path
from threading import get_ident

import pytest

from taut.client import TautClient

pytestmark = pytest.mark.sqlite_only


def test_doctor_runs_on_background_owner_and_returns_typed_report(
    tmp_path: Path,
) -> None:
    from taut_tui.system import TuiSystemOperations

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=db_path)
    operations = TuiSystemOperations(db_path=str(db_path))
    try:
        report = operations.submit_doctor().result(timeout=10)
    finally:
        operations.close()

    assert report.db == str(db_path)
    assert report.healthy is True
    assert len(report.checks) == 6


def test_doctor_findings_and_framework_failures_cross_the_background_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import DoctorCheck, DoctorReport
    from taut_tui.system import TuiSystemOperations

    owner = get_ident()
    worker_ids: list[int] = []

    def findings(*, db_path: str | None = None) -> DoctorReport:
        worker_ids.append(get_ident())
        return DoctorReport(
            db=db_path or "default",
            healthy=False,
            checks=(DoctorCheck("broker", "fail", "not reachable", {}),),
        )

    monkeypatch.setattr(TautClient, "doctor", findings)
    operations = TuiSystemOperations(db_path="broken.db")
    try:
        report = operations.submit_doctor().result(timeout=5)
        assert report.healthy is False
        assert report.checks[0].detail == "not reachable"
        assert worker_ids and worker_ids[0] != owner

        def framework_error(*, db_path: str | None = None) -> DoctorReport:
            del db_path
            raise RuntimeError("doctor framework failed")

        monkeypatch.setattr(TautClient, "doctor", framework_error)
        with pytest.raises(RuntimeError, match="doctor framework failed"):
            operations.submit_doctor().result(timeout=5)
    finally:
        operations.close()


def test_dump_is_single_flight_and_blocks_quit_until_future_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from threading import Event

    from taut_tui.system import OperationAlreadyRunning, TuiSystemOperations

    started = Event()
    release = Event()
    real_dump = TautClient.dump

    def held_dump(*, output: str, db_path: str | None = None):  # type: ignore[no-untyped-def]
        started.set()
        assert release.wait(5)
        return real_dump(output=output, db_path=db_path)

    db_path = tmp_path / "chat.db"
    output = tmp_path / "workspace.json"
    TautClient.init(db_path=db_path)
    monkeypatch.setattr(TautClient, "dump", held_dump)
    operations = TuiSystemOperations(db_path=str(db_path))
    try:
        future = operations.submit_dump(output)
        assert started.wait(5)
        assert operations.quit_block_reason() == "A workspace dump is still running."
        with pytest.raises(OperationAlreadyRunning):
            operations.submit_dump(tmp_path / "second.json")
        release.set()
        report = future.result(timeout=10)
        assert report.path == str(output)
        assert operations.quit_block_reason() is None
    finally:
        release.set()
        operations.close()


def test_existing_dump_path_requires_visual_confirmation_but_domain_replaces(
    tmp_path: Path,
) -> None:
    from taut_tui.system import (
        ReplacementConfirmationRequired,
        TuiSystemOperations,
    )

    db_path = tmp_path / "chat.db"
    output = tmp_path / "workspace.json"
    TautClient.init(db_path=db_path)
    output.write_text("old", encoding="utf-8")
    operations = TuiSystemOperations(db_path=str(db_path))
    try:
        with pytest.raises(ReplacementConfirmationRequired) as caught:
            operations.submit_dump(output)
        assert caught.value.path == output

        report = operations.submit_dump(output, replace_confirmed=True).result(
            timeout=10
        )
    finally:
        operations.close()

    assert report.path == str(output)
    assert output.read_text(encoding="utf-8").startswith("{")


def test_dump_domain_failure_crosses_the_background_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut_tui.system import TuiSystemOperations

    owner = get_ident()
    worker_ids: list[int] = []

    def failed_dump(*, output: str, db_path: str | None = None):  # type: ignore[no-untyped-def]
        del output, db_path
        worker_ids.append(get_ident())
        raise PermissionError("dump output is not writable")

    monkeypatch.setattr(TautClient, "dump", failed_dump)
    operations = TuiSystemOperations(db_path=str(tmp_path / "chat.db"))
    try:
        with pytest.raises(PermissionError, match="not writable"):
            operations.submit_dump(tmp_path / "backup.json").result(timeout=5)
    finally:
        operations.close()

    assert worker_ids and worker_ids[0] != owner


def test_load_help_is_pure_and_never_calls_public_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut_tui.system import load_help_command

    def forbidden_load(**_kwargs: object) -> None:
        raise AssertionError("TUI must never execute load")

    monkeypatch.setattr(TautClient, "load", forbidden_load)
    input_path = tmp_path / "backup with spaces.json"

    assert load_help_command(input_path=input_path, db_path=None) == (
        f"taut system load --input '{input_path}'"
    )
    assert load_help_command(input_path=input_path, db_path="chat db.sqlite") == (
        f"taut --db 'chat db.sqlite' system load --input '{input_path}'"
    )
