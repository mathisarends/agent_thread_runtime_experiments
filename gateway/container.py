from collections.abc import Iterator

from dishka import Provider, Scope, make_async_container, provide
from dishka.async_container import AsyncContainer
from dishka.integrations.fastapi import FastapiProvider
from sqlalchemy.engine import Engine

from .config import Settings
from .conversation.agent import AgentRunner, FakeAgentRunner
from .conversation.database import create_sqlite_engine
from .conversation.events import EventBroker
from .conversation.repository import Repository, SQLModelRepository
from .conversation.service import AgentThreadService


class ConversationProvider(Provider):
    def __init__(self, settings: Settings, runner: AgentRunner) -> None:
        super().__init__()
        self._settings = settings
        self._runner = runner

    @provide(scope=Scope.APP)
    def settings(self) -> Settings:
        return self._settings

    @provide(scope=Scope.APP)
    def runner(self) -> AgentRunner:
        return self._runner

    @provide(scope=Scope.APP)
    def engine(self, settings: Settings) -> Iterator[Engine]:
        engine = create_sqlite_engine(settings.database_path)
        yield engine
        engine.dispose()

    @provide(scope=Scope.APP)
    def repository(self, engine: Engine) -> Repository:
        return SQLModelRepository(engine)

    event_broker = provide(EventBroker, scope=Scope.APP)

    @provide(scope=Scope.APP)
    def service(
        self,
        repository: Repository,
        runner: AgentRunner,
        event_broker: EventBroker,
    ) -> AgentThreadService:
        return AgentThreadService(
            repository,
            runner,
            event_broker=event_broker,
        )


def create_container(
    settings: Settings,
    runner: AgentRunner | None = None,
) -> AsyncContainer:
    return make_async_container(
        ConversationProvider(settings, runner or FakeAgentRunner()),
        FastapiProvider(),
    )
