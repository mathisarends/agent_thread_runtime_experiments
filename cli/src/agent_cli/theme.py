"""ANSI styling, degrading to plain text when the terminal cannot show it."""

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import TextIO


class Color(StrEnum):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def color_supported(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", None)) and stream.isatty()


@dataclass(frozen=True, slots=True)
class Theme:
    """Semantic colors; every style is a no-op when `enabled` is false."""

    enabled: bool = True

    @classmethod
    def for_stream(cls, stream: TextIO, *, force_plain: bool = False) -> Theme:
        return cls(enabled=not force_plain and color_supported(stream))

    def _paint(self, text: str, *colors: Color) -> str:
        if not self.enabled or not text:
            return text
        return f"{''.join(colors)}{text}{Color.RESET}"

    def user(self, text: str) -> str:
        return self._paint(text, Color.CYAN, Color.BOLD)

    def agent(self, text: str) -> str:
        return self._paint(text, Color.GREEN, Color.BOLD)

    def tool(self, text: str) -> str:
        return self._paint(text, Color.YELLOW)

    def progress(self, text: str) -> str:
        return self._paint(text, Color.MAGENTA)

    def thread(self, text: str) -> str:
        return self._paint(text, Color.BLUE)

    def error(self, text: str) -> str:
        return self._paint(text, Color.RED, Color.BOLD)

    def muted(self, text: str) -> str:
        return self._paint(text, Color.DIM)

    def strong(self, text: str) -> str:
        return self._paint(text, Color.BOLD)
