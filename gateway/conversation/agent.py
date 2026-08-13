import asyncio
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field

from gateway.conversation.models import Item, ItemType, Schema
from gateway.conversation.progress import ProgressImportance, ProgressMessage


class AgentContext(Schema):
    items: tuple[Item, ...]
    progress_enabled: bool = False


class ControlMessageType(StrEnum):
    STEER = "steer"
    INTERRUPT = "interrupt"


class Steer(Schema):
    type: Literal[ControlMessageType.STEER] = ControlMessageType.STEER
    message: str


class Interrupt(Schema):
    type: Literal[ControlMessageType.INTERRUPT] = ControlMessageType.INTERRUPT


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


class AgentEventType(StrEnum):
    ITEM_STARTED = "item_started"
    AGENT_MESSAGE_DELTA = "agent_message_delta"
    AGENT_MESSAGE = "agent_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PROGRESS = "progress"


class AgentItemStarted(Schema):
    type: Literal[AgentEventType.ITEM_STARTED] = AgentEventType.ITEM_STARTED
    item_id: UUID = Field(default_factory=uuid4)
    item_type: ItemType


class AgentMessageDelta(Schema):
    type: Literal[AgentEventType.AGENT_MESSAGE_DELTA] = (
        AgentEventType.AGENT_MESSAGE_DELTA
    )
    item_id: UUID
    delta: str


class AgentMessageCreated(Schema):
    type: Literal[AgentEventType.AGENT_MESSAGE] = AgentEventType.AGENT_MESSAGE
    item_id: UUID = Field(default_factory=uuid4)
    content: str


class ToolCallCreated(Schema):
    type: Literal[AgentEventType.TOOL_CALL] = AgentEventType.TOOL_CALL
    item_id: UUID = Field(default_factory=uuid4)
    name: str
    arguments: dict[str, Any]
    call_id: str


class ToolResultCreated(Schema):
    type: Literal[AgentEventType.TOOL_RESULT] = AgentEventType.TOOL_RESULT
    item_id: UUID = Field(default_factory=uuid4)
    call_id: str
    output: Any


class AgentProgressUpdated(Schema):
    type: Literal[AgentEventType.PROGRESS] = AgentEventType.PROGRESS
    message: ProgressMessage
    importance: ProgressImportance = ProgressImportance.NORMAL


type AgentEvent = (
    AgentItemStarted
    | AgentMessageDelta
    | AgentMessageCreated
    | ToolCallCreated
    | ToolResultCreated
    | AgentProgressUpdated
)


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
