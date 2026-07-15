"""Reference gate: documentation path claims and spec-code cites must resolve.

Guards against documentation drift. The scanner deliberately recognizes only
two concrete claim shapes:

1. Path claims in markdown sources — a markdown link target
   ``](docs/...)`` or a backtick-quoted path starting with ``docs/``,
   ``taut/``, ``tests/``, ``bin/``, or ``extensions/`` (charset
   ``[A-Za-z0-9_./-]``, at least one ``/``). A trailing ``:LINE`` or
   ``::qualname`` suffix is stripped before the existence check. Anything
   looser (globs, placeholders, ellipses) fails the charset or the
   whole-token match and is not a claim.
2. Citation claims — a bare bracketed ``[FAMILY-N]``/``[FAMILY-N.M]`` in
   prose. Local families resolve to headings in their registered spec file.
   External provenance families are allowed only in their registered source
   scope. Unknown concrete families fail. Wildcards plus inline/fenced code
   samples are examples, not claims.

Scanning rules:

- Maintained markdown sources include root/extension READMEs, root agent
  aliases, current agent context and runbooks, skills, specs, and
  implementation docs. Python citation sources include Taut, tests, and
  extensions.
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

# A path claim starts with one of the five owned top-level prefixes and uses
# a conservative charset; the prefix guarantees at least one "/".
_PATH_BODY = r"(?:docs|taut|tests|bin|extensions)/[A-Za-z0-9_./-]+"
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

CITATION_RE = re.compile(r"\[([A-Z][A-Z0-9]*)-(\d+(?:\.\d+)?)\]")
INLINE_CODE_RE = re.compile(r"(`+)(.*?)\1")

LOCAL_SPEC_FILES = {
    "DOM": REPO_ROOT
    / "docs"
    / "specs"
    / "01-development-documentation-operating-model.md",
    "TAUT": REPO_ROOT / "docs" / "specs" / "02-taut-core.md",
    "IAN": REPO_ROOT / "docs" / "specs" / "03-identity-addressing-notifications.md",
    "SUM": REPO_ROOT / "docs" / "specs" / "04-summon.md",
    "MCP": REPO_ROOT / "docs" / "specs" / "05-taut-mcp.md",
}

# These cite contracts copied from upstream projects. They are provenance,
# not headings Taut owns. Keep their source scope narrow so a new CC/SB cite in
# ordinary Taut prose cannot silently masquerade as a local requirement.
EXTERNAL_FAMILIES: dict[str, tuple[str, frozenset[Path]]] = {
    "CC": (
        "copied Weft multi-queue watcher contract",
        frozenset({Path("taut/watcher.py")}),
    ),
    "SB": (
        "copied SimpleBroker watcher/storage contract",
        frozenset({Path("taut/watcher.py")}),
    ),
}


def _markdown_path_sources() -> list[Path]:
    sources = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / "docs" / "README.md",
    ]
    sources += sorted((REPO_ROOT / "extensions").glob("*/README.md"))
    sources += sorted((REPO_ROOT / "docs" / "agent-context").glob("*.md"))
    sources += sorted((REPO_ROOT / "docs" / "agent-context" / "runbooks").glob("*.md"))
    sources += sorted((REPO_ROOT / "skills").glob("**/*.md"))
    sources += sorted((REPO_ROOT / "docs" / "implementation").glob("*.md"))
    sources += sorted((REPO_ROOT / "docs" / "specs").glob("*.md"))
    return list(dict.fromkeys(sources))


def _python_sources() -> list[Path]:
    sources = (
        sorted((REPO_ROOT / "taut").glob("**/*.py"))
        + sorted((REPO_ROOT / "tests").glob("**/*.py"))
        + sorted((REPO_ROOT / "extensions").glob("**/*.py"))
    )
    # This file contains deliberate invalid-citation fixtures that test the
    # scanner. They are executable examples, not repository contract claims.
    return [source for source in sources if source != Path(__file__)]


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


def _citation_codes(line: str) -> list[str]:
    """Return concrete prose citations after removing inline code samples."""

    prose = INLINE_CODE_RE.sub("", line)
    return [match.group(0) for match in CITATION_RE.finditer(prose)]


def _valid_local_codes() -> dict[str, frozenset[str]]:
    by_family: dict[str, frozenset[str]] = {}
    for family, spec in LOCAL_SPEC_FILES.items():
        assert spec.exists(), f"registered spec file is missing: {spec}"
        codes: set[str] = set()
        for line in spec.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                codes.update(_citation_codes(line))
        by_family[family] = frozenset(codes)
    return by_family


def _citation_failure(
    code: str,
    source: Path,
    valid_local: dict[str, frozenset[str]],
) -> str | None:
    match = CITATION_RE.fullmatch(code)
    assert match is not None
    family = match.group(1)
    if family in valid_local:
        return None if code in valid_local[family] else "unknown local code"
    if family in EXTERNAL_FAMILIES:
        _reason, allowed_sources = EXTERNAL_FAMILIES[family]
        return (
            None
            if source in allowed_sources
            else "external family outside allowed scope"
        )
    return "unregistered citation family"


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
    valid = _valid_local_codes()
    assert all(valid.values()), "a registered spec has no heading codes"
    failures: list[str] = []

    def _check(rel_source: Path, lineno: int, line: str) -> None:
        for code in _citation_codes(line):
            if code in ALLOWLIST:
                continue
            if reason := _citation_failure(code, rel_source, valid):
                failures.append(f"{rel_source}:{lineno}: {code}: {reason}")

    for source in _markdown_path_sources():
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
        "documentation or code contains an unregistered/out-of-scope citation "
        "(fix the cite, or add a reasoned ALLOWLIST entry):\n" + "\n".join(failures)
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("See [TAUT-3.4].", ["[TAUT-3.4]"]),
        ("Unknown concrete claim [XYZ-1].", ["[XYZ-1]"]),
        ("Placeholder [DOM-*].", []),
        ("Inline sample `[API-4]`.", []),
        ("Inline samples ``[ABC-2]`` and `[REF-4]`.", []),
    ],
)
def test_citation_claim_grammar(line: str, expected: list[str]) -> None:
    assert _citation_codes(line) == expected


def test_fenced_citation_samples_are_not_claims(tmp_path: Path) -> None:
    sample = tmp_path / "sample.md"
    sample.write_text(
        "Before [TAUT-1]\n```text\n[UNKNOWN-1]\n```\nAfter [IAN-1]\n",
        encoding="utf-8",
    )

    assert [
        code for _lineno, line in _prose_lines(sample) for code in _citation_codes(line)
    ] == ["[TAUT-1]", "[IAN-1]"]


def test_external_and_unknown_citation_classification() -> None:
    valid = _valid_local_codes()

    assert _citation_failure("[CC-2.1]", Path("taut/watcher.py"), valid) is None
    assert _citation_failure("[SB-0.4]", Path("taut/watcher.py"), valid) is None
    assert (
        _citation_failure("[CC-2.1]", Path("README.md"), valid)
        == "external family outside allowed scope"
    )
    assert (
        _citation_failure("[XYZ-1]", Path("README.md"), valid)
        == "unregistered citation family"
    )


def test_maintained_markdown_sources_cover_current_routing_surfaces() -> None:
    relative = {path.relative_to(REPO_ROOT) for path in _markdown_path_sources()}

    assert Path("README.md") in relative
    assert Path("extensions/taut_pg/README.md") in relative
    assert Path("extensions/taut_summon/README.md") in relative
    assert Path("docs/agent-context/runbooks/testing-patterns.md") in relative
    assert Path("skills/README.md") in relative
    assert (
        Path("docs/plans/2026-07-11-multi-factor-review-remediation-plan.md")
        not in relative
    )
    assert Path("CHANGELOG.md") not in relative
