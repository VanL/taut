from __future__ import annotations

from pathlib import Path

import pytest

from taut._constants import load_config


def test_load_config_translates_taut_resolution_keys(clean_env: None) -> None:
    config = load_config()

    assert config["BROKER_DEFAULT_DB_NAME"] == ".taut.db"
    assert config["BROKER_PROJECT_SCOPE"] is True
    assert config["BROKER_PROJECT_CONFIG_NAME"] == ".taut.toml"


def test_taut_db_overrides_default_db_name(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = tmp_path / "chosen.db"
    monkeypatch.setenv("TAUT_DB", str(db))

    config = load_config()

    assert config["BROKER_DEFAULT_DB_NAME"] == str(db)
