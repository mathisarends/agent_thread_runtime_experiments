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
    ├── core/                  domain and orchestration
    │   ├── models.py
    │   ├── events.py
    │   ├── progress.py
    │   └── service.py
    ├── agents/                agent boundary and integrations
    │   ├── contracts.py
    │   ├── context.py
    │   ├── llmify.py
    │   └── tools.py
    ├── persistence/           persistence boundary and SQLModel adapter
    │   ├── repository.py
    │   ├── database.py
    │   └── sqlmodel.py
    └── transport/             WebSocket JSON-RPC transport
        ├── schemas.py
        ├── methods.py
        ├── connection.py
        └── routes.py
```

The only network endpoint is a long-lived JSON-RPC 2.0 WebSocket:

```text
ws://127.0.0.1:8000/v1/conversation
```

Machine-readable protocol types are available as JSON Schema at
`GET /v1/conversation/schema`. The same request, response, and event models are
also registered under `components.schemas` in `GET /openapi.json` for external
type generation. No generated client is bundled with the runtime.

The terminal client lives beside it as its own workspace package, `cli/`
(see `cli/README.md`); it is an ordinary protocol consumer, not part of the
runtime.

Run the gateway with:

```powershell
uv run gateway
sh scripts/run_gateway.sh
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
uv run agent-cli
sh scripts/run_cli.sh
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

Progress updates are an opt-in execution capability, not inferred from raw tool
events. A subscription selects one of three modes:

- `off` (default): no progress tool is exposed to the agent, so it adds no
  progress-specific inference work.
- `on_request`: progress generation is enabled, but updates are not pushed. Read
  the latest active status with `turn.progress.get`.
- `proactive`: progress generation is enabled and `turn.progress` notifications
  are streamed live.

```json
{"jsonrpc":"2.0","id":2,"method":"thread.subscribe","params":{"thread_id":"<uuid>","progress":"proactive"}}
{"jsonrpc":"2.0","id":3,"method":"turn.progress.get","params":{"thread_id":"<uuid>"}}
```

The service aggregates all active subscriptions when a turn starts. If at least
one subscriber requests `on_request` or `proactive`, `AgentContext.progress_enabled`
is true and the llmify runner exposes its internal `report_progress(message)`
tool. That tool becomes `turn.progress` externally and is never persisted or
shown as a normal tool item. Updates are normalized to one line and capped at 240
characters for speech output. Subscription changes apply to the next turn. In
the CLI, use `/progress proactive`, `/progress on_request`, `/progress off`, and
`/status`.

For a non-interactive end-to-end smoke test:

```powershell
uv run agent-cli --message "Hello runtime"
```

Example request sequence:

```json
{"jsonrpc":"2.0","id":1,"method":"thread.create"}
{"jsonrpc":"2.0","id":2,"method":"thread.subscribe","params":{"thread_id":"<uuid>"}}
{"jsonrpc":"2.0","id":3,"method":"turn.start","params":{"thread_id":"<uuid>","message":"Hello"}}
```

Available methods are `thread.create`, `thread.get`, `thread.subscribe`,
`thread.unsubscribe`, `turn.start`, `turn.steer`, `turn.interrupt`, and
`turn.progress.get`. Subscribed events arrive as `thread.event` JSON-RPC
notifications on the same socket.
