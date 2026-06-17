from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from taut.client import TautClient
from taut.watcher import TautWatcher
from tests.conftest import build_cli_env, run_cli

pytestmark = pytest.mark.shared


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not satisfied before timeout")


def _spawn_cli(cwd: Path, *args: object) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "taut", *map(str, args)],
        cwd=cwd,
        env=build_cli_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_project_client_join_say_read_contract(taut_project: Path) -> None:
    result = TautClient.init()
    van = TautClient(as_handle="van")
    bob = TautClient(as_handle="bob")

    van.join("general")
    bob.join("general")
    message = van.say("general", "shared hello")

    assert result.db
    assert message.thread == "general"
    assert [item.text for item in bob.read("general")][-1:] == ["shared hello"]


def test_project_cli_join_say_log_contract(taut_project: Path) -> None:
    assert run_cli("init", "--json", cwd=taut_project)[0] == 0
    rc, out, err = run_cli(
        "--as",
        "van",
        "join",
        "general",
        "--json",
        cwd=taut_project,
    )
    assert rc == 0, err
    assert json.loads(out.splitlines()[0])["handle"] == "van"

    rc, out, err = run_cli(
        "--as",
        "van",
        "say",
        "general",
        "hello from shared cli",
        "--json",
        cwd=taut_project,
    )
    assert rc == 0, err
    assert json.loads(out)["text"] == "hello from shared cli"

    rc, out, err = run_cli("log", "general", "--json", cwd=taut_project)
    assert rc == 0, err
    assert [json.loads(line)["text"] for line in out.splitlines()] == [
        "van created #general",
        "hello from shared cli",
    ]


def test_project_watcher_receives_cli_write(taut_project: Path) -> None:
    TautClient.init()
    van = TautClient(as_handle="van")
    bob = TautClient(as_handle="bob")
    van.join("general")
    bob.join("general")
    seen: list[str] = []
    watcher = TautWatcher(
        van,
        "van",
        lambda message: seen.append(message.text),
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        rc, out, err = run_cli(
            "--as",
            "bob",
            "say",
            "general",
            "hello from watched cli",
            "--json",
            cwd=taut_project,
        )
        assert rc == 0, err
        written = json.loads(out)

        _wait_until(lambda: "hello from watched cli" in seen)
        assert thread.is_alive()
        assert written["text"] == "hello from watched cli"
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_project_concurrent_writers_persist_all_messages(taut_project: Path) -> None:
    TautClient.init()
    van = TautClient(as_handle="van")
    van.join("general")
    for handle in ("bob", "codex"):
        TautClient(as_handle=handle).join("general")

    target_texts = {"from bob", "from codex"}
    processes = [
        _spawn_cli(taut_project, "--as", "bob", "say", "general", "from bob"),
        _spawn_cli(taut_project, "--as", "codex", "say", "general", "from codex"),
    ]
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=8)
            assert process.returncode == 0, stdout + stderr
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()

    messages = [
        message for message in van.log("general") if message.text in target_texts
    ]

    assert {message.text for message in messages} == target_texts
    assert {message.from_handle for message in messages} == {"bob", "codex"}
    assert [message.ts for message in messages] == sorted(
        message.ts for message in messages
    )
