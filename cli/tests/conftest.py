from collections.abc import Callable
from typing import Any

import pytest
from agent_cli.console import Console
from agent_cli.session import Session
from agent_cli.state import CliState
from agent_cli.theme import Theme


class FakeRpc:
    """Records requests and replays canned results."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.results = results or {}

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, params))
        result = self.results.get(method)
        return result(params) if callable(result) else result


@pytest.fixture
def console() -> Console:
    return Console(Theme(enabled=False))


@pytest.fixture
def make_session(console: Console) -> Callable[..., Session]:
    def factory(rpc: FakeRpc | None = None, state: CliState | None = None) -> Session:
        return Session(rpc or FakeRpc(), console, state=state)  # type: ignore[arg-type]

    return factory
