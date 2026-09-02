from __future__ import annotations

import inspect
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

import taut

pytestmark = pytest.mark.sqlite_only

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_PUBLIC_EXPORTS = [
    "AmbiguousMessageError",
    "BackendNotSupportedError",
    "BlankMessageError",
    "Channel",
    "DoctorCheck",
    "DoctorReport",
    "DumpReport",
    "EmptyResultError",
    "IdentityError",
    "UnrecognizedCallerError",
    "LoadReport",
    "Member",
    "MembershipError",
    "Message",
    "MessageDeletion",
    "MessageReaction",
    "NotInitializedError",
    "NotFoundError",
    "Notification",
    "PersistenceComponentReport",
    "SchemaVersionError",
    "SearchHit",
    "WatcherRejected",
    "TautClient",
    "TautError",
    "TautWatcher",
    "Thread",
    "ThreadNameError",
    "TokenError",
    "__version__",
    "escape_terminal_text",
]


def _typed_public_surface(
    client: taut.TautClient,
    watcher: taut.TautWatcher,
    channel: taut.Channel,
    member: taut.Member,
    message: taut.Message,
    deletion: taut.MessageDeletion,
    reaction: taut.MessageReaction,
    notification: taut.Notification,
    search_hit: taut.SearchHit,
    thread: taut.Thread,
) -> tuple[
    taut.TautClient,
    taut.TautWatcher,
    taut.Channel,
    taut.Member,
    taut.Message,
    taut.MessageDeletion,
    taut.MessageReaction,
    taut.Notification,
    taut.SearchHit,
    taut.Thread,
]:
    return (
        client,
        watcher,
        channel,
        member,
        message,
        deletion,
        reaction,
        notification,
        search_hit,
        thread,
    )


def test_exception_leaves_are_public_exports() -> None:
    assert len(taut.__all__) == len(set(taut.__all__)) == len(EXPECTED_PUBLIC_EXPORTS)
    assert set(taut.__all__) == set(EXPECTED_PUBLIC_EXPORTS)
    assert issubclass(taut.BlankMessageError, taut.EmptyResultError)
    assert taut.WatcherRejected.__module__ == "taut._exceptions"
    assert not issubclass(taut.WatcherRejected, taut.TautError)


def test_persistence_reports_are_exact_frozen_slotted_public_values() -> None:
    """[PIO-3.2] Persistence reports have exact typed public shapes."""

    from taut.client import DumpReport, LoadReport, PersistenceComponentReport

    assert taut.DumpReport is DumpReport
    assert taut.LoadReport is LoadReport
    assert taut.PersistenceComponentReport is PersistenceComponentReport
    assert [field.name for field in fields(PersistenceComponentReport)] == [
        "name",
        "version",
        "records",
    ]
    assert [field.name for field in fields(DumpReport)] == [
        "path",
        "format",
        "version",
        "components",
        "queues",
        "messages",
        "omitted_claimed_messages",
    ]
    assert [field.name for field in fields(LoadReport)] == [
        "path",
        "format",
        "version",
        "components",
        "queues",
        "messages",
        "dry_run",
        "destination_checked",
        "applied",
    ]
    component = PersistenceComponentReport(name="core", version=1, records=3)
    dump = DumpReport(
        path="workspace.taut.jsonl",
        format="taut-workspace",
        version=1,
        components=(component,),
        queues=2,
        messages=3,
        omitted_claimed_messages=0,
    )
    load = LoadReport(
        path="workspace.taut.jsonl",
        format="taut-workspace",
        version=1,
        components=(component,),
        queues=2,
        messages=3,
        dry_run=False,
        destination_checked=True,
        applied=True,
    )

    for report in (component, dump, load):
        assert not hasattr(report, "__dict__")
    with pytest.raises(FrozenInstanceError):
        component.name = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        dump.path = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        load.path = "changed"  # type: ignore[misc]


