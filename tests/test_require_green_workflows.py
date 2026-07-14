from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import urllib.error
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "bin" / "require-green-workflows.py"

pytestmark = pytest.mark.sqlite_only

SHA = "a" * 40


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("require_green_workflows", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workflow_run(
    *,
    run_id: int = 101,
    workflow_id: int = 11,
    path: str = ".github/workflows/test.yml@refs/heads/main",
    event: str = "push",
    sha: str = SHA,
    branch: str = "main",
    status: str = "completed",
    conclusion: str | None = "success",
    run_attempt: int = 1,
    created_at: str = "2026-07-13T12:00:00Z",
    repository: str = "VanL/taut",
    head_repository: str = "VanL/taut",
    repository_id: int = 21,
    head_repository_id: int = 21,
) -> dict[str, Any]:
    return {
        "id": run_id,
        "workflow_id": workflow_id,
        "path": path,
        "event": event,
        "head_sha": sha,
        "head_branch": branch,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": run_attempt,
        "created_at": created_at,
        "html_url": f"https://example.test/runs/{run_id}",
        "repository": {"id": repository_id, "full_name": repository},
        "head_repository": {
            "id": head_repository_id,
            "full_name": head_repository,
        },
    }


def _artifact(
    *,
    artifact_id: int = 301,
    name: str = "taut-release-core-attempt-2",
    expired: bool = False,
    digest: str = "sha256:" + "b" * 64,
    run_id: int = 101,
    repository_id: int = 21,
    head_repository_id: int = 21,
    branch: str = "main",
    sha: str = SHA,
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "name": name,
        "expired": expired,
        "digest": digest,
        "workflow_run": {
            "id": run_id,
            "repository_id": repository_id,
            "head_repository_id": head_repository_id,
            "head_branch": branch,
            "head_sha": sha,
        },
    }


def _http_error(code: int, headers: dict[str, str] | None = None) -> Exception:
    message = Message()
    for name, value in (headers or {}).items():
        message[name] = value
    return urllib.error.HTTPError(
        "https://api.example.test/resource",
        code,
        "failure",
        message,
        io.BytesIO(b'{"message":"failure"}'),
    )


def _raise(error: Exception) -> Any:
    raise error


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_wait_requires_github_environment_without_traceback() -> None:
    env = os.environ.copy()
    for name in (
        "GITHUB_TOKEN",
        "GITHUB_REPOSITORY",
        "GITHUB_SHA",
        "GITHUB_OUTPUT",
    ):
        env.pop(name, None)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "wait",
            "--workflow",
            "root=.github/workflows/test.yml",
            "--artifact-workflow",
            "root",
            "--artifact-prefix",
            "taut-release-core",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )

    assert completed.returncode == 2
    assert "GITHUB_TOKEN" in completed.stderr
    assert len(completed.stderr.splitlines()) == 1
    assert "Traceback" not in completed.stderr


def test_workflow_selection_normalizes_path_ref_and_uses_latest_attempt() -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=.github/workflows/test.yml")
    payload = {
        "total_count": 2,
        "workflow_runs": [
            _workflow_run(run_attempt=1, conclusion="failure"),
            _workflow_run(run_attempt=2, conclusion="success"),
        ],
    }

    check = gate.evaluate_required_workflows(
        payload,
        requirements=(requirement,),
        repository="VanL/taut",
        sha=SHA,
    )

    assert check.ready
    assert check.passed["root"].id == 101
    assert check.passed["root"].run_attempt == 2


@pytest.mark.parametrize(
    "override",
    [
        {"path": ".github/workflows/other.yml@main"},
        {"event": "workflow_call"},
        {"sha": "b" * 40},
        {"branch": "topic"},
        {"repository": "VanL/other"},
        {"head_repository": "fork/taut"},
        {"head_repository_id": 22},
    ],
)
def test_workflow_selection_rejects_wrong_identity(
    override: dict[str, Any],
) -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=.github/workflows/test.yml")

    check = gate.evaluate_required_workflows(
        {"total_count": 1, "workflow_runs": [_workflow_run(**override)]},
        requirements=(requirement,),
        repository="VanL/taut",
        sha=SHA,
    )

    assert not check.ready
    assert check.missing == ("root",)


