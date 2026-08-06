"""PostgreSQL search-provider manifest discovery contracts."""

from __future__ import annotations

import sys
from dataclasses import fields
from importlib import metadata

import pytest

pytestmark = pytest.mark.pg_only


def test_postgres_search_manifest_is_lightweight_and_exact() -> None:
    from taut_pg.search_manifest import postgres

    from taut.search._manifest import (
        SEARCH_PROVIDER_API_VERSION,
        SearchBackendSpec,
    )

    assert type(SEARCH_PROVIDER_API_VERSION) is int
    assert SEARCH_PROVIDER_API_VERSION == 1
    assert isinstance(postgres, SearchBackendSpec)
    assert type(postgres.search_provider_api_version) is int
    assert tuple(field.name for field in fields(postgres)) == (
        "search_provider_api_version",
        "backend_name",
        "implementation",
    )
    assert postgres == SearchBackendSpec(
        search_provider_api_version=1,
        backend_name="postgres",
        implementation="taut_pg._search:create_provider",
    )
    assert "taut_pg._search" not in sys.modules


def test_installed_postgres_search_entry_point_loads_the_manifest_only() -> None:
    matches = tuple(
        entry_point
        for entry_point in metadata.entry_points(group="taut.search_backends")
        if entry_point.name == "postgres"
    )

    assert len(matches) == 1
    entry_point = matches[0]
    assert entry_point.value == "taut_pg.search_manifest:postgres"
    assert entry_point.dist is not None
    assert entry_point.dist.metadata["Name"] == "taut-pg"

    from taut_pg.search_manifest import postgres

    assert entry_point.load() is postgres
    assert "taut_pg._search" not in sys.modules
