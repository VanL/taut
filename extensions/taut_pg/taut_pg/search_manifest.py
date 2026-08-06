"""Lightweight PostgreSQL search-provider manifest."""

from __future__ import annotations

from taut.search._manifest import SEARCH_PROVIDER_API_VERSION, SearchBackendSpec

postgres = SearchBackendSpec(
    search_provider_api_version=SEARCH_PROVIDER_API_VERSION,
    backend_name="postgres",
    implementation="taut_pg._search:create_provider",
)

__all__ = ["postgres"]
