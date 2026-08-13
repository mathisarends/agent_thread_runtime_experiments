from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, WebSocket

from gateway.conversation.service import AgentThreadService
from gateway.conversation.socket import handle_websocket


def create_router() -> APIRouter:
    """Expose only the long-lived JSON-RPC WebSocket transport."""
    router = APIRouter()

    @router.websocket("/v1/conversation")
    @inject
    async def conversation_socket(
        websocket: WebSocket,
        service: FromDishka[AgentThreadService],
    ) -> None:
        await handle_websocket(websocket, service)

    return router