def test_workflow_selection_accepts_numeric_workflow_id() -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=11")

    check = gate.evaluate_required_workflows(
        {"total_count": 1, "workflow_runs": [_workflow_run()]},
        requirements=(requirement,),
        repository="VanL/taut",
        sha=SHA,
    )

    assert check.ready


def test_workflow_selection_accepts_master_as_canonical_branch() -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=11")

    check = gate.evaluate_required_workflows(
        {
            "total_count": 1,
            "workflow_runs": [
                _workflow_run(
                    branch="master",
                    path=".github/workflows/test.yml@refs/heads/master",
                )
            ],
        },
        requirements=(requirement,),
        repository="VanL/taut",
        sha=SHA,
    )

    assert check.ready


def test_workflow_selection_never_borrows_older_green_attempt() -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=.github/workflows/test.yml")

    check = gate.evaluate_required_workflows(
        {
            "total_count": 2,
            "workflow_runs": [
                _workflow_run(run_attempt=1, conclusion="success"),
                _workflow_run(run_attempt=2, conclusion="cancelled"),
            ],
        },
        requirements=(requirement,),
        repository="VanL/taut",
        sha=SHA,
    )

    assert not check.ready
    assert check.failed["root"].run_attempt == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"workflow_runs": {}},
        {"total_count": 1, "workflow_runs": [None]},
        {"total_count": 2, "workflow_runs": [_workflow_run()]},
    ],
)
def test_workflow_selection_rejects_degenerate_structured_input(
    payload: dict[str, Any],
) -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=.github/workflows/test.yml")

    with pytest.raises(gate.EvidenceError):
        gate.evaluate_required_workflows(
            payload,
            requirements=(requirement,),
            repository="VanL/taut",
            sha=SHA,
        )


def test_attempt_artifact_selection_binds_immutable_identity() -> None:
    gate = _load_gate()
    run = gate.WorkflowRun.from_api(_workflow_run(run_attempt=2))

    artifact = gate.select_attempt_artifact(
        {"total_count": 1, "artifacts": [_artifact()]},
        run=run,
        artifact_prefix="taut-release-core",
    )

    assert artifact.id == 301
    assert artifact.digest == "sha256:" + "b" * 64
    assert artifact.workflow_run_id == 101
    assert artifact.name == "taut-release-core-attempt-2"


@pytest.mark.parametrize(
    ("artifacts", "message"),
    [
        ([_artifact(), _artifact(artifact_id=302)], "multiple"),
        ([_artifact(expired=True)], "expired"),
        ([_artifact(run_id=999)], "workflow run"),
        ([_artifact(repository_id=999)], "wrong repository"),
        ([_artifact(head_repository_id=999)], "head repository"),
        ([_artifact(branch="topic")], "wrong branch"),
        ([_artifact(sha="c" * 40)], "wrong commit"),
    ],
)
def test_attempt_artifact_selection_rejects_ambiguous_or_wrong_identity(
    artifacts: list[dict[str, Any]], message: str
) -> None:
    gate = _load_gate()
    run = gate.WorkflowRun.from_api(_workflow_run(run_attempt=2))

    with pytest.raises(gate.EvidenceError, match=message):
        gate.select_attempt_artifact(
            {"total_count": len(artifacts), "artifacts": artifacts},
            run=run,
            artifact_prefix="taut-release-core",
        )


def test_attempt_artifact_selection_classifies_absence_as_pollable() -> None:
    gate = _load_gate()
    run = gate.WorkflowRun.from_api(_workflow_run(run_attempt=2))

    with pytest.raises(gate.MissingEvidenceError, match="not visible"):
        gate.select_attempt_artifact(
            {"total_count": 0, "artifacts": []},
            run=run,
            artifact_prefix="taut-release-core",
        )


def test_attempt_artifact_selection_classifies_stale_attempt_as_pollable() -> None:
    gate = _load_gate()
    run = gate.WorkflowRun.from_api(_workflow_run(run_attempt=2))

    with pytest.raises(gate.MissingEvidenceError, match="stale-attempt"):
        gate.select_attempt_artifact(
            {
                "total_count": 1,
                "artifacts": [_artifact(name="taut-release-core-attempt-1")],
            },
            run=run,
            artifact_prefix="taut-release-core",
        )


