from enum import IntEnum, StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from gateway.conversation.core.events import ThreadEvent
from gateway.conversation.core.models import Thread, ThreadSnapshot, Turn
from gateway.conversation.core.progress import ProgressMode, ProgressResult


class RpcSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RpcMethod(StrEnum):
    THREAD_CREATE = "thread.create"
    THREAD_GET = "thread.get"
    THREAD_SUBSCRIBE = "thread.subscribe"
    THREAD_UNSUBSCRIBE = "thread.unsubscribe"
    TURN_START = "turn.start"
    TURN_STEER = "turn.steer"
    TURN_INTERRUPT = "turn.interrupt"
    TURN_PROGRESS_GET = "turn.progress.get"


class RpcNotificationMethod(StrEnum):
    THREAD_EVENT = "thread.event"


class RpcErrorCode(IntEnum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    RESOURCE_NOT_FOUND = -32004
    TURN_ALREADY_RUNNING = -32009


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


class RpcRequest(RpcSchema):
    """Fields shared by every incoming JSON-RPC request."""

    jsonrpc: Literal["2.0"]
    id: str | int | None = None

    @property
    def expects_response(self) -> bool:
        return "id" in self.model_fields_set


class CreateThreadRequest(RpcRequest):
    method: Literal[RpcMethod.THREAD_CREATE]
    params: EmptyParams = Field(default_factory=EmptyParams)


class GetThreadRequest(RpcRequest):
    method: Literal[RpcMethod.THREAD_GET]
    params: ThreadParams


class SubscribeThreadRequest(RpcRequest):
    method: Literal[RpcMethod.THREAD_SUBSCRIBE]
    params: SubscriptionParams


class UnsubscribeThreadRequest(RpcRequest):
    method: Literal[RpcMethod.THREAD_UNSUBSCRIBE]
    params: ThreadParams


class StartTurnRequest(RpcRequest):
    method: Literal[RpcMethod.TURN_START]
    params: StartTurnParams


class SteerTurnRequest(RpcRequest):
    method: Literal[RpcMethod.TURN_STEER]
    params: SteerTurnParams


class InterruptTurnRequest(RpcRequest):
    method: Literal[RpcMethod.TURN_INTERRUPT]
    params: TurnParams


class GetTurnProgressRequest(RpcRequest):
    method: Literal[RpcMethod.TURN_PROGRESS_GET]
    params: ThreadParams


type ConversationRequest = Annotated[
    CreateThreadRequest
    | GetThreadRequest
    | SubscribeThreadRequest
    | UnsubscribeThreadRequest
    | StartTurnRequest
    | SteerTurnRequest
    | InterruptTurnRequest
    | GetTurnProgressRequest,
    Field(discriminator="method"),
]

CONVERSATION_REQUEST_ADAPTER: TypeAdapter[ConversationRequest] = TypeAdapter(
    ConversationRequest
)


class SubscriptionResult(RpcSchema):
    subscribed: UUID
    progress: ProgressMode


class UnsubscriptionResult(RpcSchema):
    unsubscribed: UUID


type RpcResult = (
    Thread
    | ThreadSnapshot
    | Turn
    | ProgressResult
    | SubscriptionResult
    | UnsubscriptionResult
    | None
)


class RpcErrorData(RpcSchema):
    code: RpcErrorCode
    message: str


class RpcSuccess(RpcSchema):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    result: RpcResult


class RpcFailure(RpcSchema):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    error: RpcErrorData


class RpcNotification(RpcSchema):
    jsonrpc: Literal["2.0"] = "2.0"
    method: Literal[RpcNotificationMethod.THREAD_EVENT] = (
        RpcNotificationMethod.THREAD_EVENT
    )
    params: ThreadEvent


type ConversationServerMessage = RpcSuccess | RpcFailure | RpcNotification


class ConversationProtocol(RpcSchema):
    """Bidirectional message types used by the conversation WebSocket."""

    client_message: ConversationRequest
    server_message: ConversationServerMessage


CONVERSATION_SERVER_MESSAGE_ADAPTER: TypeAdapter[ConversationServerMessage] = (
    TypeAdapter(ConversationServerMessage)
)
CONVERSATION_PROTOCOL_ADAPTER: TypeAdapter[ConversationProtocol] = TypeAdapter(
    ConversationProtocol
)
