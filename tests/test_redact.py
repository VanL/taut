from __future__ import annotations

import json
import subprocess
import sys

import pytest

from taut import _redact
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


_PROVIDER_CREDENTIAL_CASES = (
    (_runtime_value("gh", "p_", "A" * 36), "ghp_<redacted>"),
    (_runtime_value("sk_", "live_", "A" * 20), "sk_live_<redacted>"),
    (_runtime_value("rk_", "live_", "A" * 20), "rk_live_<redacted>"),
    (
        _runtime_value("xo", "xb-", "1234567890-", "1234567890abc"),
        "xoxb-<redacted>",
    ),
    (
        _runtime_value("https://hooks.slack.com/", "services/", "T123/B456/", "A" * 23),
        "https://hooks.slack.com/services/<redacted>",
    ),
    (_runtime_value("S", "G.", "A" * 20, ".", "B" * 39), "SG.<redacted>"),
    (
        _runtime_value("sk-ant-", "api03-", "A" * 93, "AA"),
        "sk-ant-api03-<redacted>",
    ),
    (
        _runtime_value("sk-abc", "T3BlbkFJ", "A" * 20),
        "sk-<redacted>",
    ),
    (_runtime_value("AIza", "Sy", "A" * 33), "AIzaSy<redacted>"),
    (_runtime_value("AK", "IA", "A" * 16), "AKIA<redacted>"),
    (_runtime_value("AS", "IA", "A" * 16), "ASIA<redacted>"),
)


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


@pytest.mark.parametrize(
    ("credential", "expected"),
    _PROVIDER_CREDENTIAL_CASES,
)
def test_redact_sensitive_text_preserves_provider_prefix(
    credential: str,
    expected: str,
) -> None:
    assert redact_sensitive_text(f"value={credential}") == f"value={expected}"


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
    credential = _PROVIDER_CREDENTIAL_CASES[0][0]
    text = f"api_key={credential}; password=second-secret; value={credential}"

    assert redact_sensitive_text(text) == (
        "api_key=<redacted>; password=<redacted>; value=ghp_<redacted>"
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
    "github_token": _PROVIDER_CREDENTIAL_CASES[0],
    "stripe_secret_key": _PROVIDER_CREDENTIAL_CASES[1],
    "slack_token": _PROVIDER_CREDENTIAL_CASES[3],
    "slack_webhook": _PROVIDER_CREDENTIAL_CASES[4],
    "sendgrid_key": _PROVIDER_CREDENTIAL_CASES[5],
    "anthropic_key": _PROVIDER_CREDENTIAL_CASES[6],
    "openai_key": _PROVIDER_CREDENTIAL_CASES[7],
    "google_api_key": _PROVIDER_CREDENTIAL_CASES[8],
    "aws_access_key": _PROVIDER_CREDENTIAL_CASES[9],
    "aws_session_key": _PROVIDER_CREDENTIAL_CASES[10],
}


def test_every_redaction_rule_has_a_firing_case() -> None:
    rule_ids = {rule.id for rule in _redact._RULES}

    assert rule_ids == set(_RULE_CASES)
    for rule_id, (text, expected) in _RULE_CASES.items():
        assert redact_sensitive_text(text) == expected, rule_id


def test_redaction_patterns_compile_lazily_in_fresh_process() -> None:
    code = (
        "from taut import _redact; "
        "assert _redact._compiled_rules.cache_info().currsize == 0"
    )

    subprocess.run([sys.executable, "-c", code], check=True, timeout=5)


def test_redaction_patterns_compile_once_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_compile = _redact.re.compile
    calls: list[str] = []

    def recording_compile(pattern: str, flags: int = 0) -> object:
        calls.append(pattern)
        return original_compile(pattern, flags)

    _redact._compiled_rules.cache_clear()
    monkeypatch.setattr(_redact.re, "compile", recording_compile)

    redact_sensitive_text("password=first-secret")
    first_call_count = len(calls)
    redact_sensitive_text("password=second-secret")

    assert first_call_count == len(_redact._RULES)
    assert len(calls) == first_call_count


def test_redaction_hostile_maximum_text_is_bounded() -> None:
    code = (
        "from taut._redact import redact_sensitive_text; "
        "text = '\\\"password\\\":\\\"' + ('\\\\\\\"' * 32768); "
        "redact_sensitive_text(text)"
    )

    subprocess.run([sys.executable, "-c", code], check=True, timeout=5)
