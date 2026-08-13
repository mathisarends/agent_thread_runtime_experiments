# Spec: Minimal Agent Thread Runtime

## Goal

Build a small agent runtime that owns the canonical conversation and execution state independently of any UI or transport.

The runtime must support:

* persistent threads
* sequential agent turns
* streaming turn events
* steering a running turn
* interrupting a running turn
* multiple clients observing the same thread
* adapters such as chat, WebSocket, and voice later

Do **not** integrate OpenAI Realtime yet.

The architecture should make Realtime a future client of this runtime, not the owner of agent state.

---

## Core Model

Use three concepts:

```text
Thread
└── Turn
    └── Item
```

### Thread

A long-lived conversation.

```python
@dataclass
class Thread:
    id: UUID
    created_at: datetime
```

A thread may contain many completed turns and at most one active turn.

### Turn

One execution of the agent.

```python
@dataclass
class Turn:
    id: UUID
    thread_id: UUID
    status: TurnStatus
    created_at: datetime
    completed_at: datetime | None
```

Statuses:

```python
class TurnStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
```

### Item

An observable event/artifact produced during a turn.

Initial item types:

```python
UserMessageItem
AgentMessageItem
ToolCallItem
ToolResultItem
```

Do not model reasoning initially.

Each item must have:

```python
id
thread_id
turn_id
created_at
```

---

## Runtime API

Implement:

```python
class AgentThreadService:
    async def create_thread(self) -> Thread:
        ...

    async def start_turn(
        self,
        thread_id: UUID,
        message: str,
    ) -> Turn:
        ...

    async def steer_turn(
        self,
        thread_id: UUID,
        turn_id: UUID,
        message: str,
    ) -> None:
        ...

    async def interrupt_turn(
        self,
        thread_id: UUID,
        turn_id: UUID,
    ) -> None:
        ...

    async def get_thread(
        self,
        thread_id: UUID,
    ) -> ThreadSnapshot:
        ...
```

Only one turn may run per thread.

---

## Agent Boundary

Keep the actual LLM/agent implementation behind an interface.

```python
class AgentRunner(Protocol):
    async def run(
        self,
        context: AgentContext,
        input: str,
        control: TurnControl,
    ) -> AsyncIterator[AgentEvent]:
        ...
```

The thread runtime must not depend directly on Codex, OpenAI Realtime, or a specific LLM SDK.

---

## Steering

A running turn owns a control channel.

```python
class TurnControl:
    async def receive(self) -> AsyncIterator[ControlMessage]:
        ...
```

Control messages:

```python
@dataclass
class Steer:
    message: str


@dataclass
class Interrupt:
    pass
```

`steer_turn()` must deliver `Steer(message)` to the currently running `AgentRunner`.

Do not start another independent agent run for steering.

The implementation may initially support steering only at safe checkpoints between model/tool calls.

---

## Events

The runtime emits structured events.

Minimum event set:

```text
turn.started
item.started
item.delta
item.completed
turn.completed
turn.interrupted
turn.failed
```

Example:

```python
@dataclass
class TurnStarted:
    thread_id: UUID
    turn_id: UUID


@dataclass
class ItemCompleted:
    thread_id: UUID
    turn_id: UUID
    item: Item
```

Provide an async subscription API:

```python
async def subscribe(
    self,
    thread_id: UUID,
) -> AsyncIterator[ThreadEvent]:
    ...
```

Multiple subscribers must be supported.

---

## Execution Example

For:

```text
User: Play Believer on Spotify
```

the observable sequence should look approximately like:

```text
turn.started

item.completed
  UserMessage("Play Believer on Spotify")

item.started
  ToolCall("spotify search Believer")

item.completed
  ToolCall(...)

item.completed
  ToolResult(...)

item.completed
  AgentMessage("Believer is now playing.")

turn.completed
```

If the user says while the turn is running:

```text
Actually, play Thunder.
```

the client calls:

