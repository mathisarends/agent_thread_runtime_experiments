import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field

from gateway.conversation.models import Item, ItemType, Schema
from gateway.conversation.progress import ProgressImportance, ProgressMessage


class AgentContext(Schema):
    items: tuple[Item, ...]
    progress_enabled: bool = False


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


class AgentItemStarted(Schema):
    type: Literal["item_started"] = "item_started"
    item_id: UUID = Field(default_factory=uuid4)
    item_type: ItemType


class AgentMessageDelta(Schema):
    type: Literal["agent_message_delta"] = "agent_message_delta"
    item_id: UUID
    delta: str


class AgentMessageCreated(Schema):
    type: Literal["agent_message"] = "agent_message"
    item_id: UUID = Field(default_factory=uuid4)
    content: str


class ToolCallCreated(Schema):
    type: Literal["tool_call"] = "tool_call"
    item_id: UUID = Field(default_factory=uuid4)
    name: str
    arguments: dict[str, Any]
    call_id: str


class ToolResultCreated(Schema):
    type: Literal["tool_result"] = "tool_result"
    item_id: UUID = Field(default_factory=uuid4)
    call_id: str
    output: Any


class AgentProgressUpdated(Schema):
    type: Literal["progress"] = "progress"
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
