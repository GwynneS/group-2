import random
import unittest

from screen_behavior.awareness.models import (
    ActivityType,
    KeyboardActivity,
    ScreenContext,
    UserState,
)
from screen_behavior.pet.behavior import BehaviorEngine
from screen_behavior.pet.enums import BaseMood, Behavior
from screen_behavior.pet.models import PetState


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def scores(pet, screen, engine=None):
    engine = engine or BehaviorEngine(rng=random.Random(5), clock=FakeClock())
    return {s.behavior: s.score for s in engine.score_all(pet, screen)}


TYPING = KeyboardActivity(monitoring_available=True, typing_active=True)
CODING = ScreenContext(
    activity=ActivityType.CODING,
    keyboard=TYPING,
    user_state=UserState.FOCUSED,
)
GAMING = ScreenContext(activity=ActivityType.GAMING)
IDLE = ScreenContext(activity=ActivityType.IDLE, user_state=UserState.IDLE)


class UtilityScoringTests(unittest.TestCase):
    def test_study_with_user_wins_while_typing_code(self):
        s = scores(PetState(), CODING)

        self.assertEqual(max(s, key=s.get), Behavior.STUDY_WITH_USER)

    def test_watch_screen_wins_while_gaming(self):
        s = scores(PetState(), GAMING)

        self.assertEqual(max(s, key=s.get), Behavior.WATCH_SCREEN)

    def test_loneliness_raises_ask_for_attention(self):
        content = scores(PetState(attention=90), GAMING)
        lonely = scores(PetState(attention=25), GAMING)

        self.assertGreater(
            lonely[Behavior.ASK_FOR_ATTENTION],
            content[Behavior.ASK_FOR_ATTENTION],
        )

    def test_busy_user_lowers_ask_for_attention(self):
        pet = PetState(attention=25)
        busy = scores(pet, CODING)
        relaxed = scores(pet, GAMING)

        self.assertLess(
            busy[Behavior.ASK_FOR_ATTENTION],
            relaxed[Behavior.ASK_FOR_ATTENTION],
        )

    def test_distracting_behaviors_score_lower_when_focused(self):
        pet = PetState(energy=100, boredom=60)
        focused = scores(pet, CODING)
        idle = scores(pet, IDLE)

        self.assertLess(focused[Behavior.DANCE], idle[Behavior.DANCE])

    def test_low_budget_lowers_distracting_scores(self):
        pet = PetState(energy=100)
        full = BehaviorEngine(rng=random.Random(5), clock=FakeClock())
        empty = BehaviorEngine(rng=random.Random(5), clock=FakeClock())
        empty.budget.value = 0

        self.assertLess(
            scores(pet, GAMING, empty)[Behavior.DANCE],
            scores(pet, GAMING, full)[Behavior.DANCE],
        )

    def test_tired_mood_prefers_rest(self):
        pet = PetState(energy=25)
        pet.mood = BaseMood.TIRED
        s = scores(pet, ScreenContext())

        self.assertGreater(s[Behavior.SIT_DOWN], s[Behavior.DANCE])

    def test_repetition_penalty(self):
        engine = BehaviorEngine(rng=random.Random(5), clock=FakeClock())
        before = scores(PetState(), CODING, engine)[Behavior.STUDY_WITH_USER]

        engine.memory.record_behavior(Behavior.STUDY_WITH_USER, 0)
        after = scores(PetState(), CODING, engine)[Behavior.STUDY_WITH_USER]

        self.assertAlmostEqual(after, before * 0.4)

    def test_decision_reason_explains_choice(self):
        engine = BehaviorEngine(rng=random.Random(5), clock=FakeClock())

        decision = engine.decide(PetState(), CODING)

        self.assertEqual(decision.behavior, Behavior.STUDY_WITH_USER)
        self.assertIn("work", decision.reason)


class EngineSafetyTests(unittest.TestCase):
    def test_play_dead_times_out_without_a_yell(self):
        clock = FakeClock()
        engine = BehaviorEngine(rng=random.Random(5), clock=clock)
        pet = PetState(energy=100)
        engine._start(pet, Behavior.PLAY_DEAD, "test", clock(), force=True)

        clock.advance(30)
        self.assertEqual(engine.decide(pet, GAMING).behavior, Behavior.PLAY_DEAD)

        clock.advance(61)
        decision = engine.decide(pet, GAMING)

        self.assertFalse(pet.play_dead_active)
        self.assertNotEqual(decision.behavior, Behavior.PLAY_DEAD)

    def test_sleep_continues_until_rested(self):
        clock = FakeClock()
        engine = BehaviorEngine(rng=random.Random(5), clock=clock)
        pet = PetState(energy=10)

        self.assertEqual(engine.decide(pet, GAMING).behavior, Behavior.SLEEP)

        pet.energy = 40  # recovering, past the 20s commitment
        clock.advance(60)
        self.assertEqual(engine.decide(pet, GAMING).behavior, Behavior.SLEEP)

        pet.energy = 65
        clock.advance(1)
        self.assertNotEqual(engine.decide(pet, GAMING).behavior, Behavior.SLEEP)


if __name__ == "__main__":
    unittest.main()
