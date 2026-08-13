from fastapi import APIRouter, WebSocket

from .service import AgentThreadService
from .socket import handle_websocket


def create_router(service: AgentThreadService) -> APIRouter:
    """Expose only the long-lived JSON-RPC WebSocket transport."""
    router = APIRouter()

    @router.websocket("/v1/conversation")
    async def conversation_socket(websocket: WebSocket) -> None:
        await handle_websocket(websocket, service)

    return router
