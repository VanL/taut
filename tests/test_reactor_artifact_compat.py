"""Focused [SUM-12] checks for the installed-artifact compatibility gate."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFIER = PROJECT_ROOT / "bin" / "verify-reactor-artifact-compat.py"
RELEASE_ARTIFACT_BUILDER = PROJECT_ROOT / "bin" / "verify-reactor-release-artifacts.py"

pytestmark = pytest.mark.shared


@pytest.fixture
def verifier_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "taut_reactor_artifact_verifier", VERIFIER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release_artifact_builder_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "taut_reactor_release_artifact_builder", RELEASE_ARTIFACT_BUILDER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _select_site_packages(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.name.casefold() in {"site-packages", "dist-packages"}:
            return candidate
    rendered = ", ".join(str(candidate) for candidate in candidates) or "<none>"
    raise RuntimeError(
        "virtual environment reported no site-packages or dist-packages "
        f"directory; candidates: {rendered}"
    )


def test_select_site_packages_ignores_venv_prefix_entry(tmp_path: Path) -> None:
    prefix = tmp_path / "isolated"
    site_packages = prefix / "Lib" / "site-packages"

    assert _select_site_packages([prefix, site_packages]) == site_packages


def test_select_site_packages_rejects_missing_package_directory(
    tmp_path: Path,
) -> None:
    prefix = tmp_path / "isolated"

    with pytest.raises(RuntimeError, match="no site-packages or dist-packages"):
        _select_site_packages([prefix])


def _make_venv(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "isolated"
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(root)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    python = root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    completed = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import json, site; print(json.dumps(site.getsitepackages()))",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    candidates = [Path(item) for item in json.loads(completed.stdout)]
    return root, python, _select_site_packages(candidates)


def _write_distribution(site_packages: Path, *, name: str, version: str) -> None:
    dist_info = site_packages / f"{name.replace('-', '_')}-{version}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )


def _write_fake_taut(site_packages: Path) -> None:
    package = site_packages / "taut"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "watcher.py").write_text(
        """
class TautBaseWatcher:
    def __init__(self, *_args, **_kwargs):
        if type(self).process_once is not TautBaseWatcher.process_once:
            raise RuntimeError("upgrade taut-summon")

    def process_once(self):
        return None
