from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml
from coverage import Coverage, CoverageData

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"
FIXED_AMX_OLLAMA_IMAGE = (
    "ollama/ollama@"
    "sha256:4dea9fb511947e24a84237bb636b0203abcb2ff0d3fbc7b4ff865deb91362131"
)

pytestmark = pytest.mark.sqlite_only

SUMMON_COLLECTION_REPORTER = """
import json
import sys

import pytest


class Reporter:
    def pytest_collection_finish(self, session):
        print("TAUT_SUMMON_COLLECTED=" + json.dumps([
            {
                "nodeid": item.nodeid,
                "xdist_group": item.get_closest_marker("xdist_group") is not None,
                "requires_live_harness": item.get_closest_marker(
                    "requires_live_harness"
                ) is not None,
                "requires_local_llm": item.get_closest_marker(
                    "requires_local_llm"
                ) is not None,
            }
            for item in session.items
        ]))


raise SystemExit(pytest.main(sys.argv[1:], plugins=[Reporter()]))
"""

SOURCE_COLLECTION_REPORTER = """
import json
import sys

import pytest


class Reporter:
    def pytest_collection_finish(self, session):
        print("TAUT_SOURCE_COLLECTED=" + json.dumps([
            item.nodeid for item in session.items
        ]))


raise SystemExit(pytest.main(sys.argv[1:], plugins=[Reporter()]))
"""


def _workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def _workflow_data(name: str) -> dict[str, Any]:
    value = yaml.safe_load(_workflow(name))
    assert isinstance(value, dict)
    return value


def _named_steps(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_steps = job["steps"]
    assert isinstance(raw_steps, list)
    named = [step for step in raw_steps if isinstance(step, dict) and "name" in step]
    result = {str(step["name"]): step for step in named}
    assert len(result) == len(named), "workflow step names must be unique within a job"
    return result


def _command_option(arguments: list[str], name: str) -> str | None:
    if name in arguments:
        return arguments[arguments.index(name) + 1]
    separator = "=" if name.startswith("--") else ""
    prefix = f"{name}{separator}"
    return next(
        (
            argument.removeprefix(prefix)
            for argument in arguments
            if argument.startswith(prefix) and argument != name
        ),
        None,
    )


def _pytest_workflow_roles(
    document: dict[str, Any],
) -> Counter[tuple[str, str, tuple[str, ...], str, str | None, str | None, str | None]]:
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    roles: Counter[
        tuple[str, str, tuple[str, ...], str, str | None, str | None, str | None]
    ] = Counter()
    for job_name in (
        "test",
        "summon-process",
        "summon-local-llm",
        "mcp-coverage",
    ):
        for step_name, step in _named_steps(jobs[job_name]).items():
            run = step.get("run")
            if not isinstance(run, str):
                continue
            for line in run.splitlines():
                if "pytest" not in line:
                    continue
                arguments = shlex.split(line)
                if "pytest" not in arguments:
                    continue
                pytest_index = arguments.index("pytest")
                pytest_arguments = arguments[pytest_index + 1 :]
                target = next(
                    (
                        argument
                        for argument in pytest_arguments
                        if argument == "tests"
                        or argument.startswith("extensions/")
                        and "/tests" in argument
                    ),
                    ".",
                )
                roles[
                    (
                        job_name,
                        step_name,
                        tuple(arguments[:pytest_index]),
                        target,
                        _command_option(pytest_arguments, "-m"),
                        _command_option(pytest_arguments, "-n"),
                        _command_option(pytest_arguments, "--dist"),
                    )
                ] += 1
    return roles


def _job_block(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
        workflow,
    )
    assert match is not None, name
    return match.group(0)


def _step_block(job: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^      - name: {re.escape(name)}\n(.*?)(?=^      - (?:name|uses):|\Z)",
        job,
    )
    assert match is not None, name
    return match.group(0)


def _summon_collection_records(path: str) -> tuple[dict[str, object], ...]:
    env = os.environ.copy()
    env["PYTEST_ADDOPTS"] = ""
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            "extensions/taut_summon",
            "--extra",
            "dev",
            "python",
            "-c",
            SUMMON_COLLECTION_REPORTER,
            "--collect-only",
            "-q",
            "--strict-markers",
            path,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = next(
        line.removeprefix("TAUT_SUMMON_COLLECTED=")
        for line in completed.stdout.splitlines()
        if line.startswith("TAUT_SUMMON_COLLECTED=")
    )
    return tuple(json.loads(report))


def _source_collection_nodeids(shard: str) -> frozenset[str]:
    env = os.environ.copy()
    env["PYTEST_ADDOPTS"] = ""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            SOURCE_COLLECTION_REPORTER,
            f"--taut-source-shard={shard}",
            "--collect-only",
            "-q",
            "-c",
            "pyproject.toml",
            "-m",
            "not slow and not installed_wheel",
            "tests",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = next(
        line.removeprefix("TAUT_SOURCE_COLLECTED=")
        for line in completed.stdout.splitlines()
        if line.startswith("TAUT_SOURCE_COLLECTED=")
    )
    records = json.loads(report)
    assert isinstance(records, list)
    return frozenset(records)


def test_summon_collection_probe_owns_its_dev_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            "TAUT_SUMMON_COLLECTED=[]\n",
            "",
        )

    monkeypatch.setattr(subprocess, "run", run)

    assert _summon_collection_records("tests/test_live_harness.py") == ()
    assert commands[0][:7] == [
        "uv",
        "run",
        "--project",
        "extensions/taut_summon",
        "--extra",
        "dev",
        "python",
    ]


