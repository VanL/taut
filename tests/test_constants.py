from __future__ import annotations

from pathlib import Path

import pytest
from simplebroker import Config, Queue, resolve_config
from simplebroker.ext import InvalidConfigError, MessageError

from taut import TautClient
from taut._config import load_config

pytestmark = pytest.mark.sqlite_only


def test_load_config_has_taut_namespace_and_defaults(clean_env: None) -> None:
    config = load_config()

    assert isinstance(config, Config)
    assert config.prefix == "TAUT"
    assert config["DEFAULT_DB_NAME"] == ".taut.db"
    assert config["PROJECT_CONFIG_NAME"] == ".taut.toml"
    assert config["PROJECT_SCOPE"] is True
    assert config["DB"] == ""
    assert config["AS"] == ""
    assert config["TOKEN"] == ""


def test_taut_setting_changes_real_queue_behavior(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BROKER_MAX_MESSAGE_SIZE", "1")
    config = load_config({"TAUT_MAX_MESSAGE_SIZE": 3})
    queue = Queue("messages", db_path=str(tmp_path / "messages.db"), config=config)

    with pytest.raises(MessageError):
        queue.write("four")
    queue.write("ok")

    assert config["MAX_MESSAGE_SIZE"] == 3


def test_declared_identity_and_custom_context_reach_queue_unchanged(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TAUT_AS", "van")
    monkeypatch.setenv("TAUT_TOKEN", "secret")
    monkeypatch.setenv("TAUT_DEBUG_ACTION", "raise")
    monkeypatch.setenv("TAUT_WORKSPACE_LABEL", "docs")

    config = load_config()
    queue = Queue("messages", db_path=str(tmp_path / "messages.db"), config=config)
    queue.write("hello")

    assert queue._config is config
    assert config["AS"] == "van"
    assert config["TOKEN"] == "secret"
    assert config["DEBUG_ACTION"] == "raise"
    assert config["WORKSPACE_LABEL"] == "docs"
    assert queue.read() == "hello"


def test_invalid_setting_preserves_upstream_public_metadata(
    clean_env: None,
) -> None:
    with pytest.raises(InvalidConfigError) as raised:
        load_config({"TAUT_BUSY_TIMEOUT": "invalid"})

    assert raised.value.key == "TAUT_BUSY_TIMEOUT"
    assert raised.value.source == "override"
    assert raised.value.expected == "an integer number of milliseconds"


def test_config_derivation_keeps_source_snapshot(clean_env: None) -> None:
    source = load_config({"TAUT_CACHE_MB": 11})

    derived = resolve_config(config=source, override={"TAUT_CACHE_MB": 12})

    assert source["CACHE_MB"] == 11
    assert derived["CACHE_MB"] == 12
    assert derived.prefix == "TAUT"


def test_vacuum_threshold_keeps_percentage_units(clean_env: None) -> None:
    assert load_config({"TAUT_VACUUM_THRESHOLD": 25})["VACUUM_THRESHOLD"] == 25.0


def test_equivalent_resolutions_share_persistent_process_session(
    clean_env: None,
    tmp_path: Path,
) -> None:
    database = tmp_path / "messages.db"
    first = Queue("first", db_path=str(database), persistent=True, config=load_config())
    second = Queue(
        "second", db_path=str(database), persistent=True, config=load_config()
    )
    try:
        assert first.conn is not None
        assert second.conn is not None
        assert first.conn._shared_session is second.conn._shared_session
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("configured", ["", "selected.db"])
def test_taut_db_is_a_direct_taut_database_selector(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    configured: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TAUT_DB", configured)

    result = TautClient.init()

    expected = tmp_path / (configured or ".taut.db")
    assert result.db == (configured or str(expected))
    assert expected.exists()
    assert load_config()["DB"] == configured


def test_absolute_taut_db_remains_a_direct_database_selector(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "selected.db"
    monkeypatch.setenv("TAUT_DB", str(database))

    result = TautClient.init()

    assert result.db == str(database)
    assert database.exists()


def test_taut_db_preserves_unowned_parent_directory_spelling(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "directory with space"
    parent.mkdir()
    database = parent / "selected.db"
    monkeypatch.setenv("TAUT_DB", str(database))

    result = TautClient.init()

    assert result.db == str(database)
    assert database.exists()
