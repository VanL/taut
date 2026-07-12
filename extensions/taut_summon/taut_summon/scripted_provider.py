"""The scripted provider: a real child process with a fake model.

This program is the anti-mocking seam of [SUM-7.2]/[SUM-12]: the
``scripted`` adapter spawns it as a genuine subprocess and speaks
claude-style stream-json over real pipes — real process, real pipes,
real protocol framing; only the model is scripted. It ships in the
package (not tests/) so downstream integrators (weft's conformance run)
can use it.

It is deliberately standalone: stdlib only, no taut or taut_summon
imports, runnable by file path without any ``PYTHONPATH`` arrangement.

Wire protocol (the claude stream-json subset the adapter translates):

- stdin, one JSON object per line:
  ``{"type": "user", "message": {"role": "user", "content":
  [{"type": "text", "text": ...}]}}``
- stdout, one JSON object per line:
  - ``{"type": "system", "subtype": "init", "session_id": SID}``
  - ``{"type": "assistant", "message": {"role": "assistant", "content":
    [{"type": "text", "text": ...}]}, "session_id": SID}``
  - ``{"type": "assistant", "message": {"role": "assistant", "content":
    [{"type": "tool_use", "id": ..., "name": ..., "input": {}}]},
    "session_id": SID}``

Behavior is directed by a JSON scenario file named by the
``TAUT_SUMMON_SCENARIO`` environment variable:

.. code-block:: json

    {
      "session_id": "sess-1",
      "announce_session": true,
      "on_start": [STEP, ...],
      "responses": [[STEP, ...], ...],
      "default_response": [STEP, ...]
    }

``responses[i]`` runs for the i-th injected message; later messages fall
back to ``default_response`` (default: echo). Steps, one key each:

- ``{"assistant_text": TEXT}`` — emit assistant text; ``{text}`` expands
  to the incoming message text.
- ``{"activity": NAME}`` — emit one tool_use event.
- ``{"session": SID}`` — announce a new session id.
- ``{"flood_activity": N}`` — emit N tool_use events back to back.
- ``{"sleep": SECONDS}`` — delay scenario.
- ``{"exit": CODE}`` — crash scenario: exit immediately with CODE.
- ``{"stall": true}`` — stop reading stdin forever (blocked-inject
  scenario; only an interrupt/kill ends the process).
- ``{"close_stdin": true}`` — close the stdin file descriptor (fd 0) then
  block forever: an inject large enough to overflow the pipe buffer fails
  with a broken pipe while the process stays alive (the repeated-failed-
  inject scenario for [SUM-5.4]/[TAUT-8.4]).
- ``{"exec_taut": {"args": [...], "count": N, "interval": S}}`` — run
  ``python -m taut ARGS`` as a real subprocess ``N`` times (default 1),
  using the child's own environment. The environment always carries
  ``TAUT_TOKEN`` and carries ``TAUT_DB`` only for path-addressed backends
  ([SUM-6]); this is the agent speaking through its mouth for real — the
  end-to-end mouth-credential proof, and the flood source for the [SUM-10]
  rate-backstop test.
- ``{"raw_line": LINE}`` — emit LINE verbatim (malformed/unknown-shape
  scenarios).

The provider resumes the session id given via ``TAUT_SUMMON_SESSION``
(set by the adapter from ``spawn(session_id=...)``) in preference to the
scenario's ``session_id``.

When ``TAUT_SUMMON_RECEIVED_LOG`` names a file, the provider appends one
JSON line per observable step so driver tests can assert what actually
reached the harness process ([SUM-5.4]'s process-boundary ledger, made
visible):

- on start: ``{"event": "start", "pid": ..., "session": <resumed session
  id or null>, "env_token": $TAUT_TOKEN, "env_db": $TAUT_DB,
  "env_system_prompt": $TAUT_SUMMON_SYSTEM_PROMPT}`` — the session field
  proves resume offers ([SUM-7.3]), the token/db fields prove the conditional
  mouth selector contract ([SUM-6]), and the system-prompt field proves the
  persona / ``--system-prompt-file`` override reached the provider
  ([SUM-10]).
- per injected message: ``{"event": "message", "pid": ..., "text": ...}``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def _record(payload: dict[str, Any]) -> None:
    path = os.environ.get("TAUT_SUMMON_RECEIVED_LOG")
    if not path:
        return
    payload = {**payload, "pid": os.getpid()}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
        handle.flush()


def _emit_raw(line: str) -> None:
    print(line, flush=True)


def _emit_init(session_id: str) -> None:
    _emit({"type": "system", "subtype": "init", "session_id": session_id})


def _emit_assistant_text(text: str, session_id: str) -> None:
    _emit(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            },
            "session_id": session_id,
        }
    )


def _emit_activity(name: str, index: int, session_id: str) -> None:
    _emit(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"tool_{index}",
                        "name": name,
                        "input": {},
                    }
                ],
            },
            "session_id": session_id,
        }
    )


def _load_scenario() -> dict[str, Any]:
    path = os.environ.get("TAUT_SUMMON_SCENARIO")
    if not path:
        return {}
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("scenario file must hold a JSON object")
    return loaded


def _extract_text(event: dict[str, Any]) -> str:
    if event.get("type") != "user":
        raise ValueError(f"expected a user event, got {event.get('type')!r}")
    message = event.get("message")
    if not isinstance(message, dict):
        raise ValueError("user event carries no message object")
    content = message.get("content")
    if not isinstance(content, list):
        raise ValueError("user message carries no content list")
    parts = [
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(parts)


class _State:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.activity_index = 0


def _run_steps(
    steps: list[dict[str, Any]],
    state: _State,
    message_text: str,
) -> None:
    for step in steps:
        if "assistant_text" in step:
            text = str(step["assistant_text"]).replace("{text}", message_text)
            _emit_assistant_text(text, state.session_id)
        elif "activity" in step:
            state.activity_index += 1
            _emit_activity(
                str(step["activity"]), state.activity_index, state.session_id
            )
        elif "session" in step:
            state.session_id = str(step["session"])
            _emit_init(state.session_id)
        elif "flood_activity" in step:
            for _ in range(int(step["flood_activity"])):
                state.activity_index += 1
                _emit_activity("flood", state.activity_index, state.session_id)
        elif "sleep" in step:
            time.sleep(float(step["sleep"]))
        elif "exit" in step:
            sys.exit(int(step["exit"]))
        elif "stall" in step:
            while True:
                time.sleep(3600)
        elif "close_stdin" in step:
            # Close the underlying fd (fd 0) so the pipe's read end is truly
            # gone; a large enough inject then fails with EPIPE. Closing the
            # Python wrapper alone does not close the fd on CPython.
            try:
                os.close(0)
            except OSError:
                pass
            while True:
                time.sleep(3600)
        elif "exec_taut" in step:
            _exec_taut(step["exec_taut"])
        elif "raw_line" in step:
            _emit_raw(str(step["raw_line"]))
        else:
            raise ValueError(f"unknown scenario step: {step!r}")


def _exec_taut(spec: Any) -> None:
    """Run ``python -m taut ARGS`` as a real child, using our own env.

    The environment carries ``TAUT_TOKEN`` and, for a path backend,
    ``TAUT_DB`` ([SUM-6]), so this
    is the summoned agent speaking through its mouth for real. Best-effort:
    a non-zero taut exit is logged to stderr but does not stop the scenario.
    """

    if isinstance(spec, list):
        spec = {"args": spec}
    args = [str(a) for a in spec.get("args", [])]
    count = int(spec.get("count", 1))
    interval = float(spec.get("interval", 0.0))
    for i in range(count):
        result = subprocess.run(
            [sys.executable, "-m", "taut", *args],
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            print(
                f"scripted provider: taut exited {result.returncode}",
                file=sys.stderr,
                flush=True,
            )
        if interval and i + 1 < count:
            time.sleep(interval)


def main() -> int:
    try:
        scenario = _load_scenario()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"scripted provider: bad scenario: {exc}", file=sys.stderr)
        return 2

    session_id = (
        os.environ.get("TAUT_SUMMON_SESSION")
        or str(scenario.get("session_id") or "")
        or "scripted-session"
    )
    state = _State(session_id)
    _record(
        {
            "event": "start",
            "session": os.environ.get("TAUT_SUMMON_SESSION"),
            "env_token": os.environ.get("TAUT_TOKEN"),
            "env_db": os.environ.get("TAUT_DB"),
            "env_system_prompt": os.environ.get("TAUT_SUMMON_SYSTEM_PROMPT"),
        }
    )
    if scenario.get("announce_session", True):
        _emit_init(state.session_id)

    responses = scenario.get("responses", [])
    default_response = scenario.get(
        "default_response", [{"assistant_text": "echo: {text}"}]
    )

    try:
        _run_steps(list(scenario.get("on_start", [])), state, "")

        index = 0
        while True:
            line = sys.stdin.readline()
            if not line:
                return 0
            stripped = line.strip()
            if not stripped:
                continue
            event = json.loads(stripped)
            if not isinstance(event, dict):
                raise ValueError("stdin event must be a JSON object")
            text = _extract_text(event)
            _record({"event": "message", "text": text})
            steps = responses[index] if index < len(responses) else default_response
            index += 1
            _run_steps(list(steps), state, text)
    except KeyboardInterrupt:
        return 130
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"scripted provider: protocol error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