```python
await service.steer_turn(
    thread_id,
    active_turn_id,
    "Actually, play Thunder.",
)
```

The existing turn receives that input.

---

## Persistence

Start simple with SQLite.

Persist:

```text
threads
turns
items
```

Do not persist transient `item.delta` events.

Persist completed semantic items only.

The running execution task itself does not need to survive process restarts in v1.

On restart, turns previously marked `running` may be changed to `interrupted`.

---

## Context Construction

Before starting an agent turn:

```python
context = await context_builder.build(thread_id)
```

Build model context from persisted semantic items.

Initially include:

```text
user messages
agent messages
tool calls/results if required by the AgentRunner
```

Keep context construction behind:

```python
class ContextBuilder(Protocol):
    async def build(self, thread_id: UUID) -> AgentContext:
        ...
```

This is where compaction can be added later.

Do not implement sophisticated compaction yet.

---

## Transport

Keep transport separate from the runtime.

Implement a minimal FastAPI adapter:

```text
POST /v1/threads
POST /v1/threads/{thread_id}/turns
POST /v1/threads/{thread_id}/turns/{turn_id}/steer
POST /v1/threads/{thread_id}/turns/{turn_id}/interrupt

WS /v1/threads/{thread_id}/events
```

HTTP commands mutate state.

WebSocket streams events.

The domain/runtime must not import FastAPI.

---

## Future Voice Integration

Design for this later:

```text
                    AgentThreadService
                           ▲
                           │
          ┌────────────────┴────────────────┐
          │                                 │
      Chat Client                      Voice Client
                                           │
                                      Realtime API
```

Realtime must not own canonical task state.

Future voice flow:

```text
speech
→ transcript
→ start_turn / steer_turn

thread events
→ voice renderer
→ speech
```

No Realtime-specific concepts should appear in the core runtime.

---

## Suggested Package Structure

```text
gateway/
└── features/
    └── conversation/
        ├── domain/
        │   ├── thread.py
        │   ├── turn.py
        │   ├── item.py
        │   └── events.py
        │
        ├── application/
        │   ├── thread_service.py
        │   ├── agent_runner.py
        │   ├── context_builder.py
        │   └── event_broker.py
        │
        ├── infrastructure/
        │   ├── sqlite_repository.py
        │   └── runner/
        │       └── llmify_runner.py
        │
        └── presentation/
            ├── http.py
            └── socket.py
```

Adjust names to the existing project conventions rather than creating parallel abstractions unnecessarily.

---

## First Milestone

Implement only this vertical slice:

```text
create thread
     ↓
start turn
     ↓
AgentRunner produces AgentMessage
     ↓
persist items
     ↓
stream events over WebSocket
     ↓
turn completed
```

Use a fake `AgentRunner` first.

Example:

```python
class FakeAgentRunner:
    async def run(self, context, input, control):
        yield AgentMessageCreated(
            content=f"Echo: {input}"
        )
```

Tests must demonstrate:

1. a thread can be created
2. a turn can be started
3. events are emitted in order
4. items are persisted
5. the turn ends as `completed`
6. two subscribers can observe the same turn

Only after this works, connect the existing real text-based agent.

---

## Second Milestone

Add:

```text
steer_turn
interrupt_turn
tool-call items
```

Test steering using a fake long-running agent before integrating the real agent.

---

## Non-Goals

Do not implement yet:

* OpenAI Realtime
* speech recognition
* TTS
* advanced context compaction
* branchable conversations
* distributed execution
* agent-to-agent protocols
* MCP/A2A compatibility layers
* replay of unfinished tasks after restart
* complex approval workflows

Keep the first implementation small enough that the core runtime can be understood by reading a few files.

---

## Design Principle

There must be exactly one canonical owner of conversation/task state:

```text
AgentThreadService
```

Chat, Voice, CLI, mobile apps, and future protocols are clients of that state.

Do not create separate authoritative conversation histories per client.
