from uuid import UUID

from .agent import AgentContext
from .repository import Repository


class RepositoryContextBuilder:
    """Build the runner context from the canonical persisted thread state."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def build(self, thread_id: UUID) -> AgentContext:
        snapshot = await self._repository.get_thread(thread_id)
        return AgentContext(items=snapshot.items)
