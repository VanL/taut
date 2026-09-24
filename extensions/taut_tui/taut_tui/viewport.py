"""Pure transcript viewport ownership for [TUI-9.2].

Textual supplies settled geometry and applies returned effects. This module
owns only semantic position and generation fencing; it never reads a widget.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class ViewportMode(StrEnum):
    TAIL = "tail"
    HISTORY = "history"
    SEARCH_OWNED = "search-owned"


class ViewportEffectKind(StrEnum):
    SCROLL_END = "scroll-end"
    RESTORE = "restore"


@dataclass(frozen=True, slots=True)
class ViewportEffect:
    generation: int
    kind: ViewportEffectKind
    message_id: int | None = None
    offset: int = 0

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("viewport effect generation must be positive")
        if self.offset < 0:
            raise ValueError("viewport effect offset must be non-negative")
        if self.kind is ViewportEffectKind.SCROLL_END:
            if self.message_id is not None or self.offset:
                raise ValueError("scroll-end effect cannot name a history row")
        elif self.message_id is None or self.message_id <= 0:
            raise ValueError("restore effect message_id must be positive")


@dataclass(frozen=True, slots=True)
class TranscriptViewport:
    """One semantic viewport owner plus a fence for deferred render effects."""

    mode: ViewportMode
    generation: int = 0
    message_id: int | None = None
    offset: int = 0
    intent: int | None = None

    def __post_init__(self) -> None:
        if self.generation < 0:
            raise ValueError("viewport generation must be non-negative")
        if self.offset < 0:
            raise ValueError("viewport offset must be non-negative")
        if self.mode is ViewportMode.TAIL:
            if self.message_id is not None or self.offset or self.intent is not None:
                raise ValueError("tail viewport cannot own history or search state")
        elif self.mode is ViewportMode.HISTORY:
            if self.message_id is None or self.message_id <= 0:
                raise ValueError("history viewport message_id must be positive")
            if self.intent is not None:
                raise ValueError("history viewport cannot own a search intent")
        else:
            if self.message_id is None or self.message_id <= 0:
                raise ValueError("search viewport message_id must be positive")
            if self.intent is None or self.intent < 0:
                raise ValueError("search viewport intent must be non-negative")

    @classmethod
    def tail(cls, *, generation: int = 0) -> TranscriptViewport:
        return cls(ViewportMode.TAIL, generation=generation)

    @classmethod
    def history(
        cls,
        message_id: int,
        *,
        offset: int = 0,
        generation: int = 0,
    ) -> TranscriptViewport:
        return cls(
            ViewportMode.HISTORY,
            generation=generation,
            message_id=message_id,
            offset=offset,
        )

    @property
    def tail_pinned(self) -> bool:
        return self.mode is ViewportMode.TAIL

    @property
    def search_owned(self) -> bool:
        return self.mode is ViewportMode.SEARCH_OWNED

    def user_intent_started(self) -> TranscriptViewport:
        generation = self.generation + 1
        if self.search_owned:
            assert self.message_id is not None
            return self.history(
                self.message_id,
                offset=self.offset,
                generation=generation,
            )
        return replace(self, generation=generation)

    def user_settled(
        self,
        *,
        at_tail: bool,
        message_id: int | None = None,
        offset: int = 0,
    ) -> TranscriptViewport:
        generation = self.generation + 1
        if at_tail:
            return self.tail(generation=generation)
        if message_id is None:
            raise ValueError("history viewport message_id must be positive")
        return self.history(message_id, offset=offset, generation=generation)

    def search_armed(self, intent: int, message_id: int) -> TranscriptViewport:
        return TranscriptViewport(
            ViewportMode.SEARCH_OWNED,
            generation=self.generation + 1,
            message_id=message_id,
            intent=intent,
        )

    def target_changed(self, *, search_intent: int | None = None) -> TranscriptViewport:
        if self.search_owned and search_intent == self.intent:
            return self
        return self.tail(generation=self.generation + 1)

    def cancel_search(self, *, intent: int | None = None) -> TranscriptViewport:
        if not self.search_owned or (intent is not None and intent != self.intent):
            return self
        return self.tail(generation=self.generation + 1)

    def plan_render(
        self,
        *,
        authorized_search_intent: int | None = None,
    ) -> tuple[TranscriptViewport, ViewportEffect | None]:
        if self.search_owned and authorized_search_intent != self.intent:
            return self, None
        generation = self.generation + 1
        planned = replace(self, generation=generation)
        if self.mode is ViewportMode.TAIL:
            return planned, ViewportEffect(
                generation,
                ViewportEffectKind.SCROLL_END,
            )
        assert self.message_id is not None
        return planned, ViewportEffect(
            generation,
            ViewportEffectKind.RESTORE,
            message_id=self.message_id,
            offset=self.offset,
        )

    def accepts(self, effect: ViewportEffect) -> bool:
        return effect.generation == self.generation

    def restore_done(
        self,
        effect: ViewportEffect,
        *,
        settled_offset: int,
    ) -> TranscriptViewport:
        if not self.accepts(effect):
            return self
        if self.mode is ViewportMode.TAIL:
            return self
        assert self.message_id is not None
        return self.history(
            self.message_id,
            offset=settled_offset,
            generation=self.generation,
        )

    def restore_failed(self, effect: ViewportEffect) -> TranscriptViewport:
        if not self.accepts(effect):
            return self
        return self.tail(generation=self.generation + 1)


__all__ = [
    "TranscriptViewport",
    "ViewportEffect",
    "ViewportEffectKind",
    "ViewportMode",
]
