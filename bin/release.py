#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, NoReturn

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
CONSTANTS_PATH = PROJECT_ROOT / "taut" / "_constants.py"
VERSION_FILES: Final = (PYPROJECT_PATH, CONSTANTS_PATH)
GITHUB_RELEASE_WORKFLOW: Final = (
    PROJECT_ROOT / ".github" / "workflows" / "release-gate.yml"
)
PENDING_RELEASE_COMMIT: Final = "<pending release commit>"

SEMVER_PATTERN: Final = re.compile(r"\d+\.\d+\.\d+")
PYPROJECT_VERSION_PATTERN: Final = re.compile(r'(?m)^version = "([^"]+)"')
CONSTANTS_VERSION_PATTERN: Final = re.compile(
    r'(?m)^__version__(?::[^=]+)? = "([^"]+)"'
)

Command = tuple[str, ...]
TagActionName = Literal[
    "create",
    "replace_local",
    "replace_remote",
    "reuse_remote",
    "push_local",
]


@dataclass(frozen=True)
class ReleaseTarget:
    name: str
    package_name: str
    github_release: bool
    pypi_publish: bool

    def tag_for_version(self, version: str) -> str:
        return f"v{version}"


@dataclass(frozen=True)
class ReleaseState:
    target: ReleaseTarget
    version: str
    tag_name: str
    github_release_exists: bool
    local_tag_commit: str | None
    remote_tag_commit: str | None


@dataclass(frozen=True)
class TagAction:
    action: TagActionName
    state: ReleaseState
    head_commit: str


@dataclass(frozen=True)
class CommandStep:
    command: Command
    description: str


ROOT_TARGET: Final = ReleaseTarget(
    name="taut",
    package_name="taut",
    github_release=True,
    pypi_publish=False,
)


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def validate_version(version: str) -> None:
    if SEMVER_PATTERN.fullmatch(version) is None:
        fail(f"Invalid version {version!r}; expected X.Y.Z")


