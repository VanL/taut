from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COALESCE_CHECK = PROJECT_ROOT / "bin" / "coalesce-check"

pytestmark = pytest.mark.sqlite_only


def _coalesce_repository(tmp_path: Path) -> tuple[Path, str]:
    script = tmp_path / "bin" / "coalesce-check"
    script.parent.mkdir()
    script.write_bytes(COALESCE_CHECK.read_bytes())
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "lessons.md").write_text("", encoding="utf-8")
    for command in (
        ("git", "init", "-b", "main"),
        ("git", "config", "user.name", "Coalesce Test"),
        ("git", "config", "user.email", "coalesce-test@example.com"),
        ("git", "add", "."),
        ("git", "commit", "-m", "Initial evidence"),
    ):
        subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    sha = subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=tmp_path, text=True
    ).strip()
    return script, sha


def _run_coalesce(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(script)),
        cwd=script.parent.parent,
        text=True,
        capture_output=True,
        check=False,
    )


def test_foreign_claim_is_informational(tmp_path: Path) -> None:
    script, _sha = _coalesce_repository(tmp_path)
    (tmp_path / "docs" / "coalescing.md").write_text(
        "agent-guidance evidence `deadbeef`\n",
        encoding="utf-8",
    )

    result = _run_coalesce(script)

    assert result.returncode == 0
    assert "1 foreign claim(s)" in result.stdout
    assert "all cues resolve" in result.stdout


def test_local_only_claim_is_informational(tmp_path: Path) -> None:
    script, published_sha = _coalesce_repository(tmp_path)
    subprocess.run(
        ("git", "update-ref", "refs/remotes/origin/main", published_sha),
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "local.txt").write_text("local\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=tmp_path, check=True)
    subprocess.run(
        ("git", "commit", "-m", "Local evidence"),
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    local_sha = subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=tmp_path, text=True
    ).strip()
    (tmp_path / "docs" / "coalescing.md").write_text(
        f"local evidence `{local_sha}`\n",
        encoding="utf-8",
    )

    result = _run_coalesce(script)

    assert result.returncode == 0
    assert "local-only pin (1)" in result.stdout
    assert "all cues resolve" in result.stdout


def test_broken_retrieval_cue_fails(tmp_path: Path) -> None:
    script, sha = _coalesce_repository(tmp_path)
    (tmp_path / "docs" / "coalescing.md").write_text(
        f"broken cue `git show {sha}:missing.txt`\n",
        encoding="utf-8",
    )

    result = _run_coalesce(script)

    assert result.returncode == 1
    assert f"cue `git show {sha}:missing.txt` does not resolve here" in result.stdout
    assert "BROKEN (1)" in result.stdout


def test_shallow_clone_skips_loudly(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _script, _sha = _coalesce_repository(source)
    (source / "docs" / "coalescing.md").write_text(
        "evidence `deadbeef`\n",
        encoding="utf-8",
    )
    (source / "docs" / "lessons.md").write_text(
        "- 2026-08-01: a dated entry.\n",
        encoding="utf-8",
    )
    subprocess.run(("git", "add", "."), cwd=source, check=True)
    subprocess.run(
        ("git", "commit", "-m", "Second commit"),
        cwd=source,
        check=True,
        capture_output=True,
    )
    clone = tmp_path / "shallow"
    subprocess.run(
        ("git", "clone", "--quiet", "--depth", "1", source.as_uri(), str(clone)),
        check=True,
        capture_output=True,
    )
    script = clone / "bin" / "coalesce-check"

    result = _run_coalesce(script)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "shallow clone detected" in result.stdout
    assert "retrieval cues found (syntax only, unverified here):" in result.stdout
    assert "lessons dated entries:" in result.stdout
