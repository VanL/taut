from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest
from simplebroker.ext import get_backend_plugin

from taut._constants import PROJECT_CONFIG_NAME
from taut.client import TautClient

pytestmark = pytest.mark.pg_only


def test_extension_import_and_plugin_resolution() -> None:
    import taut_pg

    assert taut_pg.__all__ == []
    assert get_backend_plugin("postgres").name == "postgres"


def test_taut_init_and_messages_use_configured_postgres_project(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)

    result = TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")

    van.join("general")
    bob.join("general")
    message = van.say("general", "hello from pg")

    assert result.created is False
    assert result.db.startswith("postgresql://")
    assert message.text == "hello from pg"
    assert bob.read("general")[-1].text == "hello from pg"


def test_taut_client_discovers_postgres_project_from_nested_directory(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = taut_pg_project / "nested" / "worktree"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")

    van.say("general", "hello from nested pg")

    assert bob.read("general")[-1].text == "hello from nested pg"


def test_taut_cli_uses_postgres_project_config(
    taut_pg_project: Path,
    taut_cli: Callable[..., tuple[int, str, str]],
) -> None:
    rc, out, err = taut_cli("init", "--json", cwd=taut_pg_project)
    assert rc == 0, err
    init_result = json.loads(out)
    assert init_result["created"] is False
    assert init_result["db"].startswith("postgresql://")

    rc, out, err = taut_cli(
        "--as",
        "van",
        "join",
        "general",
        "--json",
        cwd=taut_pg_project,
    )
    assert rc == 0, err
    assert json.loads(out.splitlines()[0])["name"] == "van"

    rc, out, err = taut_cli(
        "--as",
        "van",
        "say",
        "general",
        "hello from pg cli",
        "--json",
        cwd=taut_pg_project,
    )
    assert rc == 0, err
    assert json.loads(out)["text"] == "hello from pg cli"

    rc, out, err = taut_cli("log", "general", "--json", cwd=taut_pg_project)
    assert rc == 0, err
    assert [json.loads(line)["text"] for line in out.splitlines()] == [
        "van created #general",
        "hello from pg cli",
    ]


def test_taut_project_config_file_selects_postgres(
    taut_pg_project: Path,
) -> None:
    config = (taut_pg_project / PROJECT_CONFIG_NAME).read_text(encoding="utf-8")

    assert 'backend = "postgres"' in config
    assert "[backend_options]" in config


def test_postgres_cleanup_drops_only_created_schema(
    pg_dsn: str,
    pg_schema: str,
    raw_pg_conn: psycopg.Connection[Any],
) -> None:
    plugin = get_backend_plugin("postgres")
    plugin.initialize_target(pg_dsn, backend_options={"schema": pg_schema})

    with raw_pg_conn.cursor() as cursor:
        cursor.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
            (pg_schema,),
        )
        assert cursor.fetchone() == (pg_schema,)

    assert plugin.cleanup_target(pg_dsn, backend_options={"schema": pg_schema}) is True

    with raw_pg_conn.cursor() as cursor:
        cursor.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
            (pg_schema,),
        )
        assert cursor.fetchone() is None