@pytest.mark.parametrize(
    ("code", "headers"),
    [
        (401, {}),
        (
            403,
            {"X-RateLimit-Remaining": "10", "X-RateLimit-Reset": "112"},
        ),
    ],
)
def test_github_api_auth_failures_are_immediate(
    code: int, headers: dict[str, str]
) -> None:
    gate = _load_gate()

    with pytest.raises(gate.EvidenceError, match=str(code)) as caught:
        gate.github_json_get(
            "https://api.example.test/resource",
            token="secret",
            opener=lambda *_args, **_kwargs: _raise(_http_error(code, headers)),
        )

    assert not isinstance(caught.value, gate.TransientAPIError)
    assert not isinstance(caught.value, gate.RateLimitError)


@pytest.mark.parametrize(
    ("code", "headers", "expected_delay"),
    [
        (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "112"}, 12),
        (429, {"Retry-After": "17"}, 17),
    ],
)
def test_github_api_rate_limits_preserve_server_delay(
    code: int, headers: dict[str, str], expected_delay: int
) -> None:
    gate = _load_gate()

    with pytest.raises(gate.RateLimitError) as caught:
        gate.github_json_get(
            "https://api.example.test/resource",
            token="secret",
            opener=lambda *_args, **_kwargs: _raise(_http_error(code, headers)),
            wall_clock=lambda: 100.0,
        )

    assert caught.value.retry_after_seconds == expected_delay


def test_github_api_5xx_is_bounded_transient() -> None:
    gate = _load_gate()

    with pytest.raises(gate.TransientAPIError, match="503"):
        gate.github_json_get(
            "https://api.example.test/resource",
            token="secret",
            opener=lambda *_args, **_kwargs: _raise(_http_error(503)),
        )


@pytest.mark.parametrize("body", [b"{", json.dumps([]).encode("utf-8")])
def test_github_api_malformed_json_is_immediate(body: bytes) -> None:
    gate = _load_gate()

    with pytest.raises(gate.EvidenceError, match="JSON object"):
        gate.github_json_get(
            "https://api.example.test/resource",
            token="secret",
            opener=lambda *_args, **_kwargs: io.BytesIO(body),
        )


def test_workflow_wait_polls_one_snapshot_every_sixty_seconds() -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=.github/workflows/test.yml")
    clock = _Clock()
    calls = 0

    def fetch() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls < 3:
            return {"total_count": 0, "workflow_runs": []}
        return {"total_count": 1, "workflow_runs": [_workflow_run()]}

    check = gate.wait_for_required_workflows(
        fetch_runs=fetch,
        requirements=(requirement,),
        repository="VanL/taut",
        sha=SHA,
        clock=clock.monotonic,
        sleep=clock.sleep,
    )

    assert check.ready
    assert calls == 3
    assert clock.sleeps == [60.0, 60.0]
    assert gate.WORKFLOW_OBSERVATION_SECONDS == 95 * 60
    assert gate.WORKFLOW_POLL_SECONDS == 60


def test_workflow_wait_fails_completed_non_success_immediately() -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=.github/workflows/test.yml")
    clock = _Clock()
    calls = 0

    def fetch() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "total_count": 1,
            "workflow_runs": [_workflow_run(conclusion="failure")],
        }

    with pytest.raises(gate.EvidenceError, match="unsuccessfully"):
        gate.wait_for_required_workflows(
            fetch_runs=fetch,
            requirements=(requirement,),
            repository="VanL/taut",
            sha=SHA,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )

    assert calls == 1
    assert clock.sleeps == []


@pytest.mark.parametrize("failure", ["missing", "5xx"])
def test_workflow_wait_bounds_missing_and_transient_5xx(failure: str) -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=.github/workflows/test.yml")
    clock = _Clock()
    calls = 0

    def fetch() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if failure == "5xx":
            raise gate.TransientAPIError("GitHub API returned HTTP 503")
        return {"total_count": 0, "workflow_runs": []}

    with pytest.raises(gate.EvidenceError, match="timed out"):
        gate.wait_for_required_workflows(
            fetch_runs=fetch,
            requirements=(requirement,),
            repository="VanL/taut",
            sha=SHA,
            timeout_seconds=120,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )

    assert calls == 3
    assert clock.sleeps == [60.0, 60.0]


