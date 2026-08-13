from typing import Any

from agent_protocol.rpc import (
    CONVERSATION_PROTOCOL_ADAPTER,
    CONVERSATION_REQUEST_ADAPTER,
    CONVERSATION_SERVER_MESSAGE_ADAPTER,
)
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

schema_router = APIRouter(tags=["conversation schema"])


@schema_router.get(
    "/v1/conversation/schema",
    response_class=JSONResponse,
    summary="Conversation WebSocket JSON Schema",
    description=(
        "JSON Schema for client-to-server requests and server-to-client messages "
        "on `/v1/conversation`."
    ),
)
async def conversation_schema() -> JSONResponse:
    return JSONResponse(
        CONVERSATION_PROTOCOL_ADAPTER.json_schema(mode="serialization"),
        media_type="application/schema+json",
    )


def install_schema_router(application: FastAPI) -> None:
    """Expose the schema endpoint and add WebSocket types to OpenAPI components."""
    application.include_router(schema_router)
    openapi_schema = application.openapi()
    schemas = openapi_schema.setdefault("components", {}).setdefault("schemas", {})

    _add_schema(schemas, "ConversationRequest", CONVERSATION_REQUEST_ADAPTER)
    _add_schema(
        schemas,
        "ConversationServerMessage",
        CONVERSATION_SERVER_MESSAGE_ADAPTER,
    )


def _add_schema(
    components: dict[str, Any], name: str, adapter: TypeAdapter[Any]
) -> None:
    schema = adapter.json_schema(
        mode="serialization",
        ref_template="#/components/schemas/{model}",
    )
    definitions = schema.pop("$defs", {})
    components.update(definitions)
    components[name] = schema
