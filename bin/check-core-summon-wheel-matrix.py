"""Check the installed core/Summon wheel matrix required by [SUM-12]."""  # noqa: N999 approved [DOM-10.2.1] [RUFF-SUP-075] exception

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import threading
import time
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from typing import NoReturn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HISTORICAL_SUMMON_COMMIT = "b03709452cf4d5962b0d7204b0dab78b9bafd524"
EXPECTED_HISTORICAL_SUMMON_VERSION = "0.5.4"
EXPECTED_HISTORICAL_MCP_COMMIT = "b4ca0fda9767736bfd81eb08c2dfc1e1d2b03998"
EXPECTED_HISTORICAL_MCP_VERSION = "0.9.5"
COMMAND_TIMEOUT_SECONDS = 180.0
CONTROL_SMOKE_TIMEOUT_SECONDS = 180.0
MCP_STAGE_TIMEOUT_SECONDS = 20.0
MCP_SHUTDOWN_TIMEOUT_SECONDS = 20.0
MATRIX_PYTHON_MIN_MINOR = 11
EXPECTED_HISTORICAL_SUMMON_REF = "taut_summon/v0.5.4"
EXPECTED_HISTORICAL_MCP_REF = "taut_mcp/v0.9.5"
EXPECTED_REF_COMMITS = {
    EXPECTED_HISTORICAL_SUMMON_REF: EXPECTED_HISTORICAL_SUMMON_COMMIT,
    EXPECTED_HISTORICAL_MCP_REF: EXPECTED_HISTORICAL_MCP_COMMIT,
}
EXPECTED_SUMMON_COMMAND_ENTRY_POINTS = (
    ("dismiss", "taut_summon.command_manifest:dismiss"),
    ("summon", "taut_summon.command_manifest:summon"),
)


class WheelMatrixError(RuntimeError):
    """One fail-closed core/Summon wheel-matrix diagnostic."""


class _CaseSensitiveConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


@dataclass(frozen=True)
class WheelMetadata:
    path: Path
    name: str
    version: str
    requirements: tuple[str, ...]
    command_entry_points: tuple[tuple[str, str], ...]
    sha256: str


@dataclass(frozen=True)
class Inputs:
    new_core: Path
    new_summon: Path
    historical_summon_ref: str
    historical_mcp_ref: str


def _fail(message: str) -> NoReturn:
    raise WheelMatrixError(message)


