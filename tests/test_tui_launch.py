"""Launch and import-boundary tests for the Taut TUI.

Spec: docs/specs/04-taut-tui.md [TUI-4.1], [TUI-4.3], [TUI-5].
Plan: docs/plans/2026-07-02-taut-tui-implementation-plan.md Tasks 0-1
(INV-5, INV-6; import-boundary proof runs in a subprocess per finding R3-6).
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_import_probe(statement: str) -> None:
    """Prove `statement` executes without pulling textual into sys.modules.

    Runs in a subprocess: an in-process check is order-dependent once any
    other test has imported Textual into the shared interpreter (finding
    R3-6).
    """

    code = (
        "import sys\n"
        f"{statement}\n"
        "assert 'textual' not in sys.modules, 'textual was imported eagerly'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"import probe failed for {statement!r}:\n{result.stderr}"
    )


class TestImportBoundary:
    """INV-6: no normal import path pulls in Textual ([TUI-4.3])."""

    def test_import_taut_and_cli_does_not_import_textual(self) -> None:
        _run_import_probe("import taut; import taut.cli")

    def test_import_taut_tui_does_not_import_textual(self) -> None:
        _run_import_probe("import taut.tui")

    def test_launch_module_importable_without_textual(self) -> None:
        _run_import_probe("from taut.tui._launch import MissingTuiExtraError")


class TestMissingExtra:
    """[TUI-5.1]: a missing extra is a clean, specific error."""

    def test_run_tui_raises_missing_extra_when_textual_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from taut.tui import MissingTuiExtraError, run_tui

        # None in sys.modules makes `import textual` raise ImportError,
        # simulating an uninstalled extra without touching the venv.
        monkeypatch.setitem(sys.modules, "textual", None)
        with pytest.raises(MissingTuiExtraError) as excinfo:
            run_tui()
        assert "taut[tui]" in str(excinfo.value)

    def test_broken_textual_install_is_not_reported_as_missing_extra(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from taut.tui import run_tui

        # Slice-review finding (Task 1): textual installed but broken — its
        # import dies on a missing transitive dependency. That is a real
        # bug, not a missing extra; the hint would send users on a useless
        # reinstall. Python drops the failed module from sys.modules
        # automatically, so the fake does not leak to other tests.
        fake = tmp_path / "textual.py"
        fake.write_text("import definitely_missing_dep_xyz\n")
        monkeypatch.delitem(sys.modules, "textual", raising=False)
        monkeypatch.syspath_prepend(str(tmp_path))
        with pytest.raises(ModuleNotFoundError, match="definitely_missing_dep_xyz"):
            run_tui()

    def test_missing_extra_error_is_not_an_importerror(self) -> None:
        from taut.tui._launch import MissingTuiExtraError

        # Guards findings 6 + R2-3: the launch site catches only this type,
        # so a genuine ImportError from a broken TUI submodule must not be
        # swallowed as "extra not installed".
        assert not issubclass(MissingTuiExtraError, ImportError)


class _RunTuiSpy:
    """Records run_tui invocations; the dispatch, not the app, is under test."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    def __call__(
        self,
        *,
        db_path: str | None = None,
        as_name: str | None = None,
        token: str | None = None,
    ) -> int:
        self.calls.append({"db_path": db_path, "as_name": as_name, "token": token})
        return 0


