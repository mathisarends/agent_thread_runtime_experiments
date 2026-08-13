import inspect
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from agent_protocol.models import (
    AgentMessageItem,
    ItemType,
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

from gateway.conversation.agents.contracts import (
    AgentContext,
    AgentEvent,
    AgentItemStarted,
    AgentMessageCreated,
    AgentMessageDelta,
    AgentProgressUpdated,
    ToolCallCreated,
    ToolResultCreated,
    TurnControl,
)

_MAX_TOOL_ROUNDS = 8
_PROGRESS_TOOL_NAME = "report_progress"


def report_progress(message: str) -> str:
    """Report one concise, user-facing progress update for a long-running task."""
    compact = " ".join(message.split())
    if len(compact) <= 240:
        return compact
    return compact[:237].rstrip() + "..."


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
        tools = list(self._tools)
        if context.progress_enabled:
            tools.append(FunctionTool(report_progress))

        for _ in range(_MAX_TOOL_ROUNDS):
            message_id = uuid4()
            message_started = False
            content_parts: list[str] = []
            tool_calls: dict[str, ToolCall] = {}

            async for event in self._model.stream(messages, tools=tools):
                if isinstance(event, StreamTextDelta):
                    if not message_started:
                        yield AgentItemStarted(
                            item_id=message_id,
                            item_type=ItemType.AGENT_MESSAGE,
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
                            item_type=ItemType.AGENT_MESSAGE,
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

            messages.append(AssistantMessage(content=content or None, tool_calls=calls))
            for call in calls:
                tool = next(
                    (
                        candidate
                        for candidate in tools
                        if candidate.name == call.function.name
                    ),
                    None,
                )
                if tool is None:
                    raise ValueError(f"unknown tool: {call.function.name}")
                arguments = tool.parse_arguments(call.function.arguments)
                result = tool(**arguments)
                if inspect.isawaitable(result):
                    result = await result
                if call.function.name == _PROGRESS_TOOL_NAME:
                    yield AgentProgressUpdated(message=str(result))
                else:
                    yield ToolCallCreated(
                        name=call.function.name,
                        arguments=arguments,
                        call_id=call.id,
                    )
                    yield ToolResultCreated(call_id=call.id, output=result)
                messages.append(
                    ToolResultMessage(
                        tool_call_id=call.id,
                        content=_stringify(result),
                    )
                )

        raise RuntimeError("maximum tool rounds exceeded")

    def _build_messages(self, context: AgentContext) -> list[Any]:
        system_prompt = self._system_prompt
        if context.progress_enabled:
            system_prompt += (
                "\nFor longer work, call report_progress occasionally with a short, "
                "user-facing status update. Report only meaningful phase changes, "
                "important intermediate findings, or strategy changes; do not report "
                "every tool call."
            )
        messages: list[Any] = [SystemMessage(content=system_prompt)]
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
