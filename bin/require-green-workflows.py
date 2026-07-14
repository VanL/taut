#!/usr/bin/env python3
"""Select immutable GitHub workflow and artifact evidence for a release SHA."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

CANONICAL_BRANCHES = frozenset({"main", "master"})
HTTP_TIMEOUT_SECONDS = 30
WORKFLOW_OBSERVATION_SECONDS = 95 * 60
WORKFLOW_POLL_SECONDS = 60
ARTIFACT_VISIBILITY_SECONDS = 2 * 60
ARTIFACT_POLL_SECONDS = 10


def _required_str(raw: Mapping[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"GitHub response field {field!r} must be a string")
    return value


def _required_int(raw: Mapping[str, Any], field: str) -> int:
    value = raw.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise EvidenceError(
            f"GitHub response field {field!r} must be a positive integer"
        )
    return value


def _repository_identity(raw: object, field: str) -> tuple[int, str]:
    if not isinstance(raw, Mapping):
        raise EvidenceError(f"GitHub response field {field!r} must be an object")
    return _required_int(raw, "id"), _required_str(raw, "full_name")


def _normalized_workflow_path(value: str) -> str:
    path = value.split("@", 1)[0].removeprefix("./")
    normalized = PurePosixPath(path).as_posix()
    if not normalized.startswith(".github/workflows/"):
        raise InvocationError(
            "workflow file must be under .github/workflows or be a numeric id"
        )
    return normalized


class EvidenceError(RuntimeError):
    """A fail-closed workflow-evidence error."""


class InvocationError(EvidenceError):
    """An invalid CLI invocation or missing GitHub environment value."""


class MissingEvidenceError(EvidenceError):
    """Expected evidence is not visible yet and may be polled."""


class TransientAPIError(EvidenceError):
    """A bounded-retry GitHub transport or server failure."""


class RateLimitError(EvidenceError):
    """A GitHub response that supplies a server-owned observation delay."""

    def __init__(self, message: str, *, retry_after_seconds: float) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _rate_limit_delay(
    headers: Mapping[str, str], *, wall_clock: Callable[[], float]
) -> float:
    delays: list[float] = []
    retry_after = headers.get("Retry-After")
    if retry_after:
        try:
            delays.append(max(0.0, float(retry_after)))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after).timestamp()
            except (TypeError, ValueError, OverflowError):
                pass
            else:
                delays.append(max(0.0, retry_at - wall_clock()))
    reset = headers.get("X-RateLimit-Reset")
    if reset:
        try:
            delays.append(max(0.0, float(reset) - wall_clock()))
        except ValueError:
            pass
    return max(delays, default=60.0)


def github_json_get(
    url: str,
    *,
    token: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
    wall_clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Fetch one GitHub REST object with fail-closed response classification."""

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "taut-release-evidence-gate",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        headers: Any = exc.headers or {}
        is_rate_limited = exc.code == 429 or (
            exc.code == 403
            and (
                headers.get("X-RateLimit-Remaining") == "0"
                or headers.get("Retry-After") is not None
            )
        )
        if is_rate_limited:
            raise RateLimitError(
                f"GitHub API rate limited request with HTTP {exc.code}",
                retry_after_seconds=_rate_limit_delay(headers, wall_clock=wall_clock),
            ) from None
        detail = _one_line(exc.read().decode("utf-8", errors="replace"))
        if 500 <= exc.code <= 599:
            raise TransientAPIError(
                f"GitHub API returned HTTP {exc.code}: {detail}"
            ) from None
        raise EvidenceError(f"GitHub API returned HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TransientAPIError(
            f"GitHub API request failed: {_one_line(str(exc))}"
        ) from None
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise EvidenceError(
            f"GitHub API response was not a valid JSON object: {_one_line(str(exc))}"
        ) from None
    if not isinstance(payload, dict):
        raise EvidenceError("GitHub API response was not a valid JSON object")
    return payload


class GateArgumentParser(argparse.ArgumentParser):
    """Keep argument failures inside the CLI's concise error boundary."""

    def error(self, message: str) -> NoReturn:
        raise InvocationError(message)


