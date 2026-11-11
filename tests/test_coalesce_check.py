from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

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


def test_retired_plan_source_sha_must_resolve(tmp_path: Path) -> None:
    script, _sha = _coalesce_repository(tmp_path)
    (tmp_path / "docs" / "coalescing.md").write_text("", encoding="utf-8")
    plans = tmp_path / "docs" / "plans"
    plans.mkdir()
    (plans / "README.md").write_text(
        """## Retired Plans

| Plan | Dates | Outcome | Absorbed into | Source SHA |
|------|-------|---------|---------------|------------|
| `retired-plan.md` | 2026-09-24 | done | current docs | `deadbee` |
""",
        encoding="utf-8",
    )

    result = _run_coalesce(script)

    assert result.returncode == 1
    assert (
        "retired plan `retired-plan.md` source `deadbee` does not resolve"
        in result.stdout
    )
    assert "BROKEN (1)" in result.stdout


def test_retired_plan_must_exist_at_its_source_sha(tmp_path: Path) -> None:
    script, sha = _coalesce_repository(tmp_path)
    (tmp_path / "docs" / "coalescing.md").write_text("", encoding="utf-8")
    plans = tmp_path / "docs" / "plans"
    plans.mkdir()
    (plans / "README.md").write_text(
        f"""## Retired Plans

| Plan | Dates | Outcome | Absorbed into | Source SHA |
|------|-------|---------|---------------|------------|
| `missing-plan.md` | 2026-09-24 | done | current docs | `{sha}` |
""",
        encoding="utf-8",
    )

    result = _run_coalesce(script)

    assert result.returncode == 1
    assert (
        f"retired plan `missing-plan.md` is missing at source `{sha}`" in result.stdout
    )


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


def _load_coalesce_module() -> Any:
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader

    loader = SourceFileLoader("coalesce_check_mod", str(COALESCE_CHECK))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


def test_batch_object_info_and_reachable_commits_single_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script, published_sha = _coalesce_repository(tmp_path)
    subprocess.run(
        ("git", "update-ref", "refs/remotes/origin/main", published_sha),
        cwd=tmp_path,
        check=True,
    )
    blob_sha = subprocess.check_output(
        ("git", "hash-object", "-w", "--stdin"),
        cwd=tmp_path,
        input="not a commit\n",
        text=True,
    ).strip()
    (tmp_path / "local.txt").write_text("local\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=tmp_path, check=True)
    subprocess.run(
        ("git", "commit", "-m", "Local commit"),
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    local_sha = subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=tmp_path, text=True
    ).strip()

    mod = _load_coalesce_module()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    git_calls: list[tuple[str, ...]] = []
    real_git = mod.git

    def counting_git(*args: str, **kwargs: Any) -> Any:
        git_calls.append(args)
        return real_git(*args, **kwargs)

    monkeypatch.setattr(mod, "git", counting_git)

    info = mod.batch_object_info(
        {
            f"{published_sha}^{{commit}}",
            f"{published_sha}:docs/lessons.md",
            f"{published_sha}:docs/missing.md",
            f"{blob_sha}^{{commit}}",
            "deadbeef^{commit}",
        }
    )
    assert info[f"{published_sha}^{{commit}}"] == (published_sha, "commit")
    assert info[f"{published_sha}:docs/lessons.md"] is not None
    assert info[f"{published_sha}:docs/lessons.md"][1] == "blob"
    assert info[f"{published_sha}:docs/missing.md"] is None
    assert info[f"{blob_sha}^{{commit}}"] is None
    assert info["deadbeef^{commit}"] is None

    reachable = mod.reachable_commits("origin/main")
    assert published_sha in reachable
    assert local_sha not in reachable
    assert len(git_calls) == 2
    assert git_calls[0][0] == "cat-file"
    assert git_calls[1] == ("rev-list", "origin/main")

    # Non-commit blob SHA cited without repository attribution must fail as broken
    script = tmp_path / "bin" / "coalesce-check"
    (tmp_path / "docs" / "coalescing.md").write_text(
        f"blob sha `{blob_sha[:12]}`\n",
        encoding="utf-8",
    )
    result = _run_coalesce(script)
    assert result.returncode == 1
    assert "resolves nowhere here" in result.stdout
