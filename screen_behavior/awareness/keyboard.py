from __future__ import annotations

import platform
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Callable

from screen_behavior.awareness.models import KeyboardActivity


class KeyboardActivityTracker:
    """
    Aggregate-only keyboard activity.

    `record_keypress()` receives no key identity. It records only a timestamp.
    This prevents the public model from ever containing typed characters,
    key names, words, passwords, or key sequences.
    """

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        typing_active_window_seconds: float = 2.0,
        burst_gap_seconds: float = 3.0,
    ) -> None:
        self._clock = clock
        self._typing_active_window = typing_active_window_seconds
        self._burst_gap = burst_gap_seconds
        self._timestamps: deque[float] = deque()
        self._last_keypress: float | None = None
        self._burst_started_at: float | None = None
        self._monitoring_available = False
        self._lock = Lock()

    def set_monitoring_available(self, value: bool) -> None:
        with self._lock:
            self._monitoring_available = bool(value)

    def record_keypress(self) -> None:
        now = self._clock()
        with self._lock:
            if (
                self._last_keypress is None
                or now - self._last_keypress > self._burst_gap
            ):
                self._burst_started_at = now

            self._last_keypress = now
            self._timestamps.append(now)
            self._prune(now)

    def snapshot(self) -> KeyboardActivity:
        now = self._clock()

        with self._lock:
            self._prune(now)

            if not self._monitoring_available:
                return KeyboardActivity(monitoring_available=False)

            last_5 = sum(1 for t in self._timestamps if now - t <= 5.0)
            last_30 = sum(1 for t in self._timestamps if now - t <= 30.0)
            last_60 = len(self._timestamps)

            if self._last_keypress is None:
                seconds_since = None
                no_typing_duration = None
                typing_active = False
                burst_duration = 0.0
            else:
                seconds_since = max(0.0, now - self._last_keypress)
                no_typing_duration = seconds_since
                typing_active = seconds_since <= self._typing_active_window

                if (
                    typing_active
                    and self._burst_started_at is not None
                ):
                    burst_duration = max(0.0, now - self._burst_started_at)
                else:
                    burst_duration = 0.0

            return KeyboardActivity(
                monitoring_available=True,
                typing_active=typing_active,
                keypresses_last_5_seconds=last_5,
                keypresses_last_30_seconds=last_30,
                typing_rate_per_minute=float(last_60),
                current_typing_burst_seconds=burst_duration,
                seconds_since_last_keypress=seconds_since,
                current_no_typing_duration=no_typing_duration,
            )

    def _prune(self, now: float) -> None:
        cutoff = now - 60.0
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()


class GlobalKeyboardMonitor:
    """
    Cross-platform listener using pynput.

    The callback intentionally ignores the key object and only calls
    `tracker.record_keypress()`.
    """

    def __init__(self, tracker: KeyboardActivityTracker | None = None) -> None:
        self.tracker = tracker or KeyboardActivityTracker()
        self._listener = None

    def start(self) -> None:
        if platform.system() == "Darwin" and not self._mac_permission_looks_available():
            self.tracker.set_monitoring_available(False)
            return

        try:
            from pynput import keyboard

            def on_press(_key) -> None:
                # Discard the key identity immediately.
                self.tracker.record_keypress()

            self._listener = keyboard.Listener(on_press=on_press)
            self._listener.daemon = True
            self._listener.start()
            self.tracker.set_monitoring_available(True)
        except Exception:
            self._listener = None
            self.tracker.set_monitoring_available(False)

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            finally:
                self._listener = None

    @staticmethod
    def _mac_permission_looks_available() -> bool:
        """
        Best-effort privacy check. We do not bypass macOS privacy controls.
        If the API is unavailable, let pynput attempt normal startup.
        """
        try:
            import Quartz

            checker = getattr(Quartz, "AXIsProcessTrusted", None)
            if checker is None:
                return True
            return bool(checker())
        except Exception:
            return True
