import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol
from uuid import UUID

from .models import Item, Schema


class AgentContext(Schema):
    items: tuple[Item, ...]


class Steer(Schema):
    type: Literal["steer"] = "steer"
    message: str


class Interrupt(Schema):
    type: Literal["interrupt"] = "interrupt"


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


class AgentMessageCreated(Schema):
    type: Literal["agent_message"] = "agent_message"
    content: str


class ToolCallCreated(Schema):
    type: Literal["tool_call"] = "tool_call"
    name: str
    arguments: dict[str, Any]
    call_id: str


class ToolResultCreated(Schema):
    type: Literal["tool_result"] = "tool_result"
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
