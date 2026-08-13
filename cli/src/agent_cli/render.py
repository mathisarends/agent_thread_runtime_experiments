"""Turn thread events into terminal output."""

import json
from typing import Any

from agent_cli.console import Console
from agent_cli.protocol import EventType, ItemType

Event = dict[str, Any]


class EventRenderer:
    """Render live events, streaming agent text incrementally."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._streaming_item_ids: set[str] = set()

    @property
    def streaming_item_ids(self) -> frozenset[str]:
        return frozenset(self._streaming_item_ids)

    def render(self, event: Event, *, thread_id: str | None = None) -> None:
        """`thread_id` marks events from a background thread."""
        badge = self._console.badge(thread_id)
        match event["type"]:
            case EventType.ITEM_DELTA:
                self._render_delta(event, badge)
            case EventType.ITEM_COMPLETED:
                self._render_item(event["item"], badge)
            case EventType.TURN_FAILED:
                self._console.error(f"{badge}turn failed: {event['error']}")
            case EventType.TURN_PROGRESS:
                self._console.message(
                    "…",
                    self._console.theme.progress(event["message"]),
                    style=self._console.theme.progress,
                    badge=badge,
                )
            case EventType.TURN_INTERRUPTED:
                self._console.note(f"{badge}interrupted")
            case EventType.TURN_COMPLETED:
                self._console.blank()
            case _:
                pass

    def _render_delta(self, event: Event, badge: str) -> None:
        item_id = event["item_id"]
        if item_id not in self._streaming_item_ids:
            self._streaming_item_ids.add(item_id)
            self._console.message(
                "agent", style=self._console.theme.agent, badge=badge, newline=False
            )
        self._console.write(event["delta"])

    def _render_item(self, item: dict[str, Any], badge: str) -> None:
        theme = self._console.theme
        match item["type"]:
            case ItemType.USER_MESSAGE:
                if badge:  # the local terminal already echoed what was typed
                    self._console.message(
                        "you", item["content"], style=theme.user, badge=badge
                    )
            case ItemType.AGENT_MESSAGE:
                self._render_agent_message(item, badge)
            case ItemType.TOOL_CALL:
                self._console.message(
                    "tool",
                    theme.tool(_format_call(item["name"], item["arguments"])),
                    style=theme.tool,
                    badge=badge,
                )
            case ItemType.TOOL_RESULT:
                self._console.note(f"{badge}{_format_value(item['output'])}")

    def _render_agent_message(self, item: dict[str, Any], badge: str) -> None:
        item_id = item.get("id")
        if item_id in self._streaming_item_ids:
            self._streaming_item_ids.discard(item_id)
            self._console.break_line()
            return
        self._console.message(
            "agent", item["content"], style=self._console.theme.agent, badge=badge
        )


def _format_call(name: str, arguments: Any) -> str:
    if isinstance(arguments, dict):
        joined = ", ".join(
            f"{key}={_format_value(value)}" for key, value in arguments.items()
        )
        return f"{name}({joined})"
    return f"{name}({_format_value(arguments)})"


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
