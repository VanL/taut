from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import urllib.error
from email.message import Message
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.sqlite_only


def _load_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "scripts"
        / "release_publication.py"
    )
    spec = importlib.util.spec_from_file_location("taut_release_publication", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


publication = _load_module()


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")


def _release_files(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "taut_chat-1.2.3-py3-none-any.whl"
    sdist = dist / "taut_chat-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    digests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (wheel, sdist)
    }
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "format": 1,
                "commit": "a" * 40,
                "package": {"name": "taut-chat", "version": "1.2.3"},
                "files": [
                    {"name": name, "sha256": digest}
                    for name, digest in sorted(digests.items())
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest, dist, digests


def _pypi_payload(
    digests: dict[str, str],
    *,
    names: tuple[str, ...] | None = None,
) -> dict[str, object]:
    selected = tuple(digests) if names is None else names
    return {
        "info": {"name": "Taut.Chat", "version": "1.2.3"},
        "urls": [
            {
                "filename": name,
                "digests": {"sha256": digests[name]},
            }
            for name in selected
        ],
    }


def _release(
    digests: dict[str, str],
    *,
    draft: bool = True,
    immutable: bool = False,
    mutate: str | None = None,
) -> dict[str, object]:
    assets = [
        {
            "name": name,
            "state": "uploaded",
            "digest": f"sha256:{digest}",
        }
        for name, digest in sorted(digests.items())
    ]
    if mutate == "extra":
        assets.append(
            {"name": "extra.whl", "state": "uploaded", "digest": f"sha256:{'0' * 64}"}
        )
    elif mutate == "digest":
        assets[0]["digest"] = f"sha256:{'0' * 64}"
    elif mutate == "incomplete":
        assets[0]["state"] = "new"
    elif mutate == "pending-digest":
        assets[0].pop("digest")
    elif mutate == "invalid-digest":
        assets[0]["digest"] = "sha256:not-a-digest"
    return {
        "id": 17,
        "tag_name": "v1.2.3",
        "draft": draft,
        "immutable": immutable,
        "assets": assets,
    }


def test_publication_manifest_binds_exact_local_files(tmp_path: Path) -> None:
    manifest, dist, digests = _release_files(tmp_path)

    expected = publication.read_publication(manifest, dist)

    assert expected.package == "taut-chat"
    assert expected.version == "1.2.3"
    assert expected.files == digests

    (dist / next(iter(digests))).write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="digest"):
        publication.read_publication(manifest, dist)


@pytest.mark.parametrize(
    "mutation",
    (
        "extra-file",
        "missing-file",
        "traversal",
        "windows-traversal",
        "duplicate",
        "bad-digest",
    ),
)
def test_publication_manifest_fails_closed_for_adversarial_allowlists(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    value = json.loads(manifest.read_text("utf-8"))
    if mutation == "extra-file":
        (dist / "unexpected.txt").write_text("extra", encoding="utf-8")
    elif mutation == "missing-file":
        (dist / next(iter(digests))).unlink()
    elif mutation == "traversal":
        value["files"][0]["name"] = "../escape.whl"
        manifest.write_text(json.dumps(value), encoding="utf-8")
    elif mutation == "windows-traversal":
        value["files"][0]["name"] = r"..\escape.whl"
        manifest.write_text(json.dumps(value), encoding="utf-8")
    elif mutation == "duplicate":
        value["files"][1] = value["files"][0]
        manifest.write_text(json.dumps(value), encoding="utf-8")
    else:
        value["files"][0]["sha256"] = "bad"
        manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(RuntimeError):
        publication.read_publication(manifest, dist)


@pytest.mark.parametrize(
    ("existing_names", "expected_state", "publish", "skip_existing"),
    (
        (None, "absent", True, False),
        (("taut_chat-1.2.3-py3-none-any.whl",), "partial", True, True),
        (
            (
                "taut_chat-1.2.3-py3-none-any.whl",
                "taut_chat-1.2.3.tar.gz",
            ),
            "complete",
            False,
            False,
        ),
    ),
)
def test_pypi_plan_distinguishes_absent_partial_and_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_names: tuple[str, ...] | None,
    expected_state: str,
    publish: bool,
    skip_existing: bool,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    existing = (
        None
        if existing_names is None
        else {name: digests[name] for name in existing_names}
    )
    monkeypatch.setattr(
        publication,
        "pypi_release_files",
        lambda package, version: existing,
    )

    plan = publication.plan_pypi(expected)

    assert plan.state == expected_state
    assert plan.publish is publish
    assert plan.skip_existing is skip_existing


@pytest.mark.parametrize("mutation", ("extra", "digest", "empty"))
def test_pypi_plan_rejects_unproven_existing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    existing = dict(digests)
    if mutation == "extra":
        existing["unexpected.whl"] = "0" * 64
    elif mutation == "digest":
        existing[next(iter(existing))] = "0" * 64
    else:
        existing = {}
    monkeypatch.setattr(
        publication,
        "pypi_release_files",
        lambda package, version: existing,
    )

    with pytest.raises(RuntimeError, match="PyPI"):
        publication.plan_pypi(expected)


def test_pypi_http_contract_treats_only_404_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*args: object, **kwargs: object) -> object:
        raise urllib.error.HTTPError("url", 404, "not found", Message(), None)

    monkeypatch.setattr(publication.urllib.request, "urlopen", missing)
    assert publication.pypi_release_files("taut-chat", "1.2.3") is None

    def forbidden(*args: object, **kwargs: object) -> object:
        raise urllib.error.HTTPError("url", 403, "forbidden", Message(), None)

    monkeypatch.setattr(publication.urllib.request, "urlopen", forbidden)
    with pytest.raises(RuntimeError, match="HTTP 403"):
        publication.pypi_release_files("taut-chat", "1.2.3")


def test_pypi_http_contract_parses_normalized_identity_and_exact_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, digests = _release_files(tmp_path)
    monkeypatch.setattr(
        publication.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Response(_pypi_payload(digests)),
    )

    assert publication.pypi_release_files("taut-chat", "1.2.3") == digests


@pytest.mark.parametrize(
    "payload",
    (
        b"{",
        {"info": {"name": "other", "version": "1.2.3"}, "urls": []},
        {"info": {"name": "taut-chat", "version": "9.9.9"}, "urls": []},
        {"info": {"name": "taut-chat", "version": "1.2.3"}, "urls": "wrong"},
    ),
)
def test_pypi_http_contract_rejects_malformed_or_wrong_identity(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    monkeypatch.setattr(
        publication.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Response(payload),
    )

    with pytest.raises(RuntimeError):
        publication.pypi_release_files("taut-chat", "1.2.3")


def test_pypi_network_failure_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("unavailable")

    monkeypatch.setattr(publication.urllib.request, "urlopen", unavailable)

    with pytest.raises(RuntimeError, match="unavailable"):
        publication.pypi_release_files("taut-chat", "1.2.3")


def test_verify_pypi_retries_only_matching_incomplete_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    states = iter(
        (
            None,
            {next(iter(digests)): digests[next(iter(digests))]},
            dict(digests),
        )
    )
    sleeps: list[float] = []
    monkeypatch.setattr(
        publication,
        "pypi_release_files",
        lambda package, version: next(states),
    )
    monkeypatch.setattr(publication.time, "sleep", sleeps.append)

    publication.verify_pypi(expected, retry_delays=(1, 2))

    assert sleeps == [1, 2]


def test_stage_draft_replaces_only_a_draft_and_reports_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    calls: list[tuple[str, str, object]] = []
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)
    monkeypatch.setattr(
        publication,
        "list_releases",
        lambda repo: (_release(digests),),
    )
    monkeypatch.setattr(
        publication,
        "github_api_request",
        lambda method, path, body=None: calls.append((method, path, body)),
    )

    assert publication.stage_draft(
        repo="VanL/taut",
        tag="v1.2.3",
        expected_sha="a" * 40,
        expected=expected,
    )
    assert calls == [("DELETE", "/repos/VanL/taut/releases/17", None)]


def test_stage_draft_accepts_only_an_exact_immutable_public_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)
    monkeypatch.setattr(
        publication,
        "list_releases",
        lambda repo: (_release(digests, draft=False, immutable=True),),
    )
    monkeypatch.setattr(
        publication,
        "pypi_release_files",
        lambda package, version: dict(digests),
    )

    assert not publication.stage_draft(
        repo="VanL/taut",
        tag="v1.2.3",
        expected_sha="a" * 40,
        expected=expected,
    )

    for release in (
        _release(digests, draft=False, immutable=False),
        _release(digests, draft=False, immutable=True, mutate="extra"),
        _release(digests, draft=False, immutable=True, mutate="digest"),
        _release(digests, draft=False, immutable=True, mutate="incomplete"),
        _release(digests, draft=False, immutable=True, mutate="pending-digest"),
        _release(digests, draft=False, immutable=True, mutate="invalid-digest"),
    ):
        monkeypatch.setattr(publication, "list_releases", lambda repo, r=release: (r,))
        with pytest.raises(RuntimeError):
            publication.stage_draft(
                repo="VanL/taut",
                tag="v1.2.3",
                expected_sha="a" * 40,
                expected=expected,
            )


