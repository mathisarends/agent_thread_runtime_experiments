import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from gateway.conversation.agents.contracts import FakeAgentRunner
from gateway.conversation.core.models import Thread, ThreadSnapshot
from gateway.conversation.core.progress import ProgressMode
from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.persistence.database import create_sqlite_engine
from gateway.conversation.persistence.sqlmodel import SQLModelRepository
from gateway.conversation.transport.methods import ConversationRpcMethods, SendMessage
from gateway.conversation.transport.schemas import (
    CreateThreadRequest,
    EmptyParams,
    GetThreadRequest,
    RpcMethod,
    RpcNotification,
    RpcSchema,
    SubscribeThreadRequest,
    SubscriptionParams,
    ThreadParams,
    UnsubscribeThreadRequest,
    UnsubscriptionResult,
)


async def _noop_send(message: RpcSchema) -> None:
    del message


def _collector() -> tuple[list[RpcSchema], SendMessage]:
    sent: list[RpcSchema] = []

    async def send(message: RpcSchema) -> None:
        sent.append(message)

    return sent, send


@pytest_asyncio.fixture
async def service() -> AsyncIterator[AgentThreadService]:
    engine = create_sqlite_engine(":memory:")
    instance = AgentThreadService(SQLModelRepository(engine), FakeAgentRunner())
    await instance.initialize()
    yield instance
    engine.dispose()


@pytest.mark.asyncio
async def test_execute_creates_a_thread(service: AgentThreadService) -> None:
    methods = ConversationRpcMethods(service, _noop_send)

    result = await methods.execute(
        CreateThreadRequest(
            jsonrpc="2.0", id=1, method=RpcMethod.THREAD_CREATE, params=EmptyParams()
        )
    )

    assert isinstance(result, Thread)
    assert isinstance(result.id, UUID)


@pytest.mark.asyncio
async def test_execute_gets_the_thread_snapshot(service: AgentThreadService) -> None:
    methods = ConversationRpcMethods(service, _noop_send)
    thread = await service.create_thread()

    result = await methods.execute(
        GetThreadRequest(
            jsonrpc="2.0",
            id=1,
            method=RpcMethod.THREAD_GET,
            params=ThreadParams(thread_id=thread.id),
        )
    )

    assert isinstance(result, ThreadSnapshot)
    assert result.thread.id == thread.id


def _subscribe_request(thread_id: UUID) -> SubscribeThreadRequest:
    return SubscribeThreadRequest(
        jsonrpc="2.0",
        id=1,
        method=RpcMethod.THREAD_SUBSCRIBE,
        params=SubscriptionParams(thread_id=thread_id, progress=ProgressMode.OFF),
    )


@pytest.mark.asyncio
async def test_subscribing_twice_forwards_each_event_only_once(
    service: AgentThreadService,
) -> None:
    sent, send = _collector()
    methods = ConversationRpcMethods(service, send)
    thread = await service.create_thread()

    await methods.execute(_subscribe_request(thread.id))
    await methods.execute(_subscribe_request(thread.id))

    await service.start_turn(thread.id, "hello")
    await asyncio.sleep(0.05)
    started = [
        message
        for message in sent
        if isinstance(message, RpcNotification)
        and message.params.type == "turn.started"
    ]
    assert len(started) == 1

    await methods.close()


@pytest.mark.asyncio
async def test_unsubscribing_stops_forwarding_events(
    service: AgentThreadService,
) -> None:
    sent, send = _collector()
    methods = ConversationRpcMethods(service, send)
    thread = await service.create_thread()
    await methods.execute(_subscribe_request(thread.id))

    result = await methods.execute(
        UnsubscribeThreadRequest(
            jsonrpc="2.0",
            id=2,
            method=RpcMethod.THREAD_UNSUBSCRIBE,
            params=ThreadParams(thread_id=thread.id),
        )
    )

    await service.start_turn(thread.id, "hello")
    await asyncio.sleep(0.05)

    assert isinstance(result, UnsubscriptionResult)
    assert result.unsubscribed == thread.id
    assert not any(isinstance(message, RpcNotification) for message in sent)


@pytest.mark.asyncio
async def test_close_cancels_every_active_subscription(
    service: AgentThreadService,
) -> None:
    sent, send = _collector()
    methods = ConversationRpcMethods(service, send)
    first = await service.create_thread()
    second = await service.create_thread()
    await methods.execute(_subscribe_request(first.id))
    await methods.execute(_subscribe_request(second.id))

    await methods.close()

    await service.start_turn(first.id, "hello")
    await service.start_turn(second.id, "hello")
    await asyncio.sleep(0.05)
    assert not any(isinstance(message, RpcNotification) for message in sent)
