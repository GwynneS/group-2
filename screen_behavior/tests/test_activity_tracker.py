import unittest

from screen_behavior.awareness.activity_tracker import (
    ActivityStabilityTracker,
)
from screen_behavior.awareness.models import (
    ActivityClassification,
    ActivityType,
)


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def classification(
    leader,
    **scores,
):
    mapped = {
        ActivityType[key.upper()]: value
        for key, value in scores.items()
    }
    for activity in ActivityType:
        mapped.setdefault(activity, 0.01)

    return ActivityClassification(
        activity=leader,
        confidence=mapped[leader],
        scores=mapped,
    )


class ActivityTrackerTests(unittest.TestCase):
    def test_duration_increases_without_resetting(self):
        clock = FakeClock()
        tracker = ActivityStabilityTracker(clock=clock)

        tracker.update(
            classification(
                ActivityType.CODING,
                coding=0.95,
                browsing=0.10,
            )
        )

        clock.advance(15)

        state = tracker.update(
            classification(
                ActivityType.CODING,
                coding=0.94,
                browsing=0.11,
            )
        )

        self.assertFalse(state.activity_changed)
        self.assertEqual(state.duration_seconds, 15)

    def test_small_confidence_flip_does_not_switch(self):
        clock = FakeClock()
        tracker = ActivityStabilityTracker(
            clock=clock,
            switch_margin=0.08,
            switch_delay_seconds=1.5,
        )

        tracker.update(
            classification(
                ActivityType.CODING,
                coding=0.91,
                browsing=0.30,
            )
        )

        clock.advance(1)

        state = tracker.update(
            classification(
                ActivityType.BROWSING,
                coding=0.90,
                browsing=0.92,
            )
        )

        self.assertEqual(state.activity, ActivityType.CODING)
        self.assertIsNone(state.pending_activity)

    def test_stronger_challenger_must_remain_stable_before_switch(self):
        clock = FakeClock()
        tracker = ActivityStabilityTracker(
            clock=clock,
            switch_margin=0.08,
            switch_delay_seconds=1.5,
            immediate_switch_confidence=1.1,  # disable immediate switch
        )

        tracker.update(
            classification(
                ActivityType.CODING,
                coding=0.90,
                browsing=0.10,
            )
        )

        clock.advance(1)
        pending = tracker.update(
            classification(
                ActivityType.BROWSING,
                coding=0.25,
                browsing=0.80,
            )
        )

        self.assertEqual(pending.activity, ActivityType.CODING)
        self.assertEqual(
            pending.pending_activity,
            ActivityType.BROWSING,
        )

        clock.advance(1.6)
        switched = tracker.update(
            classification(
                ActivityType.BROWSING,
                coding=0.20,
                browsing=0.82,
            )
        )

        self.assertTrue(switched.activity_changed)
        self.assertEqual(
            switched.activity,
            ActivityType.BROWSING,
        )
        self.assertEqual(
            switched.previous_activity,
            ActivityType.CODING,
        )
        self.assertEqual(switched.duration_seconds, 0.0)

    def test_obvious_transition_can_switch_immediately(self):
        clock = FakeClock()
        tracker = ActivityStabilityTracker(clock=clock)

        tracker.update(
            classification(
                ActivityType.CODING,
                coding=0.98,
                browsing=0.05,
            )
        )

        clock.advance(1)

        state = tracker.update(
            classification(
                ActivityType.GAMING,
                coding=0.05,
                gaming=0.97,
            )
        )

        self.assertTrue(state.activity_changed)
        self.assertEqual(state.activity, ActivityType.GAMING)


if __name__ == "__main__":
    unittest.main()
