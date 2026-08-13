from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from llmify import AssistantMessage, ChatModel, SystemMessage, UserMessage

from gateway.conversation.agent import AgentContext, AgentMessageCreated, TurnControl
from gateway.conversation.llmify_runner import LlmifyAgentRunner
from gateway.conversation.models import AgentMessageItem, UserMessageItem


class RecordingModel:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def invoke(self, messages: list[Any]) -> SimpleNamespace:
        self.messages = messages
        return SimpleNamespace(completion="A real model answer")


@pytest.mark.asyncio
async def test_runner_builds_llmify_history_and_yields_agent_event() -> None:
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

    assert events == [AgentMessageCreated(content="A real model answer")]
    assert len(model.messages) == 4
    assert isinstance(model.messages[0], SystemMessage)
    assert model.messages[0].content == "Be concise."
    assert isinstance(model.messages[1], UserMessage)
    assert model.messages[1].content == "Earlier question"
    assert isinstance(model.messages[2], AssistantMessage)
    assert model.messages[2].content == "Earlier answer"
    assert isinstance(model.messages[3], UserMessage)
    assert model.messages[3].content == "New question"
