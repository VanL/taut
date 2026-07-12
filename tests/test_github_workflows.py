from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from coverage import Coverage, CoverageData

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"

pytestmark = pytest.mark.sqlite_only


def _workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def test_test_workflow_is_reusable_and_runs_release_gates() -> None:
    workflow = _workflow("test.yml")

    assert "workflow_call:" in workflow
    assert "verify_paired_reactor_artifacts:" in workflow
    assert "type: boolean" in workflow
    assert "default: false" in workflow
    assert "if: ${{ inputs.verify_paired_reactor_artifacts }}" in workflow
    assert "python bin/verify-reactor-release-artifacts.py" in workflow
    core_build = workflow.index("- name: Build package")
    summon_build = workflow.index("- name: Build taut-summon extension package")
    paired_verify = workflow.index("- name: Verify fresh paired reactor artifacts")
    wheel_smoke = workflow.index("- name: Smoke test built wheel")
    assert core_build < summon_build < paired_verify < wheel_smoke
    assert "pytest -v --tb=short" in workflow
    assert "summon-process:" in workflow
    assert "name: taut-summon process" in workflow
    assert "max-parallel: 1" in workflow
    process_job_position = workflow.index("summon-process:")
    process_command_position = workflow.index(
        'pytest extensions/taut_summon/tests -v --tb=short -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 1 --dist loadgroup'
    )
    assert process_job_position < process_command_position
    assert (
        'pytest extensions/taut_summon/tests -v --tb=short -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 1 --dist loadgroup'
        in workflow
    )
    assert (
        "pytest extensions/taut_summon/tests/test_live_local_llm.py -v --tb=short -n 1 --dist loadgroup"
        in workflow
    )
    assert "ruff check taut tests bin" in workflow
    assert "ruff format --check taut tests bin" in workflow
    # Guard against the stale-path regression: neither the removed generator script
    # nor the deleted logo asset may reappear in the lint command.
    assert "generate_knot.py" not in workflow
    assert "gen_taut_logo" not in workflow
    assert "mypy taut tests bin/release.py --config-file pyproject.toml" in workflow
    assert "uv build" in workflow


def test_coverage_measures_core_and_summon_in_isolated_process_lanes() -> None:
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    run_config = config["tool"]["coverage"]["run"]
    assert run_config["source"] == ["taut", "taut_summon"]
    assert run_config["patch"] == ["subprocess"]

    workflow = _workflow("test.yml")
    assert "uv run coverage erase" in workflow
    assert 'coverage run --parallel-mode -m pytest tests -m "not slow"' in workflow
    assert (
        "coverage run --parallel-mode -m pytest extensions/taut_summon/tests "
        '-m "not xdist_group"' in workflow
    )
    assert (
        "coverage run --parallel-mode -m pytest extensions/taut_summon/tests "
        '-m "xdist_group and not requires_live_harness and not '
        'requires_local_llm" -n 1 --dist loadgroup' in workflow
    )
    assert (
        "coverage run --parallel-mode -m pytest "
        "extensions/taut_summon/tests/test_live_harness.py -n 1 --dist loadgroup"
        in workflow
    )
    assert (
        "coverage run --parallel-mode -m pytest "
        "extensions/taut_summon/tests/test_live_local_llm.py -n 1 --dist loadgroup"
        in workflow
    )
    assert "uv run coverage combine" in workflow
    assert "uv run python bin/verify-coverage-evidence.py" in workflow
    for critical_file in ("_driver.py", "_control.py", "cli.py"):
        assert (
            f'coverage report --include="*/taut_summon/{critical_file}" --fail-under=1'
            in workflow
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

        if name == "release-gate-summon.yml":
            assert setup_uv_lines == []
            continue
        assert setup_uv_lines, name
        for index in setup_uv_lines:
            step_header = lines[max(0, index - 2) : index + 2]
            assert any("timeout-minutes: 5" in line for line in step_header), (
                name,
                index,
            )


def test_release_gate_runs_tests_before_publishing() -> None:
    workflow = _workflow("release-gate.yml")

    test_position = workflow.index("uses: ./.github/workflows/test.yml")
    pg_test_position = workflow.index("uses: ./.github/workflows/test-pg-extension.yml")
    publish_position = workflow.index("uses: ./.github/workflows/release.yml")

    assert test_position < publish_position
    assert pg_test_position < publish_position
    assert "verify_paired_reactor_artifacts: true" in workflow
    assert "verify-tag-current:" in workflow
    assert "expected: ${EXPECTED_SHA}" in workflow


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


def test_pg_release_gate_is_github_only() -> None:
    workflow = _workflow("release-gate-pg.yml")
    lower_workflow = workflow.lower()

    assert 'tags:\n      - "taut_pg/v*"' in workflow
    assert "uses: ./.github/workflows/test.yml" in workflow
    assert "uses: ./.github/workflows/test-pg-extension.yml" in workflow
    assert "package_name: taut-pg" in workflow
    assert "package_dir: extensions/taut_pg" in workflow
    assert "verify-tag-current:" in workflow
    assert "uv publish" not in lower_workflow
    assert "pypi" not in lower_workflow
    assert "trusted-publishing" not in lower_workflow
    assert "verify_paired_reactor_artifacts: true" not in workflow


def test_summon_release_gate_is_github_only() -> None:
    workflow = _workflow("release-gate-summon.yml")
    lower_workflow = workflow.lower()

    assert 'tags:\n      - "taut_summon/v*"' in workflow
    assert "uses: ./.github/workflows/test.yml" in workflow
    assert "uses: ./.github/workflows/test-pg-extension.yml" not in workflow
    assert "package_name: taut-summon" in workflow
    assert "package_dir: extensions/taut_summon" in workflow
    assert "verify-tag-current:" in workflow
    assert "verify_paired_reactor_artifacts: true" in workflow
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
