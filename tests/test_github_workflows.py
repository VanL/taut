from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"

pytestmark = pytest.mark.sqlite_only


def _workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def test_test_workflow_is_reusable_and_runs_release_gates() -> None:
    workflow = _workflow("test.yml")

    assert "workflow_call:" in workflow
    assert "pytest -v --tb=short" in workflow
    assert "ruff check taut tests bin" in workflow
    assert "ruff format --check taut tests bin" in workflow
    # Guard against the stale-path regression: neither the removed generator script
    # nor the deleted logo asset may reappear in the lint command.
    assert "generate_knot.py" not in workflow
    assert "gen_taut_logo" not in workflow
    assert "mypy taut tests bin/release.py --config-file pyproject.toml" in workflow
    assert "uv build" in workflow


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


def test_summon_release_gate_is_github_only() -> None:
    workflow = _workflow("release-gate-summon.yml")
    lower_workflow = workflow.lower()

    assert 'tags:\n      - "taut_summon/v*"' in workflow
    assert "uses: ./.github/workflows/test.yml" in workflow
    assert "uses: ./.github/workflows/test-pg-extension.yml" not in workflow
    assert "package_name: taut-summon" in workflow
    assert "package_dir: extensions/taut_summon" in workflow
    assert "verify-tag-current:" in workflow
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
