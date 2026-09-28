from __future__ import annotations

import json
import subprocess
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from taut._redact import redact_sensitive_text

pytestmark = pytest.mark.sqlite_only

_EXACT_CREDENTIAL_LABELS = (
    "access_key",
    "api_key",
    "auth_key",
    "authorization",
    "client_secret",
    "credential",
    "credentials",
    "encryption_key",
    "password",
    "passwd",
    "private_key",
    "pwd",
    "secret",
    "secret_key",
    "access_token",
    "api_token",
    "auth_token",
)

_QUALIFIED_CREDENTIAL_SUFFIXES = (
    "_access_key",
    "_api_key",
    "_auth_key",
    "_authorization",
    "_client_secret",
    "_credential",
    "_credentials",
    "_encryption_key",
    "_password",
    "_passwd",
    "_private_key",
    "_pwd",
    "_secret",
    "_secret_key",
    "_access_token",
    "_api_token",
    "_auth_token",
)


def _runtime_value(*parts: str) -> str:
    return "".join(parts)


def _private_key_fixture(key_type: str, body: str | None = None) -> str:
    if body is None:
        body = _runtime_value("ZGVidWctcHJpdmF0ZS1", "rZXktYm9keQ==")
    return f"-----BEGIN {key_type}-----\n{body}\n-----END {key_type}-----"


def test_redact_sensitive_text_preserves_label_and_json() -> None:
    payload = json.dumps(
        {"message": "password=debug-secret-value"},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    redacted = redact_sensitive_text(payload)

    assert json.loads(redacted) == {"message": "password=<redacted>"}
    assert "debug-secret-value" not in redacted


def test_redact_sensitive_text_handles_escaped_json_value() -> None:
    secret = 'debug-"quoted\\secret'
    payload = json.dumps(
        {"message": json.dumps({"password": secret}, separators=(",", ":"))},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    redacted = redact_sensitive_text(payload)

    assert json.loads(redacted) == {"message": '{"password":"<redacted>"}'}
    assert secret not in redacted


@pytest.mark.parametrize("trailing_backslashes", [1, 2, 4])
def test_incomplete_escaped_assignment_does_not_consume_outer_json(
    trailing_backslashes: int,
) -> None:
    message = 'prefix password="debug-secret' + ("\\" * trailing_backslashes)
    event = {
        "exception": {"message": message},
        "neighbor": {"ok": True},
        "unicode": "λ 雪",
    }
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))

    redacted = redact_sensitive_text(payload)

    assert json.loads(redacted) == event


@settings(max_examples=100)
@given(
    form=st.sampled_from(["assignment", "mapping"]),
    secret=st.text(
        alphabet=st.sampled_from(["a", "Z", '"', "\\", "\n", "λ", "雪"]),
        min_size=1,
        max_size=40,
    ),
)
def test_closed_escaped_value_redaction_preserves_json_structure(
    form: str,
    secret: str,
) -> None:
    if form == "assignment":
        message = "password=" + json.dumps(secret, ensure_ascii=False)
        expected_message = 'password="<redacted>"'
    else:
        message = json.dumps(
            {"password": secret}, ensure_ascii=False, separators=(",", ":")
        )
        expected_message = '{"password":"<redacted>"}'
    event = {
        "message": message,
        "neighbor": {"items": [1, True, None]},
        "unicode": "λ 雪",
    }
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))

    parsed = json.loads(redact_sensitive_text(payload))

    assert parsed == {
        "message": expected_message,
        "neighbor": {"items": [1, True, None]},
        "unicode": "λ 雪",
    }