def test_test_workflow_is_reusable_and_owns_canonical_release_artifacts() -> None:
    workflow = _workflow("test.yml")
    document = _workflow_data("test.yml")
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    root_job = _job_block(workflow, "test")
    packaging = _job_block(workflow, "packaging")

    assert "workflow_call:" in workflow
    assert "check_paired_release_wheels" not in workflow
    assert "python bin/build-and-check-release-wheels.py" in workflow
    core_build = packaging.index("- name: Build core package")
    summon_build = packaging.index("- name: Build taut-summon extension package")
    mcp_build = packaging.index("- name: Build taut-mcp extension package")
    release_wheel_check = packaging.index("- name: Check paired release wheels")
    wheel_smoke = packaging.index("- name: Smoke test core wheel")
    assert core_build < summon_build < mcp_build < release_wheel_check < wheel_smoke
    mcp_build_step = packaging[mcp_build:release_wheel_check]
    assert "uv build --out-dir release-dist/mcp extensions/taut_mcp" in mcp_build_step
    assert "\n        if:" not in mcp_build_step
    assert "summon-process:" in workflow
    assert "name: taut-summon process" in workflow
    assert "max-parallel:" not in workflow
    assert "ruff check ." in workflow
    assert "uv run --extra dev python bin/ruff_suppression_index.py --check" in workflow
    assert workflow.index("ruff check .") < workflow.index(
        "bin/ruff_suppression_index.py --check"
    )
    assert "ruff format --check taut tests bin" in workflow
    # Guard against the stale-path regression: neither the removed generator script
    # nor the deleted logo asset may reappear in the lint command.
    assert "generate_knot.py" not in workflow
    assert "gen_taut_logo" not in workflow
    assert (
        "mypy taut tests bin/release.py bin/release-artifact.py "
        "bin/require-green-workflows.py --config-file pyproject.toml" in workflow
    )
    assert "uv build" in workflow
    roles = _pytest_workflow_roles(document)
    observed_plain = Counter(
        {role: count for role, count in roles.items() if not role[2]}
    )
    assert observed_plain == Counter(
        {
            (
                "test",
                "Run tests with pytest",
                (),
                ".",
                "not slow and not installed_wheel",
                None,
                None,
            ): 1,
            (
                "test",
                "Run installed-wheel tests",
                (),
                ".",
                "not slow and installed_wheel",
                "0",
                None,
            ): 1,
            (
                "test",
                "Run Windows source compatibility smoke",
                (),
                ".",
                None,
                "0",
                None,
            ): 1,
            (
                "test",
                "Run taut-summon extension unit tests",
                (),
                "extensions/taut_summon/tests",
                "not xdist_group",
                None,
                None,
            ): 1,
            (
                "summon-process",
                "Run taut-summon extension process tests",
                (),
                "extensions/taut_summon/tests",
                "xdist_group and not requires_live_harness and not requires_local_llm",
                "2",
                "load",
            ): 1,
        }
    )
    assert (
        "!cancelled() && steps.install.outcome == 'success' && "
        "((matrix.os == 'ubuntu-latest' && "
        "matrix.python-version != '3.13') || (matrix.os == 'macos-latest' && "
        "matrix.python-version == '3.13') || (matrix.os == 'windows-latest' && "
        "matrix.python-version == '3.11'))" in root_job
    )
    assert (
        "!cancelled() && steps.install.outcome == 'success' && "
        "matrix.os == 'ubuntu-latest' && "
        "matrix.python-version == '3.13'" in root_job
    )


