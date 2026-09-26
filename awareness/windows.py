from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

import psutil

from awareness.models import ScreenContext, WindowInfo


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


class ScreenAwarenessService:
    """
    Local-only desktop context.

    V0.1 intentionally DOES NOT:
    - capture keystrokes
    - read clipboard contents
    - inspect passwords
    - upload screenshots

    It only reads high-level desktop metadata such as:
    active window, cursor position, and idle time.
    """

    CODING_APPS = {
        "code.exe",
        "pycharm64.exe",
        "devenv.exe",
        "idea64.exe",
        "sublime_text.exe",
    }

    BROWSER_APPS = {
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "brave.exe",
        "opera.exe",
    }

    GAME_APPS = {
        "robloxplayerbeta.exe",
        "steam.exe",
    }

    def snapshot(self) -> ScreenContext:
        return ScreenContext(
            cursor_x=self._cursor_position()[0],
            cursor_y=self._cursor_position()[1],
            idle_seconds=self._idle_seconds(),
            foreground=self._foreground_window(),
            activity_kind=self._classify_activity(),
        )

    def _cursor_position(self) -> tuple[int, int]:
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return (0, 0)
        return (int(point.x), int(point.y))

    def _idle_seconds(self) -> float:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)

        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0

        tick_count = kernel32.GetTickCount()
        elapsed_ms = tick_count - info.dwTime
        return max(0.0, elapsed_ms / 1000.0)

    def _foreground_window(self) -> WindowInfo:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return WindowInfo()

        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)

        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        process_name = ""
        try:
            process_name = psutil.Process(pid.value).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

        return WindowInfo(
            title=buffer.value,
            process_name=process_name,
            pid=int(pid.value) if pid.value else None,
            left=int(rect.left),
            top=int(rect.top),
            right=int(rect.right),
            bottom=int(rect.bottom),
        )

    def _classify_activity(self) -> str:
        window = self._foreground_window()
        process = window.process_name.lower()
        title = window.title.lower()

        if process in self.CODING_APPS:
            return "coding"

        if process in self.GAME_APPS:
            return "gaming"

        if process in self.BROWSER_APPS:
            if "youtube" in title:
                return "video"
            if any(word in title for word in ("docs", "canvas", "blackboard", "school")):
                return "school"
            return "browsing"

        return "other"
