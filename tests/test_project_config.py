from __future__ import annotations

import importlib.metadata as importlib_metadata
import tomllib
from importlib import resources
from pathlib import Path

import pytest
from simplebroker import resolve_broker_target

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


def _write_reaction_project_config(path: Path, reaction_lines: list[str]) -> None:
    path.write_text(
        "\n".join(
            [
                "version = 1",
                'backend = "sqlite"',
                'target = ".taut.db"',
                "",
                *reaction_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _reaction_target(actor: TautClient, author: TautClient) -> str:
    actor.join("general")
    author.join("general")
    return str(author.say("general", "reaction policy target").ts)


def _assert_reaction_allowed(
    actor: TautClient,
    target: str,
    reaction: str,
) -> None:
    receipt = actor.react_to_message(target, reaction)

    assert receipt.message_ts == int(target)
    assert receipt.reaction == reaction


def test_packaged_reaction_defaults_are_ordered() -> None:
    with resources.files("taut").joinpath("defaults.toml").open("rb") as stream:
        document = tomllib.load(stream)

    assert document["reactions"]["values"] == ["ack", "blocked"]


@pytest.mark.parametrize(
    "packaged_text",
    [
        "[terminal_text]\nescape_patterns = []\n",
        "[reactions]\nvalues = 'ack'\n",
        "[reactions]\nvalues = ['LOUD!']\n",
    ],
)
def test_invalid_packaged_reaction_defaults_use_fixed_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    packaged_text: str,
) -> None:
    import taut._reactions as reactions

    (tmp_path / "defaults.toml").write_text(packaged_text, encoding="utf-8")
    monkeypatch.setattr(reactions.resources, "files", lambda _package: tmp_path)

    with pytest.raises(
        TautError,
        match="^reaction configuration is unavailable$",
    ):
        reactions.load_reaction_values(None)


@pytest.mark.parametrize(
    ("reaction_lines", "accepted", "rejected"),
    [
        (
            ["[reactions]", "future_key = true"],
            ("ack", "blocked"),
            "project-only",
        ),
        (
            ["[reactions]", 'values = ["ack", "done", "blocked"]'],
            ("ack", "done", "blocked"),
            "project-only",
        ),
        (["[reactions]", "values = []"], (), "ack"),
    ],
)
def test_project_reaction_values_inherit_replace_or_disable(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reaction_lines: list[str],
    accepted: tuple[str, ...],
    rejected: str,
) -> None:
    _write_reaction_project_config(
        tmp_path / PROJECT_CONFIG_NAME,
        reaction_lines,
    )
    monkeypatch.chdir(tmp_path)
    TautClient.init()

    actor = TautClient(as_name="van")
    author = TautClient(as_name="author")
    try:
        target = _reaction_target(actor, author)
        for reaction in accepted:
            _assert_reaction_allowed(actor, target, reaction)
        expected_error = (
            "message reactions are disabled by project configuration"
            if not accepted
            else "reaction must be one of"
        )
        with pytest.raises(ValueError, match=expected_error):
            actor.react_to_message(target, rejected)
    finally:
        actor.close()
        author.close()


@pytest.mark.parametrize(
    ("reaction_lines", "invalid_value"),
    [
        (["reactions = []"], None),
        (["[reactions]", 'values = "ack"'], None),
        (["[reactions]", "values = [1]"], None),
        (["[reactions]", 'values = ["ack", "ack"]'], None),
        (["[reactions]", 'values = ["ack", "LOUD!"]'], "LOUD!"),
    ],
)
def test_invalid_project_reaction_values_fail_without_echoing_values(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reaction_lines: list[str],
    invalid_value: str | None,
) -> None:
    _write_reaction_project_config(
        tmp_path / PROJECT_CONFIG_NAME,
        reaction_lines,
    )
    monkeypatch.chdir(tmp_path)
    TautClient.init()

    with pytest.raises(TautError) as caught:
        TautClient(as_name="van")

    assert str(caught.value) == (
        "invalid .taut.toml: [reactions].values must be a list of unique "
        "lowercase ASCII slugs"
    )
    if invalid_value is not None:
        assert invalid_value not in str(caught.value)


def test_reaction_values_are_frozen_per_client_construction(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / PROJECT_CONFIG_NAME
    _write_reaction_project_config(
        config_path,
        ["[reactions]", 'values = ["first"]'],
    )
    monkeypatch.chdir(tmp_path)
    TautClient.init()
    first = TautClient(as_name="van")

    _write_reaction_project_config(
        config_path,
        ["[reactions]", 'values = ["second"]'],
    )
    second = TautClient(as_name="second")
    try:
        target = _reaction_target(first, second)
        _assert_reaction_allowed(first, target, "first")
        _assert_reaction_allowed(second, target, "second")
        with pytest.raises(ValueError, match="reaction must be one of: first"):
            first.react_to_message(target, "second")
        with pytest.raises(ValueError, match="reaction must be one of: second"):
            second.react_to_message(target, "first")
    finally:
        first.close()
        second.close()


def test_handed_off_target_uses_its_own_reaction_config(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_reaction_project_config(
        project / PROJECT_CONFIG_NAME,
        ["[reactions]", 'values = ["project-only"]'],
    )
    monkeypatch.chdir(project)
    TautClient.init()
    config = load_config()
    target = resolve_broker_target(project, config=config)
    assert target is not None
    actor = TautClient(as_name="van")
    author = TautClient(as_name="author")
    reaction_target = _reaction_target(actor, author)

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    _write_reaction_project_config(
        unrelated / PROJECT_CONFIG_NAME,
        ["[reactions]", 'values = ["wrong-project"]'],
    )
    monkeypatch.chdir(unrelated)
    client = TautClient(
        broker_target=target,
        broker_config=config,
        as_name="van",
    )
    try:
        _assert_reaction_allowed(client, reaction_target, "project-only")
        with pytest.raises(ValueError, match="reaction must be one of: project-only"):
            client.react_to_message(reaction_target, "wrong-project")
    finally:
        client.close()
        actor.close()
        author.close()


@pytest.mark.parametrize("selector", ["db_path", "TAUT_DB"])
def test_explicit_path_selectors_use_packaged_reaction_defaults(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selector: str,
) -> None:
    database = tmp_path / "selected.db"
    TautClient.init(db_path=database)
    _write_reaction_project_config(
        tmp_path / PROJECT_CONFIG_NAME,
        ["[reactions]", 'values = ["cwd-only"]'],
    )
    monkeypatch.chdir(tmp_path)
    if selector == "TAUT_DB":
        monkeypatch.setenv("TAUT_DB", str(database))
        actor = TautClient(as_name="van")
        author = TautClient(as_name="author")
    else:
        actor = TautClient(db_path=database, as_name="van")
        author = TautClient(db_path=database, as_name="author")
    try:
        target = _reaction_target(actor, author)
        _assert_reaction_allowed(actor, target, "ack")
        with pytest.raises(ValueError, match="reaction must be one of: ack, blocked"):
            actor.react_to_message(target, "cwd-only")
    finally:
        actor.close()
        author.close()


@pytest.mark.parametrize("alternate_name", [".broker.toml", "pyproject.toml"])
def test_alternate_config_files_do_not_supply_reaction_values(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    alternate_name: str,
) -> None:
    database = tmp_path / ".taut.db"
    TautClient.init(db_path=database)
    _write_reaction_project_config(
        tmp_path / alternate_name,
        ["[reactions]", 'values = ["alternate-only"]'],
    )
    monkeypatch.chdir(tmp_path)

    actor = TautClient(as_name="van")
    author = TautClient(as_name="author")
    try:
        target = _reaction_target(actor, author)
        _assert_reaction_allowed(actor, target, "ack")
        with pytest.raises(ValueError, match="reaction must be one of: ack, blocked"):
            actor.react_to_message(target, "alternate-only")
    finally:
        actor.close()
        author.close()


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