def _required_wheel(path: str, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        _fail(f"{label} wheel does not exist: {resolved}")
    if resolved.suffix != ".whl":
        _fail(f"{label} artifact is not a wheel: {resolved}")
    return resolved


def _parse_args(argv: list[str] | None) -> Inputs:
    parser = argparse.ArgumentParser(
        description=(
            "Check the core/Summon compatibility matrix using installed wheels "
            "in checkout-free virtual environments."
        )
    )
    parser.add_argument("--new-core", required=True, metavar="WHEEL")
    parser.add_argument("--new-summon", required=True, metavar="WHEEL")
    parser.add_argument("--historical-summon-ref", required=True, metavar="REF")
    parser.add_argument("--historical-mcp-ref", required=True, metavar="REF")
    args = parser.parse_args(argv)
    inputs = Inputs(
        new_core=_required_wheel(args.new_core, "new core"),
        new_summon=_required_wheel(args.new_summon, "new Summon"),
        historical_summon_ref=args.historical_summon_ref,
        historical_mcp_ref=args.historical_mcp_ref,
    )
    if inputs.historical_summon_ref != EXPECTED_HISTORICAL_SUMMON_REF:
        _fail(
            "historical Summon ref must be immutable release ref "
            f"{EXPECTED_HISTORICAL_SUMMON_REF!r}"
        )
    if inputs.historical_mcp_ref != EXPECTED_HISTORICAL_MCP_REF:
        _fail(
            "historical MCP ref must be immutable release ref "
            f"{EXPECTED_HISTORICAL_MCP_REF!r}"
        )
    return inputs


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_wheel_metadata(path: Path) -> WheelMetadata:
    try:
        with zipfile.ZipFile(path) as wheel:
            candidates = [
                name
                for name in wheel.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(candidates) != 1:
                _fail(f"wheel must contain exactly one .dist-info/METADATA: {path}")
            message = BytesParser().parsebytes(wheel.read(candidates[0]))
            entry_point_candidates = [
                name
                for name in wheel.namelist()
                if name.endswith(".dist-info/entry_points.txt")
            ]
            if len(entry_point_candidates) > 1:
                _fail(
                    "wheel must contain at most one .dist-info/entry_points.txt: "
                    f"{path}"
                )
            command_entry_points: tuple[tuple[str, str], ...] = ()
            if entry_point_candidates:
                parser = _CaseSensitiveConfigParser(interpolation=None)
                parser.read_string(wheel.read(entry_point_candidates[0]).decode())
                if parser.has_section("taut.commands"):
                    command_entry_points = tuple(sorted(parser.items("taut.commands")))
    except (
        OSError,
        UnicodeDecodeError,
        configparser.Error,
        zipfile.BadZipFile,
        KeyError,
    ) as exc:
        _fail(f"cannot read wheel metadata from {path}: {exc}")
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        _fail(f"wheel metadata is missing Name or Version: {path}")
    return WheelMetadata(
        path=path,
        name=name,
        version=version,
        requirements=tuple(message.get_all("Requires-Dist", [])),
        command_entry_points=command_entry_points,
        sha256=_sha256(path),
    )


def _canonical_project_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements_for_project(metadata: WheelMetadata, project: str) -> tuple[str, ...]:
    matches: list[str] = []
    for requirement in metadata.requirements:
        name = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
        if name is not None and _canonical_project_name(name.group(0)) == project:
            matches.append(requirement)
    return tuple(matches)


def _require_exact_dependency(
    metadata: WheelMetadata, *, project: str, requirement: str
) -> None:
    project_requirements = _requirements_for_project(metadata, project)
    if project_requirements != (requirement,):
        rendered = ", ".join(metadata.requirements) or "<none>"
        _fail(
            f"{metadata.name} {metadata.version} METADATA must contain exactly one "
            f"unmarked Requires-Dist {requirement!r}; found: {rendered}"
        )


def _validate_new_metadata(core: WheelMetadata, summon: WheelMetadata) -> None:
    if _canonical_project_name(core.name) != "taut-chat":
        _fail(f"new core wheel has project name {core.name!r}, expected 'taut-chat'")
    if _canonical_project_name(summon.name) != "taut-summon":
        _fail(
            f"new Summon wheel has project name {summon.name!r}, expected 'taut-summon'"
        )
    _require_exact_dependency(
        summon,
        project="taut-chat",
        requirement=f"taut-chat>={core.version}",
    )
    if core.command_entry_points:
        rendered = ", ".join(
            f"{name}={target}" for name, target in core.command_entry_points
        )
        _fail(
            "new core wheel must not publish taut.commands entry points; "
            f"found: {rendered}"
        )
    if summon.command_entry_points != EXPECTED_SUMMON_COMMAND_ENTRY_POINTS:
        rendered = (
            ", ".join(
                f"{name}={target}" for name, target in summon.command_entry_points
            )
            or "<none>"
        )
        _fail(
            "new Summon wheel must publish exactly the summon and dismiss "
            f"taut.commands entry points; found: {rendered}"
        )


def _clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "UV_PROJECT_ENVIRONMENT",
        "UV_WORKSPACE",
    ):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _format_command(command: list[str]) -> str:
    rendered: list[str] = []
    redact_next = False
    for part in command:
        if redact_next:
            rendered.append("<python-probe>")
            redact_next = False
            continue
        rendered.append(shlex.quote(part))
        redact_next = part == "-c"
    return " ".join(rendered)


def _process_detail(completed: subprocess.CompletedProcess[str]) -> str:
    combined = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if "Traceback (most recent call last)" in combined:
        return "subprocess emitted a Python traceback"
    return " ".join(combined.split())[:2000]


def _terminate_owned_process_group(process: subprocess.Popen[str]) -> None:
    """Kill and reap one command plus descendants owned by this checker."""

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif os.name == "nt":  # pragma: no cover - exercised on Windows CI
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                text=True,
                capture_output=True,
                timeout=10.0,
                check=False,
            )
        else:  # pragma: no cover - defensive platform fallback
            process.kill()
    except ProcessLookupError:
        pass
    process.communicate()


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    expected_returncode: int | None = 0,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
    terminate_process_group: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"[wheel-matrix] + {_format_command(command)}")
    start_new_session = terminate_process_group and os.name == "posix"
    creationflags = (
        int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        if terminate_process_group and os.name == "nt"
        else 0
    )
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=start_new_session,
            creationflags=creationflags,
        )
    except OSError as exc:
        _fail(f"command could not complete: {_format_command(command)}: {exc}")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if terminate_process_group:
            _terminate_owned_process_group(process)
        else:  # pragma: no cover - every production command owns its group
            process.kill()
            process.communicate()
        _fail(f"command timed out after {timeout:g}s: {_format_command(command)}")
    except KeyboardInterrupt:
        if terminate_process_group:
            _terminate_owned_process_group(process)
        else:  # pragma: no cover - every production command owns its group
            process.kill()
            process.communicate()
        raise
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    detail = _process_detail(completed)
    if expected_returncode is not None and completed.returncode != expected_returncode:
        _fail(
            f"command exited {completed.returncode}, expected {expected_returncode}: "
            f"{_format_command(command)}{': ' + detail if detail else ''}"
        )
    if detail == "subprocess emitted a Python traceback":
        _fail(f"command emitted a traceback: {_format_command(command)}")
    return completed


def _resolve_remote_tag(ref: str, *, env: dict[str, str]) -> str:
    expected_commit = EXPECTED_REF_COMMITS.get(ref)
    if expected_commit is None:
        _fail(f"no immutable commit is configured for historical ref {ref!r}")
    remote_ref = f"refs/tags/{ref}"
    completed = _run(
        [
            "git",
            "ls-remote",
            "--tags",
            "origin",
            remote_ref,
            f"{remote_ref}^{{}}",
        ],
        cwd=PROJECT_ROOT,
        env=env,
    )
    resolved: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            resolved[fields[1]] = fields[0]
    commit = resolved.get(f"{remote_ref}^{{}}") or resolved.get(remote_ref)
    if commit is None:
        _fail(f"tag {ref!r} does not exist on origin")
    if commit != expected_commit:
        _fail(f"origin tag {ref!r} resolves to {commit}, expected {expected_commit}")
    print(f"[wheel-matrix] ref={ref} origin_commit={commit}")
    return commit