@pytest.mark.parametrize(
    ("server_delay", "expected_sleep"),
    [(17, 60.0), (75, 75)],
)
def test_workflow_wait_honors_rate_limit_without_overpolling(
    server_delay: int, expected_sleep: float
) -> None:
    gate = _load_gate()
    requirement = gate.WorkflowRequirement.parse("root=.github/workflows/test.yml")
    clock = _Clock()
    calls = 0

    def fetch() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise gate.RateLimitError("rate limited", retry_after_seconds=server_delay)
        return {"total_count": 1, "workflow_runs": [_workflow_run()]}

    check = gate.wait_for_required_workflows(
        fetch_runs=fetch,
        requirements=(requirement,),
        repository="VanL/taut",
        sha=SHA,
        clock=clock.monotonic,
        sleep=clock.sleep,
    )

    assert check.ready
    assert calls == 2
    assert clock.sleeps == [expected_sleep]


def test_wait_exports_verified_workflow_and_artifact_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _load_gate()
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "VanL/taut")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    urls: list[str] = []

    def get_json(url: str, **_kwargs: Any) -> dict[str, Any]:
        urls.append(url)
        if "/actions/runs?" in url:
            return {
                "total_count": 2,
                "workflow_runs": [
                    _workflow_run(run_attempt=2),
                    _workflow_run(
                        run_id=202,
                        workflow_id=12,
                        path=(
                            ".github/workflows/test-pg-extension.yml@refs/heads/main"
                        ),
                    ),
                ],
            }
        if "/actions/runs/101/artifacts?" in url:
            return {"total_count": 1, "artifacts": [_artifact()]}
        pytest.fail(f"unexpected GitHub URL: {url}")

    monkeypatch.setattr(gate, "github_json_get", get_json)

    result = gate.main(
        [
            "wait",
            "--workflow",
            "root=.github/workflows/test.yml",
            "--workflow",
            "pg=.github/workflows/test-pg-extension.yml",
            "--artifact-workflow",
            "root",
            "--artifact-prefix",
            "taut-release-core",
        ]
    )

    assert result == 0
    assert len([url for url in urls if "/actions/runs?" in url]) == 1
    assert "head_sha=" + SHA in urls[0]
    assert "event=push" in urls[0]
    assert set(output.read_text(encoding="utf-8").splitlines()) == {
        "root_run_id=101",
        "root_run_attempt=2",
        "pg_run_id=202",
        "pg_run_attempt=1",
        "artifact_id=301",
        "artifact_digest=sha256:" + "b" * 64,
        "artifact_run_id=101",
        "artifact_run_attempt=2",
        "artifact_repository_id=21",
        "artifact_head_repository_id=21",
        "artifact_head_branch=main",
    }


def test_wait_requires_artifact_to_come_from_root_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = _load_gate()
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "VanL/taut")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setattr(
        gate,
        "wait_for_required_workflows",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("root ownership must fail before polling")
        ),
    )

    result = gate.main(
        [
            "wait",
            "--workflow",
            "root=.github/workflows/test.yml",
            "--workflow",
            "pg=.github/workflows/test-pg-extension.yml",
            "--artifact-workflow",
            "pg",
            "--artifact-prefix",
            "taut-release-core",
        ]
    )

    stderr = capsys.readouterr().err
    assert result == 2
    assert "root" in stderr


