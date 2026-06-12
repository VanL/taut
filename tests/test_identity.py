"""Identity behavior tests over real process chains.

These tests spawn taut through a *fresh shell wrapper per command*,
mimicking how per-command agents (e.g. Claude Code's Bash tool) actually
invoke CLIs. The long-lived ancestor shared by every invocation is this
pytest process; per [TAUT-5.2] the anchor walk must skip the disposable
shell wrapper and land on a durable ancestor, so the same member resolves
across invocations.

Note that ``conftest.run_cli`` intentionally does NOT go through a shell,
which is why the rest of the suite cannot catch shell-skip regressions —
these tests exist precisely to keep a real wrapper in the chain.

Spec references:
- docs/specs/02-taut-core.md [TAUT-5.1] (untruncated capture),
  [TAUT-5.2] (anchor walk), [TAUT-5.3] (recognition), [TAUT-8.2]
  (creation member-object line), [TAUT-11]
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _taut_via_shell(
    shell: Path | str,
    args: str,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """Run ``taut`` through a fresh shell wrapper, like per-command agents do.

    The trailing ``; exit $?`` makes the -c payload a compound command on
    purpose: with a single simple command, shells exec-optimize themselves
    out of the process chain entirely, and the wrapper this test exists to
    exercise would never be captured. Do not "simplify" it away.
    """
    cmd = f"{shlex.quote(sys.executable)} -m taut {args} ; exit $?"
    return subprocess.run(
        [str(shell), "-c", cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _init_db(cwd: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "taut", "init", "-q"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr


def _join_and_capture_handle(shell: Path | str, cwd: Path) -> str:
    """Join via a fresh shell; return the created handle from the
    [TAUT-8.2] creation member-object line (the one carrying ``token``)."""
    completed = _taut_via_shell(shell, "--json join general", cwd)
    assert completed.returncode == 0, completed.stderr
    for line in completed.stdout.strip().splitlines():
        obj = json.loads(line)
        if "token" in obj:
            return str(obj["handle"])
    raise AssertionError(
        "join --json emitted no creation member-object line: " + completed.stdout
    )


def _whoami(shell: Path | str, cwd: Path) -> tuple[int, str | None]:
    completed = _taut_via_shell(shell, "--json whoami", cwd)
    if completed.returncode != 0:
        return completed.returncode, None
    line = completed.stdout.strip().splitlines()[-1]
    return completed.returncode, json.loads(line).get("handle")


_SHELL_BASENAMES = {"sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish"}


def _anchor_argv0(shell: Path | str, cwd: Path) -> str:
    """Return argv[0] of the resolved member's anchor via whoami --explain."""
    completed = _taut_via_shell(shell, "--json whoami --explain", cwd)
    assert completed.returncode == 0, completed.stderr
    line = completed.stdout.strip().splitlines()[-1]
    explain = json.loads(line).get("explain") or {}
    anchor = explain.get("anchor") or {}
    argv = anchor.get("argv") or []
    return str(argv[0]) if argv else str(anchor.get("exe") or "")


@pytest.mark.usefixtures("clean_env")
def test_recognition_survives_fresh_shell_per_command(tmp_path: Path) -> None:
    """[TAUT-5.3]: the same member must resolve across separate shell
    invocations — the headline recognition feature for per-command agents."""
    shell = shutil.which("bash") or "/bin/sh"
    _init_db(tmp_path)

    created = _join_and_capture_handle(shell, tmp_path)

    # A *new* shell wrapper: different pid, same durable ancestry.
    rc, resolved = _whoami(shell, tmp_path)
    assert rc == 0, (
        "caller unrecognized from a second shell invocation — the anchor "
        "landed on the disposable wrapper instead of a durable ancestor"
    )
    assert resolved == created

    # Same-handle alone can be masked by a live shell higher in the test
    # runner's own ancestry: the anchor must never be a shell at all
    # ([TAUT-5.2] — shells are skipped, not anchored).
    anchor_argv0 = _anchor_argv0(shell, tmp_path)
    assert Path(anchor_argv0).name.lower() not in _SHELL_BASENAMES, (
        f"anchor landed on a shell process ({anchor_argv0}); the walk must "
        "skip shells even when the captured executable name is truncated"
    )


@pytest.mark.usefixtures("clean_env")
def test_shell_skip_survives_long_executable_paths(tmp_path: Path) -> None:
    """[TAUT-5.1]/[TAUT-5.2]: shell classification must not depend on a
    truncatable executable field. Regression for the macOS ``ps`` 16-char
    clip that anchored identities on ``bash -c`` wrappers."""
    src = shutil.which("bash") or "/bin/sh"
    longdir = tmp_path / "a-directory-name-well-past-sixteen-chars"
    longdir.mkdir()
    shell = longdir / Path(src).name
    shell.symlink_to(src)

    workdir = tmp_path / "proj"
    workdir.mkdir()
    _init_db(workdir)

    created = _join_and_capture_handle(shell, workdir)
    # The handle must come from a durable ancestor, never from the shell
    # wrapper itself (truncated or not).
    assert created not in {"bash", "sh", "bi"}

    rc, resolved = _whoami(shell, workdir)
    assert rc == 0, (
        "long-path shell wrapper was not skipped by the anchor walk "
        "(executable name likely truncated at capture time)"
    )
    assert resolved == created

    anchor_argv0 = _anchor_argv0(shell, workdir)
    assert Path(anchor_argv0).name.lower() not in _SHELL_BASENAMES, (
        f"anchor landed on a shell process ({anchor_argv0}); the walk must "
        "skip shells even when the captured executable name is truncated"
    )
    assert anchor_argv0 != str(shell), (
        "anchor landed on the disposable long-path wrapper itself"
    )
