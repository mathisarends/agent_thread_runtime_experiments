from collections.abc import AsyncIterator

from llmify import AssistantMessage, ChatModel, SystemMessage, UserMessage

from .agent import (
    AgentContext,
    AgentEvent,
    AgentMessageCreated,
    TurnControl,
)
from .models import AgentMessageItem, UserMessageItem


class LlmifyAgentRunner:
    """Minimal AgentRunner adapter around a llmify chat model."""

    def __init__(self, model: ChatModel, system_prompt: str) -> None:
        self._model = model
        self._system_prompt = system_prompt

    async def run(
        self,
        context: AgentContext,
        input: str,
        control: TurnControl,
    ) -> AsyncIterator[AgentEvent]:
        del control
        messages = [SystemMessage(content=self._system_prompt)]
        for item in context.items:
            if isinstance(item, UserMessageItem):
                messages.append(UserMessage(content=item.content))
            elif isinstance(item, AgentMessageItem):
                messages.append(AssistantMessage(content=item.content))
        messages.append(UserMessage(content=input))

        response = await self._model.invoke(messages)
        yield AgentMessageCreated(content=response.completion)