@pytest.mark.parametrize(
    ("path", "live_marker"),
    [
        (
            "extensions/taut_summon/tests/test_live_harness.py",
            "requires_live_harness",
        ),
        (
            "extensions/taut_summon/tests/test_live_local_llm.py",
            "requires_local_llm",
        ),
    ],
)
def test_summon_live_files_have_disjoint_unit_and_live_owners(
    path: str,
    live_marker: str,
) -> None:
    records = _summon_collection_records(path)
    all_nodeids = {record["nodeid"] for record in records}
    unit = {record["nodeid"] for record in records if not record["xdist_group"]}
    live = {record["nodeid"] for record in records if record[live_marker]}

    assert records
    assert len(records) == len(all_nodeids)
    assert unit
    assert live
    assert unit.isdisjoint(live)
    assert unit | live == all_nodeids


def test_windows_source_matrix_uses_exact_factor_shards_and_version_smoke() -> None:
    document = _workflow_data("test.yml")
    test_job = document["jobs"]["test"]
    matrix = test_job["strategy"]["matrix"]
    rows = matrix["include"]
    windows_rows = [row for row in rows if row["os"] == "windows-latest"]

    assert [(row["python-version"], row["source-shard"]) for row in windows_rows] == [
        ("3.11", "0/4"),
        ("3.12", "1/4"),
        ("3.13", "2/4"),
        ("3.14", "3/4"),
    ]
    assert all(
        row["source-shard"] == "full" for row in rows if row["os"] != "windows-latest"
    )

    steps = _named_steps(test_job)
    source = steps["Run tests with pytest"]
    assert "--taut-source-shard=${{ matrix.source-shard }}" in source["run"]
    smoke = steps["Run Windows source compatibility smoke"]
    assert smoke["if"] == "${{ matrix.os == 'windows-latest' }}"
    assert smoke["run"].split() == [
        "pytest",
        "tests/test_cli.py::test_cli_json_join_say_log",
        "-v",
        "--tb=short",
        "-n",
        "0",
    ]


def test_windows_source_factor_is_exact_complete_disjoint_nonempty_union() -> None:
    complete = _source_collection_nodeids("full")
    shards = tuple(_source_collection_nodeids(f"{index}/4") for index in range(4))

    assert complete
    assert all(shards)
    assert frozenset().union(*shards) == complete
    for index, left in enumerate(shards):
        for right in shards[index + 1 :]:
            assert left.isdisjoint(right)


