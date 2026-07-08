"""The ``claude`` adapter: Claude Code headless streaming ([SUM-7.2]).

Exact CLI flags are implementation detail, not contract ([SUM-7.2]).
Verified against the installed CLI (claude 2.1.201, 2026-07-07):

- spawn command::

      claude -p --verbose --input-format stream-json \
          --output-format stream-json --system-prompt TEXT \
          [--resume SESSION_ID]

  ``--verbose`` is required: without it the CLI refuses with "When using
  --print, --output-format=stream-json requires --verbose".
  ``--resume SESSION_ID`` resumes the provider session; the resumed
  session announces the *same* session id in its init event.
  The CLI emits nothing (not even the init event) until the first user
  event arrives on stdin — the session id is therefore only known after
  the first injected turn, which the driver's ledger tolerates
  (``provider_session_id`` is nullable until the pump records it).
- stdin: one JSON object per line, the same user-role event shape the
  scripted provider reads (``StreamJsonHandle.inject``).
- stdout event families and their translation into the closed
  ``AdapterEvent`` union. **Recorded** rows were captured from the real
  CLI (the ``fixtures/claude_stream_sample.jsonl`` probe); **synthetic**
  rows are shapes the adapter accepts but that the recorded probe did not
  exercise — they are built from the Anthropic content-block families and
  translated defensively so a future turn that emits them cannot crash the
  driver. The distinction is honest test provenance, not a behavior
  difference: both are handled identically at runtime.

  ============================  ===========  ==========================
  line                          provenance   translation
  ============================  ===========  ==========================
  ``system``/``init``           recorded     ``SessionEvent``
  ``system``/<other subtype>    recorded     ``ActivityEvent`` (hooks,
                                             post-turn summaries)
  ``assistant`` text blocks     recorded     ``AssistantTextEvent``
  ``assistant`` tool_use        recorded     ``ActivityEvent`` (tool)
  ``user`` (tool_result echo)   recorded     ``ActivityEvent``
  ``result``                    recorded     ``SessionEvent`` (resume
                                             handle at turn end)
  ``rate_limit_event``          recorded     ``ActivityEvent``
  ``assistant`` thinking        synthetic    ``ActivityEvent``
                                             ("thinking")
  ============================  ===========  ==========================

  Anything outside these families raises a loud ``AdapterError`` — the
  union is closed, and silently skipping an unknown shape would hide
  protocol drift ([SUM-7.1]).

Spec references:
- docs/specs/04-summon.md [SUM-7.1], [SUM-7.2], [SUM-7.3]
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from typing import Any

from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    AssistantTextEvent,
    SessionEvent,
)
from taut_summon._stream import StreamJsonHandle

_CLAUDE_BIN = "claude"


class ClaudeAdapter:
    """Spawn a Claude Code headless streaming session as the harness child."""

    name: str = "claude"
    supports_terminal_mode: bool = True
    supports_attach: bool = False
    orientation_via_inject: bool = False

    def spawn(
        self,
        *,
        session_id: str | None,
        system_prompt: str,
        env: Mapping[str, str],
    ) -> ClaudeHandle:
        command = [
            _CLAUDE_BIN,
            "-p",
            "--verbose",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--system-prompt",
            system_prompt,
        ]
        if session_id is not None:
            command.extend(["--resume", session_id])
        child_env = dict(os.environ)
        child_env.update(env)
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                env=child_env,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise AdapterError(
                f"failed to spawn the claude CLI ({exc}); is Claude Code installed?"
            ) from exc
        return ClaudeHandle(proc, session_id=session_id)


class ClaudeHandle(StreamJsonHandle):
    """Live Claude Code child; satisfies the ``AdapterHandle`` protocol."""

    def _parse_line(self, line: str) -> AdapterEvent:
        payload = self._decode_object(line)
        kind = payload.get("type")
        if kind == "system":
            return self._parse_system(payload, line)
        if kind == "assistant":
            return self._parse_assistant(payload, line)
        if kind == "user":
            # Tool results are echoed back on the output stream in
            # stream-json mode: harness activity, never speech.
            return ActivityEvent(description="tool_result")
        if kind == "rate_limit_event":
            return ActivityEvent(description="rate_limit_event")
        if kind == "result":
            session_id = payload.get("session_id")
            if isinstance(session_id, str) and session_id:
                return SessionEvent(session_id=session_id)
            raise AdapterError(f"result event without a session id: {line[:200]!r}")
        raise AdapterError(f"unknown claude event shape: {line[:200]!r}")

    def _parse_system(self, payload: dict[str, Any], line: str) -> AdapterEvent:
        subtype = payload.get("subtype")
        if subtype == "init":
            session_id = payload.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise AdapterError(f"init event without a session id: {line[:200]!r}")
            return SessionEvent(session_id=session_id)
        if isinstance(subtype, str) and subtype:
            # hook_started / hook_response / post_turn_summary / future
            # peers: supervision telemetry from the harness's own
            # machinery, translated as liveness.
            return ActivityEvent(description=f"system:{subtype}")
        raise AdapterError(f"system event without a subtype: {line[:200]!r}")

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
        if any(block.get("type") == "thinking" for block in blocks):
            return ActivityEvent(description="thinking")
        raise AdapterError(
            f"assistant event with no known content blocks: {line[:200]!r}"
        )
