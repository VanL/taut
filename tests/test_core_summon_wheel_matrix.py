"""Focused [SUM-12] checks for the installed core/Summon wheel matrix."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WHEEL_MATRIX_CHECKER = PROJECT_ROOT / "bin" / "check-core-summon-wheel-matrix.py"
RELEASE_WHEEL_CHECKER = PROJECT_ROOT / "bin" / "build-and-check-release-wheels.py"

pytestmark = pytest.mark.shared


@pytest.fixture
def wheel_matrix_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "taut_core_summon_wheel_matrix", WHEEL_MATRIX_CHECKER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release_wheel_checker_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "taut_release_wheel_checker", RELEASE_WHEEL_CHECKER
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


def test_matrix_python_uses_explicit_override(
    wheel_matrix_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TAUT_WHEEL_MATRIX_PYTHON", "/custom/python311")
    monkeypatch.setattr(
        wheel_matrix_module,
        "_candidate_path",
        lambda _candidate: Path("/custom/python311"),
    )
    monkeypatch.setattr(
        wheel_matrix_module, "_python_version", lambda _candidate: (3, 11)
    )

    assert wheel_matrix_module._resolve_matrix_python() == Path("/custom/python311")


def test_matrix_python_falls_back_to_compatible_version(
    wheel_matrix_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TAUT_WHEEL_MATRIX_PYTHON", raising=False)
    monkeypatch.setattr(wheel_matrix_module.sys, "executable", "/custom/python39")

    def fake_version(candidate: str) -> tuple[int, int]:
        if candidate in {
            "/custom/python39",
            "python3.14",
            "python3.13",
            "python3.12",
            "python3",
            "python",
        }:
            return 3, 10
        if candidate == "python3.11":
            return 3, 11
        return 0, 0

    monkeypatch.setattr(wheel_matrix_module, "_candidate_path", Path)
    monkeypatch.setattr(wheel_matrix_module, "_python_version", fake_version)

    assert wheel_matrix_module._resolve_matrix_python() == Path("python3.11")


def test_matrix_python_resolution_fails_when_only_too_old(
    wheel_matrix_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TAUT_WHEEL_MATRIX_PYTHON", raising=False)
    monkeypatch.setattr(wheel_matrix_module.sys, "executable", "/custom/python39")
    monkeypatch.setattr(wheel_matrix_module, "_candidate_path", Path)
    monkeypatch.setattr(
        wheel_matrix_module, "_python_version", lambda _candidate: (3, 10)
    )

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="could not find a Python interpreter >= 3.11 for wheel-matrix environments",
    ):
        wheel_matrix_module._resolve_matrix_python()


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
    _write_distribution(site_packages, name="taut-chat", version="0.6.0")


def _write_wheel(
    path: Path,
    *,
    name: str,
    version: str,
    requirements: tuple[str, ...],
    command_entry_points: tuple[tuple[str, str], ...] | None = None,
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
    if command_entry_points is None:
        command_entry_points = (
            (
                (
                    "dismiss",
                    "taut_summon.command_manifest:dismiss",
                ),
                (
                    "summon",
                    "taut_summon.command_manifest:summon",
                ),
            )
            if name == "taut-summon"
            else ()
        )
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr(f"{dist_info}-{version}.dist-info/METADATA", "\n".join(metadata))
        if command_entry_points:
            rendered = "[taut.commands]\n" + "".join(
                f"{command} = {target}\n" for command, target in command_entry_points
            )
            wheel.writestr(
                f"{dist_info}-{version}.dist-info/entry_points.txt",
                rendered,
            )
    return path


def _write_command_provider_wheel(
    path: Path,
    *,
    name: str,
    entry_points: tuple[tuple[str, str], ...],
    modules: dict[str, str],
    version: str = "0.0.0",
) -> Path:
    """Write one minimal wheel for installed command-ownership probes."""

    dist_info = f"{name.replace('-', '_').replace('.', '_')}-{version}.dist-info"
    entry_point_text = "[taut.commands]\n" + "".join(
        f"{command_name} = {target}\n" for command_name, target in entry_points
    )
    with zipfile.ZipFile(path, "w") as wheel:
        for relative_path, source in modules.items():
            wheel.writestr(relative_path, source)
        wheel.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n",
        )
        wheel.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: taut-tests\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n",
        )
        wheel.writestr(f"{dist_info}/entry_points.txt", entry_point_text)
        wheel.writestr(f"{dist_info}/RECORD", "")
    return path


def _write_scripted_mcp_server(path: Path) -> Path:
    path.write_text(
        r"""
import json
import os
import sys
import time

mode = os.environ["TAUT_TEST_MCP_MODE"]
time.sleep(float(os.environ.get("TAUT_TEST_MCP_STARTUP_DELAY", "0")))
workspace = os.path.realpath(os.environ["TAUT_TEST_MCP_WORKSPACE"])
member_id = os.environ["TAUT_TEST_MCP_MEMBER_ID"]
member_name = os.environ["TAUT_TEST_MCP_MEMBER_NAME"]
token = None
record = None


def send(frame):
    sys.stdout.write(json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def tool_result(request_id, structured):
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [],
            "isError": False,
            "structuredContent": structured,
        },
    })


for line in sys.stdin:
    frame = json.loads(line)
    request_id = frame.get("id")
    if request_id is None:
        continue
    if mode == f"timeout-{request_id}":
        time.sleep(60)
    if mode == f"fail-{request_id}":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": "scripted failure"},
        })
        continue
    if request_id == 1:
        send({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {}}})
    elif request_id == 2:
        arguments = frame["params"]["arguments"]
        token = arguments["token"]
        record = {
            "backend": "sqlite",
            "member_id": member_id,
            "name": member_name,
            "status": "ready",
            "workspace": workspace,
        }
        if mode == "token-stdout":
            send({"jsonrpc": "2.0", "method": "leak", "params": {"token": token}})
        tool_result(2, {"records": [record]})
    elif request_id == 3:
        tool_result(3, {"records": [record]})
    elif request_id == 4:
        tool_result(4, {"records": [{"status": "detached", "workspace": workspace}]})
    elif request_id == 5:
        tool_result(5, {"empty": True, "records": []})

