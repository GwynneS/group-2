import unittest

from screen_behavior.awareness.evidence import EvidenceAccumulator
from screen_behavior.awareness.models import (
    ActivityClassification,
    ActivityType,
    KeyboardActivity,
    ScreenContext,
    UserState,
)
from screen_behavior.awareness.user_state import UserStateTracker


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def raw(**scores):
    full = {a: 0.02 for a in ActivityType}
    full.update({ActivityType(k): v for k, v in scores.items()})
    leader = max(full, key=full.get)
    return ActivityClassification(leader, full[leader], full)


CODING_RAW = raw(coding=0.98)
BROWSING_RAW = raw(browsing=0.75)
IDLE_RAW = raw(idle=0.99)


class EvidenceTests(unittest.TestCase):
    def feed(self, evidence, clock, sample, seconds):
        result = None
        for _ in range(int(seconds)):
            clock.advance(1)
            result = evidence.update(sample)
        return result

    def test_first_sample_is_used_directly(self):
        evidence = EvidenceAccumulator(clock=FakeClock())

        result = evidence.update(CODING_RAW)

        self.assertEqual(result.activity, ActivityType.CODING)
        self.assertAlmostEqual(result.confidence, 0.98)

    def test_brief_switch_does_not_change_leader(self):
        clock = FakeClock()
        evidence = EvidenceAccumulator(clock=clock)
        self.feed(evidence, clock, CODING_RAW, 60)

        result = self.feed(evidence, clock, BROWSING_RAW, 5)

        self.assertEqual(result.activity, ActivityType.CODING)

    def test_sustained_switch_changes_leader(self):
        clock = FakeClock()
        evidence = EvidenceAccumulator(clock=clock)
        self.feed(evidence, clock, CODING_RAW, 60)

        result = self.feed(evidence, clock, BROWSING_RAW, 45)

        self.assertEqual(result.activity, ActivityType.BROWSING)

    def test_evidence_decays_with_time_not_poll_count(self):
        clock = FakeClock()
        evidence = EvidenceAccumulator(clock=clock)
        evidence.update(CODING_RAW)

        clock.advance(60)  # one late poll after a long gap
        result = evidence.update(BROWSING_RAW)

        self.assertEqual(result.activity, ActivityType.BROWSING)

    def test_returning_from_idle_is_immediate(self):
        clock = FakeClock()
        evidence = EvidenceAccumulator(clock=clock)
        self.feed(evidence, clock, IDLE_RAW, 300)

        clock.advance(1)
        result = evidence.update(CODING_RAW)

        self.assertNotEqual(result.activity, ActivityType.IDLE)


def screen(activity=ActivityType.CODING, idle=0.0, typed_ago=1.0,
           previous=None, duration=600.0, changed=False):
    return ScreenContext(
        activity=activity,
        idle_seconds=idle,
        previous_activity=previous,
        activity_duration_seconds=duration,
        activity_changed=changed,
        keyboard=KeyboardActivity(
            monitoring_available=True,
            typing_active=typed_ago is not None and typed_ago < 2,
            seconds_since_last_keypress=typed_ago,
        ),
    )


class UserStateClassifyTests(unittest.TestCase):
    def setUp(self):
        self.tracker = UserStateTracker(clock=FakeClock())

    def test_coding_with_typing_is_focused(self):
        self.assertEqual(self.tracker.classify(screen()), UserState.FOCUSED)

    def test_coding_while_thinking_is_still_focused(self):
        self.assertEqual(
            self.tracker.classify(screen(typed_ago=60, idle=5)),
            UserState.FOCUSED,
        )

    def test_coding_without_typing_for_long_is_passive(self):
        self.assertEqual(
            self.tracker.classify(screen(typed_ago=200, idle=10)),
            UserState.PASSIVE,
        )

    def test_video_is_passive(self):
        self.assertEqual(
            self.tracker.classify(
                screen(activity=ActivityType.VIDEO, typed_ago=None, idle=20)
            ),
            UserState.PASSIVE,
        )

    def test_gaming_is_active(self):
        self.assertEqual(
            self.tracker.classify(screen(activity=ActivityType.GAMING)),
            UserState.ACTIVE,
        )

    def test_drifting_from_work_to_browsing_is_distracted(self):
        self.assertEqual(
            self.tracker.classify(screen(
                activity=ActivityType.BROWSING,
                previous=ActivityType.CODING,
                duration=60,
            )),
            UserState.DISTRACTED,
        )

    def test_idle_and_away(self):
        self.assertEqual(
            self.tracker.classify(screen(idle=90)),
            UserState.IDLE,
        )
        self.assertEqual(
            self.tracker.classify(screen(idle=400)),
            UserState.AWAY,
        )

    def test_body_tracking_absence_means_away(self):
        self.assertEqual(
            self.tracker.classify(screen(), present=False),
            UserState.AWAY,
        )

    def test_body_tracking_presence_prevents_inferred_away(self):
        self.assertEqual(
            self.tracker.classify(screen(idle=900), present=True),
            UserState.IDLE,
        )

    def test_keyboard_unavailable_falls_back_to_idle_time(self):
        context = screen(idle=3)
        context.keyboard = KeyboardActivity(monitoring_available=False)

        self.assertEqual(self.tracker.classify(context), UserState.FOCUSED)


class UserStateStabilityTests(unittest.TestCase):
    def test_new_state_must_hold_before_switching(self):
        clock = FakeClock()
        tracker = UserStateTracker(clock=clock, stable_seconds=5)
        tracker.update(screen())

        gaming = screen(activity=ActivityType.GAMING)
        clock.advance(2)
        self.assertEqual(tracker.update(gaming)[0], UserState.FOCUSED)
        clock.advance(5)  # held for 5s since first seen
        self.assertEqual(tracker.update(gaming)[0], UserState.ACTIVE)

    def test_going_away_is_immediate(self):
        clock = FakeClock()
        tracker = UserStateTracker(clock=clock)
        tracker.update(screen())

        clock.advance(1)
        state, _ = tracker.update(screen(), present=False)

        self.assertEqual(state, UserState.AWAY)

    def test_coming_back_is_immediate(self):
        clock = FakeClock()
        tracker = UserStateTracker(clock=clock)
        tracker.update(screen(idle=400))

        clock.advance(1)
        state, seconds = tracker.update(screen())

        self.assertEqual(state, UserState.FOCUSED)
        self.assertEqual(seconds, 0)

    def test_app_hopping_is_distracted(self):
        clock = FakeClock()
        tracker = UserStateTracker(clock=clock, stable_seconds=0)
        for activity in [ActivityType.CODING, ActivityType.BROWSING,
                         ActivityType.CODING, ActivityType.VIDEO]:
            clock.advance(10)
            state, _ = tracker.update(screen(activity=activity, changed=True))

        self.assertEqual(state, UserState.DISTRACTED)


class ScreenContextHelperTests(unittest.TestCase):
    def test_working_uses_user_state_when_present(self):
        context = ScreenContext(activity=ActivityType.CODING)
        self.assertTrue(context.user_is_working)

        context.user_state = UserState.AWAY
        self.assertFalse(context.user_is_working)
        self.assertTrue(context.user_is_idle)


if __name__ == "__main__":
    unittest.main()
