"""Lazy first-party search provider discovery contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from taut.search._manifest import SearchBackendSpec
from taut.search._provider import SidecarAccessor

pytestmark = pytest.mark.sqlite_only


@dataclass(frozen=True)
class _Distribution:
    name: str


@dataclass(frozen=True)
class _EntryPoint:
    name: str
    value: str
    manifest: object
    owner: str = "taut-pg"
    load_calls: list[str] | None = None
    fail_on_load: bool = False

    @property
    def dist(self) -> _Distribution:
        return _Distribution(self.owner)

    def load(self) -> object:
        if self.load_calls is not None:
            self.load_calls.append(self.owner)
        if self.fail_on_load:
            pytest.fail(f"ineligible provider loaded from {self.owner}")
        return self.manifest


class _CompleteProvider:
    def schema_version(self) -> int:
        return 2

    def ensure_schema(self) -> None: ...

    def replace_document(
        self, document: object, *, revision: int | None = None
    ) -> bool:
        return True

    def reconcile_unchanged_batch(
        self,
        checks: object,
        *,
        revision: int,
    ) -> frozenset[int]:
        del checks, revision
        return frozenset()

    def delete_document(self, *, message_ts: int, thread: str, revision: int) -> bool:
        return True

    def applied_revision(self, message_ts: int) -> int | None:
        return None

    def retarget_threads(
        self,
        affected: tuple[tuple[str, str], ...],
        *,
        revision: int,
    ) -> None: ...

    def thread_watermark(self, thread: str) -> object:
        return object()

    def indexed_message_ids(self, thread: str) -> tuple[int, ...]:
        return ()

    def record_reconciliation(
        self,
        thread: str,
        *,
        watermark: int | None,
        revision: int,
    ) -> bool:
        return True

    def next_reconciliation_thread(
        self,
        threads: tuple[str, ...],
    ) -> str | None:
        return None

    def requires_rebuild(self) -> bool:
        return False

    def begin_rebuild(self, scan_revision: int) -> int:
        return scan_revision

    def replace_rebuild_document(
        self,
        document: object,
        *,
        generation: int,
        revision: int,
    ) -> bool:
        return True

    def finish_rebuild(self, generation: int) -> None: ...

    def abort_rebuild(self, generation: int) -> None: ...

    def query(
        self,
        chunks: tuple[str, ...],
        *,
        before: int | None = None,
        threads: tuple[str, ...] | None = None,
        limit: int,
    ) -> list[object]:
        del chunks, before, threads, limit
        return []

    def close(self) -> None: ...


def test_postgres_provider_discovery_validates_manifest_before_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.search import _discovery

    calls: list[object] = []

    provider = _CompleteProvider()

    def factory(*, sidecar: object) -> _CompleteProvider:
        calls.append(sidecar)
        return provider

    monkeypatch.setattr(
        _discovery,
        "_search_entry_points",
        lambda: (
            _EntryPoint(
                name="postgres",
                value="fixture_manifest:postgres",
                manifest=SearchBackendSpec(1, "postgres", "fixture:factory"),
            ),
        ),
    )
    monkeypatch.setattr(_discovery, "_load_factory", lambda _target: factory)
    sidecar = cast(SidecarAccessor, object())

    assert (
        _discovery.load_search_provider(backend_name="postgres", sidecar=sidecar)
        is provider
    )
    assert calls == [sidecar]


def test_postgres_provider_discovery_filters_foreign_claim_before_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.search import _discovery

    provider = _CompleteProvider()
    loads: list[str] = []
    monkeypatch.setattr(
        _discovery,
        "_search_entry_points",
        lambda: (
            _EntryPoint(
                "postgres",
                "foreign:x",
                SearchBackendSpec(1, "postgres", "foreign:x"),
                owner="foreign",
                load_calls=loads,
                fail_on_load=True,
            ),
            _EntryPoint(
                "postgres",
                "official:x",
                SearchBackendSpec(1, "postgres", "official:x"),
                owner="TAUT.PG",
                load_calls=loads,
            ),
        ),
    )
    monkeypatch.setattr(
        _discovery, "_load_factory", lambda _target: lambda **_: provider
    )

    resolved = _discovery.load_search_provider(
        backend_name="postgres",
        sidecar=cast(SidecarAccessor, object()),
    )

    assert resolved is provider
    assert loads == ["TAUT.PG"]


@pytest.mark.parametrize(
    "entries",
    [
        (),
        (
            _EntryPoint(
                "postgres",
                "a:x",
                SearchBackendSpec(1, "postgres", "a:x"),
                fail_on_load=True,
            ),
            _EntryPoint(
                "postgres",
                "b:x",
                SearchBackendSpec(1, "postgres", "b:x"),
                fail_on_load=True,
            ),
        ),
        (
            _EntryPoint(
                "postgres",
                "a:x",
                SearchBackendSpec(1, "postgres", "a:x"),
                owner="foreign",
                fail_on_load=True,
            ),
        ),
        (_EntryPoint("postgres", "a:x", SearchBackendSpec(True, "postgres", "a:x")),),
        (_EntryPoint("postgres", "a:x", SearchBackendSpec(1, "sqlite", "a:x")),),
        (_EntryPoint("postgres", "a:x", SearchBackendSpec(1, "postgres", "bad")),),
    ],
)
def test_postgres_provider_discovery_rejects_untrusted_or_ambiguous_claims(
    monkeypatch: pytest.MonkeyPatch,
    entries: tuple[_EntryPoint, ...],
) -> None:
    from taut.search import _discovery

    monkeypatch.setattr(_discovery, "_search_entry_points", lambda: entries)

    with pytest.raises(
        _discovery.SearchProviderUnavailableError,
        match=r"taut-pg.*(install|upgrade)",
    ):
        _discovery.load_search_provider(
            backend_name="postgres", sidecar=cast(SidecarAccessor, object())
        )


def test_provider_missing_schema_version_reports_invalid_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.search import _discovery

    monkeypatch.setattr(_CompleteProvider, "schema_version", None)
    with pytest.raises(
        _discovery.SearchProviderUnavailableError,
        match=r"taut-pg.*(install|upgrade)",
    ):
        _discovery._validate_provider(_CompleteProvider())


class _ValidV2Provider(_CompleteProvider):
    def reconcile_unchanged_batch(
        self,
        checks: object,
        *,
        revision: int,
    ) -> frozenset[int]:
        del checks, revision
        return frozenset()

    def query(
        self,
        chunks: tuple[str, ...],
        *,
        before: int | None = None,
        threads: tuple[str, ...] | None = None,
        limit: int,
    ) -> list[object]:
        del chunks, before, threads, limit
        return []


def test_provider_missing_reconcile_unchanged_batch_is_rejected() -> None:
    from taut.search import _discovery

    class _MissingBatch(_ValidV2Provider):
        reconcile_unchanged_batch = None  # type: ignore[assignment]

    with pytest.raises(
        _discovery.SearchProviderUnavailableError,
        match=r"taut-pg.*(install|upgrade)",
    ):
        _discovery._validate_provider(_MissingBatch())


def test_provider_missing_threads_on_query_is_rejected() -> None:
    from taut.search import _discovery

    class _LegacyQuery(_ValidV2Provider):
        def query(  # type: ignore[override]
            self,
            chunks: tuple[str, ...],
            *,
            before: int | None = None,
            limit: int,
        ) -> list[object]:
            del chunks, before, limit
            return []

    with pytest.raises(
        _discovery.SearchProviderUnavailableError,
        match=r"taut-pg.*(install|upgrade)",
    ):
        _discovery._validate_provider(_LegacyQuery())


@pytest.mark.parametrize(
    "bad_param",
    ["revision", "before", "threads", "limit"],
)
def test_provider_positional_only_masked_by_var_keyword_is_rejected(
    bad_param: str,
) -> None:
    from taut.search import _discovery

    if bad_param == "revision":

        class _BadRevision(_ValidV2Provider):
            def reconcile_unchanged_batch(  # type: ignore[override]
                self,
                checks: object,
                revision: int = 1,
                /,
                **kwargs: object,
            ) -> frozenset[int]:
                del checks, revision, kwargs
                return frozenset()

        candidate: object = _BadRevision()
    elif bad_param == "before":

        class _BadBefore(_ValidV2Provider):
            def query(  # type: ignore[override]
                self,
                chunks: tuple[str, ...],
                before: int | None = None,
                /,
                *,
                threads: tuple[str, ...] | None = None,
                limit: int = 1,
                **kwargs: object,
            ) -> list[object]:
                del chunks, before, threads, limit, kwargs
                return []

        candidate = _BadBefore()
    elif bad_param == "threads":

        class _BadThreads(_ValidV2Provider):
            def query(  # type: ignore[override]
                self,
                chunks: tuple[str, ...],
                threads: tuple[str, ...] | None = None,
                /,
                *,
                before: int | None = None,
                limit: int = 1,
                **kwargs: object,
            ) -> list[object]:
                del chunks, threads, before, limit, kwargs
                return []

        candidate = _BadThreads()
    else:

        class _BadLimit(_ValidV2Provider):
            def query(  # type: ignore[override]
                self,
                chunks: tuple[str, ...],
                limit: int = 1,
                /,
                *,
                before: int | None = None,
                threads: tuple[str, ...] | None = None,
                **kwargs: object,
            ) -> list[object]:
                del chunks, limit, before, threads, kwargs
                return []

        candidate = _BadLimit()

    with pytest.raises(
        _discovery.SearchProviderUnavailableError,
        match=r"taut-pg.*(install|upgrade)",
    ):
        _discovery._validate_provider(candidate)