@dataclass(frozen=True)
class WorkflowRequirement:
    """One required workflow, addressed by stable file path or numeric id."""

    key: str
    workflow_file: str | None
    workflow_id: int | None

    @classmethod
    def parse(cls, value: str) -> WorkflowRequirement:
        key, separator, target = value.partition("=")
        if not separator or re.fullmatch(r"[a-z][a-z0-9_]*", key) is None:
            raise InvocationError("--workflow must use key=workflow-file-or-id")
        if target.isdecimal():
            workflow_id = int(target)
            if workflow_id <= 0:
                raise InvocationError("workflow id must be positive")
            return cls(key=key, workflow_file=None, workflow_id=workflow_id)
        return cls(
            key=key,
            workflow_file=_normalized_workflow_path(target),
            workflow_id=None,
        )


@dataclass(frozen=True)
class WorkflowRun:
    """Identity and state fields bound by release evidence selection."""

    id: int
    workflow_id: int
    path: str
    event: str
    head_sha: str
    head_branch: str
    status: str
    conclusion: str | None
    run_attempt: int
    created_at: str
    html_url: str
    repository_id: int
    repository: str
    head_repository_id: int
    head_repository: str

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> WorkflowRun:
        conclusion = raw.get("conclusion")
        if conclusion is not None and not isinstance(conclusion, str):
            raise EvidenceError(
                "GitHub response field 'conclusion' must be null or a string"
            )
        repository_id, repository = _repository_identity(
            raw.get("repository"), "repository"
        )
        head_repository_id, head_repository = _repository_identity(
            raw.get("head_repository"), "head_repository"
        )
        return cls(
            id=_required_int(raw, "id"),
            workflow_id=_required_int(raw, "workflow_id"),
            path=_required_str(raw, "path"),
            event=_required_str(raw, "event"),
            head_sha=_required_str(raw, "head_sha"),
            head_branch=_required_str(raw, "head_branch"),
            status=_required_str(raw, "status"),
            conclusion=conclusion,
            run_attempt=_required_int(raw, "run_attempt"),
            created_at=_required_str(raw, "created_at"),
            html_url=_required_str(raw, "html_url"),
            repository_id=repository_id,
            repository=repository,
            head_repository_id=head_repository_id,
            head_repository=head_repository,
        )


@dataclass(frozen=True)
class WorkflowCheck:
    """One poll's exact-SHA workflow classification."""

    passed: dict[str, WorkflowRun]
    missing: tuple[str, ...]
    pending: dict[str, WorkflowRun]
    failed: dict[str, WorkflowRun]

    @property
    def ready(self) -> bool:
        return not self.missing and not self.pending and not self.failed


@dataclass(frozen=True)
class Artifact:
    """Immutable GitHub artifact metadata bound to a workflow run."""

    id: int
    name: str
    expired: bool
    digest: str
    workflow_run_id: int
    repository_id: int
    head_repository_id: int
    head_branch: str
    head_sha: str

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Artifact:
        expired = raw.get("expired")
        if not isinstance(expired, bool):
            raise EvidenceError("GitHub artifact expired field must be boolean")
        digest = _required_str(raw, "digest")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise EvidenceError("GitHub artifact digest must be sha256 hexadecimal")
        workflow_run = raw.get("workflow_run")
        if not isinstance(workflow_run, Mapping):
            raise EvidenceError("GitHub artifact workflow_run must be an object")
        return cls(
            id=_required_int(raw, "id"),
            name=_required_str(raw, "name"),
            expired=expired,
            digest=digest,
            workflow_run_id=_required_int(workflow_run, "id"),
            repository_id=_required_int(workflow_run, "repository_id"),
            head_repository_id=_required_int(workflow_run, "head_repository_id"),
            head_branch=_required_str(workflow_run, "head_branch"),
            head_sha=_required_str(workflow_run, "head_sha"),
        )


def attempt_artifact_name(prefix: str, run_attempt: int) -> str:
    """Return the exact attempt-qualified artifact name."""

    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", prefix) is None:
        raise InvocationError("artifact prefix contains unsupported characters")
    if run_attempt <= 0:
        raise InvocationError("run attempt must be positive")
    return f"{prefix}-attempt-{run_attempt}"


def _require_single_page(
    payload: Mapping[str, Any], *, field: str
) -> list[Mapping[str, Any]]:
    raw_items = payload.get(field)
    if not isinstance(raw_items, list) or any(
        not isinstance(raw, Mapping) for raw in raw_items
    ):
        raise EvidenceError(f"GitHub response must contain an {field} object list")
    total_count = payload.get("total_count", len(raw_items))
    if (
        not isinstance(total_count, int)
        or isinstance(total_count, bool)
        or total_count != len(raw_items)
    ):
        raise EvidenceError(f"GitHub {field} response cannot be resolved in one page")
    return raw_items


