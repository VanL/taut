"""Identity behavior tests over real process chains.

These tests spawn taut through a *fresh shell wrapper per command*,
mimicking how per-command agents (e.g. Claude Code's Bash tool) actually
invoke CLIs. The long-lived ancestor shared by every invocation is this
pytest process; per [IAN-3.2] the anchor walk must skip the disposable
shell wrapper and land on a durable ancestor, so the same member resolves
across invocations.

Note that ``conftest.run_cli`` intentionally does NOT go through a shell,
which is why the rest of the suite cannot catch shell-skip regressions —
these tests exist precisely to keep a real wrapper in the chain.

Spec references:
- docs/specs/03-identity-addressing-notifications.md [IAN-3.2]
  (identity claim evidence), [IAN-3.3] (claim association and recognition),
  [IAN-3.4] (rejoin)
- docs/specs/02-taut-core.md [TAUT-8.2] (creation member-object line),
  [TAUT-11]
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace, TracebackType
from typing import Any, Self, cast

import psutil
import pytest

from taut import TautClient, identity
from taut._constants import (
    HISTORICAL_NAME_POOL,
    PER_BASENAME_NAME_POOLS,
    capitalize_automatic_name,
    normalize_name_seed,
)
from taut.state import MemberRow, SqlSidecarTautState
from tests.conftest import build_cli_env

pytestmark = pytest.mark.sqlite_only
TOKEN_RE = re.compile(r"^(proc|psutil):[0-9]+$")

_POSIX_SHELL_PROCESS_TEST = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX shell-wrapper ancestry is not a Windows process contract",
)


def _taut_via_shell(
    shell: Path | str,
    args: str,
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``taut`` through a fresh shell wrapper, like per-command agents do.

    The trailing ``; exit $?`` makes the -c payload a compound command on
    purpose: with a single simple command, shells exec-optimize themselves
    out of the process chain entirely, and the wrapper this test exists to
    exercise would never be captured. Do not "simplify" it away.
    """
    cmd = f"{shlex.quote(sys.executable)} -m taut {args} ; exit $?"
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        [str(shell), "-c", cmd],
        cwd=cwd,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _init_db(cwd: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "taut", "init", "-q"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _join_and_capture_name(shell: Path | str, cwd: Path) -> str:
    """Join via a fresh shell; return the created name from the
    [TAUT-8.2] creation member-object line (the one carrying ``token``)."""
    completed = _taut_via_shell(shell, "--json join general", cwd)
    assert completed.returncode == 0, completed.stderr
    for line in completed.stdout.strip().splitlines():
        obj = json.loads(line)
        if "token" in obj:
            return str(obj["name"])
    raise AssertionError(
        "join --json emitted no creation member-object line: " + completed.stdout
    )


def _whoami(shell: Path | str, cwd: Path) -> tuple[int, str | None]:
    completed = _taut_via_shell(shell, "--json whoami", cwd)
    if completed.returncode != 0:
        return completed.returncode, None
    line = completed.stdout.strip().splitlines()[-1]
    return completed.returncode, json.loads(line).get("name")


_SHELL_BASENAMES = {
    "sh",
    "bash",
    "zsh",
    "dash",
    "ksh",
    "csh",
    "tcsh",
    "fish",
    "cmd",
    "powershell",
    "pwsh",
}


def _anchor_argv0(shell: Path | str, cwd: Path) -> str:
    """Return argv[0] of the resolved member's anchor via whoami --explain."""
    completed = _taut_via_shell(shell, "--json whoami --explain", cwd)
    assert completed.returncode == 0, completed.stderr
    line = completed.stdout.strip().splitlines()[-1]
    explain = json.loads(line).get("explain") or {}
    anchor = explain.get("anchor") or {}
    argv = anchor.get("argv") or []
    return str(argv[0]) if argv else str(anchor.get("exe") or "")


def _expected_name_from_anchor(argv0: str) -> str:
    return capitalize_automatic_name(
        normalize_name_seed(Path(argv0).name, fallback="agent")
    )


def _capture(
    *,
    start_time: str = "start",
    anchor: bool = True,
) -> identity.IdentityCapture:
    proc = identity.ProcessInfo(
        pid=123,
        ppid=1,
        start_time=start_time,
        exe="/usr/bin/codex",
        argv=("codex", "--work"),
        uid=501,
        pgid=123,
        session_id=456,
        tty="ttys001",
        cwd="/workspace",
    )
    return identity.IdentityCapture(
        chain=(proc,),
        host=identity.HostIdentity("host:test", "test-host", "test host identity"),
        uid=501,
        login="van",
        anchor=proc if anchor else None,
        kind="agent" if anchor else "human",
        rule="test",
    )


def _assert_finite_positive_timeout(value: object) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    assert math.isfinite(float(value))
    assert value > 0


def _member_row(
    *,
    member_id: str = "m_" + "a" * 26,
    display_name: str = "ada",
    kind: str = "agent",
    host_id: str = "host:test",
    anchor_pid: int | None = 123,
    anchor_start_time: str | None = "start",
    fingerprint: str | None = None,
    last_active_ts: int = 1,
) -> MemberRow:
    return {
        "member_id": member_id,
        "display_name": display_name,
        "name_key": display_name.lower(),
        "kind": kind,
        "uid": 501,
        "host_id": host_id,
        "host_label": "test-host",
        "anchor_pid": anchor_pid,
        "anchor_start_time": anchor_start_time,
        "fingerprint": fingerprint,
        "token": None,
        "meta": {},
        "created_ts": 1,
        "last_active_ts": last_active_ts,
    }


def test_process_info_basename_and_classification_use_argv_before_exe() -> None:
    proc = identity.ProcessInfo(
        pid=1,
        exe="/usr/bin/python",
        argv=("/opt/Codex CLI",),
    )
    duplicate = identity.ProcessInfo(
        pid=2,
        exe="/usr/bin/codex",
        argv=("/opt/codex",),
    )
    anonymous = identity.ProcessInfo(pid=3)

    assert proc.basename == "codex cli"
    assert proc.classification_basenames == ("codex cli", "python")
    assert duplicate.classification_basenames == ("codex",)
    assert anonymous.basename == "process"
    assert anonymous.classification_basenames == ("process",)


def test_capture_identity_selects_agent_anchor_from_captured_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = identity.ProcessInfo(
        pid=123,
        ppid=1,
        start_time="start",
        exe="/usr/bin/codex",
        argv=("codex",),
    )

    monkeypatch.setattr(
        identity,
        "capture_host_identity",
        lambda: identity.HostIdentity("host:test", "test-host", "test host identity"),
    )
    monkeypatch.setattr(identity.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(identity.os, "getppid", lambda: 123)
    monkeypatch.setattr(identity, "capture_process_chain", lambda _pid: [proc])
    monkeypatch.setattr(identity, "_login_name", lambda _uid: "van")

    capture = identity.capture_identity()

    assert capture.host.host_id == "host:test"
    assert capture.uid == 501
    assert capture.login == "van"
    assert capture.anchor == proc
    assert capture.kind == "agent"


def test_capture_host_identity_prefers_linux_machine_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity.sys, "platform", "linux")
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "workstation")

    def fake_read_text(self: Path, **_kwargs: Any) -> str:
        if self.as_posix() == "/etc/machine-id":
            return "machine-123\n"
        raise OSError("missing")

    monkeypatch.setattr(identity.Path, "read_text", fake_read_text)

    host = identity.capture_host_identity()

    assert host == identity.HostIdentity(
        "machine-id:machine-123", "workstation", "linux machine-id"
    )