""".lstrip(),
        encoding="utf-8",
    )
    _write_distribution(site_packages, name="taut", version="0.6.0")


def _write_wheel(
    path: Path, *, name: str, version: str, requirements: tuple[str, ...]
) -> Path:
    metadata = [
        "Metadata-Version: 2.3",
        f"Name: {name}",
        f"Version: {version}",
        *(f"Requires-Dist: {requirement}" for requirement in requirements),
        "",
        "",
    ]
    dist_info = name.replace("-", "_")
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr(f"{dist_info}-{version}.dist-info/METADATA", "\n".join(metadata))
    return path


def _run_verifier(
    tmp_path: Path, core: Path, summon: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--new-core",
            str(core),
            "--new-summon",
            str(summon),
            "--previous-core-ref",
            "v0.5.0",
            "--previous-summon-ref",
            "taut_summon/v0.5.0",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )


def test_release_artifact_builder_uses_fresh_separate_wheel_outputs(
    release_artifact_builder_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = release_artifact_builder_module
    commands: list[tuple[str, ...]] = []
    output_dirs: list[Path] = []

    def fake_run(command: tuple[str, ...]) -> None:
        commands.append(command)
        if command[1:3] == ("build", "--wheel"):
            output = Path(command[command.index("--out-dir") + 1])
            output_dirs.append(output)
            assert output.is_dir()
            assert list(output.iterdir()) == []
            assert output.name in {"core", "summon"}
            wheel_name = (
                "taut-0.6.0-py3-none-any.whl"
                if output.name == "core"
                else "taut_summon-0.6.0-py3-none-any.whl"
            )
            (output / wheel_name).touch()
            return
        if command[1:3] == ("pip", "compile"):
            output = Path(command[command.index("--output-file") + 1])
            output.write_text("simplebroker-pg==3.2.0\n", encoding="utf-8")
            return
        assert command[:2] == (sys.executable, str(VERIFIER))
        core = Path(command[command.index("--new-core") + 1])
        summon = Path(command[command.index("--new-summon") + 1])
        assert core.parent == output_dirs[0]
        assert summon.parent == output_dirs[1]
        assert core.parent != summon.parent
        assert core.is_file() and summon.is_file()
        assert command[command.index("--previous-core-ref") + 1] == "v0.5.0"
        assert (
            command[command.index("--previous-summon-ref") + 1] == "taut_summon/v0.5.0"
        )

    monkeypatch.setattr(builder, "_run", fake_run)

    builder.build_and_verify()

    assert len(commands) == 4
    assert all("dist" not in part for command in commands for part in command)


def test_release_artifact_builder_requires_exactly_one_wheel_per_output(
    release_artifact_builder_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = release_artifact_builder_module
    commands: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...]) -> None:
        commands.append(command)
        output = Path(command[command.index("--out-dir") + 1])
        (output / "first.whl").touch()
        (output / "second.whl").touch()

    monkeypatch.setattr(builder, "_run", fake_run)

    with pytest.raises(
        builder.ArtifactBuildError,
        match="core build produced 2 wheels; expected exactly one",
    ):
        builder.build_and_verify()

    assert len(commands) == 1


def test_release_artifact_builder_dry_run_prints_build_build_verify_order(
    release_artifact_builder_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    builder = release_artifact_builder_module
    monkeypatch.setattr(
        builder,
        "_run",
        lambda _command: pytest.fail("dry-run must not execute a command"),
    )

    builder.build_and_verify(dry_run=True)

    output = capsys.readouterr().out
    core_build = output.index("uv build --wheel")
    summon_build = output.index("uv build --wheel", core_build + 1)
    pg_resolution = output.index("uv pip compile")
    verify = output.index("verify-reactor-artifact-compat.py")
    assert core_build < summon_build < pg_resolution < verify
    assert "--new-core" in output
    assert "--new-summon" in output
    assert "v0.5.0" in output
    assert "taut_summon/v0.5.0" in output


def test_release_artifact_builder_cli_accepts_dry_run(
    release_artifact_builder_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = release_artifact_builder_module
    calls: list[bool] = []
    monkeypatch.setattr(
        builder,
        "build_and_verify",
        lambda *, dry_run=False: calls.append(dry_run),
    )

    assert builder.main(["--dry-run"]) == 0
    assert calls == [True]


def test_release_artifact_builder_reports_spawn_error_without_traceback(
    release_artifact_builder_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    builder = release_artifact_builder_module
    monkeypatch.setattr(
        builder.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("spawn denied")),
    )

    assert builder.main([]) == 1
    error = capsys.readouterr().err
    assert "spawn denied" in error
    assert "Traceback" not in error
    assert len(error.splitlines()) == 1


def test_release_artifact_builder_rejects_retained_summon_lock_below_floor(
    tmp_path: Path,
    release_artifact_builder_module: ModuleType,
) -> None:
    builder = release_artifact_builder_module
    lock = tmp_path / "uv.lock"
    lock.write_text(
        'version = 1\n[[package]]\nname = "simplebroker"\nversion = "5.2.2"\n',
        encoding="utf-8",
    )

    with pytest.raises(
        builder.ArtifactBuildError,
        match="retained Summon lock resolved simplebroker 5.2.2 below 5.3.0",
    ):
        builder._verify_retained_summon_lock(lock)  # noqa: SLF001


def test_release_artifact_builder_rejects_resolved_pg_plugin_below_floor(
    tmp_path: Path,
    release_artifact_builder_module: ModuleType,
) -> None:
    builder = release_artifact_builder_module
    requirements = tmp_path / "pg-requirements.txt"
    requirements.write_text("simplebroker-pg==3.1.1\n", encoding="utf-8")

    with pytest.raises(
        builder.ArtifactBuildError,
        match="ephemeral PG resolution selected simplebroker-pg 3.1.1 below 3.2.0",
    ):
        builder._verify_pg_resolution(requirements)  # noqa: SLF001


@pytest.mark.parametrize(
    ("dependencies", "expected"),
    [
        (
            ("taut>=0.5.0", "simplebroker-pg>=3.2.0"),
            "taut>=X.Y.Z with X.Y.Z >= 0.5.1",
        ),
        (
            ("taut>=0.5.1", "simplebroker-pg>=3.1.1"),
            "simplebroker-pg>=X.Y.Z with X.Y.Z >= 3.2.0",
        ),
    ],
)
def test_release_artifact_builder_rejects_weak_pg_manifest_floors(
    tmp_path: Path,
    release_artifact_builder_module: ModuleType,
    dependencies: tuple[str, str],
    expected: str,
) -> None:
    builder = release_artifact_builder_module
    manifest = tmp_path / "pyproject.toml"
    rendered = ",\n".join(f'    "{dependency}"' for dependency in dependencies)
    manifest.write_text(
        f"[project]\ndependencies = [\n{rendered}\n]\n",
        encoding="utf-8",
    )

    with pytest.raises(builder.ArtifactBuildError, match=expected):
        builder._verify_pg_manifest(manifest)  # noqa: SLF001


def test_release_artifact_builder_accepts_required_pg_manifest_floors(
    tmp_path: Path,
    release_artifact_builder_module: ModuleType,
) -> None:
    builder = release_artifact_builder_module
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text(
        '[project]\ndependencies = ["taut>=0.5.1", "simplebroker-pg>=3.2.0"]\n',
        encoding="utf-8",
    )

    builder._verify_pg_manifest(manifest)  # noqa: SLF001


def test_release_artifact_builder_checks_retained_and_ephemeral_floors(
    release_artifact_builder_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = release_artifact_builder_module
    events: list[str] = []

    def fake_run(command: tuple[str, ...]) -> None:
        if command[1:3] == ("build", "--wheel"):
            output = Path(command[command.index("--out-dir") + 1])
            wheel = "taut.whl" if output.name == "core" else "taut_summon.whl"
            (output / wheel).touch()
            events.append(f"build:{output.name}")
            return
        if command[1:3] == ("pip", "compile"):
            output = Path(command[command.index("--output-file") + 1])
            output.write_text("simplebroker-pg==3.2.0\n", encoding="utf-8")
            events.append("resolve:pg")
            return
        events.append("verify:artifacts")

    monkeypatch.setattr(builder, "_run", fake_run)
    monkeypatch.setattr(
        builder,
        "_verify_pg_manifest",
        lambda: events.append("verify:pg-manifest"),
    )
    monkeypatch.setattr(
        builder,
        "_verify_retained_summon_lock",
        lambda: events.append("verify:summon-lock"),
    )

    def verify_pg(path: Path) -> None:
        assert "simplebroker-pg==3.2.0" in path.read_text(encoding="utf-8")
        events.append("verify:pg-floor")

    monkeypatch.setattr(builder, "_verify_pg_resolution", verify_pg)

    builder.build_and_verify()

    assert events == [
        "verify:pg-manifest",
        "verify:summon-lock",
        "build:core",
        "build:summon",
        "resolve:pg",
        "verify:pg-floor",
        "verify:artifacts",
    ]


def test_verifier_reports_missing_wheel_without_traceback(tmp_path: Path) -> None:
    missing_core = tmp_path / "missing-core.whl"
    missing_summon = tmp_path / "missing-summon.whl"

    completed = _run_verifier(tmp_path, missing_core, missing_summon)

    assert completed.returncode == 1
    assert "new core wheel does not exist" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_verifier_rejects_core_without_simplebroker_5_3_0_floor(
    tmp_path: Path,
) -> None:
    core = _write_wheel(
        tmp_path / "taut-0.6.0-py3-none-any.whl",
        name="taut",
        version="0.6.0",
        requirements=("simplebroker>=5.1.1", "psutil>=6.0"),
    )
    summon = _write_wheel(
        tmp_path / "taut_summon-0.6.0-py3-none-any.whl",
        name="taut-summon",
        version="0.6.0",
        requirements=("taut>=0.6.0",),
    )

    completed = _run_verifier(tmp_path, core, summon)

    assert completed.returncode == 1
    assert "simplebroker>=X.Y.Z" in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize(
    "requirements",
    [
        ("simplebroker>=5.2.2", "psutil>=6.0"),
        ("simplebroker==5.3.0", "psutil>=6.0"),
        ("simplebroker~=5.3.0", "psutil>=6.0"),
        ("simplebroker>=5.3.0,<6", "psutil>=6.0"),
        ('simplebroker>=5.3.0; python_version >= "3.11"', "psutil>=6.0"),
        ("simplebroker>=5.3.0", "simplebroker>=5.3.1", "psutil>=6.0"),
    ],
)
def test_verifier_rejects_unsupported_simplebroker_requirement_grammar(
    tmp_path: Path,
    requirements: tuple[str, ...],
) -> None:
    core = _write_wheel(
        tmp_path / "taut-0.6.0-py3-none-any.whl",
        name="taut",
        version="0.6.0",
        requirements=requirements,
    )
    summon = _write_wheel(
        tmp_path / "taut_summon-0.6.0-py3-none-any.whl",
        name="taut-summon",
        version="0.6.0",
        requirements=("taut>=0.6.0",),
    )

    completed = _run_verifier(tmp_path, core, summon)

    assert completed.returncode == 1
    assert "exactly one unmarked simplebroker>=X.Y.Z" in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize("floor", ("5.3.0", "5.3.1", "6.0.0"))
def test_verifier_accepts_supported_simplebroker_floor_grammar(
    tmp_path: Path,
    verifier_module: ModuleType,
    floor: str,
) -> None:
    core = verifier_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / f"taut-0.6.0-{floor}-py3-none-any.whl",
            name="taut",
            version="0.6.0",
            requirements=(f"simplebroker>={floor}", "psutil>=6.0"),
        )
    )
    summon = verifier_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / f"taut_summon-0.6.0-{floor}-py3-none-any.whl",
            name="taut-summon",
            version="0.6.0",
            requirements=("taut>=0.6.0",),
        )
    )

    verifier_module._validate_new_metadata(core, summon)


def test_verifier_rejects_summon_without_exact_new_core_floor(
    tmp_path: Path,
) -> None:
    core = _write_wheel(
        tmp_path / "taut-0.6.0-py3-none-any.whl",
        name="taut",
        version="0.6.0",
        requirements=("simplebroker>=5.3.0", "psutil>=6.0"),
    )
    summon = _write_wheel(
        tmp_path / "taut_summon-0.6.0-py3-none-any.whl",
        name="taut-summon",
        version="0.6.0",
        requirements=("taut>=0.5.0",),
    )

    completed = _run_verifier(tmp_path, core, summon)

    assert completed.returncode == 1
    assert "taut>=0.6.0" in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize(
    "requirements",
    [
        ("taut>=0.6.1",),
        ("taut==0.6.0",),
        ("taut>=0.6.0,<1",),
        ('taut>=0.6.0; python_version >= "3.11"',),
        ("taut>=0.6.0", "taut>=0.6.0"),
    ],
)
def test_verifier_rejects_nonexact_or_duplicate_taut_requirement(
    tmp_path: Path,
    verifier_module: ModuleType,
    requirements: tuple[str, ...],
) -> None:
    core = verifier_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut-0.6.0-py3-none-any.whl",
            name="taut",
            version="0.6.0",
            requirements=("simplebroker>=5.3.0", "psutil>=6.0"),
        )
    )
    summon = verifier_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut_summon-0.6.0-py3-none-any.whl",
            name="taut-summon",
            version="0.6.0",
            requirements=requirements,
        )
    )

    with pytest.raises(
        verifier_module.VerificationError,
        match="exactly one unmarked Requires-Dist 'taut>=0.6.0'",
    ):
        verifier_module._validate_new_metadata(core, summon)


def test_python_probe_rejects_checkout_path_from_site_packages(
    tmp_path: Path, verifier_module: ModuleType
) -> None:
    _root, python, site_packages = _make_venv(tmp_path)
    (site_packages / "checkout-leak.pth").write_text(
        f"{PROJECT_ROOT}\n", encoding="utf-8"
    )

    with pytest.raises(
        verifier_module.VerificationError, match="checkout path leaked into sys.path"
    ):
        verifier_module._run_python_probe(
            python=python,
            code='raise SystemExit("case body must not run")',
            cwd=tmp_path,
            env=verifier_module._clean_environment(),
        )


def test_prior_tags_are_fetched_into_temporary_archive_repository(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init"], cwd=origin, capture_output=True, check=True)
    (origin / "artifact.txt").write_text("immutable\n", encoding="utf-8")
    git_env = os.environ.copy()
    git_env.update(
        {
            "GIT_AUTHOR_NAME": "artifact test",
            "GIT_AUTHOR_EMAIL": "artifact@example.invalid",
            "GIT_COMMITTER_NAME": "artifact test",
            "GIT_COMMITTER_EMAIL": "artifact@example.invalid",
        }
    )
    subprocess.run(["git", "add", "artifact.txt"], cwd=origin, check=True)
    subprocess.run(
        ["git", "commit", "-m", "artifact fixture"],
        cwd=origin,
        env=git_env,
        capture_output=True,
        check=True,
    )
    for ref in ("v0.5.0", "taut_summon/v0.5.0"):
        subprocess.run(["git", "tag", ref], cwd=origin, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(origin)], cwd=origin, check=True
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=origin,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    monkeypatch.setattr(verifier_module, "PROJECT_ROOT", origin)
    monkeypatch.setattr(verifier_module, "EXPECTED_PREVIOUS_COMMIT", commit)

    archive_repository = verifier_module._prepare_archive_repository(
        refs=("v0.5.0", "taut_summon/v0.5.0"),
        work=tmp_path,
        env=verifier_module._clean_environment(),
    )

    assert archive_repository.is_dir()
    resolved = subprocess.run(
        [
            "git",
            f"--git-dir={archive_repository}",
            "rev-parse",
            "refs/tags/taut_summon/v0.5.0^{commit}",
        ],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert resolved == commit


def test_command_interrupt_terminates_owned_process_group(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InterruptingProcess:
        pid = 12345
        returncode = -2

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            raise KeyboardInterrupt

    process = InterruptingProcess()
    terminated: list[object] = []
    monkeypatch.setattr(
        verifier_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        verifier_module,
        "_terminate_owned_process_group",
        lambda owned: terminated.append(owned),
    )

    with pytest.raises(KeyboardInterrupt):
        verifier_module._run(
            ["long-running-command"],
            cwd=tmp_path,
            env=verifier_module._clean_environment(),
        )

    assert terminated == [process]


def test_new_core_case_rejects_resolved_simplebroker_below_5_3_0(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, python, site_packages = _make_venv(tmp_path)
    _write_fake_taut(site_packages)
    _write_distribution(site_packages, name="simplebroker", version="5.1.1")
    monkeypatch.setattr(
        verifier_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, python),
    )
    monkeypatch.setattr(verifier_module, "_install", lambda **_kwargs: None)

    with pytest.raises(
        verifier_module.VerificationError, match="SimpleBroker below 5.3.0 resolved"
    ):
        verifier_module._case_new_core(
            wheel=tmp_path / "unused.whl",
            work=tmp_path,
            env=verifier_module._clean_environment(),
            uv="uv",
        )


def test_new_core_case_accepts_guard_with_simplebroker_5_3_0(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _root, python, site_packages = _make_venv(tmp_path)
    _write_fake_taut(site_packages)
    _write_distribution(site_packages, name="simplebroker", version="5.3.0")
    monkeypatch.setattr(
        verifier_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, python),
    )
    monkeypatch.setattr(verifier_module, "_install", lambda **_kwargs: None)

    verifier_module._case_new_core(
        wheel=tmp_path / "unused.whl",
        work=tmp_path,
        env=verifier_module._clean_environment(),
        uv="uv",
    )

    output = capsys.readouterr().out
    assert '"simplebroker": "5.3.0"' in output
    assert '"guard": "rejected_before_broker_io"' in output


def test_prior_summon_case_records_absent_legacy_reactor_surface(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _root, python, site_packages = _make_venv(tmp_path)
    _write_fake_taut(site_packages)
    _write_distribution(site_packages, name="simplebroker", version="5.3.0")
    summon = site_packages / "taut_summon"
    summon.mkdir()
    (summon / "__init__.py").write_text("", encoding="utf-8")
    (summon / "_control.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        verifier_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, python),
    )
    monkeypatch.setattr(verifier_module, "_install", lambda **_kwargs: None)

    verifier_module._case_new_core_prior_summon(
        new_core=tmp_path / "unused-core.whl",
        previous_summon=tmp_path / "unused-summon.whl",
        work=tmp_path,
        env=verifier_module._clean_environment(),
        uv="uv",
    )

    assert '"legacy_reactor_surface": "absent"' in capsys.readouterr().out


def test_prior_summon_case_rejects_exposed_reactor_that_bypasses_guard(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, python, site_packages = _make_venv(tmp_path)
    _write_fake_taut(site_packages)
    _write_distribution(site_packages, name="simplebroker", version="5.3.0")
    summon = site_packages / "taut_summon"
    summon.mkdir()
    (summon / "__init__.py").write_text("", encoding="utf-8")
    (summon / "_control.py").write_text(
        "class _ControlReactor:\n"
        "    def __init__(self, _owner, *, db, config):\n"
        "        return None\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        verifier_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, python),
    )
    monkeypatch.setattr(verifier_module, "_install", lambda **_kwargs: None)

    with pytest.raises(
        verifier_module.VerificationError,
        match="prior Summon reactor construction was accepted",
    ):
        verifier_module._case_new_core_prior_summon(
            new_core=tmp_path / "unused-core.whl",
            previous_summon=tmp_path / "unused-summon.whl",
            work=tmp_path,
            env=verifier_module._clean_environment(),
            uv="uv",
        )


def test_paired_case_installs_both_wheels_and_runs_full_control_probe(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    core = tmp_path / "taut.whl"
    summon = tmp_path / "taut_summon.whl"
    installed: list[tuple[Path, ...]] = []
    monkeypatch.setattr(
        verifier_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, tmp_path / "python"),
    )
    monkeypatch.setattr(
        verifier_module,
        "_install",
        lambda **kwargs: installed.append(kwargs["artifacts"]),
    )

    def compile_probe(**kwargs: object) -> subprocess.CompletedProcess[str]:
        code = str(kwargs["code"])
        compile(code, "paired-control-probe", "exec")
        for required in (
            "CONTROL_PING",
            '"status"',
            '"stop"',
            '"ledger": "released"',
            "control_health=ok",
        ):
            assert required in code
        assert "TautClient.init(db_path=db)" in code
        assert code.index("TautClient.init(db_path=db)") < code.index(
            "driver = subprocess.Popen("
        )
        return subprocess.CompletedProcess(
            ["python"], 0, '{"case":"paired_control"}\n', ""
        )

    monkeypatch.setattr(verifier_module, "_run_python_probe", compile_probe)

    verifier_module._case_paired_control_smoke(
        new_core=core,
        new_summon=summon,
        work=tmp_path,
        env=verifier_module._clean_environment(),
        uv="uv",
    )

    assert installed == [(core, summon)]
    assert '"case":"paired_control"' in capsys.readouterr().out


def test_resolver_case_accepts_only_expected_taut_version_conflict(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        verifier_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, tmp_path / "python"),
    )
    monkeypatch.setattr(
        verifier_module,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["uv"],
            1,
            "No solution found when resolving dependencies: Because "
            "taut-summon==0.6.0 depends on taut>=0.6.0 and taut==0.5.0 "
            "was provided",
            "",
        ),
    )

    verifier_module._case_resolver_rejects_prior_core(
        previous_core=tmp_path / "taut-0.5.0.whl",
        new_summon=tmp_path / "taut_summon-0.6.0.whl",
        new_core_version="0.6.0",
        work=tmp_path,
        env=verifier_module._clean_environment(),
        uv="uv",
    )

    assert '"resolver": "conflict"' in capsys.readouterr().out


def test_resolver_case_accepts_uv_explicit_wheel_availability_diagnostic(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        verifier_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, tmp_path / "python"),
    )
    monkeypatch.setattr(
        verifier_module,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["uv"],
            1,
            "No solution found when resolving dependencies: Because only "
            "taut<0.5.1 is available and taut-summon==0.5.1 depends on "
            "taut>=0.5.1, taut-summon==0.5.1 cannot be used.",
            "",
        ),
    )

    verifier_module._case_resolver_rejects_prior_core(
        previous_core=tmp_path / "taut-0.5.0.whl",
        new_summon=tmp_path / "taut_summon-0.5.1.whl",
        new_core_version="0.5.1",
        work=tmp_path,
        env=verifier_module._clean_environment(),
        uv="uv",
    )

    assert '"resolver": "conflict"' in capsys.readouterr().out


def test_resolver_case_rejects_success_with_prior_core(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verifier_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, tmp_path / "python"),
    )
    monkeypatch.setattr(
        verifier_module,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["uv"], 0, "installed", ""
        ),
    )

    with pytest.raises(
        verifier_module.VerificationError,
        match="resolver accepted new Summon with prior taut 0.5.0",
    ):
        verifier_module._case_resolver_rejects_prior_core(
            previous_core=tmp_path / "taut-0.5.0.whl",
            new_summon=tmp_path / "taut_summon-0.6.0.whl",
            new_core_version="0.6.0",
            work=tmp_path,
            env=verifier_module._clean_environment(),
            uv="uv",
        )


def test_resolver_case_rejects_unrelated_error_that_mentions_all_versions(
    tmp_path: Path,
    verifier_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verifier_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, tmp_path / "python"),
    )
    monkeypatch.setattr(
        verifier_module,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["uv"],
            1,
            "network unavailable while checking taut 0.5.0 against 0.6.0",
            "",
        ),
    )

    with pytest.raises(
        verifier_module.VerificationError,
        match="unexpected reason rather than the expected taut dependency conflict",
    ):
        verifier_module._case_resolver_rejects_prior_core(
            previous_core=tmp_path / "taut-0.5.0.whl",
            new_summon=tmp_path / "taut_summon-0.6.0.whl",
            new_core_version="0.6.0",
            work=tmp_path,
            env=verifier_module._clean_environment(),
            uv="uv",
        )
