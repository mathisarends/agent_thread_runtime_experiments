from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from gateway.conversation import AgentThreadService, FakeAgentRunner, SQLiteRepository
from gateway.conversation.routes import create_router


def create_app(
    service: AgentThreadService | None = None,
) -> FastAPI:
    repository = SQLiteRepository()
    runtime = service or AgentThreadService(repository, FakeAgentRunner())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        await runtime.initialize()
        yield

    application = FastAPI(title="Agent Thread Runtime", lifespan=lifespan)
    application.include_router(create_router(runtime))
    return application


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
