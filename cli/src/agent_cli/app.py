"""Interactive loop and one-shot run."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from websockets.asyncio.client import connect

from agent_cli.commands import ExitRequested, registry
from agent_cli.console import Console
from agent_cli.protocol import TERMINAL_TURN_EVENTS
from agent_cli.rpc import JsonRpcClient, RpcError
from agent_cli.session import Session

BANNER = "agent cli"


@asynccontextmanager
async def open_session(url: str, console: Console) -> AsyncIterator[Session]:
    async with connect(url) as socket:
        rpc = JsonRpcClient(socket)
        try:
            yield Session(rpc, console)
        finally:
            await rpc.close()


async def run_interactive(
    url: str, console: Console, initial_thread: str | None = None
) -> None:
    async with open_session(url, console) as session:
        console.banner(BANNER, f"connected to {url}")
        listener = asyncio.create_task(session.consume_events(), name="event-listener")
        try:
            if initial_thread is None:
                await session.create_thread()
            else:
                await session.use_thread(initial_thread)
            console.line()
            console.line(registry.help_text(console.theme))
            console.line()
            await _prompt_loop(session)
        finally:
            listener.cancel()
            with suppress(asyncio.CancelledError):
                await listener


async def run_once(
    url: str, console: Console, message: str, thread_id: str | None = None
) -> None:
    """Send one message and wait for its terminal event (useful for smoke tests)."""
    async with open_session(url, console) as session:
        if thread_id is None:
            thread_id = await session.create_thread()
        else:
            await session.use_thread(thread_id)
        turn_id = await session.start_turn(message)
        console.note(f"turn {turn_id}")
        async for event in session.rpc.notifications():
            session.handle_event(event)
            if event["type"] in TERMINAL_TURN_EVENTS:
                break
        console.break_line()


async def _prompt_loop(session: Session) -> None:
    console = session.console
    while True:
        try:
            line = (await console.ask("you", console.theme.user)).strip()
        except EOFError, KeyboardInterrupt:
            console.line()
            return
        if not line:
            continue
        try:
            await registry.dispatch(session, line)
        except ExitRequested:
            return
        except (RpcError, ValueError, KeyError) as error:
            console.error(str(error))
