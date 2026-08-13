from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from llmify import (
    AssistantMessage,
    ChatModel,
    Function,
    StreamEnd,
    StreamTextDelta,
    StreamToolCall,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

from gateway.conversation.agent import (
    AgentContext,
    AgentItemStarted,
    AgentMessageCreated,
    AgentMessageDelta,
    AgentProgressUpdated,
    ToolCallCreated,
    ToolResultCreated,
    TurnControl,
)
from gateway.conversation.llmify_runner import LlmifyAgentRunner
from gateway.conversation.models import AgentMessageItem, UserMessageItem
from gateway.conversation.tools import default_tools


class RecordingModel:
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.tool_names: list[str] = []

    async def stream(
        self, messages: list[Any], **kwargs: Any
    ) -> AsyncIterator[Any]:
        self.tool_names = [tool.name for tool in kwargs["tools"]]
        self.messages = messages
        yield StreamTextDelta(delta="A real ")
        yield StreamTextDelta(delta="model answer")
        yield StreamEnd(completion="A real model answer")


class ToolCallingModel:
    def __init__(self) -> None:
        self.requests: list[list[Any]] = []

    async def stream(
        self, messages: list[Any], **kwargs: Any
    ) -> AsyncIterator[Any]:
        assert kwargs["tools"]
        self.requests.append(list(messages))
        if len(self.requests) == 1:
            call = ToolCall(
                id="call-add",
                function=Function(name="add_numbers", arguments='{"a": 2, "b": 3}'),
            )
            yield StreamToolCall(tool_call=call)
            yield StreamEnd(tool_calls=[call])
        else:
            yield StreamTextDelta(delta="The sum is 5.")
            yield StreamEnd(completion="The sum is 5.")


class ProgressCallingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(
        self, messages: list[Any], **kwargs: Any
    ) -> AsyncIterator[Any]:
        del messages
        self.calls += 1
        tool_names = [tool.name for tool in kwargs["tools"]]
        assert "report_progress" in tool_names
        if self.calls == 1:
            call = ToolCall(
                id="call-progress",
                function=Function(
                    name="report_progress",
                    arguments='{"message": "Ich recherchiere Stellen."}',
                ),
            )
            yield StreamToolCall(tool_call=call)
            yield StreamEnd(tool_calls=[call])
        else:
            yield StreamTextDelta(delta="Done")
            yield StreamEnd(completion="Done")


@pytest.mark.asyncio
async def test_runner_streams_llmify_history_as_item_lifecycle() -> None:
    now = datetime.now(UTC)
    thread_id = uuid4()
    previous_turn_id = uuid4()
    context = AgentContext(
        items=(
            UserMessageItem(
                id=uuid4(),
                thread_id=thread_id,
                turn_id=previous_turn_id,
                created_at=now,
                content="Earlier question",
            ),
            AgentMessageItem(
                id=uuid4(),
                thread_id=thread_id,
                turn_id=previous_turn_id,
                created_at=now,
                content="Earlier answer",
            ),
        )
    )
    model = RecordingModel()
    runner = LlmifyAgentRunner(cast(ChatModel, model), system_prompt="Be concise.")

    events = [
        event async for event in runner.run(context, "New question", TurnControl())
    ]

    assert [type(event) for event in events] == [
        AgentItemStarted,
        AgentMessageDelta,
        AgentMessageDelta,
        AgentMessageCreated,
    ]
    assert len({event.item_id for event in events}) == 1
    assert isinstance(events[-1], AgentMessageCreated)
    assert events[-1].content == "A real model answer"
    assert len(model.messages) == 4
    assert isinstance(model.messages[0], SystemMessage)
    assert isinstance(model.messages[1], UserMessage)
    assert isinstance(model.messages[2], AssistantMessage)
    assert isinstance(model.messages[3], UserMessage)
    assert "report_progress" not in model.tool_names


@pytest.mark.asyncio
async def test_runner_executes_registered_tool_and_correlates_result() -> None:
    model = ToolCallingModel()
    runner = LlmifyAgentRunner(
        cast(ChatModel, model),
        system_prompt="Use tools.",
        tools=default_tools(),
    )

    events = [
        event
        async for event in runner.run(
            AgentContext(items=()), "Add 2 and 3", TurnControl()
        )
    ]

    tool_call = next(event for event in events if isinstance(event, ToolCallCreated))
    tool_result = next(
        event for event in events if isinstance(event, ToolResultCreated)
    )
    assert tool_call.call_id == "call-add"
    assert tool_call.arguments == {"a": 2, "b": 3}
    assert tool_result.call_id == tool_call.call_id
    assert tool_result.output == 5
    assert len(model.requests) == 2
    assert isinstance(model.requests[1][-1], ToolResultMessage)


@pytest.mark.asyncio
async def test_progress_tool_is_only_exposed_as_progress_event() -> None:
    model = ProgressCallingModel()
    runner = LlmifyAgentRunner(
        cast(ChatModel, model),
        system_prompt="Help.",
        tools=default_tools(),
    )

    events = [
        event
        async for event in runner.run(
            AgentContext(items=(), progress_enabled=True),
            "Find jobs",
            TurnControl(),
        )
    ]

    progress = [event for event in events if isinstance(event, AgentProgressUpdated)]
    assert [event.message for event in progress] == ["Ich recherchiere Stellen."]
    assert not any(
        isinstance(event, ToolCallCreated) and event.name == "report_progress"
        for event in events
    )
