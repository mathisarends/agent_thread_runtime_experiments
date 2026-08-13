"""Command line entry point."""

import argparse
import asyncio
import sys
from contextlib import suppress

from agent_cli.app import run_interactive, run_once
from agent_cli.console import Console
from agent_cli.theme import Theme

DEFAULT_URL = "ws://127.0.0.1:8000/v1/conversation"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-cli", description="Agent thread JSON-RPC client"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="gateway WebSocket URL")
    parser.add_argument("--thread", help="use an existing thread UUID")
    parser.add_argument("--message", help="send one message and exit")
    parser.add_argument(
        "--no-color", action="store_true", help="disable ANSI colors and styling"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    console = Console(Theme.for_stream(sys.stdout, force_plain=args.no_color))
    with suppress(KeyboardInterrupt):
        if args.message is not None:
            asyncio.run(run_once(args.url, console, args.message, args.thread))
        else:
            asyncio.run(run_interactive(args.url, console, args.thread))


if __name__ == "__main__":
    main()
