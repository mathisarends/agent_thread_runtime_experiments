"""Names used on the wire, mirrored from the gateway's transport layer."""

from enum import StrEnum


class Method(StrEnum):
    THREAD_CREATE = "thread.create"
    THREAD_GET = "thread.get"
    THREAD_SUBSCRIBE = "thread.subscribe"
    THREAD_UNSUBSCRIBE = "thread.unsubscribe"
    TURN_START = "turn.start"
    TURN_STEER = "turn.steer"
    TURN_INTERRUPT = "turn.interrupt"
    TURN_PROGRESS_GET = "turn.progress.get"


class Notification(StrEnum):
    THREAD_EVENT = "thread.event"


class EventType(StrEnum):
    TURN_STARTED = "turn.started"
    ITEM_STARTED = "item.started"
    ITEM_DELTA = "item.delta"
    ITEM_COMPLETED = "item.completed"
    TURN_PROGRESS = "turn.progress"
    TURN_COMPLETED = "turn.completed"
    TURN_INTERRUPTED = "turn.interrupted"
    TURN_FAILED = "turn.failed"


class ItemType(StrEnum):
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class ProgressMode(StrEnum):
    OFF = "off"
    ON_REQUEST = "on_request"
    PROACTIVE = "proactive"


TERMINAL_TURN_EVENTS = frozenset(
    {
        EventType.TURN_COMPLETED,
        EventType.TURN_INTERRUPTED,
        EventType.TURN_FAILED,
    }
)

RUNNING_TURN_STATUS = "running"
