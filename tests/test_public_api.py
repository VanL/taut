from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

import taut

pytestmark = pytest.mark.sqlite_only

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_PUBLIC_EXPORTS = [
    "AmbiguousMessageError",
    "BackendNotSupportedError",
    "BlankMessageError",
    "EmptyResultError",
    "IdentityError",
    "Member",
    "MembershipError",
    "Message",
    "NotInitializedError",
    "NotFoundError",
    "Notification",
    "SchemaVersionError",
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
    member: taut.Member,
    message: taut.Message,
    notification: taut.Notification,
    thread: taut.Thread,
) -> tuple[
    taut.TautClient,
    taut.TautWatcher,
    taut.Member,
    taut.Message,
    taut.Notification,
    taut.Thread,
]:
    return client, watcher, member, message, notification, thread


def test_exception_leaves_are_public_exports() -> None:
    assert taut.__all__ == EXPECTED_PUBLIC_EXPORTS
    assert issubclass(taut.BlankMessageError, taut.EmptyResultError)
    assert taut.NotFoundError.__name__ == "NotFoundError"
    assert taut.TokenError.__name__ == "TokenError"
    assert taut.TautWatcher.__name__ == "TautWatcher"
    assert "NotFoundError" in taut.__all__
    assert "TokenError" in taut.__all__
    assert "TautWatcher" in taut.__all__
    assert taut.Notification.__name__ == "Notification"
    assert "Notification" in taut.__all__


def test_lazy_public_exports_cache_and_unknown_names_fail_normally() -> None:
    client_type = taut.TautClient

    assert vars(taut)["TautClient"] is client_type
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


def test_notification_peek_limit_is_keyword_only_with_core_default() -> None:
    """[TAUT-8.3] The public peek keeps the core 1,000-record bound."""

    parameters = inspect.signature(taut.TautClient.peek_inbox).parameters

    assert parameters["limit"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["limit"].default == 1000


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
    from taut.client import Member, Message, Notification, TautClient, Thread
    from taut.terminal import escape_terminal_text
    from taut.watcher import TautWatcher

    assert taut.Member is Member
    assert taut.Message is Message
    assert taut.Notification is Notification
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
