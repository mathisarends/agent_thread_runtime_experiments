import asyncio

from agent_protocol.rpc import (
    CONVERSATION_REQUEST_ADAPTER,
    ConversationRequest,
    RpcErrorCode,
    RpcErrorData,
    RpcFailure,
    RpcSchema,
    RpcSuccess,
)
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.persistence.repository import (
    ThreadNotFoundError,
    TurnAlreadyRunningError,
    TurnNotFoundError,
)
from gateway.conversation.transport.methods import ConversationRpcMethods


class JsonRpcError(Exception):
    def __init__(self, code: RpcErrorCode, message: str) -> None:
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
                    await self._send_error(
                        None, RpcErrorCode.PARSE_ERROR, "Parse error"
                    )
                    continue
                await self._handle(request)
        except WebSocketDisconnect:
            pass
        finally:
            await self._methods.close()

    async def _handle(self, raw_request: object) -> None:
        request_id = _request_id(raw_request)
        try:
            request = _parse_request(raw_request)
            result = await self._methods.execute(request)
        except Exception as error:
            failure = _rpc_error(error)
            await self._send_error(request_id, failure.code, failure.message)
            return

        if request.expects_response:
            await self._send(RpcSuccess(id=request.id, result=result))

    async def _send_error(
        self, request_id: str | int | None, code: RpcErrorCode, message: str
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


def _parse_request(raw_request: object) -> ConversationRequest:
    try:
        return CONVERSATION_REQUEST_ADAPTER.validate_python(raw_request)
    except ValidationError as error:
        raise _request_error(error) from error


def _request_error(error: ValidationError) -> JsonRpcError:
    issue = error.errors(include_url=False)[0]
    error_type = issue["type"]
    location = issue["loc"]
    if error_type == "union_tag_invalid":
        return JsonRpcError(RpcErrorCode.METHOD_NOT_FOUND, "Method not found")
    if "params" in location:
        return JsonRpcError(RpcErrorCode.INVALID_PARAMS, _validation_message(error))
    return JsonRpcError(RpcErrorCode.INVALID_REQUEST, "Invalid Request")


def _rpc_error(error: Exception) -> JsonRpcError:
    if isinstance(error, JsonRpcError):
        return error
    if isinstance(error, (ThreadNotFoundError, TurnNotFoundError)):
        return JsonRpcError(RpcErrorCode.RESOURCE_NOT_FOUND, f"Not found: {error}")
    if isinstance(error, TurnAlreadyRunningError):
        return JsonRpcError(
            RpcErrorCode.TURN_ALREADY_RUNNING,
            f"Turn already running: {error}",
        )
    if isinstance(error, ValueError):
        return JsonRpcError(RpcErrorCode.INVALID_PARAMS, f"Invalid params: {error}")
    return JsonRpcError(RpcErrorCode.INTERNAL_ERROR, "Internal error")


def _request_id(raw_request: object) -> str | int | None:
    if not isinstance(raw_request, dict):
        return None
    request_id = raw_request.get("id")
    if isinstance(request_id, str) or (
        isinstance(request_id, int) and not isinstance(request_id, bool)
    ):
        return request_id
    return None
