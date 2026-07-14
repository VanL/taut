from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

pytestmark = pytest.mark.shared


def _write_terminal_project_config(
    path: Path,
    *,
    escape_patterns: tuple[str, ...],
    inherit_defaults: bool | None = None,
) -> None:
    lines = [
        "version = 1",
        'backend = "sqlite"',
        'target = ".taut.db"',
        "",
        "[terminal_text]",
    ]
    if inherit_defaults is not None:
        lines.append(f"inherit_defaults = {str(inherit_defaults).lower()}")
    rendered_patterns = ", ".join(json.dumps(item) for item in escape_patterns)
    lines.extend((f"escape_patterns = [{rendered_patterns}]", ""))
    path.write_text("\n".join(lines), encoding="utf-8")


def test_default_policy_escapes_terminal_controls() -> None:
    from taut import escape_terminal_text

    text = "before\x1b]52;c;Y2xpcGJvYXJk\x07after\x9b31m"

    assert escape_terminal_text(text) == (
        "before\\x1b]52;c;Y2xpcGJvYXJk\\aafter\\x9b31m"
    )


def test_default_policy_covers_every_c0_del_and_c1_code_point() -> None:
    from taut import escape_terminal_text

    controls = "".join(
        chr(code_point) for code_point in (*range(0x20), *range(0x7F, 0xA0))
    )
    expected = controls.encode("unicode_escape").decode("ascii")
    expected = (
        expected.replace(r"\x07", r"\a")
        .replace(r"\x08", r"\b")
        .replace(r"\x0b", r"\v")
        .replace(r"\x0c", r"\f")
    )

    assert escape_terminal_text(controls) == expected
    assert escape_terminal_text("plain café 🐍 \\x1b") == "plain café 🐍 \\x1b"


def test_callers_can_extend_or_replace_the_default_policy() -> None:
    from taut import escape_terminal_text

    assert (
        escape_terminal_text(
            "Aé🐍\x1b",
            additional_patterns=("A|é", "🐍"),
        )
        == r"\x41\xe9\U0001f40d\x1b"
    )
    assert (
        escape_terminal_text(
            "zabcq\x1b",
            additional_patterns=("ab", "bc"),
            inherit_defaults=False,
        )
        == "z\\x61\\x62\\x63q\x1b"
    )
    assert (
        escape_terminal_text(
            "unchanged\x1b",
            inherit_defaults=False,
        )
        == "unchanged\x1b"
    )


@pytest.mark.parametrize(
    ("escape_patterns", "inherit_defaults", "expected"),
    [
        (("MARK",), None, r"\x4d\x41\x52\x4b\x1b"),
        (("MARK",), False, "\\x4d\\x41\\x52\\x4b\x1b"),
        ((), False, "MARK\x1b"),
    ],
)
def test_project_policy_appends_replaces_and_disables_packaged_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    escape_patterns: tuple[str, ...],
    inherit_defaults: bool | None,
    expected: str,
) -> None:
    from taut import escape_terminal_text

    nested = tmp_path / "nested" / "deeper"
    nested.mkdir(parents=True)
    _write_terminal_project_config(
        tmp_path / ".taut.toml",
        escape_patterns=escape_patterns,
        inherit_defaults=inherit_defaults,
    )
    monkeypatch.chdir(nested)

    assert escape_terminal_text("MARK\x1b") == expected


def test_explicit_replacement_bypasses_project_and_packaged_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut import escape_terminal_text

    _write_terminal_project_config(
        tmp_path / ".taut.toml",
        escape_patterns=("PROJECT",),
    )
    monkeypatch.chdir(tmp_path)

    assert (
        escape_terminal_text(
            "PROJECT CALLER\x1b",
            additional_patterns=("CALLER",),
            inherit_defaults=False,
        )
        == "PROJECT \\x43\\x41\\x4c\\x4c\\x45\\x52\x1b"
    )


def test_project_and_caller_patterns_are_additive_in_inherited_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut import escape_terminal_text

    _write_terminal_project_config(
        tmp_path / ".taut.toml",
        escape_patterns=("PROJECT",),
    )
    monkeypatch.chdir(tmp_path)

    assert escape_terminal_text(
        "PROJECT CALLER\x1b",
        additional_patterns=("CALLER",),
    ) == (
        r"\x50\x52\x4f\x4a\x45\x43\x54 "
        r"\x43\x41\x4c\x4c\x45\x52\x1b"
    )