def test_capture_host_identity_uses_macos_platform_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity.sys, "platform", "darwin")
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "mac")

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert cmd == ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]
        _assert_finite_positive_timeout(kwargs["timeout"])
        return subprocess.CompletedProcess(
            cmd,
            0,
            '    | |   "IOPlatformUUID" = "ABC-123"\n',
            "",
        )

    monkeypatch.setattr(identity.subprocess, "run", fake_run)

    host = identity.capture_host_identity()

    assert host == identity.HostIdentity(
        "ioplatformuuid:ABC-123",
        "mac",
        "macOS IOKit platform UUID",
    )


def test_capture_host_identity_falls_back_to_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity.sys, "platform", "darwin")
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "fallback-host")

    def fake_run(_cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("ioreg unavailable")

    monkeypatch.setattr(identity.subprocess, "run", fake_run)

    host = identity.capture_host_identity()

    assert host == identity.HostIdentity(
        "hostname:fallback-host", "fallback-host", "hostname fallback"
    )
    capture = identity.IdentityCapture(
        chain=(),
        host=host,
        uid=501,
        login="tester",
        anchor=None,
        kind="human",
        rule="fallback capture",
    )
    explanation = identity.explain_capture(capture, "identity claim")
    assert explanation["rule"] == "identity claim"
    assert explanation["host_rule"] == "hostname fallback"


@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS IOKit smoke")
@pytest.mark.usefixtures("clean_env")
def test_macos_host_identity_is_path_independent_across_cli_calls(
    tmp_path: Path,
) -> None:
    _init_db(tmp_path)
    env = build_cli_env({"TAUT_DB": str(tmp_path / ".taut.db"), "PATH": ""})

    joined = subprocess.run(
        [sys.executable, "-m", "taut", "--json", "join", "general"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    created = next(obj for obj in _json_lines(joined.stdout) if "token" in obj)
    resolved = subprocess.run(
        [sys.executable, "-m", "taut", "--json", "whoami", "--explain"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    member = _json_lines(resolved.stdout)[-1]

    assert member["member_id"] == created["member_id"]
    assert member["explain"]["host_rule"] == "macOS IOKit platform UUID"
    assert member["explain"]["host_id"].startswith("ioplatformuuid:")


def test_capture_host_identity_uses_fixed_windows_machine_guid_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity.sys, "platform", "win32")
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "windows-host")
    calls: list[tuple[object, ...]] = []

    class Key:
        def __enter__(self) -> Self:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            del exc_type, exc, traceback

    key = Key()

    def open_key(*args: object) -> Key:
        calls.append(("open", *args))
        return key

    def query_value(opened: object, value: str) -> tuple[object, int]:
        calls.append(("query", opened, value))
        return "  ABC-123  ", 1

    registry = SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        KEY_READ=0x1,
        KEY_WOW64_64KEY=0x100,
        OpenKey=open_key,
        QueryValueEx=query_value,
    )
    monkeypatch.setattr(identity, "_load_windows_registry", lambda: registry)

    host = identity.capture_host_identity()

    assert host == identity.HostIdentity(
        "machine-guid:ABC-123",
        "windows-host",
        "Windows machine GUID",
    )
    assert calls == [
        (
            "open",
            registry.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            registry.KEY_READ | registry.KEY_WOW64_64KEY,
        ),
        ("query", key, "MachineGuid"),
    ]


@pytest.mark.parametrize(
    ("raw_value", "error"),
    [
        (None, ImportError("winreg unavailable")),
        (None, OSError("registry unavailable")),
        ("", None),
        ("   ", None),
        (123, None),
    ],
)
def test_capture_host_identity_windows_invalid_machine_guid_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: object,
    error: BaseException | None,
) -> None:
    monkeypatch.setattr(identity.sys, "platform", "win32")
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "windows-fallback")

    if error is not None:

        def load_registry() -> object:
            raise error

        monkeypatch.setattr(identity, "_load_windows_registry", load_registry)
    else:

        class Key:
            def __enter__(self) -> Self:
                return self

            def __exit__(
                self,
                exc_type: type[BaseException] | None,
                exc: BaseException | None,
                traceback: TracebackType | None,
            ) -> None:
                del exc_type, exc, traceback

        registry = SimpleNamespace(
            HKEY_LOCAL_MACHINE=object(),
            KEY_READ=0x1,
            KEY_WOW64_64KEY=0x100,
            OpenKey=lambda *_args: Key(),
            QueryValueEx=lambda _key, _name: (raw_value, 1),
        )
        monkeypatch.setattr(identity, "_load_windows_registry", lambda: registry)

    assert identity.capture_host_identity() == identity.HostIdentity(
        "hostname:windows-fallback",
        "windows-fallback",
        "hostname fallback",
    )


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows registry smoke")
def test_capture_host_identity_windows_is_path_independent() -> None:
    env = build_cli_env()
    env["PATH"] = ""

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from taut.identity import capture_host_identity; "
                "host = capture_host_identity(); "
                "print(host.host_id); print(host.host_rule)"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    lines = completed.stdout.splitlines()
    assert lines[0].startswith("machine-guid:")
    assert len(lines[0]) > len("machine-guid:")
    assert lines[1] == "Windows machine GUID"


def test_capture_process_chain_stops_at_missing_or_self_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = {
        10: identity.ProcessInfo(pid=10, ppid=11),
        11: identity.ProcessInfo(pid=11, ppid=11),
    }

    monkeypatch.setattr(identity, "capture_process", lambda pid: processes.get(pid))

    assert [proc.pid for proc in identity.capture_process_chain(10)] == [10, 11]
    assert identity.capture_process_chain(99) == []


def test_capture_process_prefers_psutil_then_platform_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    psutil_proc = identity.ProcessInfo(pid=1)
    linux_proc = identity.ProcessInfo(pid=2)

    monkeypatch.setattr(identity, "_capture_psutil_process", lambda _pid: psutil_proc)
    assert identity.capture_process(1) == psutil_proc

    monkeypatch.setattr(identity, "_capture_psutil_process", lambda _pid: None)
    monkeypatch.setattr(identity.sys, "platform", "linux")
    monkeypatch.setattr(identity, "_capture_linux_process", lambda _pid: linux_proc)
    assert identity.capture_process(2) == linux_proc

    monkeypatch.setattr(identity.sys, "platform", "darwin")
    assert identity.capture_process(3) is None


def test_select_anchor_skips_wrappers_and_explains_human_fallbacks() -> None:
    shell = identity.ProcessInfo(
        pid=1,
        start_time="shell-start",
        exe="/bin/bash",
        argv=("bash",),
    )
    codex = identity.ProcessInfo(
        pid=2,
        start_time="codex-start",
        exe="/usr/bin/codex",
        argv=("codex",),
    )
    tmux = identity.ProcessInfo(
        pid=3,
        start_time="tmux-start",
        exe="/usr/bin/tmux",
        argv=("tmux",),
    )
    no_start = identity.ProcessInfo(pid=4, exe="/usr/bin/codex", argv=("codex",))

    assert identity.select_anchor((shell, codex)) == (
        codex,
        "agent anchor selected at codex",
    )
    assert identity.select_anchor((tmux,)) == (
        None,
        "human fallback at infrastructure process tmux",
    )
    assert identity.select_anchor((no_start,)) == (
        None,
        "human fallback because codex has no start-time token",
    )
    assert identity.select_anchor(()) == (
        None,
        "human fallback at top of readable process chain",
    )


@pytest.mark.parametrize(
    ("proc", "expected"),
    [
        (
            identity.ProcessInfo(
                pid=1,
                start_time="start",
                exe="/usr/bin/tmux",
                argv=("bash",),
            ),
            "skip",
        ),
        (
            identity.ProcessInfo(
                pid=2,
                start_time="start",
                exe="/usr/bin/tmux",
                argv=("tmux",),
            ),
            "stop",
        ),
        (
            identity.ProcessInfo(pid=3, exe="/usr/bin/python3", argv=("python3",)),
            "unanchorable",
        ),
        (
            identity.ProcessInfo(
                pid=4,
                start_time="start",
                exe="/usr/bin/python3",
                argv=("python3",),
            ),
            "agent_candidate",
        ),
    ],
)
def test_process_role_classification_has_one_fixed_precedence(
    proc: identity.ProcessInfo,
    expected: str,
) -> None:
    assert identity.classify_process_role(proc) == expected


