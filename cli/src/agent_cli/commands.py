"""Slash commands: one registry, one handler per command."""

import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field

from agent_cli.protocol import Method, ProgressMode
from agent_cli.session import Session
from agent_cli.theme import Theme

Handler = Callable[[Session, str], Awaitable[None]]


class ExitRequested(Exception):
    """Raised by /quit to leave the interactive loop."""


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    summary: str
    handler: Handler
    argument: str = ""
    aliases: tuple[str, ...] = ()

    @property
    def usage(self) -> str:
        return f"{self.name} {self.argument}".strip()


@dataclass(slots=True)
class CommandRegistry:
    _commands: dict[str, Command] = field(default_factory=dict)
    _order: list[Command] = field(default_factory=list)

    def register(
        self,
        name: str,
        summary: str,
        *,
        argument: str = "",
        aliases: Iterable[str] = (),
    ) -> Callable[[Handler], Handler]:
        def decorate(handler: Handler) -> Handler:
            command = Command(
                name=name,
                summary=summary,
                handler=handler,
                argument=argument,
                aliases=tuple(aliases),
            )
            self._order.append(command)
            for key in (command.name, *command.aliases):
                self._commands[key] = command
            return handler

        return decorate

    def get(self, name: str) -> Command:
        command = self._commands.get(name)
        if command is None:
            raise ValueError(f"unknown command {name}; use /help")
        return command

    async def dispatch(self, session: Session, line: str) -> None:
        """Route a line: slash commands by name, plain text to the thread."""
        if not line.startswith("/"):
            await _send_text(session, line)
            return
        name, _, argument = line.partition(" ")
        await self.get(name).handler(session, argument.strip())

    def help_text(self, theme: Theme) -> str:
        width = max(len(command.usage) for command in self._order)
        lines = [theme.strong("Commands")]
        lines.append(
            f"  {theme.user('<text>'.ljust(width))}  "
            f"{theme.muted('start a turn, or steer the active turn')}"
        )
        lines.extend(
            f"  {theme.user(command.usage.ljust(width))}  "
            f"{theme.muted(command.summary)}"
            for command in self._order
        )
        return "\n".join(lines)


registry = CommandRegistry()


@registry.register("/new", "create and subscribe to a new thread")
async def _new(session: Session, argument: str) -> None:
    await session.create_thread()


@registry.register("/use", "switch to an existing thread", argument="THREAD_ID")
async def _use(session: Session, argument: str) -> None:
    await session.use_thread(_required(argument, "thread ID"))


@registry.register("/get", "print the current persisted snapshot")
async def _get(session: Session, argument: str) -> None:
    snapshot = await session.rpc.request(
        Method.THREAD_GET, {"thread_id": session.state.require_thread()}
    )
    session.console.json(snapshot)


@registry.register("/start", "explicitly start a turn", argument="TEXT")
async def _start(session: Session, argument: str) -> None:
    turn_id = await session.start_turn(_required(argument, "message"))
    session.console.note(f"turn {turn_id}")


@registry.register("/steer", "explicitly steer the active turn", argument="TEXT")
async def _steer(session: Session, argument: str) -> None:
    await session.steer_turn(_required(argument, "message"))
    session.console.note("steering delivered")


@registry.register("/interrupt", "interrupt the active turn")
async def _interrupt(session: Session, argument: str) -> None:
    await session.interrupt_turn()
    session.console.note("interrupt requested")


@registry.register("/subscribe", "subscribe to live events", argument="[THREAD_ID]")
async def _subscribe(session: Session, argument: str) -> None:
    thread_id = argument or session.state.require_thread()
    await session.subscribe(thread_id)
    session.console.note(f"subscribed to {thread_id} (future events only)")


@registry.register(
    "/unsubscribe", "unsubscribe from live events", argument="[THREAD_ID]"
)
async def _unsubscribe(session: Session, argument: str) -> None:
    thread_id = argument or session.state.require_thread()
    await session.unsubscribe(thread_id)
    session.console.note(f"unsubscribed from {thread_id}")


@registry.register(
    "/progress", "set the progress mode for this thread", argument="MODE"
)
async def _progress(session: Session, argument: str) -> None:
    mode = _progress_mode(_required(argument, "progress mode"))
    await session.subscribe(session.state.require_thread(), mode)
    session.console.note(f"progress mode: {mode.value}")


@registry.register("/status", "print the active turn's latest progress")
async def _status(session: Session, argument: str) -> None:
    result = await session.rpc.request(
        Method.TURN_PROGRESS_GET, {"thread_id": session.state.require_thread()}
    )
    progress = result["progress"]
    session.console.note(progress["message"] if progress else "no active progress")


@registry.register(
    "/rpc", "send an arbitrary JSON-RPC request", argument="METHOD [JSON]"
)
async def _rpc(session: Session, argument: str) -> None:
    method, _, raw_params = argument.partition(" ")
    if not method:
        raise ValueError("usage: /rpc METHOD [JSON_OBJECT]")
    params = json.loads(raw_params) if raw_params.strip() else None
    if params is not None and not isinstance(params, dict):
        raise ValueError("RPC params must be a JSON object")
    session.console.json(await session.rpc.request(method, params))


@registry.register("/help", "show this help", aliases=("/?",))
async def _help(session: Session, argument: str) -> None:
    session.console.break_line()
    session.console.line(registry.help_text(session.console.theme))
    session.console.line()


@registry.register("/quit", "close the connection", aliases=("/exit",))
async def _quit(session: Session, argument: str) -> None:
    raise ExitRequested


async def _send_text(session: Session, text: str) -> None:
    """Plain input stays quiet: the agent's reply is the feedback."""
    if session.state.active_turn_id is None:
        await session.start_turn(text)
    else:
        await session.steer_turn(text)
        session.console.note("steering delivered")


def _progress_mode(value: str) -> ProgressMode:
    try:
        return ProgressMode(value)
    except ValueError:
        modes = ", ".join(mode.value for mode in ProgressMode)
        raise ValueError(f"progress mode must be one of: {modes}") from None


def _required(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"missing {label}")
    return value
