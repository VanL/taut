"""Lightweight fixture manifest; importing it must not import execution code."""

from taut.commands import CommandSpec, GlobalOption

MANIFEST_IMPORTED = True

fixture = CommandSpec(
    command_api_version=1,
    name="fixture",
    summary="Exercise an installed command extension.",
    post_verb_globals=frozenset(
        {
            GlobalOption.DB,
            GlobalOption.AS,
            GlobalOption.TOKEN,
            GlobalOption.JSON,
            GlobalOption.TIMESTAMPS,
            GlobalOption.QUIET,
        }
    ),
    implementation="taut_command_plugin.command:create_command",
)
