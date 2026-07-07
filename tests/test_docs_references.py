"""Reference gate: documentation path claims and spec-code cites must resolve.

Guards against documentation drift (plan
2026-07-06-evaluation-findings-remediation-plan.md, S8/F14). The scanner is
deliberately dumb and matches only two recognized claim shapes:

1. Path claims in markdown sources — a markdown link target
   ``](docs/...)`` or a backtick-quoted path starting with ``docs/``,
   ``taut/``, ``tests/``, or ``bin/`` (charset ``[A-Za-z0-9_./-]``, at least
   one ``/``). A trailing ``:LINE`` or ``::qualname`` suffix is stripped
   before the existence check. Anything looser (globs, placeholders,
   ellipses) fails the charset or the whole-token match and is not a claim.
2. Spec-code claims — a bracketed ``[TAUT-N]``/``[TAUT-N.M]`` or
   ``[IAN-N]``/``[IAN-N.M]`` code, which must resolve to a heading in
   ``docs/specs/02-taut-core.md`` or
   ``docs/specs/03-identity-addressing-notifications.md``.

Scanning rules:

- Path-claim sources: ``docs/implementation/*.md``, ``docs/specs/*.md``,
  ``CLAUDE.md``, ``AGENTS.md``. Spec-code sources: ``taut/**/*.py``,
  ``tests/**/*.py``, ``docs/implementation/*.md``.
- ``docs/plans/`` files are never scanned as sources (immutable historical
  records), but a plan path referenced *from* a scanned source must exist.
- Fenced code blocks (``` ... ```) are skipped entirely in markdown
  sources — examples and command transcripts are not reference claims.
- A false positive is fixed by tightening the recognized-syntax rules or by
  adding a reasoned ALLOWLIST entry, never by weakening the assertion to a
  warning.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.sqlite_only

REPO_ROOT = Path(__file__).resolve().parent.parent

# Deliberate exceptions: path-or-code -> reason. Entries require a reason
# string; add only when a claim is intentionally unresolvable.
ALLOWLIST: dict[str, str] = {}

# A path claim starts with one of the four owned top-level prefixes and uses
# a conservative charset; the prefix guarantees at least one "/".
_PATH_BODY = r"(?:docs|taut|tests|bin)/[A-Za-z0-9_./-]+"
# Markdown link target: ](docs/...), optionally suffixed with ":123" (line
# number) — the suffix is stripped so a line-anchored link is still an
# existence claim, matching the backtick rule below. Targets with #anchors
# or other charsets do not match and are not treated as claims.
LINK_PATH_RE = re.compile(rf"\]\(({_PATH_BODY})(?::\d+)?\)")
# Backtick-quoted path, optionally suffixed with ":123" (line number) or
# "::qualname" (symbol reference); only the file path is capture group 1.
# The closing backtick anchors the whole token: globs and placeholders
# containing characters outside the charset never match.
BACKTICK_PATH_RE = re.compile(rf"`({_PATH_BODY})(?::\d+|::[A-Za-z0-9_.]+)?`")

SPEC_CODE_RE = re.compile(r"\[(?:TAUT|IAN)-\d+(?:\.\d+)?\]")

SPEC_FILES = (
    REPO_ROOT / "docs" / "specs" / "02-taut-core.md",
    REPO_ROOT / "docs" / "specs" / "03-identity-addressing-notifications.md",
)


def _markdown_path_sources() -> list[Path]:
    sources = sorted((REPO_ROOT / "docs" / "implementation").glob("*.md"))
    sources += sorted((REPO_ROOT / "docs" / "specs").glob("*.md"))
    sources += [REPO_ROOT / "CLAUDE.md", REPO_ROOT / "AGENTS.md"]
    return sources


def _python_sources() -> list[Path]:
    return sorted((REPO_ROOT / "taut").glob("**/*.py")) + sorted(
        (REPO_ROOT / "tests").glob("**/*.py")
    )


def _prose_lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (lineno, line) for *path*, skipping fenced code blocks."""

    in_fence = False
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield lineno, line


def _valid_spec_codes() -> frozenset[str]:
    codes: set[str] = set()
    for spec in SPEC_FILES:
        for line in spec.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                codes.update(SPEC_CODE_RE.findall(line))
    return frozenset(codes)


def test_documented_paths_exist() -> None:
    failures: list[str] = []
    for source in _markdown_path_sources():
        rel_source = source.relative_to(REPO_ROOT)
        for lineno, line in _prose_lines(source):
            claims = [
                match.group(1)
                for regex in (LINK_PATH_RE, BACKTICK_PATH_RE)
                for match in regex.finditer(line)
            ]
            for claim in claims:
                if claim in ALLOWLIST:
                    continue
                if not (REPO_ROOT / claim).exists():
                    failures.append(f"{rel_source}:{lineno}: {claim}")
    assert not failures, (
        "documentation references paths that do not exist "
        "(fix the doc, or tighten the recognized syntax in "
        "tests/test_docs_references.py, or add a reasoned ALLOWLIST entry):\n"
        + "\n".join(failures)
    )


def test_cited_spec_codes_resolve_to_spec_headings() -> None:
    valid = _valid_spec_codes()
    assert valid, "no spec codes found in spec headings; scanner is broken"
    failures: list[str] = []

    def _check(rel_source: Path, lineno: int, line: str) -> None:
        for code in SPEC_CODE_RE.findall(line):
            if code in ALLOWLIST:
                continue
            if code not in valid:
                failures.append(f"{rel_source}:{lineno}: {code}")

    for source in sorted((REPO_ROOT / "docs" / "implementation").glob("*.md")):
        rel_source = source.relative_to(REPO_ROOT)
        for lineno, line in _prose_lines(source):
            _check(rel_source, lineno, line)
    for source in _python_sources():
        rel_source = source.relative_to(REPO_ROOT)
        for lineno, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            _check(rel_source, lineno, line)

    assert not failures, (
        "cited spec codes do not resolve to a heading in the spec files "
        "(fix the cite, or add a reasoned ALLOWLIST entry):\n" + "\n".join(failures)
    )
