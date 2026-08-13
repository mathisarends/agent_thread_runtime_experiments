from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from gateway.config import Settings
from gateway.container import create_container
from gateway.conversation.agents.contracts import AgentRunner
from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.transport.routes import router as conversation_router


def create_app(
    settings: Settings | None = None,
    runner: AgentRunner | None = None,
) -> FastAPI:
    config = settings or Settings()
    container = create_container(config, runner)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        service = await container.get(AgentThreadService)
        await service.initialize()
        yield
        await container.close()

    application = FastAPI(title="Agent Thread Runtime", lifespan=lifespan)
    application.include_router(conversation_router)
    setup_dishka(container, application)
    return application


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
