import unittest

from screen_behavior.awareness.models import (
    ActivityType,
    ScreenContext,
)
from screen_behavior.pet.behavior import (
    BehaviorEngine,
    ExternalSignals,
)
from screen_behavior.pet.enums import Behavior
from screen_behavior.pet.models import PetState
from screen_behavior.pet.needs import NeedsSystem


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ChoiceRng:
    """
    Deterministic RNG that prefers a requested behavior when available.
    """
    def __init__(self, preferred=Behavior.DANCE, random_value=0.5):
        self.preferred = preferred
        self.random_value = random_value

    def random(self):
        return self.random_value

    def choice(self, values):
        if self.preferred in values:
            return self.preferred
        return values[0]


class BehaviorTests(unittest.TestCase):
    def test_low_energy_sleeps(self):
        clock = FakeClock()
        pet = PetState(energy=10)

        decision = BehaviorEngine(
            rng=ChoiceRng(),
            clock=clock,
        ).decide(
            pet,
            ScreenContext(),
        )

        self.assertEqual(
            decision.behavior,
            Behavior.SLEEP,
        )

    def test_low_attention_asks_for_attention(self):
        clock = FakeClock()
        pet = PetState(attention=5)

        decision = BehaviorEngine(
            rng=ChoiceRng(),
            clock=clock,
        ).decide(
            pet,
            ScreenContext(),
        )

        self.assertEqual(
            decision.behavior,
            Behavior.ASK_FOR_ATTENTION,
        )

    def test_work_context_prefers_low_distraction(self):
        allowed = {
            Behavior.STUDY_WITH_USER,
            Behavior.SIT_DOWN,
            Behavior.FOLLOW_MOUSE_WITH_EYES,
            Behavior.LOOK_AROUND,
            Behavior.STRETCH,
        }

        for preferred in [
            Behavior.DANCE,
            Behavior.WALK_AROUND_CORNER,
            Behavior.WAVE,
        ]:
            clock = FakeClock()
            engine = BehaviorEngine(
                rng=ChoiceRng(preferred=preferred),
                clock=clock,
            )

            decision = engine.decide(
                PetState(energy=100),
                ScreenContext(activity=ActivityType.CODING),
            )

            self.assertIn(
                decision.behavior,
                allowed,
            )

    def test_commitment_prevents_rapid_switching(self):
        clock = FakeClock()
        engine = BehaviorEngine(
            rng=ChoiceRng(preferred=Behavior.DANCE),
            clock=clock,
        )
        pet = PetState(energy=100)
        screen = ScreenContext()

        first = engine.decide(pet, screen)
        clock.advance(1)
        second = engine.decide(pet, screen)

        self.assertEqual(
            second.behavior,
            first.behavior,
        )
        self.assertGreater(
            second.commitment_remaining_seconds,
            0,
        )

    def test_dance_cooldown_prevents_immediate_repeat(self):
        clock = FakeClock()
        engine = BehaviorEngine(
            rng=ChoiceRng(preferred=Behavior.DANCE),
            clock=clock,
        )
        pet = PetState(energy=100)
        screen = ScreenContext()

        first = engine.decide(pet, screen)
        self.assertEqual(first.behavior, Behavior.DANCE)

        # Past the dance commitment but still well inside cooldown.
        clock.advance(20)
        second = engine.decide(pet, screen)

        self.assertNotEqual(
            second.behavior,
            Behavior.DANCE,
        )

    def test_play_dead_wake_signal(self):
        clock = FakeClock()
        pet = PetState()
        pet.play_dead_active = True

        decision = BehaviorEngine(
            rng=ChoiceRng(),
            clock=clock,
        ).decide(
            pet,
            ScreenContext(),
            ExternalSignals(
                loud_voice_detected=True,
            ),
        )

        self.assertFalse(pet.play_dead_active)
        self.assertEqual(
            decision.behavior,
            Behavior.WAVE,
        )

    def test_behavior_energy_cost_is_spent_once(self):
        clock = FakeClock()
        engine = BehaviorEngine(
            rng=ChoiceRng(preferred=Behavior.DANCE),
            clock=clock,
        )
        pet = PetState(energy=100)

        first = engine.decide(
            pet,
            ScreenContext(),
        )
        energy_after_start = pet.energy

        clock.advance(1)
        engine.decide(
            pet,
            ScreenContext(),
        )

        self.assertEqual(
            pet.energy,
            energy_after_start,
        )


if __name__ == "__main__":
    unittest.main()