@pytest.fixture
def tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make both stdio ends look interactive ([TUI-5.3] predicates)."""

    monkeypatch.setattr("taut.tui._launch.stdin_isatty", lambda: True)
    monkeypatch.setattr("taut.tui._launch.stdout_isatty", lambda: True)


@pytest.fixture
def run_tui_spy(monkeypatch: pytest.MonkeyPatch) -> _RunTuiSpy:
    spy = _RunTuiSpy()
    monkeypatch.setattr("taut.tui.run_tui", spy)
    return spy


class TestLaunchDispatch:
    """[TUI-5] dispatch through the real main() entry (INV-1..4)."""

    def test_verb_present_runs_cli_never_tui(
        self, tty: None, run_tui_spy: _RunTuiSpy, tmp_path: Path
    ) -> None:
        from taut.cli import main

        rc = main(["--db", str(tmp_path / "absent.db"), "list"])
        assert rc != 0  # no db: the CLI errors, but through the CLI path
        assert run_tui_spy.calls == []

    @pytest.mark.parametrize("flag", ["--help", "--version"])
    def test_help_and_version_stay_argparse_actions(
        self, tty: None, run_tui_spy: _RunTuiSpy, flag: str
    ) -> None:
        from taut.cli import main

        with pytest.raises(SystemExit) as excinfo:
            main([flag])
        assert excinfo.value.code == 0
        assert run_tui_spy.calls == []

    def test_main_empty_list_is_bare_taut(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from taut.cli import main

        # Regression for review finding 1: `argv or sys.argv[1:]` leaked the
        # process argv when argv == []. With a verb in sys.argv, main([])
        # must still be a bare invocation (help + exit 1 in non-tty).
        monkeypatch.setattr(sys, "argv", ["taut", "--version"])
        monkeypatch.setattr("taut.tui._launch.stdin_isatty", lambda: False)
        monkeypatch.setattr("taut.tui._launch.stdout_isatty", lambda: False)
        rc = main([])
        assert rc == 1
        assert "usage: taut" in capsys.readouterr().out

    def test_bare_tty_launches_tui_with_none_kwargs(
        self, tty: None, run_tui_spy: _RunTuiSpy
    ) -> None:
        from taut.cli import main

        assert main([]) == 0
        assert run_tui_spy.calls == [{"db_path": None, "as_name": None, "token": None}]

    @pytest.mark.parametrize("which", ["stdin", "stdout"])
    def test_bare_non_tty_prints_help_exits_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        run_tui_spy: _RunTuiSpy,
        capsys: pytest.CaptureFixture[str],
        which: str,
    ) -> None:
        from taut.cli import main

        # INV-3: agents never hang — either non-tty end forces the CLI path.
        monkeypatch.setattr("taut.tui._launch.stdin_isatty", lambda: which != "stdin")
        monkeypatch.setattr("taut.tui._launch.stdout_isatty", lambda: which != "stdout")
        rc = main([])
        assert rc == 1
        assert "usage: taut" in capsys.readouterr().out
        assert run_tui_spy.calls == []

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["--db", "X"], {"db_path": "X", "as_name": None, "token": None}),
            (["--db=X"], {"db_path": "X", "as_name": None, "token": None}),
            (["--as", "van"], {"db_path": None, "as_name": "van", "token": None}),
            (["--token", "T1"], {"db_path": None, "as_name": None, "token": "T1"}),
        ],
    )
    def test_accepted_globals_launch_configured_tui(
        self,
        tty: None,
        run_tui_spy: _RunTuiSpy,
        argv: list[str],
        expected: dict[str, str | None],
    ) -> None:
        from taut.cli import main

        # INV-4 accepted set, one firing test per element (finding R3-11),
        # plus the equals-form spelling argparse already accepts for verbs
        # (finding R4-4).
        assert main(argv) == 0
        assert run_tui_spy.calls == [expected]

    @pytest.mark.parametrize("flag", ["--json", "-t", "--timestamps", "-q", "--quiet"])
    def test_output_only_flags_never_launch(
        self,
        tty: None,
        run_tui_spy: _RunTuiSpy,
        capsys: pytest.CaptureFixture[str],
        flag: str,
    ) -> None:
        from taut.cli import main

        # INV-4 excluded set: output flags are meaningless interactively.
        rc = main([flag])
        assert rc == 1
        assert "usage: taut" in capsys.readouterr().out
        assert run_tui_spy.calls == []

    def test_missing_extra_prints_hint_and_exits_1(
        self,
        tty: None,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from taut.cli import main

        # Real run_tui, simulated absent textual: the probe raises
        # MissingTuiExtraError, which is the only thing the CLI translates
        # into the [TUI-5.1] hint.
        monkeypatch.setitem(sys.modules, "textual", None)
        rc = main([])
        assert rc == 1
        err = capsys.readouterr().err
        for fragment in ("taut[tui]", "pipx inject", "taut list", "taut watch"):
            assert fragment in err

    def test_real_importerror_is_not_swallowed(
        self, tty: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from taut.cli import main

        # Negative test for finding R2-3: only MissingTuiExtraError becomes
        # the install hint; a genuine ImportError from the TUI is a real bug
        # and must propagate.
        def broken(**_: object) -> int:
            raise ImportError("broken taut.tui submodule")

        monkeypatch.setattr("taut.tui.run_tui", broken)
        with pytest.raises(ImportError, match="broken taut.tui submodule"):
            main([])


class TestPackaging:
    """INV-5: Textual stays behind the extras; build ships TUI files."""

    def _pyproject(self) -> dict[str, object]:
        with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
            return tomllib.load(fh)

    def test_textual_only_in_optional_extras(self) -> None:
        data = self._pyproject()
        project = data["project"]
        assert isinstance(project, dict)
        core = [str(dep) for dep in project["dependencies"]]
        assert not any("textual" in dep for dep in core), (
            "textual must never enter [project.dependencies] (INV-5)"
        )
        extras = project["optional-dependencies"]
        assert isinstance(extras, dict)
        assert any("textual" in str(dep) for dep in extras["tui"])
        assert any("textual" in str(dep) for dep in extras["dev"])

    def test_hatch_build_ships_tcss(self) -> None:
        data = self._pyproject()
        tool = data["tool"]
        assert isinstance(tool, dict)
        include = tool["hatch"]["build"]["include"]
        assert any(".tcss" in str(entry) for entry in include), (
            "Textual CSS files under taut/tui/ must ship in the build"
        )
