import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from .models import Item


@dataclass(frozen=True, slots=True)
class AgentContext:
    items: tuple[Item, ...]


@dataclass(frozen=True, slots=True)
class Steer:
    message: str


@dataclass(frozen=True, slots=True)
class Interrupt:
    pass


type ControlMessage = Steer | Interrupt


class TurnControl:
    """The private control channel for one running turn."""

    def __init__(self) -> None:
        self._messages: asyncio.Queue[ControlMessage] = asyncio.Queue()

    async def send(self, message: ControlMessage) -> None:
        await self._messages.put(message)

    async def receive(self) -> AsyncIterator[ControlMessage]:
        while True:
            yield await self._messages.get()

    async def receive_one(self) -> ControlMessage:
        """Convenience checkpoint for runners that poll between operations."""
        return await self._messages.get()


@dataclass(frozen=True, slots=True)
class AgentMessageCreated:
    content: str


@dataclass(frozen=True, slots=True)
class ToolCallCreated:
    name: str
    arguments: dict[str, Any]
    call_id: str


@dataclass(frozen=True, slots=True)
class ToolResultCreated:
    call_id: str
    output: Any


type AgentEvent = AgentMessageCreated | ToolCallCreated | ToolResultCreated


class AgentRunner(Protocol):
    def run(
        self,
        context: AgentContext,
        input: str,
        control: TurnControl,
    ) -> AsyncIterator[AgentEvent]: ...


class ContextBuilder(Protocol):
    async def build(self, thread_id: UUID) -> AgentContext: ...


class FakeAgentRunner:
    async def run(
        self,
        context: AgentContext,
        input: str,
        control: TurnControl,
    ) -> AsyncIterator[AgentEvent]:
        del context, control
        yield AgentMessageCreated(content=f"Echo: {input}")
