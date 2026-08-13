import asyncio
from collections.abc import Awaitable, Callable
from typing import assert_never
from uuid import UUID

from agent_protocol.progress import ProgressMode
from agent_protocol.rpc import (
    ConversationRequest,
    CreateThreadRequest,
    GetThreadRequest,
    GetTurnProgressRequest,
    InterruptTurnRequest,
    RpcNotification,
    RpcResult,
    RpcSchema,
    StartTurnRequest,
    SteerTurnRequest,
    SubscribeThreadRequest,
    SubscriptionResult,
    UnsubscribeThreadRequest,
    UnsubscriptionResult,
)

from gateway.conversation.core.service import AgentThreadService

SendMessage = Callable[[RpcSchema], Awaitable[None]]


class ConversationRpcMethods:
    """Execute typed conversation requests for one connection."""

    def __init__(self, service: AgentThreadService, send: SendMessage) -> None:
        self._service = service
        self._send = send
        self._subscriptions: dict[UUID, asyncio.Task[None]] = {}

    async def execute(self, request: ConversationRequest) -> RpcResult:
        match request:
            case CreateThreadRequest():
                return await self._service.create_thread()
            case GetThreadRequest(params=params):
                return await self._service.get_thread(params.thread_id)
            case SubscribeThreadRequest(params=params):
                return await self._subscribe(params.thread_id, params.progress)
            case UnsubscribeThreadRequest(params=params):
                return await self._unsubscribe(params.thread_id)
            case StartTurnRequest(params=params):
                return await self._service.start_turn(params.thread_id, params.message)
            case SteerTurnRequest(params=params):
                await self._service.steer_turn(
                    params.thread_id, params.turn_id, params.message
                )
                return None
            case InterruptTurnRequest(params=params):
                await self._service.interrupt_turn(params.thread_id, params.turn_id)
                return None
            case GetTurnProgressRequest(params=params):
                return await self._service.get_progress(params.thread_id)
            case unexpected:
                assert_never(unexpected)
        raise AssertionError("unreachable")

    async def close(self) -> None:
        tasks = tuple(self._subscriptions.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._subscriptions.clear()

    async def _subscribe(
        self, thread_id: UUID, progress: ProgressMode
    ) -> SubscriptionResult:
        await self._service.get_thread(thread_id)
        await self._stop_subscription(thread_id)

        ready = asyncio.Event()
        self._subscriptions[thread_id] = asyncio.create_task(
            self._forward_events(thread_id, progress, ready),
            name=f"socket-events-{thread_id}",
        )
        await ready.wait()
        return SubscriptionResult(subscribed=thread_id, progress=progress)

    async def _unsubscribe(self, thread_id: UUID) -> UnsubscriptionResult:
        await self._stop_subscription(thread_id)
        return UnsubscriptionResult(unsubscribed=thread_id)

    async def _stop_subscription(self, thread_id: UUID) -> None:
        task = self._subscriptions.pop(thread_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _forward_events(
        self, thread_id: UUID, progress: ProgressMode, ready: asyncio.Event
    ) -> None:
        async for event in self._service.subscribe(
            thread_id, progress=progress, _ready=ready
        ):
            await self._send(RpcNotification(params=event))