def _prepare_archive_repository(
    *, refs: tuple[str, ...], work: Path, env: dict[str, str]
) -> Path:
    """Fetch immutable prior tags into a temporary bare object database."""

    repository = work / "prior-artifact.git"
    _run(["git", "init", "--bare", str(repository)], cwd=work, env=env)
    remote = _run(
        ["git", "remote", "get-url", "origin"],
        cwd=PROJECT_ROOT,
        env=env,
    ).stdout.strip()
    if not remote:
        _fail("origin has no fetch URL")
    for ref in refs:
        expected_commit = EXPECTED_REF_COMMITS.get(ref)
        if expected_commit is None:
            _fail(f"no immutable commit is configured for historical ref {ref!r}")
        tag_ref = f"refs/tags/{ref}"
        _run(
            [
                "git",
                f"--git-dir={repository}",
                "fetch",
                "--no-tags",
                remote,
                f"{tag_ref}:{tag_ref}",
            ],
            cwd=work,
            env=env,
        )
        fetched = _run(
            [
                "git",
                f"--git-dir={repository}",
                "rev-parse",
                f"{tag_ref}^{{commit}}",
            ],
            cwd=work,
            env=env,
        ).stdout.strip()
        if fetched != expected_commit:
            _fail(
                f"fetched tag {ref!r} resolves to {fetched}, expected {expected_commit}"
            )
    return repository


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive) as source:
            for member in source.getmembers():
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    _fail(f"git archive contains unsafe path {member.name!r}")
                if member.issym() or member.islnk():
                    target = Path(member.linkname)
                    if target.is_absolute() or ".." in target.parts:
                        _fail(
                            "git archive contains unsafe link target "
                            f"{member.linkname!r}"
                        )
            source.extractall(destination)
    except (OSError, tarfile.TarError) as exc:
        _fail(f"cannot extract git archive {archive}: {exc}")


def _export_ref(
    *,
    repository: Path,
    commit: str,
    destination: Path,
    env: dict[str, str],
) -> None:
    destination.mkdir(parents=True)
    archive = destination.parent / f"{destination.name}.tar"
    _run(
        [
            "git",
            f"--git-dir={repository}",
            "archive",
            "--format=tar",
            f"--output={archive}",
            commit,
        ],
        cwd=destination.parent,
        env=env,
    )
    _safe_extract_tar(archive, destination)


def _find_built_wheel(directory: Path, expected_project: str) -> Path:
    matches: list[Path] = []
    for candidate in sorted(directory.glob("*.whl")):
        metadata = _read_wheel_metadata(candidate)
        if _canonical_project_name(metadata.name) == expected_project:
            matches.append(candidate)
    if len(matches) != 1:
        _fail(
            f"expected exactly one {expected_project} wheel in {directory}, "
            f"found {len(matches)}"
        )
    return matches[0]


def _build_historical_summon(
    *,
    summon_source: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> Path:
    summon_out = work / "historical-summon-wheel"
    summon_out.mkdir()
    _run(
        [
            uv,
            "build",
            "--wheel",
            str(summon_source / "extensions" / "taut_summon"),
            "--out-dir",
            str(summon_out),
        ],
        cwd=summon_source,
        env=env,
    )
    historical_summon = _find_built_wheel(summon_out, "taut-summon")
    metadata = _read_wheel_metadata(historical_summon)
    if metadata.version != EXPECTED_HISTORICAL_SUMMON_VERSION:
        _fail(
            f"historical Summon wheel version is {metadata.version}, expected "
            f"{EXPECTED_HISTORICAL_SUMMON_VERSION}"
        )
    _print_wheel_evidence("historical_summon", metadata)
    return historical_summon


def _build_historical_mcp(
    *,
    mcp_source: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> Path:
    mcp_out = work / "historical-mcp-wheel"
    mcp_out.mkdir()
    _run(
        [
            uv,
            "build",
            "--wheel",
            str(mcp_source / "extensions" / "taut_mcp"),
            "--out-dir",
            str(mcp_out),
        ],
        cwd=mcp_source,
        env=env,
    )
    historical_mcp = _find_built_wheel(mcp_out, "taut-mcp")
    metadata = _read_wheel_metadata(historical_mcp)
    if metadata.version != EXPECTED_HISTORICAL_MCP_VERSION:
        _fail(
            f"historical MCP wheel version is {metadata.version}, expected "
            f"{EXPECTED_HISTORICAL_MCP_VERSION}"
        )
    _print_wheel_evidence("historical_mcp", metadata)
    return historical_mcp


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _python_version(python: str) -> tuple[int, int]:
    """Return (major, minor) for a candidate interpreter, or (0, 0) if it cannot run."""
    try:
        completed = subprocess.run(
            [
                python,
                "-c",
                "import sys; print(sys.version_info.major); print(sys.version_info.minor)",
            ],
            cwd=PROJECT_ROOT,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=10.0,
            check=False,
        )
    except OSError:
        return 0, 0

    if completed.returncode != 0:
        return 0, 0
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return 0, 0
    try:
        return int(lines[0]), int(lines[1])
    except ValueError:
        return 0, 0


def _matrix_python_candidates() -> tuple[str, ...]:
    candidates: list[str] = []
    override = os.environ.get("TAUT_WHEEL_MATRIX_PYTHON")
    if override:
        candidates.append(override)
    candidates.append(sys.executable)
    for minor in range(14, MATRIX_PYTHON_MIN_MINOR - 1, -1):
        candidates.append(f"python3.{minor}")
    candidates.append("python3")
    candidates.append("python")
    return tuple(dict.fromkeys(candidates))


def _candidate_path(candidate: str) -> Path:
    resolved = shutil.which(candidate)
    return Path(resolved if resolved is not None else candidate)


def _resolve_matrix_python() -> Path:
    for candidate in _matrix_python_candidates():
        python = str(_candidate_path(candidate))
        major, minor = _python_version(python)
        if major < 3:
            continue
        if major == 3 and minor < MATRIX_PYTHON_MIN_MINOR:
            continue
        if not python or major == 0:
            continue
        return Path(python)
    _fail(
        "could not find a Python interpreter >= 3."
        f"{MATRIX_PYTHON_MIN_MINOR} for wheel-matrix environments"
    )


def _create_environment(
    *, name: str, work: Path, env: dict[str, str], uv: str
) -> tuple[Path, Path]:
    case_root = work / name
    case_root.mkdir()
    venv = case_root / "venv"
    matrix_python = _resolve_matrix_python()
    _run(
        [uv, "venv", "--python", str(matrix_python), str(venv)],
        cwd=case_root,
        env=env,
    )
    python = _venv_python(venv)
    if not python.is_file():
        _fail(f"uv did not create an environment interpreter: {python}")
    return case_root, python


def _install(
    *,
    python: Path,
    artifacts: tuple[Path, ...],
    cwd: Path,
    env: dict[str, str],
    uv: str,
) -> None:
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            *(str(path) for path in artifacts),
        ],
        cwd=cwd,
        env=env,
    )
    frozen = _run(
        [uv, "pip", "freeze", "--python", str(python)],
        cwd=cwd,
        env=env,
    )
    print(f"[wheel-matrix] resolved[{cwd.name}]:")
    print(frozen.stdout.rstrip())