@pytest.mark.parametrize(
    ("terminal_section", "expected"),
    [
        ("", r"MARK\x1b"),
        ("[terminal_text]\nfuture_setting = 'ignored'\n", r"MARK\x1b"),
        ("[terminal_text]\ninherit_defaults = false\n", "MARK\x1b"),
    ],
)
def test_project_policy_omitted_keys_and_unknown_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    terminal_section: str,
    expected: str,
) -> None:
    from taut import escape_terminal_text

    (tmp_path / ".taut.toml").write_text(
        "\n".join(
            (
                "version = 1",
                'backend = "sqlite"',
                'target = ".taut.db"',
                "",
                terminal_section,
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert escape_terminal_text("MARK\x1b") == expected


def test_explicit_replacement_skips_ambient_and_packaged_policy_loading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import taut.terminal as terminal

    (tmp_path / ".taut.toml").write_text("terminal_text = [", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        terminal.resources,
        "files",
        lambda _package: pytest.fail("packaged policy was accessed"),
    )

    assert (
        terminal.escape_terminal_text(
            "CALLER\x1b",
            additional_patterns=("CALLER",),
            inherit_defaults=False,
        )
        == "\\x43\\x41\\x4c\\x4c\\x45\\x52\x1b"
    )


def test_project_policy_reloads_after_edit_deletion_and_nearer_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut import escape_terminal_text

    nested = tmp_path / "nested"
    nested.mkdir()
    parent_config = tmp_path / ".taut.toml"
    _write_terminal_project_config(
        parent_config,
        escape_patterns=("FIRST",),
    )
    monkeypatch.chdir(nested)
    assert escape_terminal_text("FIRST SECOND\x1b") == (
        r"\x46\x49\x52\x53\x54 SECOND\x1b"
    )

    _write_terminal_project_config(
        parent_config,
        escape_patterns=("SECOND-LONGER",),
    )
    assert escape_terminal_text("FIRST SECOND-LONGER\x1b") == (
        r"FIRST \x53\x45\x43\x4f\x4e\x44\x2d\x4c\x4f\x4e\x47\x45\x52\x1b"
    )

    parent_config.unlink()
    assert escape_terminal_text("FIRST SECOND\x1b") == r"FIRST SECOND\x1b"

    _write_terminal_project_config(
        nested / ".taut.toml",
        escape_patterns=("NEAR",),
    )
    assert escape_terminal_text("FIRST NEAR\x1b") == (r"FIRST \x4e\x45\x41\x52\x1b")


def test_broker_config_and_database_files_do_not_define_terminal_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut import escape_terminal_text

    _write_terminal_project_config(
        tmp_path / ".broker.toml",
        escape_patterns=(),
        inherit_defaults=False,
    )
    (tmp_path / ".taut.db").touch()
    monkeypatch.chdir(tmp_path)

    assert escape_terminal_text("MARK\x1b") == r"MARK\x1b"


@pytest.mark.parametrize("project_file", ["pyproject.toml", "workspace.toml"])
def test_other_project_files_do_not_define_terminal_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_file: str,
) -> None:
    from taut import escape_terminal_text

    (tmp_path / project_file).write_text(
        "\n".join(
            [
                "[tool.taut.terminal_text]",
                "inherit_defaults = false",
                "escape_patterns = []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert escape_terminal_text("MARK\x1b") == r"MARK\x1b"


def test_project_terminal_policy_does_not_merge_other_project_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut import escape_terminal_text

    _write_terminal_project_config(
        tmp_path / ".taut.toml",
        escape_patterns=("TAUT",),
        inherit_defaults=False,
    )
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.taut.terminal_text]",
                'escape_patterns = ["OTHER"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert escape_terminal_text("TAUT OTHER") == r"\x54\x41\x55\x54 OTHER"


def test_project_policy_search_has_no_artificial_depth_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut import escape_terminal_text

    _write_terminal_project_config(
        tmp_path / ".taut.toml",
        escape_patterns=("ROOT",),
    )
    nested = tmp_path
    for _ in range(105):
        nested /= "d"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert escape_terminal_text("ROOT") == r"\x52\x4f\x4f\x54"


def test_project_policy_parse_cache_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import taut.terminal as terminal

    terminal._load_project_policy.cache_clear()
    try:
        for index in range(140):
            project = tmp_path / str(index)
            project.mkdir()
            _write_terminal_project_config(
                project / ".taut.toml",
                escape_patterns=(f"P{index}",),
            )
            monkeypatch.chdir(project)
            terminal.escape_terminal_text("plain")

        cache_info = terminal._load_project_policy.cache_info()
        assert cache_info.maxsize == 128
        assert cache_info.currsize == 128
    finally:
        terminal._load_project_policy.cache_clear()


def test_nearest_project_policy_wins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut import escape_terminal_text

    nested = tmp_path / "nested"
    nested.mkdir()
    _write_terminal_project_config(
        tmp_path / ".taut.toml",
        escape_patterns=("PARENT",),
    )
    _write_terminal_project_config(
        nested / ".taut.toml",
        escape_patterns=("CHILD",),
    )
    monkeypatch.chdir(nested)

    assert escape_terminal_text("PARENT CHILD") == (r"PARENT \x43\x48\x49\x4c\x44")


def test_representative_project_policy_location_matches_broker_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from simplebroker import resolve_broker_target

    import taut.terminal as terminal
    from taut._constants import load_config

    nested = tmp_path / "nested" / "deeper"
    nested.mkdir(parents=True)
    config_path = tmp_path / ".taut.toml"
    _write_terminal_project_config(
        config_path,
        escape_patterns=("PROJECT",),
    )
    monkeypatch.chdir(nested)

    target = resolve_broker_target(Path.cwd(), config=load_config())
    assert target is not None
    assert target.config_path == config_path
    assert terminal._find_project_config(Path.cwd().resolve()) == config_path


@pytest.mark.parametrize(
    "terminal_section",
    [
        "terminal_text = [\n",
        "terminal_text = 'wrong type'\n",
        "[terminal_text]\ninherit_defaults = 'wrong type'\n",
        "[terminal_text]\nescape_patterns = 'wrong type'\n",
        "[terminal_text]\nescape_patterns = [1]\n",
        "[terminal_text]\nescape_patterns = ['[']\n",
        "[terminal_text]\nescape_patterns = ['(?=e)']\n",
    ],
)
def test_invalid_project_policy_uses_bootstrap_safe_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    terminal_section: str,
) -> None:
    from taut import escape_terminal_text

    (tmp_path / ".taut.toml").write_text(
        "\n".join(
            (
                "version = 1",
                'backend = "sqlite"',
                'target = ".taut.db"',
                "",
                terminal_section,
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(
        RuntimeError,
        match=r"^terminal output policy is unavailable$",
    ):
        escape_terminal_text("hello")


def test_extension_rules_merge_original_input_spans_without_reprocessing_output() -> (
    None
):
    from taut import escape_terminal_text

    assert (
        escape_terminal_text(
            "zabcq",
            additional_patterns=("ab", "bc"),
            inherit_defaults=False,
        )
        == r"z\x61\x62\x63q"
    )
    assert (
        escape_terminal_text(
            "\x1b",
            additional_patterns=(r"\x1b", r"\\"),
            inherit_defaults=False,
        )
        == r"\x1b"
    )


def test_extension_regexes_keep_independent_flags_groups_and_backreferences() -> None:
    from taut import escape_terminal_text

    assert (
        escape_terminal_text(
            "A aa bb",
            additional_patterns=(r"(?i)a", r"(b)\1"),
            inherit_defaults=False,
        )
        == r"\x41 \x61\x61 \x62\x62"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ""),
        ("\x1b]0;hostile title\x07", r"\x1b]0;hostile title\a"),
        ("\x1b[31mred\x1b[0m", r"\x1b[31mred\x1b[0m"),
        ("a\rb\bc\td\ne", r"a\rb\bc\td\ne"),
    ],
)
def test_default_policy_renders_common_terminal_control_sequences(
    text: str,
    expected: str,
) -> None:
    from taut import escape_terminal_text

    assert escape_terminal_text(text) == expected


def test_invalid_extension_pattern_contract() -> None:
    from taut import escape_terminal_text

    with pytest.raises(ValueError, match="invalid terminal escape pattern"):
        escape_terminal_text(
            "",
            additional_patterns=("", "["),
            inherit_defaults=False,
        )
    with pytest.raises(
        ValueError,
        match="terminal escape patterns must not match empty text",
    ):
        escape_terminal_text(
            "abc",
            additional_patterns=(r"(?=b)",),
            inherit_defaults=False,
        )


@pytest.mark.parametrize("patterns", ["abc", 1, ("abc", 1)])
def test_additional_patterns_require_an_iterable_of_strings(
    patterns: object,
) -> None:
    from taut import escape_terminal_text

    with pytest.raises(TypeError, match="additional_patterns"):
        escape_terminal_text(
            "abc",
            additional_patterns=patterns,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "policy",
    [
        None,
        "terminal_text = [",
        "terminal_text = 'wrong type'\n",
        "[terminal_text]\n",
        "[terminal_text]\nescape_patterns = 'wrong type'\n",
        "[terminal_text]\nescape_patterns = [1]\n",
        "[terminal_text]\nescape_patterns = ['[']\n",
    ],
)
def test_packaged_policy_failures_use_one_bootstrap_safe_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    policy: str | None,
) -> None:
    import taut.terminal as terminal

    if policy is not None:
        (tmp_path / "defaults.toml").write_text(policy, encoding="utf-8")
    monkeypatch.setattr(terminal.resources, "files", lambda _package: tmp_path)
    terminal._default_pattern_sources.cache_clear()
    terminal._compiled_default_patterns.cache_clear()
    try:
        with pytest.raises(
            RuntimeError,
            match=r"^terminal output policy is unavailable$",
        ):
            terminal.escape_terminal_text("hello")
    finally:
        terminal._default_pattern_sources.cache_clear()
        terminal._compiled_default_patterns.cache_clear()


def test_dispatch_policy_failure_is_exit_one_without_recursion_or_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import taut.terminal as terminal
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    (tmp_path / "defaults.toml").write_text("terminal_text = [", encoding="utf-8")
    monkeypatch.setattr(terminal.resources, "files", lambda _package: tmp_path)
    terminal._default_pattern_sources.cache_clear()
    terminal._compiled_default_patterns.cache_clear()
    stdout = StringIO()
    stderr = StringIO()
    try:
        result = dispatch(
            ["--unknown"],
            registry=CommandRegistry(entry_points=()),
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        terminal._default_pattern_sources.cache_clear()
        terminal._compiled_default_patterns.cache_clear()

    assert result == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "terminal output policy is unavailable\n"
    assert "Traceback" not in stderr.getvalue()

    stderr = StringIO()
    result = dispatch(
        ["watch"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
        client_factory=lambda **_kwargs: pytest.fail(
            "watch initialized a client before policy preflight"
        ),
    )
    assert result == 1
    assert stderr.getvalue() == "terminal output policy is unavailable\n"


def test_json_watch_skips_human_policy_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import taut.terminal as terminal
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    class Watcher:
        def run_forever(self) -> None:
            return

        def stop(self, *, join: bool, timeout: float) -> None:
            assert join is True
            assert timeout == 5.0

    class Client:
        def watch(self, _handler: object, *, threads: object) -> Watcher:
            assert threads is None
            return Watcher()

        def close(self) -> None:
            return

    (tmp_path / "defaults.toml").write_text("terminal_text = [", encoding="utf-8")
    monkeypatch.setattr(terminal.resources, "files", lambda _package: tmp_path)
    terminal._default_pattern_sources.cache_clear()
    terminal._compiled_default_patterns.cache_clear()
    stderr = StringIO()
    try:
        result = dispatch(
            ["--json", "watch"],
            registry=CommandRegistry(entry_points=()),
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
            client_factory=lambda **_kwargs: Client(),
        )
    finally:
        terminal._default_pattern_sources.cache_clear()
        terminal._compiled_default_patterns.cache_clear()

    assert result == 0
    assert stderr.getvalue() == ""


def test_maximum_size_printable_and_control_heavy_inputs() -> None:
    from taut import escape_terminal_text

    input_size = 10 * 1024 * 1024
    printable = "p" * input_size
    controls = "\x1b" * input_size

    assert escape_terminal_text(printable) == printable
    assert escape_terminal_text(controls) == r"\x1b" * input_size


def test_alternating_and_multi_code_point_extension_patterns() -> None:
    from taut import escape_terminal_text

    alternating = "a\x1b" * 32_768
    assert escape_terminal_text(alternating) == r"a\x1b" * 32_768
    assert (
        escape_terminal_text(
            "left TOKEN right",
            additional_patterns=("TOKEN",),
            inherit_defaults=False,
        )
        == r"left \x54\x4f\x4b\x45\x4e right"
    )
