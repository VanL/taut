"""Lazy discovery for official durable-state contributors.

Spec reference: docs/specs/08-persistence-io.md [PIO-5.4], [PIO-8].
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from importlib import import_module, metadata
from typing import Any, Protocol

from simplebroker import Queue
from simplebroker.ext import SidecarSession

from taut._exceptions import TautError

from . import PersistenceComponentSpec

ENTRY_POINT_GROUP = "taut.persistence_components"
_NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,31}")


class PersistenceComponentCompatibilityError(TautError):
    """An installed contributor cannot read its active live schema."""


class PersistenceComponentManifestError(TautError):
    """Installed contributor metadata violates the fixed manifest contract."""


class PersistenceComponentRuntimeError(TautError):
    """Trusted contributor code could not be imported or initialized."""


class PersistenceComponent(Protocol):
    def validate_live_schema(self, queue: Queue) -> None: ...

    def ensure_schema(self, queue: Queue) -> None: ...

    def dump_records(self, queue: Queue) -> list[dict[str, Any]]: ...

    def validate_records(
        self,
        version: int,
        records: Iterable[dict[str, Any]],
        *,
        core_member_ids: frozenset[str],
    ) -> None: ...

    def is_fresh(self, queue: Queue) -> bool: ...

    def load_records(
        self,
        session: SidecarSession,
        records: Iterable[dict[str, Any]],
    ) -> None: ...


class RegisteredPersistenceComponent:
    __slots__ = ("component", "spec")

    def __init__(
        self,
        spec: PersistenceComponentSpec,
        component: PersistenceComponent,
    ) -> None:
        self.spec = spec
        self.component = component


def _entry_point_identity(entry_point: metadata.EntryPoint) -> str:
    distribution = getattr(entry_point, "dist", None)
    distribution_name = getattr(distribution, "name", None) or "unknown"
    distribution_version = getattr(distribution, "version", None) or "unknown"
    return (
        f"distribution {distribution_name!r} {distribution_version!r}, "
        f"entry point {entry_point.name!r} ({entry_point.value!r})"
    )


def _load_target(target: str) -> Any:
    module_name, separator, attribute = target.partition(":")
    if not separator or not module_name or not attribute or "." in attribute:
        raise PersistenceComponentRuntimeError(
            f"invalid persistence implementation target {target!r}"
        )
    try:
        return getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise PersistenceComponentRuntimeError(
            f"cannot load persistence implementation {target!r}: {exc}"
        ) from exc


def _validate_spec(
    entry_point: metadata.EntryPoint, value: Any
) -> PersistenceComponentSpec:
    if type(value) is not PersistenceComponentSpec:
        raise PersistenceComponentManifestError(
            f"persistence entry point {entry_point.name!r} returned "
            f"{type(value).__name__}, expected PersistenceComponentSpec"
        )
    if value.component_api_version != 1 or isinstance(
        value.component_api_version, bool
    ):
        raise PersistenceComponentManifestError(
            f"persistence component {entry_point.name!r} has unsupported "
            f"interface version {value.component_api_version!r}"
        )
    if (
        value.name != entry_point.name
        or _NAME_RE.fullmatch(value.name) is None
        or value.name in {"simplebroker", "taut-core"}
    ):
        raise PersistenceComponentManifestError(
            f"persistence entry point {entry_point.name!r} has invalid manifest name "
            f"{value.name!r}"
        )
    if (
        not isinstance(value.write_version, int)
        or isinstance(value.write_version, bool)
        or value.write_version <= 0
        or type(value.load_versions) is not frozenset
        or value.write_version not in value.load_versions
        or not value.load_versions
        or any(
            not isinstance(version, int) or isinstance(version, bool) or version <= 0
            for version in value.load_versions
        )
        or type(value.schema_keys) is not frozenset
        or not value.schema_keys
        or any(not isinstance(key, str) or not key for key in value.schema_keys)
        or not isinstance(value.implementation, str)
    ):
        raise PersistenceComponentManifestError(
            f"persistence component {value.name!r} has malformed metadata"
        )
    return value


def discover_components() -> tuple[RegisteredPersistenceComponent, ...]:
    """Discover, validate, and instantiate contributors for one system operation."""

    selected = metadata.entry_points().select(group=ENTRY_POINT_GROUP)
    registered: list[RegisteredPersistenceComponent] = []
    names: set[str] = set()
    keys: set[str] = set()
    for entry_point in sorted(selected, key=lambda item: (item.name, item.value)):
        identity = _entry_point_identity(entry_point)
        try:
            raw_spec = entry_point.load()
        except Exception as exc:
            raise PersistenceComponentRuntimeError(
                f"{identity}: persistence manifest failed to load: {exc}"
            ) from exc
        try:
            spec = _validate_spec(entry_point, raw_spec)
            if spec.name in names:
                raise PersistenceComponentManifestError(
                    f"duplicate persistence component {spec.name!r}"
                )
            overlap = keys & spec.schema_keys
            if overlap:
                raise PersistenceComponentManifestError(
                    "duplicate persistence schema-key ownership: "
                    + ", ".join(sorted(overlap))
                )
            factory = _load_target(spec.implementation)
            if not callable(factory):
                raise PersistenceComponentRuntimeError(
                    f"persistence implementation {spec.implementation!r} "
                    "is not callable"
                )
            try:
                component = factory()
            except Exception as exc:
                raise PersistenceComponentRuntimeError(
                    f"persistence implementation {spec.implementation!r} "
                    f"failed to initialize: {exc}"
                ) from exc
        except PersistenceComponentManifestError as exc:
            raise PersistenceComponentManifestError(f"{identity}: {exc}") from exc
        except PersistenceComponentRuntimeError as exc:
            raise PersistenceComponentRuntimeError(f"{identity}: {exc}") from exc
        registered.append(RegisteredPersistenceComponent(spec, component))
        names.add(spec.name)
        keys.update(spec.schema_keys)
    return tuple(registered)
