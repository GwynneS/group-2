from __future__ import annotations

import platform

from screen_behavior.awareness.activity_tracker import ActivityStabilityTracker
from screen_behavior.awareness.classifier import ActivityClassifier
from screen_behavior.awareness.geometry import calculate_window_edge_awareness
from screen_behavior.awareness.keyboard import (
    GlobalKeyboardMonitor,
    KeyboardActivityTracker,
)
from screen_behavior.awareness.models import ScreenContext


class AwarenessService:
    """
    Platform-neutral public awareness API.
    """

    def __init__(
        self,
        backend=None,
        classifier=None,
        activity_tracker=None,
        keyboard_tracker=None,
        keyboard_monitor=None,
        start_keyboard_monitor: bool = True,
    ) -> None:
        self.backend = backend or self._build_backend()
        self.classifier = classifier or ActivityClassifier()
        self.activity_tracker = (
            activity_tracker or ActivityStabilityTracker()
        )

        self.keyboard_tracker = (
            keyboard_tracker or KeyboardActivityTracker()
        )
        self.keyboard_monitor = (
            keyboard_monitor
            or GlobalKeyboardMonitor(self.keyboard_tracker)
        )

        if start_keyboard_monitor:
            self.keyboard_monitor.start()

    def snapshot(self) -> ScreenContext:
        raw = self.backend.snapshot()
        keyboard = self.keyboard_tracker.snapshot()

        raw_classification = self.classifier.classify(
            raw,
            keyboard,
        )
        timing = self.activity_tracker.update(
            raw_classification,
        )
        edge = calculate_window_edge_awareness(raw)

        return ScreenContext(
            cursor_x=raw.cursor_x,
            cursor_y=raw.cursor_y,
            idle_seconds=raw.idle_seconds,

            # Stable activity used by the rest of the project.
            activity=timing.activity,
            activity_confidence=timing.confidence,
            activity_scores=dict(raw_classification.scores),
            activity_duration_seconds=timing.duration_seconds,
            previous_activity=timing.previous_activity,
            activity_changed=timing.activity_changed,

            # Raw leader is exposed for debugging/advanced integrations.
            leading_activity=raw_classification.activity,
            leading_activity_confidence=raw_classification.confidence,
            pending_activity=timing.pending_activity,
            pending_activity_seconds=timing.pending_seconds,

            foreground=raw.foreground,
            screen_bounds=raw.screen_bounds,
            window_edge=edge,
            keyboard=keyboard,
        )

    def close(self) -> None:
        self.keyboard_monitor.stop()

    @staticmethod
    def _build_backend():
        system = platform.system()

        if system == "Windows":
            from screen_behavior.awareness.backends.windows_backend import (
                WindowsAwarenessBackend,
            )
            return WindowsAwarenessBackend()

        if system == "Darwin":
            from screen_behavior.awareness.backends.macos_backend import (
                MacOSAwarenessBackend,
            )
            return MacOSAwarenessBackend()

        raise RuntimeError(
            f"Unsupported operating system: {system}. "
            "This subsystem currently supports Windows and macOS."
        )
