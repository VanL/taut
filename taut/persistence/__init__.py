"""Workspace persistence interfaces.

Spec reference: docs/specs/08-persistence-io.md [PIO-3.2], [PIO-8.1].
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PersistenceComponentSpec:
    """Lightweight manifest for one installed durable-state contributor."""

    component_api_version: int
    name: str
    write_version: int
    load_versions: frozenset[int]
    schema_keys: frozenset[str]
    implementation: str


__all__ = ["PersistenceComponentSpec"]
