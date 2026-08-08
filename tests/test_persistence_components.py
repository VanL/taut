"""Strict, lazy persistence-contributor discovery contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

pytestmark = pytest.mark.shared


@dataclass(frozen=True)
class _Distribution:
    name: str
    version: str


@dataclass(frozen=True)
class _EntryPoint:
    name: str
    value: str
    loaded: Any
    dist: _Distribution

    def load(self) -> Any:
        return self.loaded


class _EntryPoints(tuple[_EntryPoint, ...]):
    def select(self, *, group: str) -> _EntryPoints:
        assert group == "taut.persistence_components"
        return self


def test_malformed_manifest_error_names_distribution_and_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut._exceptions import TautError
    from taut.persistence import _components

    entry_point = _EntryPoint(
        name="broken",
        value="broken_package.persistence:manifest",
        loaded=object(),
        dist=_Distribution("broken-package", "3.2.1"),
    )
    monkeypatch.setattr(
        _components.metadata,
        "entry_points",
        lambda: _EntryPoints((entry_point,)),
    )

    with pytest.raises(TautError) as caught:
        _components.discover_components()

    message = str(caught.value)
    assert "distribution 'broken-package' '3.2.1'" in message
    assert "entry point 'broken' ('broken_package.persistence:manifest')" in message
    assert "expected PersistenceComponentSpec" in message


def test_duplicate_schema_key_error_names_the_conflicting_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut._exceptions import TautError
    from taut.persistence import PersistenceComponentSpec, _components

    def manifest(name: str) -> PersistenceComponentSpec:
        return PersistenceComponentSpec(
            component_api_version=1,
            name=name,
            write_version=1,
            load_versions=frozenset({1}),
            schema_keys=frozenset({"shared_schema_version"}),
            implementation="taut_summon.persistence:create_component",
        )

    entry_points = _EntryPoints(
        (
            _EntryPoint(
                name="first",
                value="first.persistence:manifest",
                loaded=manifest("first"),
                dist=_Distribution("first-package", "1.0"),
            ),
            _EntryPoint(
                name="second",
                value="second.persistence:manifest",
                loaded=manifest("second"),
                dist=_Distribution("second-package", "2.0"),
            ),
        )
    )
    monkeypatch.setattr(
        _components.metadata,
        "entry_points",
        lambda: entry_points,
    )

    with pytest.raises(TautError) as caught:
        _components.discover_components()

    message = str(caught.value)
    assert "distribution 'second-package' '2.0'" in message
    assert "duplicate persistence schema-key ownership" in message
    assert "shared_schema_version" in message