def test_redact_sensitive_text_handles_single_quoted_repr_value() -> None:
    secret = "debug-'quoted\\secret"
    rendered_mapping = "{'password': 'debug-\\'quoted\\\\secret'}"
    payload = json.dumps(
        {"message": rendered_mapping},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    redacted = redact_sensitive_text(payload)

    assert json.loads(redacted) == {"message": "{'password': '<redacted>'}"}
    assert secret not in json.loads(redacted)["message"]


@pytest.mark.parametrize(
    "label",
    [
        *_EXACT_CREDENTIAL_LABELS,
        *(f"provider{suffix}" for suffix in _QUALIFIED_CREDENTIAL_SUFFIXES),
        "anthropicApiKey",
        "databasePassword",
        "providerAuthToken",
    ],
)
def test_redact_sensitive_text_covers_normative_labels(label: str) -> None:
    redacted = redact_sensitive_text(f"{label}=debug-secret-value")

    assert redacted == f"{label}=<redacted>"


@pytest.mark.parametrize(
    "label",
    ["token", "TAUT_TOKEN", "continuity_token", "provider_token"],
)
def test_redact_sensitive_text_preserves_noncredential_token_labels(label: str) -> None:
    text = f"{label}=taut-continuity-value"

    assert redact_sensitive_text(text) == text


@pytest.mark.parametrize("scheme", ["Bearer", "Basic"])
def test_redact_sensitive_text_preserves_authorization_scheme(scheme: str) -> None:
    text = f"Authorization: {scheme} debug-credential-value"

    assert redact_sensitive_text(text) == f"Authorization: {scheme} <redacted>"


@pytest.mark.parametrize(
    "uri",
    [
        "postgresql://dbuser:debug-db-password@db.example/taut",
        "postgres://dbuser:debug-db-password@db.example/taut",
        "mongodb://dbuser:debug-db-password@db.example/taut",
        "mongodb+srv://dbuser:debug-db-password@db.example/taut",
        "redis://dbuser:debug-db-password@db.example/0",
        "redis://:debug-db-password@db.example/0",
        "rediss://dbuser:debug-db-password@db.example/0",
        "amqp://dbuser:debug-db-password@db.example/vhost",
        "amqps://dbuser:debug-db-password@db.example/vhost",
        "ftp://dbuser:debug-db-password@files.example/root",
    ],
)
def test_redact_sensitive_text_preserves_credentialed_uri_structure(uri: str) -> None:
    redacted = redact_sensitive_text(uri)

    assert redacted == uri.replace("debug-db-password", "<redacted>")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "host=db.example password='debug db password' dbname=taut",
            "host=db.example password='<redacted>' dbname=taut",
        ),
        (
            'host=db.example password="debug db password" dbname=taut',
            'host=db.example password="<redacted>" dbname=taut',
        ),
        (
            "jdbc:postgresql://db.example/taut?user=taut&password=debug-db-password&ssl=true",
            "jdbc:postgresql://db.example/taut?user=taut&password=<redacted>&ssl=true",
        ),
    ],
)
def test_redact_sensitive_text_handles_conninfo_and_query_passwords(
    text: str,
    expected: str,
) -> None:
    assert redact_sensitive_text(text) == expected


def test_redact_sensitive_text_handles_quoted_assignment_in_final_json() -> None:
    payload = json.dumps(
        {"message": 'host=db password="debug db password" dbname=taut'},
        separators=(",", ":"),
    )

    redacted = redact_sensitive_text(payload)

    assert json.loads(redacted) == {
        "message": 'host=db password="<redacted>" dbname=taut'
    }


def test_redact_sensitive_text_preserves_private_key_boundaries() -> None:
    text = _private_key_fixture("OPENSSH PRIVATE KEY")

    assert redact_sensitive_text(text) == _private_key_fixture(
        "OPENSSH PRIVATE KEY", "<redacted>"
    )


def test_redact_sensitive_text_preserves_private_key_boundaries_in_json() -> None:
    pem = _private_key_fixture("PRIVATE KEY")
    payload = json.dumps({"message": pem}, separators=(",", ":"))

    redacted = redact_sensitive_text(payload)

    assert json.loads(redacted) == {
        "message": _private_key_fixture("PRIVATE KEY", "<redacted>")
    }


