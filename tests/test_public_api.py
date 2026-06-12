from __future__ import annotations

import taut


def test_exception_leaves_are_public_exports() -> None:
    assert taut.NotFoundError.__name__ == "NotFoundError"
    assert taut.TokenError.__name__ == "TokenError"
    assert "NotFoundError" in taut.__all__
    assert "TokenError" in taut.__all__