def test_verify_artifact_mode_refetches_and_rechecks_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _load_gate()
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "VanL/taut")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    urls: list[str] = []

    def get_json(url: str, **_kwargs: Any) -> dict[str, Any]:
        urls.append(url)
        return _artifact()

    monkeypatch.setattr(gate, "github_json_get", get_json)

    result = gate.main(
        [
            "verify-artifact",
            "--artifact-id",
            "301",
            "--artifact-digest",
            "sha256:" + "b" * 64,
            "--artifact-prefix",
            "taut-release-core",
            "--run-id",
            "101",
            "--run-attempt",
            "2",
            "--repository-id",
            "21",
            "--head-repository-id",
            "21",
            "--branch",
            "main",
        ]
    )

    assert result == 0
    assert len(urls) == 1
    assert urls[0].endswith("/repos/VanL/taut/actions/artifacts/301")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"artifact_id": 302}, "artifact id"),
        ({"artifact_digest": "sha256:" + "c" * 64}, "digest"),
        ({"run_attempt": 3}, "run attempt"),
        ({"run_id": 999}, "workflow run"),
        ({"repository_id": 999}, "wrong repository"),
        ({"head_repository_id": 999}, "head repository"),
        ({"branch": "master"}, "wrong branch"),
        ({"sha": "c" * 40}, "wrong commit"),
    ],
)
def test_verify_artifact_metadata_fails_closed_on_changed_evidence(
    override: dict[str, Any], message: str
) -> None:
    gate = _load_gate()
    expected = {
        "artifact_id": 301,
        "artifact_digest": "sha256:" + "b" * 64,
        "artifact_prefix": "taut-release-core",
        "run_id": 101,
        "run_attempt": 2,
        "repository_id": 21,
        "head_repository_id": 21,
        "branch": "main",
        "sha": SHA,
    }
    expected.update(override)

    with pytest.raises(gate.EvidenceError, match=message):
        gate.verify_artifact_metadata(_artifact(), **expected)


def test_artifact_visibility_wait_is_bounded_to_two_minutes() -> None:
    gate = _load_gate()
    run = gate.WorkflowRun.from_api(_workflow_run(run_attempt=2))
    clock = _Clock()
    calls = 0

    def fetch() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"total_count": 0, "artifacts": []}

    with pytest.raises(gate.EvidenceError, match="timed out"):
        gate.wait_for_attempt_artifact(
            fetch_artifacts=fetch,
            run=run,
            artifact_prefix="taut-release-core",
            clock=clock.monotonic,
            sleep=clock.sleep,
        )

    assert gate.ARTIFACT_VISIBILITY_SECONDS == 120
    assert calls == 13
    assert clock.sleeps == [10.0] * 12


def test_artifact_visibility_wait_accepts_current_attempt_after_stale_listing() -> None:
    gate = _load_gate()
    run = gate.WorkflowRun.from_api(_workflow_run(run_attempt=2))
    clock = _Clock()
    calls = 0

    def fetch() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        name = (
            "taut-release-core-attempt-1"
            if calls < 3
            else "taut-release-core-attempt-2"
        )
        return {"total_count": 1, "artifacts": [_artifact(name=name)]}

    artifact = gate.wait_for_attempt_artifact(
        fetch_artifacts=fetch,
        run=run,
        artifact_prefix="taut-release-core",
        clock=clock.monotonic,
        sleep=clock.sleep,
    )

    assert artifact.name == "taut-release-core-attempt-2"
    assert calls == 3
    assert clock.sleeps == [10.0, 10.0]


def test_stale_attempt_only_times_out_after_visibility_window() -> None:
    gate = _load_gate()
    run = gate.WorkflowRun.from_api(_workflow_run(run_attempt=2))
    clock = _Clock()

    def fetch() -> dict[str, Any]:
        return {
            "total_count": 1,
            "artifacts": [_artifact(name="taut-release-core-attempt-1")],
        }

    with pytest.raises(gate.EvidenceError, match="stale-attempt"):
        gate.wait_for_attempt_artifact(
            fetch_artifacts=fetch,
            run=run,
            artifact_prefix="taut-release-core",
            clock=clock.monotonic,
            sleep=clock.sleep,
        )

    assert clock.sleeps == [10.0] * 12