@pytest.mark.parametrize(
    "pypi_state",
    ("absent", "partial"),
)
def test_stage_draft_never_backfills_pypi_after_github_is_public(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pypi_state: str,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)
    monkeypatch.setattr(
        publication,
        "list_releases",
        lambda repo: (_release(digests, draft=False, immutable=True),),
    )
    monkeypatch.setattr(
        publication,
        "pypi_release_files",
        lambda package, version: (
            None
            if pypi_state == "absent"
            else {filename: digests[filename] for filename in tuple(digests)[:1]}
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="cannot be used to create or complete a PyPI release",
    ):
        publication.stage_draft(
            repo="VanL/taut",
            tag="v1.2.3",
            expected_sha="a" * 40,
            expected=expected,
        )


def test_finalize_checks_pypi_and_exact_assets_before_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    calls: list[tuple[str, str, object]] = []
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)
    monkeypatch.setattr(
        publication,
        "list_releases",
        lambda repo: (_release(digests),),
    )

    def verify_pypi(
        observed: object,
        *,
        retry_delays: tuple[float, ...],
    ) -> None:
        calls.append(("VERIFY", "pypi", (observed, retry_delays)))

    monkeypatch.setattr(publication, "verify_pypi", verify_pypi)

    def request(method: str, path: str, body: object = None) -> object:
        calls.append((method, path, body))
        return _release(digests, draft=False, immutable=True)

    monkeypatch.setattr(publication, "github_api_request", request)

    publication.finalize_release(
        repo="VanL/taut",
        tag="v1.2.3",
        expected_sha="a" * 40,
        expected=expected,
    )

    assert calls == [
        ("VERIFY", "pypi", (expected, ())),
        (
            "PATCH",
            "/repos/VanL/taut/releases/17",
            {"draft": False},
        ),
    ]


