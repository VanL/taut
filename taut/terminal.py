"""Terminal-safe display transformation shared by core and extensions.

Spec references:
- docs/specs/02-taut-core.md [TAUT-6.4], [TAUT-8.3], [TAUT-8.6], [TAUT-9]
"""

from __future__ import annotations

import heapq
import re
import tomllib
from collections.abc import Iterable, Iterator
from functools import lru_cache
from importlib import resources
from io import StringIO
from pathlib import Path
from stat import S_ISREG
from typing import Any, Final

from taut._constants import PROJECT_CONFIG_NAME

_POLICY_ERROR_MESSAGE: Final[str] = "terminal output policy is unavailable"
_SHORT_ESCAPES: Final[dict[int, str]] = {
    0x07: r"\a",
    0x08: r"\b",
    0x09: r"\t",
    0x0A: r"\n",
    0x0B: r"\v",
    0x0C: r"\f",
    0x0D: r"\r",
}

_MatchIterator = Iterator[re.Match[str]]
_SpanHeapItem = tuple[int, int, int, bool, _MatchIterator]


class _ProjectConfigSyntaxError(RuntimeError):
    """Fixed-message policy failure that still belongs to `.taut.toml`."""

    _taut_project_config_syntax = True


def escape_terminal_text(
    text: str,
    *,
    additional_patterns: Iterable[str] = (),
    inherit_defaults: bool = True,
) -> str:
    """Render text using inherited project policy plus explicit regexes.

    ``inherit_defaults=False`` bypasses both CWD project discovery and the
    packaged policy, leaving only ``additional_patterns``.
    """

    extra_sources = _normalize_additional_patterns(additional_patterns)
    policy_patterns = _compiled_effective_policy() if inherit_defaults else ()
    extra_patterns = _compile_patterns(extra_sources)
    patterns = (
        *((pattern, True) for pattern in policy_patterns),
        *((pattern, False) for pattern in extra_patterns),
    )
    if not patterns:
        return text

    heap: list[_SpanHeapItem] = []
    for index, (pattern, policy_owned) in enumerate(patterns):
        iterator = pattern.finditer(text)
        _push_next_span(heap, index, policy_owned, iterator)
    if not heap:
        return text

    output = StringIO()
    source_cursor = 0
    merged_start: int | None = None
    merged_end = 0

    while heap:
        start, end, index, policy_owned, iterator = heapq.heappop(heap)
        _push_next_span(heap, index, policy_owned, iterator)
        if merged_start is None:
            merged_start = start
            merged_end = end
            continue
        if start <= merged_end:
            merged_end = max(merged_end, end)
            continue
        output.write(text[source_cursor:merged_start])
        _write_escaped(output, text[merged_start:merged_end])
        source_cursor = merged_end
        merged_start = start
        merged_end = end

    assert merged_start is not None
    output.write(text[source_cursor:merged_start])
    _write_escaped(output, text[merged_start:merged_end])
    output.write(text[merged_end:])
    return output.getvalue()


def _normalize_additional_patterns(patterns: Iterable[str]) -> tuple[str, ...]:
    if isinstance(patterns, str):
        raise TypeError("additional_patterns must be an iterable of strings")
    try:
        normalized = tuple(patterns)
    except TypeError as exc:
        raise TypeError("additional_patterns must be an iterable of strings") from exc
    if any(not isinstance(pattern, str) for pattern in normalized):
        raise TypeError("additional_patterns must contain only strings")
    return normalized


@lru_cache(maxsize=1)
def _default_pattern_sources() -> tuple[str, ...]:
    try:
        with resources.files("taut").joinpath("defaults.toml").open("rb") as stream:
            document: dict[str, Any] = tomllib.load(stream)
        section = document["terminal_text"]
        patterns = section["escape_patterns"]
        if not isinstance(section, dict) or not isinstance(patterns, list):
            raise TypeError
        if any(not isinstance(pattern, str) for pattern in patterns):
            raise TypeError
        return tuple(patterns)
    except (KeyError, OSError, TypeError, UnicodeError, tomllib.TOMLDecodeError):
        raise RuntimeError(_POLICY_ERROR_MESSAGE) from None