def _verify_artifact_against_run(artifact: Artifact, run: WorkflowRun) -> None:
    if artifact.expired:
        raise EvidenceError("release artifact is expired")
    if artifact.workflow_run_id != run.id:
        raise EvidenceError("release artifact belongs to the wrong workflow run")
    if artifact.repository_id != run.repository_id:
        raise EvidenceError("release artifact belongs to the wrong repository")
    if artifact.head_repository_id != run.head_repository_id:
        raise EvidenceError("release artifact belongs to the wrong head repository")
    if artifact.head_branch != run.head_branch:
        raise EvidenceError("release artifact belongs to the wrong branch")
    if artifact.head_sha != run.head_sha:
        raise EvidenceError("release artifact belongs to the wrong commit")


def select_attempt_artifact(
    payload: Mapping[str, Any],
    *,
    run: WorkflowRun,
    artifact_prefix: str,
) -> Artifact:
    """Select exactly one non-expired artifact for the eligible run attempt."""

    raw_artifacts = _require_single_page(payload, field="artifacts")
    expected_name = attempt_artifact_name(artifact_prefix, run.run_attempt)
    package_pattern = re.compile(rf"{re.escape(artifact_prefix)}-attempt-[1-9][0-9]*")
    package_candidates: list[Mapping[str, Any]] = []
    expected: list[Mapping[str, Any]] = []
    for raw in raw_artifacts:
        name = raw.get("name")
        if not isinstance(name, str):
            raise EvidenceError("GitHub artifact name must be a string")
        if package_pattern.fullmatch(name):
            package_candidates.append(raw)
        if name == expected_name:
            expected.append(raw)
    if len(expected) > 1:
        raise EvidenceError("multiple release artifacts match the eligible attempt")
    if not expected:
        if package_candidates:
            raise MissingEvidenceError(
                "only stale-attempt release artifacts are visible"
            )
        raise MissingEvidenceError("release artifact is not visible yet")
    artifact = Artifact.from_api(expected[0])
    _verify_artifact_against_run(artifact, run)
    return artifact


def _run_matches(
    run: WorkflowRun,
    requirement: WorkflowRequirement,
    *,
    repository: str,
    sha: str,
) -> bool:
    try:
        normalized_run_path = _normalized_workflow_path(run.path)
    except InvocationError as exc:
        raise EvidenceError(f"GitHub workflow path is invalid: {exc}") from None
    workflow_matches = (
        run.workflow_id == requirement.workflow_id
        if requirement.workflow_id is not None
        else normalized_run_path == requirement.workflow_file
    )
    repository_matches = repository.casefold()
    return (
        workflow_matches
        and run.event == "push"
        and run.head_sha == sha
        and run.head_branch in CANONICAL_BRANCHES
        and run.repository.casefold() == repository_matches
        and run.head_repository.casefold() == repository_matches
        and run.repository_id == run.head_repository_id
    )


def evaluate_required_workflows(
    payload: Mapping[str, Any],
    *,
    requirements: Sequence[WorkflowRequirement],
    repository: str,
    sha: str,
) -> WorkflowCheck:
    """Select the latest eligible attempt for each required workflow."""

    raw_runs = payload.get("workflow_runs")
    if not isinstance(raw_runs, list):
        raise EvidenceError("GitHub runs response must contain a workflow_runs list")
    if any(not isinstance(raw, Mapping) for raw in raw_runs):
        raise EvidenceError("GitHub workflow_runs entries must be objects")
    total_count = payload.get("total_count", len(raw_runs))
    if (
        not isinstance(total_count, int)
        or isinstance(total_count, bool)
        or total_count < len(raw_runs)
        or total_count > len(raw_runs)
    ):
        raise EvidenceError("GitHub runs response cannot be resolved in one page")

    runs = tuple(WorkflowRun.from_api(raw) for raw in raw_runs)
    passed: dict[str, WorkflowRun] = {}
    pending: dict[str, WorkflowRun] = {}
    failed: dict[str, WorkflowRun] = {}
    missing: list[str] = []
    for requirement in requirements:
        candidates = [
            run
            for run in runs
            if _run_matches(run, requirement, repository=repository, sha=sha)
        ]
        if not candidates:
            missing.append(requirement.key)
            continue
        latest = max(
            candidates,
            key=lambda run: (run.created_at, run.id, run.run_attempt),
        )
        if latest.status != "completed":
            pending[requirement.key] = latest
        elif latest.conclusion != "success":
            failed[requirement.key] = latest
        else:
            passed[requirement.key] = latest
    return WorkflowCheck(
        passed=passed,
        missing=tuple(missing),
        pending=pending,
        failed=failed,
    )


