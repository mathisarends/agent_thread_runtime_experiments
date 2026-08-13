import asyncio
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.persistence.repository import (
    ThreadNotFoundError,
    TurnAlreadyRunningError,
    TurnNotFoundError,
)
from gateway.conversation.transport.methods import (
    ConversationRpcMethods,
    UnknownRpcMethodError,
)
from gateway.conversation.transport.schemas import (
    RpcErrorData,
    RpcFailure,
    RpcRequest,
    RpcSchema,
    RpcSuccess,
)


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class JsonRpcConnection:
    """JSON-RPC 2.0 commands and event notifications on one WebSocket."""

    def __init__(self, socket: WebSocket, service: AgentThreadService) -> None:
        self._socket = socket
        self._send_lock = asyncio.Lock()
        self._methods = ConversationRpcMethods(service, self._send)

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
            await self._methods.close()

    async def _handle(self, raw_request: Any) -> None:
        request_id: str | int | None = None
        try:
            try:
                request = RpcRequest.model_validate(raw_request)
            except ValidationError as error:
                raise JsonRpcError(-32600, "Invalid Request") from error
            request_id = request.id
            result = await self._methods.execute(request.method, request.params)
            if request.expects_response:
                await self._send(RpcSuccess(id=request.id, result=result))
        except UnknownRpcMethodError:
            await self._send_error(request_id, -32601, "Method not found")
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


def _validation_message(error: ValidationError) -> str:
    issue = error.errors(include_url=False)[0]
    location = ".".join(str(part) for part in issue["loc"])
    return f"Invalid params at {location}: {issue['msg']}"
