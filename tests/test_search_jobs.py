from __future__ import annotations

import pytest

from taut.search._jobs import (
    MalformedSearchJob,
    MessageJob,
    decode_message_job,
    decode_thread_rename_job,
    encode_message_job,
    encode_thread_rename_job,
)

pytestmark = pytest.mark.sqlite_only


def test_message_job_codec_is_exact_content_free_and_strict() -> None:
    """[SRCH-8.2] Version-one message jobs have one closed JSON shape."""

    message_ts = 1786032926849409024
    body = encode_message_job(message_ts=message_ts, thread="general")

    assert body == (
        '{"entity":"message","message_ts":1786032926849409024,"thread":"general","v":1}'
    )
    assert "parser is green" not in body
    assert decode_message_job(body) == MessageJob(
        message_ts=message_ts,
        thread="general",
    )


def test_thread_rename_job_codec_preserves_exact_content_free_mapping() -> None:
    body = encode_thread_rename_job(
        old="general",
        new="ops",
        affected=[
            {"old": "general", "new": "ops"},
            {"old": "general.1786032926849409024", "new": "ops.1786032926849409024"},
        ],
    )

    assert decode_thread_rename_job(body).affected == (
        ("general", "ops"),
        ("general.1786032926849409024", "ops.1786032926849409024"),
    )
    assert "message text" not in body


def test_thread_rename_job_rejects_mismatched_top_level_mapping() -> None:
    body = (
        '{"affected":[{"new":"other","old":"general"}],'
        '"entity":"thread_rename","new":"ops","old":"general","v":1}'
    )

    with pytest.raises(MalformedSearchJob) as raised:
        decode_thread_rename_job(body)

    assert raised.value.code == "invalid_rename"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("not-json", "invalid_json"),
        ("[]", "not_object"),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"general","v":1,"x":0}'
            ),
            "unexpected_fields",
        ),
        (
            (
                '{"entity":"message","entity":"message",'
                '"message_ts":1786032926849409024,"thread":"general","v":1}'
            ),
            "duplicate_field",
        ),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"general"}'
            ),
            "unexpected_fields",
        ),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"general","v":2}'
            ),
            "invalid_version",
        ),
        (
            (
                '{"entity":"thread_rename","message_ts":1786032926849409024,'
                '"thread":"general","v":1}'
            ),
            "invalid_entity",
        ),
        (
            ('{"entity":"message","message_ts":true,"thread":"general","v":1}'),
            "invalid_message_ts",
        ),
        (
            ('{"entity":"message","message_ts":1,"thread":"general","v":1}'),
            "invalid_message_ts",
        ),
        (
            ('{"entity":"message","message_ts":1786032926849409024,"thread":7,"v":1}'),
            "invalid_thread",
        ),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"taut.search_index","v":1}'
            ),
            "invalid_thread",
        ),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"dm.bad","v":1}'
            ),
            "invalid_thread",
        ),
    ],
)
def test_message_job_decoder_reports_bounded_structural_codes(
    body: str,
    code: str,
) -> None:
    with pytest.raises(MalformedSearchJob) as raised:
        decode_message_job(body)

    assert raised.value.code == code
    assert len(raised.value.code.encode("ascii")) <= 32
