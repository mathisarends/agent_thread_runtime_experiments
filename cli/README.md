# Agent CLI

Interactive terminal client for the agent thread runtime gateway. It speaks the
same JSON-RPC 2.0 WebSocket protocol as any other client; nothing here is
privileged.

```powershell
uv run agent-cli
uv run agent-cli --thread <uuid>
uv run agent-cli --message "Hello runtime"
```

The package is split by responsibility:

```text
agent_cli/
├── protocol.py    method, event, and item names of the wire protocol
├── rpc.py         JSON-RPC multiplexing over one WebSocket
├── state.py       per-session CLI state
├── theme.py       ANSI palette, disabled for non-TTY output
├── console.py     all terminal writes go through here
├── render.py      thread events → terminal output
├── session.py     high-level thread and turn operations
├── commands.py    slash command registry and dispatch
├── app.py         interactive loop and one-shot run
└── main.py        argument parsing and entry point
```

Colors are disabled automatically when stdout is not a TTY, when `NO_COLOR` is
set, or with `--no-color`.
