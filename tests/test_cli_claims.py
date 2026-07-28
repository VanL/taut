"""Documentation gate for executable Taut CLI path claims.

Spec reference: docs/specs/01-development-documentation-operating-model.md
[DOM-10.1].
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import TypeAlias

import pytest

pytestmark = pytest.mark.sqlite_only

REPO_ROOT = Path(__file__).resolve().parent.parent
CommandPath: TypeAlias = tuple[str, ...]
ExemptionKey: TypeAlias = tuple[Path, CommandPath]

# Intentionally unimplemented lifecycle examples in the active core spec.
# Exact source/path keys prevent a broad allowance from hiding unrelated drift.
EXEMPTIONS: dict[ExemptionKey, str] = {
    (Path("docs/specs/01-development-documentation-operating-model.md"), ("...",)): (
        "Metasyntactic invalid-command example defining the claim grammar."
    ),
    (Path("docs/specs/02-taut-core.md"), ("channel", "close")): (
        "Possible future channel lifecycle command; not version 0.8.0 behavior."
    ),
    (Path("docs/specs/02-taut-core.md"), ("channel", "reopen")): (
        "Possible future channel lifecycle command; not version 0.8.0 behavior."
    ),
    (Path("docs/specs/02-taut-core.md"), ("COMMAND",)): (
        "Metasyntactic command placeholder in root dispatch documentation."
    ),
}

_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_SHELL_BREAKS = frozenset({"|", "||", "&", "&&", ";"})


@dataclass(frozen=True, slots=True)
class CommandClaim:
    """One shell-like invocation extracted from maintained Markdown."""

    source: Path
    line: int
    tokens: tuple[str, ...]


def _markdown_sources(root: Path) -> list[Path]:
    """Return the exact maintained Markdown source set from [DOM-10.1]."""

    sources = [
        root / "README.md",
        root / "AGENTS.md",
        root / "CLAUDE.md",
        root / "docs" / "README.md",
        root / "docs" / "coalescing.md",
        root / "docs" / "plans" / "README.md",
    ]
    sources += sorted((root / "extensions").glob("*/README.md"))
    sources += sorted((root / "docs" / "agent-context").glob("*.md"))
    sources += sorted((root / "docs" / "agent-context" / "runbooks").glob("*.md"))
    sources += sorted((root / "skills").glob("**/*.md"))
    sources += sorted((root / "docs" / "implementation").glob("*.md"))
    sources += sorted((root / "docs" / "specs").glob("*.md"))
    return [
        source
        for source in dict.fromkeys(sources)
        if source.is_file()
        and source != root / "CHANGELOG.md"
        and source != root / "docs" / "lessons.md"
        and (source.parent != root / "docs" / "plans" or source.name == "README.md")
    ]


def _shell_claim_tokens(fragment: str) -> tuple[list[tuple[str, ...]], str | None]:
    """Tokenize the Taut invocations in one inline/fenced shell fragment."""

    if re.search(r"(?<![\w-])taut(?=$|[\s;|&])", fragment) is None:
        return [], None
    if fragment.rstrip().endswith("\\"):
        fragment = fragment.rstrip()[:-1]
    try:
        lexer = shlex.shlex(fragment, posix=True, punctuation_chars="|;&")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError as exc:
        return [], f"malformed shell-like claim: {exc}"

    claims: list[tuple[str, ...]] = []
    for index, token in enumerate(tokens):
        if token != "taut":
            continue
        segment_start = index
        while segment_start > 0 and tokens[segment_start - 1] not in _SHELL_BREAKS:
            segment_start -= 1
        prefix = tokens[segment_start:index]
        while prefix and (
            prefix[0] in {"$", ">"}
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", prefix[0]) is not None
        ):
            prefix = prefix[1:]
        if prefix in (["uv", "run"], ["exec"], ["do"], ["then"]):
            prefix = []
        if prefix:
            continue
        tail: list[str] = ["taut"]
        for candidate in tokens[index + 1 :]:
            if candidate in _SHELL_BREAKS:
                break
            tail.append(candidate)
        # A bare inline ``taut`` is a package/program name, not a path claim.
        if len(tail) > 1:
            claims.append(tuple(tail))
    return claims, None


def _extract_claims(
    source: Path,
    *,
    root: Path,
) -> tuple[list[CommandClaim], list[str]]:
    """Extract inline and fenced invocations, containing per-file failures."""

    relative = source.relative_to(root)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        return [], [f"{relative}:1: source is not valid UTF-8: {exc}"]

    claims: list[CommandClaim] = []
    failures: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for lineno, line in enumerate(lines, start=1):
        fence = _FENCE_RE.match(line)
        if fence is not None:
            delimiter = fence.group(1)
            if fence_character is None:
                fence_character = delimiter[0]
                fence_length = len(delimiter)
                continue
            if delimiter[0] == fence_character and len(delimiter) >= fence_length:
                fence_character = None
                fence_length = 0
                continue
        fragments = (
            [line]
            if fence_character is not None
            else [match.group(2) for match in _INLINE_CODE_RE.finditer(line)]
        )
        for fragment in fragments:
            extracted, failure = _shell_claim_tokens(fragment)
            if failure is not None:
                failures.append(f"{relative}:{lineno}: {failure}")
                continue
            claims.extend(
                CommandClaim(source=relative, line=lineno, tokens=tokens)
                for tokens in extracted
            )
    return claims, failures


def _required_nested_operations(
    parser: argparse.ArgumentParser,
) -> frozenset[str] | None:
    """Return required first-level operations from configured adapter structure."""

    actions = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    required = [action for action in actions if action.required]
    if not required:
        return None
    if len(required) != 1:
        raise RuntimeError("core adapter has multiple required nested parser groups")
    return frozenset(required[0].choices)


def _core_command_grammar() -> dict[str, frozenset[str] | None]:
    """Derive current paths from the deterministic registry and adapter parsers."""

    from taut.commands._imports import resolve_import_target
    from taut.commands._protocol import CommandArgumentParser
    from taut.commands._registry import CommandRegistry

    grammar: dict[str, frozenset[str] | None] = {}
    for registered in CommandRegistry(entry_points=()).commands():
        if registered.spec is None:
            raise RuntimeError(f"static command {registered.name!r} is unavailable")
        if not registered.builtin:
            # Reserved first-party compatibility manifests are valid top-level
            # claims. Their tails are owned by the extension bridge.
            grammar[registered.name] = None
            continue
        factory = resolve_import_target(registered.spec.implementation)
        command = factory()
        parser = CommandArgumentParser(
            prog=f"taut {registered.name}",
            stdout=StringIO(),
            stderr=StringIO(),
        )
        command.configure_parser(parser)
        grammar[registered.name] = _required_nested_operations(parser)
    return grammar


def _claim_path(
    claim: CommandClaim,
    grammar: dict[str, frozenset[str] | None],
) -> tuple[CommandPath, str | None]:
    """Classify one claim with dispatcher-owned root/global token handling."""

    from taut.commands._dispatch import _extract_post_globals, _split_root, _UsageError
    from taut.commands._registry import CommandRegistry

    try:
        _root, verb, tail, action, literal_tail = _split_root(list(claim.tokens[1:]))
    except _UsageError as exc:
        return (), f"malformed root command: {exc}"
    if action is not None or verb is None:
        return (), None
    path: CommandPath = (verb,)
    if verb not in grammar:
        return path, "unknown top-level command"
    operations = grammar[verb]
    if operations is None:
        return path, None

    spec = CommandRegistry(entry_points=()).get(verb).spec
    assert spec is not None
    if literal_tail:
        remaining = tail
    else:
        try:
            remaining, _globals = _extract_post_globals(tail, spec)
        except _UsageError as exc:
            return path, f"malformed command globals: {exc}"
        if remaining and remaining[0] == "--":
            remaining = remaining[1:]
    if not remaining:
        return path, "required nested operation is missing"
    operation = remaining[0]
    path = (verb, operation)
    if operation not in operations:
        return path, "unknown operation for nested core command"
    return path, None


def _validate_sources(
    root: Path,
    *,
    sources: list[Path],
    exemptions: dict[ExemptionKey, str],
) -> tuple[list[str], int]:
    """Validate claims and exemption hygiene through one deterministic grammar."""

    grammar = _core_command_grammar()
    failures: list[str] = []
    claims: list[CommandClaim] = []
    for source in sources:
        extracted, extraction_failures = _extract_claims(source, root=root)
        claims.extend(extracted)
        failures.extend(extraction_failures)

    matched_exemptions: set[ExemptionKey] = set()
    for claim in claims:
        path, reason = _claim_path(claim, grammar)
        if not path:
            if reason is not None:
                failures.append(f"{claim.source}:{claim.line}: taut: {reason}")
            continue
        key = (claim.source, path)
        if key in exemptions:
            matched_exemptions.add(key)
            exemption_reason = exemptions[key]
            if not exemption_reason.strip():
                failures.append(
                    f"{claim.source}:{claim.line}: taut {' '.join(path)}: "
                    "exemption requires a non-empty reason"
                )
                continue
            if reason is None:
                failures.append(
                    f"{claim.source}:{claim.line}: taut {' '.join(path)}: "
                    "exemption is stale because this path now resolves"
                )
                continue
            continue
        if reason is not None:
            failures.append(
                f"{claim.source}:{claim.line}: taut {' '.join(path)}: {reason}"
            )

    for key, exemption_reason in exemptions.items():
        source, path = key
        if not exemption_reason.strip() and key not in matched_exemptions:
            failures.append(
                f"{source}:1: taut {' '.join(path)}: exemption requires a "
                "non-empty reason"
            )
        elif key not in matched_exemptions:
            failures.append(
                f"{source}:1: taut {' '.join(path)}: exemption matches no claim"
            )
    return failures, len(claims)


def test_markdown_sources_match_the_maintained_contract() -> None:
    relative = {path.relative_to(REPO_ROOT) for path in _markdown_sources(REPO_ROOT)}

    assert Path("README.md") in relative
    assert Path("AGENTS.md") in relative
    assert Path("CLAUDE.md") in relative
    assert Path("docs/README.md") in relative
    assert Path("docs/coalescing.md") in relative
    assert Path("docs/plans/README.md") in relative
    assert Path("extensions/taut_pg/README.md") in relative
    assert Path("docs/agent-context/runbooks/testing-patterns.md") in relative
    assert Path("skills/README.md") in relative
    assert Path("docs/implementation/04-taut-architecture.md") in relative
    assert Path("docs/specs/02-taut-core.md") in relative
    assert Path("CHANGELOG.md") not in relative
    assert Path("docs/lessons.md") not in relative
    assert Path("docs/plans/2026-07-28-channel-topics-plan.md") not in relative


def test_extracts_inline_and_fenced_shell_like_claims(tmp_path: Path) -> None:
    source = tmp_path / "claims.md"
    source.write_text(
        "\n".join(
            (
                "Use `taut channel show dev` or ``TAUT_TOKEN=x taut say dev hi``.",
                "The package name `taut` and prose saying taut channel are inert.",
                "```bash",
                "$ taut --db ./chat.db channel topic dev focus",
                "make test 2>&1 | taut say ci -",
                "```",
                "~~~console",
                "> taut message show 1800000000000000001",
                "~~~",
                "",
            )
        ),
        encoding="utf-8",
    )

    claims, failures = _extract_claims(source, root=tmp_path)

    assert failures == []
    assert [(claim.line, claim.tokens) for claim in claims] == [
        (1, ("taut", "channel", "show", "dev")),
        (1, ("taut", "say", "dev", "hi")),
        (4, ("taut", "--db", "./chat.db", "channel", "topic", "dev", "focus")),
        (5, ("taut", "say", "ci", "-")),
        (8, ("taut", "message", "show", "1800000000000000001")),
    ]


def test_registry_grammar_derives_required_nested_operations_without_clients() -> None:
    grammar = _core_command_grammar()

    assert grammar["say"] is None
    assert grammar["summon"] is None
    assert grammar["dismiss"] is None
    assert grammar["message"] == frozenset({"show", "delete", "react"})
    assert grammar["channel"] == frozenset({"show", "topic", "rename"})
    assert "rename" not in grammar


@pytest.mark.parametrize(
    ("body", "path", "reason"),
    [
        ("`taut rename old new`", "taut rename", "unknown top-level command"),
        ("`taut channel archive dev`", "taut channel archive", "unknown operation"),
        ("`taut channel`", "taut channel", "required nested operation"),
        ("`taut message --json`", "taut message", "required nested operation"),
    ],
)
def test_stale_and_missing_command_paths_fail_with_source_and_line(
    tmp_path: Path,
    body: str,
    path: str,
    reason: str,
) -> None:
    source = tmp_path / "README.md"
    source.write_text(f"heading\n{body}\n", encoding="utf-8")

    failures, _claim_count = _validate_sources(
        tmp_path,
        sources=[source],
        exemptions={},
    )

    assert len(failures) == 1
    assert failures[0].startswith("README.md:2:")
    assert path in failures[0]
    assert reason in failures[0]


def test_prompt_env_root_global_and_pipeline_forms_validate(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    source.write_text(
        "\n".join(
            (
                "`$ taut --json channel show dev`",
                "`TAUT_TOKEN=secret taut message --quiet show 1800000000000000001`",
                "`taut -- channel show dev`",
                "`taut channel -- show dev`",
                "```sh",
                "uv run taut --db chat.db list --all | jq .",
                "```",
                "",
            )
        ),
        encoding="utf-8",
    )

    failures, claim_count = _validate_sources(
        tmp_path,
        sources=[source],
        exemptions={},
    )

    assert failures == []
    assert claim_count == 5


def test_double_literal_separator_does_not_hide_invalid_nested_operation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "README.md"
    source.write_text("`taut -- channel -- show dev`\n", encoding="utf-8")

    failures, claim_count = _validate_sources(
        tmp_path,
        sources=[source],
        exemptions={},
    )

    assert claim_count == 1
    assert len(failures) == 1
    assert "taut channel --" in failures[0]
    assert "unknown operation" in failures[0]


def test_future_exemption_is_exact_reasoned_and_source_scoped(tmp_path: Path) -> None:
    source = tmp_path / "docs" / "specs" / "02-taut-core.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "`taut channel close dev`\n`taut channel reopen dev`\n",
        encoding="utf-8",
    )
    exemptions: dict[ExemptionKey, str] = {
        (Path("docs/specs/02-taut-core.md"), ("channel", "close")): (
            "Possible future lifecycle command."
        ),
        (Path("docs/specs/02-taut-core.md"), ("channel", "reopen")): (
            "Possible future lifecycle command."
        ),
    }

    failures, claim_count = _validate_sources(
        tmp_path,
        sources=[source],
        exemptions=exemptions,
    )

    assert failures == []
    assert claim_count == 2

    wrong_source = tmp_path / "README.md"
    wrong_source.write_text("`taut channel close dev`\n", encoding="utf-8")
    failures, _ = _validate_sources(
        tmp_path,
        sources=[wrong_source],
        exemptions=exemptions,
    )
    assert any("unknown operation" in failure for failure in failures)


def test_external_extension_claim_uses_an_exact_source_exemption(
    tmp_path: Path,
) -> None:
    source = tmp_path / "extensions" / "fixture" / "README.md"
    source.parent.mkdir(parents=True)
    source.write_text("`taut deploy production`\n", encoding="utf-8")
    exemptions: dict[ExemptionKey, str] = {
        (Path("extensions/fixture/README.md"), ("deploy",)): (
            "Command is owned by the documented fixture extension."
        )
    }

    failures, claim_count = _validate_sources(
        tmp_path,
        sources=[source],
        exemptions=exemptions,
    )

    assert failures == []
    assert claim_count == 1


def test_stale_empty_and_unmatched_exemptions_fail(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    source.write_text("`taut channel show dev`\n", encoding="utf-8")

    failures, _ = _validate_sources(
        tmp_path,
        sources=[source],
        exemptions={
            (Path("README.md"), ("channel", "show")): "was once future",
            (Path("README.md"), ("channel", "close")): "",
            (Path("README.md"), ("channel", "reopen")): "claim was removed",
        },
    )

    assert any("now resolves" in failure for failure in failures)
    assert any("non-empty reason" in failure for failure in failures)
    assert any("matches no claim" in failure for failure in failures)


def test_non_utf8_source_is_one_diagnostic_and_other_sources_continue(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "README.md"
    bad.write_bytes(b"\xff")
    good = tmp_path / "AGENTS.md"
    good.write_text("`taut rename old new`\n", encoding="utf-8")

    failures, claim_count = _validate_sources(
        tmp_path,
        sources=[bad, good],
        exemptions={},
    )

    assert claim_count == 1
    assert any(
        "README.md:1" in failure and "valid UTF-8" in failure for failure in failures
    )
    assert any(
        "AGENTS.md:1" in failure and "taut rename" in failure for failure in failures
    )


def test_repository_cli_claims_are_current() -> None:
    failures, claim_count = _validate_sources(
        REPO_ROOT,
        sources=_markdown_sources(REPO_ROOT),
        exemptions=EXEMPTIONS,
    )

    assert claim_count > 0
    assert not failures, "stale documentation command claims:\n" + "\n".join(failures)


def test_bin_entry_point_exit_classes(tmp_path: Path) -> None:
    checker = REPO_ROOT / "bin" / "check-cli-claims"
    readme = tmp_path / "README.md"
    readme.write_text("`taut channel show dev`\n", encoding="utf-8")

    clean = subprocess.run(
        [sys.executable, str(checker), "--root", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert clean.returncode == 0
    assert "1 command claim(s)" in clean.stdout

    readme.write_text("`taut rename old new`\n", encoding="utf-8")
    stale = subprocess.run(
        [sys.executable, str(checker), "--root", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale.returncode == 1
    assert "README.md:1" in stale.stdout
    assert "taut rename" in stale.stdout
    assert "Traceback" not in stale.stdout + stale.stderr

    missing = subprocess.run(
        [sys.executable, str(checker), "--root", str(tmp_path / "missing")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2
    assert "does not exist" in missing.stdout
    assert "Traceback" not in missing.stdout + missing.stderr