def test_coverage_reuses_existing_ubuntu_lanes_and_aggregates_without_tests() -> None:
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    run_config = config["tool"]["coverage"]["run"]
    assert run_config["source"] == ["taut", "taut_summon", "taut_mcp"]
    assert run_config["patch"] == ["subprocess"]

    workflow = _workflow("test.yml")
    document = _workflow_data("test.yml")
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    named_steps = {
        job_name: _named_steps(jobs[job_name])
        for job_name in (
            "test",
            "summon-process",
            "summon-local-llm",
            "mcp-coverage",
            "coverage",
        )
    }
    root_job = _job_block(workflow, "test")
    process_job = _job_block(workflow, "summon-process")
    llm_job = _job_block(workflow, "summon-local-llm")
    mcp_job = _job_block(workflow, "mcp-coverage")
    coverage_job = _job_block(workflow, "coverage")

    representative = "matrix.os == 'ubuntu-latest' && matrix.python-version == '3.13'"
    assert representative in root_job
    assert representative in process_job
    assert "python -m coverage erase" in root_job
    wrapper = ("python", "-m", "coverage", "run", "--parallel-mode", "-m")
    roles = _pytest_workflow_roles(document)
    observed_coverage = Counter(
        {role: count for role, count in roles.items() if role[2]}
    )
    assert observed_coverage == Counter(
        {
            (
                "test",
                "Run tests with coverage",
                wrapper,
                ".",
                "not slow and not installed_wheel",
                "0",
                None,
            ): 1,
            (
                "test",
                "Run installed-wheel tests with coverage",
                wrapper,
                ".",
                "not slow and installed_wheel",
                "0",
                None,
            ): 1,
            (
                "test",
                "Run taut-summon extension unit tests with coverage",
                wrapper,
                "extensions/taut_summon/tests",
                "not xdist_group",
                "0",
                None,
            ): 1,
            (
                "summon-process",
                "Run taut-summon extension process tests with coverage",
                wrapper,
                "extensions/taut_summon/tests",
                "xdist_group and not requires_live_harness and not requires_local_llm",
                "2",
                "load",
            ): 1,
            (
                "summon-local-llm",
                "Run taut-summon local LLM live tests",
                wrapper,
                "extensions/taut_summon/tests/test_live_local_llm.py",
                "requires_local_llm",
                "1",
                "loadgroup",
            ): 1,
            (
                "mcp-coverage",
                "Run taut-mcp non-PG tests with coverage",
                wrapper,
                "extensions/taut_mcp/tests",
                "not pg_only",
                "0",
                None,
            ): 1,
        }
    )
    assert "steps.root_coverage.outcome != 'skipped'" in root_job
    assert "steps.summon_unit_coverage.outcome != 'skipped'" in root_job
    assert "steps.summon_process_coverage.outcome != 'skipped'" in process_job
    assert "steps.local_llm_coverage.outcome != 'skipped'" in llm_job
    assert '-e "./extensions/taut_pg"' in mcp_job
    assert '-e "./extensions/taut_mcp"' in mcp_job
    assert "services:" not in mcp_job
    assert "\n    if:" not in mcp_job.split("    steps:", maxsplit=1)[0]

    artifact_owners = {
        "test": (
            "Upload root and unit coverage data",
            "coverage-data-root-unit",
            "${{ github.workspace }}/.coverage.root-unit.*",
        ),
        "summon-process": (
            "Upload process coverage data",
            "coverage-data-summon-process",
            "${{ github.workspace }}/.coverage.summon-process.*",
        ),
        "summon-local-llm": (
            "Upload local LLM coverage data",
            "coverage-data-local-llm",
            "${{ github.workspace }}/.coverage.local-llm.*",
        ),
        "mcp-coverage": (
            "Upload MCP coverage data",
            "coverage-data-mcp",
            "${{ github.workspace }}/.coverage.mcp.*",
        ),
    }
    observed_artifacts = {}
    for job_name, (step_name, artifact_name, artifact_path) in artifact_owners.items():
        step = named_steps[job_name][step_name]
        settings = step["with"]
        observed_artifacts[job_name] = (
            step["uses"].split("@", maxsplit=1)[0],
            settings["name"],
            settings["path"],
            settings["if-no-files-found"],
            settings["include-hidden-files"],
            str(step["if"]).startswith("${{ always()"),
        )
        assert settings["name"] == artifact_name
        assert settings["path"] == artifact_path
    assert observed_artifacts == {
        job_name: (
            "actions/upload-artifact",
            artifact_name,
            artifact_path,
            "error",
            True,
            True,
        )
        for job_name, (
            _step_name,
            artifact_name,
            artifact_path,
        ) in artifact_owners.items()
    }

    assert (
        "needs: [test, summon-process, summon-local-llm, mcp-coverage]" in coverage_job
    )
    assert "pattern: coverage-data-*" in coverage_job
    assert "merge-multiple: true" in coverage_job
    assert (
        "python bin/combine-coverage.py coverage-data --output .coverage"
        in coverage_job
    )
    assert "python -m coverage combine coverage-data" not in coverage_job
    assert "python bin/check-required-coverage-paths.py" in coverage_job
    assert "pytest" not in coverage_job
    assert "test_live_harness.py" not in workflow
    assert "uv run coverage" not in workflow
    for critical_file in ("_driver.py", "_control.py", "cli.py"):
        assert (
            f'python -m coverage report --include="*/taut_summon/{critical_file}" '
            "--fail-under=1" in coverage_job
        )


