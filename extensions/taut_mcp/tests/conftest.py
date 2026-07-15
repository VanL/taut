"""Backend fixtures for the optional Taut MCP conformance lane."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import taut_pg  # noqa: F401  # Register the Postgres backend plugin.
from simplebroker.ext import get_backend_plugin


@pytest.fixture
def taut_pg_project(tmp_path: Path) -> Iterator[Path]:
    dsn = os.environ.get("SIMPLEBROKER_PG_TEST_DSN")
    if not dsn:
        pytest.skip("Set SIMPLEBROKER_PG_TEST_DSN to run MCP Postgres tests")
    schema = f"taut_mcp_test_{uuid.uuid4().hex[:12]}"
    (tmp_path / ".taut.toml").write_text(
        "\n".join(
            [
                "version = 1",
                'backend = "postgres"',
                f'target = "{dsn}"',
                "",
                "[backend_options]",
                f'schema = "{schema}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        yield tmp_path
    finally:
        get_backend_plugin("postgres").cleanup_target(
            dsn,
            backend_options={"schema": schema},
        )