@pytest.mark.parametrize(
    ("argv0", "exe", "family"),
    [
        ("sshd: van@pts/0", "/usr/sbin/sshd", "sshd"),
        ("tmux: server (/tmp/tmux-501/default)", "/usr/bin/tmux", "tmux"),
    ],
)
def test_select_anchor_classifies_infrastructure_by_every_basename(
    argv0: str,
    exe: str,
    family: str,
) -> None:
    """[IAN-3.2]: sshd and tmux rewrite argv[0] on Linux, so the family must
    be read from every classification basename, not only argv[0]."""
    rewritten = identity.ProcessInfo(
        pid=7,
        start_time="infra-start",
        exe=exe,
        argv=(argv0,),
    )
    shell = identity.ProcessInfo(
        pid=6,
        start_time="shell-start",
        exe="/bin/bash",
        argv=("bash",),
    )
    claude = identity.ProcessInfo(
        pid=8,
        start_time="claude-start",
        exe="/opt/homebrew/bin/claude",
        argv=("claude",),
    )
    assert rewritten.basename != family

    assert identity.select_anchor((rewritten,)) == (
        None,
        f"human fallback at infrastructure process {family}",
    )
    anchor, _rule = identity.select_anchor((shell, rewritten, claude))
    assert anchor is None


@pytest.mark.parametrize(
    "wrapper",
    ["time", "nice", "caffeinate", "stdbuf", "watch", "hyperfine"],
)
def test_select_anchor_skips_process_wrappers(wrapper: str) -> None:
    """[IAN-3.2]: ``/usr/bin/time taut join`` must anchor on the agent behind
    the wrapper, never on the ephemeral wrapper pid."""
    chain = (
        identity.ProcessInfo(
            pid=2,
            start_time="wrapper-start",
            exe=f"/usr/bin/{wrapper}",
            argv=(wrapper, "taut", "join"),
        ),
        identity.ProcessInfo(
            pid=3,
            start_time="shell-start",
            exe="/bin/bash",
            argv=("bash",),
        ),
        identity.ProcessInfo(
            pid=4,
            start_time="claude-start",
            exe="/opt/homebrew/bin/claude",
            argv=("claude",),
        ),
    )

    anchor, rule = identity.select_anchor(chain)

    assert anchor is chain[2]
    assert rule == "agent anchor selected at claude"


@pytest.mark.parametrize(
    ("basename", "expected_pid"),
    [
        ("cmd.exe", 2),
        ("powershell.exe", 2),
        ("PWSH.EXE", 2),
        ("bash.exe", 2),
        ("uv.exe", 2),
        ("tmux.exe", None),
        ("codex.exe", 1),
        ("bash.exe.exe", 1),
    ],
)
def test_select_anchor_classifies_one_terminal_exe_suffix(
    basename: str,
    expected_pid: int | None,
) -> None:
    candidate = identity.ProcessInfo(
        pid=1,
        start_time="candidate-start",
        exe=f"C:/tools/{basename}",
        argv=(f"C:/tools/{basename}",),
    )
    control = identity.ProcessInfo(
        pid=2,
        start_time="control-start",
        exe="C:/tools/codex.exe",
        argv=("C:/tools/codex.exe",),
    )

    anchor, _rule = identity.select_anchor((candidate, control))

    assert (None if anchor is None else anchor.pid) == expected_pid


def test_exe_classification_preserves_raw_fingerprint_and_claim_evidence() -> None:
    proc = identity.ProcessInfo(
        pid=42,
        ppid=7,
        start_time="start-42",
        exe="C:/Tools/CODEX.EXE",
        argv=("C:/Tools/CODEX.EXE", "--work"),
        uid=501,
        pgid=42,
        session_id=9,
        tty="console",
        cwd="C:/workspace",
    )

    anchor, _rule = identity.select_anchor((proc,))
    fingerprint = json.loads(identity.fingerprint_for_process(anchor) or "null")
    capture = replace(_capture(), chain=(proc,), anchor=proc)
    claim = identity.claim_for_capture(capture)

    assert anchor is proc
    assert proc.basename == "codex.exe"
    assert capitalize_automatic_name(normalize_name_seed(proc.basename)) == "Codex-exe"
    assert fingerprint["exe"] == "C:/Tools/CODEX.EXE"
    assert fingerprint["argv"] == ["C:/Tools/CODEX.EXE", "--work"]
    assert claim.evidence["exe"] == "C:/Tools/CODEX.EXE"
    assert claim.evidence["argv"] == ["C:/Tools/CODEX.EXE", "--work"]


