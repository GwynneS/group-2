from __future__ import annotations

import ctypes
from ctypes import wintypes

import psutil

from screen_behavior.awareness.models import (
    RawScreenSnapshot,
    ScreenBounds,
    WindowInfo,
)


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


class WindowsAwarenessBackend:
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    def snapshot(self) -> RawScreenSnapshot:
        x, y = self._cursor_position()

        return RawScreenSnapshot(
            cursor_x=x,
            cursor_y=y,
            idle_seconds=self._idle_seconds(),
            foreground=self._foreground_window(),
            screen_bounds=self._screen_bounds(),
        )

    def _cursor_position(self) -> tuple[int, int]:
        point = POINT()

        if not user32.GetCursorPos(ctypes.byref(point)):
            return 0, 0

        return int(point.x), int(point.y)

    def _idle_seconds(self) -> float:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)

        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0

        return max(
            0.0,
            (kernel32.GetTickCount() - info.dwTime) / 1000.0,
        )

    def _screen_bounds(self) -> ScreenBounds:
        left = user32.GetSystemMetrics(self.SM_XVIRTUALSCREEN)
        top = user32.GetSystemMetrics(self.SM_YVIRTUALSCREEN)
        width = user32.GetSystemMetrics(self.SM_CXVIRTUALSCREEN)
        height = user32.GetSystemMetrics(self.SM_CYVIRTUALSCREEN)

        return ScreenBounds(
            left=int(left),
            top=int(top),
            right=int(left + width),
            bottom=int(top + height),
        )

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
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            pass

        return WindowInfo(
            title=buffer.value,
            app_name=process_name,
            process_name=process_name,
            pid=int(pid.value) if pid.value else None,
            left=int(rect.left),
            top=int(rect.top),
            right=int(rect.right),
            bottom=int(rect.bottom),
        )
