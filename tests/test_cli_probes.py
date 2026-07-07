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
from pathlib import Path

import pytest

from tests.conftest import run_cli

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


def _assert_clean_failure(rc: int, out: str, err: str, *, expected_rc: int) -> None:
    """Floor assertions shared by every probe: exit class, one-line stderr
    diagnostic, no traceback."""

    assert rc == expected_rc
    assert out == ""
    assert err != ""
    assert len(err.splitlines()) == 1
    assert "Traceback" not in err


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
        assert ".taut.toml" in err


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
