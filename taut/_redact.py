"""Value-only credential redaction for rendered diagnostic text.

The helper is deliberately text-in/text-out. Debug capture owns when it runs;
this module owns only the immutable rule manifest and span replacement.

Spec reference: docs/specs/02-taut-core.md [TAUT-13.3.1].
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

_REDACTION = "<redacted>"

_CREDENTIAL_LABEL = (
    r"(?:access[_-]?key|api[_-]?key|auth[_-]?key|authorization|"
    r"client[_-]?secret|credential|credentials|encryption[_-]?key|"
    r"password|passwd|private[_-]?key|pwd|secret|secret[_-]?key|"
    r"access[_-]?token|api[_-]?token|auth[_-]?token|"
    r"[A-Za-z][A-Za-z0-9_-]*(?:_access_key|_api_key|_auth_key|"
    r"_authorization|_client_secret|_credential|_credentials|"
    r"_encryption_key|_password|_passwd|_private_key|_pwd|_secret|"
    r"_secret_key|_access_token|_api_token|_auth_token)|"
    r"(?-i:[A-Za-z][A-Za-z0-9]*(?:AccessKey|ApiKey|AuthKey|Authorization|"
    r"ClientSecret|Credential|Credentials|EncryptionKey|Password|Passwd|"
    r"PrivateKey|Pwd|SecretKey|Secret|AccessToken|ApiToken|AuthToken)))"
)
_JSON_ESCAPED_QUOTE = re.escape('\\"')
_JSON_EMBEDDED_QUOTE = re.escape('\\\\\\"')
_JSON_ESCAPED_BACKSLASH = re.escape("\\\\")
_JSON_ESCAPED_CHARACTER_WITHOUT_QUOTE = r"\\(?:[/bfnrt]|u[0-9A-Fa-f]{4})"
_JSON_ESCAPED_VALUE_ATOM = (
    rf"(?:{_JSON_EMBEDDED_QUOTE}|{_JSON_ESCAPED_BACKSLASH}|"
    rf"{_JSON_ESCAPED_CHARACTER_WITHOUT_QUOTE}|[^\\\"])"
)
_JSON_NEWLINE = re.escape("\\n")
_JSON_CARRIAGE_RETURN = re.escape("\\r")
_REPR_EMBEDDED_SINGLE_QUOTE = re.escape("\\\\'")


@dataclass(frozen=True, slots=True)
class _Rule:
    id: str
    pattern: str
    secret_group: int
    flags: int = 0


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    rule: _Rule
    regex: re.Pattern[str]


_RULES = (
    _Rule(
        id="labeled_json_direct",
        pattern=(
            rf"\"{_CREDENTIAL_LABEL}\"\s*:\s*\""
            r"((?:\\.|[^\"\\])*)\""
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    _Rule(
        id="labeled_double_quoted",
        pattern=(
            rf"(?<![A-Za-z0-9_-]){_CREDENTIAL_LABEL}\s*[:=]\s*\""
            r"((?:\\.|[^\"\\])*)\""
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    _Rule(
        id="labeled_single_quoted",
        pattern=(
            rf"(?<![A-Za-z0-9_-]){_CREDENTIAL_LABEL}\s*[:=]\s*'"
            r"((?:\\.|[^'\\])*)'"
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    _Rule(
        id="labeled_unquoted",
        pattern=(
            rf"(?<![A-Za-z0-9_-]){_CREDENTIAL_LABEL}\s*[:=]\s*"
            r"(?!\\*[\"']|(?:Basic|Bearer)\s+)"
            r"(?:((?:\\.|[^\s,;}\]\"'&\\])+))"
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    _Rule(
        id="labeled_json_escaped",
        pattern=(
            rf"{_JSON_ESCAPED_QUOTE}{_CREDENTIAL_LABEL}{_JSON_ESCAPED_QUOTE}"
            rf"\s*:\s*{_JSON_ESCAPED_QUOTE}"
            rf"({_JSON_ESCAPED_VALUE_ATOM}*)"
            rf"{_JSON_ESCAPED_QUOTE}"
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    _Rule(
        id="labeled_json_escaped_assignment",
        pattern=(
            rf"(?<![A-Za-z0-9_-]){_CREDENTIAL_LABEL}\s*[:=]\s*"
            rf"{_JSON_ESCAPED_QUOTE}"
            rf"({_JSON_ESCAPED_VALUE_ATOM}*)"
            rf"{_JSON_ESCAPED_QUOTE}"
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    _Rule(
        id="labeled_repr_single_quoted",
        pattern=(
            rf"'{_CREDENTIAL_LABEL}'\s*:\s*'"
            rf"((?:{_REPR_EMBEDDED_SINGLE_QUOTE}|[^'])*)'"
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    _Rule(
        id="authorization_scheme",
        pattern=(
            r"(?<![A-Za-z0-9_-])Authorization\s*:\s*(?:Basic|Bearer)\s+"
            r"((?:\\.|[^\s,;\"'\\])+)"
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    # Adapted from mm's PostgreSQL/MongoDB/Redis/RabbitMQ/FTP detectors, but
    # narrowed to the user-info password so scheme, user, host, and path remain.
    _Rule(
        id="credentialed_uri",
        pattern=(
            r"\b(?:postgres(?:ql)?|mongodb(?:\+srv)?|rediss?|amqps?|ftp)://"
            r"[^/\s:@]*:([^@\s/]+)@"
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    # Keep the PEM type and begin/end lines; only the encoded body is secret.
    _Rule(
        id="private_key_pem_body",
        pattern=(
            r"-----BEGIN[ A-Z0-9_-]*PRIVATE KEY-----\r?\n"
            r"([A-Za-z0-9+/=_-]+(?:\r?\n[A-Za-z0-9+/=_-]+)*)\r?\n"
            r"(?=-----END[ A-Z0-9_-]*PRIVATE KEY-----)"
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
    _Rule(
        id="private_key_pem_body_json",
        pattern=(
            rf"-----BEGIN[ A-Z0-9_-]*PRIVATE KEY-----"
            rf"(?:{_JSON_CARRIAGE_RETURN})?{_JSON_NEWLINE}"
            rf"([A-Za-z0-9+/=_-]+(?:(?:{_JSON_CARRIAGE_RETURN})?"
            rf"{_JSON_NEWLINE}[A-Za-z0-9+/=_-]+)*)"
            rf"(?:{_JSON_CARRIAGE_RETURN})?{_JSON_NEWLINE}"
            rf"(?=-----END[ A-Z0-9_-]*PRIVATE KEY-----)"
        ),
        secret_group=1,
        flags=re.IGNORECASE,
    ),
)


@cache
def _compiled_rules() -> tuple[_CompiledRule, ...]:
    compiled: list[_CompiledRule] = []
    for rule in _RULES:
        regex = re.compile(rule.pattern, rule.flags)
        if rule.secret_group > regex.groups:
            raise ValueError(
                f"redaction rule {rule.id!r} references missing group "
                f"{rule.secret_group}"
            )
        compiled.append(_CompiledRule(rule=rule, regex=regex))
    return tuple(compiled)


def redact_sensitive_text(text: str) -> str:
    """Replace recognized credential-value spans while preserving context."""

    spans: list[tuple[int, int]] = []
    for compiled in _compiled_rules():
        for match in compiled.regex.finditer(text):
            start, end = match.span(compiled.rule.secret_group)
            if start >= 0 and end > start:
                spans.append((start, end))
    if not spans:
        return text

    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))

    redacted = text
    for start, end in reversed(merged):
        redacted = redacted[:start] + _REDACTION + redacted[end:]
    return redacted


__all__ = ["redact_sensitive_text"]
