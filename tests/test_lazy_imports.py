"""Fresh-process import floors for public facades and command selection.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.3], [TAUT-8.6]
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import PROJECT_ROOT, build_cli_env

pytestmark = pytest.mark.sqlite_only

SUMMON_RUNTIME_MODULES = {
    "taut_summon._adapter",
    "taut_summon._control",
    "taut_summon._driver",
    "taut_summon._pty",
    "taut_summon._state",
    "taut_summon.controller",
}


def _probe_modules(source: str, *, cwd: Path) -> set[str]:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=cwd,
        env=build_cli_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return set(json.loads(completed.stdout))


@pytest.mark.parametrize(
    ("source", "required", "forbidden", "forbid_all_summon"),
    [
        (
            """
            import json
            import sys
            import taut
            assert set(taut.__all__) <= set(dir(taut))
            assert {name for name in sys.modules if name == "taut" or name.startswith("taut.")} == {
                "taut", "taut._constants", "taut._exceptions"
            }
            print(json.dumps(sorted(sys.modules)))
            """,
            {"taut", "taut._constants", "taut._exceptions"},
            {"simplebroker", "taut.client", "taut.state", "taut.watcher"},
            True,
        ),
        (
            """
            import contextlib
            import io
            import json
            import sys
            from taut.cli import main
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                assert main(["--version"]) == 0
            print(json.dumps(sorted(sys.modules)))
            """,
            {"taut.cli", "taut.commands._dispatch"},
            {"simplebroker", "taut.client", "taut.state", "taut.watcher"},
            True,
        ),
        (
            """
            import contextlib
            import io
            import json
            import sys
            from taut.cli import main
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                assert main(["--help"]) == 0
            print(json.dumps(sorted(sys.modules)))
            """,
            {"taut.commands._builtins", "taut.commands._registry"},
            {
                "simplebroker",
                "taut.client",
                "taut.commands._summon_compat",
                "taut.commands.say",
                "taut.commands.watch",
                "taut.state",
                "taut.watcher",
            },
            False,
        ),
        (
            """
            import contextlib
            import io
            import json
            import sys
            from taut.cli import main
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                assert main(["say", "--help"]) == 0
            print(json.dumps(sorted(sys.modules)))
            """,
            {"taut.commands._rendering", "taut.commands.say"},
            {
                "simplebroker",
                "taut.client",
                "taut.commands._summon_compat",
                "taut.state",
                "taut.watcher",
            },
            True,
        ),
        (
            """
            import contextlib
            import io
            import json
            import sys
            from taut.cli import main
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                assert main(["watch", "--help"]) == 0
            print(json.dumps(sorted(sys.modules)))
            """,
            {"taut.commands._rendering", "taut.commands.watch"},
            {
                "simplebroker",
                "taut.client",
                "taut.commands._summon_compat",
                "taut.state",
                "taut.watcher",
            },
            True,
        ),
    ],
)
def test_fresh_process_import_floors(
    tmp_path: Path,
    source: str,
    required: set[str],
    forbidden: set[str],
    forbid_all_summon: bool,
) -> None:
    modules = _probe_modules(source, cwd=tmp_path)

    assert required <= modules
    assert forbidden.isdisjoint(modules)
    assert SUMMON_RUNTIME_MODULES.isdisjoint(modules)
    if forbid_all_summon:
        assert not any(name.startswith("taut_summon") for name in modules)


def test_lazy_public_values_load_and_cache_only_their_owning_subsystem(
    tmp_path: Path,
) -> None:
    modules = _probe_modules(
        """
        import json
        import sys
        import taut
        client_type = taut.TautClient
        assert taut.__dict__["TautClient"] is client_type
        assert "taut.client" in sys.modules
        assert "taut.watcher" not in sys.modules
        watcher_type = taut.TautWatcher
        assert taut.__dict__["TautWatcher"] is watcher_type
        print(json.dumps(sorted(sys.modules)))
        """,
        cwd=tmp_path,
    )

    assert {"taut.client", "taut.watcher"} <= modules


def test_terminal_text_export_loads_only_its_lightweight_owner(tmp_path: Path) -> None:
    (tmp_path / ".taut.toml").write_text(
        "version = 1\n"
        'backend = "sqlite"\n'
        'target = ".taut.db"\n\n'
        "[terminal_text]\n"
        'escape_patterns = ["PROJECT"]\n',
        encoding="utf-8",
    )
    modules = _probe_modules(
        """
        import json
        import sys
        import taut
        escape = taut.escape_terminal_text
        assert taut.__dict__["escape_terminal_text"] is escape
        assert escape("PROJECT\\x1b") == "\\\\x50\\\\x52\\\\x4f\\\\x4a\\\\x45\\\\x43\\\\x54\\\\x1b"
        print(json.dumps(sorted(sys.modules)))
        """,
        cwd=tmp_path,
    )

    assert "taut.terminal" in modules
    assert {
        "simplebroker",
        "taut.client",
        "taut.commands",
        "taut.state",
        "taut.watcher",
    }.isdisjoint(modules)
    assert not any(name.startswith("taut_summon") for name in modules)


def test_installed_wheel_terminal_text_export_loads_packaged_policy(
    installed_command_fixture: Any,
) -> None:
    project_policy = installed_command_fixture.root / ".taut.toml"
    project_policy.write_text(
        "\n".join(
            (
                "version = 1",
                'backend = "sqlite"',
                'target = ".taut.db"',
                "",
                "[terminal_text]",
                'escape_patterns = ["PROJECT"]',
                "",
            )
        ),
        encoding="utf-8",
    )
    try:
        result = installed_command_fixture.run_python(
            "from importlib import resources; import taut; "
            "policy = resources.files('taut').joinpath('defaults.toml'); "
            "assert policy.is_file(); "
            "assert taut.escape_terminal_text('PROJECT\\x1b') == "
            "'\\\\x50\\\\x52\\\\x4f\\\\x4a\\\\x45\\\\x43"
            "\\\\x54\\\\x1b'"
        )
    finally:
        project_policy.unlink()

    assert result.returncode == 0, result.stderr


def test_sdist_rebuild_installs_terminal_policy_outside_checkout(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    sdist_dir = tmp_path / "sdist"
    sdist_dir.mkdir()
    build_sdist = subprocess.run(
        [uv, "build", "--sdist", "--out-dir", str(sdist_dir), str(PROJECT_ROOT)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert build_sdist.returncode == 0, build_sdist.stderr
    sdists = tuple(sdist_dir.glob("*.tar.gz"))
    assert len(sdists) == 1

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(sdists[0], "r:gz") as archive:
        members = archive.getmembers()
        assert any(member.name.endswith("/taut/defaults.toml") for member in members)
        for member in members:
            destination = (extracted / member.name).resolve()
            assert extracted.resolve() in destination.parents
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                source = archive.extractfile(member)
                assert source is not None
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read())
            else:
                pytest.fail(f"unsupported sdist member type: {member.name}")

    roots = tuple(path for path in extracted.iterdir() if path.is_dir())
    assert len(roots) == 1
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build_wheel = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(wheel_dir), str(roots[0])],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert build_wheel.returncode == 0, build_wheel.stderr
    wheels = tuple(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        assert "taut/defaults.toml" in archive.namelist()

    environment = tmp_path / "environment"
    create_environment = subprocess.run(
        [uv, "venv", "--python", sys.executable, str(environment)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert create_environment.returncode == 0, create_environment.stderr
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    install = subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            str(wheels[0]),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert install.returncode == 0, install.stderr

    probe_root = tmp_path / "probe"
    probe_root.mkdir()
    (probe_root / ".taut.toml").write_text(
        "version = 1\n"
        'backend = "sqlite"\n'
        'target = ".taut.db"\n\n'
        "[terminal_text]\n"
        'escape_patterns = ["PROJECT"]\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    probe = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "from pathlib import Path; import taut; "
            "assert Path(taut.__file__).resolve().is_relative_to(Path.cwd().parent); "
            "assert taut.escape_terminal_text('PROJECT\\x1b') == "
            "'\\\\x50\\\\x52\\\\x4f\\\\x4a\\\\x45\\\\x43"
            "\\\\x54\\\\x1b'",
        ],
        cwd=probe_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr


def test_ordinary_message_execution_does_not_import_watcher_or_summon(
    tmp_path: Path,
) -> None:
    modules = _probe_modules(
        f"""
        import contextlib
        import io
        import json
        import sys
        from taut.cli import main
        db = {str(tmp_path / "chat.db")!r}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert main(["--db", db, "init"]) == 0
            assert main(["--db", db, "--as", "van", "join", "general"]) == 0
            assert main(["--db", db, "--as", "van", "say", "general", "hello"]) == 0
        print(json.dumps(sorted(sys.modules)))
        """,
        cwd=tmp_path,
    )

    assert {"simplebroker", "taut.client", "taut.state"} <= modules
    assert {
        "taut._watch_runtime",
        "taut.client._watching",
        "taut.watcher",
    }.isdisjoint(modules)
    assert not any(name.startswith("taut_summon") for name in modules)


def test_watch_selection_loads_only_the_watcher_runtime(
    tmp_path: Path,
) -> None:
    modules = _probe_modules(
        f"""
        import contextlib
        import io
        import json
        import sys
        from taut.cli import main
        db = {str(tmp_path / "chat.db")!r}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert main(["--db", db, "init"]) == 0
            assert main(["--db", db, "--as", "van", "join", "general"]) == 0
            assert main(["--db", db, "--as", "van", "watch", "missing"]) == 2
        print(json.dumps(sorted(sys.modules)))
        """,
        cwd=tmp_path,
    )

    assert {
        "taut._watch_runtime",
        "taut.client._watching",
        "taut.watcher",
    } <= modules
    assert not any(name.startswith("taut_summon") for name in modules)


def test_installed_core_selection_skips_unrelated_manifest_but_help_and_reserved_do_not(
    installed_command_fixture: Any,
) -> None:
    core = installed_command_fixture.run_python(
        "import contextlib, io, sys, tempfile; from pathlib import Path; "
        "from taut.cli import main; "
        "out=io.StringIO(); err=io.StringIO(); "
        "db=str(Path(tempfile.mkdtemp()) / 'chat.db'); "
        "ctx=contextlib.ExitStack(); ctx.enter_context(contextlib.redirect_stdout(out)); "
        "ctx.enter_context(contextlib.redirect_stderr(err)); "
        "assert main(['--version']) == 0; "
        "assert main(['--db', db, 'init']) == 0; "
        "assert main(['--db', db, '--as', 'van', 'join', 'general']) == 0; "
        "assert main(['--db', db, '--as', 'van', 'say', 'general', 'hello']) == 0; "
        "ctx.close(); "
        "assert 'taut_command_plugin.manifest' not in sys.modules; "
        "assert 'taut_command_plugin.command' not in sys.modules"
    )
    assert core.returncode == 0, core.stderr

    help_result = installed_command_fixture.run_python(
        "import contextlib, io, sys; from taut.cli import main; "
        "out=io.StringIO(); err=io.StringIO(); "
        "ctx=contextlib.ExitStack(); ctx.enter_context(contextlib.redirect_stdout(out)); "
        "ctx.enter_context(contextlib.redirect_stderr(err)); "
        "rc=main(['--help']); ctx.close(); "
        "assert rc == 0; "
        "assert 'taut_command_plugin.manifest' in sys.modules; "
        "assert 'taut_command_plugin.command' not in sys.modules"
    )
    assert help_result.returncode == 0, help_result.stderr

    reserved = installed_command_fixture.run_python(
        "import contextlib, io, sys; from taut.cli import main; "
        "out=io.StringIO(); err=io.StringIO(); "
        "ctx=contextlib.ExitStack(); ctx.enter_context(contextlib.redirect_stdout(out)); "
        "ctx.enter_context(contextlib.redirect_stderr(err)); "
        "rc=main(['summon', 'claude']); ctx.close(); "
        "assert rc == 1; "
        "assert 'taut_command_plugin.manifest' in sys.modules"
    )
    assert reserved.returncode == 0, reserved.stderr