@lru_cache(maxsize=1)
def _compiled_default_patterns() -> tuple[re.Pattern[str], ...]:
    try:
        return _compile_patterns(_default_pattern_sources())
    except ValueError:
        raise RuntimeError(_POLICY_ERROR_MESSAGE) from None


def _compiled_effective_policy() -> tuple[re.Pattern[str], ...]:
    try:
        starting_dir = Path.cwd().resolve()
    except OSError:
        raise RuntimeError(_POLICY_ERROR_MESSAGE) from None
    inherit_packaged, project_sources = _project_policy_sources(starting_dir)
    packaged = _compiled_default_patterns() if inherit_packaged else ()
    try:
        project = _compile_patterns(project_sources)
    except ValueError:
        raise RuntimeError(_POLICY_ERROR_MESSAGE) from None
    return (*packaged, *project)


def _project_policy_sources(starting_dir: Path) -> tuple[bool, tuple[str, ...]]:
    config_path = _find_project_config(starting_dir)
    if config_path is None:
        return True, ()
    try:
        metadata = config_path.stat()
    except OSError:
        raise RuntimeError(_POLICY_ERROR_MESSAGE) from None
    return _load_project_policy(
        config_path,
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mtime_ns,
        metadata.st_size,
    )


@lru_cache(maxsize=128)
def _load_project_policy(
    config_path: Path,
    _device: int,
    _inode: int,
    _modified_ns: int,
    _size: int,
) -> tuple[bool, tuple[str, ...]]:
    try:
        with config_path.open("rb") as stream:
            document: dict[str, Any] = tomllib.load(stream)
        section = document.get("terminal_text")
        if section is None:
            return True, ()
        if not isinstance(section, dict):
            raise TypeError
        inherit_defaults = section.get("inherit_defaults", True)
        patterns = section.get("escape_patterns", [])
        if not isinstance(inherit_defaults, bool) or not isinstance(patterns, list):
            raise TypeError
        if any(not isinstance(pattern, str) for pattern in patterns):
            raise TypeError
        return inherit_defaults, tuple(patterns)
    except tomllib.TOMLDecodeError:
        raise _ProjectConfigSyntaxError(_POLICY_ERROR_MESSAGE) from None
    except (OSError, TypeError, UnicodeError):
        raise RuntimeError(_POLICY_ERROR_MESSAGE) from None


def _find_project_config(starting_dir: Path) -> Path | None:
    current = starting_dir
    while True:
        candidate = current / PROJECT_CONFIG_NAME
        try:
            metadata = candidate.stat()
        except FileNotFoundError:
            pass
        except OSError:
            raise RuntimeError(_POLICY_ERROR_MESSAGE) from None
        else:
            if S_ISREG(metadata.st_mode):
                return candidate
        if current.parent == current:
            return None
        current = current.parent


@lru_cache(maxsize=128)
def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    try:
        return tuple(re.compile(pattern) for pattern in patterns)
    except re.error as exc:
        raise ValueError(f"invalid terminal escape pattern: {exc}") from exc


def _push_next_span(
    heap: list[_SpanHeapItem],
    index: int,
    policy_owned: bool,
    iterator: _MatchIterator,
) -> None:
    try:
        match = next(iterator)
    except StopIteration:
        return
    start, end = match.span()
    if start == end:
        if policy_owned:
            raise RuntimeError(_POLICY_ERROR_MESSAGE)
        raise ValueError("terminal escape patterns must not match empty text")
    heapq.heappush(heap, (start, end, index, policy_owned, iterator))


def _write_escaped(output: StringIO, value: str) -> None:
    for character in value:
        code_point = ord(character)
        short = _SHORT_ESCAPES.get(code_point)
        if short is not None:
            output.write(short)
        elif code_point <= 0xFF:
            output.write(f"\\x{code_point:02x}")
        elif code_point <= 0xFFFF:
            output.write(f"\\u{code_point:04x}")
        else:
            output.write(f"\\U{code_point:08x}")


__all__ = ["escape_terminal_text"]
