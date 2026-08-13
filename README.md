# Minimal Agent Thread Runtime

The runtime owns persistent conversation state independently of its transport. It
uses Pydantic schemas, SQLModel-backed SQLite persistence, and Dishka dependency
injection. It permits one active turn per thread, fans live events out to multiple
subscribers, and keeps the agent behind an `AgentRunner` protocol.
The default runner uses [`llmify`](https://github.com/mathisarends/llmify) with
OpenAI; tests and custom integrations can override it at the container edge.

The small gateway is split by responsibility:

```text
gateway/
├── config.py                 Pydantic application settings
├── container.py              Dishka composition root
└── conversation/
    ├── models.py             Pydantic domain schemas
    ├── events.py             Pydantic event schemas and live broker
    ├── database.py           SQLModel tables and SQLite engine
    ├── repository.py         persistence boundary and mappings
    ├── agent.py              runner protocol and control channel
    ├── context.py            persisted-context builder
    ├── llmify_runner.py      minimal real LLM adapter
    ├── service.py            canonical orchestration
    ├── rpc.py                JSON-RPC Pydantic schemas
    ├── socket.py             connection handling
    └── routes.py             injected WebSocket route
```

The only network endpoint is a long-lived JSON-RPC 2.0 WebSocket:

```text
ws://127.0.0.1:8000/v1/conversation
```

Run it with:

```powershell
uv run python main.py
```

Configuration is loaded from environment variables and a local `.env` file:

```dotenv
OPENAI_API_KEY=sk-...
AGENT_MODEL=gpt-5.4-mini
AGENT_SYSTEM_PROMPT=You are a helpful assistant.
AGENT_THREAD_DB=agent_threads.db
```

Only `OPENAI_API_KEY` is required. `.env` and SQLite database files are ignored
by Git.

In another terminal, start the interactive client:

```powershell
uv run python client.py
```

Plain text starts a turn (or steers a currently active turn). Use `/help` for all
commands, including `/new`, `/use`, `/get`, `/start`, `/steer`, `/interrupt`, and
the generic `/rpc` protocol escape hatch.

`/subscribe THREAD_ID` streams future events for that thread. It does not replay
history; use `/use THREAD_ID` followed by `/get` to inspect persisted history.
Events from subscribed background threads are prefixed with their thread ID.

Every item uses the same lifecycle on the WebSocket:

```text
item.started → item.delta* → item.completed
```

Agent text is emitted as live `item.delta` chunks and rendered incrementally by
the CLI. Tool calls use the same lifecycle and correlate `tool_call` with
`tool_result` through a stable `call_id`. The default llmify runner registers a
minimal `add_numbers(a, b)` tool as an end-to-end tool-loop example.

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
