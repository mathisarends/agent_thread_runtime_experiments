from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_conversation_types_are_exposed_as_json_schema_and_openapi_components(
    app: FastAPI,
) -> None:
    with TestClient(app) as client:
        schema_response = client.get("/v1/conversation/schema")
        openapi = client.get("/openapi.json").json()

    assert schema_response.status_code == 200
    assert schema_response.headers["content-type"].startswith("application/schema+json")
    protocol_schema = schema_response.json()
    assert "client_message" in protocol_schema["properties"]
    assert "server_message" in protocol_schema["properties"]

    schemas = openapi["components"]["schemas"]
    request_schema = schemas["ConversationRequest"]
    assert request_schema["discriminator"]["propertyName"] == "method"
    assert len(request_schema["oneOf"]) == 8
    assert "ConversationServerMessage" in schemas