def test_wait_keeps_artifact_visibility_inside_total_ninety_five_minutes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _load_gate()
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "VanL/taut")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    now = [0.0]
    run = gate.WorkflowRun.from_api(_workflow_run(run_attempt=2))
    check = gate.WorkflowCheck(passed={"root": run}, missing=(), pending={}, failed={})
    artifact = gate.Artifact.from_api(_artifact())

    def workflow_wait(**_kwargs: Any) -> Any:
        now[0] = 95 * 60 - 10
        return check

    def artifact_wait(*, timeout_seconds: float, **_kwargs: Any) -> Any:
        assert timeout_seconds == 10
        return artifact

    monkeypatch.setattr(gate.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(gate, "wait_for_required_workflows", workflow_wait)
    monkeypatch.setattr(gate, "wait_for_attempt_artifact", artifact_wait)

    result = gate.main(
        [
            "wait",
            "--workflow",
            "root=.github/workflows/test.yml",
            "--artifact-workflow",
            "root",
            "--artifact-prefix",
            "taut-release-core",
        ]
    )

    assert result == 0


def test_wait_fails_when_workflow_consumes_total_ninety_five_minutes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = _load_gate()
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "VanL/taut")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    now = [0.0]
    run = gate.WorkflowRun.from_api(_workflow_run(run_attempt=2))
    check = gate.WorkflowCheck(passed={"root": run}, missing=(), pending={}, failed={})

    def workflow_wait(**_kwargs: Any) -> Any:
        now[0] = 95 * 60
        return check

    monkeypatch.setattr(gate.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(gate, "wait_for_required_workflows", workflow_wait)
    monkeypatch.setattr(
        gate,
        "wait_for_attempt_artifact",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("artifact polling must stay inside the total window")
        ),
    )

    result = gate.main(
        [
            "wait",
            "--workflow",
            "root=.github/workflows/test.yml",
            "--artifact-workflow",
            "root",
            "--artifact-prefix",
            "taut-release-core",
        ]
    )

    stderr = capsys.readouterr().err
    assert result == 1
    assert "total 95-minute observation window" in stderr
    assert "Traceback" not in stderr


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("401", "401"),
        ("403", "403"),
        ("rate-403", "rate limited"),
        ("429", "rate limited"),
        ("503", "503"),
        ("malformed", "JSON object"),
    ],
)
def test_wait_cli_api_failures_are_concise_and_nonzero(
    scenario: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = _load_gate()
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "VanL/taut")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    original_get = gate.github_json_get
    original_wait = gate.wait_for_required_workflows

    def failing_get(url: str, **kwargs: Any) -> dict[str, Any]:
        def opener(*_args: Any, **_kwargs: Any) -> Any:
            if scenario == "malformed":
                return io.BytesIO(b"{")
            headers = None
            code = int(scenario.removeprefix("rate-"))
            if scenario == "rate-403":
                headers = {
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": "112",
                }
            if scenario == "429":
                headers = {"Retry-After": "17"}
            return _raise(_http_error(code, headers))

        return cast(
            dict[str, Any],
            original_get(
                url,
                token=kwargs["token"],
                opener=opener,
                wall_clock=lambda: 100.0,
            ),
        )

    def short_wait(**kwargs: Any) -> Any:
        kwargs["timeout_seconds"] = 0
        return original_wait(**kwargs)

    monkeypatch.setattr(gate, "github_json_get", failing_get)
    monkeypatch.setattr(gate, "wait_for_required_workflows", short_wait)

    result = gate.main(
        [
            "wait",
            "--workflow",
            "root=.github/workflows/test.yml",
            "--artifact-workflow",
            "root",
            "--artifact-prefix",
            "taut-release-core",
        ]
    )

    stderr = capsys.readouterr().err
    assert result == 1
    assert expected in stderr
    assert len(stderr.splitlines()) == 1
    assert "Traceback" not in stderr


def test_cli_contains_unexpected_multiline_error_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = _load_gate()
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "VanL/taut")
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    def fail(**_kwargs: Any) -> Any:
        raise RuntimeError("first line\nsecond line")

    monkeypatch.setattr(gate, "wait_for_required_workflows", fail)

    result = gate.main(
        [
            "wait",
            "--workflow",
            "root=.github/workflows/test.yml",
            "--artifact-workflow",
            "root",
            "--artifact-prefix",
            "taut-release-core",
        ]
    )

    stderr = capsys.readouterr().err
    assert result == 1
    assert "first line second line" in stderr
    assert len(stderr.splitlines()) == 1
    assert "Traceback" not in stderr
