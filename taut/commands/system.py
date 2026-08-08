"""Actor-free workspace persistence command adapter.

Spec references:
- docs/specs/08-persistence-io.md [PIO-3.1], [PIO-3.3]
"""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext, CommandError
from taut.commands._rendering import emit_dump_report, emit_load_report


class SystemCommand:
    """Own the required nested grammar for workspace maintenance."""

    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Actor-free workspace maintenance. Exit codes: 0 success; "
            "1 error; 2 missing input."
        )
        subparsers = parser.add_subparsers(
            dest="system_command",
            required=True,
            title="operations",
            metavar="OPERATION",
            help="Maintenance operation; use 'taut system OPERATION --help' for syntax.",
        )

        dump_parser = subparsers.add_parser(
            "dump",
            help="Write a full-workspace composite logical backup.",
            description=(
                "Write an owner-only composite logical backup. Stop workspace "
                "writers for the full operation. Receipts count every registered "
                "Taut queue, including empty queues."
            ),
        )
        dump_parser.add_argument(
            "--output",
            required=True,
            metavar="FILE",
            help="File to replace atomically after the complete dump is verified.",
        )

        load_parser = subparsers.add_parser(
            "load",
            help="Preflight or restore a full-workspace composite backup.",
            description=(
                "Preflight or restore a composite backup into a fresh workspace. "
                "Stop workspace processes for the full operation. Receipts count "
                "every registered Taut queue, including empty queues."
            ),
        )
        load_parser.add_argument(
            "--input",
            required=True,
            metavar="FILE",
            help="Composite dump file to validate or restore.",
        )
        load_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the file without opening or checking the destination.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        if context.as_name is not None or context.auth_token is not None:
            raise CommandError("taut system does not accept --as or --token")
        if context.timestamps:
            raise CommandError("taut system does not accept --timestamps")
        from taut.client import TautClient

        if args.system_command == "dump":
            dump_report = TautClient.dump(output=args.output, db_path=context.db_path)
            emit_dump_report(
                dump_report,
                json_output=context.json,
                quiet=context.quiet,
                stdout=context.stdout,
            )
            return 0
        if args.system_command == "load":
            try:
                load_report = TautClient.load(
                    input_path=args.input,
                    db_path=context.db_path,
                    dry_run=args.dry_run,
                )
            except FileNotFoundError as exc:
                raise CommandError(f"input file not found: {args.input}", 2) from exc
            emit_load_report(
                load_report,
                json_output=context.json,
                quiet=context.quiet,
                stdout=context.stdout,
            )
            return 0
        raise RuntimeError(f"unsupported system operation: {args.system_command}")


def create_command() -> SystemCommand:
    return SystemCommand()
