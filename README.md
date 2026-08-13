# Minimal Agent Thread Runtime

The runtime owns persistent conversation state independently of its transport. It
uses SQLite, permits one active turn per thread, fans live events out to multiple
subscribers, and keeps the agent behind an `AgentRunner` protocol.

The only network endpoint is a long-lived JSON-RPC 2.0 WebSocket:

```text
ws://127.0.0.1:8000/v1/conversation
```

Run it with:

```powershell
uv run python main.py
```

In another terminal, start the interactive client:

```powershell
uv run python client.py
```

Plain text starts a turn (or steers a currently active turn). Use `/help` for all
commands, including `/new`, `/use`, `/get`, `/start`, `/steer`, `/interrupt`, and
the generic `/rpc` protocol escape hatch.

For a non-interactive end-to-end smoke test:

```powershell
uv run python client.py --message "Hello runtime"
```

Example request sequence:

```json
{"jsonrpc":"2.0","id":1,"method":"thread.create"}
{"jsonrpc":"2.0","id":2,"method":"thread.subscribe","params":{"thread_id":"<uuid>"}}
{"jsonrpc":"2.0","id":3,"method":"turn.start","params":{"thread_id":"<uuid>","message":"Hello"}}
```

Available methods are `thread.create`, `thread.get`, `thread.subscribe`,
`thread.unsubscribe`, `turn.start`, `turn.steer`, and `turn.interrupt`. Subscribed
events arrive as `thread.event` JSON-RPC notifications on the same socket.
