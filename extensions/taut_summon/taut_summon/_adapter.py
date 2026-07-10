"""Provider adapter interface: the [SUM-7.1] contract and the registry.

An adapter owns exactly four things — spawn, inject, events, interrupt —
and translates its provider's native streaming envelope into the closed
``AdapterEvent`` union below. There is no summon-defined wire protocol:
adapters translate, they do not define ([SUM-7.1]).

Contract requirements on every adapter (enforced by the conformance
tests, exercised today through the ``scripted`` adapter):

- ``inject()`` returns only after the event is written *and flushed* to
  the child's stdin, and surfaces failures synchronously ([SUM-5.4]'s
  at-least-once delivery to the harness process boundary depends on it).
- ``interrupt()`` and ``close()`` are thread-safe and unblock any
  in-flight ``inject()`` — [SUM-9]'s STOP path must always be able to
  stop a stalled harness.
- ``events()`` must be drained continuously by its (single) consumer; an
  undrained stream is a child-stdout deadlock waiting to happen. The
  stream ends with exactly one ``ExitEvent``.
- ``env`` passed to ``spawn`` is merged over the parent environment —
  it carries additions such as ``TAUT_TOKEN``/``TAUT_DB`` ([SUM-6]),
  not a replacement environment.

Spec references:
- docs/specs/04-summon.md [SUM-7.1], [SUM-7.2]
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Protocol


class AdapterError(Exception):
    """An adapter operation failed (spawn, inject, or stream translation)."""


class UnknownAdapterError(AdapterError):
    """No adapter is registered under the requested provider name."""


@dataclass(frozen=True, slots=True)
class AssistantTextEvent:
    """Assistant-authored text (posted to chat only in terminal mode)."""

    text: str


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    """Tool use or comparable liveness signal — feeds presence, never chat."""

    description: str


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """The provider announced or changed its session id (resume handle)."""

    session_id: str


@dataclass(frozen=True, slots=True)
class ExitEvent:
    """The harness child exited; the event stream ends after this."""

    returncode: int


AdapterEvent = AssistantTextEvent | ActivityEvent | SessionEvent | ExitEvent


class AdapterHandle(Protocol):
    """A live harness child owned by an adapter."""

    @property
    def session_id(self) -> str | None:
        """Current provider session id, updated as ``SessionEvent``s arrive."""
        ...

    @property
    def pid(self) -> int:
        """Harness child pid — the [SUM-4] re-anchor evidence.

        The summoned member's identity anchor is ultimately the harness
        child process; the driver builds its rejoin capture from this pid,
        so exposing it is part of the handle surface.
        """
        ...

    def inject(self, text: str) -> None:
        """Write one user-role event; return only after a flushed write."""
        ...

    def events(self) -> Iterator[AdapterEvent]:
        """Typed output stream; single consumer, ends with ``ExitEvent``."""
        ...

    def interrupt(self) -> None:
        """Harness-graceful stop; unblocks an in-flight ``inject()``."""
        ...

    def close(self) -> None:
        """Stop (bounded escalation), reap the child, release the pipes."""
        ...

    def status_fields(self) -> dict[str, str]:
        """Adapter-specific STATUS fields; empty for structured adapters."""
        ...

    def wait_until_quiet(self) -> None:
        """Wait for terminal startup output to settle, or return immediately."""
        ...

    def mark_awaiting_onboarding(self) -> None:
        """Expose that an attached terminal is waiting on provider onboarding."""
        ...

    def attach(
        self,
        *,
        wake: threading.Event,
        shutdown: threading.Event,
        input_fd: int = 0,
        output_fd: int = 1,
        detach_chord: bytes = b"\x1c\x1c",
    ) -> str:
        """Bridge a human terminal when supported, else raise AdapterError."""
        ...


class ProviderAdapter(Protocol):
    """One provider harness family (claude, scripted, codex...)."""

    name: str
    supports_terminal_mode: bool
    supports_attach: bool
    orientation_via_inject: bool
    emits_session_events: bool

    def spawn(
        self,
        *,
        session_id: str | None,
        system_prompt: str,
        env: Mapping[str, str],
    ) -> AdapterHandle:
        """Start the harness child, resuming ``session_id`` when given."""
        ...


def _scripted_factory() -> ProviderAdapter:
    from taut_summon._scripted import ScriptedAdapter

    return ScriptedAdapter()


def _claude_factory() -> ProviderAdapter:
    from taut_summon._claude import ClaudeAdapter

    return ClaudeAdapter()


def _pty_int_env(name: str, default: str) -> int:
    raw = os.environ.get(name, default)
    try:
        return int(raw)
    except ValueError as exc:
        raise AdapterError(f"{name} must be an integer, got {raw!r}") from exc


def _pty_float_env(name: str, default: str) -> float:
    raw = os.environ.get(name, default)
    try:
        return float(raw)
    except ValueError as exc:
        raise AdapterError(f"{name} must be a number, got {raw!r}") from exc


def _pty_factory() -> ProviderAdapter:
    from taut_summon._pty import PtyAdapter, PtySpec

    raw_argv = os.environ.get("TAUT_SUMMON_PTY_ARGV")
    if raw_argv is not None:
        try:
            parsed = json.loads(raw_argv)
        except json.JSONDecodeError as exc:
            raise AdapterError(
                f"TAUT_SUMMON_PTY_ARGV must be valid JSON: {exc}"
            ) from exc
        if not isinstance(parsed, list) or not all(
            isinstance(item, str) and item for item in parsed
        ):
            raise AdapterError("TAUT_SUMMON_PTY_ARGV must be a JSON string list")
        spec = PtySpec(
            name="pty",
            argv=tuple(parsed),
            rows=_pty_int_env("TAUT_SUMMON_PTY_ROWS", "24"),
            cols=_pty_int_env("TAUT_SUMMON_PTY_COLS", "80"),
            stall_s=_pty_float_env("TAUT_SUMMON_PTY_STALL_S", "10.0"),
            quiet_ms=_pty_int_env("TAUT_SUMMON_PTY_QUIET_MS", "500"),
            max_settle_s=_pty_float_env("TAUT_SUMMON_PTY_MAX_SETTLE_S", "10.0"),
        )
        return PtyAdapter(spec)
    return PtyAdapter()


def _pty_harness_factory(name: str, binary: str) -> Callable[[], ProviderAdapter]:
    def _factory() -> ProviderAdapter:
        from taut_summon._pty import PtyAdapter, PtySpec

        return PtyAdapter(PtySpec(name=name, argv=(binary,)))

    return _factory


_FACTORIES: dict[str, Callable[[], ProviderAdapter]] = {
    "claude": _pty_harness_factory("claude", "claude"),
    "claude-stream": _claude_factory,
    "codex": _pty_harness_factory("codex", "codex"),
    "coder": _pty_harness_factory("coder", "coder"),
    "grok": _pty_harness_factory("grok", "grok"),
    "kimi": _pty_harness_factory("kimi", "kimi"),
    "opencode": _pty_harness_factory("opencode", "opencode"),
    "pi": _pty_harness_factory("pi", "pi"),
    "pty": _pty_factory,
    "qwen": _pty_harness_factory("qwen", "qwen"),
    "scripted": _scripted_factory,
}


def adapter_names() -> tuple[str, ...]:
    """Return the registered provider names, sorted."""

    return tuple(sorted(_FACTORIES))


def get_adapter(name: str) -> ProviderAdapter:
    """Return the adapter registered under ``name``.

    Raises ``UnknownAdapterError`` naming the known adapters ([SUM-3]
    resolution step 4).
    """

    factory = _FACTORIES.get(name)
    if factory is None:
        known = ", ".join(adapter_names())
        raise UnknownAdapterError(
            f"no adapter named '{name}' (known adapters: {known})"
        )
    return factory()
