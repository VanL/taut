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

    def test_missing_extra_error_is_not_an_importerror(self) -> None:
        from taut.tui._launch import MissingTuiExtraError

        # Guards findings 6 + R2-3: the launch site catches only this type,
        # so a genuine ImportError from a broken TUI submodule must not be
        # swallowed as "extra not installed".
        assert not issubclass(MissingTuiExtraError, ImportError)


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