_ISOLATION_PROBE = r"""
import importlib.metadata
import json
import re
import sys
from pathlib import Path

checkout = Path(sys.argv[1]).resolve()
venv = Path(sys.argv[2]).resolve()
base_prefix = Path(sys.base_prefix).resolve()

for raw_entry in sys.path:
    if not raw_entry:
        continue
    entry = Path(raw_entry).resolve()
    if entry == checkout or checkout in entry.parents:
        raise SystemExit(f"checkout path leaked into sys.path: {entry}")
    if not (
        entry == venv
        or venv in entry.parents
        or entry == base_prefix
        or base_prefix in entry.parents
    ):
        raise SystemExit(f"external source path leaked into sys.path: {entry}")

def assert_installed(module):
    path = Path(module.__file__).resolve()
    if venv not in path.parents:
        raise SystemExit(f"module did not import from isolated environment: {path}")
    if "site-packages" not in path.parts and "dist-packages" not in path.parts:
        raise SystemExit(f"module did not import from site-packages: {path}")
    return str(path)

"""


def _run_python_probe(
    *, python: Path, code: str, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    guarded_code = (
        textwrap.dedent(_ISOLATION_PROBE)
        + "\ntry:\n"
        + textwrap.indent(textwrap.dedent(code), "    ")
        + "\nexcept Exception as exc:\n"
        + "    detail = str(exc).replace('\\n', ' ')\n"
        + "    raise SystemExit(f'probe failed: {type(exc).__name__}: {detail}')\n"
    )
    return _run(
        [
            str(python),
            "-I",
            "-c",
            guarded_code,
            str(PROJECT_ROOT),
            str(python.parent.parent),
        ],
        cwd=cwd,
        env=env,
        timeout=CONTROL_SMOKE_TIMEOUT_SECONDS,
        terminate_process_group=True,
    )


def _case_new_core(*, wheel: Path, work: Path, env: dict[str, str], uv: str) -> None:
    case_root, python = _create_environment(
        name="01-new-core", work=work, env=env, uv=uv
    )
    _install(python=python, artifacts=(wheel,), cwd=case_root, env=env, uv=uv)
    probe = _run_python_probe(
        python=python,
        cwd=case_root,
        env=env,
        code=r"""
import taut
from taut.watcher import TautBaseWatcher

taut_path = assert_installed(taut)

class ObsoleteReactor(TautBaseWatcher):
    def process_once(self):
        raise AssertionError("obsolete lifecycle template ran")

db = Path.cwd() / "guard-must-not-touch.db"
try:
    ObsoleteReactor(
        {"artifact.input": {"handler": lambda *_args: None}},
        db=db,
    )
except RuntimeError as exc:
    diagnostic = str(exc)
    if "upgrade taut-summon" not in diagnostic:
        raise SystemExit(f"unexpected compatibility diagnostic: {diagnostic}")
else:
    raise SystemExit("obsolete reactor construction was accepted")
if db.exists():
    raise SystemExit("obsolete reactor touched the database before rejection")

print(json.dumps({
    "case": "new_core",
    "simplebroker": importlib.metadata.version("simplebroker"),
    "taut_chat": importlib.metadata.version("taut-chat"),
    "taut_path": taut_path,
    "guard": "rejected_before_broker_io",
}, sort_keys=True))
""",
    )
    print(probe.stdout.rstrip())


def _case_new_core_command_fallback(
    *,
    new_core: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> None:
    case_root, python = _create_environment(
        name="03-command-core-only", work=work, env=env, uv=uv
    )
    _install(
        python=python,
        artifacts=(new_core,),
        cwd=case_root,
        env=env,
        uv=uv,
    )
    probe = _run_python_probe(
        python=python,
        cwd=case_root,
        env=env,
        code=r"""
from io import StringIO

import taut
from taut.commands._dispatch import dispatch

taut_path = assert_installed(taut)
stdout = StringIO()
stderr = StringIO()
result = dispatch(
    ["summon", "reviewer"],
    stdin=StringIO(),
    stdout=stdout,
    stderr=stderr,
)
expected = (
    "taut summon requires the taut-summon extension "
    "(pipx inject taut-chat taut-summon)\n"
)
if result != 1 or stdout.getvalue() or stderr.getvalue() != expected:
    raise SystemExit(
        "core-only summon did not produce the exact install hint: "
        f"result={result} stdout={stdout.getvalue()!r} stderr={stderr.getvalue()!r}"
    )
if any(name == "taut_summon" or name.startswith("taut_summon.") for name in sys.modules):
    raise SystemExit("core-only summon imported taut_summon")

print(json.dumps({
    "case": "command_core_only",
    "summon": "install_hint",
    "taut_path": taut_path,
}, sort_keys=True))
""",
    )
    print(probe.stdout.rstrip())


def _case_paired_control_smoke(
    *,
    new_core: Path,
    new_summon: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> None:
    case_root, python = _create_environment(
        name="02-paired-control", work=work, env=env, uv=uv
    )
    _install(
        python=python,
        artifacts=(new_core, new_summon),
        cwd=case_root,
        env=env,
        uv=uv,
    )
    probe = _run_python_probe(
        python=python,
        cwd=case_root,
        env=env,
        code=r"""
import os
import subprocess
import time

import taut
import taut_summon
from taut import TautClient
from taut_summon.controller import SummonController

taut_path = assert_installed(taut)
summon_path = assert_installed(taut_summon)
Path(".taut.toml").write_text(
    "version = 1\n"
    "backend = \"sqlite\"\n"
    "target = \"unused.db\"\n\n"
    "[terminal_text]\n"
    "escape_patterns = [\"CUSTOM\"]\n",
    encoding="utf-8",
)
if taut.escape_terminal_text("CUSTOM\x1b") != (
    "\\x43\\x55\\x53\\x54\\x4f\\x4d\\x1b"
):
    raise SystemExit("installed core terminal policy/resource probe failed")
claims = {
    entry_point.name: (
        entry_point.dist.metadata.get("Name"),
        entry_point.value,
    )
    for entry_point in importlib.metadata.entry_points(group="taut.commands")
}
expected_claims = {
    "dismiss": (
        "taut-summon",
        "taut_summon.command_manifest:dismiss",
    ),
    "summon": (
        "taut-summon",
        "taut_summon.command_manifest:summon",
    ),
}
if claims != expected_claims:
    raise SystemExit(f"unexpected installed command ownership: {claims!r}")

db = Path.cwd() / "control-smoke.db"
TautClient.init(db_path=db)
command = [
    sys.executable,
    "-I",
    "-m",
    "taut",
    "--db",
    str(db),
    "summon",
    "artifact-probe",
    "--provider",
    "scripted",
    "--detach",
]
child_env = os.environ.copy()
child_env.pop("PYTHONPATH", None)
child_env["PYTHONNOUSERSITE"] = "1"
child_env["TAUT_SUMMON_CONTROL_INTERVAL"] = "0.05"
driver = subprocess.Popen(
    command,
    cwd=Path.cwd(),
    env=child_env,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
try:
    controller = SummonController(db_path=db)
    deadline = time.monotonic() + 45.0
    live = ()
    while time.monotonic() < deadline:
        if driver.poll() is not None:
            stdout, stderr = driver.communicate(timeout=2)
            raise SystemExit(
                f"summon driver exited before readiness rc={driver.returncode} "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
        try:
            live = controller.list_live()
        except Exception:
            live = ()
        if any(member.name == "artifact-probe" for member in live):
            break
        time.sleep(0.05)
    else:
        raise SystemExit("summon driver did not publish live ledger evidence")

    status = controller.status("artifact-probe")
    if status.driver != "alive" or status.provider != "scripted":
        raise SystemExit(f"unexpected public controller status: {status!r}")

    dismiss = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "taut",
            "--db",
            str(db),
            "dismiss",
            "artifact-probe",
        ],
        cwd=Path.cwd(),
        env=child_env,
        text=True,
        capture_output=True,
        timeout=45.0,
        check=False,
    )
    if dismiss.returncode != 0 or "stopped 'artifact-probe'" not in dismiss.stdout:
        raise SystemExit(
            f"native DISMISS failed rc={dismiss.returncode} "
            f"stdout={dismiss.stdout!r} stderr={dismiss.stderr!r}"
        )
    try:
        driver.wait(timeout=15.0)
    except subprocess.TimeoutExpired:
        raise SystemExit("summon driver remained live after DISMISS")
    if driver.returncode != 0:
        stdout, stderr = driver.communicate(timeout=2)
        raise SystemExit(
            f"summon driver exited nonzero after DISMISS rc={driver.returncode} "
            f"stdout={stdout!r} stderr={stderr!r}"
        )
    driver_stdout, driver_stderr = driver.communicate(timeout=2)
    all_process_output = "\n".join(
        (
            dismiss.stdout,
            dismiss.stderr,
            driver_stdout,
            driver_stderr,
        )
    )
    if "Traceback (most recent call last)" in all_process_output:
        raise SystemExit("paired control smoke emitted an unhandled traceback")
    if controller.list_live():
        raise SystemExit("ledger still owns live driver evidence after DISMISS")
    print(json.dumps({
        "case": "paired_control",
        "command_owner": "taut-summon",
        "status": "ok",
        "dismiss": "ok",
        "ledger": "released",
        "taut_path": taut_path,
        "summon_path": summon_path,
    }, sort_keys=True))
finally:
    if driver.poll() is None:
        driver.terminate()
        try:
            driver.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            driver.kill()
            driver.wait(timeout=5.0)
""",
    )
    print(probe.stdout.rstrip())


def _stop_interactive_process(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif os.name == "nt":  # pragma: no cover - exercised on Windows CI
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                text=True,
                capture_output=True,
                timeout=10.0,
                check=False,
            )
        else:  # pragma: no cover - defensive platform fallback
            process.kill()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10.0)


class _HistoricalMcpStdioDriver:
    def __init__(
        self,
        *,
        process: subprocess.Popen[str],
        token: str,
        stage_timeout: float,
        shutdown_timeout: float,
    ) -> None:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            _stop_interactive_process(process)
            _fail("installed MCP stdio pipes were not created")
        self.process = process
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.stderr = process.stderr
        self.token = token
        self.stage_timeout = stage_timeout
        self.shutdown_timeout = shutdown_timeout
        self.received: queue.Queue[object] = queue.Queue()
        self.eof = object()
        self.reader = threading.Thread(target=self._read_stdout, daemon=True)
        self.reader.start()

    @classmethod
    def start(
        cls,
        *,
        command: tuple[str, ...],
        token: str,
        cwd: Path,
        env: dict[str, str],
        stage_timeout: float,
        shutdown_timeout: float,
    ) -> _HistoricalMcpStdioDriver:
        child_env = env.copy()
        child_env.pop("PYTHONPATH", None)
        child_env["PYTHONNOUSERSITE"] = "1"
        print(f"[wheel-matrix] + {_format_command(list(command))}")
        creationflags = (
            int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            if os.name == "nt"
            else 0
        )
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=child_env,
                text=True,
                bufsize=1,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
                creationflags=creationflags,
            )
        except OSError as exc:
            detail = str(exc).replace(token, "<redacted>")
            _fail(f"installed MCP stdio could not start: {detail}")
        return cls(
            process=process,
            token=token,
            stage_timeout=stage_timeout,
            shutdown_timeout=shutdown_timeout,
        )

    def _redact(self, value: object) -> str:
        return str(value).replace(self.token, "<redacted>")

    def _fail(self, message: str) -> NoReturn:
        _fail(self._redact(message))

    def _read_stdout(self) -> None:
        try:
            for line in self.stdout:
                self.received.put(json.loads(line))
        except (OSError, UnicodeError, ValueError) as exc:
            self.received.put(("reader-error", self._redact(exc)))
        finally:
            self.received.put(self.eof)

    def _send(self, frame: dict[str, object]) -> None:
        try:
            self.stdin.write(
                json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n"
            )
            self.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._fail(f"server input failed: {exc}")

    def _receive(self, request_id: int, stage: str) -> dict[str, object]:
        deadline = time.monotonic() + self.stage_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._fail(f"{stage} timed out")
            try:
                frame = self.received.get(timeout=remaining)
            except queue.Empty:
                self._fail(f"{stage} timed out")
            if frame is self.eof:
                self._fail(f"server stdout closed during {stage}")
            if isinstance(frame, tuple) and frame[0] == "reader-error":
                self._fail(f"invalid server output during {stage}: {frame[1]}")
            if not isinstance(frame, dict):
                self._fail(f"invalid server frame during {stage}")
            if self.token in json.dumps(frame, sort_keys=True):
                self._fail(f"server echoed continuity selector during {stage}")
            if frame.get("id") == request_id:
                return frame

    def _tool_result(self, request_id: int, stage: str) -> dict[str, object]:
        frame = self._receive(request_id, stage)
        if "error" in frame:
            self._fail(f"{stage} returned a protocol error")
        result = frame.get("result")
        if not isinstance(result, dict) or result.get("isError") is True:
            self._fail(f"{stage} returned a tool error")
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            self._fail(f"{stage} omitted structured content")
        return structured

    def initialize(self) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "wheel-matrix", "version": "1"},
                },
            }
        )
        initialized = self._receive(1, "initialize")
        if "error" in initialized or not isinstance(initialized.get("result"), dict):
            self._fail("initialize returned a protocol error")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def attach(
        self, *, workspace: Path, member_id: str, member_name: str
    ) -> tuple[dict[str, object], str]:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "attach_workspace",
                    "arguments": {"workspace": str(workspace), "token": self.token},
                },
            }
        )
        attached = self._tool_result(2, "attach_workspace")
        records = attached.get("records")
        if not isinstance(records, list) or len(records) != 1:
            self._fail("attach_workspace returned the wrong record count")
        record = records[0]
        if (
            not isinstance(record, dict)
            or record.get("status") != "ready"
            or record.get("member_id") != member_id
            or record.get("name") != member_name
        ):
            self._fail("attach_workspace returned the wrong ready member")
        canonical = record.get("workspace")
        if not isinstance(canonical, str) or canonical != os.path.realpath(workspace):
            self._fail("attach_workspace returned the wrong canonical workspace")
        return record, canonical

    def assert_listed(self, record: dict[str, object]) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_workspaces", "arguments": {}},
            }
        )
        if self._tool_result(3, "list_workspaces").get("records") != [record]:
            self._fail("list_workspaces did not retain the attached workspace")

    def detach(self, canonical: str) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "detach_workspace",
                    "arguments": {"workspace": canonical},
                },
            }
        )
        detached_records = self._tool_result(4, "detach_workspace").get("records")
        if (
            not isinstance(detached_records, list)
            or len(detached_records) != 1
            or not isinstance(detached_records[0], dict)
            or detached_records[0].get("status") != "detached"
        ):
            self._fail("detach_workspace did not report detached state")

    def assert_empty(self) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "list_workspaces", "arguments": {}},
            }
        )
        listed = self._tool_result(5, "list_workspaces after detach")
        if listed.get("records") != [] or listed.get("empty") is not True:
            self._fail("list_workspaces retained state after detach")

    def shutdown(self) -> None:
        self.stdin.close()
        try:
            returncode = self.process.wait(timeout=self.shutdown_timeout)
        except subprocess.TimeoutExpired:
            self._fail("clean_shutdown timed out")
        self.reader.join(timeout=5.0)
        if self.reader.is_alive():
            self._fail("clean_shutdown left the stdout reader live")
        stderr = self._redact(self.stderr.read())
        if returncode != 0:
            self._fail(f"clean_shutdown exited {returncode}: {stderr[:500]}")
        if "Traceback (most recent call last)" in stderr:
            self._fail("clean_shutdown emitted a traceback")

    def close(self) -> None:
        if self.process.poll() is None:
            _stop_interactive_process(self.process)
        self.reader.join(timeout=5.0)