@pytest.mark.skipif(
    os.name != "nt",
    reason="PowerShell ancestry is a hosted Windows process contract",
)
@pytest.mark.usefixtures("clean_env")
def test_powershell_parent_is_observed_but_not_selected_as_anchor(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    assert powershell is not None, "hosted Windows proof requires PowerShell"
    probe = tmp_path / "identity_probe.py"
    probe.write_text(
        """
import json
from taut import identity


def process_payload(process):
    if process is None:
        return None
    return {
        "exe": process.exe,
        "argv": list(process.argv),
    }


capture = identity.capture_identity()
print(json.dumps({
    "chain": [process_payload(process) for process in capture.chain],
    "anchor": process_payload(capture.anchor),
}))
""".lstrip(),
        encoding="utf-8",
    )
    launcher = tmp_path / "launch-probe.ps1"
    launcher.write_text(
        """
$ErrorActionPreference = 'Stop'
& $env:TAUT_TEST_PYTHON $env:TAUT_TEST_PROBE
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
""".lstrip(),
        encoding="utf-8",
    )
    env = build_cli_env()
    env.update(
        {
            "TAUT_TEST_PYTHON": sys.executable,
            "TAUT_TEST_PROBE": str(probe),
        }
    )

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    def classification_names(process: dict[str, Any]) -> set[str]:
        sources = [*(process.get("argv") or ())[:1], process.get("exe")]
        return {
            PureWindowsPath(source).name.casefold().removesuffix(".exe")
            for source in sources
            if source
        }

    observed_names = {
        name for process in payload["chain"] for name in classification_names(process)
    }
    assert observed_names & {"powershell", "pwsh"}, (
        "PowerShell was not present in the captured ancestry"
    )
    if payload["anchor"] is not None:
        assert classification_names(payload["anchor"]).isdisjoint(_SHELL_BASENAMES)


def test_fingerprint_and_token_claims_do_not_store_secret_material() -> None:
    token_claim = identity.claim_for_token("secret-token")

    assert identity.fingerprint_for_process(None) is None
    assert token_claim.claim_kind == "continuity_token"
    assert token_claim.host_id is None
    assert token_claim.evidence["claim_kind"] == "continuity_token"
    assert "secret-token" not in json.dumps(token_claim.evidence)


def test_explain_capture_summarizes_anchor_and_chain() -> None:
    capture = _capture()

    explanation = identity.explain_capture(capture, "identity claim")

    assert explanation["host_id"] == "host:test"
    assert explanation["host_rule"] == "test host identity"
    assert explanation["rule"] == "identity claim"
    assert explanation["anchor"]["pid"] == 123
    assert explanation["chain"][0]["argv"] == ["codex", "--work"]


def test_explain_capture_reports_host_rule_for_human_capture() -> None:
    explanation = identity.explain_capture(_capture(anchor=False), "human uid fallback")

    assert explanation["host_rule"] == "test host identity"
    assert explanation["rule"] == "human uid fallback"
    assert explanation["anchor"] is None


def test_match_anchor_returns_nearest_matching_member() -> None:
    selected = identity.ProcessInfo(pid=123, start_time="start")
    capture = identity.IdentityCapture(
        chain=(identity.ProcessInfo(pid=122, start_time=None), selected),
        host=identity.HostIdentity("host:test", "test-host", "test host identity"),
        uid=501,
        login="van",
        anchor=selected,
        kind="agent",
        rule="test",
    )
    host_mismatch = _member_row(host_id="host:other")
    match = _member_row(display_name="match")

    assert identity.match_anchor(capture, [host_mismatch, match]) == match
    assert identity.match_anchor(capture, [host_mismatch]) is None


@pytest.mark.parametrize(
    "ancestor",
    [
        identity.ProcessInfo(
            pid=123,
            start_time="ancestor-start",
            exe="/bin/bash",
            argv=("bash",),
        ),
        identity.ProcessInfo(
            pid=123,
            start_time="ancestor-start",
            exe="/usr/bin/tmux",
            argv=("tmux",),
        ),
    ],
)
def test_match_anchor_allows_legacy_skipped_or_stopped_ancestor(
    ancestor: identity.ProcessInfo,
) -> None:
    selected = identity.ProcessInfo(
        pid=200,
        start_time="child-start",
        exe="/usr/bin/codex",
        argv=("codex",),
    )
    capture = identity.IdentityCapture(
        chain=(selected, ancestor),
        host=identity.HostIdentity("host:test", "test-host", "test host identity"),
        uid=501,
        login="van",
        anchor=selected,
        kind="agent",
        rule="test",
    )
    member = _member_row(
        anchor_pid=ancestor.pid,
        anchor_start_time=ancestor.start_time,
    )

    assert identity.match_anchor(capture, [member]) == member


def test_match_anchor_rejects_skipped_descendant_before_selected_anchor() -> None:
    descendant = identity.ProcessInfo(
        pid=201,
        start_time="shell-start",
        exe="/bin/bash",
        argv=("bash",),
    )
    selected = identity.ProcessInfo(
        pid=200,
        start_time="child-start",
        exe="/usr/bin/codex",
        argv=("codex",),
    )
    capture = identity.IdentityCapture(
        chain=(descendant, selected),
        host=identity.HostIdentity("host:test", "test-host", "test host identity"),
        uid=501,
        login="van",
        anchor=selected,
        kind="agent",
        rule="test",
    )
    member = _member_row(
        anchor_pid=descendant.pid,
        anchor_start_time=descendant.start_time,
    )

    assert identity.match_anchor(capture, [member]) is None


def test_match_anchor_does_not_bind_child_agent_to_agent_ancestor() -> None:
    selected = identity.ProcessInfo(
        pid=200,
        ppid=123,
        start_time="child-start",
        exe="/usr/bin/codex",
        argv=("codex",),
    )
    parent = identity.ProcessInfo(
        pid=123,
        ppid=1,
        start_time="parent-start",
        exe="/usr/bin/python3",
        argv=("python3", "agent.py"),
    )
    capture = identity.IdentityCapture(
        chain=(selected, parent),
        host=identity.HostIdentity("host:test", "test-host", "test host identity"),
        uid=501,
        login="van",
        anchor=selected,
        kind="agent",
        rule="agent anchor selected at codex",
    )
    parent_member = _member_row(
        anchor_pid=parent.pid,
        anchor_start_time=parent.start_time,
    )

    assert identity.match_anchor(capture, [parent_member]) is None


def test_match_anchor_rejects_unanchorable_ancestor() -> None:
    selected = identity.ProcessInfo(
        pid=200,
        start_time="child-start",
        exe="/usr/bin/codex",
        argv=("codex",),
    )
    ancestor = identity.ProcessInfo(
        pid=123,
        start_time=None,
        exe="/usr/bin/python3",
        argv=("python3", "agent.py"),
    )
    capture = identity.IdentityCapture(
        chain=(selected, ancestor),
        host=identity.HostIdentity("host:test", "test-host", "test host identity"),
        uid=501,
        login="van",
        anchor=selected,
        kind="agent",
        rule="agent anchor selected at codex",
    )
    member = _member_row(anchor_pid=ancestor.pid, anchor_start_time=None)

    assert identity.match_anchor(capture, [member]) is None


def test_member_presence_distinguishes_human_remote_here_and_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        identity,
        "capture_process",
        lambda pid: (
            identity.ProcessInfo(pid=pid, start_time="start") if pid == 123 else None
        ),
    )

    assert identity.member_presence(_member_row(kind="human"), "host:test") == "active"
    assert (
        identity.member_presence(_member_row(host_id="host:remote"), "host:test")
        == "remote"
    )
    assert (
        identity.member_presence(
            _member_row(anchor_pid=999, anchor_start_time="start"),
            "host:test",
        )
        == "gone"
    )
    assert identity.member_presence(_member_row(), "host:test") == "here"


def test_choose_name_uses_seed_pool_history_then_numeric_suffix() -> None:
    assert identity.choose_name(seed="New Agent", taken=set()) == "New-agent"
    assert (
        identity.choose_name(seed="codex", taken={"codex"})
        == (PER_BASENAME_NAME_POOLS["codex"][0])
    )
    assert identity.choose_name(seed="worker", taken={"worker"}) == "Ada"

    taken = {"agent", *HISTORICAL_NAME_POOL}

    assert identity.choose_name(seed=None, taken=taken) == "Agent-2"


def test_choose_name_capitalizes_first_ascii_letter_after_leading_digits() -> None:
    assert identity.choose_name(seed="2agent", taken=set()) == "2Agent"
    assert identity.choose_name(seed="123", taken=set()) == "123"


def test_choose_name_reaches_every_curated_candidate_in_declared_order() -> None:
    for seed, pool in PER_BASENAME_NAME_POOLS.items():
        taken = {seed}
        for expected in pool:
            first_letter = next(
                character for character in expected if character.isalpha()
            )
            assert "A" <= first_letter <= "Z"
            assert identity.choose_name(seed=seed, taken=taken) == expected
            taken.add(expected)
    assert all("A" <= name[0] <= "Z" for name in HISTORICAL_NAME_POOL)


def test_rank_candidates_scores_matching_process_fingerprints() -> None:
    capture = _capture()
    full_match = _member_row(
        display_name="ada",
        fingerprint=json.dumps(
            {
                "exe": "/usr/bin/codex",
                "cwd": "/workspace",
                "tty": "ttys001",
                "session_id": 456,
            }
        ),
        last_active_ts=1,
    )
    exe_only = _member_row(
        member_id="m_" + "b" * 26,
        display_name="bob",
        fingerprint=json.dumps({"exe": "/usr/bin/codex"}),
        last_active_ts=99,
    )
    ignored = [
        _member_row(member_id="m_" + "c" * 26, kind="human", fingerprint="{}"),
        _member_row(member_id="m_" + "d" * 26, fingerprint=None),
        _member_row(member_id="m_" + "e" * 26, fingerprint="{not json"),
        _member_row(
            member_id="m_" + "f" * 26,
            fingerprint=json.dumps({"exe": "/usr/bin/other"}),
        ),
    ]

    ranked = identity.rank_candidates(capture, [exe_only, *ignored, full_match])

    assert ranked == [
        (
            full_match,
            ["same executable", "same cwd", "same tty", "same session"],
        ),
        (exe_only, ["same executable"]),
    ]
    assert identity.rank_candidates(_capture(anchor=False), [full_match]) == []


