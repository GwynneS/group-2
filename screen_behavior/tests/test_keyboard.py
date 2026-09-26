import unittest

from screen_behavior.awareness.keyboard import KeyboardActivityTracker


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class KeyboardActivityTests(unittest.TestCase):
    def test_inactivity_clock_resets_and_increases(self):
        clock = FakeClock()
        tracker = KeyboardActivityTracker(clock=clock)
        tracker.set_monitoring_available(True)

        tracker.record_keypress()

        first = tracker.snapshot()
        self.assertEqual(first.seconds_since_last_keypress, 0.0)

        clock.advance(12.5)
        second = tracker.snapshot()
        self.assertAlmostEqual(
            second.current_no_typing_duration,
            12.5,
        )

        tracker.record_keypress()
        third = tracker.snapshot()
        self.assertEqual(
            third.current_no_typing_duration,
            0.0,
        )

    def test_polling_does_not_reset_inactivity(self):
        clock = FakeClock()
        tracker = KeyboardActivityTracker(clock=clock)
        tracker.set_monitoring_available(True)

        tracker.record_keypress()
        clock.advance(5)
        _ = tracker.snapshot()
        clock.advance(5)
        second = tracker.snapshot()

        self.assertAlmostEqual(
            second.current_no_typing_duration,
            10.0,
        )

    def test_unavailable_monitor_returns_none(self):
        clock = FakeClock()
        tracker = KeyboardActivityTracker(clock=clock)
        tracker.set_monitoring_available(False)

        snapshot = tracker.snapshot()

        self.assertFalse(snapshot.monitoring_available)
        self.assertIsNone(snapshot.seconds_since_last_keypress)
        self.assertIsNone(snapshot.current_no_typing_duration)

    def test_public_model_contains_no_key_content(self):
        snapshot = KeyboardActivityTracker().snapshot()
        fields = set(snapshot.__dataclass_fields__)

        forbidden = {
            "key",
            "keys",
            "keycode",
            "characters",
            "text",
            "sequence",
        }

        self.assertTrue(fields.isdisjoint(forbidden))

    def test_typing_rate_and_windows(self):
        clock = FakeClock()
        tracker = KeyboardActivityTracker(clock=clock)
        tracker.set_monitoring_available(True)

        for _ in range(4):
            tracker.record_keypress()
            clock.advance(1)

        snapshot = tracker.snapshot()

        self.assertEqual(
            snapshot.keypresses_last_5_seconds,
            4,
        )
        self.assertEqual(
            snapshot.keypresses_last_30_seconds,
            4,
        )
        self.assertEqual(
            snapshot.typing_rate_per_minute,
            4.0,
        )


if __name__ == "__main__":
    unittest.main()
