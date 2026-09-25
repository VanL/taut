"""Installed-wheel fixtures for the separately distributed TUI extension."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _record_tui_phases(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Observe real owner phases only when the hosted recorder opts in."""

    directory = os.environ.get("TAUT_TUI_PHASE_DIR")
    if not directory:
        yield
        return

    from _phase_evidence import PhaseEvidence, install_phase_observers

    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    identity = hashlib.sha256(f"{worker}:{request.node.nodeid}".encode()).hexdigest()
    path = Path(directory) / f"{identity}.jsonl"
    kind = {
        "test_direct_message_header_and_composer_use_actor_scoped_label": "navigation",
        "test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes": "recovery",
    }.get(request.node.name, "other")
    evidence = PhaseEvidence(path)
    try:
        # Use the test's shared patch stack: later test patches must undo
        # before these wrappers, or they can restore a disposed observer.
        install_phase_observers(monkeypatch, evidence, gate_module=request.module)
        yield
    finally:
        evidence.close(test_kind=kind)


@pytest.fixture(autouse=True)
def _isolate_ambient_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep ``db_path=None`` pilots independent of a developer's workspace DB."""

    monkeypatch.setenv("TAUT_DB", str(tmp_path / "ambient.db"))


@dataclass(frozen=True, slots=True)
class InstalledTuiFixture:
    """Fresh environment plus the paired core and TUI wheels."""

    python: Path
    root: Path
    core_wheel: Path
    tui_wheel: Path

    def create_isolated(self, root: Path) -> InstalledTuiFixture:
        """Create a core-only environment for explicit extension installation."""

        python = _install_environment(root, self.core_wheel)
        return InstalledTuiFixture(
            python=python,
            root=root,
            core_wheel=self.core_wheel,
            tui_wheel=self.tui_wheel,
        )

    def install_wheels(self, *wheels: Path) -> subprocess.CompletedProcess[str]:
        """Install additional local artifacts without consulting the checkout."""

        uv = _uv()
        return subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(self.python),
                *(str(wheel) for wheel in wheels),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )

    def run_python(self, code: str) -> subprocess.CompletedProcess[str]:
        """Run Python with no checkout import path."""

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            [str(self.python), "-c", code],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )


def _uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for installed TUI tests")
    return uv


def _install_environment(root: Path, *wheels: Path) -> Path:
    uv = _uv()
    root.mkdir(parents=True, exist_ok=True)
    venv = root / "venv"
    subprocess.run(
        [uv, "venv", "--python", sys.executable, str(venv)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    python = (
        venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"
    )
    subprocess.run(
        [uv, "pip", "install", "--python", str(python), *(str(w) for w in wheels)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return python


@pytest.fixture(scope="session")
def installed_command_fixture(
    tmp_path_factory: pytest.TempPathFactory,
) -> InstalledTuiFixture:
    """Build paired artifacts and start with a checkout-free core-only install."""

    uv = _uv()
    root = tmp_path_factory.mktemp("installed-tui-fixture")
    core_dist = root / "core-dist"
    tui_dist = root / "tui-dist"
    for source, destination in (
        (REPOSITORY_ROOT, core_dist),
        (REPOSITORY_ROOT / "extensions" / "taut_tui", tui_dist),
    ):
        subprocess.run(
            [uv, "build", "--wheel", "--out-dir", str(destination), str(source)],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    core_wheels = tuple(core_dist.glob("*.whl"))
    tui_wheels = tuple(tui_dist.glob("*.whl"))
    if len(core_wheels) != 1 or len(tui_wheels) != 1:
        raise RuntimeError(
            "installed TUI fixture requires exactly one wheel per package"
        )
    python = _install_environment(root, core_wheels[0])
    return InstalledTuiFixture(
        python=python,
        root=root,
        core_wheel=core_wheels[0],
        tui_wheel=tui_wheels[0],
    )