def test_rank_candidates_scores_stored_session_id_zero() -> None:
    capture = _capture()
    assert capture.anchor is not None
    capture = replace(capture, anchor=replace(capture.anchor, session_id=0))
    match = _member_row(
        fingerprint=json.dumps({"session_id": 0}),
    )

    assert identity.rank_candidates(capture, [match]) == [
        (match, ["same session"]),
    ]


def test_capture_linux_process_reads_procfs_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stat_fields = ["S", "1", "123", "456", "0", *("0" for _ in range(14)), "98765"]
    stat = "123 (codex) " + " ".join(stat_fields)

    def fake_read_text(self: Path, **_kwargs: Any) -> str:
        path = self.as_posix()
        if path == "/proc/123/stat":
            return stat
        if path == "/proc/123/status":
            return "Name:\tcodex\nUid:\t501\t501\t501\t501\n"
        raise OSError("missing")

    def fake_read_bytes(self: Path) -> bytes:
        if self.as_posix() == "/proc/123/cmdline":
            return b"codex\0--work\0"
        raise OSError("missing")

    def fake_readlink(self: Path) -> PurePosixPath:
        if self.as_posix() == "/proc/123/exe":
            return PurePosixPath("/usr/bin/codex")
        if self.as_posix() == "/proc/123/cwd":
            return PurePosixPath("/workspace")
        raise OSError("missing")

    monkeypatch.setattr(identity.Path, "read_text", fake_read_text)
    monkeypatch.setattr(identity.Path, "read_bytes", fake_read_bytes)
    monkeypatch.setattr(identity.Path, "readlink", fake_readlink)
    monkeypatch.setattr(identity.sys, "platform", "linux")

    proc = identity._capture_linux_process(123)

    assert proc == identity.ProcessInfo(
        pid=123,
        ppid=1,
        start_time="proc:98765",
        exe="/usr/bin/codex",
        argv=("codex", "--work"),
        uid=501,
        pgid=123,
        session_id=456,
        tty=None,
        cwd="/workspace",
    )


def test_capture_linux_process_returns_none_for_missing_or_malformed_stat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_read_text(self: Path, **_kwargs: Any) -> str:
        assert self.as_posix() == "/proc/123/stat"
        raise OSError("missing")

    monkeypatch.setattr(identity.Path, "read_text", missing_read_text)
    assert identity._capture_linux_process(123) is None

    def malformed_read_text(self: Path, **_kwargs: Any) -> str:
        assert self.as_posix() == "/proc/123/stat"
        return "not proc stat"

    monkeypatch.setattr(identity.Path, "read_text", malformed_read_text)
    assert identity._capture_linux_process(123) is None


def test_capture_psutil_process_reads_best_effort_fields(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-060] exception
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOneshot:
        def __enter__(self) -> Self:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

    class FakeProcess:
        def oneshot(self) -> FakeOneshot:
            return FakeOneshot()

        def ppid(self) -> int:
            return 1

        def create_time(self) -> float:
            return 123.456

        def exe(self) -> str:
            return "/usr/bin/codex"

        def cmdline(self) -> list[str]:
            return ["codex", "--work"]

        def cwd(self) -> str:
            return "/workspace"

        def uids(self) -> SimpleNamespace:
            return SimpleNamespace(real=501)

        def terminal(self) -> str:
            return "ttys001"

    monkeypatch.setattr(identity.psutil, "Process", lambda _pid: FakeProcess())
    monkeypatch.setattr(
        identity, "start_time_token", lambda _pid, _proc: "psutil:123456000"
    )
    monkeypatch.setattr(identity, "_safe_getpgid", lambda _pid: 123)
    monkeypatch.setattr(identity, "_safe_getsid", lambda _pid: 456)

    proc = identity._capture_psutil_process(123)

    assert proc == identity.ProcessInfo(
        pid=123,
        ppid=1,
        start_time="psutil:123456000",
        exe="/usr/bin/codex",
        argv=("codex", "--work"),
        uid=501,
        pgid=123,
        session_id=456,
        tty="ttys001",
        cwd="/workspace",
    )


def test_capture_psutil_process_returns_none_when_psutil_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_process(_pid: int) -> object:
        raise psutil.Error("missing")

    monkeypatch.setattr(identity.psutil, "Process", raise_process)
    assert identity._capture_psutil_process(123) is None

    class BrokenOneshot:
        def __enter__(self) -> Self:
            raise psutil.Error("gone")

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

    class BrokenProcess:
        def oneshot(self) -> BrokenOneshot:
            return BrokenOneshot()

    monkeypatch.setattr(identity.psutil, "Process", lambda _pid: BrokenProcess())
    assert identity._capture_psutil_process(123) is None


def test_start_time_token_is_digits_with_scheme_on_this_platform() -> None:
    proc = psutil.Process(os.getpid())
    token = identity.start_time_token(os.getpid(), proc)

    assert token is not None
    assert TOKEN_RE.fullmatch(token), token
    expected = "proc" if sys.platform.startswith("linux") else "psutil"
    assert token.split(":", 1)[0] == expected


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc only")
def test_linux_start_time_token_is_proc_stat_field_22() -> None:
    stat = Path(f"/proc/{os.getpid()}/stat").read_text(encoding="utf-8")
    ticks = stat.rpartition(") ")[2].split()[19]

    assert identity.start_time_token(os.getpid(), None) == f"proc:{ticks}"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS source only")
def test_macos_start_time_token_is_integer_microseconds() -> None:
    proc = psutil.Process(os.getpid())
    raw = cast(Any, proc)._proc.create_time(monotonic=True)

    assert identity.start_time_token(os.getpid(), proc) == (
        f"psutil:{round(raw * 1_000_000)}"
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows source only")
def test_windows_start_time_token_is_integer_microseconds() -> None:
    proc = psutil.Process(os.getpid())

    assert identity.start_time_token(os.getpid(), proc) == (
        f"psutil:{round(proc.create_time() * 1_000_000)}"
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS source only")
def test_macos_start_time_token_ignores_boot_time_adjustments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from psutil import _psosx

    pid = os.getpid()
    boot = 1_000_000.0
    raw_values: list[float] = []
    tokens: list[str | None] = []
    adjusted: list[float] = []
    monkeypatch.setattr(_psosx, "INIT_BOOT_TIME", boot)
    for observed_boot in (boot, boot + 2, boot - 2):
        monkeypatch.setattr(_psosx, "boot_time", lambda value=observed_boot: value)
        proc = psutil.Process(pid)
        raw_values.append(cast(Any, proc)._proc.create_time(monotonic=True))
        tokens.append(identity.start_time_token(pid, proc))
        adjusted.append(psutil.Process(pid).create_time())

    assert raw_values[0] == raw_values[1] == raw_values[2]
    assert tokens[0] is not None and tokens[0] == tokens[1] == tokens[2]
    assert any(value != adjusted[0] for value in adjusted[1:])


def test_start_time_token_matches_across_observer_processes() -> None:
    code = (
        "import os, psutil; from taut.identity import start_time_token; "
        "pid=int(os.environ['TAUT_TEST_PID']); "
        "print(start_time_token(pid, psutil.Process(pid)))"
    )
    base_env = {**os.environ, "TAUT_TEST_PID": str(os.getpid())}
    environments = (
        {**base_env, "LC_ALL": "C", "LANG": "C"},
        {**base_env, "LC_ALL": "de_DE.UTF-8", "LANG": "ja_JP.UTF-8"},
    )
    observed = [
        subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        for env in environments
    ]

    assert [item.returncode for item in observed] == [0, 0]
    tokens = [item.stdout.strip() for item in observed]
    assert all(TOKEN_RE.fullmatch(token) for token in tokens), observed
    assert tokens[0] == tokens[1]


def test_start_time_token_returns_none_when_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform.startswith("linux"):

        def raise_oserror(_self: Path, **_kwargs: Any) -> str:
            raise OSError("missing")

        monkeypatch.setattr(identity.Path, "read_text", raise_oserror)
        assert identity.start_time_token(123, None) is None
        return

    class BrokenNative:
        def create_time(self, **_kwargs: Any) -> float:
            raise psutil.AccessDenied(123)

    class BrokenProcess:
        _proc = BrokenNative()

        def create_time(self) -> float:
            raise psutil.AccessDenied(123)

    assert identity.start_time_token(123, cast(psutil.Process, BrokenProcess())) is None


@pytest.mark.skipif(sys.platform.startswith("linux"), reason="psutil source only")
def test_start_time_token_without_psutil_object_off_linux() -> None:
    assert identity.start_time_token(os.getpid(), None) is None


def test_linux_start_time_token_rejects_malformed_stat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity.sys, "platform", "linux")
    cases = (
        " ".join(["0"] * 19 + ["98765"]),
        "123 (codex) S",
        "123 (codex) " + " ".join(["0"] * 19 + [""]),
        "123 (codex) " + " ".join(["0"] * 19 + ["not-digits"]),
        "123 (codex) " + " ".join(["0"] * 19 + ["²"]),
    )
    for stat in cases:
        monkeypatch.setattr(
            identity.Path, "read_text", lambda _self, value=stat, **_kwargs: value
        )
        assert identity.start_time_token(123, None) is None


def test_capture_process_never_spawns_a_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"subprocess spawned: {args[0] if args else 'unknown'}")

    with monkeypatch.context() as context:
        context.setattr(identity.subprocess, "run", forbid)
        proc = identity.capture_process(os.getpid())

    assert proc is not None
    assert proc.start_time is not None


