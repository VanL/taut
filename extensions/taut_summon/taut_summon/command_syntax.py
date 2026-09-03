"""Syntax-only contribution for the Taut command mirror."""

from __future__ import annotations

from taut.commands.syntax import (
    CommandSyntax,
    CommandSyntaxProvider,
    ExclusiveGroupSyntax,
    GlobalOptionSyntax,
    OptionSyntax,
    PositionalSyntax,
    ValueKind,
)


def provide_syntax() -> CommandSyntaxProvider:
    """Publish Summon paths without importing CLI adapters or terminal code."""

    db = GlobalOptionSyntax("db_path", ("--db",), True, ValueKind.PATH)
    summon = CommandSyntax(
        ("summon",),
        "Start or resume a summoned agent harness.",
        positionals=(
            PositionalSyntax("name"),
            PositionalSyntax("threads", required=False, multiple=True),
        ),
        options=(
            OptionSyntax("provider", ("--provider",), True),
            OptionSyntax("attach", ("--attach",)),
            OptionSyntax("detach", ("--detach",)),
            OptionSyntax("takeover", ("--takeover",)),
            OptionSyntax("persona", ("--persona",), True),
            OptionSyntax(
                "system_prompt_file", ("--system-prompt-file",), True, ValueKind.PATH
            ),
            OptionSyntax("rate_limit", ("--rate-limit",), True, ValueKind.INTEGER),
        ),
        exclusive_groups=(ExclusiveGroupSyntax(("attach", "detach")),),
        post_verb_globals=(db,),
        intermixed=True,
    )
    dismiss = CommandSyntax(
        ("dismiss",),
        "Stop one live summoned agent harness.",
        positionals=(PositionalSyntax("name"),),
        post_verb_globals=(db,),
    )
    return CommandSyntaxProvider("taut-summon", "0.9", (summon, dismiss))


__all__ = ["provide_syntax"]