def test_coverage_subprocess_patch_records_plain_children(tmp_path: Path) -> None:
    coverage_file = tmp_path / ".coverage"
    env = os.environ.copy()
    env["COVERAGE_FILE"] = str(coverage_file)
    env["COVERAGE_PROCESS_START"] = str(PROJECT_ROOT / "pyproject.toml")
    provider_path = (
        PROJECT_ROOT
        / "extensions"
        / "taut_summon"
        / "taut_summon"
        / "scripted_provider.py"
    )
    provider_input = (
        '{"type":"user","message":{"role":"user","content":'
        '[{"type":"text","text":"coverage probe"}]}}\n'
    )
    launcher = (
        "import subprocess,sys\n"
        "subprocess.run([sys.executable,'-m','taut','--version'],check=True)\n"
        "subprocess.run([sys.executable,'-m','taut_summon.scripted_provider'],"
        f"input={provider_input!r},text=True,check=True,capture_output=True)\n"
    )
    launcher_path = tmp_path / "coverage_launcher.py"
    launcher_path.write_text(launcher, encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--parallel-mode",
            str(launcher_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    coverage = Coverage(data_file=str(coverage_file), config_file=False)
    coverage.combine(data_paths=[str(tmp_path)], strict=True)
    coverage.save()
    data = CoverageData(basename=str(coverage_file))
    data.read()
    main_path = str((PROJECT_ROOT / "taut" / "__main__.py").resolve())
    source_lines = (
        (PROJECT_ROOT / "taut" / "__main__.py").read_text("utf-8").splitlines()
    )
    exit_line = next(
        index
        for index, line in enumerate(source_lines, start=1)
        if "raise SystemExit(main())" in line
    )

    assert exit_line in (data.lines(main_path) or [])

    provider_source = provider_path.read_text("utf-8").splitlines()
    provider_exit_line = next(
        index
        for index, line in enumerate(provider_source, start=1)
        if "raise SystemExit(main())" in line
    )
    assert provider_exit_line in (data.lines(str(provider_path.resolve())) or [])


def test_local_llm_readiness_lists_then_completes_exactly_once() -> None:
    workflow = _workflow("test.yml")
    llm_job = _job_block(workflow, "summon-local-llm")

    model_list = llm_job.index('rstrip("/") + "/models"')
    completion = llm_job.index('"/chat/completions"')
    live_test = llm_job.index("Run taut-summon local LLM live tests")

    assert model_list < completion < live_test
    assert llm_job.count('"/chat/completions"') == 1
    assert "break" in llm_job[model_list:completion]
    assert "timeout=60" in llm_job[completion:live_test]
    assert "waiting for chat completion" not in llm_job


def test_local_llm_pins_fixed_amx_build_and_reports_cpu_identity() -> None:
    workflow = _workflow("test.yml")
    llm_job = _job_block(workflow, "summon-local-llm")

    assert f"OLLAMA_IMAGE: {FIXED_AMX_OLLAMA_IMAGE}" in llm_job
    diagnostics = llm_job.index("- name: Local LLM diagnostics")
    assert "lscpu || true" in llm_job[diagnostics:]


def test_canonical_packaging_builds_and_smokes_each_release_artifact_once() -> None:
    document = _workflow_data("test.yml")
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    steps = _named_steps(jobs["packaging"])

    package_owners = {
        "taut-chat": (
            "Build core package",
            ("uv", "build", "--out-dir", "release-dist/core", "."),
            ".",
            "release-dist/core",
            "release-bundles/taut-chat",
            "Upload core release evidence",
        ),
        "taut-summon": (
            "Build taut-summon extension package",
            (
                "uv",
                "build",
                "--out-dir",
                "release-dist/summon",
                "extensions/taut_summon",
            ),
            "extensions/taut_summon",
            "release-dist/summon",
            "release-bundles/taut-summon",
            "Upload Summon release evidence",
        ),
        "taut-pg": (
            "Build taut-pg release package",
            (
                "uv",
                "build",
                "--out-dir",
                "release-dist/pg",
                "extensions/taut_pg",
            ),
            "extensions/taut_pg",
            "release-dist/pg",
            "release-bundles/taut-pg",
            "Upload PG release evidence",
        ),
        "taut-mcp": (
            "Build taut-mcp extension package",
            (
                "uv",
                "build",
                "--out-dir",
                "release-dist/mcp",
                "extensions/taut_mcp",
            ),
            "extensions/taut_mcp",
            "release-dist/mcp",
            "release-bundles/taut-mcp",
            "Upload MCP release evidence",
        ),
    }
    bundle_commands = [
        shlex.split(line)
        for line in str(steps["Create release provenance bundles"]["run"]).splitlines()
        if "release-artifact.py create" in line
    ]
    canonical_ref = (
        "${{ github.event_name == 'push' && "
        "(github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master') }}"
    )
    evidence_steps = [
        "Create release provenance bundles",
        *(values[5] for values in package_owners.values()),
    ]
    assert {name: steps[name].get("if") for name in evidence_steps} == dict.fromkeys(
        evidence_steps,
        canonical_ref,
    )
    observed = []
    for package, (
        build_step,
        build_command,
        _package_dir,
        _dist_dir,
        output_dir,
        upload_step,
    ) in package_owners.items():
        matching_bundles = [
            command
            for command in bundle_commands
            if command[command.index("--output-dir") + 1] == output_dir
        ]
        assert len(matching_bundles) == 1
        bundle = matching_bundles[0]
        upload = steps[upload_step]["with"]
        observed.append(
            (
                package,
                tuple(shlex.split(str(steps[build_step]["run"]))),
                bundle[bundle.index("--package-dir") + 1],
                bundle[bundle.index("--dist-dir") + 1],
                bundle[bundle.index("--output-dir") + 1],
                upload["name"],
                str(upload["path"]).rstrip("/"),
            )
        )
        assert tuple(shlex.split(str(steps[build_step]["run"]))) == build_command
    assert observed == [
        (
            package,
            values[1],
            values[2],
            values[3],
            values[4],
            f"release-{package}-attempt-${{{{ github.run_attempt }}}}",
            values[4],
        )
        for package, values in package_owners.items()
    ]
    assert len(bundle_commands) == len(package_owners)

    smoke_owners = {
        "Smoke test core wheel": ("release-dist/core/*.whl", "taut --version"),
        "Smoke test taut-pg wheel with paired core": (
            "release-dist/core/*.whl release-dist/pg/*.whl",
            'get_backend_plugin("postgres")',
        ),
        "Smoke test taut-mcp wheel with paired core": (
            "release-dist/core/*.whl release-dist/mcp/*.whl",
            "taut-mcp --version",
        ),
    }
    assert {
        name: all(fragment in str(steps[name]["run"]) for fragment in fragments)
        for name, fragments in smoke_owners.items()
    } == dict.fromkeys(smoke_owners, True)

    paired_run = str(steps["Check paired release wheels"]["run"])
    normalized_paired_run = paired_run.replace("\\\n", " ")
    paired_command = next(
        shlex.split(line.strip())
        for line in normalized_paired_run.splitlines()
        if line.strip().startswith("python bin/build-and-check-release-wheels.py")
    )
    assert paired_command == [
        "python",
        "bin/build-and-check-release-wheels.py",
        "--core-wheel",
        "${core_wheels[0]}",
        "--summon-wheel",
        "${summon_wheels[0]}",
    ]
    assert "core_wheels=(release-dist/core/*.whl)" in paired_run
    assert "summon_wheels=(release-dist/summon/*.whl)" in paired_run
    assert 'test "${#core_wheels[@]}" -eq 1' in paired_run
    assert 'test "${#summon_wheels[@]}" -eq 1' in paired_run


def test_setup_uv_steps_have_tight_timeouts() -> None:
    for name in (
        "test.yml",
        "test-pg-extension.yml",
        "release.yml",
        "release-gate-summon.yml",
        "release-gate-mcp.yml",
    ):
        lines = _workflow(name).splitlines()
        setup_uv_lines = [
            index
            for index, line in enumerate(lines)
            if "uses: astral-sh/setup-uv@" in line
        ]

        if name in {"release.yml", "release-gate-summon.yml", "release-gate-mcp.yml"}:
            assert setup_uv_lines == []
            continue
        assert setup_uv_lines, name
        for index in setup_uv_lines:
            step_header = lines[max(0, index - 2) : index + 2]
            assert any("timeout-minutes: 5" in line for line in step_header), (
                name,
                index,
            )


def _assert_exact_sha_release_observer(name: str, *, artifact_prefix: str) -> str:
    workflow = _workflow(name)
    evidence = _job_block(workflow, "release-evidence")
    stage = _job_block(workflow, "stage-release")

    assert "uses: ./.github/workflows/test.yml" not in workflow
    assert "uses: ./.github/workflows/test-pg-extension.yml" not in workflow
    assert "uses: ./.github/workflows/test-mcp-extension.yml" not in workflow
    assert "timeout-minutes: 110" in evidence
    assert 'git rev-parse "${GITHUB_REF}^{commit}"' in evidence
    assert "GITHUB_SHA: ${{ steps.tag.outputs.tag_commit }}" in evidence
    assert "tag_commit: ${{ steps.tag.outputs.tag_commit }}" in evidence
    assert "python bin/require-green-workflows.py wait" in evidence
    assert evidence.count("--workflow root=.github/workflows/test.yml") == 1
    assert evidence.count("--workflow pg=.github/workflows/test-pg-extension.yml") == 1
    assert (
        evidence.count("--workflow mcp=.github/workflows/test-mcp-extension.yml") == 1
    )
    assert "--artifact-workflow root" in evidence
    assert f"--artifact-prefix {artifact_prefix}" in evidence
    assert "GITHUB_TOKEN: ${{ github.token }}" in evidence
    assert "needs: release-evidence" in stage
    for output in (
        "artifact_id",
        "artifact_digest",
        "artifact_run_id",
        "artifact_run_attempt",
        "artifact_repository_id",
        "artifact_head_repository_id",
        "artifact_head_branch",
    ):
        assert f"{output}: ${{{{ steps.observe.outputs.{output} }}}}" in evidence
    for release_input in (
        "evidence_run_id",
        "evidence_run_attempt",
        "evidence_branch",
        "artifact_id",
        "artifact_digest",
        "artifact_repository_id",
        "artifact_head_repository_id",
    ):
        assert f"{release_input}: ${{{{ needs.release-evidence.outputs." in stage
    assert f"artifact_prefix: {artifact_prefix}" in stage
    assert "release_ref: ${{ needs.release-evidence.outputs.tag_commit }}" in stage
    assert (
        "expected_tag_commit: ${{ needs.release-evidence.outputs.tag_commit }}" in stage
    )
    return workflow


def test_pg_workflow_is_reusable_and_runs_pg_helper() -> None:
    workflow = _workflow("test-pg-extension.yml")

    assert "workflow_call:" in workflow
    assert "uv run ./bin/pytest-pg" in workflow
    assert (
        "ruff check extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg"
        in workflow
    )
    assert "ruff_suppression_index.py" not in workflow
    assert (
        "mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests"
        in workflow
    )


def test_mcp_workflow_runs_sqlite_postgres_quality_and_build_gates() -> None:
    workflow = _workflow("test-mcp-extension.yml")

    assert "workflow_call:" in workflow
    assert "image: postgres:18" in workflow
    assert "SIMPLEBROKER_PG_TEST_DSN:" in workflow
    assert "job.services.postgres.ports[5432]" in workflow
    assert (
        "uv run --project extensions/taut_mcp --extra dev pytest "
        "extensions/taut_mcp/tests"
    ) in workflow
    assert (
        "ruff check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests" in workflow
    )
    assert "ruff_suppression_index.py" not in workflow
    assert "mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests" in workflow
    assert "uv build --project extensions/taut_mcp" in workflow
    assert "release-artifact.py" not in workflow
    assert "release-taut-mcp" not in workflow


@pytest.mark.parametrize(
    ("name", "tag_pattern", "package_dir", "package_name", "artifact_prefix"),
    (
        ("release-gate.yml", "v*", ".", "taut-chat", "release-taut-chat"),
        (
            "release-gate-pg.yml",
            "taut_pg/v*",
            "extensions/taut_pg",
            "taut-pg",
            "release-taut-pg",
        ),
        (
            "release-gate-summon.yml",
            "taut_summon/v*",
            "extensions/taut_summon",
            "taut-summon",
            "release-taut-summon",
        ),
        (
            "release-gate-mcp.yml",
            "taut_mcp/v*",
            "extensions/taut_mcp",
            "taut-mcp",
            "release-taut-mcp",
        ),
    ),
)
def test_release_gates_publish_exact_artifact_through_top_level_pypi_job(
    name: str,
    tag_pattern: str,
    package_dir: str,
    package_name: str,
    artifact_prefix: str,
) -> None:
    workflow = _assert_exact_sha_release_observer(
        name,
        artifact_prefix=artifact_prefix,
    )
    stage = _job_block(workflow, "stage-release")
    pypi = _job_block(workflow, "publish-to-pypi")
    finalize = _job_block(workflow, "publish-github-release")

    assert f'      - "{tag_pattern}"' in workflow
    assert "uv build" not in workflow
    assert "python -m build" not in workflow
    assert workflow.count("pypa/gh-action-pypi-publish@") == 1
    assert f"package_dir: {package_dir}" in stage
    assert "uses: ./.github/workflows/release.yml" in stage
    assert "contents: write" in stage
    assert "needs:" in pypi
    assert "release-evidence" in pypi
    assert "stage-release" in pypi
    assert "environment:" in pypi
    assert "name: pypi" in pypi
    assert f"url: https://pypi.org/p/{package_name}" in pypi
    assert "actions: read" in pypi
    assert "contents: read" in pypi
    assert "id-token: write" in pypi
    assert "contents: write" not in pypi
    assert "release-artifact.py verify" in pypi
    assert ".github/scripts/release_publication.py plan-pypi" in pypi
    assert ".github/scripts/release_publication.py verify-pypi" in pypi
    recreate = _step_block(pypi, "Recreate clean verified distributions for postflight")
    postflight_step = _step_block(pypi, "Verify complete exact PyPI publication")
    assert f"--package-dir {package_dir} \\" in recreate
    assert "--bundle-dir bundle \\" in recreate
    assert '--commit "${{ needs.release-evidence.outputs.tag_commit }}" \\' in recreate
    assert '--tag-name "${{ github.ref_name }}" \\' in recreate
    assert "--output-dir postflight-dist" in recreate
    assert "if:" not in recreate
    assert pypi.count(".github/scripts/release_publication.py verify-pypi") == 1
    assert "--dist-dir postflight-dist" in postflight_step
    assert "--dist-dir dist" not in postflight_step
    tag_recheck = pypi.index(".github/scripts/release_publication.py verify-tag")
    upload = pypi.index("pypa/gh-action-pypi-publish@")
    clean_postflight = pypi.index(
        "Recreate clean verified distributions for postflight"
    )
    postflight = pypi.rindex(".github/scripts/release_publication.py verify-pypi")
    assert tag_recheck < upload < clean_postflight < postflight
    assert (
        "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33" in pypi
    )
    assert "skip-existing: ${{ steps.publication.outputs.skip_existing }}" in pypi
    assert "if: ${{ steps.publication.outputs.publish == 'true' }}" in pypi
    assert "needs:" in finalize
    assert "stage-release" in finalize
    assert "publish-to-pypi" in finalize
    assert "uses: ./.github/workflows/release-finalize.yml" in finalize
    assert "contents: write" in finalize


def test_release_workflow_stages_draft_and_carries_verified_bundle() -> None:
    workflow = _workflow("release.yml")
    document = _workflow_data("release.yml")
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    stage_permissions = jobs["stage-release"]["permissions"]
    lower_workflow = workflow.lower()

    assert stage_permissions == {"actions": "read", "contents": "write"}
    assert "softprops/action-gh-release@" in workflow
    assert "draft: true" in workflow
    assert "fail_on_unmatched_files: true" in workflow
    assert "target_commitish: ${{ github.event.repository.default_branch }}" in workflow
    assert "target_commitish: ${{ inputs.expected_tag_commit }}" not in workflow
    assert "dist/*.tar.gz" in workflow
    assert "dist/*.whl" in workflow
    assert ".github/scripts/release_publication.py stage-draft" in workflow
    assert "actions/upload-artifact@" in workflow
    assert "carried_artifact_id:" in workflow
    assert "uv publish" not in lower_workflow
    assert "pypi" not in lower_workflow
    assert "trusted-publishing" not in lower_workflow


def test_release_workflow_consumes_pinned_verified_artifact_without_rebuild() -> None:
    workflow = _workflow("release.yml")

    for input_name in (
        "evidence_run_id:",
        "evidence_run_attempt:",
        "evidence_branch:",
        "artifact_prefix:",
        "artifact_id:",
        "artifact_digest:",
        "artifact_repository_id:",
        "artifact_head_repository_id:",
    ):
        assert input_name in workflow
    assert "require-green-workflows.py verify-artifact" in workflow
    assert '--artifact-prefix "${{ inputs.artifact_prefix }}"' in workflow
    assert '--repository-id "${{ inputs.artifact_repository_id }}"' in workflow
    assert (
        '--head-repository-id "${{ inputs.artifact_head_repository_id }}"' in workflow
    )
    assert "GITHUB_SHA: ${{ inputs.expected_tag_commit }}" in workflow
    assert "artifact-ids: ${{ inputs.artifact_id }}" in workflow
    assert "run-id: ${{ inputs.evidence_run_id }}" in workflow
    assert "repository: ${{ github.repository }}" in workflow
    assert "github-token: ${{ github.token }}" in workflow
    assert "release-artifact.py verify" in workflow
    assert '--tag-name "${{ inputs.tag_name }}"' in workflow
    assert "uv build" not in workflow
    assert "python -m build" not in workflow


def test_release_finalizer_is_least_privilege_and_never_publishes_to_pypi() -> None:
    workflow = _workflow("release-finalize.yml")
    lower_workflow = workflow.lower()
    finalizer = _job_block(workflow, "github-release")

    assert "workflow_call:" in workflow
    assert "actions: read" in finalizer
    assert "contents: write" in finalizer
    assert "id-token: write" not in finalizer
    assert "release-artifact.py verify" in finalizer
    assert ".github/scripts/release_publication.py finalize" in finalizer
    assert "pypa/gh-action-pypi-publish" not in workflow
    assert "uv publish" not in lower_workflow
    assert "python -m build" not in workflow
