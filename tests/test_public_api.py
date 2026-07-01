from __future__ import annotations

import pytest

import taut

pytestmark = pytest.mark.sqlite_only


def test_exception_leaves_are_public_exports() -> None:
    assert taut.NotFoundError.__name__ == "NotFoundError"
    assert taut.TokenError.__name__ == "TokenError"
    assert taut.TautWatcher.__name__ == "TautWatcher"
    assert "NotFoundError" in taut.__all__
    assert "TokenError" in taut.__all__
    assert "TautWatcher" in taut.__all__
    assert taut.Notification.__name__ == "Notification"
    assert "Notification" in taut.__all__
