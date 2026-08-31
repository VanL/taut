from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from simplebroker import ResolvedConfig, resolve_config
from simplebroker.ext import InvalidConfigError

from taut._constants import _TAUT_BROKER_DEFAULTS, freeze_broker_config, load_config

pytestmark = pytest.mark.sqlite_only


CONFIG_CASES: tuple[tuple[str, str, Any, Any], ...] = (
    ("TAUT_DEFAULT_DB_LOCATION", "", "/tmp/taut-config", "/tmp/taut-config"),
    ("TAUT_DEFAULT_DB_NAME", ".taut.db", "chosen.db", "chosen.db"),
    ("TAUT_PROJECT_CONFIG_PATH", "", "config", "config"),
    ("TAUT_PROJECT_CONFIG_NAME", ".taut.toml", "chosen.toml", "chosen.toml"),
    ("TAUT_PROJECT_SCOPE", "1", "0", False),
    ("TAUT_BACKEND", "sqlite", "memory", "memory"),
    ("TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS", "300", "42", 42),
    ("TAUT_BUSY_TIMEOUT", "5000", "1234", 1234),
    ("TAUT_CACHE_MB", "10", "11", 11),
    ("TAUT_SYNC_MODE", "FULL", "normal", "NORMAL"),
    ("TAUT_WAL_AUTOCHECKPOINT", "1000", "321", 321),
    ("TAUT_MAX_MESSAGE_SIZE", "10485760", "4096", 4096),
    ("TAUT_READ_COMMIT_INTERVAL", "1", "2", 2),
    ("TAUT_GENERATOR_BATCH_SIZE", "100", "25", 25),
    ("TAUT_AUTO_VACUUM", "1", "0", 0),
    ("TAUT_AUTO_VACUUM_INTERVAL", "100", "75", 75),
    ("TAUT_VACUUM_THRESHOLD", "10", "25", 0.25),
    ("TAUT_VACUUM_BATCH_SIZE", "1000", "250", 250),
    ("TAUT_SKIP_IDLE_CHECK", "0", "1", True),
    ("TAUT_JITTER_FACTOR", "0.15", "0.25", 0.25),
    ("TAUT_INITIAL_CHECKS", "100", "12", 12),
    ("TAUT_MAX_INTERVAL", "0.1", "0.5", 0.5),
    ("TAUT_BURST_SLEEP", "0.00001", "0.001", 0.001),
    ("TAUT_DEBUG", "", "1", True),
    ("TAUT_LOGGING_ENABLED", "0", "1", True),
    ("TAUT_BACKEND_HOST", "localhost", "db.internal", "db.internal"),
    ("TAUT_BACKEND_PORT", "5432", "5544", 5544),
    ("TAUT_BACKEND_USER", "postgres", "taut", "taut"),
    ("TAUT_BACKEND_PASSWORD", "", "secret", "secret"),
    ("TAUT_BACKEND_DATABASE", "simplebroker", "taut", "taut"),
    ("TAUT_BACKEND_SCHEMA", "simplebroker_pg_v1", "taut_v1", "taut_v1"),
    ("TAUT_BACKEND_TARGET", "", "opaque-target", "opaque-target"),
)


def _broker_key(taut_key: str) -> str:
    return f"BROKER_{taut_key.removeprefix('TAUT_')}"


def test_load_config_has_exhaustive_isolated_mapping(clean_env: None) -> None:
    config = load_config()

    expected_keys = {_broker_key(key) for key, _, _, _ in CONFIG_CASES}
    assert _TAUT_BROKER_DEFAULTS == {
        key: raw_default for key, raw_default, _, _ in CONFIG_CASES
    }
    assert isinstance(config, ResolvedConfig)
    assert expected_keys.issubset(config)


@pytest.mark.parametrize(
    ("taut_key", "raw_default", "raw_override", "expected"), CONFIG_CASES
)
def test_each_taut_setting_maps_to_one_broker_field(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    taut_key: str,
    raw_default: str,
    raw_override: Any,
    expected: Any,
) -> None:
    default_config = load_config()
    monkeypatch.setenv(taut_key, str(raw_override))
    changed_config = load_config()
    broker_key = _broker_key(taut_key)

    assert changed_config[broker_key] == expected
    assert {
        key for key in changed_config if changed_config[key] != default_config[key]
    } == {broker_key}


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

    assert config["BROKER_DEFAULT_DB_LOCATION"] == str(db.parent)
    assert config["BROKER_DEFAULT_DB_NAME"] == db.name


