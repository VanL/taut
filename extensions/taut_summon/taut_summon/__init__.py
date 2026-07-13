"""Public, lazily loaded Summon extension surface."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
    from taut_summon.controller import SummonController
    from taut_summon.interaction import (
        ShellSummonInteraction,
        SummonInteraction,
        TerminalAvailability,
        TerminalIntent,
        TerminalLease,
    )
    from taut_summon.models import (
        DriverUnresponsive,
        NothingSummoned,
        StopResult,
        SummonedMember,
        SummonOperationError,
        SummonRequest,
        SummonStatus,
    )

__all__ = [
    "ActivityEvent",
    "AdapterError",
    "AdapterEvent",
    "AdapterHandle",
    "AssistantTextEvent",
    "DriverUnresponsive",
    "ExitEvent",
    "NothingSummoned",
    "ProviderAdapter",
    "ScriptedAdapter",
    "SessionEvent",
    "ShellSummonInteraction",
    "StopResult",
    "SummonController",
    "SummonInteraction",
    "SummonOperationError",
    "SummonRequest",
    "SummonStatus",
    "SummonedMember",
    "TerminalAvailability",
    "TerminalIntent",
    "TerminalLease",
    "UnknownAdapterError",
    "adapter_names",
    "get_adapter",
]

_LAZY_EXPORTS = {
    "ActivityEvent": ("taut_summon._adapter", "ActivityEvent"),
    "AdapterError": ("taut_summon._adapter", "AdapterError"),
    "AdapterEvent": ("taut_summon._adapter", "AdapterEvent"),
    "AdapterHandle": ("taut_summon._adapter", "AdapterHandle"),
    "AssistantTextEvent": ("taut_summon._adapter", "AssistantTextEvent"),
    "ExitEvent": ("taut_summon._adapter", "ExitEvent"),
    "ProviderAdapter": ("taut_summon._adapter", "ProviderAdapter"),
    "SessionEvent": ("taut_summon._adapter", "SessionEvent"),
    "UnknownAdapterError": ("taut_summon._adapter", "UnknownAdapterError"),
    "adapter_names": ("taut_summon._adapter", "adapter_names"),
    "get_adapter": ("taut_summon._adapter", "get_adapter"),
    "ScriptedAdapter": ("taut_summon._scripted", "ScriptedAdapter"),
    "ShellSummonInteraction": (
        "taut_summon.interaction",
        "ShellSummonInteraction",
    ),
    "SummonController": ("taut_summon.controller", "SummonController"),
    "SummonInteraction": ("taut_summon.interaction", "SummonInteraction"),
    "TerminalAvailability": (
        "taut_summon.interaction",
        "TerminalAvailability",
    ),
    "TerminalIntent": ("taut_summon.interaction", "TerminalIntent"),
    "TerminalLease": ("taut_summon.interaction", "TerminalLease"),
    "DriverUnresponsive": ("taut_summon.models", "DriverUnresponsive"),
    "NothingSummoned": ("taut_summon.models", "NothingSummoned"),
    "StopResult": ("taut_summon.models", "StopResult"),
    "SummonedMember": ("taut_summon.models", "SummonedMember"),
    "SummonOperationError": ("taut_summon.models", "SummonOperationError"),
    "SummonRequest": ("taut_summon.models", "SummonRequest"),
    "SummonStatus": ("taut_summon.models", "SummonStatus"),
}


if not TYPE_CHECKING:

    def __getattr__(name: str) -> Any:
        try:
            module_name, attribute = _LAZY_EXPORTS[name]
        except KeyError as exc:
            raise AttributeError(
                f"module {__name__!r} has no attribute {name!r}"
            ) from exc
        value = getattr(import_module(module_name), attribute)
        globals()[name] = value
        return value

    def __dir__() -> list[str]:
        return sorted(set(globals()) | set(__all__))
