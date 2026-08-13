import inspect
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

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

from gateway.conversation.agent import (
    AgentContext,
    AgentEvent,
    AgentItemStarted,
    AgentMessageCreated,
    AgentMessageDelta,
    ToolCallCreated,
    ToolResultCreated,
    TurnControl,
)
from gateway.conversation.models import (
    AgentMessageItem,
    ToolCallItem,
    ToolResultItem,
    UserMessageItem,
)

_MAX_TOOL_ROUNDS = 8


class LlmifyAgentRunner:
    """Streaming llmify adapter with a small, explicit tool loop."""

    def __init__(
        self,
        model: ChatModel,
        system_prompt: str,
        tools: tuple[FunctionTool, ...] = (),
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt
        self._tools = tools
        self._tools_by_name = {tool.name: tool for tool in tools}

    async def run(
        self,
        context: AgentContext,
        input: str,
        control: TurnControl,
    ) -> AsyncIterator[AgentEvent]:
        del control
        messages = self._build_messages(context)
        messages.append(UserMessage(content=input))

        for _ in range(_MAX_TOOL_ROUNDS):
            message_id = uuid4()
            message_started = False
            content_parts: list[str] = []
            tool_calls: dict[str, ToolCall] = {}

            async for event in self._model.stream(messages, tools=list(self._tools)):
                if isinstance(event, StreamTextDelta):
                    if not message_started:
                        yield AgentItemStarted(
                            item_id=message_id,
                            item_type="agent_message",
                        )
                        message_started = True
                    content_parts.append(event.delta)
                    yield AgentMessageDelta(item_id=message_id, delta=event.delta)
                elif isinstance(event, StreamToolCall):
                    tool_calls[event.tool_call.id] = event.tool_call
                elif isinstance(event, StreamEnd):
                    for call in event.tool_calls:
                        tool_calls[call.id] = call
                    if not content_parts and event.completion:
                        yield AgentItemStarted(
                            item_id=message_id,
                            item_type="agent_message",
                        )
                        yield AgentMessageDelta(
                            item_id=message_id,
                            delta=event.completion,
                        )
                        content_parts.append(event.completion)
                        message_started = True

            content = "".join(content_parts)
            calls = list(tool_calls.values())
            if content:
                yield AgentMessageCreated(item_id=message_id, content=content)
            if not calls:
                return

            messages.append(
                AssistantMessage(content=content or None, tool_calls=calls)
            )
            for call in calls:
                tool = self._tools_by_name.get(call.function.name)
                if tool is None:
                    raise ValueError(f"unknown tool: {call.function.name}")
                arguments = tool.parse_arguments(call.function.arguments)
                yield ToolCallCreated(
                    name=call.function.name,
                    arguments=arguments,
                    call_id=call.id,
                )
                result = tool(**arguments)
                if inspect.isawaitable(result):
                    result = await result
                yield ToolResultCreated(call_id=call.id, output=result)
                messages.append(
                    ToolResultMessage(
                        tool_call_id=call.id,
                        content=_stringify(result),
                    )
                )

        raise RuntimeError("maximum tool rounds exceeded")

    def _build_messages(self, context: AgentContext) -> list[Any]:
        messages: list[Any] = [SystemMessage(content=self._system_prompt)]
        for item in context.items:
            if isinstance(item, UserMessageItem):
                messages.append(UserMessage(content=item.content))
            elif isinstance(item, AgentMessageItem):
                messages.append(AssistantMessage(content=item.content))
            elif isinstance(item, ToolCallItem):
                messages.append(
                    AssistantMessage(
                        content=None,
                        tool_calls=[
                            ToolCall(
                                id=item.call_id,
                                function=Function(
                                    name=item.name,
                                    arguments=json.dumps(item.arguments),
                                ),
                            )
                        ],
                    )
                )
            elif isinstance(item, ToolResultItem):
                messages.append(
                    ToolResultMessage(
                        tool_call_id=item.call_id,
                        content=_stringify(item.output),
                    )
                )
        return messages


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)
