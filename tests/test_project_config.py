from __future__ import annotations

from pathlib import Path

import pytest

from taut._constants import PROJECT_CONFIG_NAME, load_config
from taut._exceptions import NotInitializedError, TautError
from taut.client import TautClient
from tests.conftest import ensure_taut_project_config

pytestmark = pytest.mark.sqlite_only


def _write_project_config(path: Path, *, backend: str, target: str) -> None:
    path.write_text(
        "\n".join(
            [
                "version = 1",
                f'backend = "{backend}"',
                f'target = "{target}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_load_config_pins_ambient_broker_backend_to_sqlite(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROKER_BACKEND", "postgres")

    config = load_config()

    assert config["BROKER_BACKEND"] == "sqlite"


def test_env_only_broker_backend_does_not_select_postgres(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROKER_BACKEND", "postgres")

    result = TautClient.init()

    assert result.created is True
    assert result.db == str(tmp_path / ".taut.db")
    assert (tmp_path / ".taut.db").exists()


def test_missing_postgres_plugin_error_mentions_extension(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    ensure_taut_project_config(
        tmp_path,
        dsn="postgresql://taut.example/missing_plugin",
        schema="taut_schema",
    )

    def raise_unknown(name: str) -> None:
        raise RuntimeError(f"Unknown backend plugin: {name}; entry point not loaded")

    monkeypatch.setattr(
        "simplebroker._project_config.get_backend_plugin", raise_unknown
    )

    with pytest.raises(TautError, match="Install taut-pg"):
        TautClient.init()


def test_taut_project_config_wins_over_broker_toml(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    broker_db = tmp_path / "broker-selected.db"
    taut_db = tmp_path / "taut-selected.db"
    _write_project_config(
        tmp_path / ".broker.toml",
        backend="sqlite",
        target=broker_db.name,
    )
    _write_project_config(
        tmp_path / PROJECT_CONFIG_NAME,
        backend="sqlite",
        target=taut_db.name,
    )
    monkeypatch.chdir(tmp_path)

    result = TautClient.init()
    TautClient(as_handle="van").join("general")

    assert result.db == str(taut_db)
    assert taut_db.exists()
    assert not broker_db.exists()


def test_existing_taut_project_config_is_not_overwritten(tmp_path: Path) -> None:
    config_path = tmp_path / PROJECT_CONFIG_NAME
    config_path.write_text("# user config\n", encoding="utf-8")

    returned = ensure_taut_project_config(
        tmp_path,
        dsn="postgresql://example/ignored",
        schema="ignored",
    )

    assert returned == config_path
    assert config_path.read_text(encoding="utf-8") == "# user config\n"


def test_explicit_missing_path_does_not_auto_create(tmp_path: Path) -> None:
    with pytest.raises(NotInitializedError):
        TautClient(db_path=tmp_path / ".taut.db")

    assert not (tmp_path / ".taut.db").exists()
