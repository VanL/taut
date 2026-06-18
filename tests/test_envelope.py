from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from taut.envelope import decode_envelope, encode_envelope

pytestmark = pytest.mark.sqlite_only


@given(
    from_handle=st.from_regex(r"^[a-z0-9][a-z0-9_-]{0,20}$", fullmatch=True),
    text=st.text(),
    kind=st.sampled_from(["message", "notice"]),
)
def test_envelope_round_trip(from_handle: str, text: str, kind: str) -> None:
    body = encode_envelope(from_handle=from_handle, kind=kind, text=text)  # type: ignore[arg-type]

    decoded = decode_envelope(body)

    assert decoded.from_handle == from_handle
    assert decoded.kind == kind
    assert decoded.text == text


@given(body=st.text())
def test_decode_never_raises_for_arbitrary_text(body: str) -> None:
    decode_envelope(body)


def test_foreign_and_future_inputs_render_as_foreign() -> None:
    assert decode_envelope("plain text").kind == "foreign"

    future = decode_envelope('{"v":2,"from":"a","kind":"message","text":"x"}')

    assert future.kind == "foreign"
    assert future.warning is not None