def _read_version(path: Path, pattern: re.Pattern[str], label: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = pattern.search(text)
    if match is None:
        fail(f"Could not find {label} version in {path.relative_to(PROJECT_ROOT)}")
    version = match.group(1)
    validate_version(version)
    return version


def read_current_version() -> str:
    pyproject_version = _read_version(
        PYPROJECT_PATH, PYPROJECT_VERSION_PATTERN, "pyproject.toml"
    )
    constants_version = _read_version(
        CONSTANTS_PATH, CONSTANTS_VERSION_PATTERN, "taut/_constants.py"
    )
    if pyproject_version != constants_version:
        fail(
            "Version mismatch: "
            f"pyproject.toml has {pyproject_version}, "
            f"taut/_constants.py has {constants_version}"
        )
    return pyproject_version


def _replace_version(
    path: Path, pattern: re.Pattern[str], replacement: str, label: str
) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        fail(f"Could not update {label} version in {path.relative_to(PROJECT_ROOT)}")
    path.write_text(updated, encoding="utf-8")


def write_version_files(version: str) -> None:
    validate_version(version)
    _replace_version(
        PYPROJECT_PATH,
        re.compile(r'(?m)^version = "[^"]+"'),
        f'version = "{version}"',
        "pyproject.toml",
    )
    _replace_version(
        CONSTANTS_PATH,
        re.compile(r'(?m)^(__version__(?::[^=]+)? = )"[^"]+"'),
        rf'\g<1>"{version}"',
        "taut/_constants.py",
    )


def format_command(command: Command) -> str:
    return " ".join(shlex.quote(part) for part in command)


def run_command(command: Command, *, dry_run: bool = False) -> None:
    print(f"+ {format_command(command)}")
    if dry_run:
        return
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def capture_command(command: Command) -> str:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def capture_optional_command(command: Command) -> str | None:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def current_head_commit() -> str:
    return capture_command(("git", "rev-parse", "HEAD"))


def current_branch() -> str:
    branch = capture_command(("git", "rev-parse", "--abbrev-ref", "HEAD"))
    if branch == "HEAD":
        fail("Cannot release from a detached HEAD")
    return branch


def push_current_branch(*, dry_run: bool) -> None:
    branch = capture_command(("git", "rev-parse", "--abbrev-ref", "HEAD"))
    if branch == "HEAD":
        if dry_run:
            print(
                "DRY RUN: detached HEAD; a real release would stop before branch push"
            )
            return
        fail("Cannot release from a detached HEAD")
    run_command(("git", "push", "origin", branch), dry_run=dry_run)


def is_dirty_worktree() -> bool:
    return bool(capture_command(("git", "status", "--porcelain")))


def local_tag_commit(tag_name: str) -> str | None:
    return capture_optional_command(
        ("git", "rev-parse", "--verify", f"refs/tags/{tag_name}^{{}}")
    )


def remote_tag_commit(tag_name: str) -> str | None:
    result = subprocess.run(
        (
            "git",
            "ls-remote",
            "--tags",
            "origin",
            f"refs/tags/{tag_name}",
            f"refs/tags/{tag_name}^{{}}",
        ),
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown error"
        fail(f"Could not inspect remote tag {tag_name}: {detail}")

    tag_ref = f"refs/tags/{tag_name}"
    peeled_ref = f"{tag_ref}^{{}}"
    tag_sha: str | None = None
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref == peeled_ref:
            return sha
        if ref == tag_ref:
            tag_sha = sha
    return tag_sha


def origin_remote_url() -> str:
    return capture_command(("git", "remote", "get-url", "origin"))


def github_repo_slug_from_remote(remote_url: str) -> str | None:
    patterns = (
        r"^git@github\.com:(?P<slug>[^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/(?P<slug>[^/]+/[^/]+?)(?:\.git)?$",
        r"^https://github\.com/(?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, remote_url)
        if match is not None:
            return match.group("slug")
    return None


def github_api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "taut-release-helper",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_release_exists(tag_name: str) -> bool:
    slug = github_repo_slug_from_remote(origin_remote_url())
    if slug is None:
        fail("Origin remote is not a GitHub repository; taut releases are GitHub-only")

    encoded_tag = urllib.parse.quote(tag_name, safe="")
    url = f"https://api.github.com/repos/{slug}/releases/tags/{encoded_tag}"
    request = urllib.request.Request(url, headers=github_api_headers())
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data: object = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        fail(f"GitHub release lookup failed for {tag_name}: HTTP {exc.code}")
    except urllib.error.URLError as exc:
        fail(f"GitHub release lookup failed for {tag_name}: {exc.reason}")

    return isinstance(data, dict) and data.get("tag_name") == tag_name


def inspect_release_state(target: ReleaseTarget, version: str) -> ReleaseState:
    validate_version(version)
    tag_name = target.tag_for_version(version)
    exists = github_release_exists(tag_name) if target.github_release else False
    return ReleaseState(
        target=target,
        version=version,
        tag_name=tag_name,
        github_release_exists=exists,
        local_tag_commit=local_tag_commit(tag_name),
        remote_tag_commit=remote_tag_commit(tag_name),
    )


def resolve_target_version(
    requested_version: str | None,
) -> tuple[str, str, ReleaseState]:
    current_version = read_current_version()
    target_version = requested_version or current_version
    validate_version(target_version)
    state = inspect_release_state(ROOT_TARGET, target_version)
    if state.github_release_exists:
        fail(
            f"{ROOT_TARGET.name} {target_version} already exists as a GitHub Release; "
            "choose a new version"
        )
    return current_version, target_version, state


def build_precheck_commands() -> tuple[Command, ...]:
    return (
        ("uv", "run", "pytest"),
        ("uv", "run", "ruff", "check", "taut", "tests", "bin"),
        ("uv", "run", "ruff", "format", "--check", "taut", "tests", "bin"),
        ("uv", "run", "mypy", "taut", "tests", "bin/release.py"),
    )


def build_postupdate_steps() -> tuple[CommandStep, ...]:
    return (CommandStep(("uv", "build"), "Build source and wheel artifacts"),)


def run_prechecks(*, dry_run: bool) -> None:
    for command in build_precheck_commands():
        run_command(command, dry_run=dry_run)


def run_postupdate_steps(*, dry_run: bool) -> None:
    for step in build_postupdate_steps():
        print(step.description)
        run_command(step.command, dry_run=dry_run)


def plan_tag_action(
    state: ReleaseState,
    *,
    version_changed: bool,
    head_commit: str,
    retag: bool,
) -> TagAction:
    local_commit = state.local_tag_commit
    remote_commit = state.remote_tag_commit
    tag_name = state.tag_name

    if version_changed:
        if remote_commit is not None:
            if retag:
                return TagAction("replace_remote", state, head_commit)
            fail(
                f"Remote tag {tag_name} exists at {remote_commit}; "
                "pass --retag to replace it"
            )
        if local_commit is not None:
            return TagAction("replace_local", state, head_commit)
        return TagAction("create", state, head_commit)

    if remote_commit is not None and remote_commit != head_commit:
        if retag:
            return TagAction("replace_remote", state, head_commit)
        fail(
            f"Remote tag {tag_name} exists at {remote_commit}, "
            f"not current HEAD {head_commit}; pass --retag to replace it"
        )

    if local_commit is not None and local_commit != head_commit:
        if remote_commit is None:
            return TagAction("replace_local", state, head_commit)
        fail(
            f"Local tag {tag_name} exists at {local_commit}, "
            f"not current HEAD {head_commit}"
        )

    if remote_commit is not None:
        return TagAction("reuse_remote", state, head_commit)
    if local_commit is not None:
        return TagAction("push_local", state, head_commit)
    return TagAction("create", state, head_commit)


def describe_tag_action(action: TagAction) -> str:
    tag_name = action.state.tag_name
    descriptions = {
        "create": f"create local tag {tag_name}",
        "replace_local": f"replace stale local tag {tag_name}",
        "replace_remote": f"replace remote tag {tag_name}",
        "reuse_remote": f"reuse existing remote tag {tag_name}",
        "push_local": f"push existing local tag {tag_name}",
    }
    return descriptions[action.action]


def prepare_tag(action: TagAction, *, dry_run: bool) -> None:
    tag_name = action.state.tag_name
    if action.action == "reuse_remote":
        print(
            f"Remote tag {tag_name} already points at {action.head_commit}; no tag push"
        )
        return

    if action.action == "push_local":
        print(f"Local tag {tag_name} already points at {action.head_commit}")
        return

    if action.action in {"replace_local", "replace_remote"}:
        if action.state.local_tag_commit is not None:
            run_command(("git", "tag", "-d", tag_name), dry_run=dry_run)

    run_command(("git", "tag", tag_name), dry_run=dry_run)


def push_tag(action: TagAction, *, dry_run: bool) -> None:
    tag_name = action.state.tag_name
    if action.action == "reuse_remote":
        return
    if action.action == "replace_remote":
        run_command(
            (
                "git",
                "push",
                "--force",
                "origin",
                f"refs/tags/{tag_name}:refs/tags/{tag_name}",
            ),
            dry_run=dry_run,
        )
        return
    run_command(
        ("git", "push", "origin", f"refs/tags/{tag_name}:refs/tags/{tag_name}"),
        dry_run=dry_run,
    )


def print_release_summary(
    *,
    current_version: str,
    target_version: str,
    state: ReleaseState,
    version_changed: bool,
    tag_action: TagAction,
) -> None:
    print(f"Package: {state.target.package_name}")
    print(f"Current version: {current_version}")
    print(f"Target version: {target_version}")
    print(f"Version change: {'yes' if version_changed else 'no'}")
    print(f"Tag: {state.tag_name}")
    print(f"GitHub Release exists: {'yes' if state.github_release_exists else 'no'}")
    print(f"Local tag commit: {state.local_tag_commit or '<missing>'}")
    print(f"Remote tag commit: {state.remote_tag_commit or '<missing>'}")
    print(f"Tag action: {describe_tag_action(tag_action)}")
    print("PyPI publish: disabled until the taut package-name request is cleared")


def print_publish_note(tag_name: str) -> None:
    if GITHUB_RELEASE_WORKFLOW.exists():
        print(
            f"After push, GitHub automation should create the release for {tag_name}. "
            "PyPI remains disabled."
        )
        return
    print(
        f"After push, create the GitHub Release manually from tag {tag_name}. "
        "This repository has no release-gate workflow yet, and PyPI remains disabled."
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a taut GitHub-only release.")
    parser.add_argument(
        "--version",
        help="Target version in X.Y.Z form. Defaults to the current project version.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the release plan without changing files, tags, or remotes.",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip pytest, ruff, and mypy prechecks.",
    )
    parser.add_argument(
        "--retag",
        action="store_true",
        help="Replace an existing remote tag if it points at the wrong commit.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Compatibility no-op. Taut releases are GitHub-only for now.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.publish:
        print(
            "--publish is ignored: taut is GitHub-only until PyPI name clearance; "
            "pushing the GitHub tag is the publish boundary."
        )

    dirty = is_dirty_worktree()
    if dirty:
        if args.dry_run:
            print("DRY RUN: worktree is dirty; a real release would stop here.")
        else:
            fail("Worktree is dirty; commit or stash changes before releasing")

    current_version, target_version, state = resolve_target_version(args.version)
    version_changed = target_version != current_version
    planning_head = (
        PENDING_RELEASE_COMMIT
        if version_changed and args.dry_run
        else current_head_commit()
    )
    tag_action = plan_tag_action(
        state,
        version_changed=version_changed,
        head_commit=planning_head,
        retag=args.retag,
    )
    print_release_summary(
        current_version=current_version,
        target_version=target_version,
        state=state,
        version_changed=version_changed,
        tag_action=tag_action,
    )

    if not args.skip_checks:
        run_prechecks(dry_run=args.dry_run)

    if version_changed:
        if args.dry_run:
            print(f"Would update version files to {target_version}:")
            for path in VERSION_FILES:
                print(f"  {path.relative_to(PROJECT_ROOT)}")
        else:
            write_version_files(target_version)

    run_postupdate_steps(dry_run=args.dry_run)

    if version_changed:
        run_command(
            ("git", "add", "pyproject.toml", "taut/_constants.py"),
            dry_run=args.dry_run,
        )
        run_command(
            ("git", "commit", "-m", f"Release taut {target_version}"),
            dry_run=args.dry_run,
        )

    head_commit = planning_head if args.dry_run else current_head_commit()
    tag_action = plan_tag_action(
        state,
        version_changed=version_changed,
        head_commit=head_commit,
        retag=args.retag,
    )
    prepare_tag(tag_action, dry_run=args.dry_run)

    push_current_branch(dry_run=args.dry_run)
    push_tag(tag_action, dry_run=args.dry_run)
    print_publish_note(state.tag_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
