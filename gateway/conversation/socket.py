import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from gateway.conversation.repository import (
    ThreadNotFoundError,
    TurnAlreadyRunningError,
    TurnNotFoundError,
)
from gateway.conversation.rpc import (
    EmptyParams,
    RpcErrorData,
    RpcFailure,
    RpcNotification,
    RpcRequest,
    RpcSchema,
    RpcSuccess,
    StartTurnParams,
    SteerTurnParams,
    SubscriptionResult,
    ThreadParams,
    TurnParams,
    UnsubscriptionResult,
)
from gateway.conversation.service import AgentThreadService


class Socket(Protocol):
    async def accept(self) -> None: ...

    async def receive_json(self) -> Any: ...

    async def send_json(self, data: Any) -> None: ...


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class JsonRpcConnection:
    """JSON-RPC 2.0 commands and event notifications on one WebSocket."""

    def __init__(self, socket: Socket, service: AgentThreadService) -> None:
        self._socket = socket
        self._service = service
        self._send_lock = asyncio.Lock()
        self._subscriptions: dict[UUID, asyncio.Task[None]] = {}
        self._methods: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = {
            "thread.create": self._create_thread,
            "thread.get": self._get_thread,
            "thread.subscribe": self._subscribe,
            "thread.unsubscribe": self._unsubscribe,
            "turn.start": self._start_turn,
            "turn.steer": self._steer_turn,
            "turn.interrupt": self._interrupt_turn,
        }

    async def run(self) -> None:
        await self._socket.accept()
        try:
            while True:
                try:
                    request = await self._socket.receive_json()
                except ValueError:
                    await self._send_error(None, -32700, "Parse error")
                    continue
                await self._handle(request)
        except WebSocketDisconnect:
            pass
        finally:
            for task in self._subscriptions.values():
                task.cancel()
            if self._subscriptions:
                await asyncio.gather(
                    *self._subscriptions.values(), return_exceptions=True
                )

    async def _handle(self, raw_request: Any) -> None:
        request_id: str | int | None = None
        try:
            try:
                request = RpcRequest.model_validate(raw_request)
            except ValidationError as error:
                raise JsonRpcError(-32600, "Invalid Request") from error
            request_id = request.id
            method = self._methods.get(request.method)
            if method is None:
                raise JsonRpcError(-32601, "Method not found")
            result = await method(request.params)
            if request.expects_response:
                await self._send(RpcSuccess(id=request.id, result=result))
        except JsonRpcError as error:
            await self._send_error(request_id, error.code, error.message)
        except ValidationError as error:
            await self._send_error(request_id, -32602, _validation_message(error))
        except (ThreadNotFoundError, TurnNotFoundError) as error:
            await self._send_error(request_id, -32004, f"Not found: {error}")
        except TurnAlreadyRunningError as error:
            await self._send_error(request_id, -32009, f"Turn already running: {error}")
        except ValueError as error:
            await self._send_error(request_id, -32602, f"Invalid params: {error}")
        except Exception:
            await self._send_error(request_id, -32603, "Internal error")

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

    async def _subscribe(self, raw: dict[str, Any]) -> SubscriptionResult:
        params = ThreadParams.model_validate(raw)
        await self._service.get_thread(params.thread_id)
        if params.thread_id not in self._subscriptions:
            ready = asyncio.Event()
            self._subscriptions[params.thread_id] = asyncio.create_task(
                self._forward_events(params.thread_id, ready),
                name=f"socket-events-{params.thread_id}",
            )
            await ready.wait()
        return SubscriptionResult(subscribed=params.thread_id)

    async def _unsubscribe(self, raw: dict[str, Any]) -> UnsubscriptionResult:
        params = ThreadParams.model_validate(raw)
        task = self._subscriptions.pop(params.thread_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return UnsubscriptionResult(unsubscribed=params.thread_id)

    async def _forward_events(self, thread_id: UUID, ready: asyncio.Event) -> None:
        async for event in self._service.subscribe(thread_id, _ready=ready):
            await self._send(RpcNotification(method="thread.event", params=event))

    async def _send_error(
        self, request_id: str | int | None, code: int, message: str
    ) -> None:
        await self._send(
            RpcFailure(
                id=request_id,
                error=RpcErrorData(code=code, message=message),
            )
        )

    async def _send(self, message: RpcSchema) -> None:
        async with self._send_lock:
            await self._socket.send_json(message.model_dump(mode="json"))


async def handle_websocket(websocket: WebSocket, service: AgentThreadService) -> None:
    await JsonRpcConnection(websocket, service).run()


def _validation_message(error: ValidationError) -> str:
    issue = error.errors(include_url=False)[0]
    location = ".".join(str(part) for part in issue["loc"])
    return f"Invalid params at {location}: {issue['msg']}"
