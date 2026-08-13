import argparse
import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.client import ClientConnection, connect


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"JSON-RPC error {code}: {message}")
        self.code = code
        self.message = message


class JsonRpcClient:
    """Multiplex JSON-RPC responses and notifications on one WebSocket."""

    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._receiver = asyncio.create_task(self._receive(), name="rpc-receiver")

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params
        try:
            await self._socket.send(json.dumps(request))
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def notifications(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await self._notifications.get()

    async def close(self) -> None:
        await self._socket.close()
        self._receiver.cancel()
        with suppress(asyncio.CancelledError):
            await self._receiver

    async def _receive(self) -> None:
        try:
            async for raw_message in self._socket:
                message = json.loads(raw_message)
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if request_id is not None:
                    future = self._pending.get(request_id)
                    if future is None:
                        continue
                    if "error" in message:
                        error = message["error"]
                        future.set_exception(RpcError(error["code"], error["message"]))
                    else:
                        future.set_result(message.get("result"))
                elif message.get("method") == "thread.event":
                    await self._notifications.put(message["params"])
        except Exception as error:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("WebSocket closed"))


@dataclass(slots=True)
class CliState:
    thread_id: str | None = None
    active_turn_id: str | None = None
    finished_turn_ids: set[str] = field(default_factory=set)
    subscribed_thread_ids: set[str] = field(default_factory=set)
    streaming_item_ids: set[str] = field(default_factory=set)
    progress_modes: dict[str, str] = field(default_factory=dict)


HELP = """Commands:
  <text>                    start a turn, or steer the active turn
  /new                     create and subscribe to a new thread
  /use THREAD_ID           switch to and subscribe to an existing thread
  /get                     print the current persisted snapshot
  /start TEXT              explicitly start a turn
  /steer TEXT              explicitly steer the active turn
  /interrupt               interrupt the active turn
  /subscribe [THREAD_ID]   subscribe to live events
  /unsubscribe [THREAD_ID] unsubscribe from live events
  /progress MODE           set off, on_request, or proactive for this thread
  /status                  print the active turn's latest progress
  /rpc METHOD [JSON]       send an arbitrary JSON-RPC request
  /help                    show this help
  /quit                    close the connection
"""


async def run_interactive(url: str, initial_thread: str | None) -> None:
    async with connect(url) as socket:
        rpc = JsonRpcClient(socket)
        state = CliState()
        printer = asyncio.create_task(_print_notifications(rpc, state))
        try:
            if initial_thread is None:
                await _new_thread(rpc, state)
            else:
                await _use_thread(rpc, state, initial_thread)
            print(HELP)
            while True:
                line = (await asyncio.to_thread(input, "agent> ")).strip()
                if not line:
                    continue
                if line in {"/quit", "/exit"}:
                    break
                try:
                    await _execute_command(rpc, state, line)
                except (RpcError, ValueError, KeyError) as error:
                    print(f"error: {error}")
        finally:
            printer.cancel()
            with suppress(asyncio.CancelledError):
                await printer
            await rpc.close()


async def run_once(url: str, message: str, thread_id: str | None = None) -> None:
    """Send one message and wait for its terminal event (useful for smoke tests)."""
    async with connect(url) as socket:
        rpc = JsonRpcClient(socket)
        try:
            if thread_id is None:
                thread = await rpc.request("thread.create")
                thread_id = thread["id"]
            await rpc.request("thread.subscribe", {"thread_id": thread_id})
            turn = await rpc.request(
                "turn.start", {"thread_id": thread_id, "message": message}
            )
            print(f"thread: {thread_id}")
            print(f"turn:   {turn['id']}")
            streaming_item_ids: set[str] = set()
            async for event in rpc.notifications():
                _render_event(event, streaming_item_ids=streaming_item_ids)
                if event["type"] in {
                    "turn.completed",
                    "turn.interrupted",
                    "turn.failed",
                }:
                    break
        finally:
            await rpc.close()


async def _execute_command(rpc: JsonRpcClient, state: CliState, line: str) -> None:
    command, _, argument = line.partition(" ")
    if command == "/help":
        print(HELP)
    elif command == "/new":
        await _new_thread(rpc, state)
    elif command == "/use":
        await _use_thread(rpc, state, _required(argument, "thread ID"))
    elif command == "/get":
        snapshot = await rpc.request(
            "thread.get", {"thread_id": _current_thread(state)}
        )
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    elif command == "/start":
        await _start(rpc, state, _required(argument, "message"))
    elif command == "/steer":
        await _steer(rpc, state, _required(argument, "message"))
    elif command == "/interrupt":
        await rpc.request(
            "turn.interrupt",
            {
                "thread_id": _current_thread(state),
                "turn_id": _active_turn(state),
            },
        )
        print("interrupt requested")
    elif command == "/progress":
        mode = _required(argument, "progress mode")
        if mode not in {"off", "on_request", "proactive"}:
            raise ValueError("progress mode must be off, on_request, or proactive")
        target = _current_thread(state)
        await rpc.request("thread.subscribe", {"thread_id": target, "progress": mode})
        state.progress_modes[target] = mode
        print(f"progress mode: {mode}")
    elif command == "/status":
        result = await rpc.request(
            "turn.progress.get", {"thread_id": _current_thread(state)}
        )
        progress = result["progress"]
        print(progress["message"] if progress else "no active progress")
    elif command == "/subscribe":
        target = argument.strip() or _current_thread(state)
        await rpc.request("thread.subscribe", {"thread_id": target})
        state.subscribed_thread_ids.add(target)
        state.progress_modes[target] = "off"
        print(f"subscribed to {target} (future live events only)")
    elif command == "/unsubscribe":
        target = argument.strip() or _current_thread(state)
        await rpc.request("thread.unsubscribe", {"thread_id": target})
        state.subscribed_thread_ids.discard(target)
        state.progress_modes.pop(target, None)
        print(f"unsubscribed from {target}")
    elif command == "/rpc":
        await _raw_rpc(rpc, argument)
    elif command.startswith("/"):
        raise ValueError(f"unknown command {command}; use /help")
    elif state.active_turn_id is None:
        await _start(rpc, state, line)
    else:
        await _steer(rpc, state, line)


