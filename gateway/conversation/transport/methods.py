import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from gateway.conversation.core.progress import ProgressMode
from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.transport.schemas import (
    EmptyParams,
    RpcNotification,
    RpcSchema,
    StartTurnParams,
    SteerTurnParams,
    SubscriptionParams,
    SubscriptionResult,
    ThreadParams,
    TurnParams,
    UnsubscriptionResult,
)

SendMessage = Callable[[RpcSchema], Awaitable[None]]
RpcMethod = Callable[[dict[str, Any]], Awaitable[Any]]


class UnknownRpcMethodError(LookupError):
    pass


class ConversationRpcMethods:
    """Conversation commands and the subscriptions owned by one connection."""

    def __init__(self, service: AgentThreadService, send: SendMessage) -> None:
        self._service = service
        self._send = send
        self._subscriptions: dict[UUID, asyncio.Task[None]] = {}
        self._handlers: dict[str, RpcMethod] = {
            "thread.create": self._create_thread,
            "thread.get": self._get_thread,
            "thread.subscribe": self._subscribe,
            "thread.unsubscribe": self._unsubscribe,
            "turn.start": self._start_turn,
            "turn.steer": self._steer_turn,
            "turn.interrupt": self._interrupt_turn,
            "turn.progress.get": self._get_progress,
        }

    async def execute(self, method: str, params: dict[str, Any]) -> Any:
        handler = self._handlers.get(method)
        if handler is None:
            raise UnknownRpcMethodError(method)
        return await handler(params)

    async def close(self) -> None:
        tasks = tuple(self._subscriptions.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._subscriptions.clear()

    async def _create_thread(self, raw: dict[str, Any]) -> Any:
        EmptyParams.model_validate(raw)
        return await self._service.create_thread()

    async def _get_thread(self, raw: dict[str, Any]) -> Any:
        params = ThreadParams.model_validate(raw)
        return await self._service.get_thread(params.thread_id)

    async def _start_turn(self, raw: dict[str, Any]) -> Any:
        params = StartTurnParams.model_validate(raw)
        return await self._service.start_turn(params.thread_id, params.message)

    async def _steer_turn(self, raw: dict[str, Any]) -> None:
        params = SteerTurnParams.model_validate(raw)
        await self._service.steer_turn(params.thread_id, params.turn_id, params.message)

    async def _interrupt_turn(self, raw: dict[str, Any]) -> None:
        params = TurnParams.model_validate(raw)
        await self._service.interrupt_turn(params.thread_id, params.turn_id)

    async def _get_progress(self, raw: dict[str, Any]) -> Any:
        params = ThreadParams.model_validate(raw)
        return await self._service.get_progress(params.thread_id)

    async def _subscribe(self, raw: dict[str, Any]) -> SubscriptionResult:
        params = SubscriptionParams.model_validate(raw)
        await self._service.get_thread(params.thread_id)
        await self._stop_subscription(params.thread_id)

        ready = asyncio.Event()
        self._subscriptions[params.thread_id] = asyncio.create_task(
            self._forward_events(params.thread_id, params.progress, ready),
            name=f"socket-events-{params.thread_id}",
        )
        await ready.wait()
        return SubscriptionResult(
            subscribed=params.thread_id,
            progress=params.progress,
        )

    async def _unsubscribe(self, raw: dict[str, Any]) -> UnsubscriptionResult:
        params = ThreadParams.model_validate(raw)
        await self._stop_subscription(params.thread_id)
        return UnsubscriptionResult(unsubscribed=params.thread_id)

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
            await self._send(RpcNotification(method="thread.event", params=event))
