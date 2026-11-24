"""Main ``taut mcp`` command adapter."""

from __future__ import annotations

import argparse

from taut.commands import CommandArgumentParser, CommandContext


class _McpCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        from .cli import configure_parser

        configure_parser(parser)

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        from .cli import McpLaunchDefaults, run_process, validate_launch_defaults

        if (
            context.db_path is not None
            or context.json
            or context.timestamps
            or context.quiet
        ):
            context.stderr.write(
                "taut mcp: error: taut mcp does not accept --db, --json, "
                "--timestamps, or --quiet; use --workspace for a default workspace\n"
            )
            return 1
        post_token: str | None = getattr(args, "token", None)
        post_as: str | None = getattr(args, "as_name", None)
        identities = [
            value
            for value in (
                context.continuity_token,
                context.as_name,
                post_token,
                post_as,
            )
            if value is not None
        ]
        if len(identities) > 1:
            context.stderr.write(
                "taut mcp: error: taut mcp accepts at most one of --token or --as\n"
            )
            return 1
        token = post_token if post_token is not None else context.continuity_token
        as_name = post_as if post_as is not None else context.as_name
        try:
            defaults = validate_launch_defaults(
                McpLaunchDefaults(
                    workspace=getattr(args, "workspace", None),
                    token=token,
                    as_name=as_name,
                )
            )
        except ValueError as exc:
            context.stderr.write(f"taut mcp: error: {exc}\n")
            return 1
        return run_process(defaults)


def create_command() -> _McpCommand:
    return _McpCommand()


__all__ = ["create_command"]