def test_finalize_retries_pending_github_asset_digest_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    sleeps: list[float] = []
    api_calls: list[tuple[str, str, object]] = []
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)
    monkeypatch.setattr(
        publication,
        "list_releases",
        lambda repo: (_release(digests, mutate="pending-digest"),),
    )
    monkeypatch.setattr(
        publication,
        "verify_pypi",
        lambda observed, **kwargs: None,
    )
    monkeypatch.setattr(publication.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        publication,
        "GITHUB_ASSET_RETRY_DELAYS",
        (1,),
        raising=False,
    )

    def request(method: str, path: str, body: object = None) -> object:
        api_calls.append((method, path, body))
        if method == "GET":
            return [_release(digests)]
        return _release(digests, draft=False, immutable=True)

    monkeypatch.setattr(publication, "github_api_request", request)

    publication.finalize_release(
        repo="VanL/taut",
        tag="v1.2.3",
        expected_sha="a" * 40,
        expected=expected,
    )

    assert sleeps == [1]
    assert api_calls == [
        ("GET", "/repos/VanL/taut/releases?per_page=100&page=1", None),
        ("PATCH", "/repos/VanL/taut/releases/17", {"draft": False}),
    ]


def test_finalize_bounds_pending_github_asset_digest_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    sleeps: list[float] = []
    pending = _release(digests, mutate="pending-digest")
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)
    monkeypatch.setattr(publication, "list_releases", lambda repo: (pending,))
    monkeypatch.setattr(
        publication,
        "github_api_request",
        lambda method, path, body=None: [pending],
    )
    monkeypatch.setattr(publication.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        publication,
        "GITHUB_ASSET_RETRY_DELAYS",
        (1, 2),
        raising=False,
    )
    monkeypatch.setattr(
        publication,
        "verify_pypi",
        lambda observed: pytest.fail("PyPI must wait for exact GitHub assets"),
    )

    with pytest.raises(RuntimeError, match="did not expose the complete exact asset"):
        publication.finalize_release(
            repo="VanL/taut",
            tag="v1.2.3",
            expected_sha="a" * 40,
            expected=expected,
        )

    assert sleeps == [1, 2]


