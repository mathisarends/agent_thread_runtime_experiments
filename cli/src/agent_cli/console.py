"""Every terminal write goes through here, so layout stays consistent."""

import asyncio
import json
import sys
from collections.abc import Callable
from typing import Any, TextIO

from agent_cli.theme import Theme

Styler = Callable[[str], str]

GUTTER_WIDTH = 6
GUTTER_SEPARATOR = "│"
CONTINUATION = "↳"
CLEAR_LINE = "\r\033[2K"


class Console:
    """Line-aware terminal output with a fixed-width speaker gutter.

    Events arrive while the user is typing, so the console knows about the
    pending prompt: it erases the prompt line before a block and redraws it
    afterwards, instead of letting output land on top of it.
    """

    def __init__(self, theme: Theme, stream: TextIO | None = None) -> None:
        self._theme = theme
        self._stream = stream
        self._at_line_start = True
        self._prompt: str | None = None
        self._prompt_visible = False

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def stream(self) -> TextIO:
        """Resolved late so redirected output (tests, pipes) is honoured."""
        return self._stream if self._stream is not None else sys.stdout

    def write(self, text: str) -> None:
        """Write without a trailing newline, e.g. for streamed deltas."""
        self._hide_prompt()
        self._emit(text)

    def line(self, text: str = "") -> None:
        self.write(f"{text}\n")
        self._show_prompt()

    def blank(self) -> None:
        """One empty line, e.g. between turns."""
        self.break_line()
        self.line()

    def break_line(self) -> None:
        """Close a partially written line so the next block starts cleanly."""
        self._hide_prompt()
        if not self._at_line_start:
            self._emit("\n")

    def message(
        self,
        label: str,
        body: str = "",
        *,
        style: Styler | None = None,
        badge: str = "",
        newline: bool = True,
    ) -> None:
        self.break_line()
        self.write(f"{self._gutter(label, style)}{badge}{body}")
        if newline:
            self.line()

    def note(self, text: str) -> None:
        self.message(CONTINUATION, self._theme.muted(text), style=self._theme.muted)

    def error(self, text: str) -> None:
        self.message("error", self._theme.error(text), style=self._theme.error)

    def json(self, payload: Any) -> None:
        self.break_line()
        self.line(json.dumps(payload, indent=2, ensure_ascii=False))

    def banner(self, title: str, subtitle: str = "") -> None:
        self.break_line()
        self.line(self._theme.strong(title))
        if subtitle:
            self.line(self._theme.muted(subtitle))

    def badge(self, thread_id: str | None) -> str:
        """Marker for events belonging to a background thread."""
        if thread_id is None:
            return ""
        return self._theme.thread(f"[{thread_id[:8]}] ")

    async def ask(self, label: str, style: Styler | None = None) -> str:
        """Read one line, keeping the prompt intact across live output."""
        self.break_line()
        self._prompt = self._gutter(label, style)
        self._show_prompt()
        try:
            return await asyncio.to_thread(input)
        finally:
            self._prompt = None
            self._prompt_visible = False
            self._at_line_start = True

    def _gutter(self, label: str, style: Styler | None) -> str:
        painted = (style or self._theme.muted)(label.rjust(GUTTER_WIDTH))
        return f"{painted} {self._theme.muted(GUTTER_SEPARATOR)} "

    def _show_prompt(self) -> None:
        if self._prompt is not None and not self._prompt_visible:
            self._emit(self._prompt)
            self._prompt_visible = True

    def _hide_prompt(self) -> None:
        if not self._prompt_visible:
            return
        self._prompt_visible = False
        if self._theme.enabled:
            self._emit(CLEAR_LINE)
            self._at_line_start = True
        else:
            self._emit("\n")

    def _emit(self, text: str) -> None:
        if not text:
            return
        self.stream.write(text)
        self.stream.flush()
        self._at_line_start = text.endswith("\n")
