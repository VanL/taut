"""Adversarial acceptance probes for the taut CLI.

These probes apply the invariant floors from
``docs/agent-context/runbooks/adversarial-acceptance-probes.md`` to the
shipped entry point (black-box, real subprocesses, real databases):
every failure path must exit with the correct class ([TAUT-8.1]: 1 error,
2 empty/not-found), print a one-line diagnostic, and never leak a
traceback to stderr. Probes that pin ugly-but-decided current behavior
say so in a comment.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import psutil
import pytest
from simplebroker import Queue

from taut._constants import META_QUEUE_NAME
from taut.state import SQLITE_SQL_DIALECT, SqlSidecarTautState
from tests import conftest as harness
from tests.conftest import run_cli

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


def _pin_cli_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    diagnostic = tmp_path / "cli-diagnostic.log"

    def create() -> Path:
        diagnostic.touch()
        return diagnostic

    monkeypatch.setattr(harness, "_new_cli_diagnostic", create)
    return diagnostic


def test_run_cli_starts_behavior_deadline_after_real_import_readiness(
    tmp_path: Path,
) -> None:
    rc, out, err = run_cli(
        "--version",
        cwd=tmp_path,
        env={"TAUT_TEST_CLI_STARTUP_DELAY": "6"},
        startup_timeout=60,
        timeout=5,
    )

    assert rc == 0
    assert out.startswith("taut ")
    assert err == ""


def test_run_cli_fails_immediately_when_child_exits_before_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic = _pin_cli_diagnostic(tmp_path, monkeypatch)

    with pytest.raises(
        RuntimeError,
        match="child exited before application readiness",
    ):
        run_cli(
            "--version",
            cwd=tmp_path,
            env={"TAUT_TEST_CLI_EXIT_BEFORE_READY": "1"},
            startup_timeout=2,
        )

    assert not diagnostic.exists()


def test_run_cli_startup_watchdog_is_separate_and_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("COVERAGE_PROCESS_START", "COVERAGE_FILE", "COVERAGE_RCFILE"):
        monkeypatch.delenv(name, raising=False)
    diagnostic = _pin_cli_diagnostic(tmp_path, monkeypatch)

    with pytest.raises(TimeoutError):
        run_cli(
            "--version",
            cwd=tmp_path,
            env={"TAUT_TEST_CLI_STARTUP_DELAY": "2"},
            startup_timeout=0.1,
            timeout=2,
        )

    assert not diagnostic.exists()


def test_run_cli_post_readiness_timeout_reaps_child_and_reports_stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("COVERAGE_PROCESS_START", "COVERAGE_FILE", "COVERAGE_RCFILE"):
        monkeypatch.delenv(name, raising=False)
    diagnostic = _pin_cli_diagnostic(tmp_path, monkeypatch)

    with pytest.raises(subprocess.TimeoutExpired) as raised:
        run_cli(
            "--version",
            cwd=tmp_path,
            env={
                "TAUT_TEST_CLI_AFTER_READY_DELAY": "5",
            },
            startup_timeout=30,
            timeout=2,
        )

    assert "cli_ready.py" in str(raised.value.stderr)
    assert not diagnostic.exists()


def test_run_cli_timeout_kills_inherited_pipe_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("COVERAGE_PROCESS_START", "COVERAGE_FILE", "COVERAGE_RCFILE"):
        monkeypatch.delenv(name, raising=False)
    diagnostic = _pin_cli_diagnostic(tmp_path, monkeypatch)
    descendant_pid_path = tmp_path / "descendant.pid"

    with pytest.raises(subprocess.TimeoutExpired):
        run_cli(
            "--version",
            cwd=tmp_path,
            env={
                "TAUT_TEST_CLI_AFTER_READY_DELAY": "2",
                "TAUT_TEST_CLI_DESCENDANT_PID_PATH": str(descendant_pid_path),
            },
            startup_timeout=30,
            timeout=0.3,
        )

    descendant_pid = int(descendant_pid_path.read_text(encoding="ascii"))
    assert not psutil.pid_exists(descendant_pid)
    assert not diagnostic.exists()


def test_run_cli_completed_after_diagnostic_dump_keeps_stderr_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic = _pin_cli_diagnostic(tmp_path, monkeypatch)

    rc, out, err = run_cli(
        "--version",
        cwd=tmp_path,
        env={"TAUT_TEST_CLI_AFTER_READY_DELAY": "2"},
        startup_timeout=30,
        timeout=4,
    )

    assert rc == 0
    assert out.startswith("taut ")
    assert err == ""
    assert not diagnostic.exists()


@pytest.mark.parametrize("failure", ["listener", "spawn"])
def test_run_cli_cleans_diagnostic_when_setup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    diagnostic = _pin_cli_diagnostic(tmp_path, monkeypatch)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError(f"synthetic {failure} failure")

    if failure == "listener":
        monkeypatch.setattr(harness.socket, "socket", fail)
    else:
        monkeypatch.setattr(harness.subprocess, "Popen", fail)

    with pytest.raises(OSError, match=f"synthetic {failure} failure"):
        run_cli("--version", cwd=tmp_path)

    assert not diagnostic.exists()


def _assert_clean_failure(rc: int, out: str, err: str, *, expected_rc: int) -> None:
    """Floor assertions shared by every probe: exit class, one-line stderr
    diagnostic, no traceback."""

    assert rc == expected_rc
    assert out == ""
    assert err != ""
    assert len(err.splitlines()) == 1
    assert "Traceback" not in err


def test_probe_system_dump_load_json_and_missing_input_exit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    assert run_cli("init", cwd=source)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=source)[0] == 0
    assert run_cli("--as", "van", "say", "general", "hello", cwd=source)[0] == 0
    dump_path = tmp_path / "backup.taut.jsonl"

    rc, out, err = run_cli(
        "system",
        "dump",
        "--output",
        str(dump_path),
        "--json",
        cwd=source,
    )

    assert rc == 0, err
    dumped = json.loads(out)
    assert dumped["type"] == "system_dump"
    assert dumped["path"] == str(dump_path)
    assert dumped["messages"] == 2
    assert err == ""

    destination = tmp_path / "destination"
    destination.mkdir()
    rc, out, err = run_cli(
        "system",
        "load",
        "--input",
        str(dump_path),
        "--json",
        cwd=destination,
    )
    assert rc == 0, err
    loaded = json.loads(out)
    assert loaded["type"] == "system_load"
    assert loaded["applied"] is True
    assert loaded["destination_checked"] is True
    assert err == ""

    rc, out, err = run_cli(
        "system",
        "load",
        "--input",
        str(tmp_path / "missing.taut.jsonl"),
        cwd=destination,
    )
    _assert_clean_failure(rc, out, err, expected_rc=2)
    assert "input file not found" in err


def test_probe_system_globals_quiet_dry_run_and_dash_prefixed_path(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert run_cli("init", cwd=workspace)[0] == 0
    ordinary = workspace / "ordinary.taut.jsonl"

    rc, out, err = run_cli(
        "--as",
        "van",
        "system",
        "dump",
        "--output",
        ordinary,
        cwd=workspace,
    )
    _assert_clean_failure(rc, out, err, expected_rc=1)
    assert "does not accept --as" in err

    rc, out, err = run_cli(
        "system",
        "dump",
        "--output",
        ordinary,
        "--as",
        "van",
        cwd=workspace,
    )
    assert rc == 1
    assert out == ""
    assert "unrecognized arguments" in err
    assert "Traceback" not in err

    rc, out, err = run_cli(
        "system",
        "dump",
        f"--output={ordinary}",
        "--quiet",
        cwd=workspace,
        env={"TAUT_AS": "ambient-actor", "TAUT_TOKEN": "ambient-token"},
    )
    assert (rc, out, err) == (0, "", "")

    dash_path = workspace / "-backup.taut.jsonl"
    ordinary.replace(dash_path)
    destination = workspace / "must-not-exist.db"
    rc, out, err = run_cli(
        "--db",
        destination,
        "system",
        "load",
        "--input=-backup.taut.jsonl",
        "--dry-run",
        "--json",
        cwd=workspace,
    )
    assert rc == 0, err
    report = json.loads(out)
    assert report["dry_run"] is True
    assert report["destination_checked"] is False
    assert report["applied"] is False
    assert not destination.exists()


def test_probe_garbage_taut_db_is_reported_without_traceback(tmp_path: Path) -> None:
    (tmp_path / ".taut.db").write_bytes(b"garbage, not a sqlite file")

    rc, out, err = run_cli("list", cwd=tmp_path)

    # Documents current behavior: SimpleBroker's project-scope resolution
    # does not recognize a non-SQLite file as a database, so read verbs
    # report the generic "no database" diagnostic (exit 1). `init` on the
    # same tree (below) names the real problem, so the hint chain ends at
    # an accurate message.
    _assert_clean_failure(rc, out, err, expected_rc=1)
    assert "No taut database found" in err

    rc, out, err = run_cli("init", cwd=tmp_path)

    _assert_clean_failure(rc, out, err, expected_rc=1)
    assert ".taut.db" in err
    assert "not a valid SQLite database" in err


def test_probe_truncated_taut_db_is_reported_without_traceback(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    db = tmp_path / ".taut.db"
    db.write_bytes(db.read_bytes()[:100])

    rc, out, err = run_cli("--as", "van", "say", "general", "hi", cwd=tmp_path)

    # Documents current behavior: a truncated database is unrecognizable
    # to target resolution and degrades to the same "no database" class
    # as the garbage-file probe above (exit 1, one line, no traceback).
    _assert_clean_failure(rc, out, err, expected_rc=1)
    assert "No taut database found" in err


def test_probe_invalid_project_toml_names_the_file(tmp_path: Path) -> None:
    (tmp_path / ".taut.toml").write_text("version = [unclosed\n", encoding="utf-8")

    for args in (("init",), ("list",)):
        rc, out, err = run_cli(*args, cwd=tmp_path)

        _assert_clean_failure(rc, out, err, expected_rc=1)
        assert err == ("invalid .taut.toml: terminal output policy is unavailable")


def test_probe_unknown_project_toml_keys_are_silently_ignored(
    tmp_path: Path,
) -> None:
    # [TAUT-3.2]: unknown .taut.toml keys are ignored, not rejected — the
    # spec'd forward-compatibility posture (mirroring SimpleBroker's loader
    # and [IAN-7.2] unknown payload fields). This probe pins that contract
    # so any future change to loud failure is deliberate.
    (tmp_path / ".taut.toml").write_text(
        'version = 1\nbackend = "sqlite"\ntarget = ".taut.db"\nnot_a_real_key = true\n',
        encoding="utf-8",
    )

    rc, _out, err = run_cli("init", cwd=tmp_path)
    assert rc == 0, err

    rc, out, err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0, err
    assert any("member_id" in json.loads(line) for line in out.splitlines())


def test_probe_non_utf8_stdin_fails_clean_and_posts_nothing(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli(
        "--as",
        "van",
        "say",
        "general",
        "-",
        cwd=tmp_path,
        stdin_bytes=b"\xff\xfe not utf-8 \x80 bytes",
    )

    _assert_clean_failure(rc, out, err, expected_rc=1)
    assert "stdin is not valid UTF-8" in err

    # No partial write: history still holds only the creation notice.
    rc, out, err = run_cli("log", "general", "--json", cwd=tmp_path)
    assert rc == 0, err
    assert [json.loads(line)["text"] for line in out.splitlines()] == [
        "van created #general"
    ]


@pytest.mark.parametrize(
    ("table", "field", "command"),
    [
        ("taut_members", "meta", ("who", "--json")),
        ("taut_threads", "meta", ("list", "--all", "--json")),
        (
            "taut_identity_claims",
            "evidence_json",
            ("rejoin", "van", "--json"),
        ),
    ],
)
def test_probe_corrupt_owned_object_json_fails_with_context(
    tmp_path: Path,
    table: str,
    field: str,
    command: tuple[str, ...],
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(f"UPDATE {table} SET {field} = ?", ("{broken",))
    finally:
        queue.close()

    rc, out, err = run_cli(*command, cwd=tmp_path)

    _assert_clean_failure(rc, out, err, expected_rc=1)
    assert f"{table}.{field}: invalid JSON" in err


def test_probe_corrupt_channel_rename_json_fails_without_completing_marker(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    state = SqlSidecarTautState(queue, SQLITE_SQL_DIALECT)
    try:
        state.start_channel_rename(
            old_name="general",
            new_name="ops",
            affected=[{"old": "general", "new": "ops"}],
            started_ts=queue.generate_timestamp(),
        )
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_channel_renames SET affected_json = ? WHERE old_name = ?",
                ("{broken", "general"),
            )
    finally:
        queue.close()

    rc, out, err = run_cli(
        "channel", "rename", "general", "ops", "--json", cwd=tmp_path
    )

    _assert_clean_failure(rc, out, err, expected_rc=1)
    assert "taut_channel_renames.affected_json: invalid JSON" in err
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        with queue.sidecar() as session:
            rows = list(
                session.run(
                    "SELECT state FROM taut_channel_renames WHERE old_name = ?",
                    ("general",),
                    fetch=True,
                )
            )
        assert rows == [("started",)]
    finally:
        queue.close()


def test_probe_corrupt_channel_topic_fails_without_traceback(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_threads SET meta = ? WHERE name = ?",
                (json.dumps({"topic": {"text": "partial"}}), "general"),
            )
    finally:
        queue.close()

    rc, out, err = run_cli("channel", "show", "general", "--json", cwd=tmp_path)

    _assert_clean_failure(rc, out, err, expected_rc=1)
    assert "taut_threads.meta.topic: expected exactly" in err


@pytest.mark.skipif(
    os.name == "nt",
    reason="directory write permissions are not enforced this way on Windows",
)
@pytest.mark.skipif(
    os.name == "posix" and os.geteuid() == 0,
    reason="root bypasses directory write permissions",
)
def test_probe_init_in_read_only_directory_fails_fast(tmp_path: Path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        # run_cli's own 20s timeout doubles as the hang guard here: before
        # the pre-flight writability check, this stalled for the full
        # SimpleBroker setup phase-lock timeout (~60s).
        rc, out, err = run_cli("init", cwd=ro)
    finally:
        ro.chmod(0o755)

    _assert_clean_failure(rc, out, err, expected_rc=1)
    assert "not writable" in err
    assert not (ro / ".taut.db").exists()