def test_doctor_reports_are_exact_frozen_slotted_public_values() -> None:
    """[DOCT-3.2] Doctor reports have exact typed public shapes."""

    from taut.client import DoctorCheck, DoctorReport

    assert taut.DoctorCheck is DoctorCheck
    assert taut.DoctorReport is DoctorReport
    assert [field.name for field in fields(DoctorCheck)] == [
        "name",
        "status",
        "detail",
        "data",
    ]
    assert [field.name for field in fields(DoctorReport)] == [
        "db",
        "healthy",
        "checks",
    ]
    check = DoctorCheck("core_schema", "pass", "current", {"version": 2})
    report = DoctorReport("workspace.db", True, (check,))
    assert not hasattr(check, "__dict__")
    assert not hasattr(report, "__dict__")
    with pytest.raises(FrozenInstanceError):
        check.name = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        report.db = "changed"  # type: ignore[misc]
    signature = inspect.signature(taut.TautClient.doctor)
    assert list(signature.parameters) == ["db_path"]
    assert signature.parameters["db_path"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["db_path"].default is None


def test_search_hit_is_exact_frozen_slotted_public_value() -> None:
    """[SRCH-5.2] Search hits have one exact typed public shape."""

    from taut.client import SearchHit

    assert taut.SearchHit is SearchHit
    assert SearchHit.__module__ == "taut.client"
    assert [field.name for field in fields(SearchHit)] == [
        "thread",
        "ts",
        "from_id",
        "from_name",
        "kind",
        "text",
        "thread_kind",
        "channel",
        "parent",
        "members",
    ]
    hit = SearchHit(
        thread="general",
        ts=1786032926849409024,
        from_id="m_abcd1234abcd1234abcd1234ab",
        from_name="van",
        kind="message",
        text="parser is green",
        thread_kind="channel",
        channel="general",
        parent=None,
        members=None,
    )

    assert not hasattr(hit, "__dict__")
    with pytest.raises(FrozenInstanceError):
        hit.text = "changed"  # type: ignore[misc]


def test_unknown_public_names_fail_normally() -> None:
    missing_name = "missing_public_name"
    with pytest.raises(AttributeError, match="missing_public_name"):
        getattr(taut, missing_name)


def test_every_public_export_resolves() -> None:
    assert {name for name in taut.__all__ if not hasattr(taut, name)} == set()


def test_unread_limit_is_keyword_only_with_core_default() -> None:
    for method_name in ("read", "read_unread"):
        parameters = inspect.signature(getattr(taut.TautClient, method_name)).parameters

        assert parameters["thread"].default is None
        assert parameters["limit"].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters["limit"].default == 1000


def test_history_around_bounds_are_keyword_only_with_core_defaults() -> None:
    parameters = inspect.signature(taut.TautClient.history_around).parameters

    assert list(parameters) == ["self", "thread", "msg_id", "before", "after"]
    assert parameters["before"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["before"].default == 25
    assert parameters["after"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["after"].default == 25


def test_notification_peek_limit_is_keyword_only_with_core_default() -> None:
    """[TAUT-8.3] The public peek keeps the core 1,000-record bound."""

    parameters = inspect.signature(taut.TautClient.peek_inbox).parameters

    assert parameters["limit"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["limit"].default == 1000


def test_public_identity_activity_seams_have_exact_signatures() -> None:
    """[TAUT-8.3] Extension seams accept no alternate selector or queue name."""

    assert list(inspect.signature(taut.TautClient.peek_identity).parameters) == ["self"]
    assert list(
        inspect.signature(taut.TautClient.notification_activity_queue).parameters
    ) == ["self"]


def test_client_environment_identity_inheritance_is_keyword_only_and_defaulted() -> (
    None
):
    """[TAUT-8.3] Existing callers retain ambient identity inheritance."""

    parameters = inspect.signature(taut.TautClient).parameters

    assert (
        parameters["inherit_environment_identity"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )
    assert parameters["inherit_environment_identity"].default is True


def test_lazy_exports_are_the_owning_module_objects() -> None:
    from taut.client import (
        Channel,
        DoctorCheck,
        DoctorReport,
        DumpReport,
        LoadReport,
        Member,
        Message,
        MessageDeletion,
        MessageReaction,
        Notification,
        PersistenceComponentReport,
        SearchHit,
        TautClient,
        Thread,
    )
    from taut.terminal import escape_terminal_text
    from taut.watcher import TautWatcher

    assert taut.Member is Member
    assert taut.Channel is Channel
    assert taut.DoctorCheck is DoctorCheck
    assert taut.DoctorReport is DoctorReport
    assert taut.Message is Message
    assert taut.MessageDeletion is MessageDeletion
    assert taut.MessageReaction is MessageReaction
    assert taut.Notification is Notification
    assert taut.SearchHit is SearchHit
    assert taut.DumpReport is DumpReport
    assert taut.LoadReport is LoadReport
    assert taut.PersistenceComponentReport is PersistenceComponentReport
    assert taut.TautClient is TautClient
    assert taut.TautWatcher is TautWatcher
    assert taut.Thread is Thread
    assert taut.escape_terminal_text is escape_terminal_text


def test_static_typing_rejects_unknown_public_export(tmp_path: Path) -> None:
    probe = tmp_path / "unknown_taut_export.py"
    probe.write_text(
        "import taut\n\nclient_type = taut.TautCleint\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(PROJECT_ROOT / "pyproject.toml"),
            str(probe),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert 'Module has no attribute "TautCleint"' in result.stdout
