from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from agent_protocol.models import (
    Item,
    Thread,
    ThreadSnapshot,
    Turn,
    TurnStatus,
    UserMessageItem,
)


class ThreadNotFoundError(LookupError):
    pass


class TurnNotFoundError(LookupError):
    pass


class TurnAlreadyRunningError(RuntimeError):
    pass


class Repository(ABC):
    """Persistence boundary used by the conversation service."""

    @abstractmethod
    async def initialize(self) -> None:
        """Prepare storage and recover state left by an unclean shutdown."""

    @abstractmethod
    async def create_thread(self, thread: Thread) -> None:
        """Persist a new thread."""

    @abstractmethod
    async def get_thread(self, thread_id: UUID) -> ThreadSnapshot:
        """Return a thread with all of its turns and items."""

    @abstractmethod
    async def create_turn(self, turn: Turn, initial_item: UserMessageItem) -> None:
        """Atomically persist a turn and its initial user message."""

    @abstractmethod
    async def add_item(self, item: Item) -> None:
        """Append an item to an existing turn."""

    @abstractmethod
    async def finish_turn(
        self, turn_id: UUID, status: TurnStatus, completed_at: datetime
    ) -> None:
        """Move a running turn to a terminal status."""