def test_finalize_public_immutable_inconsistency_does_not_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)
    monkeypatch.setattr(
        publication,
        "list_releases",
        lambda repo: (
            _release(
                digests,
                draft=False,
                immutable=True,
                mutate="pending-digest",
            ),
        ),
    )
    monkeypatch.setattr(
        publication.time,
        "sleep",
        lambda delay: pytest.fail("immutable public state must not be retried"),
    )
    monkeypatch.setattr(
        publication,
        "verify_pypi",
        lambda observed, **kwargs: pytest.fail(
            "assets must be exact before checking PyPI"
        ),
    )

    with pytest.raises(RuntimeError, match="asset metadata is not complete"):
        publication.finalize_release(
            repo="VanL/taut",
            tag="v1.2.3",
            expected_sha="a" * 40,
            expected=expected,
        )


def test_finalize_rerun_requires_public_immutable_release_and_complete_pypi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    verified: list[object] = []
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)
    monkeypatch.setattr(
        publication,
        "list_releases",
        lambda repo: (_release(digests, draft=False, immutable=True),),
    )
    monkeypatch.setattr(
        publication,
        "verify_pypi",
        lambda observed, **kwargs: verified.append(observed),
    )
    monkeypatch.setattr(
        publication,
        "github_api_request",
        lambda *args, **kwargs: pytest.fail("immutable rerun must not mutate GitHub"),
    )

    publication.finalize_release(
        repo="VanL/taut",
        tag="v1.2.3",
        expected_sha="a" * 40,
        expected=expected,
    )
    assert verified == [expected]


def test_wrong_tag_sha_and_duplicate_release_state_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, dist, digests = _release_files(tmp_path)
    expected = publication.read_publication(manifest, dist)
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "b" * 40)

    with pytest.raises(RuntimeError, match="expected release SHA"):
        publication.stage_draft(
            repo="VanL/taut",
            tag="v1.2.3",
            expected_sha="a" * 40,
            expected=expected,
        )

    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)
    monkeypatch.setattr(
        publication,
        "list_releases",
        lambda repo: (_release(digests), _release(digests)),
    )
    with pytest.raises(RuntimeError, match="at most one"):
        publication.stage_draft(
            repo="VanL/taut",
            tag="v1.2.3",
            expected_sha="a" * 40,
            expected=expected,
        )


def test_verify_tag_rechecks_remote_commit_without_token_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(publication, "resolve_tag_commit", lambda repo, tag: "a" * 40)

    publication.verify_tag(
        repo="VanL/taut",
        tag="v1.2.3",
        expected_sha="a" * 40,
    )


def test_cli_has_no_token_argument() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "scripts"
        / "release_publication.py"
    ).read_text("utf-8")
    assert 'add_argument("--token"' not in source
