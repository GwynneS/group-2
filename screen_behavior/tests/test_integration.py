import unittest

from screen_behavior.awareness.models import (
    ActivityType,
    KeyboardActivity,
    ScreenContext,
)
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.pet.interactions import InteractionEffect


class FakeAwareness:
    def snapshot(self):
        return ScreenContext(
            activity=ActivityType.CODING,
            activity_confidence=0.98,
            keyboard=KeyboardActivity(
                monitoring_available=True,
                typing_active=True,
                current_no_typing_duration=0.0,
            ),
        )

    def close(self):
        pass


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class IntegrationTests(unittest.TestCase):
    def test_other_groups_can_use_brain_update(self):
        clock = FakeClock()

        brain = CompanionBrain(
            awareness=FakeAwareness(),
            clock=clock,
        )

        update = brain.update()

        self.assertEqual(
            update.screen.activity,
            ActivityType.CODING,
        )
        self.assertIsNotNone(
            update.decision.behavior,
        )

    def test_generic_interaction_effect_hook(self):
        brain = CompanionBrain(
            awareness=FakeAwareness(),
        )

        before = brain.pet.affection

        brain.apply_interaction(
            InteractionEffect(
                affection_delta=5,
                attention_delta=10,
            )
        )

        self.assertEqual(
            brain.pet.affection,
            before + 5,
        )


if __name__ == "__main__":
    unittest.main()