def test_capture_process_psutil_failure_never_spawns_a_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"subprocess spawned: {args[0] if args else 'unknown'}")

    with monkeypatch.context() as context:
        context.setattr(identity, "_capture_psutil_process", lambda _pid: None)
        context.setattr(identity.subprocess, "run", forbid)
        proc = identity.capture_process(os.getpid())

    if sys.platform.startswith("linux"):
        assert proc is not None
        assert proc.start_time == identity.start_time_token(os.getpid(), None)
    else:
        assert proc is None


def test_capture_without_start_time_uses_human_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity, "start_time_token", lambda _pid, _proc: None)

    proc = identity._capture_psutil_process(os.getpid())

    assert proc is not None
    assert proc.start_time is None
    anchor, reason = identity.select_anchor([proc])
    assert anchor is None
    assert "has no start-time token" in reason


def test_psutil_field_helpers_return_empty_values_on_psutil_errors() -> None:
    class FailingProcess:
        def ppid(self) -> int:
            raise psutil.Error("ppid")

        def exe(self) -> str:
            raise OSError("exe")

        def cmdline(self) -> list[str]:
            raise psutil.Error("argv")

        def cwd(self) -> str:
            raise OSError("cwd")

        def uids(self) -> SimpleNamespace:
            raise psutil.Error("uids")

        def terminal(self) -> str:
            raise psutil.Error("tty")

    proc = cast(psutil.Process, FailingProcess())

    assert identity._psutil_ppid(proc) is None
    assert identity._psutil_exe(proc) is None
    assert identity._psutil_argv(proc) == ()
    assert identity._psutil_cwd(proc) is None
    assert identity._psutil_uid(proc) is None
    assert identity._psutil_terminal(proc) is None


def test_safe_process_group_helpers_return_none_on_os_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_os_error(_pid: int) -> int:
        raise OSError("missing")

    monkeypatch.setattr(identity.os, "getpgid", raise_os_error, raising=False)
    monkeypatch.setattr(identity.os, "getsid", raise_os_error, raising=False)

    assert identity._safe_getpgid(123) is None
    assert identity._safe_getsid(123) is None


def test_linux_proc_helpers_tolerate_missing_or_bad_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc_dir = Path("/proc/123")

    def missing_bytes(_self: Path) -> bytes:
        raise OSError("missing")

    monkeypatch.setattr(identity.Path, "read_bytes", missing_bytes)
    assert identity._read_linux_argv(proc_dir) == ()

    def bad_uid_text(self: Path, **_kwargs: Any) -> str:
        assert self.as_posix() == "/proc/123/status"
        return "Uid:\tnot-int\n"

    monkeypatch.setattr(identity.Path, "read_text", bad_uid_text)
    assert identity._read_linux_uid(proc_dir) is None

    def no_uid_text(_self: Path, **_kwargs: Any) -> str:
        return "Name:\tcodex\n"

    monkeypatch.setattr(identity.Path, "read_text", no_uid_text)
    assert identity._read_linux_uid(proc_dir) is None

    def missing_status(_self: Path, **_kwargs: Any) -> str:
        raise OSError("missing")

    monkeypatch.setattr(identity.Path, "read_text", missing_status)
    assert identity._read_linux_uid(proc_dir) is None

    def missing_link(_self: Path) -> Path:
        raise OSError("missing")

    monkeypatch.setattr(identity.Path, "readlink", missing_link)
    assert identity._safe_readlink(Path("/proc/123/exe")) is None