def test_load_config_translates_taut_future_skew_setting(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert load_config()["BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS"] == 300

    monkeypatch.setenv("TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS", "42")

    assert load_config()["BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS"] == 42


@pytest.mark.parametrize("invalid", ["-1", "true", "1.5", "not-an-integer"])
def test_invalid_taut_future_skew_names_public_setting(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    monkeypatch.setenv("TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS", invalid)

    with pytest.raises(
        ValueError,
        match="invalid configuration TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS=",
    ):
        load_config()


def test_taut_future_skew_overrides_valid_ambient_broker_value(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS", "99")
    monkeypatch.setenv("TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS", "42")

    assert load_config()["BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS"] == 42


def test_invalid_ambient_broker_future_skew_does_not_affect_taut(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS", "invalid-base")
    monkeypatch.setenv("TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS", "42")

    config = load_config()

    assert config["BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS"] == 42


def test_ambient_broker_values_do_not_change_taut_config(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = load_config()
    for taut_key, _, raw_override, _ in CONFIG_CASES:
        monkeypatch.setenv(_broker_key(taut_key), str(raw_override))

    assert dict(load_config()) == dict(expected)


@pytest.mark.parametrize(
    "taut_key",
    (
        "TAUT_BUSY_TIMEOUT",
        "TAUT_CACHE_MB",
        "TAUT_WAL_AUTOCHECKPOINT",
        "TAUT_MAX_MESSAGE_SIZE",
        "TAUT_READ_COMMIT_INTERVAL",
        "TAUT_GENERATOR_BATCH_SIZE",
        "TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS",
        "TAUT_AUTO_VACUUM",
        "TAUT_AUTO_VACUUM_INTERVAL",
        "TAUT_VACUUM_THRESHOLD",
        "TAUT_VACUUM_BATCH_SIZE",
        "TAUT_JITTER_FACTOR",
        "TAUT_INITIAL_CHECKS",
        "TAUT_MAX_INTERVAL",
        "TAUT_BURST_SLEEP",
        "TAUT_BACKEND_PORT",
    ),
)
def test_every_invalid_ambient_broker_numeric_is_ignored(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    taut_key: str,
) -> None:
    expected = load_config()
    monkeypatch.setenv(_broker_key(taut_key), "not-a-number")

    assert dict(load_config()) == dict(expected)


@pytest.mark.parametrize(
    "taut_key",
    (
        "TAUT_DEFAULT_DB_LOCATION",
        "TAUT_DEFAULT_DB_NAME",
        "TAUT_PROJECT_CONFIG_PATH",
        "TAUT_PROJECT_CONFIG_NAME",
    ),
)
def test_every_invalid_ambient_broker_path_is_ignored(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    taut_key: str,
) -> None:
    expected = load_config()
    monkeypatch.setenv(_broker_key(taut_key), "../unsafe")

    assert dict(load_config()) == dict(expected)


def test_taut_values_do_not_change_standalone_broker_config(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = resolve_config()
    for taut_key, _, raw_override, _ in CONFIG_CASES:
        monkeypatch.setenv(taut_key, str(raw_override))

    assert resolve_config() == expected


def test_relative_taut_db_clears_default_location(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAUT_DEFAULT_DB_LOCATION", "/tmp/ambient-location")
    monkeypatch.setenv("TAUT_DB", "relative.db")

    config = load_config()

    assert config["BROKER_DEFAULT_DB_LOCATION"] == ""
    assert config["BROKER_DEFAULT_DB_NAME"] == "relative.db"


def test_explicit_location_and_name_suppress_taut_db(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    explicit_location = tmp_path / "explicit"
    monkeypatch.setenv("TAUT_DB", str(tmp_path / "ambient.db"))

    config = load_config(
        {
            "TAUT_DEFAULT_DB_LOCATION": str(explicit_location),
            "TAUT_DEFAULT_DB_NAME": "workspace.db",
        }
    )

    assert config["BROKER_DEFAULT_DB_LOCATION"] == str(explicit_location)
    assert config["BROKER_DEFAULT_DB_NAME"] == "workspace.db"


def test_unknown_taut_override_fails_closed(clean_env: None) -> None:
    with pytest.raises(ValueError, match="unknown Taut configuration key"):
        load_config({"TAUT_NOT_A_BROKER_SETTING": "value"})


@pytest.mark.parametrize(
    "taut_key",
    (
        "TAUT_BUSY_TIMEOUT",
        "TAUT_CACHE_MB",
        "TAUT_WAL_AUTOCHECKPOINT",
        "TAUT_MAX_MESSAGE_SIZE",
        "TAUT_READ_COMMIT_INTERVAL",
        "TAUT_GENERATOR_BATCH_SIZE",
        "TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS",
        "TAUT_AUTO_VACUUM",
        "TAUT_AUTO_VACUUM_INTERVAL",
        "TAUT_VACUUM_THRESHOLD",
        "TAUT_VACUUM_BATCH_SIZE",
        "TAUT_JITTER_FACTOR",
        "TAUT_INITIAL_CHECKS",
        "TAUT_MAX_INTERVAL",
        "TAUT_BURST_SLEEP",
        "TAUT_BACKEND_PORT",
    ),
)
def test_rejecting_numeric_grammars_name_the_taut_key(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    taut_key: str,
) -> None:
    monkeypatch.setenv(taut_key, "not-a-number")

    with pytest.raises(ValueError, match=rf"invalid configuration {taut_key}="):
        load_config()


def test_invalid_value_preserves_real_resolver_expected_display(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import simplebroker

    with pytest.raises(InvalidConfigError) as upstream:
        simplebroker.resolve_isolated_config({"BROKER_BUSY_TIMEOUT": "invalid"})
    monkeypatch.setenv("TAUT_BUSY_TIMEOUT", "invalid")

    with pytest.raises(ValueError) as translated:
        load_config()

    assert f"expected {upstream.value.expected}" in str(translated.value)


@pytest.mark.parametrize(
    "taut_key",
    (
        "TAUT_DEFAULT_DB_LOCATION",
        "TAUT_DEFAULT_DB_NAME",
        "TAUT_PROJECT_CONFIG_PATH",
        "TAUT_PROJECT_CONFIG_NAME",
    ),
)
def test_rejecting_path_grammars_name_the_taut_key(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    taut_key: str,
) -> None:
    monkeypatch.setenv(taut_key, "../unsafe")

    with pytest.raises(ValueError, match=rf"invalid configuration {taut_key}="):
        load_config()


def test_future_canonical_broker_key_survives_load_and_refreeze(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import simplebroker

    real_resolver = simplebroker.resolve_isolated_config

    def future_resolver(values: dict[str, Any]) -> ResolvedConfig:
        current = dict(values)
        new_value = current.pop("BROKER_NEW_SETTING", "future-default")
        resolved = dict(real_resolver(current))
        resolved["BROKER_NEW_SETTING"] = new_value
        return ResolvedConfig(resolved)

    monkeypatch.setattr(simplebroker, "resolve_isolated_config", future_resolver)

    loaded = load_config()
    frozen = freeze_broker_config(dict(loaded))

    assert isinstance(loaded, ResolvedConfig)
    assert loaded["BROKER_NEW_SETTING"] == "future-default"
    assert isinstance(frozen, ResolvedConfig)
    assert frozen["BROKER_NEW_SETTING"] == "future-default"


@pytest.mark.parametrize("drift", ("removal", "rename"))
def test_broker_schema_drift_fails_closed(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    import simplebroker

    real_resolver = simplebroker.resolve_isolated_config

    def drifted(config: dict[str, Any]) -> object:
        resolved = dict(real_resolver(config))
        if not config:
            value = resolved.pop("BROKER_BUSY_TIMEOUT")
            if drift == "rename":
                resolved["BROKER_REMOVED_BUSY_TIMEOUT"] = value
        return resolved

    monkeypatch.setattr(simplebroker, "resolve_isolated_config", drifted)

    with pytest.raises(
        RuntimeError,
        match="incompatible SimpleBroker configuration schema",
    ):
        load_config()


def test_freeze_rejects_missing_taut_owned_key_before_default_refill(
    clean_env: None,
) -> None:
    config = dict(load_config())
    config.pop("BROKER_BUSY_TIMEOUT")

    with pytest.raises(
        RuntimeError,
        match="incompatible SimpleBroker configuration schema",
    ):
        freeze_broker_config(config)


def test_freeze_rejects_arbitrary_unknown_broker_key(clean_env: None) -> None:
    config = dict(load_config())
    config["BROKER_NOT_CANONICAL"] = "opaque"

    with pytest.raises(InvalidConfigError) as raised:
        freeze_broker_config(config)

    assert raised.value.key == "BROKER_NOT_CANONICAL"


def test_freeze_fails_closed_on_removed_required_upstream_key(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import simplebroker

    config = load_config()
    real_resolver = simplebroker.resolve_isolated_config

    def removed_field(values: dict[str, Any]) -> object:
        if not values:
            resolved = dict(real_resolver(values))
            resolved.pop("BROKER_BUSY_TIMEOUT")
            return resolved
        return real_resolver(values)

    monkeypatch.setattr(simplebroker, "resolve_isolated_config", removed_field)

    with pytest.raises(
        RuntimeError,
        match="incompatible SimpleBroker configuration schema",
    ):
        freeze_broker_config(config)
