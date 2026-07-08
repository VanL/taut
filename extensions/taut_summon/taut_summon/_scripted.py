"""The ``scripted`` adapter: a real subprocess with a scripted model.

This is the [SUM-7.2] test adapter and the [SUM-12] anti-mocking seam:
``spawn`` starts ``taut_summon/scripted_provider.py`` as a genuine child
process and this module translates its claude-style stream-json output
into the closed ``AdapterEvent`` union over real pipes. Unknown stream
shapes are rejected loudly — the union is closed, and a quiet skip would
hide protocol drift.

The [SUM-7.1] contract mechanics (flushed inject, thread-safe interrupt
and close that unblock a blocked inject, single-consumer event stream
ending in one ``ExitEvent``) live in ``taut_summon._stream``; this module
owns only the spawn command and the strict scripted-shape translation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    AssistantTextEvent,
    SessionEvent,
)
from taut_summon._stream import StreamJsonHandle

_PROVIDER_PATH = Path(__file__).with_name("scripted_provider.py")


class ScriptedAdapter:
    """Spawn the scripted provider program as a real harness child."""

    name: str = "scripted"
    supports_terminal_mode: bool = True
    supports_attach: bool = False
    orientation_via_inject: bool = False

    def spawn(
        self,
        *,
        session_id: str | None,
        system_prompt: str,
        env: Mapping[str, str],
    ) -> ScriptedHandle:
        child_env = dict(os.environ)
        child_env.update(env)
        child_env["TAUT_SUMMON_SYSTEM_PROMPT"] = system_prompt
        if session_id is not None:
            child_env["TAUT_SUMMON_SESSION"] = session_id
        try:
            proc = subprocess.Popen(
                [sys.executable, str(_PROVIDER_PATH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                env=child_env,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise AdapterError(f"failed to spawn scripted provider: {exc}") from exc
        return ScriptedHandle(proc, session_id=session_id)


class ScriptedHandle(StreamJsonHandle):
    """Live scripted-provider child; satisfies the ``AdapterHandle`` protocol."""

    def _parse_line(self, line: str) -> AdapterEvent:
        payload = self._decode_object(line)
        kind = payload.get("type")
        if kind == "system" and payload.get("subtype") == "init":
            session_id = payload.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise AdapterError(f"init event without a session id: {line[:200]!r}")
            return SessionEvent(session_id=session_id)
        if kind == "assistant":
            return self._parse_assistant(payload, line)
        raise AdapterError(f"unknown provider event shape: {line[:200]!r}")

    def _parse_assistant(self, payload: dict[str, Any], line: str) -> AdapterEvent:
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            raise AdapterError(
                f"assistant event without a content list: {line[:200]!r}"
            )
        blocks = [block for block in content if isinstance(block, dict)]
        texts = [
            str(block.get("text", ""))
            for block in blocks
            if block.get("type") == "text"
        ]
        if texts:
            return AssistantTextEvent(text="".join(texts))
        tools = [
            str(block.get("name", ""))
            for block in blocks
            if block.get("type") == "tool_use"
        ]
        if tools:
            return ActivityEvent(description=tools[0])
        raise AdapterError(
            f"assistant event with no text or tool_use blocks: {line[:200]!r}"
        )