def test_login_name_falls_back_to_platform_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePwd:
        @staticmethod
        def getpwuid(_uid: int) -> object:
            raise KeyError("missing")

    monkeypatch.setattr(identity, "_PWD", FakePwd)
    monkeypatch.setattr(
        identity.getpass,
        "getuser",
        lambda: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    monkeypatch.setattr(identity.platform, "node", lambda: "node-host")

    assert identity._login_name(501) == "node-host"


def test_same_process_evidence_produces_same_claim_hash() -> None:
    first = identity.claim_for_capture(_capture())
    second = identity.claim_for_capture(_capture())

    assert first.claim_hash == second.claim_hash
    assert first.claim_hash.startswith("ic_")
    assert len(first.claim_hash) == 55


def test_display_name_material_does_not_change_claim_hash() -> None:
    first_capture = _capture()
    second_capture = replace(
        first_capture,
        host=replace(first_capture.host, host_label="renamed-display-host"),
        login="renamed-display-login",
        rule="different-diagnostic-rule",
    )
    first = identity.claim_for_capture(first_capture)
    second = identity.claim_for_capture(second_capture)

    assert first.evidence == second.evidence
    assert first.claim_hash == second.claim_hash


def test_different_process_start_token_changes_claim_hash() -> None:
    first = identity.claim_for_capture(_capture(start_time="one"))
    second = identity.claim_for_capture(_capture(start_time="two"))

    assert first.claim_hash != second.claim_hash


def test_human_session_claim_includes_host_and_uid() -> None:
    claim = identity.claim_for_capture(_capture(anchor=False))

    assert claim.claim_kind == "human_session"
    assert claim.evidence["host_id"] == "host:test"
    assert claim.evidence["uid"] == 501


def test_random_member_id_has_opaque_random_token_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_byte_sizes: list[int] = []

    def token_bytes(size: int) -> bytes:
        token_byte_sizes.append(size)
        return b"\x00" * size

    monkeypatch.setattr(identity.secrets, "token_bytes", token_bytes)

    member_id = identity.random_member_id()

    assert token_byte_sizes == [20]
    assert member_id == "m_" + "a" * 32
    assert re.fullmatch(r"m_[a-z0-9]{26,52}", member_id)


def test_login_name_falls_back_without_pwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """The identity module must import and resolve a login name on platforms
    without the Unix-only ``pwd`` module."""

    def fake_getuser() -> str:
        return "windows-user"

    monkeypatch.setattr(identity, "_PWD", None)
    monkeypatch.setattr(identity.getpass, "getuser", fake_getuser)

    assert identity._login_name(0) == "windows-user"


def test_psutil_terminal_falls_back_when_platform_lacks_terminal() -> None:
    """Some psutil backends do not expose ``Process.terminal``."""

    class ProcessWithoutTerminal:
        pass

    proc = cast(psutil.Process, ProcessWithoutTerminal())

    assert identity._psutil_terminal(proc) is None


@_POSIX_SHELL_PROCESS_TEST
@pytest.mark.usefixtures("clean_env")
def test_recognition_survives_fresh_shell_per_command(tmp_path: Path) -> None:
    """[IAN-3.3]: the same member must resolve across separate shell
    invocations — the headline recognition feature for per-command agents."""
    shell = shutil.which("bash") or "/bin/sh"
    _init_db(tmp_path)

    created = _join_and_capture_name(shell, tmp_path)

    # A *new* shell wrapper: different pid, same durable ancestry.
    rc, resolved = _whoami(shell, tmp_path)
    assert rc == 0, (
        "caller unrecognized from a second shell invocation — the anchor "
        "landed on the disposable wrapper instead of a durable ancestor"
    )
    assert resolved == created

    # Same-name alone can be masked by a live shell higher in the test
    # runner's own ancestry: the anchor must never be a shell at all
    # ([IAN-3.2] — shells are skipped, not anchored).
    anchor_argv0 = _anchor_argv0(shell, tmp_path)
    assert Path(anchor_argv0).name.lower() not in _SHELL_BASENAMES, (
        f"anchor landed on a shell process ({anchor_argv0}); the walk must "
        "skip shells even when the captured executable name is truncated"
    )
    assert created == _expected_name_from_anchor(anchor_argv0)


_NESTED_AGENT_HARNESS = """
import json
import os
import subprocess
import sys

db = sys.argv[1]
cli_python = sys.argv[2]
force_new = sys.argv[3] == "new"
env = os.environ.copy()
env["TAUT_DB"] = db


def taut(*args):
    completed = subprocess.run(
        [cli_python, "-m", "taut", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return {
        "rc": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


join_args = ("--json", "join", "general", "--new") if force_new else (
    "--json", "join", "general"
)
print(json.dumps({"join": taut(*join_args),
                  "whoami": taut("--json", "whoami", "--explain")}))
"""


@pytest.mark.skipif(
    os.name == "nt",
    reason="symlinked executable ancestry is a POSIX process contract",
)
@pytest.mark.usefixtures("clean_env")
@pytest.mark.parametrize("force_new", [False, True], ids=["join", "join-new"])
def test_nested_agent_first_contact_does_not_bind_parent_member(
    tmp_path: Path,
    force_new: bool,
) -> None:
    shell = shutil.which("bash") or "/bin/sh"
    _init_db(tmp_path)
    parent_name = _join_and_capture_name(shell, tmp_path)
    observer = TautClient(db_path=tmp_path / ".taut.db")
    state = cast(SqlSidecarTautState, observer._state)
    parent = state.get_member_by_route_key(parent_name.casefold())
    assert parent is not None
    parent_claims_before = [
        record
        for record in state.persistence_records()
        if record["type"] == "identity_claim"
        and record["member_id"] == parent["member_id"]
    ]
    observer.close()
    harness = tmp_path / "nested_agent.py"
    harness.write_text(_NESTED_AGENT_HARNESS, encoding="utf-8")
    codex = tmp_path / "codex"
    codex.symlink_to(sys.executable)

    completed = subprocess.run(
        [
            str(codex),
            str(harness),
            str(tmp_path / ".taut.db"),
            sys.executable,
            "new" if force_new else "ordinary",
        ],
        cwd=tmp_path,
        env=build_cli_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    results = json.loads(completed.stdout.strip().splitlines()[-1])
    joined = results["join"]
    assert joined["rc"] == 0, joined["stderr"]
    creation = next(obj for obj in _json_lines(joined["stdout"]) if "token" in obj)
    assert creation["name"] != parent_name
    resolved = results["whoami"]
    assert resolved["rc"] == 0, resolved["stderr"]
    whoami = _json_lines(resolved["stdout"])[-1]
    assert whoami["member_id"] == creation["member_id"]
    assert whoami["explain"]["rule"] == "identity claim"
    observer = TautClient(db_path=tmp_path / ".taut.db")
    state = cast(SqlSidecarTautState, observer._state)
    parent_claims_after = [
        record
        for record in state.persistence_records()
        if record["type"] == "identity_claim"
        and record["member_id"] == parent["member_id"]
    ]
    observer.close()
    assert parent_claims_after == parent_claims_before


_READ_ONLY_CHILD_HARNESS = """
import json
import os
import subprocess
import sys

db = sys.argv[1]
cli_python = sys.argv[2]
otherdir = sys.argv[3]
verb = sys.argv[4]
env = os.environ.copy()
env["TAUT_DB"] = db


def taut(*args):
    return subprocess.run(
        [cli_python, "-m", "taut", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def snapshot():
    source = (
        "import json,sys; "
        "from simplebroker import Queue; "
        "from taut import TautClient; "
        "from taut._constants import META_QUEUE_NAME; "
        "client=TautClient(db_path=sys.argv[1]); "
        "meta=Queue(META_QUEUE_NAME,db_path=sys.argv[1]); "
        "print(json.dumps([client._state.persistence_records(),"
        "meta.refresh_last_ts()])); meta.close(); client.close()"
    )
    completed = subprocess.run(
        [cli_python, "-c", source, db],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=True,
    )
    return json.loads(completed.stdout)


joined = taut("--json", "join", "general")
created = next(
    json.loads(line)
    for line in joined.stdout.splitlines()
    if "token" in json.loads(line)
)
assert taut("--as", "other", "join", "general").returncode == 0
assert taut("--as", "other", "say", "general", "unread").returncode == 0
assert taut("--as", "other", "say", "@" + created["name"], "direct").returncode == 0

commands = {
    "whoami": ("--json", "whoami"),
    "whoami-explain": ("--json", "whoami", "--explain"),
    "who": ("--json", "who"),
    "list": ("--json", "list"),
    "list-all": ("--json", "list", "--all"),
    "list-dms": ("--json", "list", "--dms"),
}
os.chdir(otherdir)
before = snapshot()
completed = taut(*commands[verb])
after = snapshot()
print(json.dumps({
    "rc": completed.returncode,
    "stdout": completed.stdout,
    "stderr": completed.stderr,
    "unchanged": before == after,
}))
"""


@pytest.mark.skipif(
    os.name == "nt",
    reason="symlinked executable ancestry is a POSIX process contract",
)
@pytest.mark.usefixtures("clean_env")
@pytest.mark.parametrize(
    "verb",
    ["whoami", "whoami-explain", "who", "list", "list-all", "list-dms"],
)
def test_read_verbs_are_read_only_in_fresh_child_processes(
    tmp_path: Path,
    verb: str,
) -> None:
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    otherdir = tmp_path / "moved"
    otherdir.mkdir()
    _init_db(workdir)
    harness = tmp_path / "read_only_child.py"
    harness.write_text(_READ_ONLY_CHILD_HARNESS, encoding="utf-8")
    codex = tmp_path / "codex"
    codex.symlink_to(sys.executable)

    completed = subprocess.run(
        [
            str(codex),
            str(harness),
            str(workdir / ".taut.db"),
            sys.executable,
            str(otherdir),
            verb,
        ],
        cwd=workdir,
        env=build_cli_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["rc"] == 0, result["stderr"]
    assert result["stdout"]
    assert result["unchanged"] is True


@_POSIX_SHELL_PROCESS_TEST
@pytest.mark.usefixtures("clean_env")
def test_shell_skip_survives_long_executable_paths(tmp_path: Path) -> None:
    """[IAN-3.2]: shell classification must not depend on a
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

    created = _join_and_capture_name(shell, workdir)
    # The name must come from a durable ancestor, never from the shell
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
    assert created == _expected_name_from_anchor(anchor_argv0)


@_POSIX_SHELL_PROCESS_TEST
@pytest.mark.usefixtures("clean_env")
def test_token_acts_as_unanchored_member_despite_different_live_anchor(
    tmp_path: Path,
) -> None:
    """[IAN-3.3]/[TAUT-11]: a continuity token bypasses process-tree
    heuristics, even when the live chain would resolve another member."""
    shell = shutil.which("bash") or "/bin/sh"
    _init_db(tmp_path)

    completed = _taut_via_shell(shell, "--as ada --json join general", tmp_path)
    assert completed.returncode == 0, completed.stderr

    completed = _taut_via_shell(shell, "--as van --json join general", tmp_path)
    assert completed.returncode == 0, completed.stderr
    token = next(
        json.loads(line)["token"]
        for line in completed.stdout.splitlines()
        if "token" in json.loads(line)
    )

    rc, resolved = _whoami(shell, tmp_path)
    assert rc == 0
    assert resolved == "ada"

    completed = _taut_via_shell(
        shell,
        "--json whoami",
        tmp_path,
        env={"TAUT_TOKEN": token},
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip())["name"] == "van"


_CHDIR_HARNESS = '''
"""Long-lived anchor harness: invokes taut, chdir()s, reads, writes, reads.

This process is a plain Python process (non-wrapper basename), so the
anchor walk selects *it* as the anchor for every taut invocation below.
"""

import json
import os
import subprocess
import sys

db = sys.argv[1]
workdir = sys.argv[2]
otherdir = sys.argv[3]

env = os.environ.copy()
env["TAUT_DB"] = db


def taut(*args):
    completed = subprocess.run(
        [sys.executable, "-m", "taut", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return {
        "rc": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


os.chdir(workdir)
results = {"join": taut("--json", "join", "general")}
os.chdir(otherdir)
results["whoami_after_chdir"] = taut("--json", "whoami", "--explain")
results["say_to_heal"] = taut("say", "general", "heal on write")
results["whoami_after_heal"] = taut("--json", "whoami", "--explain")
print(json.dumps(results))
'''


def _json_lines(stdout: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stdout.strip().splitlines() if line.strip()]


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX process-chain ancestry is not a Windows process contract",
)
@pytest.mark.usefixtures("clean_env")
def test_anchor_match_survives_anchor_chdir_in_real_chain(tmp_path: Path) -> None:
    """[IAN-3.3] step 4, proven on a real process chain: a long-lived anchor
    process that ``os.chdir()``s between taut invocations keeps resolving to
    the same member. A shell cannot host this proof — ``select_anchor()``
    skips shells — so the anchor is a small long-lived Python harness.

    The first read resolves via ``anchor match`` without healing. A later
    state-changing verb records the claim, then the final read resolves via
    ``identity claim``.
    """
    workdir = tmp_path / "proj"
    workdir.mkdir()
    otherdir = tmp_path / "elsewhere"
    otherdir.mkdir()
    _init_db(workdir)
    harness = tmp_path / "anchor_harness.py"
    harness.write_text(_CHDIR_HARNESS, encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(harness),
            str(workdir / ".taut.db"),
            str(workdir),
            str(otherdir),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        # The harness invokes `python -m taut`; without the repo on
        # PYTHONPATH it could import an installed taut and prove nothing
        # about the working tree.
        env=build_cli_env(),
    )
    assert completed.returncode == 0, completed.stderr
    results = json.loads(completed.stdout.strip().splitlines()[-1])

    join = results["join"]
    assert join["rc"] == 0, join["stderr"]
    creation = next(obj for obj in _json_lines(join["stdout"]) if "token" in obj)
    member_id = creation["member_id"]

    moved = results["whoami_after_chdir"]
    assert moved["rc"] == 0, (
        "caller unrecognized after the anchor chdir()ed — the mutable-cwd "
        "claim orphaned a live anchor: " + moved["stderr"]
    )
    moved_obj = _json_lines(moved["stdout"])[-1]
    assert moved_obj["member_id"] == member_id
    assert moved_obj["explain"]["rule"] == "anchor match"

    say = results["say_to_heal"]
    assert say["rc"] == 0, say["stderr"]

    healed = results["whoami_after_heal"]
    assert healed["rc"] == 0, healed["stderr"]
    healed_obj = _json_lines(healed["stdout"])[-1]
    assert healed_obj["member_id"] == member_id
    assert healed_obj["explain"]["rule"] == "identity claim"


_CONCURRENT_JOIN_WORKER = '''
"""First-contact join worker: one synthetic agent capture per process.

The capture is injected only through the public
``TautClient(identity_capture=...)`` seam; the broker, sidecar, and state
layer are all real, so the name race is a real cross-process race.
"""

import json
import os
import sys
import time
from pathlib import Path

import taut.identity as identity
from taut.client import TautClient

db = sys.argv[1]
barrier_dir = Path(sys.argv[2])
worker = sys.argv[3]

pid = os.getpid()
process = identity.ProcessInfo(
    pid=pid,
    ppid=1,
    start_time=f"start-{pid}",
    exe="/usr/local/bin/workerbot",
    argv=("workerbot",),
    uid=501,
    pgid=pid,
    session_id=7,
    tty=None,
    cwd="/workspace",
)
capture = identity.IdentityCapture(
    chain=(process,),
    host=identity.HostIdentity(
        "host:concurrency", "concurrency-host", "test host identity"
    ),
    uid=501,
    login="tester",
    anchor=process,
    kind="agent",
    rule="test capture",
)
client = TautClient(db_path=db, identity_capture=capture)

(barrier_dir / f"ready-{worker}").touch()
go = barrier_dir / "go"
deadline = time.monotonic() + 60
while not go.exists():
    if time.monotonic() > deadline:
        raise SystemExit(3)
    time.sleep(0.001)

client.join("general")
member = client.whoami()
print(json.dumps({"member_id": member.member_id, "name": member.name}))
'''


@pytest.mark.usefixtures("clean_env")
def test_concurrent_first_contact_joins_all_get_distinct_names(
    tmp_path: Path,
) -> None:
    """[IAN-9]: N simultaneous first-contact joins with the same name seed
    must all succeed with distinct member ids and distinct names. Workers are
    real separate processes synchronized on a file barrier so their
    snapshot-then-insert windows overlap; the deterministic single-collision
    proof lives in tests/test_client.py
    (test_first_contact_join_retries_next_name_after_losing_race), because a
    barrier cannot guarantee the overlap on every run.
    """
    _init_db(tmp_path)
    barrier_dir = tmp_path / "barrier"
    barrier_dir.mkdir()
    worker_script = tmp_path / "join_worker.py"
    worker_script.write_text(_CONCURRENT_JOIN_WORKER, encoding="utf-8")

    count = 5
    workers = [
        subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                str(tmp_path / ".taut.db"),
                str(barrier_dir),
                str(index),
            ],
            env=build_cli_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(count)
    ]
    try:
        deadline = time.monotonic() + 60
        while len(list(barrier_dir.glob("ready-*"))) < count:
            if time.monotonic() > deadline:
                raise AssertionError("workers never reached the barrier")
            time.sleep(0.01)
        (barrier_dir / "go").touch()
        outputs = [worker.communicate(timeout=120) for worker in workers]
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()

    failures = [
        (worker.returncode, stderr)
        for worker, (_stdout, stderr) in zip(workers, outputs, strict=True)
        if worker.returncode != 0
    ]
    assert not failures, f"first-contact joins failed: {failures}"
    members = [json.loads(stdout.strip().splitlines()[-1]) for stdout, _ in outputs]
    assert len({member["member_id"] for member in members}) == count
    assert len({member["name"] for member in members}) == count
