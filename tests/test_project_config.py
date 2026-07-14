from __future__ import annotations

import importlib.metadata as importlib_metadata
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


def _write_embedded_taut_config(path: Path, *, target: str) -> None:
    path.write_text(
        "\n".join(
            [
                "[tool.taut]",
                "version = 1",
                'backend = "sqlite"',
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

    class EmptyEntryPoints:
        def select(
            self, **_kwargs: object
        ) -> tuple[importlib_metadata.EntryPoint, ...]:
            return ()

    monkeypatch.setattr(importlib_metadata, "entry_points", EmptyEntryPoints)

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
    TautClient(as_name="van").join("general")

    assert result.db == str(taut_db)
    assert taut_db.exists()
    assert not broker_db.exists()


@pytest.mark.parametrize(
    "project_file",
    [".broker.toml", "pyproject.toml", "workspace.toml"],
)
def test_other_project_files_do_not_redirect_default_sqlite(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_file: str,
) -> None:
    alternate_db = tmp_path / "alternate.db"
    path = tmp_path / project_file
    if project_file == ".broker.toml":
        _write_project_config(
            path,
            backend="sqlite",
            target=alternate_db.name,
        )
    else:
        _write_embedded_taut_config(path, target=alternate_db.name)
    monkeypatch.chdir(tmp_path)

    result = TautClient.init()

    assert result.db == str(tmp_path / ".taut.db")
    assert (tmp_path / ".taut.db").exists()
    assert not alternate_db.exists()


@pytest.mark.parametrize("missing_field", ["version", "backend", "target"])
def test_discovered_taut_project_config_requires_every_storage_field(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing_field: str,
) -> None:
    fields = {
        "version": "version = 1",
        "backend": 'backend = "sqlite"',
        "target": 'target = ".taut.db"',
    }
    (tmp_path / PROJECT_CONFIG_NAME).write_text(
        "\n".join(value for key, value in fields.items() if key != missing_field)
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match=missing_field):
        TautClient.init()


def test_discovered_taut_config_does_not_merge_storage_from_other_files(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / PROJECT_CONFIG_NAME).write_text(
        'version = 1\nbackend = "sqlite"\n',
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[tool.taut]\ntarget = "alternate.db"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="target"):
        TautClient.init()


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


def test_terminal_only_project_config_does_not_define_storage(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut import escape_terminal_text

    (tmp_path / PROJECT_CONFIG_NAME).write_text(
        "[terminal_text]\ninherit_defaults = false\nescape_patterns = []\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert escape_terminal_text("raw\x1b") == "raw\x1b"
    with pytest.raises(ValueError, match="version"):
        TautClient.init()


def test_explicit_missing_path_does_not_auto_create(tmp_path: Path) -> None:
    with pytest.raises(NotInitializedError):
        TautClient(db_path=tmp_path / ".taut.db")

    assert not (tmp_path / ".taut.db").exists()
