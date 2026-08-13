from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from gateway.conversation.agents.contracts import (
    AgentContext,
    AgentItemStarted,
    AgentMessageCreated,
    AgentMessageDelta,
    AgentProgressUpdated,
    ToolCallCreated,
    ToolResultCreated,
    TurnControl,
)
from gateway.conversation.agents.llmify import LlmifyAgentRunner, report_progress
from gateway.conversation.agents.tools import default_tools
from gateway.conversation.core.models import (
    AgentMessageItem,
    ToolCallItem,
    ToolResultItem,
    UserMessageItem,
)
from llmify import (
    AssistantMessage,
    ChatModel,
    Function,
    FunctionTool,
    StreamEnd,
    StreamTextDelta,
    StreamToolCall,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


class RecordingModel:
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.tool_names: list[str] = []

    async def stream(self, messages: list[Any], **kwargs: Any) -> AsyncIterator[Any]:
        self.tool_names = [tool.name for tool in kwargs["tools"]]
        self.messages = messages
        yield StreamTextDelta(delta="A real ")
        yield StreamTextDelta(delta="model answer")
        yield StreamEnd(completion="A real model answer")


class ToolCallingModel:
    def __init__(self) -> None:
        self.requests: list[list[Any]] = []

    async def stream(self, messages: list[Any], **kwargs: Any) -> AsyncIterator[Any]:
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

    async def stream(self, messages: list[Any], **kwargs: Any) -> AsyncIterator[Any]:
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


class CompletionOnlyModel:
    """Streams a final answer only through StreamEnd.completion, no deltas."""

    async def stream(self, messages: list[Any], **kwargs: Any) -> AsyncIterator[Any]:
        del messages, kwargs
        yield StreamEnd(completion="Whole answer at once")


class UnknownToolModel:
    async def stream(self, messages: list[Any], **kwargs: Any) -> AsyncIterator[Any]:
        del messages, kwargs
        call = ToolCall(
            id="call-ghost",
            function=Function(name="does_not_exist", arguments="{}"),
        )
        yield StreamToolCall(tool_call=call)
        yield StreamEnd(tool_calls=[call])


class AsyncToolCallingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages: list[Any], **kwargs: Any) -> AsyncIterator[Any]:
        del messages, kwargs
        self.calls += 1
        if self.calls == 1:
            call = ToolCall(
                id="call-async",
                function=Function(name="double", arguments='{"value": 4}'),
            )
            yield StreamToolCall(tool_call=call)
            yield StreamEnd(tool_calls=[call])
        else:
            yield StreamTextDelta(delta="The double is 8.")
            yield StreamEnd(completion="The double is 8.")


class AlwaysCallingModel:
    """Never stops requesting the same tool call, forcing the round limit."""

    async def stream(self, messages: list[Any], **kwargs: Any) -> AsyncIterator[Any]:
        del messages, kwargs
        call = ToolCall(
            id="call-loop",
            function=Function(name="add_numbers", arguments='{"a": 1, "b": 1}'),
        )
        yield StreamToolCall(tool_call=call)
        yield StreamEnd(tool_calls=[call])


async def double(value: float) -> float:
    return value * 2


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


def test_report_progress_truncates_overly_long_messages() -> None:
    message = "word " * 100

    result = report_progress(message)

    assert len(result) <= 240
    assert result.endswith("...")


def test_report_progress_keeps_short_messages_untouched() -> None:
    assert report_progress("  Ich   recherchiere.  ") == "Ich recherchiere."


@pytest.mark.asyncio
async def test_completion_only_stream_is_still_emitted_as_a_message() -> None:
    model = CompletionOnlyModel()
    runner = LlmifyAgentRunner(cast(ChatModel, model), system_prompt="Be concise.")

    events = [
        event async for event in runner.run(AgentContext(items=()), "Hi", TurnControl())
    ]

    assert [type(event) for event in events] == [
        AgentItemStarted,
        AgentMessageDelta,
        AgentMessageCreated,
    ]
    assert events[-1].content == "Whole answer at once"


@pytest.mark.asyncio
async def test_calling_an_unregistered_tool_raises() -> None:
    model = UnknownToolModel()
    runner = LlmifyAgentRunner(
        cast(ChatModel, model), system_prompt="Use tools.", tools=default_tools()
    )

    with pytest.raises(ValueError, match="unknown tool: does_not_exist"):
        async for _ in runner.run(AgentContext(items=()), "Do it", TurnControl()):
            pass


@pytest.mark.asyncio
async def test_async_tool_results_are_awaited() -> None:
    model = AsyncToolCallingModel()
    runner = LlmifyAgentRunner(
        cast(ChatModel, model),
        system_prompt="Use tools.",
        tools=(FunctionTool(double),),
    )

    events = [
        event
        async for event in runner.run(AgentContext(items=()), "Double 4", TurnControl())
    ]

    tool_result = next(event for event in events if isinstance(event, ToolResultCreated))
    assert tool_result.output == 8


@pytest.mark.asyncio
async def test_exceeding_the_maximum_tool_rounds_raises() -> None:
    model = AlwaysCallingModel()
    runner = LlmifyAgentRunner(
        cast(ChatModel, model), system_prompt="Use tools.", tools=default_tools()
    )

    with pytest.raises(RuntimeError, match="maximum tool rounds exceeded"):
        async for _ in runner.run(AgentContext(items=()), "Loop", TurnControl()):
            pass


@pytest.mark.asyncio
async def test_build_messages_replays_tool_call_and_result_history() -> None:
    now = datetime.now(UTC)
    thread_id = uuid4()
    turn_id = uuid4()
    context = AgentContext(
        items=(
            ToolCallItem(
                id=uuid4(),
                thread_id=thread_id,
                turn_id=turn_id,
                created_at=now,
                name="add_numbers",
                arguments={"a": 2, "b": 3},
                call_id="call-1",
            ),
            ToolResultItem(
                id=uuid4(),
                thread_id=thread_id,
                turn_id=turn_id,
                created_at=now,
                call_id="call-1",
                output=5,
            ),
        )
    )
    model = RecordingModel()
    runner = LlmifyAgentRunner(cast(ChatModel, model), system_prompt="Be concise.")

    async for _ in runner.run(context, "And now?", TurnControl()):
        pass

    assert len(model.messages) == 4
    assistant_message = model.messages[1]
    assert isinstance(assistant_message, AssistantMessage)
    assert assistant_message.tool_calls is not None
    assert assistant_message.tool_calls[0].function.name == "add_numbers"
    tool_result_message = model.messages[2]
    assert isinstance(tool_result_message, ToolResultMessage)
    assert tool_result_message.tool_call_id == "call-1"
    assert tool_result_message.content == "5"
