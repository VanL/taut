#!/usr/bin/env python3
"""Check the installed core/Summon wheel matrix required by [SUM-12]."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from typing import NoReturn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PREVIOUS_COMMIT = "766e3aaf84f75046a57ef769b9c802148b42e71a"
EXPECTED_PREVIOUS_CORE_VERSION = "0.5.0"
EXPECTED_COMMAND_ROLLOUT_COMMIT = "b03709452cf4d5962b0d7204b0dab78b9bafd524"
EXPECTED_COMMAND_ROLLOUT_CORE_VERSION = "0.5.4"
EXPECTED_COMMAND_ROLLOUT_SUMMON_VERSION = "0.5.4"
MINIMUM_SIMPLEBROKER_VERSION = "5.3.0"
COMMAND_TIMEOUT_SECONDS = 180.0
CONTROL_SMOKE_TIMEOUT_SECONDS = 180.0
EXPECTED_CORE_REF = "v0.5.0"
EXPECTED_SUMMON_REF = "taut_summon/v0.5.0"
EXPECTED_COMMAND_CORE_REF = "v0.5.4"
EXPECTED_COMMAND_SUMMON_REF = "taut_summon/v0.5.4"
EXPECTED_REF_COMMITS = {
    EXPECTED_CORE_REF: EXPECTED_PREVIOUS_COMMIT,
    EXPECTED_SUMMON_REF: EXPECTED_PREVIOUS_COMMIT,
    EXPECTED_COMMAND_CORE_REF: EXPECTED_COMMAND_ROLLOUT_COMMIT,
    EXPECTED_COMMAND_SUMMON_REF: EXPECTED_COMMAND_ROLLOUT_COMMIT,
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


@dataclass(frozen=True, slots=True)
class WheelMetadata:
    path: Path
    name: str
    version: str
    requirements: tuple[str, ...]
    command_entry_points: tuple[tuple[str, str], ...]
    sha256: str


@dataclass(frozen=True, slots=True)
class Inputs:
    new_core: Path
    new_summon: Path
    previous_core_ref: str
    previous_summon_ref: str
    previous_command_core_ref: str
    previous_command_summon_ref: str


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
    parser.add_argument("--previous-core-ref", required=True, metavar="REF")
    parser.add_argument("--previous-summon-ref", required=True, metavar="REF")
    parser.add_argument("--previous-command-core-ref", required=True, metavar="REF")
    parser.add_argument("--previous-command-summon-ref", required=True, metavar="REF")
    args = parser.parse_args(argv)
    inputs = Inputs(
        new_core=_required_wheel(args.new_core, "new core"),
        new_summon=_required_wheel(args.new_summon, "new Summon"),
        previous_core_ref=args.previous_core_ref,
        previous_summon_ref=args.previous_summon_ref,
        previous_command_core_ref=args.previous_command_core_ref,
        previous_command_summon_ref=args.previous_command_summon_ref,
    )
    if inputs.previous_core_ref != EXPECTED_CORE_REF:
        _fail(f"previous core ref must be immutable release ref {EXPECTED_CORE_REF!r}")
    if inputs.previous_summon_ref != EXPECTED_SUMMON_REF:
        _fail(
            f"previous Summon ref must be immutable release ref {EXPECTED_SUMMON_REF!r}"
        )
    if inputs.previous_command_core_ref != EXPECTED_COMMAND_CORE_REF:
        _fail(
            "command-rollout core ref must be immutable release ref "
            f"{EXPECTED_COMMAND_CORE_REF!r}"
        )
    if inputs.previous_command_summon_ref != EXPECTED_COMMAND_SUMMON_REF:
        _fail(
            "command-rollout Summon ref must be immutable release ref "
            f"{EXPECTED_COMMAND_SUMMON_REF!r}"
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


def _require_simplebroker_floor(metadata: WheelMetadata) -> None:
    project_requirements = _requirements_for_project(metadata, "simplebroker")
    match = (
        re.fullmatch(r"simplebroker>=(\d+)\.(\d+)\.(\d+)", project_requirements[0])
        if len(project_requirements) == 1
        else None
    )
    if match is None or tuple(int(part) for part in match.groups()) < (5, 3, 0):
        rendered = ", ".join(metadata.requirements) or "<none>"
        _fail(
            f"{metadata.name} {metadata.version} METADATA must contain exactly one "
            "unmarked simplebroker>=X.Y.Z requirement with X.Y.Z >= 5.3.0; "
            f"found: {rendered}"
        )


def _validate_new_metadata(core: WheelMetadata, summon: WheelMetadata) -> None:
    if _canonical_project_name(core.name) != "taut":
        _fail(f"new core wheel has project name {core.name!r}, expected 'taut'")
    if _canonical_project_name(summon.name) != "taut-summon":
        _fail(
            f"new Summon wheel has project name {summon.name!r}, expected 'taut-summon'"
        )
    _require_simplebroker_floor(core)
    _require_exact_dependency(
        summon,
        project="taut",
        requirement=f"taut>={core.version}",
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


def _build_previous_wheels(
    *,
    core_source: Path,
    summon_source: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> tuple[Path, Path]:
    core_out = work / "previous-core-wheel"
    summon_out = work / "previous-summon-wheel"
    core_out.mkdir()
    summon_out.mkdir()
    _run(
        [uv, "build", "--wheel", "--out-dir", str(core_out)],
        cwd=core_source,
        env=env,
    )
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
    previous_core = _find_built_wheel(core_out, "taut")
    previous_summon = _find_built_wheel(summon_out, "taut-summon")
    previous_core_metadata = _read_wheel_metadata(previous_core)
    previous_summon_metadata = _read_wheel_metadata(previous_summon)
    if previous_core_metadata.version != EXPECTED_PREVIOUS_CORE_VERSION:
        _fail(
            f"prior core wheel version is {previous_core_metadata.version}, "
            f"expected {EXPECTED_PREVIOUS_CORE_VERSION}"
        )
    if previous_summon_metadata.version != EXPECTED_PREVIOUS_CORE_VERSION:
        _fail(
            f"prior Summon wheel version is {previous_summon_metadata.version}, "
            f"expected {EXPECTED_PREVIOUS_CORE_VERSION}"
        )
    _print_wheel_evidence("previous_core", previous_core_metadata)
    _print_wheel_evidence("previous_summon", previous_summon_metadata)
    return previous_core, previous_summon


def _build_previous_command_summon(
    *,
    summon_source: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> Path:
    summon_out = work / "previous-command-summon-wheel"
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
    previous_summon = _find_built_wheel(summon_out, "taut-summon")
    metadata = _read_wheel_metadata(previous_summon)
    if metadata.version != EXPECTED_COMMAND_ROLLOUT_SUMMON_VERSION:
        _fail(
            f"command-rollout Summon wheel version is {metadata.version}, expected "
            f"{EXPECTED_COMMAND_ROLLOUT_SUMMON_VERSION}"
        )
    _print_wheel_evidence("command_previous_summon", metadata)
    return previous_summon


def _build_previous_command_core(
    *,
    core_source: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> Path:
    core_out = work / "previous-command-core-wheel"
    core_out.mkdir()
    _run(
        [uv, "build", "--wheel", "--out-dir", str(core_out)],
        cwd=core_source,
        env=env,
    )
    previous_core = _find_built_wheel(core_out, "taut")
    metadata = _read_wheel_metadata(previous_core)
    if metadata.version != EXPECTED_COMMAND_ROLLOUT_CORE_VERSION:
        _fail(
            f"command-rollout core wheel version is {metadata.version}, expected "
            f"{EXPECTED_COMMAND_ROLLOUT_CORE_VERSION}"
        )
    _print_wheel_evidence("command_previous_core", metadata)
    return previous_core


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _create_environment(
    *, name: str, work: Path, env: dict[str, str], uv: str
) -> tuple[Path, Path]:
    case_root = work / name
    case_root.mkdir()
    venv = case_root / "venv"
    _run(
        [uv, "venv", "--python", sys.executable, str(venv)],
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

def release_tuple(version):
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise SystemExit(f"unrecognized SimpleBroker version: {version}")
    return tuple(int(part) for part in match.groups())

simplebroker_version = importlib.metadata.version("simplebroker")
if release_tuple(simplebroker_version) < (5, 3, 0):
    raise SystemExit(f"SimpleBroker below 5.3.0 resolved: {simplebroker_version}")
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
    "simplebroker": simplebroker_version,
    "taut": importlib.metadata.version("taut"),
    "taut_path": taut_path,
    "guard": "rejected_before_broker_io",
}, sort_keys=True))
""",
    )
    print(probe.stdout.rstrip())


