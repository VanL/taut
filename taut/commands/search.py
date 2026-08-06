"""Command adapter for full-text message search."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_search_hits


class SearchCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = "Search visible Taut message history."
        parser.enable_intermixed_args()
        parser.epilog = "Exit 0 for hits, 2 for no hits, and 1 for invalid search."
        parser.add_argument(
            "query",
            nargs="+",
            metavar="QUERY",
            help="Terms to require; shell words are joined with one space.",
        )
        parser.add_argument(
            "--channel",
            action="append",
            default=[],
            metavar="CHANNEL",
            help="Search one channel and its subthreads; repeat to union scopes.",
        )
        parser.add_argument(
            "--dm",
            action="append",
            default=[],
            metavar="@NAME_OR_HANDLE",
            help="Search one accessible DM; repeat to union scopes.",
        )
        parser.add_argument(
            "--dms",
            action="store_true",
            help="Search all accessible direct messages.",
        )
        parser.add_argument(
            "--from",
            dest="from_member",
            metavar="NAME_OR_ALIAS",
            help="Require the current stable member selected by name or alias.",
        )
        parser.add_argument(
            "--kind",
            action="append",
            choices=("message", "notice", "foreign"),
            default=[],
            help="Require a message kind; repeat to include multiple kinds.",
        )
        parser.add_argument(
            "--before",
            metavar="MSG_ID",
            help="Return hits older than one exact 19-digit message id.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            metavar="N",
            help="Return 1 through 1000 hits (default: 50).",
        )
        parser.add_argument(
            "--reindex",
            action="store_true",
            help="Rebuild disposable search state before querying.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        client = context.client()
        query = " ".join(args.query)
        hits = client.search(
            query,
            channels=args.channel,
            direct_messages=args.dm,
            all_direct_messages=args.dms,
            from_member=args.from_member,
            kinds=args.kind,
            before=args.before,
            limit=args.limit,
            reindex=args.reindex,
        )
        emit_search_hits(
            client,
            hits,
            json_output=context.json,
            timestamps=context.timestamps,
            quiet=context.quiet,
            stdout=context.stdout,
            stderr=context.stderr,
            query=query,
        )
        return 0


def create_command() -> SearchCommand:
    return SearchCommand()
