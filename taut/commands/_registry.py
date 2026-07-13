"""Deterministic static and installed command discovery.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.6]
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import metadata
from typing import Any

from taut.commands._builtins import BUILTIN_SPECS
from taut.commands._imports import validate_import_target
from taut.commands._protocol import CommandSpec, GlobalOption

_COMMAND_NAME_RE = re.compile(r"[a-z][a-z0-9-]*\Z")

_RESERVED_FIRST_PARTY_SPECS = (
    CommandSpec(
        command_api_version=1,
        name="summon",
        summary="Delegate agent-harness startup to the taut-summon extension.",
        post_verb_globals=frozenset({GlobalOption.DB}),
        implementation="taut.commands._summon_compat:create_summon_command",
    ),
    CommandSpec(
        command_api_version=1,
        name="dismiss",
        summary="Delegate agent-harness shutdown to the taut-summon extension.",
        post_verb_globals=frozenset({GlobalOption.DB}),
        implementation="taut.commands._summon_compat:create_dismiss_command",
    ),
)
_CORE_BUILTIN_NAMES = frozenset(spec.name for spec in BUILTIN_SPECS)
_RESERVED_FIRST_PARTY_OWNER = "taut-summon"


@dataclass(frozen=True, slots=True)
class RegisteredCommand:
    """One selected manifest and its diagnostic provenance."""

    name: str
    spec: CommandSpec | None
    distribution_name: str
    distribution_version: str
    entry_point: Any | None = None
    builtin: bool = False
    verbatim_tail: bool = False
    error: str | None = None


class CommandRegistry:
    """Immutable command view built from core manifests and installed metadata."""

    def __init__(self, *, entry_points: Iterable[Any] | None = None) -> None:
        discovered = (
            tuple(metadata.entry_points(group="taut.commands"))
            if entry_points is None
            else tuple(entry_points)
        )
        commands = [
            RegisteredCommand(
                name=spec.name,
                spec=spec,
                distribution_name="taut",
                distribution_version="built-in",
                builtin=True,
            )
            for spec in BUILTIN_SPECS
        ]
        compatibility_commands = tuple(
            RegisteredCommand(
                name=spec.name,
                spec=spec,
                distribution_name="taut-summon compatibility",
                distribution_version="built-in bridge",
                verbatim_tail=True,
            )
            for spec in _RESERVED_FIRST_PARTY_SPECS
        )
        external: list[RegisteredCommand] = []
        for entry_point in discovered:
            distribution_name = "unknown distribution"
            distribution_version = "unknown version"
            try:
                distribution = getattr(entry_point, "dist", None)
                if distribution is not None:
                    metadata_name = distribution.metadata.get("Name")
                    distribution_name = metadata_name or distribution_name
                    distribution_version = str(distribution.version)
                loaded = entry_point.load()
                _validate_manifest(entry_point.name, loaded)
            except BaseException as exc:
                if isinstance(exc, KeyboardInterrupt):
                    raise
                reason = _exception_message(exc)
                external.append(
                    RegisteredCommand(
                        name=entry_point.name,
                        spec=None,
                        distribution_name=distribution_name,
                        distribution_version=distribution_version,
                        entry_point=entry_point,
                        error=_manifest_error(
                            entry_point,
                            distribution_name,
                            distribution_version,
                            reason,
                        ),
                    )
                )
                continue
            assert isinstance(loaded, CommandSpec)
            external.append(
                RegisteredCommand(
                    name=loaded.name,
                    spec=loaded,
                    distribution_name=distribution_name,
                    distribution_version=distribution_version,
                    entry_point=entry_point,
                )
            )
        external.sort(
            key=lambda command: (
                command.name,
                _normalize_distribution_name(command.distribution_name),
                command.distribution_name,
                command.distribution_version,
                command.entry_point.value if command.entry_point is not None else "",
            )
        )
        builtin_names = {spec.name for spec in BUILTIN_SPECS}
        reserved_names = {command.name for command in compatibility_commands}
        diagnostics: list[str] = []
        grouped: dict[str, list[RegisteredCommand]] = {}
        reserved_claims: dict[str, list[RegisteredCommand]] = {
            name: [] for name in reserved_names
        }
        for command in external:
            if _COMMAND_NAME_RE.fullmatch(command.name) is None:
                if command.error is not None:
                    diagnostics.append(command.error)
                continue
            if command.name in builtin_names:
                diagnostics.append(
                    f"installed command {command.name!r} from "
                    f"{command.distribution_name} {command.distribution_version} "
                    "cannot override the core built-in"
                )
                continue
            if command.name in reserved_names:
                reserved_claims[command.name].append(command)
                continue
            grouped.setdefault(command.name, []).append(command)
        selected_reserved = _select_reserved_commands(
            compatibility_commands,
            reserved_claims,
            diagnostics,
        )
        selected_external: list[RegisteredCommand] = []
        for name, claimants in grouped.items():
            if len(claimants) == 1:
                selected_external.append(claimants[0])
                continue
            owners = ", ".join(_claimant_label(claimant) for claimant in claimants)
            selected_external.append(
                RegisteredCommand(
                    name=name,
                    spec=None,
                    distribution_name="multiple distributions",
                    distribution_version="",
                    error=(
                        f"command {name!r} is unavailable because multiple "
                        f"distributions claim it: {owners}"
                    ),
                )
            )
        self._commands = (*commands, *selected_reserved, *selected_external)
        self._by_name = {command.name: command for command in self._commands}
        self._diagnostics = tuple(sorted(diagnostics))

    def names(self) -> tuple[str, ...]:
        return tuple(command.name for command in self._commands)

    def commands(self) -> tuple[RegisteredCommand, ...]:
        return self._commands

    def diagnostics(self) -> tuple[str, ...]:
        return self._diagnostics

    def get(self, name: str) -> RegisteredCommand:
        return self._by_name[name]


def is_core_builtin(name: str) -> bool:
    """Return whether *name* is a statically owned core command."""

    return name in _CORE_BUILTIN_NAMES


def _select_reserved_commands(
    compatibility_commands: tuple[RegisteredCommand, ...],
    claims_by_name: dict[str, list[RegisteredCommand]],
    diagnostics: list[str],
) -> tuple[RegisteredCommand, ...]:
    selected: list[RegisteredCommand] = []
    for compatibility in compatibility_commands:
        claimants = claims_by_name[compatibility.name]
        official = [
            claimant
            for claimant in claimants
            if _normalize_distribution_name(claimant.distribution_name)
            == _RESERVED_FIRST_PARTY_OWNER
        ]
        unofficial = [claimant for claimant in claimants if claimant not in official]
        diagnostics.extend(
            f"installed command {claimant.name!r} from {_claimant_label(claimant)} "
            "cannot own the reserved first-party "
            "slot; the official owner is taut-summon"
            for claimant in unofficial
        )
        if not official:
            selected.append(compatibility)
            continue
        if len(official) == 1:
            selected.append(official[0])
            continue
        owners = ", ".join(_claimant_label(claimant) for claimant in official)
        selected.append(
            RegisteredCommand(
                name=compatibility.name,
                spec=None,
                distribution_name=_RESERVED_FIRST_PARTY_OWNER,
                distribution_version="",
                error=(
                    f"command {compatibility.name!r} is unavailable because "
                    "multiple official taut-summon entry points claim it: "
                    f"{owners}"
                ),
            )
        )
    return tuple(selected)


def _validate_manifest(entry_point_name: str, loaded: object) -> None:
    if not isinstance(loaded, CommandSpec):
        raise TypeError("entry point must load a CommandSpec")
    if loaded.name != entry_point_name:
        raise ValueError(
            f"manifest name {loaded.name!r} does not match entry point "
            f"{entry_point_name!r}"
        )
    if not _COMMAND_NAME_RE.fullmatch(loaded.name):
        raise ValueError("command name must match [a-z][a-z0-9-]*")
    if loaded.command_api_version != 1:
        raise ValueError(
            f"unsupported command interface version {loaded.command_api_version}; "
            "core supports version 1"
        )
    if not loaded.summary.strip():
        raise ValueError("command summary must be non-empty")
    if not isinstance(loaded.post_verb_globals, frozenset) or not all(
        isinstance(option, GlobalOption) for option in loaded.post_verb_globals
    ):
        raise TypeError("post_verb_globals must be a frozenset of GlobalOption")
    validate_import_target(loaded.implementation)


def _manifest_error(
    entry_point: Any,
    distribution_name: str,
    distribution_version: str,
    reason: str,
) -> str:
    return (
        f"command {entry_point.name!r} from {distribution_name} "
        f"{distribution_version} ({entry_point.value}) is unavailable: {reason}"
    )


def _claimant_label(claimant: RegisteredCommand) -> str:
    assert claimant.entry_point is not None
    return (
        f"{claimant.distribution_name} {claimant.distribution_version} "
        f"({claimant.entry_point.value})"
    )


def _normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _exception_message(exc: BaseException) -> str:
    if isinstance(exc, SystemExit):
        return f"SystemExit({exc.code!r})"
    return str(exc) or type(exc).__name__
