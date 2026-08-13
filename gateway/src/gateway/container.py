from collections.abc import Iterator

from dishka import Provider, Scope, make_async_container, provide
from dishka.async_container import AsyncContainer
from dishka.integrations.fastapi import FastapiProvider
from llmify import ChatModel, ChatOpenAI
from sqlalchemy.engine import Engine

from gateway.config import Settings
from gateway.conversation.agents.context import RepositoryContextBuilder
from gateway.conversation.agents.contracts import AgentRunner, ContextBuilder
from gateway.conversation.agents.llmify import LlmifyAgentRunner
from gateway.conversation.agents.tools import default_tools
from gateway.conversation.core.broker import EventBroker
from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.persistence.database import create_sqlite_engine
from gateway.conversation.persistence.repository import Repository
from gateway.conversation.persistence.sqlmodel import SQLModelRepository


class ConversationProvider(Provider):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    @provide(scope=Scope.APP)
    def settings(self) -> Settings:
        return self._settings

    @provide(scope=Scope.APP)
    def engine(self, settings: Settings) -> Iterator[Engine]:
        engine = create_sqlite_engine(settings.database_path)
        yield engine
        engine.dispose()

    @provide(scope=Scope.APP)
    def repository(self, engine: Engine) -> Repository:
        return SQLModelRepository(engine)

    @provide(scope=Scope.APP)
    def context_builder(self, repository: Repository) -> ContextBuilder:
        return RepositoryContextBuilder(repository)

    event_broker = provide(EventBroker, scope=Scope.APP)

    @provide(scope=Scope.APP)
    def service(
        self,
        repository: Repository,
        runner: AgentRunner,
        context_builder: ContextBuilder,
        event_broker: EventBroker,
    ) -> AgentThreadService:
        return AgentThreadService(
            repository,
            runner,
            context_builder=context_builder,
            event_broker=event_broker,
        )


class LlmifyAgentProvider(Provider):
    @provide(scope=Scope.APP)
    def chat_model(self, settings: Settings) -> ChatModel:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else None
        )
        return ChatOpenAI(model=settings.agent_model, api_key=api_key)

    @provide(scope=Scope.APP)
    def runner(self, model: ChatModel, settings: Settings) -> AgentRunner:
        return LlmifyAgentRunner(
            model,
            settings.agent_system_prompt,
            tools=default_tools(),
        )


class RunnerOverrideProvider(Provider):
    def __init__(self, runner: AgentRunner) -> None:
        super().__init__()
        self._runner = runner

    @provide(scope=Scope.APP)
    def runner(self) -> AgentRunner:
        return self._runner


def create_container(
    settings: Settings,
    runner: AgentRunner | None = None,
) -> AsyncContainer:
    agent_provider: Provider = (
        RunnerOverrideProvider(runner) if runner is not None else LlmifyAgentProvider()
    )
    return make_async_container(
        ConversationProvider(settings),
        agent_provider,
        FastapiProvider(),
    )
