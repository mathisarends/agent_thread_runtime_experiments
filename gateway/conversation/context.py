from uuid import UUID

from gateway.conversation.agent import AgentContext
from gateway.conversation.repository import Repository


class RepositoryContextBuilder:
    """Build the runner context from the canonical persisted thread state."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def build(self, thread_id: UUID) -> AgentContext:
        snapshot = await self._repository.get_thread(thread_id)
        return AgentContext(items=snapshot.items)
