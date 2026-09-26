import unittest

from types import SimpleNamespace

from screen_behavior.awareness.keyboard import (
    KeyboardActivityTracker,
    modifier_name,
    shortcut_for_key,
)
from screen_behavior.awareness.models import Shortcut


def key(char=None, vk=None):
    return SimpleNamespace(char=char, vk=vk)


def special(name):
    return SimpleNamespace(name=name)


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


class ShortcutDetectionTests(unittest.TestCase):
    def test_ctrl_c_v_z_on_windows(self):
        held = {"ctrl"}
        # Windows delivers Ctrl+C as a control character plus a vk code.
        self.assertEqual(
            shortcut_for_key(key("\x03", 0x43), held, is_mac=False),
            Shortcut.COPY,
        )
        self.assertEqual(
            shortcut_for_key(key("\x16", 0x56), held, is_mac=False),
            Shortcut.PASTE,
        )
        self.assertEqual(
            shortcut_for_key(key("\x1a", 0x5A), held, is_mac=False),
            Shortcut.UNDO,
        )

    def test_cmd_c_v_z_on_mac(self):
        held = {"cmd"}
        self.assertEqual(
            shortcut_for_key(key("c", 8), held, is_mac=True),
            Shortcut.COPY,
        )
        self.assertEqual(
            shortcut_for_key(key("v", 9), held, is_mac=True),
            Shortcut.PASTE,
        )
        self.assertEqual(
            shortcut_for_key(key("z", 6), held, is_mac=True),
            Shortcut.UNDO,
        )

    def test_ctrl_on_mac_also_counts(self):
        self.assertEqual(
            shortcut_for_key(key("\x03", 8), {"ctrl"}, is_mac=True),
            Shortcut.COPY,
        )

    def test_uppercase_with_shift_still_counts(self):
        self.assertEqual(
            shortcut_for_key(key("C"), {"cmd"}, is_mac=True),
            Shortcut.COPY,
        )

    def test_plain_typing_is_not_a_shortcut(self):
        for char in "cvz":
            self.assertIsNone(
                shortcut_for_key(key(char), set(), is_mac=True)
            )

    def test_other_ctrl_combos_are_ignored(self):
        held = {"ctrl"}
        self.assertIsNone(shortcut_for_key(key("a"), held, is_mac=False))
        self.assertIsNone(shortcut_for_key(key("\x01"), held, is_mac=False))
        self.assertIsNone(shortcut_for_key(key(vk=0x41), held, is_mac=False))

    def test_modifier_names(self):
        self.assertEqual(modifier_name(special("ctrl_l")), "ctrl")
        self.assertEqual(modifier_name(special("cmd_r")), "cmd")
        self.assertIsNone(modifier_name(special("shift")))
        self.assertIsNone(modifier_name(key("c")))

    def test_tracker_counts_shortcuts(self):
        clock = FakeClock()
        tracker = KeyboardActivityTracker(clock=clock)
        tracker.set_monitoring_available(True)

        tracker.record_shortcut(Shortcut.COPY)
        tracker.record_shortcut(Shortcut.PASTE)
        tracker.record_shortcut(Shortcut.PASTE)
        clock.advance(3)

        snapshot = tracker.snapshot()

        self.assertEqual(snapshot.last_shortcut, Shortcut.PASTE)
        self.assertEqual(snapshot.seconds_since_last_shortcut, 3.0)
        self.assertEqual(
            snapshot.shortcut_counts,
            {Shortcut.COPY: 1, Shortcut.PASTE: 2},
        )

    def test_no_shortcuts_yet(self):
        tracker = KeyboardActivityTracker(clock=FakeClock())
        tracker.set_monitoring_available(True)

        snapshot = tracker.snapshot()

        self.assertIsNone(snapshot.last_shortcut)
        self.assertIsNone(snapshot.seconds_since_last_shortcut)
        self.assertEqual(snapshot.shortcut_counts, {})


if __name__ == "__main__":
    unittest.main()
