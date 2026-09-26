import unittest
from array import array

from screen_behavior.awareness.microphone import (
    MicrophoneActivity,
    VoiceLevelTracker,
    rms_db,
)
from screen_behavior.awareness.models import ActivityType, ScreenContext
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.pet.enums import BaseMood, Behavior


QUIET_ROOM = -60.0
NORMAL_TALK = -42.0
YELL = -15.0


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def feed_levels(tracker, clock, level, seconds, block=0.05):
    for _ in range(int(round(seconds / block))):
        clock.advance(block)
        tracker.record_level(level)


def make_tracker():
    clock = FakeClock()
    tracker = VoiceLevelTracker(clock=clock)
    tracker.set_monitoring_available(True)
    feed_levels(tracker, clock, QUIET_ROOM, 2.0)
    return tracker, clock


class RmsTests(unittest.TestCase):
    def test_silence_is_minimum(self):
        self.assertEqual(rms_db(array("h", [0] * 100)), -100.0)

    def test_full_scale_is_near_zero(self):
        self.assertAlmostEqual(
            rms_db(array("h", [32767, -32768] * 50)),
            0.0,
            places=2,
        )


class VoiceLevelTrackerTests(unittest.TestCase):
    def test_unavailable_monitor_reports_unavailable(self):
        tracker = VoiceLevelTracker(clock=FakeClock())

        activity = tracker.snapshot()

        self.assertFalse(activity.monitoring_available)
        self.assertFalse(activity.loud_voice_detected)

    def test_quiet_room_is_not_talking_or_loud(self):
        tracker, _ = make_tracker()

        activity = tracker.snapshot()

        self.assertFalse(activity.user_talking)
        self.assertFalse(activity.loud_voice_detected)

    def test_normal_talking_is_not_loud(self):
        tracker, clock = make_tracker()

        feed_levels(tracker, clock, NORMAL_TALK, 1.0)
        activity = tracker.snapshot()

        self.assertTrue(activity.user_talking)
        self.assertFalse(activity.loud_voice_detected)

    def test_yell_is_loud(self):
        tracker, clock = make_tracker()

        feed_levels(tracker, clock, YELL, 0.5)

        self.assertTrue(tracker.snapshot().loud_voice_detected)

    def test_tiny_spike_is_not_loud(self):
        tracker, clock = make_tracker()

        # A single 50ms click/bang, shorter than loud_min_seconds.
        feed_levels(tracker, clock, YELL, 0.05)
        feed_levels(tracker, clock, QUIET_ROOM, 0.2)

        self.assertFalse(tracker.snapshot().loud_voice_detected)

    def test_short_yell_is_held_until_next_poll(self):
        tracker, clock = make_tracker()

        feed_levels(tracker, clock, YELL, 0.3)
        feed_levels(tracker, clock, QUIET_ROOM, 1.0)

        self.assertTrue(tracker.snapshot().loud_voice_detected)

        clock.advance(2.0)
        self.assertFalse(tracker.snapshot().loud_voice_detected)

    def test_noisy_room_raises_the_bar(self):
        tracker, clock = make_tracker()

        # Background noise rises (fan, music). Level that would have been
        # a yell in a quiet room is now just "normal" relative to it.
        feed_levels(tracker, clock, -45.0, 30.0)
        feed_levels(tracker, clock, -30.0, 0.5)

        self.assertFalse(tracker.snapshot().loud_voice_detected)

    def test_yell_still_counts_with_hot_mic(self):
        clock = FakeClock()
        tracker = VoiceLevelTracker(clock=clock)
        tracker.set_monitoring_available(True)

        # Background already at -25 dB; floor + 25 would be 0 dB, which a
        # mic can't record. A -5 dB yell must still wake buddy.
        feed_levels(tracker, clock, -25.0, 2.0)
        feed_levels(tracker, clock, -5.0, 0.5)

        self.assertTrue(tracker.snapshot().loud_voice_detected)

    def test_snapshot_contains_no_audio(self):
        tracker, clock = make_tracker()
        feed_levels(tracker, clock, NORMAL_TALK, 0.5)

        fields = set(MicrophoneActivity.__slots__)

        self.assertEqual(
            fields,
            {
                "monitoring_available",
                "level_db",
                "noise_floor_db",
                "user_talking",
                "loud_voice_detected",
                "seconds_since_voice",
            },
        )


class FakeAwareness:
    def snapshot(self):
        return ScreenContext(activity=ActivityType.OTHER)


class FakeMicrophone:
    def __init__(self):
        self.loud = False
        self.stopped = False

    def snapshot(self):
        return MicrophoneActivity(
            monitoring_available=True,
            loud_voice_detected=self.loud,
        )

    def stop(self):
        self.stopped = True


class BrainMicrophoneTests(unittest.TestCase):
    def make_brain(self):
        clock = FakeClock()
        mic = FakeMicrophone()
        brain = CompanionBrain(
            awareness=FakeAwareness(),
            microphone=mic,
            clock=clock,
        )
        brain.pet.play_dead_active = True
        return brain, mic, clock

    def test_quiet_keeps_buddy_playing_dead(self):
        brain, _, clock = self.make_brain()

        clock.advance(1)
        update = brain.update()

        self.assertEqual(update.decision.behavior, Behavior.PLAY_DEAD)

    def test_yell_wakes_buddy_from_play_dead(self):
        brain, mic, clock = self.make_brain()
        clock.advance(1)
        brain.update()

        mic.loud = True
        clock.advance(1)
        update = brain.update()

        self.assertFalse(brain.pet.play_dead_active)
        self.assertEqual(update.decision.behavior, Behavior.WAVE)
        self.assertEqual(update.decision.mood, BaseMood.SURPRISED)
        self.assertTrue(update.microphone.loud_voice_detected)

    def test_microphone_off_by_default(self):
        brain = CompanionBrain(awareness=FakeAwareness())

        self.assertIsNone(brain.microphone)
        self.assertFalse(brain.update().microphone.monitoring_available)

    def test_close_stops_microphone(self):
        brain, mic, _ = self.make_brain()

        brain.close()

        self.assertTrue(mic.stopped)


if __name__ == "__main__":
    unittest.main()