if mode == "shutdown-timeout":
    time.sleep(60)
if mode == "shutdown-traceback":
    sys.stderr.write("Traceback (most recent call last): scripted\n")
if mode == "shutdown-token":
    sys.stderr.write(f"selector={token}\n")
    raise SystemExit(2)
if mode == "shutdown-failure":
    sys.stderr.write("scripted shutdown failure\n")
    raise SystemExit(2)
""".lstrip(),
        encoding="utf-8",
    )
    return path


_VALID_SUMMON_MANIFEST = """
from taut.commands import CommandSpec

summon = CommandSpec(
    1,
    "summon",
    "Synthetic installed summon owner.",
    frozenset(),
    "synthetic_command:create_command",
)
""".lstrip()

_VALID_SUMMON_COMMAND = """
class SyntheticCommand:
    def configure_parser(self, parser):
        parser.add_argument("value")

    def run(self, context, args):
        context.stdout.write(f"official:{args.value}\\n")
        return 0


def create_command():
    return SyntheticCommand()
""".lstrip()

_LOUD_LEGACY_SUMMON = """
import sys


def main(argv=None):
    print("legacy fallback executed", file=sys.stderr)
    return 0
""".lstrip()


def _assert_wheels_installed(environment: Any, *wheels: Path) -> None:
    result = environment.install_wheels(*wheels)
    assert result.returncode == 0, result.stderr


def test_installed_new_core_alone_uses_summon_install_hint(
    tmp_path: Path,
    installed_command_fixture: Any,
) -> None:
    environment = installed_command_fixture.create_isolated(tmp_path / "core-only")

    result = environment.run_console("summon", "reviewer")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "taut summon requires the taut-summon extension "
        "(pipx inject taut-chat taut-summon)\n"
    )


def test_installed_new_core_with_current_summon_uses_official_command_adapters(
    tmp_path: Path,
    installed_command_fixture: Any,
) -> None:
    environment = installed_command_fixture.create_isolated(tmp_path / "new-summon")
    _assert_wheels_installed(environment, installed_command_fixture.summon_wheel)

    summon_help = environment.run_console("summon", "--help")
    dismiss_help = environment.run_console("dismiss", "--help")
    provenance = environment.run_python(
        "import json; from taut.commands._registry import CommandRegistry; "
        "registry = CommandRegistry(); "
        "print(json.dumps({name: {"
        "'distribution': registry.get(name).distribution_name, "
        "'target': registry.get(name).spec.implementation, "
        "'verbatim': registry.get(name).verbatim_tail} "
        "for name in ('summon', 'dismiss')}, sort_keys=True))"
    )

    assert summon_help.returncode == 0
    assert "usage: taut summon" in summon_help.stdout
    assert "usage: taut-summon" not in summon_help.stdout
    assert summon_help.stderr == ""
    assert dismiss_help.returncode == 0
    assert "usage: taut dismiss" in dismiss_help.stdout
    assert dismiss_help.stderr == ""
    assert provenance.returncode == 0, provenance.stderr
    assert json.loads(provenance.stdout) == {
        "dismiss": {
            "distribution": "taut-summon",
            "target": "taut_summon.commands.dismiss:create_command",
            "verbatim": False,
        },
        "summon": {
            "distribution": "taut-summon",
            "target": "taut_summon.commands.summon:create_command",
            "verbatim": False,
        },
    }


def test_installed_core_summon_pair_shares_blank_message_exception(
    tmp_path: Path,
    installed_command_fixture: Any,
) -> None:
    """[TAUT-8.3, SUM-6] The paired wheel imports the typed core outcome."""

    environment = installed_command_fixture.create_isolated(tmp_path / "blank-error")
    _assert_wheels_installed(environment, installed_command_fixture.summon_wheel)

    result = environment.run_python(
        "from taut import BlankMessageError, EmptyResultError; "
        "import taut_summon._driver; "
        "assert issubclass(BlankMessageError, EmptyResultError); "
        "print(BlankMessageError.__name__)"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "BlankMessageError\n"


@pytest.mark.parametrize(
    ("root_args", "standalone_args"),
    [
        (("summon", "scripted"), ("run", "scripted")),
        (
            ("summon", "reviewer", "--provider", "scripted", "dev"),
            ("run", "reviewer", "--provider", "scripted", "dev"),
        ),
        (("summon", "--", "-q"), ("run", "--", "-q")),
        (
            ("summon", "reviewer", "--provider", "scripted", "--", "--as"),
            ("run", "reviewer", "--provider", "scripted", "--", "--as"),
        ),
        (("dismiss", "reviewer"), ("stop", "reviewer")),
    ],
)
def test_installed_root_and_standalone_summon_surfaces_have_execution_parity(
    tmp_path: Path,
    installed_command_fixture: Any,
    root_args: tuple[str, ...],
    standalone_args: tuple[str, ...],
) -> None:
    environment = installed_command_fixture.create_isolated(
        tmp_path / ("parity-" + "-".join(root_args))
    )
    _assert_wheels_installed(environment, installed_command_fixture.summon_wheel)

    root = environment.run_console(*root_args)
    standalone = environment.run_summon_console(*standalone_args)

    assert (root.returncode, root.stdout, root.stderr) == (
        standalone.returncode,
        standalone.stdout,
        standalone.stderr,
    )
    assert "Traceback" not in root.stderr


@pytest.mark.parametrize("verb", ("summon", "dismiss"))
def test_installed_summon_help_does_not_import_runtime_subsystems(
    tmp_path: Path,
    installed_command_fixture: Any,
    verb: str,
) -> None:
    environment = installed_command_fixture.create_isolated(
        tmp_path / f"help-imports-{verb}"
    )
    _assert_wheels_installed(environment, installed_command_fixture.summon_wheel)

    result = environment.run_python(
        "import contextlib, io, json, sys; "
        "from taut.commands._dispatch import dispatch; "
        "stdout = io.StringIO(); stderr = io.StringIO(); "
        f"rc = dispatch([{verb!r}, '--help'], stdout=stdout, stderr=stderr); "
        "print(json.dumps({'rc': rc, 'stdout': stdout.getvalue(), "
        "'stderr': stderr.getvalue(), 'loaded': sorted(sys.modules)}))"
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["rc"] == 0
    assert payload["stderr"] == ""
    assert f"usage: taut {verb}" in payload["stdout"]
    forbidden = (
        "simplebroker",
        "taut.client",
        "taut.state",
        "taut_summon._adapter",
        "taut_summon._control",
        "taut_summon._driver",
        "taut_summon._pty",
        "taut_summon._state",
        "taut_summon.controller",
        "taut_summon.interaction",
    )
    assert not [name for name in payload["loaded"] if name.startswith(forbidden)]


def test_installed_unofficial_reserved_claim_cannot_suppress_compatibility(
    tmp_path: Path,
    installed_command_fixture: Any,
) -> None:
    wheel = _write_command_provider_wheel(
        tmp_path / "counterfeit_owner-0.0.0-py3-none-any.whl",
        name="counterfeit-owner",
        entry_points=(("summon", "unofficial_manifest:summon"),),
        modules={"unofficial_manifest.py": _VALID_SUMMON_MANIFEST},
    )
    environment = installed_command_fixture.create_isolated(tmp_path / "unofficial")
    _assert_wheels_installed(environment, wheel)

    help_result = environment.run_console("--help")
    invoke_result = environment.run_console("summon", "reviewer")

    assert help_result.returncode == 0
    assert (
        "installed command 'summon' from counterfeit-owner 0.0.0 "
        "(unofficial_manifest:summon) cannot own"
    ) in help_result.stderr
    assert invoke_result.returncode == 1
    assert "requires the taut-summon extension" in invoke_result.stderr
    assert "official:" not in invoke_result.stdout


def test_installed_official_reserved_claim_wins_with_unofficial_claimant(
    tmp_path: Path,
    installed_command_fixture: Any,
) -> None:
    official = _write_command_provider_wheel(
        tmp_path / "taut_summon-0.0.0-py3-none-any.whl",
        name="taut-summon",
        entry_points=(("summon", "official_manifest:summon"),),
        modules={
            "official_manifest.py": _VALID_SUMMON_MANIFEST,
            "synthetic_command.py": _VALID_SUMMON_COMMAND,
        },
    )
    unofficial = _write_command_provider_wheel(
        tmp_path / "counterfeit_owner-0.0.0-py3-none-any.whl",
        name="counterfeit-owner",
        entry_points=(("summon", "unofficial_manifest:summon"),),
        modules={"unofficial_manifest.py": _VALID_SUMMON_MANIFEST},
    )
    environment = installed_command_fixture.create_isolated(
        tmp_path / "official-plus-unofficial"
    )
    _assert_wheels_installed(environment, official, unofficial)

    help_result = environment.run_console("--help")
    invoke_result = environment.run_console("summon", "reviewer")

    assert help_result.returncode == 0
    assert (
        "installed command 'summon' from counterfeit-owner 0.0.0 "
        "(unofficial_manifest:summon) cannot own"
    ) in help_result.stderr
    assert invoke_result.returncode == 0
    assert invoke_result.stdout == "official:reviewer\n"
    assert invoke_result.stderr == ""


def test_installed_duplicate_official_claims_do_not_run_legacy_fallback(
    tmp_path: Path,
    installed_command_fixture: Any,
) -> None:
    wheel = _write_command_provider_wheel(
        tmp_path / "taut_summon-0.0.0-py3-none-any.whl",
        name="taut-summon",
        entry_points=(
            ("summon", "duplicate_manifest:summon"),
            ("summon", "duplicate_manifest:second"),
        ),
        modules={
            "duplicate_manifest.py": _VALID_SUMMON_MANIFEST + "\nsecond = summon\n",
            "synthetic_command.py": _VALID_SUMMON_COMMAND,
            "taut_summon/__init__.py": "",
            "taut_summon/cli.py": _LOUD_LEGACY_SUMMON,
        },
    )
    environment = installed_command_fixture.create_isolated(
        tmp_path / "duplicate-official"
    )
    _assert_wheels_installed(environment, wheel)

    result = environment.run_console("summon", "reviewer")

    assert result.returncode == 1
    assert "multiple official taut-summon entry points claim it" in result.stderr
    assert "legacy fallback executed" not in result.stderr
    assert "Traceback" not in result.stderr


def test_installed_broken_official_claim_does_not_run_legacy_fallback(
    tmp_path: Path,
    installed_command_fixture: Any,
) -> None:
    wheel = _write_command_provider_wheel(
        tmp_path / "taut_summon-0.0.0-py3-none-any.whl",
        name="taut-summon",
        entry_points=(("summon", "broken_manifest:summon"),),
        modules={
            "broken_manifest.py": "raise RuntimeError('broken official manifest')\n",
            "taut_summon/__init__.py": "",
            "taut_summon/cli.py": _LOUD_LEGACY_SUMMON,
        },
    )
    environment = installed_command_fixture.create_isolated(
        tmp_path / "broken-official"
    )
    _assert_wheels_installed(environment, wheel)

    result = environment.run_console("summon", "reviewer")

    assert result.returncode == 1
    assert "broken official manifest" in result.stderr
    assert "legacy fallback executed" not in result.stderr
    assert "Traceback" not in result.stderr


def _run_wheel_matrix_check(
    tmp_path: Path, core: Path, summon: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(WHEEL_MATRIX_CHECKER),
            "--new-core",
            str(core),
            "--new-summon",
            str(summon),
            "--historical-summon-ref",
            "taut_summon/v0.5.4",
            "--historical-mcp-ref",
            "taut_mcp/v0.9.5",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )


def test_release_wheel_checker_uses_fresh_separate_wheel_outputs(
    release_wheel_checker_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = release_wheel_checker_module
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
                "taut_chat-0.6.0-py3-none-any.whl"
                if output.name == "core"
                else "taut_summon-0.6.0-py3-none-any.whl"
            )
            (output / wheel_name).touch()
            return
        assert command[:2] == (sys.executable, str(WHEEL_MATRIX_CHECKER))
        core = Path(command[command.index("--new-core") + 1])
        summon = Path(command[command.index("--new-summon") + 1])
        assert core.parent == output_dirs[0]
        assert summon.parent == output_dirs[1]
        assert core.parent != summon.parent
        assert core.is_file() and summon.is_file()
        assert (
            command[command.index("--historical-summon-ref") + 1]
            == "taut_summon/v0.5.4"
        )
        assert command[command.index("--historical-mcp-ref") + 1] == "taut_mcp/v0.9.5"

    monkeypatch.setattr(builder, "_run", fake_run)

    builder.build_and_check()

    assert len(commands) == 3
    assert all("dist" not in part for command in commands for part in command)


def test_release_wheel_checker_requires_exactly_one_wheel_per_output(
    release_wheel_checker_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = release_wheel_checker_module
    commands: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...]) -> None:
        commands.append(command)
        output = Path(command[command.index("--out-dir") + 1])
        (output / "first.whl").touch()
        (output / "second.whl").touch()

    monkeypatch.setattr(builder, "_run", fake_run)

    with pytest.raises(
        builder.ReleaseWheelCheckError,
        match="core build produced 2 wheels; expected exactly one",
    ):
        builder.build_and_check()

    assert len(commands) == 1


def test_release_wheel_checker_dry_run_prints_build_build_check_order(
    release_wheel_checker_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    builder = release_wheel_checker_module
    monkeypatch.setattr(
        builder,
        "_run",
        lambda _command: pytest.fail("dry-run must not execute a command"),
    )

    builder.build_and_check(dry_run=True)

    output = capsys.readouterr().out
    core_build = output.index("uv build --wheel")
    summon_build = output.index("uv build --wheel", core_build + 1)
    matrix_check = output.index("check-core-summon-wheel-matrix.py")
    assert core_build < summon_build < matrix_check
    assert "--new-core" in output
    assert "--new-summon" in output
    assert "--historical-summon-ref taut_summon/v0.5.4" in output
    assert "--historical-mcp-ref taut_mcp/v0.9.5" in output


def test_release_wheel_checker_reuses_explicit_current_wheels_without_building(
    tmp_path: Path,
    release_wheel_checker_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = release_wheel_checker_module
    core = tmp_path / "taut_chat-0.6.1-py3-none-any.whl"
    summon = tmp_path / "taut_summon-0.6.1-py3-none-any.whl"
    core.touch()
    summon.touch()
    commands: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...]) -> None:
        commands.append(command)
        assert command[1:3] != ("build", "--wheel")
        assert command[command.index("--new-core") + 1] == str(core)
        assert command[command.index("--new-summon") + 1] == str(summon)

    monkeypatch.setattr(builder, "_run", fake_run)

    builder.build_and_check(core_wheel=core, summon_wheel=summon)

    roles = Counter(
        "build"
        if command[:2] == ("uv", "build")
        else "wheel-matrix"
        if command[1] == str(builder.WHEEL_MATRIX_CHECKER)
        else "unexpected"
        for command in commands
    )
    assert roles == Counter({"wheel-matrix": 1})


def test_release_wheel_checker_rejects_partial_explicit_pair(
    tmp_path: Path,
    release_wheel_checker_module: ModuleType,
) -> None:
    builder = release_wheel_checker_module
    core = tmp_path / "taut.whl"
    core.touch()

    with pytest.raises(
        builder.ReleaseWheelCheckError,
        match="core and Summon wheel paths must be supplied together",
    ):
        builder.build_and_check(core_wheel=core)


def test_wheel_matrix_checker_accepts_exact_historical_summon_ref(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    core = tmp_path / "core.whl"
    summon = tmp_path / "summon.whl"
    core.touch()
    summon.touch()

    inputs = wheel_matrix_module._parse_args(
        [
            "--new-core",
            str(core),
            "--new-summon",
            str(summon),
            "--historical-summon-ref",
            "taut_summon/v0.5.4",
            "--historical-mcp-ref",
            "taut_mcp/v0.9.5",
        ]
    )

    assert inputs.historical_summon_ref == "taut_summon/v0.5.4"
    assert inputs.historical_mcp_ref == "taut_mcp/v0.9.5"


def test_wheel_matrix_checker_rejects_mutable_historical_summon_ref(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    core = tmp_path / "core.whl"
    summon = tmp_path / "summon.whl"
    core.touch()
    summon.touch()

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="historical Summon ref must be immutable release ref",
    ):
        wheel_matrix_module._parse_args(
            [
                "--new-core",
                str(core),
                "--new-summon",
                str(summon),
                "--historical-summon-ref",
                "main",
                "--historical-mcp-ref",
                "taut_mcp/v0.9.5",
            ]
        )


def test_wheel_matrix_checker_rejects_mutable_historical_mcp_ref(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    core = tmp_path / "core.whl"
    summon = tmp_path / "summon.whl"
    core.touch()
    summon.touch()

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="historical MCP ref must be immutable release ref",
    ):
        wheel_matrix_module._parse_args(
            [
                "--new-core",
                str(core),
                "--new-summon",
                str(summon),
                "--historical-summon-ref",
                "taut_summon/v0.5.4",
                "--historical-mcp-ref",
                "main",
            ]
        )


def test_historical_mcp_tag_commit_mismatch_fails_closed(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = "a" * 40
    observed = "b" * 40
    ref = "taut_mcp/v0.9.5"
    monkeypatch.setattr(wheel_matrix_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(wheel_matrix_module, "EXPECTED_REF_COMMITS", {ref: expected})
    monkeypatch.setattr(
        wheel_matrix_module,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["git", "ls-remote"],
            0,
            f"{observed}\trefs/tags/{ref}^{{}}\n",
            "",
        ),
    )

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match=f"resolves to {observed}, expected {expected}",
    ):
        wheel_matrix_module._resolve_remote_tag(
            ref,
            env=wheel_matrix_module._clean_environment(),
        )


def test_release_wheel_checker_cli_accepts_dry_run(
    release_wheel_checker_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = release_wheel_checker_module
    calls: list[bool] = []
    monkeypatch.setattr(
        builder,
        "build_and_check",
        lambda *, dry_run=False: calls.append(dry_run),
    )

    assert builder.main(["--dry-run"]) == 0
    assert calls == [True]


def test_release_wheel_checker_reports_spawn_error_without_traceback(
    release_wheel_checker_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    builder = release_wheel_checker_module
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


def test_release_wheel_checker_builds_both_wheels_before_matrix_check(
    release_wheel_checker_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = release_wheel_checker_module
    events: list[str] = []

    def fake_run(command: tuple[str, ...]) -> None:
        if command[1:3] == ("build", "--wheel"):
            output = Path(command[command.index("--out-dir") + 1])
            wheel = "taut_chat.whl" if output.name == "core" else "taut_summon.whl"
            (output / wheel).touch()
            events.append(f"build:{output.name}")
            return
        events.append("check:wheel-matrix")

    monkeypatch.setattr(builder, "_run", fake_run)

    builder.build_and_check()

    assert events == [
        "build:core",
        "build:summon",
        "check:wheel-matrix",
    ]


def test_wheel_matrix_checker_reports_missing_wheel_without_traceback(
    tmp_path: Path,
) -> None:
    missing_core = tmp_path / "missing-core.whl"
    missing_summon = tmp_path / "missing-summon.whl"

    completed = _run_wheel_matrix_check(tmp_path, missing_core, missing_summon)

    assert completed.returncode == 1
    assert "new core wheel does not exist" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_wheel_matrix_checker_rejects_old_core_distribution_name(
    tmp_path: Path,
) -> None:
    core = _write_wheel(
        tmp_path / "taut-0.6.0-py3-none-any.whl",
        name="taut",
        version="0.6.0",
        requirements=(),
    )
    summon = _write_wheel(
        tmp_path / "taut_summon-0.6.0-py3-none-any.whl",
        name="taut-summon",
        version="0.6.0",
        requirements=("taut-chat>=0.6.0",),
    )

    completed = _run_wheel_matrix_check(tmp_path, core, summon)

    assert completed.returncode == 1
    assert "expected 'taut-chat'" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_wheel_matrix_checker_rejects_summon_without_exact_new_core_floor(
    tmp_path: Path,
) -> None:
    core = _write_wheel(
        tmp_path / "taut_chat-0.6.0-py3-none-any.whl",
        name="taut-chat",
        version="0.6.0",
        requirements=(),
    )
    summon = _write_wheel(
        tmp_path / "taut_summon-0.6.0-py3-none-any.whl",
        name="taut-summon",
        version="0.6.0",
        requirements=("taut-chat>=0.5.0",),
    )

    completed = _run_wheel_matrix_check(tmp_path, core, summon)

    assert completed.returncode == 1
    assert "taut-chat>=0.6.0" in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize(
    "requirements",
    [
        ("taut-chat>=0.6.1",),
        ("taut-chat==0.6.0",),
        ("taut-chat>=0.6.0,<1",),
        ('taut-chat>=0.6.0; python_version >= "3.11"',),
        ("taut-chat>=0.6.0", "taut-chat>=0.6.0"),
    ],
)
def test_wheel_matrix_checker_rejects_nonexact_or_duplicate_taut_chat_requirement(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    requirements: tuple[str, ...],
) -> None:
    core = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut_chat-0.6.0-py3-none-any.whl",
            name="taut-chat",
            version="0.6.0",
            requirements=(),
        )
    )
    summon = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut_summon-0.6.0-py3-none-any.whl",
            name="taut-summon",
            version="0.6.0",
            requirements=requirements,
        )
    )

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="exactly one unmarked Requires-Dist 'taut-chat>=0.6.0'",
    ):
        wheel_matrix_module._validate_new_metadata(core, summon)


def test_wheel_matrix_checker_rejects_taut_command_entry_points_in_core_wheel(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    core = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut-0.6.0-py3-none-any.whl",
            name="taut-chat",
            version="0.6.0",
            requirements=(),
            command_entry_points=(("summon", "wrong_owner:summon"),),
        )
    )
    summon = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut_summon-0.6.0-py3-none-any.whl",
            name="taut-summon",
            version="0.6.0",
            requirements=("taut-chat>=0.6.0",),
        )
    )

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="new core wheel must not publish taut.commands entry points",
    ):
        wheel_matrix_module._validate_new_metadata(core, summon)


@pytest.mark.parametrize(
    "entry_points",
    (
        (),
        (("summon", "taut_summon.command_manifest:summon"),),
        (
            ("dismiss", "taut_summon.command_manifest:dismiss"),
            ("summon", "wrong_manifest:summon"),
        ),
    ),
)
def test_wheel_matrix_checker_requires_exact_summon_command_entry_points(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    entry_points: tuple[tuple[str, str], ...],
) -> None:
    core = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut-0.6.0-py3-none-any.whl",
            name="taut-chat",
            version="0.6.0",
            requirements=(),
        )
    )
    summon = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut_summon-0.6.0-py3-none-any.whl",
            name="taut-summon",
            version="0.6.0",
            requirements=("taut-chat>=0.6.0",),
            command_entry_points=entry_points,
        )
    )

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="new Summon wheel must publish exactly",
    ):
        wheel_matrix_module._validate_new_metadata(core, summon)


def test_python_probe_rejects_checkout_path_from_site_packages(
    tmp_path: Path, wheel_matrix_module: ModuleType
) -> None:
    _root, python, site_packages = _make_venv(tmp_path)
    (site_packages / "checkout-leak.pth").write_text(
        f"{PROJECT_ROOT}\n", encoding="utf-8"
    )

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError, match="checkout path leaked into sys.path"
    ):
        wheel_matrix_module._run_python_probe(
            python=python,
            code='raise SystemExit("case body must not run")',
            cwd=tmp_path,
            env=wheel_matrix_module._clean_environment(),
        )


def test_prior_tags_are_fetched_into_temporary_archive_repository(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
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
    (origin / "artifact.txt").write_text("command rollout\n", encoding="utf-8")
    subprocess.run(["git", "add", "artifact.txt"], cwd=origin, check=True)
    subprocess.run(
        ["git", "commit", "-m", "command rollout fixture"],
        cwd=origin,
        env=git_env,
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "tag", "taut_summon/v0.5.4"], cwd=origin, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(origin)], cwd=origin, check=True
    )
    command_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=origin,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    monkeypatch.setattr(wheel_matrix_module, "PROJECT_ROOT", origin)
    monkeypatch.setattr(
        wheel_matrix_module,
        "EXPECTED_REF_COMMITS",
        {"taut_summon/v0.5.4": command_commit},
    )

    archive_repository = wheel_matrix_module._prepare_archive_repository(
        refs=("taut_summon/v0.5.4",),
        work=tmp_path,
        env=wheel_matrix_module._clean_environment(),
    )

    assert archive_repository.is_dir()
    command_resolved = subprocess.run(
        [
            "git",
            f"--git-dir={archive_repository}",
            "rev-parse",
            "refs/tags/taut_summon/v0.5.4^{commit}",
        ],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert command_resolved == command_commit


def test_command_interrupt_terminates_owned_process_group(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
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
        wheel_matrix_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        wheel_matrix_module,
        "_terminate_owned_process_group",
        lambda owned: terminated.append(owned),
    )

    with pytest.raises(KeyboardInterrupt):
        wheel_matrix_module._run(
            ["long-running-command"],
            cwd=tmp_path,
            env=wheel_matrix_module._clean_environment(),
        )

    assert terminated == [process]


def test_new_core_case_accepts_obsolete_reactor_guard(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _root, python, site_packages = _make_venv(tmp_path)
    _write_fake_taut(site_packages)
    _write_distribution(site_packages, name="simplebroker", version="7.4.1")
    monkeypatch.setattr(
        wheel_matrix_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, python),
    )
    monkeypatch.setattr(wheel_matrix_module, "_install", lambda **_kwargs: None)

    wheel_matrix_module._case_new_core(
        wheel=tmp_path / "unused.whl",
        work=tmp_path,
        env=wheel_matrix_module._clean_environment(),
        uv="uv",
    )

    output = capsys.readouterr().out
    assert '"guard": "rejected_before_broker_io"' in output


def test_historical_summon_metadata_records_unrelated_taut_dependency(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    historical = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut_summon-0.5.4-py3-none-any.whl",
            name="taut-summon",
            version="0.5.4",
            requirements=("taut>=0.5.4",),
            command_entry_points=(),
        )
    )

    wheel_matrix_module._case_historical_summon_metadata(historical)

    output = capsys.readouterr().out
    assert '"case": "historical_summon_metadata"' in output
    assert '"requires": "taut>=0.5.4"' in output
    assert '"relation_to_current_core": "unrelated_distribution"' in output


def test_historical_summon_metadata_rejects_taut_chat_dependency(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    historical = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut_summon-0.5.4-py3-none-any.whl",
            name="taut-summon",
            version="0.5.4",
            requirements=("taut-chat>=0.5.4",),
            command_entry_points=(),
        )
    )

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="historical Summon METADATA must contain exactly one "
        "Requires-Dist 'taut>=0.5.4'",
    ):
        wheel_matrix_module._case_historical_summon_metadata(historical)


def test_historical_mcp_metadata_records_open_candidate_core_requirement(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    historical = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut_mcp-0.9.5-py3-none-any.whl",
            name="taut-mcp",
            version="0.9.5",
            requirements=(
                "jsonschema>=4.26.0,<5",
                "mcp>=2.0.0,<3",
                "taut-chat>=0.9.5",
            ),
            command_entry_points=(),
        )
    )

    wheel_matrix_module._case_historical_mcp_metadata(historical)

    output = capsys.readouterr().out
    assert '"case": "historical_mcp_metadata"' in output
    assert '"requires": "taut-chat>=0.9.5"' in output
    assert '"candidate_core_admitted": true' in output


@pytest.mark.parametrize(
    "requirements",
    [
        ("taut-chat>=0.9.5,<2",),
        ("taut-chat>=0.9.5", "taut-chat>=0.9.5"),
    ],
    ids=("upper-bound", "duplicate"),
)
def test_historical_mcp_metadata_rejects_nonexact_open_core_requirement(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    requirements: tuple[str, ...],
) -> None:
    historical = wheel_matrix_module._read_wheel_metadata(
        _write_wheel(
            tmp_path / "taut_mcp-0.9.5-py3-none-any.whl",
            name="taut-mcp",
            version="0.9.5",
            requirements=requirements,
            command_entry_points=(),
        )
    )

    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="exactly one open Requires-Dist 'taut-chat>=0.9.5'",
    ):
        wheel_matrix_module._case_historical_mcp_metadata(historical)


def test_command_core_only_case_compiles_install_hint_probe(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    core = tmp_path / "taut.whl"
    installed: list[tuple[Path, ...]] = []
    monkeypatch.setattr(
        wheel_matrix_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, tmp_path / "python"),
    )
    monkeypatch.setattr(
        wheel_matrix_module,
        "_install",
        lambda **kwargs: installed.append(kwargs["artifacts"]),
    )

    def compile_probe(**kwargs: object) -> subprocess.CompletedProcess[str]:
        code = str(kwargs["code"])
        compile(code, "command-core-only-probe", "exec")
        assert "pipx inject taut-chat taut-summon" in code
        assert "taut_summon" in code
        return subprocess.CompletedProcess(
            ["python"], 0, '{"case":"command_core_only"}\n', ""
        )

    monkeypatch.setattr(wheel_matrix_module, "_run_python_probe", compile_probe)

    wheel_matrix_module._case_new_core_command_fallback(
        new_core=core,
        work=tmp_path,
        env=wheel_matrix_module._clean_environment(),
        uv="uv",
    )

    assert installed == [(core,)]
    assert '"case":"command_core_only"' in capsys.readouterr().out


def test_historical_summon_builder_requires_version_0_5_4(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    (source / "extensions" / "taut_summon").mkdir(parents=True)

    def fake_run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        output = Path(command[command.index("--out-dir") + 1])
        _write_command_provider_wheel(
            output / "taut_summon-0.5.4-py3-none-any.whl",
            name="taut-summon",
            version="0.5.4",
            entry_points=(),
            modules={},
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wheel_matrix_module, "_run", fake_run)

    wheel = wheel_matrix_module._build_historical_summon(
        summon_source=source,
        work=tmp_path,
        env=wheel_matrix_module._clean_environment(),
        uv="uv",
    )

    assert wheel.name == "taut_summon-0.5.4-py3-none-any.whl"


def test_historical_mcp_builder_requires_version_0_9_5(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    (source / "extensions" / "taut_mcp").mkdir(parents=True)

    def fake_run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        output = Path(command[command.index("--out-dir") + 1])
        _write_wheel(
            output / "taut_mcp-0.9.5-py3-none-any.whl",
            name="taut-mcp",
            version="0.9.5",
            requirements=("taut-chat>=0.9.5",),
            command_entry_points=(),
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wheel_matrix_module, "_run", fake_run)

    wheel = wheel_matrix_module._build_historical_mcp(
        mcp_source=source,
        work=tmp_path,
        env=wheel_matrix_module._clean_environment(),
        uv="uv",
    )

    assert wheel.name == "taut_mcp-0.9.5-py3-none-any.whl"


def test_historical_mcp_case_installs_normally_and_bootstraps_isolated_selector(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    core = tmp_path / "taut_chat.whl"
    historical_mcp = tmp_path / "taut_mcp.whl"
    installed: list[tuple[Path, ...]] = []
    driven: list[dict[str, object]] = []
    python = tmp_path / "bin" / "python"
    python.parent.mkdir()
    python.touch()
    console = python.with_name("taut-mcp.exe" if os.name == "nt" else "taut-mcp")
    console.touch()
    monkeypatch.setattr(
        wheel_matrix_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, python),
    )
    monkeypatch.setattr(
        wheel_matrix_module,
        "_install",
        lambda **kwargs: installed.append(kwargs["artifacts"]),
    )

    def compile_probe(**kwargs: object) -> subprocess.CompletedProcess[str]:
        code = str(kwargs["code"])
        compile(code, "historical-mcp-probe", "exec")
        for required in (
            "TautClient.init(db_path=db)",
            '"historical_mcp_bootstrap"',
            "os.O_EXCL",
            '"member_id": member.member_id',
            '"token": member.token',
        ):
            assert required in code
        assert "--no-deps" not in code
        (tmp_path / ".historical-mcp-selector.json").write_text(
            json.dumps(
                {
                    "member_id": "m_matrix",
                    "member_name": "matrix-member",
                    "token": "taut-secret-selector",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            ["python"], 0, '{"case":"historical_mcp_bootstrap"}\n', ""
        )

    monkeypatch.setattr(wheel_matrix_module, "_run_python_probe", compile_probe)
    monkeypatch.setattr(
        wheel_matrix_module,
        "_drive_historical_mcp_stdio",
        lambda **kwargs: driven.append(kwargs),
    )

    wheel_matrix_module._case_historical_mcp_attach(
        new_core=core,
        historical_mcp=historical_mcp,
        work=tmp_path,
        env=wheel_matrix_module._clean_environment(),
        uv="uv",
    )

    assert installed == [(core, historical_mcp)]
    assert len(driven) == 1
    assert driven[0]["command"] == (str(console),)
    assert driven[0]["token"] == "taut-secret-selector"
    assert driven[0]["member_id"] == "m_matrix"
    assert driven[0]["member_name"] == "matrix-member"
    assert not (tmp_path / ".historical-mcp-selector.json").exists()
    output = capsys.readouterr().out
    assert '"case":"historical_mcp_bootstrap"' in output
    assert "taut-secret-selector" not in output


def _start_scripted_historical_mcp(
    *,
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    mode: str,
    token: str = "taut-scripted-secret",
    stage_timeout: float = 1.0,
    shutdown_timeout: float = 1.0,
    startup_delay: float = 0.0,
) -> tuple[Any, Path]:
    server = _write_scripted_mcp_server(tmp_path / f"server-{mode}.py")
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    env = wheel_matrix_module._clean_environment()
    env.update(
        {
            "TAUT_TEST_MCP_MEMBER_ID": "m_scripted",
            "TAUT_TEST_MCP_MEMBER_NAME": "matrix-member",
            "TAUT_TEST_MCP_MODE": mode,
            "TAUT_TEST_MCP_STARTUP_DELAY": str(startup_delay),
            "TAUT_TEST_MCP_WORKSPACE": str(workspace),
        }
    )
    driver = wheel_matrix_module._HistoricalMcpStdioDriver.start(
        command=(sys.executable, str(server)),
        token=token,
        cwd=tmp_path,
        env=env,
        stage_timeout=stage_timeout,
        shutdown_timeout=shutdown_timeout,
    )
    return driver, workspace


def _drive_scripted_historical_mcp(
    *,
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    mode: str,
    token: str = "taut-scripted-secret",
    stage_timeout: float = 1.0,
    shutdown_timeout: float = 1.0,
) -> None:
    driver, workspace = _start_scripted_historical_mcp(
        tmp_path=tmp_path,
        wheel_matrix_module=wheel_matrix_module,
        mode=mode,
        token=token,
        stage_timeout=stage_timeout,
        shutdown_timeout=shutdown_timeout,
    )
    try:
        driver.initialize()
        record, canonical = driver.attach(
            workspace=workspace,
            member_id="m_scripted",
            member_name="matrix-member",
        )
        driver.assert_listed(record)
        driver.detach(canonical)
        driver.assert_empty()
        driver.shutdown()
        print(
            json.dumps(
                {
                    "case": "historical_mcp_attach",
                    "clean_shutdown": "ok",
                    "status": "ok",
                },
                sort_keys=True,
            )
        )
    finally:
        driver.close()


def test_historical_mcp_stdio_driver_fires_complete_success_lifecycle(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _drive_scripted_historical_mcp(
        tmp_path=tmp_path,
        wheel_matrix_module=wheel_matrix_module,
        mode="success",
    )

    output = capsys.readouterr().out
    assert '"case": "historical_mcp_attach"' in output
    assert '"clean_shutdown": "ok"' in output
    assert "taut-scripted-secret" not in output


@pytest.mark.parametrize(
    ("mode", "diagnostic"),
    [
        ("fail-1", "initialize returned a protocol error"),
        ("fail-2", "attach_workspace returned a protocol error"),
        ("fail-3", "list_workspaces returned a protocol error"),
        ("fail-4", "detach_workspace returned a protocol error"),
        ("fail-5", "list_workspaces after detach returned a protocol error"),
        ("shutdown-failure", "clean_shutdown exited 2"),
    ],
    ids=(
        "initialize",
        "attach",
        "list-attached",
        "detach",
        "list-detached",
        "shutdown",
    ),
)
def test_historical_mcp_stdio_driver_fails_each_lifecycle_stage(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    mode: str,
    diagnostic: str,
) -> None:
    with pytest.raises(wheel_matrix_module.WheelMatrixError, match=diagnostic):
        _drive_scripted_historical_mcp(
            tmp_path=tmp_path,
            wheel_matrix_module=wheel_matrix_module,
            mode=mode,
        )


def test_historical_mcp_stdio_driver_fires_bounded_request_timeout(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    driver, workspace = _start_scripted_historical_mcp(
        tmp_path=tmp_path,
        wheel_matrix_module=wheel_matrix_module,
        mode="timeout-2",
        startup_delay=0.1,
    )
    try:
        driver.initialize()
        driver.stage_timeout = 0.05
        with pytest.raises(
            wheel_matrix_module.WheelMatrixError,
            match="attach_workspace timed out",
        ):
            driver.attach(
                workspace=workspace,
                member_id="m_scripted",
                member_name="matrix-member",
            )
    finally:
        driver.close()


def test_historical_mcp_stdio_driver_fires_bounded_shutdown_timeout(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    driver, workspace = _start_scripted_historical_mcp(
        tmp_path=tmp_path,
        wheel_matrix_module=wheel_matrix_module,
        mode="shutdown-timeout",
        startup_delay=0.1,
    )
    try:
        driver.initialize()
        record, canonical = driver.attach(
            workspace=workspace,
            member_id="m_scripted",
            member_name="matrix-member",
        )
        driver.assert_listed(record)
        driver.detach(canonical)
        driver.assert_empty()
        driver.shutdown_timeout = 0.05
        with pytest.raises(
            wheel_matrix_module.WheelMatrixError,
            match="clean_shutdown timed out",
        ):
            driver.shutdown()
    finally:
        driver.close()


def test_historical_mcp_stdio_driver_rejects_traceback_without_reprinting_it(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="clean_shutdown emitted a traceback",
    ) as caught:
        _drive_scripted_historical_mcp(
            tmp_path=tmp_path,
            wheel_matrix_module=wheel_matrix_module,
            mode="shutdown-traceback",
        )

    assert "Traceback (most recent call last)" not in str(caught.value)


def test_historical_mcp_stdio_driver_rejects_selector_echo_without_exposing_it(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    token = "taut-stdout-secret"
    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="server echoed continuity selector during attach_workspace",
    ) as caught:
        _drive_scripted_historical_mcp(
            tmp_path=tmp_path,
            wheel_matrix_module=wheel_matrix_module,
            mode="token-stdout",
            token=token,
        )

    assert token not in str(caught.value)


def test_historical_mcp_stdio_driver_redacts_selector_from_stderr(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
) -> None:
    token = "taut-stderr-secret"
    with pytest.raises(
        wheel_matrix_module.WheelMatrixError,
        match="clean_shutdown exited 2",
    ) as caught:
        _drive_scripted_historical_mcp(
            tmp_path=tmp_path,
            wheel_matrix_module=wheel_matrix_module,
            mode="shutdown-token",
            token=token,
        )

    diagnostic = str(caught.value)
    assert token not in diagnostic
    assert "selector=<redacted>" in diagnostic


def test_wheel_install_uses_ordinary_dependency_resolution(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = tmp_path / "venv" / "bin" / "python"
    core = tmp_path / "taut_chat.whl"
    historical_mcp = tmp_path / "taut_mcp.whl"
    commands: list[list[str]] = []

    def record_run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wheel_matrix_module, "_run", record_run)

    wheel_matrix_module._install(
        python=python,
        artifacts=(core, historical_mcp),
        cwd=tmp_path,
        env=wheel_matrix_module._clean_environment(),
        uv="uv",
    )

    install = commands[0]
    assert install[:3] == ["uv", "pip", "install"]
    assert "--no-deps" not in install
    assert install[-2:] == [str(core), str(historical_mcp)]


def test_paired_case_installs_both_wheels_and_runs_full_control_probe(
    tmp_path: Path,
    wheel_matrix_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    core = tmp_path / "taut.whl"
    summon = tmp_path / "taut_summon.whl"
    installed: list[tuple[Path, ...]] = []
    monkeypatch.setattr(
        wheel_matrix_module,
        "_create_environment",
        lambda **_kwargs: (tmp_path, tmp_path / "python"),
    )
    monkeypatch.setattr(
        wheel_matrix_module,
        "_install",
        lambda **kwargs: installed.append(kwargs["artifacts"]),
    )

    def compile_probe(**kwargs: object) -> subprocess.CompletedProcess[str]:
        code = str(kwargs["code"])
        compile(code, "paired-control-probe", "exec")
        normalized = " ".join(code.split())
        for required in (
            "SummonController",
            "taut.escape_terminal_text",
            '"summon"',
            '"dismiss"',
            '"ledger": "released"',
            '"command_owner": "taut-summon"',
        ):
            assert required in code
        for forbidden in (
            "from taut_summon.cli import",
            "_resolve_member",
            "_resolve_member_session",
            "CONTROL_PING",
        ):
            assert forbidden not in code
        assert normalized.count('"-m", "taut",') == 2
        assert '"taut_summon.cli"' not in normalized
        assert '"run",' not in normalized
        assert '"stop",' not in normalized
        assert "TautClient.init(db_path=db)" in code
        assert code.index("TautClient.init(db_path=db)") < code.index(
            "driver = subprocess.Popen("
        )
        return subprocess.CompletedProcess(
            ["python"], 0, '{"case":"paired_control"}\n', ""
        )

    monkeypatch.setattr(wheel_matrix_module, "_run_python_probe", compile_probe)

    wheel_matrix_module._case_paired_control_smoke(
        new_core=core,
        new_summon=summon,
        work=tmp_path,
        env=wheel_matrix_module._clean_environment(),
        uv="uv",
    )

    assert installed == [(core, summon)]
    assert '"case":"paired_control"' in capsys.readouterr().out
