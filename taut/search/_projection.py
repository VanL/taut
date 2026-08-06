"""Backend-neutral query chunks and UTF-8-safe source segmentation."""

from __future__ import annotations

MAX_QUERY_CHUNKS = 256


def query_chunks(query: str) -> tuple[str, ...]:
    """Return distinct case-folded alphanumeric chunks in first-seen order."""

    if not isinstance(query, str):
        raise TypeError("search query must be a string")
    chunks = _distinct_chunks(query)
    if not chunks:
        raise ValueError("search query must contain at least one alphanumeric token")
    if len(chunks) > MAX_QUERY_CHUNKS:
        raise ValueError("search query must contain at most 256 distinct query chunks")
    return chunks


def projection_segments(text: str, *, max_segment_bytes: int) -> tuple[str, ...]:
    """Return the source's canonical Unicode chunks packed into segments.

    A single chunk larger than the preferred segment size remains intact. This
    keeps segmentation from inventing tokens. PostgreSQL may omit an oversized
    lexeme under its pinned analyzer contract, while the document still indexes.
    """

    if not isinstance(text, str):
        raise TypeError("search projection text must be a string")
    _validate_segment_bound(max_segment_bytes)
    chunks = _distinct_chunks(text)
    if not chunks:
        return ("",)

    segments: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for chunk in chunks:
        chunk_bytes = len(chunk.encode("utf-8"))
        separator_bytes = 1 if current else 0
        if (
            current
            and current_bytes + separator_bytes + chunk_bytes > max_segment_bytes
        ):
            segments.append(" ".join(current))
            current = []
            current_bytes = 0
            separator_bytes = 0
        current.append(chunk)
        current_bytes += separator_bytes + chunk_bytes
    if current:
        segments.append(" ".join(current))
    return tuple(segments)


def _distinct_chunks(text: str) -> tuple[str, ...]:
    chunks: list[str] = []
    seen: set[str] = set()
    current: list[str] = []
    for character in text.casefold():
        if character.isalnum():
            current.append(character)
            continue
        _append_chunk(current, chunks, seen)
    _append_chunk(current, chunks, seen)
    return tuple(chunks)


def segment_text(text: str, *, max_segment_bytes: int) -> tuple[str, ...]:
    """Partition text without splitting a UTF-8 code point.

    Separator boundaries are preferred when one occurs before the byte limit.
    A limit of four bytes is the smallest value that can contain every Unicode
    code point encoded as UTF-8.
    """

    if not isinstance(text, str):
        raise TypeError("search projection text must be a string")
    _validate_segment_bound(max_segment_bytes)
    if not text:
        return ("",)

    segments: list[str] = []
    start = 0
    while start < len(text):
        cut = _next_segment_end(text, start, max_segment_bytes)
        segments.append(text[start:cut])
        start = cut
    return tuple(segments)


def _validate_segment_bound(max_segment_bytes: int) -> None:
    if isinstance(max_segment_bytes, bool) or not isinstance(max_segment_bytes, int):
        raise TypeError("max_segment_bytes must be an integer")
    if max_segment_bytes < 4:
        raise ValueError("max_segment_bytes must be at least 4")


def _append_chunk(
    current: list[str],
    chunks: list[str],
    seen: set[str],
) -> None:
    if not current:
        return
    chunk = "".join(current)
    current.clear()
    if chunk in seen:
        return
    seen.add(chunk)
    chunks.append(chunk)


def _next_segment_end(text: str, start: int, max_segment_bytes: int) -> int:
    end = start
    used_bytes = 0
    last_separator_end: int | None = None
    while end < len(text):
        character = text[end]
        character_bytes = len(character.encode("utf-8"))
        if used_bytes + character_bytes > max_segment_bytes:
            break
        used_bytes += character_bytes
        end += 1
        if not character.isalnum():
            last_separator_end = end
    if end == len(text):
        return end
    if last_separator_end is not None and last_separator_end > start:
        return last_separator_end
    # max_segment_bytes >= 4 guarantees that at least one code point fits.
    assert end > start
    return end
