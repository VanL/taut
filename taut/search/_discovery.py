"""Strict lazy discovery for the first-party PostgreSQL search provider."""

from __future__ import annotations

import re
from collections.abc import Callable
from importlib import import_module, metadata
from typing import Protocol, cast

from taut.search._manifest import SEARCH_PROVIDER_API_VERSION, SearchBackendSpec
from taut.search._provider import SearchProvider, SidecarAccessor

_IMPLEMENTATION_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r":[A-Za-z_][A-Za-z0-9_]*\Z"
)
_DIAGNOSTIC = (
    "taut-pg search provider unavailable; install or upgrade taut-pg "
    "in the same environment as taut"
)


class SearchProviderUnavailableError(RuntimeError):
    """The resolved backend has no trusted compatible search provider."""


class _Distribution(Protocol):
    @property
    def name(self) -> str: ...


class _EntryPoint(Protocol):
    name: str
    value: str
    dist: _Distribution | None

    def load(self) -> object: ...


def load_search_provider(
    *,
    backend_name: str,
    sidecar: SidecarAccessor,
) -> SearchProvider:
    """Load exactly one trusted backend provider on first search use."""

    if backend_name != "postgres":
        raise SearchProviderUnavailableError(_DIAGNOSTIC)
    claims = tuple(
        entry for entry in _search_entry_points() if entry.name == backend_name
    )
    if len(claims) != 1:
        raise SearchProviderUnavailableError(_DIAGNOSTIC)
    entry = claims[0]
    owner = None if entry.dist is None else _normalized_distribution(entry.dist.name)
    if owner != "taut-pg":
        raise SearchProviderUnavailableError(_DIAGNOSTIC)
    try:
        manifest = entry.load()
        validated = _validate_manifest(manifest, backend_name=backend_name)
        factory = _load_factory(validated.implementation)
        provider = factory(sidecar=sidecar)
        _validate_provider(provider)
    except SearchProviderUnavailableError:
        raise
    except Exception as exc:
        raise SearchProviderUnavailableError(_DIAGNOSTIC) from exc
    return cast(SearchProvider, provider)


def _search_entry_points() -> tuple[_EntryPoint, ...]:
    return cast(
        tuple[_EntryPoint, ...],
        tuple(metadata.entry_points(group="taut.search_backends")),
    )


def _validate_manifest(manifest: object, *, backend_name: str) -> SearchBackendSpec:
    if type(manifest) is not SearchBackendSpec:
        raise SearchProviderUnavailableError(_DIAGNOSTIC)
    if (
        isinstance(manifest.search_provider_api_version, bool)
        or manifest.search_provider_api_version != SEARCH_PROVIDER_API_VERSION
        or manifest.backend_name != backend_name
        or _IMPLEMENTATION_RE.fullmatch(manifest.implementation) is None
    ):
        raise SearchProviderUnavailableError(_DIAGNOSTIC)
    return manifest


def _load_factory(target: str) -> Callable[..., object]:
    module_name, attribute = target.split(":", 1)
    value = getattr(import_module(module_name), attribute)
    if not callable(value):
        raise SearchProviderUnavailableError(_DIAGNOSTIC)
    return cast(Callable[..., object], value)


def _validate_provider(provider: object) -> None:
    required = (
        "ensure_schema",
        "replace_document",
        "delete_document",
        "applied_revision",
        "retarget_threads",
        "thread_watermark",
        "indexed_message_ids",
        "record_reconciliation",
        "next_reconciliation_thread",
        "requires_rebuild",
        "begin_rebuild",
        "replace_rebuild_document",
        "finish_rebuild",
        "abort_rebuild",
        "query",
        "close",
    )
    if any(not callable(getattr(provider, name, None)) for name in required):
        raise SearchProviderUnavailableError(_DIAGNOSTIC)


def _normalized_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


__all__ = ["SearchProviderUnavailableError", "load_search_provider"]
