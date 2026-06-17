from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def test_test_workflow_is_reusable_and_runs_release_gates() -> None:
    workflow = _workflow("test.yml")

    assert "workflow_call:" in workflow
    assert "pytest -v --tb=short" in workflow
    assert (
        "ruff check taut tests bin assets/gen_taut_logo.py generate_knot.py" in workflow
    )
    assert (
        "ruff format --check taut tests bin assets/gen_taut_logo.py generate_knot.py"
        in workflow
    )
    assert "mypy taut tests bin/release.py --config-file pyproject.toml" in workflow
    assert "uv build" in workflow


def test_release_gate_runs_tests_before_publishing() -> None:
    workflow = _workflow("release-gate.yml")

    test_position = workflow.index("uses: ./.github/workflows/test.yml")
    publish_position = workflow.index("uses: ./.github/workflows/release.yml")

    assert test_position < publish_position
    assert "verify-tag-current:" in workflow
    assert "expected: ${EXPECTED_SHA}" in workflow


def test_release_workflow_publishes_github_release_only() -> None:
    workflow = _workflow("release.yml")
    lower_workflow = workflow.lower()

    assert "softprops/action-gh-release@" in workflow
    assert "dist/*.tar.gz" in workflow
    assert "dist/*.whl" in workflow
    assert "uv publish" not in lower_workflow
    assert "pypi" not in lower_workflow
    assert "trusted-publishing" not in lower_workflow