def _case_new_core_prior_summon(
    *,
    new_core: Path,
    previous_summon: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> None:
    case_root, python = _create_environment(
        name="02-new-core-prior-summon", work=work, env=env, uv=uv
    )
    _install(
        python=python,
        artifacts=(new_core, previous_summon),
        cwd=case_root,
        env=env,
        uv=uv,
    )
    db_path = case_root / "must-not-be-created.db"
    probe = _run_python_probe(
        python=python,
        cwd=case_root,
        env=env,
        code=rf"""
import taut
import taut_summon
import taut_summon._control as control

taut_path = assert_installed(taut)
summon_path = assert_installed(taut_summon)
reactor = getattr(control, "_ControlReactor", None)
surface = "absent"
guard = "not_applicable"
if reactor is not None:
    surface = "present"
    class Owner:
        _member_id = "artifact-probe"
        _interval = 0.01
    db = Path({str(db_path)!r})
    try:
        reactor(Owner(), db=db, config={{}})
    except RuntimeError as exc:
        diagnostic = str(exc)
        if "upgrade taut-summon" not in diagnostic:
            raise SystemExit(f"unexpected compatibility diagnostic: {{diagnostic}}")
        guard = "rejected_before_broker_io"
    else:
        raise SystemExit("prior Summon reactor construction was accepted")
    if db.exists():
        raise SystemExit("prior Summon reactor touched the database before rejection")

print(json.dumps({{
    "case": "new_core_prior_summon",
    "legacy_reactor_surface": surface,
    "construction_guard": guard,
    "taut_path": taut_path,
    "summon_path": summon_path,
}}, sort_keys=True))
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
        name="05-command-core-only", work=work, env=env, uv=uv
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
    "(pipx inject taut taut-summon)\n"
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


def _case_new_core_previous_command_summon(
    *,
    new_core: Path,
    previous_summon: Path,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> None:
    case_root, python = _create_environment(
        name="06-command-prior-summon", work=work, env=env, uv=uv
    )
    _install(
        python=python,
        artifacts=(new_core, previous_summon),
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
root_stdout = StringIO()
root_stderr = StringIO()
if dispatch(
    ["--help"],
    stdin=StringIO(),
    stdout=root_stdout,
    stderr=root_stderr,
) != 0:
    raise SystemExit("root help failed with prior Summon installed")
if any(name == "taut_summon" or name.startswith("taut_summon.") for name in sys.modules):
    raise SystemExit("root help imported taut_summon")

for core_verb, legacy_usage in (
    ("summon", "usage: taut-summon run"),
    ("dismiss", "usage: taut-summon stop"),
):
    stdout = StringIO()
    stderr = StringIO()
    result = dispatch(
        [core_verb, "--help"],
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )
    if result != 0 or legacy_usage not in stdout.getvalue() or stderr.getvalue():
        raise SystemExit(
            f"legacy {core_verb} bridge failed: result={result} "
            f"stdout={stdout.getvalue()!r} stderr={stderr.getvalue()!r}"
        )

missing_db = Path.cwd() / "legacy-stop-missing.db"
stop_stdout = StringIO()
stop_stderr = StringIO()
legacy_stop_exit = dispatch(
    ["dismiss", "nobody", "--db", str(missing_db)],
    stdin=StringIO(),
    stdout=stop_stdout,
    stderr=stop_stderr,
)
if (
    legacy_stop_exit != 2
    or stop_stdout.getvalue()
    or "nothing summoned as 'nobody'" not in stop_stderr.getvalue()
    or str(missing_db) not in stop_stderr.getvalue()
):
    raise SystemExit(
        "legacy stop execution failed: "
        f"result={legacy_stop_exit} stdout={stop_stdout.getvalue()!r} "
        f"stderr={stop_stderr.getvalue()!r}"
    )
if missing_db.exists():
    raise SystemExit("legacy stop created a database for an empty result")

import taut_summon

summon_path = assert_installed(taut_summon)
summon_version = importlib.metadata.version("taut-summon")
if summon_version != "0.5.4":
    raise SystemExit(f"command-rollout Summon is {summon_version}, expected 0.5.4")

print(json.dumps({
    "case": "command_rollout_0_5_4",
    "compatibility": "legacy_command_bridge",
    "legacy_stop_exit": legacy_stop_exit,
    "summon_path": summon_path,
    "summon_version": summon_version,
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
        name="03-paired-control", work=work, env=env, uv=uv
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


def _case_resolver_rejects_prior_core(
    *,
    previous_core: Path,
    previous_core_version: str,
    new_summon: Path,
    new_core_version: str,
    work: Path,
    env: dict[str, str],
    uv: str,
) -> None:
    case_root, python = _create_environment(
        name="04-resolver-rejects-prior-core", work=work, env=env, uv=uv
    )
    command = [
        uv,
        "pip",
        "install",
        "--python",
        str(python),
        str(previous_core),
        str(new_summon),
    ]
    completed = _run(
        command,
        cwd=case_root,
        env=env,
        expected_returncode=None,
    )
    if completed.returncode == 0:
        _fail(
            f"resolver accepted new Summon with prior taut {previous_core_version}; "
            "the new "
            f"Summon floor must require taut>={new_core_version}"
        )
    diagnostic = f"{completed.stdout}\n{completed.stderr}".lower()
    if "traceback (most recent call last)" in diagnostic:
        _fail("resolver failed with a Python traceback, not a dependency conflict")
    normalized = " ".join(diagnostic.split())
    prior_markers = (
        f"taut=={previous_core_version}",
        f"taut {previous_core_version}",
        f"only taut<{new_core_version} is available",
    )
    expected_conflict = (
        "no solution found" in normalized
        and "because" in normalized
        and f"depends on taut>={new_core_version}" in normalized
        and any(marker in normalized for marker in prior_markers)
    )
    if not expected_conflict:
        _fail(
            "resolver failed for an unexpected reason rather than the expected "
            f"taut dependency conflict: {normalized}"
        )
    print(
        json.dumps(
            {
                "case": "resolver_rejects_prior_core",
                "new_core_floor": new_core_version,
                "prior_core": previous_core_version,
                "resolver": "conflict",
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

    core_commit = _resolve_remote_tag(inputs.previous_core_ref, env=env)
    summon_commit = _resolve_remote_tag(inputs.previous_summon_ref, env=env)
    command_core_commit = _resolve_remote_tag(inputs.previous_command_core_ref, env=env)
    command_summon_commit = _resolve_remote_tag(
        inputs.previous_command_summon_ref, env=env
    )
    with tempfile.TemporaryDirectory(prefix="taut-wheel-matrix-") as raw_work:
        work = Path(raw_work)
        core_source = work / "previous-core-source"
        summon_source = work / "previous-summon-source"
        command_core_source = work / "previous-command-core-source"
        command_summon_source = work / "previous-command-summon-source"
        archive_repository = _prepare_archive_repository(
            refs=(
                inputs.previous_core_ref,
                inputs.previous_summon_ref,
                inputs.previous_command_core_ref,
                inputs.previous_command_summon_ref,
            ),
            work=work,
            env=env,
        )
        _export_ref(
            repository=archive_repository,
            commit=core_commit,
            destination=core_source,
            env=env,
        )
        _export_ref(
            repository=archive_repository,
            commit=summon_commit,
            destination=summon_source,
            env=env,
        )
        _export_ref(
            repository=archive_repository,
            commit=command_core_commit,
            destination=command_core_source,
            env=env,
        )
        _export_ref(
            repository=archive_repository,
            commit=command_summon_commit,
            destination=command_summon_source,
            env=env,
        )
        _previous_core, previous_summon = _build_previous_wheels(
            core_source=core_source,
            summon_source=summon_source,
            work=work,
            env=env,
            uv=uv,
        )
        previous_command_summon = _build_previous_command_summon(
            summon_source=command_summon_source,
            work=work,
            env=env,
            uv=uv,
        )
        previous_command_core = _build_previous_command_core(
            core_source=command_core_source,
            work=work,
            env=env,
            uv=uv,
        )
        _case_new_core(wheel=inputs.new_core, work=work, env=env, uv=uv)
        _case_new_core_prior_summon(
            new_core=inputs.new_core,
            previous_summon=previous_summon,
            work=work,
            env=env,
            uv=uv,
        )
        _case_paired_control_smoke(
            new_core=inputs.new_core,
            new_summon=inputs.new_summon,
            work=work,
            env=env,
            uv=uv,
        )
        _case_resolver_rejects_prior_core(
            previous_core=previous_command_core,
            previous_core_version=EXPECTED_COMMAND_ROLLOUT_CORE_VERSION,
            new_summon=inputs.new_summon,
            new_core_version=core_metadata.version,
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
        _case_new_core_previous_command_summon(
            new_core=inputs.new_core,
            previous_summon=previous_command_summon,
            work=work,
            env=env,
            uv=uv,
        )
    print("[wheel-matrix] all six installed-wheel cases passed")


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
    except Exception as exc:  # fail closed without exposing an agent/tool traceback
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
