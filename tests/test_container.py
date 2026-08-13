import pytest

from gateway.config import Settings
from gateway.container import create_container
from gateway.conversation.agent import AgentRunner, FakeAgentRunner
from gateway.conversation.llmify_runner import LlmifyAgentRunner


@pytest.mark.asyncio
async def test_container_uses_llmify_runner_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    container = create_container(Settings(database_path=":memory:"))
    try:
        runner = await container.get(AgentRunner)
        assert isinstance(runner, LlmifyAgentRunner)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_container_accepts_runner_override() -> None:
    override = FakeAgentRunner()
    container = create_container(Settings(database_path=":memory:"), override)
    try:
        assert await container.get(AgentRunner) is override
    finally:
        await container.close()
