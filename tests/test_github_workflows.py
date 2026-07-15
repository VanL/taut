from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from coverage import Coverage, CoverageData

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"

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


def _workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def _job_block(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
        workflow,
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
    root_job = _job_block(workflow, "test")
    packaging = _job_block(workflow, "packaging")

    assert "workflow_call:" in workflow
    assert "check_paired_release_wheels" not in workflow
    assert "python bin/build-and-check-release-wheels.py" in workflow
    core_build = packaging.index("- name: Build core package")
    summon_build = packaging.index("- name: Build taut-summon extension package")
    release_wheel_check = packaging.index("- name: Check paired release wheels")
    wheel_smoke = packaging.index("- name: Smoke test core wheel")
    assert core_build < summon_build < release_wheel_check < wheel_smoke
    assert "pytest -v --tb=short" in workflow
    assert "summon-process:" in workflow
    assert "name: taut-summon process" in workflow
    assert "max-parallel:" not in workflow
    process_job_position = workflow.index("summon-process:")
    process_command_position = workflow.index(
        'pytest extensions/taut_summon/tests -v --tb=short -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 2 --dist load'
    )
    assert process_job_position < process_command_position
    assert (
        'pytest extensions/taut_summon/tests -v --tb=short -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 2 --dist load'
        in workflow
    )
    assert (
        "pytest extensions/taut_summon/tests/test_live_local_llm.py -v "
        "--tb=short -m requires_local_llm -n 1 --dist loadgroup" in workflow
    )
    assert "ruff check taut tests bin" in workflow
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
    assert root_job.count('-m "not slow and not installed_wheel"') == 2
    assert root_job.count('-m "not slow and installed_wheel" -n 0') == 2
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
    ("path", "live_marker", "unit_count", "live_count"),
    [
        (
            "extensions/taut_summon/tests/test_live_harness.py",
            "requires_live_harness",
            10,
            8,
        ),
        (
            "extensions/taut_summon/tests/test_live_local_llm.py",
            "requires_local_llm",
            18,
            1,
        ),
    ],
)
def test_summon_live_files_have_disjoint_unit_and_live_owners(
    path: str,
    live_marker: str,
    unit_count: int,
    live_count: int,
) -> None:
    records = _summon_collection_records(path)
    all_nodeids = {record["nodeid"] for record in records}
    unit = {record["nodeid"] for record in records if not record["xdist_group"]}
    live = {record["nodeid"] for record in records if record[live_marker]}

    assert len(records) == len(all_nodeids)
    assert len(unit) == unit_count
    assert len(live) == live_count
    assert unit.isdisjoint(live)
    assert unit | live == all_nodeids


def test_coverage_reuses_existing_ubuntu_lanes_and_aggregates_without_tests() -> None:
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    run_config = config["tool"]["coverage"]["run"]
    assert run_config["source"] == ["taut", "taut_summon"]
    assert run_config["patch"] == ["subprocess"]

    workflow = _workflow("test.yml")
    root_job = _job_block(workflow, "test")
    process_job = _job_block(workflow, "summon-process")
    llm_job = _job_block(workflow, "summon-local-llm")
    coverage_job = _job_block(workflow, "coverage")

    representative = "matrix.os == 'ubuntu-latest' && matrix.python-version == '3.13'"
    assert representative in root_job
    assert representative in process_job
    assert "python -m coverage erase" in root_job
    assert "python -m coverage run --parallel-mode -m pytest" in root_job
    assert "python -m coverage run --parallel-mode -m pytest" in process_job
    assert "-n 2 --dist load" in process_job
    assert "python -m coverage run --parallel-mode -m pytest" in llm_job
    assert "test_live_local_llm.py" in llm_job
    assert "steps.root_coverage.outcome != 'skipped'" in root_job
    assert "steps.summon_unit_coverage.outcome != 'skipped'" in root_job
    assert "steps.summon_process_coverage.outcome != 'skipped'" in process_job
    assert "steps.local_llm_coverage.outcome != 'skipped'" in llm_job

    for job, artifact in (
        (root_job, "coverage-data-root-unit"),
        (process_job, "coverage-data-summon-process"),
        (llm_job, "coverage-data-local-llm"),
    ):
        assert "if: ${{ always()" in job
        assert artifact in job
        assert "include-hidden-files: true" in job

    assert "needs: [test, summon-process, summon-local-llm]" in coverage_job
    assert "pattern: coverage-data-*" in coverage_job
    assert "merge-multiple: true" in coverage_job
    assert "python -m coverage combine coverage-data" in coverage_job
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


