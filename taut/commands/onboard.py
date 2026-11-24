"""Actor-free project onboarding command adapter.

Spec references:
- docs/specs/02-taut-core.md [TAUT-6.4], [TAUT-8.1], [TAUT-8.2]
"""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext, CommandError
from taut.commands._rendering import emit_onboard, write_human_line


class OnboardCommand:
    """Bootstrap Taut storage, agent instructions, ignore entries, and MCP config."""

    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Actor-free current-directory onboarding. Initializes storage, writes "
            "or updates the fenced Taut section in AGENTS.md/CLAUDE.md, appends "
            "default SQLite/lock entries to existing .gitignore/.dockerignore "
            "(never creating absent ignore files), and optionally registers "
            "taut mcp in .mcp.json."
        )
        parser.add_argument(
            "--channel",
            default=None,
            metavar="CHANNEL",
            help="Default channel rendered in agent instructions (default: general).",
        )
        parser.add_argument(
            "--mcp",
            action="store_true",
            help="Register 'taut mcp' in .mcp.json under mcpServers.taut.",
        )
        parser.add_argument(
            "--no-init",
            action="store_true",
            help="Skip storage initialization.",
        )
        parser.add_argument(
            "--no-agents",
            action="store_true",
            help="Skip AGENTS.md / CLAUDE.md creation or update.",
        )
        parser.add_argument(
            "--no-ignore",
            action="store_true",
            help="Skip existing .gitignore / .dockerignore updates.",
        )
        parser.add_argument(
            "--print-kernel",
            action="store_true",
            help="Print the packaged agent-kernel protocol document and exit.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        if context.as_name is not None or context.continuity_token is not None:
            raise CommandError("taut onboard does not accept --as or --token")
        if context.timestamps:
            raise CommandError("taut onboard does not accept --timestamps")
        from taut.client import TautClient

        if args.print_kernel:
            if context.db_path is not None or context.json or context.quiet:
                raise CommandError(
                    "taut onboard --print-kernel does not accept --db, --json, or --quiet"
                )
            if (
                args.channel is not None
                or args.mcp
                or args.no_init
                or args.no_agents
                or args.no_ignore
            ):
                raise CommandError(
                    "taut onboard --print-kernel cannot be combined with onboarding flags"
                )
            kernel_text = TautClient.agent_kernel()
            for line in kernel_text.removesuffix("\n").split("\n"):
                write_human_line(context.stdout, line)
            return 0

        channel = "general" if args.channel is None else str(args.channel)
        report = TautClient.onboard(
            db_path=context.db_path,
            channel=channel,
            mcp=bool(args.mcp),
            init_storage=not bool(args.no_init),
            update_agents=not bool(args.no_agents),
            update_ignore=not bool(args.no_ignore),
        )
        emit_onboard(
            report,
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
        )
        return 0


def create_command() -> OnboardCommand:
    return OnboardCommand()
