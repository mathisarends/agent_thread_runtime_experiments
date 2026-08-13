from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field

from gateway.conversation.core.models import Schema

type ProgressMessage = Annotated[str, Field(min_length=1, max_length=240)]


class ProgressMode(StrEnum):
    OFF = "off"
    ON_REQUEST = "on_request"
    PROACTIVE = "proactive"

    @property
    def enables_agent(self) -> bool:
        return self is not ProgressMode.OFF


class ProgressImportance(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ProgressSnapshot(Schema):
    thread_id: UUID
    turn_id: UUID
    message: ProgressMessage
    importance: ProgressImportance


class ProgressResult(Schema):
    progress: ProgressSnapshot | None
