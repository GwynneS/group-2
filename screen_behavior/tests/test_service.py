import unittest

from screen_behavior.awareness.activity_tracker import (
    ActivityStabilityTracker,
)
from screen_behavior.awareness.keyboard import KeyboardActivityTracker
from screen_behavior.awareness.models import (
    ActivityType,
    RawScreenSnapshot,
    ScreenBounds,
    WindowInfo,
)
from screen_behavior.awareness.service import AwarenessService


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeBackend:
    def __init__(self):
        self.process_name = "Code.exe"
        self.title = "project - Visual Studio Code"

    def snapshot(self):
        return RawScreenSnapshot(
            cursor_x=105,
            cursor_y=300,
            idle_seconds=1.0,
            foreground=WindowInfo(
                title=self.title,
                process_name=self.process_name,
                left=100,
                top=100,
                right=900,
                bottom=700,
            ),
            screen_bounds=ScreenBounds(
                left=0,
                top=0,
                right=1920,
                bottom=1080,
            ),
        )


class FakeKeyboardMonitor:
    def start(self):
        pass

    def stop(self):
        pass


class ServiceTests(unittest.TestCase):
    def test_platform_neutral_service_contract(self):
        clock = FakeClock()
        keyboard = KeyboardActivityTracker(clock=clock)
        keyboard.set_monitoring_available(True)
        keyboard.record_keypress()

        service = AwarenessService(
            backend=FakeBackend(),
            activity_tracker=ActivityStabilityTracker(clock=clock),
            keyboard_tracker=keyboard,
            keyboard_monitor=FakeKeyboardMonitor(),
            start_keyboard_monitor=False,
        )

        first = service.snapshot()

        self.assertEqual(first.activity, ActivityType.CODING)
        self.assertEqual(first.leading_activity, ActivityType.CODING)
        self.assertIn(ActivityType.CODING, first.activity_scores)
        self.assertGreaterEqual(first.activity_confidence, 0.0)
        self.assertLessEqual(first.activity_confidence, 1.0)
        self.assertTrue(first.window_edge.available)
        self.assertTrue(first.keyboard.monitoring_available)

        clock.advance(10)
        second = service.snapshot()

        self.assertEqual(
            second.activity_duration_seconds,
            10.0,
        )

    def test_service_exposes_pending_leader_without_flicker(self):
        clock = FakeClock()
        backend = FakeBackend()
        keyboard = KeyboardActivityTracker(clock=clock)
        keyboard.set_monitoring_available(True)

        tracker = ActivityStabilityTracker(
            clock=clock,
            switch_delay_seconds=5.0,
            immediate_switch_confidence=1.1,
        )

        service = AwarenessService(
            backend=backend,
            activity_tracker=tracker,
            keyboard_tracker=keyboard,
            keyboard_monitor=FakeKeyboardMonitor(),
            start_keyboard_monitor=False,
        )

        first = service.snapshot()
        self.assertEqual(first.activity, ActivityType.CODING)

        backend.process_name = "chrome.exe"
        backend.title = "Google Chrome"

        clock.advance(1)
        second = service.snapshot()

        self.assertEqual(second.activity, ActivityType.CODING)
        self.assertEqual(
            second.leading_activity,
            ActivityType.BROWSING,
        )
        self.assertEqual(
            second.pending_activity,
            ActivityType.BROWSING,
        )


if __name__ == "__main__":
    unittest.main()
