import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from agent_cli.rpc import JsonRpcClient, RpcError


class FakeSocket:
    """A WebSocket that records sends and replays queued inbound frames."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._inbound: asyncio.Queue[str | None] = asyncio.Queue()

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True
        await self._inbound.put(None)

    def push(self, message: Any) -> None:
        self.push_raw(json.dumps(message))

    def push_raw(self, raw: str) -> None:
        self._inbound.put_nowait(raw)

    def finish(self) -> None:
        self._inbound.put_nowait(None)

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            raw = await self._inbound.get()
            if raw is None:
                return
            yield raw


def make_client(socket: FakeSocket) -> JsonRpcClient:
    return JsonRpcClient(socket)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_request_resolves_with_the_matching_response() -> None:
    socket = FakeSocket()
    client = make_client(socket)

    pending = asyncio.create_task(client.request("thread.create", {"a": 1}))
    await asyncio.sleep(0)
    socket.push({"jsonrpc": "2.0", "id": 1, "result": {"id": "thread-1"}})

    assert await pending == {"id": "thread-1"}
    assert socket.sent == [
        {"jsonrpc": "2.0", "id": 1, "method": "thread.create", "params": {"a": 1}}
    ]
    await client.close()


@pytest.mark.asyncio
async def test_request_without_params_omits_the_field() -> None:
    socket = FakeSocket()
    client = make_client(socket)

    pending = asyncio.create_task(client.request("thread.create"))
    await asyncio.sleep(0)
    socket.push({"jsonrpc": "2.0", "id": 1, "result": None})
    await pending

    assert "params" not in socket.sent[0]
    await client.close()


@pytest.mark.asyncio
async def test_error_responses_raise_rpc_error() -> None:
    socket = FakeSocket()
    client = make_client(socket)

    pending = asyncio.create_task(client.request("turn.start"))
    await asyncio.sleep(0)
    socket.push(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad params"}}
    )

    with pytest.raises(RpcError, match="bad params") as excinfo:
        await pending
    assert excinfo.value.code == -32602
    await client.close()


@pytest.mark.asyncio
async def test_notifications_are_queued_and_other_traffic_is_ignored() -> None:
    socket = FakeSocket()
    client = make_client(socket)

    socket.push("not an object")
    socket.push({"jsonrpc": "2.0", "method": "unrelated", "params": {}})
    socket.push({"jsonrpc": "2.0", "id": 99, "result": "no such request"})
    socket.push(
        {"jsonrpc": "2.0", "method": "thread.event", "params": {"type": "turn.started"}}
    )

    events = client.notifications()
    assert await asyncio.wait_for(anext(events), timeout=1) == {"type": "turn.started"}
    await client.close()


@pytest.mark.asyncio
async def test_a_broken_frame_fails_pending_requests() -> None:
    socket = FakeSocket()
    client = make_client(socket)

    pending = asyncio.create_task(client.request("thread.get"))
    await asyncio.sleep(0)
    socket.push_raw("{not json")

    with pytest.raises(json.JSONDecodeError):
        await pending
    await client.close()


@pytest.mark.asyncio
async def test_pending_requests_fail_when_the_socket_closes() -> None:
    socket = FakeSocket()
    client = make_client(socket)

    pending = asyncio.create_task(client.request("thread.get"))
    await asyncio.sleep(0)
    socket.finish()

    with pytest.raises(ConnectionError):
        await pending
    await client.close()
    assert socket.closed