def test_canonical_packaging_builds_and_smokes_each_release_artifact_once() -> None:
    workflow = _workflow("test.yml")
    packaging = _job_block(workflow, "packaging")
    canonical = (
        "github.event_name == 'push' && "
        "(github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master')"
    )

    assert "check_paired_release_wheels" not in workflow
    assert "uv build --out-dir release-dist/core ." in packaging
    assert "uv build --out-dir release-dist/summon extensions/taut_summon" in packaging
    assert "uv build --out-dir release-dist/pg extensions/taut_pg" in packaging
    assert "--core-wheel" in packaging
    assert "--summon-wheel" in packaging
    assert "python -m venv /tmp/taut-pg-wheel-smoke" in packaging
    assert "import taut_pg" in packaging
    assert 'get_backend_plugin("postgres")' in packaging
    assert packaging.count("python bin/release-artifact.py create") == 3
    assert packaging.count("${{ github.run_attempt }}") >= 3
    assert packaging.count(canonical) >= 3
    for package in ("taut", "taut-summon", "taut-pg"):
        assert f"release-{package}-attempt-${{{{ github.run_attempt }}}}" in packaging


def test_setup_uv_steps_have_tight_timeouts() -> None:
    for name in (
        "test.yml",
        "test-pg-extension.yml",
        "release.yml",
        "release-gate-summon.yml",
    ):
        lines = _workflow(name).splitlines()
        setup_uv_lines = [
            index
            for index, line in enumerate(lines)
            if "uses: astral-sh/setup-uv@" in line
        ]

        if name in {"release.yml", "release-gate-summon.yml"}:
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
    publish = _job_block(workflow, "publish-release")

    assert "uses: ./.github/workflows/test.yml" not in workflow
    assert "uses: ./.github/workflows/test-pg-extension.yml" not in workflow
    assert "timeout-minutes: 110" in evidence
    assert 'git rev-parse "${GITHUB_REF}^{commit}"' in evidence
    assert "GITHUB_SHA: ${{ steps.tag.outputs.tag_commit }}" in evidence
    assert "tag_commit: ${{ steps.tag.outputs.tag_commit }}" in evidence
    assert "python bin/require-green-workflows.py wait" in evidence
    assert evidence.count("--workflow root=.github/workflows/test.yml") == 1
    assert evidence.count("--workflow pg=.github/workflows/test-pg-extension.yml") == 1
    assert "--artifact-workflow root" in evidence
    assert f"--artifact-prefix {artifact_prefix}" in evidence
    assert "GITHUB_TOKEN: ${{ github.token }}" in evidence
    assert "needs: release-evidence" in publish
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
        assert f"{release_input}: ${{{{ needs.release-evidence.outputs." in publish
    assert f"artifact_prefix: {artifact_prefix}" in publish
    assert "release_ref: ${{ needs.release-evidence.outputs.tag_commit }}" in publish
    assert (
        "expected_tag_commit: ${{ needs.release-evidence.outputs.tag_commit }}"
        in publish
    )
    return workflow


def test_core_release_gate_observes_exact_sha_without_rerunning_tests() -> None:
    workflow = _assert_exact_sha_release_observer(
        "release-gate.yml",
        artifact_prefix="release-taut",
    )

    assert "package_name: taut" in workflow
    assert "package_dir: ." in workflow


def test_pg_workflow_is_reusable_and_runs_pg_helper() -> None:
    workflow = _workflow("test-pg-extension.yml")

    assert "workflow_call:" in workflow
    assert "uv run ./bin/pytest-pg" in workflow
    assert (
        "ruff check extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg"
        in workflow
    )
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
    assert "mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests" in workflow
    assert "uv build --project extensions/taut_mcp" in workflow


def test_pg_release_gate_is_github_only() -> None:
    workflow = _assert_exact_sha_release_observer(
        "release-gate-pg.yml",
        artifact_prefix="release-taut-pg",
    )
    lower_workflow = workflow.lower()

    assert 'tags:\n      - "taut_pg/v*"' in workflow
    assert "package_name: taut-pg" in workflow
    assert "package_dir: extensions/taut_pg" in workflow
    assert "uv publish" not in lower_workflow
    assert "pypi" not in lower_workflow
    assert "trusted-publishing" not in lower_workflow


def test_summon_release_gate_is_github_only() -> None:
    workflow = _assert_exact_sha_release_observer(
        "release-gate-summon.yml",
        artifact_prefix="release-taut-summon",
    )
    lower_workflow = workflow.lower()

    assert 'tags:\n      - "taut_summon/v*"' in workflow
    assert "package_name: taut-summon" in workflow
    assert "package_dir: extensions/taut_summon" in workflow
    assert "uv publish" not in lower_workflow
    assert "pypi" not in lower_workflow
    assert "trusted-publishing" not in lower_workflow


def test_release_workflow_publishes_github_release_only() -> None:
    workflow = _workflow("release.yml")
    lower_workflow = workflow.lower()

    assert "softprops/action-gh-release@" in workflow
    assert "dist/*.tar.gz" in workflow
    assert "dist/*.whl" in workflow
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
    assert "actions/upload-artifact" not in workflow
