"""Static lightweight manifests for core-owned commands.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.1], [TAUT-8.6]
"""

from __future__ import annotations

from taut.commands._protocol import CommandSpec, GlobalOption

_COMMON_GLOBALS = frozenset(GlobalOption)
_REJOIN_GLOBALS = _COMMON_GLOBALS - {GlobalOption.TOKEN}


def _spec(
    name: str,
    summary: str,
    *,
    globals_: frozenset[GlobalOption] = _COMMON_GLOBALS,
) -> CommandSpec:
    return CommandSpec(
        command_api_version=1,
        name=name,
        summary=summary,
        post_verb_globals=globals_,
        implementation=f"taut.commands.{name}:create_command",
    )


BUILTIN_SPECS = (
    _spec("init", "Initialize the resolved Taut storage."),
    _spec("join", "Join a channel, creating it when needed."),
    _spec("leave", "Leave a joined thread without deleting history."),
    _spec("set", "Change a property of the acting member."),
    _spec("say", "Post to a channel, sub-thread, or direct-message target."),
    _spec("reply", "Reply in the sub-thread rooted at a message."),
    _spec("read", "Show unread messages and advance chat cursors."),
    _spec("inbox", "Claim and show pending notification pointers."),
    _spec("log", "Show thread history without moving a cursor."),
    _spec("list", "List joined threads and unread state."),
    _spec("watch", "Live-follow chat and notification activity."),
    _spec("rename", "Rename a channel and its registered sub-threads."),
    _spec("who", "Show members and presence evidence."),
    _spec("whoami", "Show the identity Taut resolved for this caller."),
    _spec(
        "rejoin",
        "Associate current identity evidence with an existing member.",
        globals_=_REJOIN_GLOBALS,
    ),
)