def test_unlabeled_vendor_shaped_text_is_outside_structural_redaction() -> None:
    credential = _runtime_value("gh", "p_", "A" * 36)
    assert redact_sensitive_text(f"value={credential}") == f"value={credential}"


@pytest.mark.parametrize(
    "text",
    [
        "token=taut-continuity-value",
        "TAUT_TOKEN=taut-continuity-value",
        "continuity_token=taut-continuity-value",
        "provider_token=not-a-credential-format",
        "primary_key=record-id",
        "postgresql://db.example/taut",
        "mongodb://db.example/taut",
        "pk_live_" + "A" * 20,
        "ghp_too_short",
        "AIzaSytoo_short",
    ],
)
def test_redact_sensitive_text_preserves_nonsecret_near_misses(text: str) -> None:
    assert redact_sensitive_text(text) == text


def test_redact_sensitive_text_handles_repeated_and_overlapping_matches() -> None:
    credential = "first-secret"
    text = f"api_key={credential}; password=second-secret; value={credential}"

    assert redact_sensitive_text(text) == (
        "api_key=<redacted>; password=<redacted>; value=first-secret"
    )


_RULE_CASES = {
    "labeled_json_direct": (
        '"password":"secret-value"',
        '"password":"<redacted>"',
    ),
    "labeled_double_quoted": ('password="secret value"', 'password="<redacted>"'),
    "labeled_single_quoted": ("password='secret value'", "password='<redacted>'"),
    "labeled_unquoted": ("password=secret-value", "password=<redacted>"),
    "labeled_json_escaped": (
        r"{\"password\":\"secret-value\"}",
        r"{\"password\":\"<redacted>\"}",
    ),
    "labeled_json_escaped_assignment": (
        r"password=\"secret value\"",
        r"password=\"<redacted>\"",
    ),
    "labeled_repr_single_quoted": (
        "{'password': 'secret-value'}",
        "{'password': '<redacted>'}",
    ),
    "authorization_scheme": (
        "Authorization: Bearer secret-value",
        "Authorization: Bearer <redacted>",
    ),
    "credentialed_uri": (
        "postgresql://user:secret-value@db.example/taut",
        "postgresql://user:<redacted>@db.example/taut",
    ),
    "private_key_pem_body": (
        _private_key_fixture("PRIVATE KEY", "QUJDRA=="),
        _private_key_fixture("PRIVATE KEY", "<redacted>"),
    ),
    "private_key_pem_body_json": (
        _private_key_fixture("PRIVATE KEY", "QUJDRA==").replace("\n", r"\n"),
        _private_key_fixture("PRIVATE KEY", "<redacted>").replace("\n", r"\n"),
    ),
}


@pytest.mark.parametrize(("text", "expected"), tuple(_RULE_CASES.values()))
def test_structural_redaction_examples(text: str, expected: str) -> None:
    assert redact_sensitive_text(text) == expected


def test_redaction_hostile_maximum_text_is_bounded() -> None:
    code = (
        "from taut._redact import redact_sensitive_text; "
        "text = '\\\"password\\\":\\\"' + ('\\\\\\\"' * 32768); "
        "redact_sensitive_text(text)"
    )

    subprocess.run([sys.executable, "-c", code], check=True, timeout=5)


@pytest.mark.parametrize(
    "text",
    [
        json.dumps({"message": 'connect failed: password="' + "a" * 64}),
        json.dumps({"password": "b" * 64 + "\n"})[:-3],
        json.dumps({"message": 'token="' + "c1-d2 e3.f4/g5:h6!i7 " * 8}),
    ],
    ids=["assignment", "mapping-truncated", "assignment-punctuated"],
)
def test_unterminated_escaped_credential_value_is_linear(text: str) -> None:
    code = (
        "import sys; from taut._redact import redact_sensitive_text; "
        "redact_sensitive_text(sys.stdin.read())"
    )

    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        input=text,
        text=True,
        timeout=5,
    )
