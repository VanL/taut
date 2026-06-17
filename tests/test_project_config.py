from __future__ import annotations

from pathlib import Path

import pytest

from taut._constants import PROJECT_CONFIG_NAME, load_config
from taut.client import TautClient, _raise_with_backend_install_hint
from tests.conftest import ensure_taut_project_config


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


def test_missing_postgres_plugin_error_mentions_extension() -> None:
    with pytest.raises(RuntimeError, match="Install taut-pg"):
        _raise_with_backend_install_hint(
            RuntimeError("Unknown backend plugin: postgres")
        )


def test_taut_project_config_wins_over_broker_toml(tmp_path: Path) -> None:
    (tmp_path / ".broker.toml").write_text(
        "\n".join(
            [
                "version = 1",
                'backend = "postgres"',
                'target = "postgresql://broker.example/ignored"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    config_path = ensure_taut_project_config(
        tmp_path,
        dsn="postgresql://taut.example/selected",
        schema="taut_schema",
    )

    assert config_path.name == PROJECT_CONFIG_NAME
    assert 'target = "postgresql://taut.example/selected"' in config_path.read_text(
        encoding="utf-8"
    )


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
    from taut._exceptions import NotInitializedError

    with pytest.raises(NotInitializedError):
        TautClient(db_path=tmp_path / ".taut.db")

    assert not (tmp_path / ".taut.db").exists()
