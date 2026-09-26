from __future__ import annotations

import platform
from time import monotonic

from screen_behavior.awareness.activity_tracker import ActivityStabilityTracker
from screen_behavior.awareness.classifier import ActivityClassifier
from screen_behavior.awareness.evidence import EvidenceAccumulator
from screen_behavior.awareness.geometry import calculate_window_edge_awareness
from screen_behavior.awareness.keyboard import (
    GlobalKeyboardMonitor,
    KeyboardActivityTracker,
)
from screen_behavior.awareness.models import ScreenContext
from screen_behavior.awareness.mouse import ContinuousMouseMonitor
from screen_behavior.awareness.user_state import UserStateTracker


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
        mouse_monitor=None,
        start_mouse_monitor: bool | None = None,
        evidence=None,
        user_state_tracker=None,
    ) -> None:
        # By default only start the mouse thread for a real OS backend, so
        # tests with fake backends don't spawn polling threads.
        if start_mouse_monitor is None:
            start_mouse_monitor = backend is None

        self.backend = backend or self._build_backend()
        self.classifier = classifier or ActivityClassifier()
        self.activity_tracker = (
            activity_tracker or ActivityStabilityTracker()
        )

        # Share the activity tracker's clock so tests/simulations that
        # control time also control evidence decay and user-state timing.
        clock = getattr(self.activity_tracker, "_clock", monotonic)
        self.evidence = evidence or EvidenceAccumulator(clock=clock)
        self.user_state_tracker = (
            user_state_tracker or UserStateTracker(clock=clock)
        )
        self.user_present: bool | None = None

        self.keyboard_tracker = (
            keyboard_tracker or KeyboardActivityTracker()
        )
        self.keyboard_monitor = (
            keyboard_monitor
            or GlobalKeyboardMonitor(self.keyboard_tracker)
        )

        if start_keyboard_monitor:
            self.keyboard_monitor.start()

        self.mouse_monitor = mouse_monitor or ContinuousMouseMonitor(
            self._cursor_reader(self.backend),
        )
        if start_mouse_monitor:
            self.mouse_monitor.start()

    def snapshot(self) -> ScreenContext:
        raw = self.backend.snapshot()
        keyboard = self.keyboard_tracker.snapshot()

        raw_classification = self.classifier.classify(
            raw,
            keyboard,
        )
        smoothed = self.evidence.update(raw_classification)
        timing = self.activity_tracker.update(
            smoothed,
        )
        edge = calculate_window_edge_awareness(raw)

        context = ScreenContext(
            cursor_x=raw.cursor_x,
            cursor_y=raw.cursor_y,
            idle_seconds=raw.idle_seconds,

            # Stable activity used by the rest of the project.
            activity=timing.activity,
            activity_confidence=timing.confidence,
            # Decayed evidence over roughly the last 30-60 seconds.
            activity_scores=dict(smoothed.scores),
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
            mouse=self.mouse_monitor.snapshot(),
            user_present=self.user_present,
        )

        state, seconds = self.user_state_tracker.update(
            context,
            self.user_present,
        )
        context.user_state = state
        context.user_state_seconds = seconds
        return context

    def set_user_present(self, present: bool | None) -> None:
        """
        Hook for body tracking: True/False when known, None when the camera
        is off. False makes the user AWAY immediately.
        """
        self.user_present = present

    def close(self) -> None:
        self.keyboard_monitor.stop()
        self.mouse_monitor.stop()

    @staticmethod
    def _cursor_reader(backend):
        reader = getattr(backend, "_cursor_position", None)
        if callable(reader):
            return reader

        def from_snapshot():
            raw = backend.snapshot()
            return raw.cursor_x, raw.cursor_y

        return from_snapshot

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
