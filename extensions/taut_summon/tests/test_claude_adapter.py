"""Claude adapter tests: stream translation and one live smoke.

Contract under test: docs/specs/04-summon.md [SUM-7.2] (the ``claude``
adapter speaks Claude Code's headless stream-json envelope) through the
[SUM-7.1] interface. Exact CLI flags are implementation detail verified
against the installed CLI, not contract.

Anti-mocking posture ([SUM-12]): the translation layer is exercised by
feeding **real recorded stream-json lines** (fixture
``fixtures/claude_stream_sample.jsonl``, provenance in its header) through
a real subprocess replayer, and by pointing the claude handle at the real
scripted provider (which speaks the same shapes) over real pipes. Popen is
never mocked. One live smoke test spawns the installed ``claude`` CLI and
is skipped when it is absent (``requires_claude``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AssistantTextEvent,
    ExitEvent,
    SessionEvent,
    adapter_names,
    get_adapter,
)
from taut_summon._claude import ClaudeAdapter, ClaudeHandle
from test_scripted_adapter import EventPump  # resolved by pytest's test-dir path

if TYPE_CHECKING:
    from taut_summon._pty import PtyAdapter
else:
    _pty_module = pytest.importorskip(
        "taut_summon._pty", reason="POSIX PTY tests require fcntl/termios"
    )
    PtyAdapter = _pty_module.PtyAdapter

FIXTURE = Path(__file__).with_name("fixtures") / "claude_stream_sample.jsonl"
SCRIPTED_PROVIDER = (
    Path(__file__).resolve().parents[1] / "taut_summon" / "scripted_provider.py"
)

# A cat-like replayer: a real child process that prints the recorded
# fixture lines (skipping '#' comments) on stdout and exits 0.
_REPLAYER_SRC = """
import sys
from pathlib import Path
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("#") or not line.strip():
        continue
    print(line, flush=True)
