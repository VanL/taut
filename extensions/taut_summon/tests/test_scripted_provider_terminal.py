"""Interactive terminal contract for the packaged scripted provider."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from taut_summon._adapter import ExitEvent, get_adapter
from taut_summon.scripted_provider import _TerminalInputParser


def _entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _wait_for_message(path: Path, *, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = [entry for entry in _entries(path) if entry["event"] == "message"]
        if messages:
            return messages[-1]
        time.sleep(0.01)
    raise AssertionError(f"no scripted-provider message: {_entries(path)!r}")


def test_terminal_parser_accepts_split_bracketed_and_plain_turns() -> None:
    parser = _TerminalInputParser()

    turns, interrupts = parser.feed(b"\x1b[20")
    assert (turns, interrupts) == ([], 0)
    turns, interrupts = parser.feed(b"0~one\ntwo\x1b[20")
    assert (turns, interrupts) == ([], 0)
    turns, interrupts = parser.feed(b"1~\rplain\r")

    assert turns == ["one\ntwo", "plain"]
    assert interrupts == 0


def test_scripted_provider_is_a_real_bracketed_paste_pty_child(
    tmp_path: Path,
) -> None:
    scenario = tmp_path / "scenario.json"
    received = tmp_path / "received.jsonl"
    scenario.write_text(json.dumps({"default_response": []}), encoding="utf-8")
    adapter = get_adapter("scripted")
    handle = adapter.spawn(
        system_prompt="delivered as the first interactive turn",
        env={
            "TAUT_SUMMON_SCENARIO": str(scenario),
            "TAUT_SUMMON_RECEIVED_LOG": str(received),
        },
    )
    observed: list[object] = []
    pump = threading.Thread(
        target=lambda: observed.extend(handle.events()), daemon=True
    )
    pump.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not handle.input_prompt_observed:
            time.sleep(0.01)
        assert handle.input_prompt_observed is True

        handle.inject("one\ntwo")
        assert _wait_for_message(received)["text"] == "one\ntwo"
    finally:
        handle.close()
        pump.join(timeout=5.0)

    assert not pump.is_alive()
    assert any(isinstance(event, ExitEvent) for event in observed)


def test_scripted_provider_accepts_plain_terminal_input_and_etx_cleanup(
    tmp_path: Path,
) -> None:
    scenario = tmp_path / "scenario.json"
    received = tmp_path / "received.jsonl"
    scenario.write_text(
        json.dumps({"sigint_cleanup_seconds": 0.05, "default_response": []}),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["TAUT_SUMMON_SCENARIO"] = str(scenario)
    env["TAUT_SUMMON_RECEIVED_LOG"] = str(received)
    provider = subprocess.Popen(
        [sys.executable, "-m", "taut_summon.scripted_provider"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert provider.stdin is not None
    assert provider.stdout is not None
    assert provider.stdout.read(len(b"\x1b[?2004h")) == b"\x1b[?2004h"

    provider.stdin.write(b"plain turn\r")
    provider.stdin.flush()
    assert _wait_for_message(received)["text"] == "plain turn"
    provider.stdin.write(b"\x03")
    provider.stdin.flush()

    assert provider.wait(timeout=3.0) == 0
    assert any(entry["event"] == "signal" for entry in _entries(received))
