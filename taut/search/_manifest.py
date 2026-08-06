"""Lightweight first-party search-provider manifest contract.

Spec reference: docs/specs/06-search.md [SRCH-7].
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

SEARCH_PROVIDER_API_VERSION: Final[int] = 1


@dataclass(frozen=True, slots=True)
class SearchBackendSpec:
    """Describe one lazily loaded first-party search backend."""

    search_provider_api_version: int
    backend_name: str
    implementation: str


__all__ = ["SEARCH_PROVIDER_API_VERSION", "SearchBackendSpec"]
