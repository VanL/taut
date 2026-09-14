"""Shared Markdown fenced-block exclusion for repository checkers."""

from __future__ import annotations

from collections.abc import Iterator


def prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield original line numbers and lines outside Markdown fences."""

    fence: tuple[str, int] | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        marker: tuple[str, int, str] | None = None
        leading_spaces = len(line) - len(line.lstrip(" "))
        stripped = line[leading_spaces:]
        if leading_spaces <= 3 and stripped.startswith(("```", "~~~")):
            character = stripped[0]
            length = len(stripped) - len(stripped.lstrip(character))
            marker = (character, length, stripped[length:])

        if fence is None and marker is not None:
            fence = marker[0], marker[1]
            continue
        if fence is not None:
            if (
                marker is not None
                and marker[0] == fence[0]
                and marker[1] >= fence[1]
                and not marker[2].strip()
            ):
                fence = None
            continue
        yield line_number, line
