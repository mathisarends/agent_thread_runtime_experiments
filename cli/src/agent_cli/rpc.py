"""JSON-RPC 2.0 over a single WebSocket, multiplexing replies and events."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from websockets.asyncio.client import ClientConnection

from agent_cli.protocol import Notification


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"JSON-RPC error {code}: {message}")
        self.code = code
        self.message = message


class JsonRpcClient:
    """Multiplex JSON-RPC responses and notifications on one WebSocket."""

    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._receiver = asyncio.create_task(self._receive(), name="rpc-receiver")

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params
        try:
            await self._socket.send(json.dumps(request))
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def notifications(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await self._notifications.get()

    async def close(self) -> None:
        await self._socket.close()
        self._receiver.cancel()
        with suppress(asyncio.CancelledError):
            await self._receiver

    async def _receive(self) -> None:
        try:
            async for raw_message in self._socket:
                message = json.loads(raw_message)
                if isinstance(message, dict):
                    await self._dispatch(message)
        except Exception as error:
            self._fail_pending(error)
        finally:
            self._fail_pending(ConnectionError("WebSocket closed"))

    async def _dispatch(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id is None:
            if message.get("method") == Notification.THREAD_EVENT:
                await self._notifications.put(message["params"])
            return
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        if "error" in message:
            error = message["error"]
            future.set_exception(RpcError(error["code"], error["message"]))
        else:
            future.set_result(message.get("result"))

    def _fail_pending(self, error: BaseException) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