async def _new_thread(rpc: JsonRpcClient, state: CliState) -> None:
    thread = await rpc.request("thread.create")
    await _use_thread(rpc, state, thread["id"])


async def _use_thread(rpc: JsonRpcClient, state: CliState, thread_id: str) -> None:
    snapshot = await rpc.request("thread.get", {"thread_id": thread_id})
    await rpc.request("thread.subscribe", {"thread_id": thread_id})
    state.subscribed_thread_ids.add(thread_id)
    state.progress_modes[thread_id] = "off"
    state.thread_id = thread_id
    active = next(
        (turn for turn in snapshot["turns"] if turn["status"] == "running"), None
    )
    state.active_turn_id = active["id"] if active else None
    print(f"using thread {thread_id}")


async def _start(rpc: JsonRpcClient, state: CliState, message: str) -> None:
    turn = await rpc.request(
        "turn.start",
        {"thread_id": _current_thread(state), "message": message},
    )
    if turn["id"] not in state.finished_turn_ids:
        state.active_turn_id = turn["id"]
    print(f"started turn {turn['id']}")


async def _steer(rpc: JsonRpcClient, state: CliState, message: str) -> None:
    await rpc.request(
        "turn.steer",
        {
            "thread_id": _current_thread(state),
            "turn_id": _active_turn(state),
            "message": message,
        },
    )
    print("steering delivered")


async def _raw_rpc(rpc: JsonRpcClient, argument: str) -> None:
    method, _, raw_params = argument.strip().partition(" ")
    if not method:
        raise ValueError("usage: /rpc METHOD [JSON_OBJECT]")
    params = json.loads(raw_params) if raw_params else None
    if params is not None and not isinstance(params, dict):
        raise ValueError("RPC params must be a JSON object")
    result = await rpc.request(method, params)
    print(json.dumps(result, indent=2, ensure_ascii=False))


async def _print_notifications(rpc: JsonRpcClient, state: CliState) -> None:
    async for event in rpc.notifications():
        _process_notification(state, event)


def _process_notification(state: CliState, event: dict[str, Any]) -> None:
    thread_id = event.get("thread_id")
    is_current = thread_id == state.thread_id
    if is_current:
        if event["type"] == "turn.started":
            state.active_turn_id = event["turn_id"]
        elif event["type"] in {
            "turn.completed",
            "turn.interrupted",
            "turn.failed",
        }:
            state.finished_turn_ids.add(event["turn_id"])
            state.active_turn_id = None
    _render_event(
        event,
        thread_id=None if is_current else thread_id,
        streaming_item_ids=state.streaming_item_ids,
    )


def _render_event(
    event: dict[str, Any],
    *,
    thread_id: str | None = None,
    streaming_item_ids: set[str] | None = None,
) -> None:
    prefix = f"[thread {thread_id}] " if thread_id is not None else ""
    event_type = event["type"]
    streamed = streaming_item_ids if streaming_item_ids is not None else set()
    if event_type == "item.delta":
        if event["item_id"] not in streamed:
            streamed.add(event["item_id"])
            print(f"\n{prefix}agent> ", end="", flush=True)
        print(event["delta"], end="", flush=True)
    elif event_type == "item.completed":
        item = event["item"]
        if item["type"] == "user_message":
            print(f"\n{prefix}user> {item['content']}")
        elif item["type"] == "agent_message":
            item_id = item.get("id")
            if item_id in streamed:
                streamed.discard(item_id)
                print()
            else:
                print(f"\n{prefix}agent> {item['content']}")
        elif item["type"] == "tool_call":
            print(f"\n{prefix}tool> {item['name']} {json.dumps(item['arguments'])}")
        elif item["type"] == "tool_result":
            print(f"\n{prefix}result> {json.dumps(item['output'], ensure_ascii=False)}")
    elif event_type == "turn.failed":
        print(f"\n{prefix}[turn failed: {event['error']}]")
    elif event_type == "turn.progress":
        print(f"\n{prefix}[progress] {event['message']}")
    elif event_type.startswith("turn.") and event_type != "turn.started":
        print(f"\n{prefix}[{event_type}]")


def _current_thread(state: CliState) -> str:
    if state.thread_id is None:
        raise ValueError("no current thread; use /new or /use")
    return state.thread_id


def _active_turn(state: CliState) -> str:
    if state.active_turn_id is None:
        raise ValueError("no active turn")
    return state.active_turn_id


def _required(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"missing {label}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent thread JSON-RPC client")
    parser.add_argument("--url", default="ws://127.0.0.1:8000/v1/conversation")
    parser.add_argument("--thread", help="use an existing thread UUID")
    parser.add_argument("--message", help="send one message and exit")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.message is not None:
        asyncio.run(run_once(args.url, args.message, args.thread))
    else:
        asyncio.run(run_interactive(args.url, args.thread))


if __name__ == "__main__":
    main()
