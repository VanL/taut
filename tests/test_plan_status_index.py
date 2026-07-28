"""Contract tests for the [DOM-14] structured plan-status gate."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.sqlite_only

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "bin" / "check-plan-status-index"
ALLOWED_STATUSES = (
    "draft",
    "active",
    "status-review",
    "completed",
    "superseded",
    "retired-pending",
)


def _write_index(path: Path, rows: list[tuple[str, str, str]]) -> None:
    lines = [
        "# Plans",
        "",
        "## Plan Status Index",
        "",
        "| Plan | Status | Exemplar | Note |",
        "|------|--------|----------|------|",
    ]
    lines.extend(
        f"| `{plan}` | {status} | {exemplar} | fixture |"
        for plan, status, exemplar in rows
    )
    lines.extend(("", "## Retired Plans", ""))
    path.write_text("\n".join(lines), encoding="utf-8")


def _run(index: Path, plans_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--index",
            str(index),
            "--plans-dir",
            str(plans_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("status", ALLOWED_STATUSES)
@pytest.mark.parametrize("exemplar", ("yes", "no"))
def test_each_status_and_exemplar_value_fires(
    tmp_path: Path, status: str, exemplar: str
) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "one-plan.md").write_text("# One\n", encoding="utf-8")
    index = plans / "README.md"
    _write_index(index, [("one-plan.md", status, exemplar)])

    result = _run(index, plans)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "plan status index OK" in result.stdout


@pytest.mark.parametrize(
    ("case", "files", "rows", "expected"),
    [
        (
            "missing row",
            ("one-plan.md", "two-plan.md"),
            (("one-plan.md", "active", "no"),),
            "missing index row: two-plan.md",
        ),
        (
            "duplicate row",
            ("one-plan.md",),
            (
                ("one-plan.md", "active", "no"),
                ("one-plan.md", "active", "no"),
            ),
            "duplicate index row: one-plan.md",
        ),
        (
            "nonexistent path",
            (),
            (("ghost-plan.md", "active", "no"),),
            "index row has no plan file: ghost-plan.md",
        ),
        (
            "unknown status",
            ("one-plan.md",),
            (("one-plan.md", "done-ish", "no"),),
            "unknown status 'done-ish': one-plan.md",
        ),
        (
            "unknown exemplar",
            ("one-plan.md",),
            (("one-plan.md", "active", "maybe"),),
            "unknown exemplar value 'maybe': one-plan.md",
        ),
    ],
)
def test_each_declared_defect_fails(
    tmp_path: Path,
    case: str,
    files: tuple[str, ...],
    rows: tuple[tuple[str, str, str], ...],
    expected: str,
) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    for filename in files:
        (plans / filename).write_text(f"# {filename}\n", encoding="utf-8")
    index = plans / "README.md"
    _write_index(index, list(rows))

    result = _run(index, plans)

    assert result.returncode == 1, case
    assert expected in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "table",
    (
        "| Wrong | Columns |\n|---|---|",
        (
            "| Plan | Status | Exemplar | Note |\n"
            "|:|--------|----------|------|\n"
            "| `one-plan.md` | active | no | fixture |"
        ),
    ),
)
def test_malformed_status_table_fails(tmp_path: Path, table: str) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "one-plan.md").write_text("# One\n", encoding="utf-8")
    index = plans / "README.md"
    index.write_text(
        f"# Plans\n\n## Plan Status Index\n\n{table}\n",
        encoding="utf-8",
    )

    result = _run(index, plans)

    assert result.returncode == 1
    assert "malformed or missing plan status table" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_invocation_error_is_exit_2_without_traceback(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    plans = tmp_path / "plans"
    plans.mkdir()

    result = _run(missing, plans)

    assert result.returncode == 2
    assert "cannot read index" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_current_repository_plan_status_index_passes() -> None:
    result = _run(
        REPO_ROOT / "docs" / "plans" / "README.md",
        REPO_ROOT / "docs" / "plans",
    )

    assert result.returncode == 0, result.stdout + result.stderr
