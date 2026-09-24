"""Root-CLI scenarios driven through a test-owned POSIX host terminal."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import termios
import time
from pathlib import Path
from typing import Any

import pytest
from conftest import _base_env

from taut.identity import capture_process
from tests.helpers.terminal_probe import PosixHostShell  # type: ignore[import-untyped]

pytestmark = pytest.mark.posix_only

_FALSEY_ENV = {"", "0", "false", "no", "off"}
_KITTY_ENABLE_SEQUENCE = re.compile(rb"\x1b\[(?:>|=)[1-9][0-9]*(?:;[0-9]+)*u")
_REAL_PROVIDER_READY_TEXT = {
    "claude": "Claude",
    "coder": "Coder",
    "codex": "Codex",
    "grok": "Grok",
    "kimi": "Kimi",
    "opencode": "OpenCode",
    "pi": "Pi",
    "qwen": "Qwen",
}


@pytest.mark.skipif(os.name == "nt", reason="POSIX host PTY contract")
def test_host_shell_owns_real_terminal_and_cumulative_transcript(
    tmp_path: Path,
) -> None:
    with PosixHostShell.open(cwd=tmp_path) as shell:
        shell.wait_for_prompt()
        cooked = shell.termios_snapshot()
        start = shell.mark()

        shell.run("printf 'host-probe-ok\\n'")

        shell.wait_for_text("host-probe-ok", after=start)
        shell.wait_for_prompt(after=start)
        assert shell.termios_snapshot() == cooked
        assert "host-probe-ok" in shell.text

        raw_start = shell.mark()
        shell.run(
            shlex.join(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os,tty;tty.setraw(0);"
                        "print(bytes.fromhex('5241572d5245414459').decode(),flush=True);"
                        "print(os.read(0,2).hex(),flush=True)"
                    ),
                ]
            )
        )
        shell.wait_for_text("RAW-READY", after=raw_start)
        shell.write(b"\x1c\x1c")
        shell.wait_for_text("1c1c", after=raw_start)
        shell.wait_for_prompt(after=raw_start)


@pytest.mark.skipif(os.name == "nt", reason="POSIX host PTY contract")
def test_host_shell_cleanup_kills_term_ignoring_foreground_child(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "term-ignoring-child.pid"
    shell = PosixHostShell.open(cwd=tmp_path)
    child_pid: int | None = None
    try:
        shell.wait_for_prompt()
        command = (
            "import os,signal,time,pathlib;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()));"
            "print('TERM-IGNORING-READY',flush=True);"
            "time.sleep(60)"
        )
        shell.run(shlex.join([sys.executable, "-c", command]))
        shell.wait_for_text("TERM-IGNORING-READY")
        child_pid = int(pid_file.read_text(encoding="utf-8"))
        assert capture_process(child_pid) is not None
    finally:
        shell.close()

    assert child_pid is not None
    _wait_until(
        lambda: capture_process(child_pid) is None,
        message="term-ignoring host child retirement",
    )


def _run(
    *args: str,
    cwd: Path,
    env: dict[str, str],
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30.0,
        check=False,
    )


def _entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _wait_until(predicate: Any, *, message: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {message}")


def _wait_for_status(db: Path, name: str, *, cwd: Path, env: dict[str, str]) -> str:
    last = ""

    def ready() -> bool:
        nonlocal last
        result = _run("taut_summon", "status", name, "--db", str(db), cwd=cwd, env=env)
        last = f"stdout={result.stdout!r}; stderr={result.stderr!r}"
        return result.returncode == 0 and "awaiting_onboarding" not in result.stdout

    _wait_until(ready, message=f"out-of-band live wired status; last={last}")
    return last


def _root_command(db: Path, *args: str) -> str:
    return shlex.join([sys.executable, "-m", "taut", "--db", str(db), *args])


def _wait_for_cooked(shell: PosixHostShell, cooked: list[Any], *, message: str) -> None:
    deadline = time.monotonic() + 20.0
    current: list[Any] = []
    while time.monotonic() < deadline:
        shell.read_available()
        current = shell.termios_snapshot()
        if _configured_termios(current) == _configured_termios(cooked):
            return
        time.sleep(0.05)
    raise AssertionError(
        f"timed out waiting for {message}; saved={cooked!r}; current={current!r}"
    )


def _configured_termios(attributes: list[Any]) -> list[Any]:
    """Ignore only the kernel-maintained pending-input status bit."""

    configured = list(attributes)
    configured[3] = int(configured[3]) & ~int(getattr(termios, "PENDIN", 0))
    return configured


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and value.strip().lower() not in _FALSEY_ENV


def _live_lane_enabled() -> bool:
    configured = os.environ.get("TAUT_SUMMON_LIVE_HARNESS")
    if configured is not None:
        return configured.strip().lower() not in _FALSEY_ENV
    return not _env_truthy("CI")


def _kitty_negotiated(raw: bytes) -> bool:
    return _KITTY_ENABLE_SEQUENCE.search(raw) is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\x1b[>1u", True),
        (b"prefix\x1b[=3;1usuffix", True),
        (b"\x1b[>0u", False),
        (b"\x1b[>0;1;0c useful text", False),
        (b"\x1b[>1c then ordinary u", False),
    ],
)
def test_kitty_negotiation_requires_complete_enabling_sequence(
    raw: bytes, expected: bool
) -> None:
    assert _kitty_negotiated(raw) is expected


def _selected_real_provider() -> str | None:
    selected = os.environ.get("TAUT_SUMMON_HOST_PTY_PROVIDER")
    return selected.strip() if selected and selected.strip() else None


def test_real_provider_selection_never_guesses_from_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TAUT_SUMMON_HOST_PTY_PROVIDER", raising=False)
    monkeypatch.setenv("PATH", f"/fake/bin{os.pathsep}{os.environ.get('PATH', '')}")
    assert _selected_real_provider() is None

    monkeypatch.setenv("TAUT_SUMMON_HOST_PTY_PROVIDER", "codex")
    assert _selected_real_provider() == "codex"


@pytest.mark.skipif(os.name == "nt", reason="POSIX host PTY contract")
@pytest.mark.parametrize(
    ("keyboard_output", "detach_chord"),
    [
        pytest.param("", b"\x1c\x1c", id="legacy"),
        pytest.param(
            "\x1b[>1u",
            b"\x1b[92::92;5u\x1b[92::92;5u",
            id="kitty-alternate-key",
        ),
    ],
)
def test_scripted_root_cli_detach_control_plane_and_fresh_attach(
    tmp_path: Path, keyboard_output: str, detach_chord: bytes
) -> None:
    db = tmp_path / "host-terminal.sqlite3"
    received = tmp_path / "host-terminal-received.jsonl"
    scenario = tmp_path / "host-terminal-scenario.json"
    prompt = tmp_path / "host-terminal-orientation.txt"
    prompt.write_text("host-orientation-proof", encoding="utf-8")
    scenario_payload: dict[str, Any] = {
        "responses": [
            [],
            [],
            [{"exec_taut": {"args": ["say", "general", "host-mouth-reply"]}}],
        ]
    }
    if keyboard_output:
        scenario_payload["on_start"] = [{"terminal_text": keyboard_output}]
    scenario.write_text(
        json.dumps(scenario_payload),
        encoding="utf-8",
    )
    env = _base_env()
    env.update(
        {
            "TAUT_SUMMON_SCENARIO": str(scenario),
            "TAUT_SUMMON_RECEIVED_LOG": str(received),
            "TAUT_SUMMON_CONTROL_INTERVAL": "0.1",
        }
    )
    initialized = _run("taut", "--db", str(db), "init", cwd=tmp_path, env=env)
    assert initialized.returncode == 0, initialized.stderr
    joined = _run(
        "taut",
        "--db",
        str(db),
        "--as",
        "host-human",
        "join",
        "general",
        cwd=tmp_path,
        env=env,
    )
    assert joined.returncode == 0, joined.stderr

    with PosixHostShell.open(cwd=tmp_path, env=env) as shell:
        shell.wait_for_prompt()
        shell_cooked = shell.termios_snapshot()
        first = shell.mark()
        shell.run(
            _root_command(
                db,
                "summon",
                "host-bot",
                "general",
                "--provider",
                "scripted",
                "--system-prompt-file",
                str(prompt),
            )
        )
        shell.wait_for_text("Press Enter to continue", after=first)
        attach_cooked = shell.termios_snapshot()
        shell.write(b"\r")
        shell.wait_for_text("scripted> ", after=first)
        attached_mode = shell.termios_snapshot()
        assert attached_mode != attach_cooked
        assert not attached_mode[3] & termios.ICANON
        assert not attached_mode[3] & termios.ISIG
        shell.write(b"setup-human\r")
        _wait_until(
            lambda: any(
                entry.get("event") == "message" and entry.get("text") == "setup-human"
                for entry in _entries(received)
            ),
            message="human provider input",
        )
        shell.write(detach_chord)
        _wait_for_cooked(
            shell, attach_cooked, message="termios restoration after detach"
        )
        _wait_for_status(db, "host-bot", cwd=tmp_path, env=env)
        _wait_until(
            lambda: any(
                entry.get("event") == "message"
                and "host-orientation-proof" in str(entry.get("text"))
                for entry in _entries(received)
            ),
            message="post-detach orientation in provider received log",
        )
        assert _configured_termios(shell.termios_snapshot()) == _configured_termios(
            attach_cooked
        )
        assert shell.poll() is None

        said = _run(
            "taut",
            "--db",
            str(db),
            "--as",
            "host-human",
            "say",
            "general",
            "host-chat-probe",
            cwd=tmp_path,
            env=env,
        )
        assert said.returncode == 0, said.stderr
        _wait_until(
            lambda: any(
                entry.get("event") == "message"
                and "host-chat-probe" in str(entry.get("text"))
                for entry in _entries(received)
            ),
            message="chat delivery through provider ears",
        )
        _wait_until(
            lambda: (
                (
                    logged := _run(
                        "taut", "--db", str(db), "log", "general", cwd=tmp_path, env=env
                    )
                ).returncode
                == 0
                and "host-mouth-reply" in logged.stdout
            ),
            message="provider mouth reply in out-of-band log",
        )

        before_dismiss = shell.mark()
        dismissed = _run(
            "taut", "--db", str(db), "dismiss", "host-bot", cwd=tmp_path, env=env
        )
        assert dismissed.returncode == 0, dismissed.stderr
        shell.wait_for_prompt(after=before_dismiss)
        assert shell.termios_snapshot() == shell_cooked
        stty_mark = shell.mark()
        shell.run("stty -a; printf '\\nSTTY-DONE\\n'")
        stty = shell.wait_for_text("STTY-DONE", after=stty_mark)
        shell.wait_for_prompt(after=stty_mark)
        stty_tokens = set(stty.replace(";", " ").split())
        assert "icanon" in stty_tokens
        assert "-icanon" not in stty_tokens
        assert "echo" in stty_tokens
        assert "-echo" not in stty_tokens

        attach_mark = shell.mark()
        shell.run(_root_command(db, "summon", "--attach", "host-bot"))
        shell.wait_for_text("Press Enter to continue", after=attach_mark)
        fresh_attach_cooked = shell.termios_snapshot()
        shell.write(b"\r")
        shell.wait_for_text("scripted> ", after=attach_mark)
        shell.write(detach_chord)
        _wait_for_cooked(
            shell,
            fresh_attach_cooked,
            message="termios restoration after fresh-attach detach",
        )
        _wait_for_status(db, "host-bot", cwd=tmp_path, env=env)
        starts = [
            entry for entry in _entries(received) if entry.get("event") == "start"
        ]
        assert len(starts) >= 2
        final_provider_pid = int(starts[-1]["pid"])

        final_mark = shell.mark()
        dismissed = _run(
            "taut", "--db", str(db), "dismiss", "host-bot", cwd=tmp_path, env=env
        )
        assert dismissed.returncode == 0, dismissed.stderr
        shell.wait_for_prompt(after=final_mark)
        _wait_until(
            lambda: capture_process(final_provider_pid) is None,
            message="final scripted provider retirement",
        )
        assert shell.termios_snapshot() == shell_cooked


@pytest.mark.skipif(os.name == "nt", reason="POSIX host PTY contract")
def test_env_selected_real_provider_through_root_cli_host_terminal(
    tmp_path: Path,
) -> None:
    if not _live_lane_enabled():
        pytest.skip(
            "real host-PTY lane disabled by CI/default or TAUT_SUMMON_LIVE_HARNESS=0"
        )
    provider = _selected_real_provider()
    if not provider:
        pytest.skip("set TAUT_SUMMON_HOST_PTY_PROVIDER to select the real provider")
    if shutil.which(provider) is None:
        if _env_truthy("TAUT_SUMMON_LIVE_HARNESS_STRICT"):
            pytest.fail(f"selected real host-PTY provider is absent: {provider}")
        pytest.skip(f"selected real host-PTY provider is absent: {provider}")
    ready_text = os.environ.get(
        "TAUT_SUMMON_HOST_PTY_READY_TEXT"
    ) or _REAL_PROVIDER_READY_TEXT.get(provider)
    if not ready_text:
        pytest.fail(
            "TAUT_SUMMON_HOST_PTY_READY_TEXT is required for an unrecognized provider"
        )

    db = tmp_path / "real-host-terminal.sqlite3"
    prompt = tmp_path / "real-host-terminal-orientation.txt"
    prompt.write_text(
        "Use your Taut mouth for replies. Stay ready for messages.", encoding="utf-8"
    )
    env = _base_env()
    env["TAUT_SUMMON_CONTROL_INTERVAL"] = "0.1"
    initialized = _run("taut", "--db", str(db), "init", cwd=tmp_path, env=env)
    assert initialized.returncode == 0, initialized.stderr
    joined = _run(
        "taut",
        "--db",
        str(db),
        "--as",
        "host-human",
        "join",
        "general",
        cwd=tmp_path,
        env=env,
    )
    assert joined.returncode == 0, joined.stderr

    with PosixHostShell.open(cwd=tmp_path, env=env) as shell:
        shell.wait_for_prompt()
        shell_cooked = shell.termios_snapshot()
        first = shell.mark()
        shell.run(
            _root_command(
                db,
                "summon",
                "host-real",
                "general",
                "--provider",
                provider,
                "--system-prompt-file",
                str(prompt),
            )
        )
        shell.wait_for_text("Press Enter to continue", after=first)
        attach_cooked = shell.termios_snapshot()
        attach_output_mark = shell.mark()
        shell.write(b"\r")
        shell.wait_for_text(ready_text, after=attach_output_mark, timeout=60.0)
        if setup_input := os.environ.get("TAUT_SUMMON_HOST_PTY_SETUP_INPUT"):
            shell.write(setup_input.encode("utf-8") + b"\r")
        shell.write(b"\x1c\x1c")
        _wait_for_cooked(
            shell, attach_cooked, message="real-provider termios restoration"
        )
        _wait_for_status(db, "host-real", cwd=tmp_path, env=env)

        instruction = (
            "Reply now through your Taut mouth by running exactly: "
            "taut say general host-real-mouth-reply"
        )
        said = _run(
            "taut",
            "--db",
            str(db),
            "--as",
            "host-human",
            "say",
            "general",
            instruction,
            cwd=tmp_path,
            env=env,
        )
        assert said.returncode == 0, said.stderr
        _wait_until(
            lambda: (
                (
                    logged := _run(
                        "taut", "--db", str(db), "log", "general", cwd=tmp_path, env=env
                    )
                ).returncode
                == 0
                and "host-real-mouth-reply" in logged.stdout
            ),
            message="real provider mouth reply",
            timeout=float(os.environ.get("TAUT_SUMMON_LIVE_HARNESS_TIMEOUT", "90")),
        )

        before_dismiss = shell.mark()
        dismissed = _run(
            "taut", "--db", str(db), "dismiss", "host-real", cwd=tmp_path, env=env
        )
        assert dismissed.returncode == 0, dismissed.stderr
        shell.wait_for_prompt(after=before_dismiss)
        assert shell.termios_snapshot() == shell_cooked

        reattach = shell.mark()
        shell.run(_root_command(db, "summon", "--attach", "host-real"))
        shell.wait_for_text("Press Enter to continue", after=reattach)
        reattach_cooked = shell.termios_snapshot()
        provider_output_mark = shell.mark()
        shell.write(b"\r")
        shell.wait_for_text(ready_text, after=provider_output_mark, timeout=60.0)
        shell.read_available()
        provider_output = shell.transcript[provider_output_mark:]
        chord = (
            b"\x1b[92::92;5u\x1b[92::92;5u"
            if _kitty_negotiated(provider_output)
            else b"\x1c\x1c"
        )
        shell.write(chord)
        _wait_for_cooked(
            shell, reattach_cooked, message="real-provider reattach restoration"
        )
        final_mark = shell.mark()
        dismissed = _run(
            "taut", "--db", str(db), "dismiss", "host-real", cwd=tmp_path, env=env
        )
        assert dismissed.returncode == 0, dismissed.stderr
        shell.wait_for_prompt(after=final_mark)
        assert shell.termios_snapshot() == shell_cooked