"""


def _replayer_handle(fixture: Path) -> ClaudeHandle:
    proc = subprocess.Popen(
        [sys.executable, "-c", _REPLAYER_SRC, str(fixture)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    return ClaudeHandle(proc, session_id=None)


def _raw_line_handle(tmp_path: Path, line: str) -> ClaudeHandle:
    path = tmp_path / "line.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    return _replayer_handle(path)


def test_registry_knows_claude() -> None:
    assert "claude" in adapter_names()
    assert "claude-stream" in adapter_names()
    adapter = get_adapter("claude")
    assert isinstance(adapter, PtyAdapter)
    assert adapter.name == "claude"
    assert adapter.supports_terminal_mode is False
    assert adapter.supports_attach is True
    assert adapter.orientation_via_inject is True
    stream_adapter = get_adapter("claude-stream")
    assert isinstance(stream_adapter, ClaudeAdapter)
    assert stream_adapter.supports_terminal_mode is True


def test_translates_recorded_stream_lines() -> None:
    handle = _replayer_handle(FIXTURE)
    try:
        events = list(handle.events())
    finally:
        handle.close()

    # Recorded sequence: hook_started, init, assistant text, assistant
    # tool_use, rate_limit_event, user tool_result, assistant text,
    # post_turn_summary, result — then the child exits.
    assert isinstance(events[0], ActivityEvent)
    assert events[0].description == "system:hook_started"

    session = events[1]
    assert isinstance(session, SessionEvent)
    assert session.session_id == "4014b88f-c64b-4bdd-ac10-29e012e37cb8"

    assert isinstance(events[2], AssistantTextEvent)
    assert events[2].text == "I'll run the command."

    tool = events[3]
    assert isinstance(tool, ActivityEvent)
    assert tool.description == "Bash"

    assert isinstance(events[4], ActivityEvent)
    assert events[4].description == "rate_limit_event"

    assert isinstance(events[5], ActivityEvent)
    assert events[5].description == "tool_result"

    assert isinstance(events[6], AssistantTextEvent)
    assert events[6].text == "done"

    assert isinstance(events[7], ActivityEvent)
    assert events[7].description == "system:post_turn_summary"

    # The terminal result event re-announces the session id (resume handle).
    result = events[8]
    assert isinstance(result, SessionEvent)
    assert result.session_id == session.session_id

    assert isinstance(events[9], ExitEvent)
    assert events[9].returncode == 0
    assert handle.session_id == session.session_id


def test_translation_echo_round_trip_against_scripted_provider(
    tmp_path: Path,
) -> None:
    # The scripted provider speaks the same claude stream-json shapes
    # ([SUM-7.2]); pointing the claude handle at it proves inject framing
    # and output translation against a real interactive child.
    scenario: dict[str, Any] = {
        "session_id": "sess-claude-shape",
        "default_response": [{"assistant_text": "echo: {text}"}],
    }
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPTED_PROVIDER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env={
            **__import__("os").environ,
            "TAUT_SUMMON_SCENARIO": str(scenario_path),
        },
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    handle = ClaudeHandle(proc, session_id=None)
    try:
        pump = EventPump(handle)
        session = pump.next_of(SessionEvent)
        assert isinstance(session, SessionEvent)
        assert session.session_id == "sess-claude-shape"

        handle.inject("hello")

        reply = pump.next_of(AssistantTextEvent)
        assert isinstance(reply, AssistantTextEvent)
        assert reply.text == "echo: hello"
    finally:
        handle.close()


def test_unknown_event_shape_is_rejected_loudly(tmp_path: Path) -> None:
    handle = _raw_line_handle(tmp_path, '{"type": "mystery"}')
    try:
        with pytest.raises(AdapterError, match="mystery"):
            list(handle.events())
    finally:
        handle.close()


def test_assistant_thinking_block_is_activity(tmp_path: Path) -> None:
    # Shape synthesized from the Anthropic API content-block family (a
    # thinking block was not exercised by the recorded probe); the adapter
    # must treat it as liveness, never speech.
    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "thinking", "thinking": "hmm"}],
            },
            "session_id": "sess-t",
        }
    )
    handle = _raw_line_handle(tmp_path, line)
    try:
        events = list(handle.events())
    finally:
        handle.close()
    assert isinstance(events[0], ActivityEvent)
    assert events[0].description == "thinking"


def test_assistant_event_without_known_blocks_is_loud(tmp_path: Path) -> None:
    line = json.dumps(
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "wat"}]},
        }
    )
    handle = _raw_line_handle(tmp_path, line)
    try:
        with pytest.raises(AdapterError, match="assistant"):
            list(handle.events())
    finally:
        handle.close()


@pytest.mark.requires_claude
@pytest.mark.skipif(
    shutil.which("claude") is None,
    reason="claude CLI is not installed",
)
def test_live_claude_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spawn the real claude CLI: session event, inject, reply, clean close."""

    monkeypatch.chdir(tmp_path)  # keep the harness out of the repo's config
    adapter = get_adapter("claude-stream")
    handle = adapter.spawn(
        session_id=None,
        system_prompt=(
            "You are a terse test probe. Reply to every message with "
            "exactly the single word: pong"
        ),
        env={},
    )
    try:
        pump = EventPump(handle)
        # The CLI emits nothing (not even init) until the first user event
        # arrives, so inject before waiting on the session announcement.
        handle.inject("ping")

        session = pump.next_of(SessionEvent, timeout=120.0)
        assert isinstance(session, SessionEvent)
        assert session.session_id

        reply = pump.next_of(AssistantTextEvent, timeout=120.0)
        assert isinstance(reply, AssistantTextEvent)
        assert reply.text.strip()
    finally:
        handle.close()

    # Resume: a second spawn with the captured session id continues the
    # same provider session ([SUM-7.3]).
    resumed = adapter.spawn(
        session_id=session.session_id,
        system_prompt="You are a terse test probe.",
        env={},
    )
    try:
        pump = EventPump(resumed)
        resumed.inject("reply with exactly: pong")
        again = pump.next_of(SessionEvent, timeout=120.0)
        assert isinstance(again, SessionEvent)
        assert again.session_id == session.session_id
        reply = pump.next_of(AssistantTextEvent, timeout=120.0)
        assert isinstance(reply, AssistantTextEvent)
    finally:
        resumed.close()
