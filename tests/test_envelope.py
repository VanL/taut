from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from taut.envelope import decode_envelope, encode_envelope

pytestmark = pytest.mark.sqlite_only


@given(
    from_id=st.from_regex(r"^m_[a-z0-9]{26}$", fullmatch=True),
    from_name=st.from_regex(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,20}$", fullmatch=True),
    text=st.text(),
    kind=st.sampled_from(["message", "notice"]),
)
def test_envelope_round_trip(
    from_id: str,
    from_name: str,
    text: str,
    kind: str,
) -> None:
    body = encode_envelope(
        from_id=from_id,
        from_name=from_name,
        kind=kind,  # type: ignore[arg-type]
        text=text,
    )

    decoded = decode_envelope(body)

    assert decoded.from_id == from_id
    assert decoded.from_name == from_name
    assert decoded.kind == kind
    assert decoded.text == text


@given(body=st.text())
def test_decode_never_raises_for_arbitrary_text(body: str) -> None:
    decode_envelope(body)


def test_foreign_and_malformed_shape_inputs_render_as_foreign() -> None:
    assert decode_envelope("plain text").kind == "foreign"

    old = decode_envelope('{"sender":"a","kind":"message","text":"x"}')

    assert old.kind == "foreign"
    assert old.from_id is None
    assert old.from_name == "?"


def test_envelope_without_from_id_decodes_as_foreign() -> None:
    decoded = decode_envelope('{"from":"a","kind":"message","text":"x"}')

    assert decoded.kind == "foreign"
