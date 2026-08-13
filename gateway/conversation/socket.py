import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, cast
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect

from .repository import (
    ThreadNotFoundError,
    TurnAlreadyRunningError,
    TurnNotFoundError,
)
from .service import AgentThreadService

JSON = dict[str, Any]


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
        self._methods: dict[str, Callable[[JSON], Awaitable[Any]]] = {
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
        request_id: Any = None
        try:
            request = self._validate_request(raw_request)
            request_id = request.get("id")
            method = self._methods.get(request["method"])
            if method is None:
                raise JsonRpcError(-32601, "Method not found")
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise JsonRpcError(-32602, "Invalid params")
            result = await method(params)
            if "id" in request:
                await self._send({"jsonrpc": "2.0", "id": request_id, "result": result})
        except JsonRpcError as error:
            await self._send_error(request_id, error.code, error.message)
        except (KeyError, TypeError, ValueError) as error:
            await self._send_error(request_id, -32602, f"Invalid params: {error}")
        except (ThreadNotFoundError, TurnNotFoundError) as error:
            await self._send_error(request_id, -32004, f"Not found: {error}")
        except TurnAlreadyRunningError as error:
            await self._send_error(request_id, -32009, f"Turn already running: {error}")
        except Exception:
            await self._send_error(request_id, -32603, "Internal error")

    @staticmethod
    def _validate_request(raw_request: Any) -> JSON:
        if not isinstance(raw_request, dict):
            raise JsonRpcError(-32600, "Invalid Request")
        request = cast(JSON, raw_request)
        if request.get("jsonrpc") != "2.0" or not isinstance(
            request.get("method"), str
        ):
            raise JsonRpcError(-32600, "Invalid Request")
        return request

    async def _create_thread(self, params: JSON) -> Any:
        _require_only(params)
        return _json(await self._service.create_thread())

    async def _get_thread(self, params: JSON) -> Any:
        _require_only(params, "thread_id")
        return _json(await self._service.get_thread(_uuid(params, "thread_id")))

    async def _start_turn(self, params: JSON) -> Any:
        _require_only(params, "thread_id", "message")
        message = params["message"]
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        return _json(
            await self._service.start_turn(_uuid(params, "thread_id"), message)
        )

    async def _steer_turn(self, params: JSON) -> Any:
        _require_only(params, "thread_id", "turn_id", "message")
        message = params["message"]
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        await self._service.steer_turn(
            _uuid(params, "thread_id"), _uuid(params, "turn_id"), message
        )
        return None

    async def _interrupt_turn(self, params: JSON) -> Any:
        _require_only(params, "thread_id", "turn_id")
        await self._service.interrupt_turn(
            _uuid(params, "thread_id"), _uuid(params, "turn_id")
        )
        return None

    async def _subscribe(self, params: JSON) -> Any:
        _require_only(params, "thread_id")
        thread_id = _uuid(params, "thread_id")
        await self._service.get_thread(thread_id)
        if thread_id not in self._subscriptions:
            ready = asyncio.Event()
            self._subscriptions[thread_id] = asyncio.create_task(
                self._forward_events(thread_id, ready),
                name=f"socket-events-{thread_id}",
            )
            await ready.wait()
        return {"subscribed": str(thread_id)}

    async def _unsubscribe(self, params: JSON) -> Any:
        _require_only(params, "thread_id")
        thread_id = _uuid(params, "thread_id")
        task = self._subscriptions.pop(thread_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return {"unsubscribed": str(thread_id)}

    async def _forward_events(self, thread_id: UUID, ready: asyncio.Event) -> None:
        async for event in self._service.subscribe(thread_id, _ready=ready):
            await self._send(
                {
                    "jsonrpc": "2.0",
                    "method": "thread.event",
                    "params": _json(event),
                }
            )

    async def _send_error(self, request_id: Any, code: int, message: str) -> None:
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    async def _send(self, message: JSON) -> None:
        async with self._send_lock:
            await self._socket.send_json(message)


async def handle_websocket(websocket: WebSocket, service: AgentThreadService) -> None:
    await JsonRpcConnection(websocket, service).run()


def _require_only(params: JSON, *names: str) -> None:
    expected = set(names)
    missing = expected - params.keys()
    extra = params.keys() - expected
    if missing:
        raise KeyError(f"missing {', '.join(sorted(missing))}")
    if extra:
        raise KeyError(f"unexpected {', '.join(sorted(extra))}")


def _uuid(params: JSON, name: str) -> UUID:
    value = params[name]
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string UUID")
    return UUID(value)


def _json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json(asdict(value))
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, (UUID, datetime, Enum)):
        return str(value)
    return value
