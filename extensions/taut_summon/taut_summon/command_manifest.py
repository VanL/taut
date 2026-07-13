"""Lightweight command-extension manifests for the Taut root CLI."""

from taut.commands import CommandSpec, GlobalOption

summon = CommandSpec(
    command_api_version=1,
    name="summon",
    summary="Start or resume a summoned agent harness.",
    post_verb_globals=frozenset({GlobalOption.DB}),
    implementation="taut_summon.commands.summon:create_command",
)

dismiss = CommandSpec(
    command_api_version=1,
    name="dismiss",
    summary="Stop one live summoned agent harness.",
    post_verb_globals=frozenset({GlobalOption.DB}),
    implementation="taut_summon.commands.dismiss:create_command",
)

__all__ = ["dismiss", "summon"]
