"""Summon extension for Taut: host an agent harness as a workspace member.

Spec: docs/specs/04-summon.md ([SUM-1]-[SUM-12]) in the core repository.

The adapter surface is exported here because the ``scripted`` adapter
ships for downstream integrators ([SUM-7.2]): conformance runners spawn
it as a real subprocess speaking real stream shapes ([SUM-12]).
"""

from __future__ import annotations

from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    AdapterHandle,
    AssistantTextEvent,
    ExitEvent,
    ProviderAdapter,
    SessionEvent,
    UnknownAdapterError,
    adapter_names,
    get_adapter,
)
from taut_summon._scripted import ScriptedAdapter

__all__ = [
    "ActivityEvent",
    "AdapterError",
    "AdapterEvent",
    "AdapterHandle",
    "AssistantTextEvent",
    "ExitEvent",
    "ProviderAdapter",
    "ScriptedAdapter",
    "SessionEvent",
    "UnknownAdapterError",
    "adapter_names",
    "get_adapter",
]