def _drive_historical_mcp_stdio(
    *,
    command: tuple[str, ...],
    workspace: Path,
    token: str,
    member_id: str,
    member_name: str,
    cwd: Path,
    env: dict[str, str],
    stage_timeout: float = MCP_STAGE_TIMEOUT_SECONDS,
    shutdown_timeout: float = MCP_SHUTDOWN_TIMEOUT_SECONDS,
) -> None:
    """Drive the retained legacy lifecycle without exposing its selector."""

    driver = _HistoricalMcpStdioDriver.start(
        command=command,
        token=token,
        cwd=cwd,
        env=env,
        stage_timeout=stage_timeout,
        shutdown_timeout=shutdown_timeout,
    )
    try:
        driver.initialize()
        record, canonical = driver.attach(
            workspace=workspace,
            member_id=member_id,
            member_name=member_name,
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


def _case_historical_mcp_attach(
    *,
    new_core: Path,
    historical_mcp: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> None:
    case_root, python = _create_environment(
        name="04-historical-mcp", work=work, env=env, uv=uv
    )
    _install(
        python=python,
        artifacts=(new_core, historical_mcp),
        cwd=case_root,
        env=env,
        uv=uv,
    )
    selector_path = case_root / ".historical-mcp-selector.json"
    probe = _run_python_probe(
        python=python,
        cwd=case_root,
        env=env,
        code=r"""
import os

import taut
import taut_mcp
from taut import TautClient

taut_path = assert_installed(taut)
mcp_path = assert_installed(taut_mcp)
workspace = Path.cwd() / "workspace"
workspace.mkdir()
db = workspace / ".taut.db"
TautClient.init(db_path=db)
owner = TautClient(db_path=db, as_name="matrix-member")
try:
    owner.join("general")
    member = owner.last_created_member
    if member is None or member.token is None:
        raise SystemExit("candidate core did not create a continuity selector")
    selector_path = Path.cwd() / ".historical-mcp-selector.json"
    descriptor = os.open(
        selector_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "member_id": member.member_id,
                "member_name": member.name,
                "token": member.token,
            },
            stream,
            sort_keys=True,
        )
finally:
    owner.close()
print(json.dumps({
    "case": "historical_mcp_bootstrap",
    "mcp_path": mcp_path,
    "status": "ok",
    "taut_path": taut_path,
}, sort_keys=True))
""",
    )
    print(probe.stdout.rstrip())
    try:
        selector = json.loads(selector_path.read_text(encoding="utf-8"))
        token = selector.get("token")
        member_id = selector.get("member_id")
        member_name = selector.get("member_name")
        if not all(
            isinstance(value, str) and value
            for value in (token, member_id, member_name)
        ):
            _fail("candidate core bootstrap emitted invalid selector evidence")
        console = python.with_name("taut-mcp.exe" if os.name == "nt" else "taut-mcp")
        if not console.is_file():
            _fail("installed taut-mcp console entry point is missing")
        _drive_historical_mcp_stdio(
            command=(str(console),),
            workspace=case_root / "workspace",
            token=token,
            member_id=member_id,
            member_name=member_name,
            cwd=case_root,
            env=env,
        )
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"cannot read candidate core selector evidence: {exc}")
    finally:
        selector_path.unlink(missing_ok=True)


def _case_historical_summon_metadata(metadata: WheelMetadata) -> None:
    if _canonical_project_name(metadata.name) != "taut-summon":
        _fail(
            "historical Summon wheel has project name "
            f"{metadata.name!r}, expected 'taut-summon'"
        )
    if metadata.version != EXPECTED_HISTORICAL_SUMMON_VERSION:
        _fail(
            f"historical Summon wheel version is {metadata.version}, expected "
            f"{EXPECTED_HISTORICAL_SUMMON_VERSION}"
        )
    legacy_requirement = f"taut>={EXPECTED_HISTORICAL_SUMMON_VERSION}"
    project_requirements = _requirements_for_project(metadata, "taut")
    if project_requirements != (legacy_requirement,):
        rendered = ", ".join(metadata.requirements) or "<none>"
        _fail(
            "historical Summon METADATA must contain exactly one Requires-Dist "
            f"{legacy_requirement!r}; found: {rendered}"
        )
    if _requirements_for_project(metadata, "taut-chat"):
        _fail("historical Summon METADATA must not require taut-chat")
    print(
        json.dumps(
            {
                "case": "historical_summon_metadata",
                "relation_to_current_core": "unrelated_distribution",
                "requires": legacy_requirement,
                "version": metadata.version,
            },
            sort_keys=True,
        )
    )


def _case_historical_mcp_metadata(metadata: WheelMetadata) -> None:
    if _canonical_project_name(metadata.name) != "taut-mcp":
        _fail(
            "historical MCP wheel has project name "
            f"{metadata.name!r}, expected 'taut-mcp'"
        )
    if metadata.version != EXPECTED_HISTORICAL_MCP_VERSION:
        _fail(
            f"historical MCP wheel version is {metadata.version}, expected "
            f"{EXPECTED_HISTORICAL_MCP_VERSION}"
        )
    requirement = f"taut-chat>={EXPECTED_HISTORICAL_MCP_VERSION}"
    core_requirements = _requirements_for_project(metadata, "taut-chat")
    if core_requirements != (requirement,):
        rendered = ", ".join(metadata.requirements) or "<none>"
        _fail(
            "historical MCP METADATA must contain exactly one open Requires-Dist "
            f"{requirement!r}; found: {rendered}"
        )
    print(
        json.dumps(
            {
                "case": "historical_mcp_metadata",
                "candidate_core_admitted": True,
                "requires": requirement,
                "status": "ok",
            },
            sort_keys=True,
        )
    )


def _print_wheel_evidence(label: str, metadata: WheelMetadata) -> None:
    print(
        "[wheel-matrix] "
        f"artifact={label} project={metadata.name} version={metadata.version} "
        f"sha256={metadata.sha256} path={metadata.path}"
    )


def _check(inputs: Inputs) -> None:
    core_metadata = _read_wheel_metadata(inputs.new_core)
    summon_metadata = _read_wheel_metadata(inputs.new_summon)
    _validate_new_metadata(core_metadata, summon_metadata)
    _print_wheel_evidence("new_core", core_metadata)
    _print_wheel_evidence("new_summon", summon_metadata)

    env = _clean_environment()
    git = shutil.which("git")
    uv = shutil.which("uv")
    if git is None:
        _fail("required command not found on PATH: git")
    if uv is None:
        _fail("required command not found on PATH: uv")

    historical_summon_commit = _resolve_remote_tag(
        inputs.historical_summon_ref, env=env
    )
    historical_mcp_commit = _resolve_remote_tag(inputs.historical_mcp_ref, env=env)
    with tempfile.TemporaryDirectory(prefix="taut-wheel-matrix-") as raw_work:
        work = Path(raw_work)
        historical_summon_source = work / "historical-summon-source"
        historical_mcp_source = work / "historical-mcp-source"
        archive_repository = _prepare_archive_repository(
            refs=(inputs.historical_summon_ref, inputs.historical_mcp_ref),
            work=work,
            env=env,
        )
        _export_ref(
            repository=archive_repository,
            commit=historical_summon_commit,
            destination=historical_summon_source,
            env=env,
        )
        _export_ref(
            repository=archive_repository,
            commit=historical_mcp_commit,
            destination=historical_mcp_source,
            env=env,
        )
        historical_summon = _build_historical_summon(
            summon_source=historical_summon_source,
            work=work,
            env=env,
            uv=uv,
        )
        historical_mcp = _build_historical_mcp(
            mcp_source=historical_mcp_source,
            work=work,
            env=env,
            uv=uv,
        )
        _case_historical_summon_metadata(_read_wheel_metadata(historical_summon))
        _case_historical_mcp_metadata(_read_wheel_metadata(historical_mcp))
        _case_new_core(wheel=inputs.new_core, work=work, env=env, uv=uv)
        _case_paired_control_smoke(
            new_core=inputs.new_core,
            new_summon=inputs.new_summon,
            work=work,
            env=env,
            uv=uv,
        )
        _case_new_core_command_fallback(
            new_core=inputs.new_core,
            work=work,
            env=env,
            uv=uv,
        )
        _case_historical_mcp_attach(
            new_core=inputs.new_core,
            historical_mcp=historical_mcp,
            work=work,
            env=env,
            uv=uv,
        )
    print(
        "[wheel-matrix] all four installed-wheel cases and historical "
        "metadata probes passed"
    )


def main(argv: list[str] | None = None) -> int:
    try:
        inputs = _parse_args(argv)
        _check(inputs)
    except WheelMatrixError as exc:
        print(f"core/Summon wheel-matrix check failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("core/Summon wheel-matrix check interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-065] exception
        detail = str(exc).replace("\n", " ")
        print(
            "core/Summon wheel-matrix check failed: internal checker "
            f"error ({type(exc).__name__}): {detail}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
