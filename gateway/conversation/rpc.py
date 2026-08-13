from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from gateway.conversation.progress import ProgressMode


class RpcSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RpcRequest(RpcSchema):
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)

    @property
    def expects_response(self) -> bool:
        return "id" in self.model_fields_set


class EmptyParams(RpcSchema):
    pass


class ThreadParams(RpcSchema):
    thread_id: UUID


class SubscriptionParams(ThreadParams):
    progress: ProgressMode = ProgressMode.OFF


class StartTurnParams(ThreadParams):
    message: str = Field(min_length=1)


class TurnParams(ThreadParams):
    turn_id: UUID


class SteerTurnParams(TurnParams):
    message: str = Field(min_length=1)


class SubscriptionResult(RpcSchema):
    subscribed: UUID
    progress: ProgressMode


class UnsubscriptionResult(RpcSchema):
    unsubscribed: UUID


class RpcErrorData(RpcSchema):
    code: int
    message: str


class RpcSuccess(RpcSchema):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    result: Any


class RpcFailure(RpcSchema):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    error: RpcErrorData


class RpcNotification(RpcSchema):
    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: Any
