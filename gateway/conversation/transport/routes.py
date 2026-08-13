from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, WebSocket

from gateway.conversation.core.service import AgentThreadService
from gateway.conversation.transport.connection import JsonRpcConnection

router = APIRouter()


@router.websocket("/v1/conversation")
@inject
async def conversation_socket(
    websocket: WebSocket,
    service: FromDishka[AgentThreadService],
) -> None:
    """Serve one long-lived JSON-RPC conversation connection."""
    connection = JsonRpcConnection(websocket, service)
    await connection.run()
