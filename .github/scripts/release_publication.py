#!/usr/bin/env python3
"""Verify and advance exact draft-first package publication state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

GITHUB_API_BASE: Final[str] = "https://api.github.com"
GITHUB_API_VERSION: Final[str] = "2026-03-10"
PYPI_API_BASE: Final[str] = "https://pypi.org/pypi"
HTTP_TIMEOUT_SECONDS: Final[float] = 30.0
PYPI_RETRY_DELAYS: Final[tuple[int, ...]] = (5, 10, 15, 20, 30)
GITHUB_ASSET_RETRY_DELAYS: Final[tuple[int, ...]] = (2, 4, 8)


@dataclass(frozen=True)
class Publication:
    """The exact package/version/file set bound by a release manifest."""

    package: str
    version: str
    files: dict[str, str]


@dataclass(frozen=True)
class PyPIPlan:
    """One fail-closed action derived from current PyPI state."""

    state: str
    publish: bool
    skip_existing: bool


class _GitHubAssetsPending(RuntimeError):
    """GitHub has not exposed the complete uploaded asset metadata yet."""


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{label} was not a JSON object")
    return value


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(value: object) -> bool:
    return (
        isinstance(value, str)
        and value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
        and Path(value).name == value
    )


def read_publication(manifest_path: Path, dist_dir: Path) -> Publication:
    """Read the strict release manifest and recheck the local distribution bytes."""

    try:
        manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Cannot read release manifest {manifest_path}: {exc}"
        ) from exc
    manifest = _mapping(manifest_value, label="Release manifest")
    if set(manifest) != {"format", "commit", "package", "files"}:
        raise RuntimeError("Release manifest has an invalid top-level field allowlist")
    if manifest["format"] != 1:
        raise RuntimeError(
            f"Unsupported release manifest format {manifest['format']!r}"
        )
    commit = manifest["commit"]
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise RuntimeError("Release manifest commit is not an exact lowercase Git SHA")

    package = _mapping(manifest["package"], label="Release manifest package")
    if set(package) != {"name", "version"}:
        raise RuntimeError("Release manifest package has an invalid field allowlist")
    name = package["name"]
    version = package["version"]
    if (
        not isinstance(name, str)
        or not name
        or _normalized_name(name) != name
        or not isinstance(version, str)
        or not version
        or "/" in version
    ):
        raise RuntimeError("Release manifest package identity is invalid")

    raw_files = manifest["files"]
    if not isinstance(raw_files, list) or len(raw_files) != 2:
        raise RuntimeError(
            "Release manifest must allow exactly one wheel and one .tar.gz sdist"
        )
    expected: dict[str, str] = {}
    for raw_entry in raw_files:
        entry = _mapping(raw_entry, label="Release manifest file")
        if set(entry) != {"name", "sha256"}:
            raise RuntimeError("Release manifest file has an invalid field allowlist")
        filename = entry["name"]
        digest = entry["sha256"]
        if not _safe_filename(filename):
            raise RuntimeError("Release manifest contains an invalid filename")
        assert isinstance(filename, str)
        if filename in expected:
            raise RuntimeError("Release manifest contains a duplicate filename")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(f"Release manifest digest is invalid for {filename!r}")
        expected[filename] = digest

    wheels = sum(filename.endswith(".whl") for filename in expected)
    sdists = sum(filename.endswith(".tar.gz") for filename in expected)
    if (wheels, sdists) != (1, 1):
        raise RuntimeError(
            "Release manifest must allow exactly one wheel and one .tar.gz sdist"
        )

    try:
        actual_paths = tuple(sorted(dist_dir.iterdir()))
    except OSError as exc:
        raise RuntimeError(
            f"Cannot list distribution directory {dist_dir}: {exc}"
        ) from exc
    if (
        {path.name for path in actual_paths} != set(expected)
        or len(actual_paths) != len(expected)
        or any(path.is_symlink() or not path.is_file() for path in actual_paths)
    ):
        raise RuntimeError(
            "Local distribution files do not match the release manifest allowlist"
        )
    for path in actual_paths:
        if _sha256(path) != expected[path.name]:
            raise RuntimeError(f"Local distribution digest mismatch for {path.name}")

    return Publication(package=name, version=version, files=expected)


def _decode_json_response(response: Any, *, label: str) -> object:
    try:
        raw = response.read()
    except OSError as exc:
        raise RuntimeError(f"{label} response could not be read: {exc}") from exc
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc


def pypi_release_files(package: str, version: str) -> dict[str, str] | None:
    """Return exact PyPI filenames and SHA-256 digests; only 404 means absent."""

    url = (
        f"{PYPI_API_BASE}/{urllib.parse.quote(package, safe='')}/"
        f"{urllib.parse.quote(version, safe='')}/json"
    )
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "taut-release"},
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload_value = _decode_json_response(response, label="PyPI")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f"PyPI request failed with HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"PyPI request failed: {exc.reason}") from exc

    payload = _mapping(payload_value, label="PyPI response")
    info = _mapping(payload.get("info"), label="PyPI project info")
    observed_name = info.get("name")
    observed_version = info.get("version")
    if not isinstance(observed_name, str) or _normalized_name(
        observed_name
    ) != _normalized_name(package):
        raise RuntimeError(
            f"PyPI reported package {observed_name!r} instead of {package!r}"
        )
    if observed_version != version:
        raise RuntimeError(
            f"PyPI reported version {observed_version!r} instead of {version!r}"
        )

    raw_urls = payload.get("urls")
    if not isinstance(raw_urls, list):
        raise RuntimeError("PyPI response urls was not a JSON list")
    files: dict[str, str] = {}
    for raw_file in raw_urls:
        file_record = _mapping(raw_file, label="PyPI file")
        filename = file_record.get("filename")
        if not _safe_filename(filename):
            raise RuntimeError("PyPI response contained an invalid filename")
        assert isinstance(filename, str)
        if filename in files:
            raise RuntimeError(f"PyPI response contained duplicate file {filename!r}")
        digests = _mapping(file_record.get("digests"), label="PyPI file digests")
        digest = digests.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(
                f"PyPI response contained invalid digest for {filename!r}"
            )
        files[filename] = digest
    return files


def plan_pypi(expected: Publication) -> PyPIPlan:
    """Plan absent, proven-partial, or complete publication state."""

    existing = pypi_release_files(expected.package, expected.version)
    if existing is None:
        return PyPIPlan(state="absent", publish=True, skip_existing=False)
    if not existing:
        raise RuntimeError("PyPI reported the release with an empty file set")
    unexpected = sorted(set(existing) - set(expected.files))
    if unexpected:
        raise RuntimeError(f"PyPI release has unexpected files: {unexpected}")
    mismatched = sorted(
        filename
        for filename, digest in existing.items()
        if expected.files[filename] != digest
    )
    if mismatched:
        raise RuntimeError(f"PyPI release has digest mismatches: {mismatched}")
    if set(existing) == set(expected.files):
        return PyPIPlan(state="complete", publish=False, skip_existing=False)
    return PyPIPlan(state="partial", publish=True, skip_existing=True)


def verify_pypi(
    expected: Publication,
    *,
    retry_delays: Sequence[float] = PYPI_RETRY_DELAYS,
) -> None:
    """Wait a bounded interval for the complete exact PyPI file set."""

    last_state = "not checked"
    for attempt in range(len(retry_delays) + 1):
        plan = plan_pypi(expected)
        last_state = plan.state
        if plan.state == "complete":
            return
        if attempt < len(retry_delays):
            time.sleep(retry_delays[attempt])
    raise RuntimeError(
        f"PyPI did not expose the complete exact {expected.package} "
        f"{expected.version} file set; last state was {last_state}"
    )


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    return token


def github_api_request(method: str, path: str, body: object = None) -> object:
    """Send one authenticated GitHub request using only the environment token."""

    if not path.startswith("/"):
        raise RuntimeError("GitHub API path must start with /")
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{GITHUB_API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_github_token()}",
            "Content-Type": "application/json",
            "User-Agent": "taut-release-publication",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API {method} {path} failed: HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API {method} {path} failed: {exc.reason}") from exc
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GitHub API {method} {path} returned invalid JSON") from exc


def _release_page(repo: str, page: int) -> tuple[Mapping[str, object], ...]:
    encoded_repo = urllib.parse.quote(repo, safe="/")
    value = github_api_request(
        "GET",
        f"/repos/{encoded_repo}/releases?per_page=100&page={page}",
    )
    if not isinstance(value, list):
        raise RuntimeError("GitHub releases response was not a JSON list")
    return tuple(_mapping(release, label="GitHub Release") for release in value)


def list_releases(repo: str) -> tuple[Mapping[str, object], ...]:
    """List releases, including maintainer-visible drafts."""

    releases: list[Mapping[str, object]] = []
    page = 1
    while True:
        current = _release_page(repo, page)
        releases.extend(current)
        if len(current) < 100:
            return tuple(releases)
        page += 1


def resolve_tag_commit(repo: str, tag: str) -> str:
    """Resolve a lightweight or annotated remote tag to its commit."""

    encoded_repo = urllib.parse.quote(repo, safe="/")
    encoded_tag = urllib.parse.quote(tag, safe="")
    value = github_api_request(
        "GET",
        f"/repos/{encoded_repo}/git/ref/tags/{encoded_tag}",
    )
    current = _mapping(value, label="Git tag reference").get("object")
    for _ in range(8):
        tag_object = _mapping(current, label="Git tag object")
        kind = tag_object.get("type")
        sha = tag_object.get("sha")
        if not isinstance(sha, str) or not sha:
            raise RuntimeError(f"Git tag {tag} did not contain an object SHA")
        if kind == "commit":
            return sha
        if kind != "tag":
            raise RuntimeError(
                f"Git tag {tag} resolved to unsupported object type {kind!r}"
            )
        value = github_api_request(
            "GET",
            f"/repos/{encoded_repo}/git/tags/{sha}",
        )
        current = _mapping(value, label="Annotated Git tag").get("object")
    raise RuntimeError(f"Git tag {tag} exceeded the annotated-tag resolution limit")


def _require_tag(repo: str, tag: str, expected_sha: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise RuntimeError("Expected release SHA is not an exact lowercase Git SHA")
    actual_sha = resolve_tag_commit(repo, tag)
    if actual_sha != expected_sha:
        raise RuntimeError(
            f"Remote tag {tag} at {actual_sha} does not match expected release SHA "
            f"{expected_sha}"
        )


def verify_tag(*, repo: str, tag: str, expected_sha: str) -> None:
    """Require the remote release tag to remain at the tested commit."""

    _require_tag(repo, tag, expected_sha)


def _matching_releases(repo: str, tag: str) -> tuple[Mapping[str, object], ...]:
    return tuple(
        release for release in list_releases(repo) if release.get("tag_name") == tag
    )


def _release_id(release: Mapping[str, object]) -> int:
    release_id = release.get("id")
    if type(release_id) is not int:
        raise RuntimeError("GitHub Release did not contain a numeric id")
    return release_id


def _find_release(repo: str, release_id: int) -> Mapping[str, object]:
    page = 1
    while True:
        current = _release_page(repo, page)
        for release in current:
            if _release_id(release) == release_id:
                return release
        if len(current) < 100:
            raise RuntimeError(f"GitHub Release {release_id} disappeared")
        page += 1


def require_exact_assets(
    release: Mapping[str, object],
    expected: Publication,
) -> None:
    """Require an uploaded GitHub asset with the exact digest for each file."""

    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        raise RuntimeError("GitHub Release asset set was not a JSON list")
    seen: set[str] = set()
    observed: dict[str, str] = {}
    incomplete: list[str] = []
    for raw_asset in raw_assets:
        asset = _mapping(raw_asset, label="GitHub Release asset")
        name = asset.get("name")
        if not _safe_filename(name):
            raise RuntimeError("GitHub Release asset set contained an invalid name")
        assert isinstance(name, str)
        if name in seen:
            raise RuntimeError("GitHub Release asset set contained duplicate names")
        seen.add(name)
        digest = asset.get("digest")
        if digest is None:
            incomplete.append(name)
        elif (
            not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        ):
            raise RuntimeError(
                f"GitHub Release asset {name!r} had an invalid SHA-256 digest"
            )
        else:
            observed[name] = digest.removeprefix("sha256:")
        if asset.get("state") != "uploaded":
            incomplete.append(name)
    missing = sorted(set(expected.files) - seen)
    extra = sorted(seen - set(expected.files))
    mismatched = sorted(
        name
        for name in set(observed) & set(expected.files)
        if observed[name] != expected.files[name]
    )
    if extra or mismatched:
        raise RuntimeError(
            "GitHub Release asset set does not match expected files; "
            f"missing={missing}, extra={extra}, mismatched={mismatched}, "
            f"incomplete={sorted(set(incomplete))}"
        )
    if missing or incomplete:
        raise _GitHubAssetsPending(
            "GitHub Release asset metadata is not complete yet; "
            f"missing={missing}, incomplete={sorted(set(incomplete))}"
        )


def _wait_for_exact_assets(
    *,
    repo: str,
    tag: str,
    release: Mapping[str, object],
    expected: Publication,
    retry_delays: Sequence[float] | None = None,
) -> Mapping[str, object]:
    """Bound eventual GitHub asset-metadata visibility without weakening checks."""

    delays = GITHUB_ASSET_RETRY_DELAYS if retry_delays is None else retry_delays
    current = release
    release_id = _release_id(release)
    last_pending = ""
    for attempt in range(len(delays) + 1):
        try:
            require_exact_assets(current, expected)
        except _GitHubAssetsPending as exc:
            last_pending = str(exc)
        else:
            return current
        if attempt < len(delays):
            time.sleep(delays[attempt])
            current = _find_release(repo, release_id)
            if current.get("tag_name") != tag:
                raise RuntimeError(
                    f"GitHub Release {release_id} changed tag while waiting for "
                    f"asset metadata"
                )
    raise RuntimeError(
        f"GitHub Release for tag {tag} did not expose the complete exact asset "
        f"set after the bounded wait: {last_pending}"
    )


def stage_draft(
    *,
    repo: str,
    tag: str,
    expected_sha: str,
    expected: Publication,
) -> bool:
    """Prepare to stage a draft; return false only for an exact immutable rerun."""

    _require_tag(repo, tag, expected_sha)
    matches = _matching_releases(repo, tag)
    if len(matches) > 1:
        raise RuntimeError(
            f"Expected at most one GitHub Release for tag {tag}, found {len(matches)}"
        )
    if not matches:
        return True
    release = matches[0]
    if release.get("draft") is True:
        encoded_repo = urllib.parse.quote(repo, safe="/")
        github_api_request(
            "DELETE",
            f"/repos/{encoded_repo}/releases/{_release_id(release)}",
        )
        return True
    if release.get("draft") is not False:
        raise RuntimeError(f"GitHub Release for tag {tag} has invalid draft state")
    if release.get("immutable") is not True:
        raise RuntimeError(f"Published GitHub Release for tag {tag} is not immutable")
    require_exact_assets(release, expected)
    pypi_plan = plan_pypi(expected)
    if pypi_plan.state != "complete":
        # The managed order verifies PyPI before making GitHub public, so this
        # state is unreachable unless publication happened outside that order.
        # Refuse to backfill PyPI from a public release rather than guessing.
        raise RuntimeError(
            f"Published GitHub Release for tag {tag} cannot be used to create or "
            f"complete a PyPI release; PyPI state is {pypi_plan.state}"
        )
    return False


def finalize_release(
    *,
    repo: str,
    tag: str,
    expected_sha: str,
    expected: Publication,
) -> None:
    """Verify PyPI and publish one exact draft, or validate an exact rerun."""

    _require_tag(repo, tag, expected_sha)
    matches = _matching_releases(repo, tag)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one GitHub Release for tag {tag}, found {len(matches)}"
        )
    release = matches[0]
    if release.get("draft") is False:
        if release.get("immutable") is not True:
            raise RuntimeError(
                f"Published GitHub Release for tag {tag} is not immutable"
            )
        require_exact_assets(release, expected)
        verify_pypi(expected, retry_delays=())
        return
    if release.get("draft") is not True:
        raise RuntimeError(f"GitHub Release for tag {tag} has invalid draft state")

    release = _wait_for_exact_assets(
        repo=repo,
        tag=tag,
        release=release,
        expected=expected,
    )
    verify_pypi(expected, retry_delays=())

    if release.get("draft") is False:
        if release.get("immutable") is not True:
            raise RuntimeError(
                f"Published GitHub Release for tag {tag} is not immutable"
            )
        return
    if release.get("draft") is not True:
        raise RuntimeError(f"GitHub Release for tag {tag} has invalid draft state")

    encoded_repo = urllib.parse.quote(repo, safe="/")
    value = github_api_request(
        "PATCH",
        f"/repos/{encoded_repo}/releases/{_release_id(release)}",
        {"draft": False},
    )
    published = _mapping(value, label="Published GitHub Release")
    if published.get("draft") is not False:
        raise RuntimeError(f"GitHub Release for tag {tag} remained a draft")
    if published.get("immutable") is not True:
        raise RuntimeError(f"Published GitHub Release for tag {tag} is not immutable")
    require_exact_assets(published, expected)


def _publication_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dist-dir", type=Path, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    stage = commands.add_parser("stage-draft")
    stage.add_argument("--repo", required=True)
    stage.add_argument("--tag", required=True)
    stage.add_argument("--expected-sha", required=True)
    _publication_arguments(stage)

    plan = commands.add_parser("plan-pypi")
    _publication_arguments(plan)

    verify = commands.add_parser("verify-pypi")
    _publication_arguments(verify)

    verify_tag_parser = commands.add_parser("verify-tag")
    verify_tag_parser.add_argument("--repo", required=True)
    verify_tag_parser.add_argument("--tag", required=True)
    verify_tag_parser.add_argument("--expected-sha", required=True)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--repo", required=True)
    finalize.add_argument("--tag", required=True)
    finalize.add_argument("--expected-sha", required=True)
    _publication_arguments(finalize)
    return parser


def _write_outputs(values: Mapping[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output_path:
        raise RuntimeError("GITHUB_OUTPUT is required")
    with Path(output_path).open("a", encoding="utf-8") as stream:
        for name, value in values.items():
            stream.write(f"{name}={value}\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify-tag":
            verify_tag(
                repo=args.repo,
                tag=args.tag,
                expected_sha=args.expected_sha,
            )
            return 0
        expected = read_publication(args.manifest, args.dist_dir)
        if args.command == "stage-draft":
            required = stage_draft(
                repo=args.repo,
                tag=args.tag,
                expected_sha=args.expected_sha,
                expected=expected,
            )
            _write_outputs({"stage_required": str(required).lower()})
        elif args.command == "plan-pypi":
            plan = plan_pypi(expected)
            _write_outputs(
                {
                    "state": plan.state,
                    "publish": str(plan.publish).lower(),
                    "skip_existing": str(plan.skip_existing).lower(),
                }
            )
        elif args.command == "verify-pypi":
            verify_pypi(expected)
        else:
            finalize_release(
                repo=args.repo,
                tag=args.tag,
                expected_sha=args.expected_sha,
                expected=expected,
            )
    except (OSError, RuntimeError) as exc:
        print(f"release publication failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
