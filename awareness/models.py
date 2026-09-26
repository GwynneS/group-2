from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WindowInfo:
    title: str = ""
    process_name: str = ""
    pid: int | None = None
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(slots=True)
class ScreenContext:
    cursor_x: int
    cursor_y: int
    idle_seconds: float
    foreground: WindowInfo
    activity_kind: str