def _workflow_check_description(check: WorkflowCheck) -> str:
    parts: list[str] = []
    if check.passed:
        parts.append("green=" + ",".join(sorted(check.passed)))
    if check.pending:
        parts.append("pending=" + ",".join(sorted(check.pending)))
    if check.missing:
        parts.append("missing=" + ",".join(check.missing))
    if check.failed:
        parts.append("failed=" + ",".join(sorted(check.failed)))
    return " ".join(parts) if parts else "no workflow evidence"


def wait_for_required_workflows(
    *,
    fetch_runs: Callable[[], Mapping[str, Any]],
    requirements: Sequence[WorkflowRequirement],
    repository: str,
    sha: str,
    timeout_seconds: float = WORKFLOW_OBSERVATION_SECONDS,
    poll_seconds: float = WORKFLOW_POLL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> WorkflowCheck:
    """Observe one repository-wide run snapshot per bounded poll."""

    started = clock()
    deadline = started + timeout_seconds
    last_detail = "no workflow evidence"
    while True:
        retry_delay = poll_seconds
        try:
            payload = fetch_runs()
        except RateLimitError as exc:
            retry_delay = max(poll_seconds, exc.retry_after_seconds)
            last_detail = str(exc)
        except TransientAPIError as exc:
            last_detail = str(exc)
        else:
            check = evaluate_required_workflows(
                payload,
                requirements=requirements,
                repository=repository,
                sha=sha,
            )
            last_detail = _workflow_check_description(check)
            print(last_detail, flush=True)
            if check.failed:
                failed = ", ".join(
                    f"{key} [{run.conclusion or run.status}]"
                    for key, run in sorted(check.failed.items())
                )
                raise EvidenceError(
                    f"required workflow completed unsuccessfully: {failed}"
                )
            if check.ready:
                return check

        now = clock()
        if now >= deadline or now + retry_delay > deadline:
            raise EvidenceError(
                f"timed out waiting for exact-SHA workflow evidence: {last_detail}"
            )
        sleep(retry_delay)


def _repository_url(api_url: str, repository: str) -> str:
    encoded = urllib.parse.quote(repository, safe="/")
    return f"{api_url.rstrip('/')}/repos/{encoded}"


def fetch_workflow_runs_once(
    *,
    api_url: str,
    repository: str,
    sha: str,
    token: str,
) -> dict[str, Any]:
    """Fetch one repository-wide exact-SHA push-run snapshot."""

    query = urllib.parse.urlencode(
        {"head_sha": sha, "event": "push", "per_page": "100"}
    )
    url = f"{_repository_url(api_url, repository)}/actions/runs?{query}"
    return github_json_get(url, token=token)


def fetch_run_artifacts_once(
    *,
    api_url: str,
    repository: str,
    run_id: int,
    token: str,
) -> dict[str, Any]:
    """Fetch one page containing every artifact for an eligible run."""

    query = urllib.parse.urlencode({"per_page": "100"})
    url = (
        f"{_repository_url(api_url, repository)}/actions/runs/{run_id}/artifacts?"
        f"{query}"
    )
    return github_json_get(url, token=token)


def fetch_artifact_once(
    *,
    api_url: str,
    repository: str,
    artifact_id: int,
    token: str,
) -> dict[str, Any]:
    """Refetch one artifact by immutable id immediately before download."""

    url = f"{_repository_url(api_url, repository)}/actions/artifacts/{artifact_id}"
    return github_json_get(url, token=token)


def wait_for_attempt_artifact(
    *,
    fetch_artifacts: Callable[[], Mapping[str, Any]],
    run: WorkflowRun,
    artifact_prefix: str,
    timeout_seconds: float = ARTIFACT_VISIBILITY_SECONDS,
    poll_seconds: float = ARTIFACT_POLL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Artifact:
    """Wait at most two minutes for one attempt-qualified artifact."""

    deadline = clock() + timeout_seconds
    last_detail = "release artifact is not visible yet"
    while True:
        retry_delay = poll_seconds
        try:
            payload = fetch_artifacts()
            artifact = select_attempt_artifact(
                payload, run=run, artifact_prefix=artifact_prefix
            )
        except MissingEvidenceError as exc:
            last_detail = str(exc)
        except RateLimitError as exc:
            retry_delay = max(poll_seconds, exc.retry_after_seconds)
            last_detail = str(exc)
        except TransientAPIError as exc:
            last_detail = str(exc)
        else:
            return artifact

        now = clock()
        if now >= deadline or now + retry_delay > deadline:
            raise EvidenceError(
                f"timed out waiting for release artifact: {last_detail}"
            )
        sleep(retry_delay)


def _write_github_output(path: Path, values: Mapping[str, object]) -> None:
    lines = []
    for key, value in values.items():
        text = str(value)
        if "\n" in text or "\r" in text:
            raise EvidenceError(f"GitHub output {key!r} contains a newline")
        lines.append(f"{key}={text}")
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
    except OSError as exc:
        raise EvidenceError(
            f"cannot write GITHUB_OUTPUT: {_one_line(str(exc))}"
        ) from None


def verify_artifact_metadata(
    payload: Mapping[str, Any],
    *,
    artifact_id: int,
    artifact_digest: str,
    artifact_prefix: str,
    run_id: int,
    run_attempt: int,
    repository_id: int,
    head_repository_id: int,
    branch: str,
    sha: str,
) -> Artifact:
    """Recheck consumer-supplied artifact identity against fresh REST metadata."""

    artifact = Artifact.from_api(payload)
    if artifact.id != artifact_id:
        raise EvidenceError("refetched artifact id does not match the selected id")
    if artifact.digest != artifact_digest:
        raise EvidenceError(
            "refetched artifact digest does not match the selected digest"
        )
    if artifact.name != attempt_artifact_name(artifact_prefix, run_attempt):
        raise EvidenceError("refetched artifact belongs to the wrong run attempt")
    if artifact.expired:
        raise EvidenceError("refetched artifact is expired")
    if artifact.workflow_run_id != run_id:
        raise EvidenceError("refetched artifact belongs to the wrong workflow run")
    if artifact.repository_id != repository_id:
        raise EvidenceError("refetched artifact belongs to the wrong repository")
    if artifact.head_repository_id != head_repository_id:
        raise EvidenceError("refetched artifact belongs to the wrong head repository")
    if artifact.head_branch != branch:
        raise EvidenceError("refetched artifact belongs to the wrong branch")
    if artifact.head_sha != sha:
        raise EvidenceError("refetched artifact belongs to the wrong commit")
    return artifact


def build_parser() -> argparse.ArgumentParser:
    parser = GateArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    wait = subparsers.add_parser("wait")
    wait.add_argument("--workflow", action="append", required=True)
    wait.add_argument("--artifact-workflow", required=True)
    wait.add_argument("--artifact-prefix", required=True)
    verify = subparsers.add_parser("verify-artifact")
    verify.add_argument("--artifact-id", type=_positive_int, required=True)
    verify.add_argument("--artifact-digest", required=True)
    verify.add_argument("--artifact-prefix", required=True)
    verify.add_argument("--run-id", type=_positive_int, required=True)
    verify.add_argument("--run-attempt", type=_positive_int, required=True)
    verify.add_argument("--repository-id", type=_positive_int, required=True)
    verify.add_argument("--head-repository-id", type=_positive_int, required=True)
    verify.add_argument("--branch", choices=sorted(CANONICAL_BRANCHES), required=True)
    return parser


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise InvocationError(f"{name} is required")
    return value


def _validated_repository(value: str) -> str:
    if re.fullmatch(r"[^/\s]+/[^/\s]+", value) is None:
        raise InvocationError("GITHUB_REPOSITORY must use owner/name")
    return value


def _validated_sha(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise InvocationError("GITHUB_SHA must be an exact lowercase 40-character SHA")
    return value


def _parse_requirements(values: Sequence[str]) -> tuple[WorkflowRequirement, ...]:
    requirements = tuple(WorkflowRequirement.parse(value) for value in values)
    keys = [requirement.key for requirement in requirements]
    if len(keys) != len(set(keys)):
        raise InvocationError("workflow output keys must be unique")
    return requirements


def _run_wait(args: argparse.Namespace) -> None:
    token = _required_environment("GITHUB_TOKEN")
    repository = _validated_repository(_required_environment("GITHUB_REPOSITORY"))
    sha = _validated_sha(_required_environment("GITHUB_SHA"))
    output_path = Path(_required_environment("GITHUB_OUTPUT"))
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    requirements = _parse_requirements(args.workflow)
    requirement_keys = {requirement.key for requirement in requirements}
    if args.artifact_workflow != "root":
        raise InvocationError("--artifact-workflow must be the root workflow")
    if args.artifact_workflow not in requirement_keys:
        raise InvocationError("the root artifact workflow must be required")
    root_requirement = next(
        requirement for requirement in requirements if requirement.key == "root"
    )
    if root_requirement.workflow_file not in (
        None,
        ".github/workflows/test.yml",
    ):
        raise InvocationError(
            "the root workflow must resolve .github/workflows/test.yml or its id"
        )
    attempt_artifact_name(args.artifact_prefix, 1)

    observation_deadline = time.monotonic() + WORKFLOW_OBSERVATION_SECONDS
    check = wait_for_required_workflows(
        fetch_runs=lambda: fetch_workflow_runs_once(
            api_url=api_url,
            repository=repository,
            sha=sha,
            token=token,
        ),
        requirements=requirements,
        repository=repository,
        sha=sha,
        timeout_seconds=max(0.0, observation_deadline - time.monotonic()),
    )
    artifact_run = check.passed[args.artifact_workflow]
    remaining_seconds = observation_deadline - time.monotonic()
    if remaining_seconds <= 0:
        raise EvidenceError(
            "workflow evidence consumed the total 95-minute observation window"
        )
    artifact = wait_for_attempt_artifact(
        fetch_artifacts=lambda: fetch_run_artifacts_once(
            api_url=api_url,
            repository=repository,
            run_id=artifact_run.id,
            token=token,
        ),
        run=artifact_run,
        artifact_prefix=args.artifact_prefix,
        timeout_seconds=min(ARTIFACT_VISIBILITY_SECONDS, remaining_seconds),
    )
    outputs: dict[str, object] = {}
    for requirement in requirements:
        run = check.passed[requirement.key]
        outputs[f"{requirement.key}_run_id"] = run.id
        outputs[f"{requirement.key}_run_attempt"] = run.run_attempt
    outputs.update(
        {
            "artifact_id": artifact.id,
            "artifact_digest": artifact.digest,
            "artifact_run_id": artifact.workflow_run_id,
            "artifact_run_attempt": artifact_run.run_attempt,
            "artifact_repository_id": artifact.repository_id,
            "artifact_head_repository_id": artifact.head_repository_id,
            "artifact_head_branch": artifact.head_branch,
        }
    )
    _write_github_output(output_path, outputs)


def _run_verify_artifact(args: argparse.Namespace) -> None:
    token = _required_environment("GITHUB_TOKEN")
    repository = _validated_repository(_required_environment("GITHUB_REPOSITORY"))
    sha = _validated_sha(_required_environment("GITHUB_SHA"))
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", args.artifact_digest) is None:
        raise InvocationError("--artifact-digest must be sha256 hexadecimal")
    attempt_artifact_name(args.artifact_prefix, args.run_attempt)
    payload = fetch_artifact_once(
        api_url=api_url,
        repository=repository,
        artifact_id=args.artifact_id,
        token=token,
    )
    artifact = verify_artifact_metadata(
        payload,
        artifact_id=args.artifact_id,
        artifact_digest=args.artifact_digest,
        artifact_prefix=args.artifact_prefix,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        repository_id=args.repository_id,
        head_repository_id=args.head_repository_id,
        branch=args.branch,
        sha=sha,
    )
    print(
        f"verified immutable release artifact {artifact.id} ({artifact.digest})",
        flush=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.mode == "wait":
            _run_wait(args)
        elif args.mode == "verify-artifact":
            _run_verify_artifact(args)
        else:
            raise InvocationError(f"unsupported mode {args.mode!r}")
    except InvocationError as exc:
        print(
            f"workflow evidence gate failed: {_one_line(str(exc))}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(
            f"workflow evidence gate failed: {_one_line(str(exc))}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
