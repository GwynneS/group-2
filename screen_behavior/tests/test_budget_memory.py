import unittest

from screen_behavior.awareness.models import ActivityType, ScreenContext
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.pet.behavior import BehaviorEngine
from screen_behavior.pet.distraction import DistractionBudget
from screen_behavior.pet.enums import Behavior
from screen_behavior.pet.interactions import InteractionEffect
from screen_behavior.pet.memory import BehaviorMemory
from screen_behavior.pet.models import PetState


CODING = ScreenContext(activity=ActivityType.CODING)
BROWSING = ScreenContext(activity=ActivityType.BROWSING)
IDLE = ScreenContext(activity=ActivityType.IDLE)


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ChoiceRng:
    """Picks `preferred` when offered, else the first option."""
    def __init__(self, preferred=Behavior.DANCE, random_value=0.5):
        self.preferred = preferred
        self.random_value = random_value

    def random(self):
        return self.random_value

    def choice(self, values):
        if self.preferred in values:
            return self.preferred
        return values[0]


class DistractionBudgetTests(unittest.TestCase):
    def test_distracting_behaviors_cost_budget_quiet_ones_dont(self):
        budget = DistractionBudget()

        budget.spend(Behavior.DANCE)
        after_dance = budget.value
        budget.spend(Behavior.LOOK_AROUND)

        self.assertLess(after_dance, 100)
        self.assertEqual(budget.value, after_dance)

    def test_regen_is_slow_when_focused_fast_when_idle(self):
        focused = DistractionBudget()
        idle = DistractionBudget()
        focused.value = idle.value = 0

        focused.tick(CODING, 60)
        idle.tick(IDLE, 60)

        self.assertLess(focused.value, idle.value)
        self.assertGreater(focused.value, 0)

    def test_budget_is_capped_and_floored(self):
        budget = DistractionBudget()
        budget.tick(IDLE, 10_000)
        self.assertEqual(budget.value, 100)

        budget.value = 5
        budget.spend(Behavior.DANCE)
        self.assertEqual(budget.value, 0)

    def test_engine_skips_behaviors_it_cannot_afford(self):
        clock = FakeClock()
        engine = BehaviorEngine(rng=ChoiceRng(Behavior.DANCE), clock=clock)
        engine.budget.value = 10  # dance costs 35

        decision = engine.decide(PetState(energy=100), BROWSING)

        self.assertNotEqual(decision.behavior, Behavior.DANCE)
        self.assertEqual(decision.distraction_budget, 10)

    def test_engine_spends_budget_once_per_behavior(self):
        clock = FakeClock()
        engine = BehaviorEngine(rng=ChoiceRng(Behavior.DANCE), clock=clock)
        pet = PetState(energy=100)

        engine.decide(pet, BROWSING)
        after_start = engine.budget.value
        clock.advance(1)
        engine.decide(pet, BROWSING)  # still committed to dance

        self.assertEqual(after_start, 65)
        self.assertAlmostEqual(engine.budget.value, 65.3)

    def test_urgent_attention_request_goes_through_on_empty_budget(self):
        engine = BehaviorEngine(rng=ChoiceRng(), clock=FakeClock())
        engine.budget.value = 0

        decision = engine.decide(PetState(attention=5), BROWSING)

        self.assertEqual(decision.behavior, Behavior.ASK_FOR_ATTENTION)


class BehaviorMemoryTests(unittest.TestCase):
    def test_last_5_behaviors(self):
        memory = BehaviorMemory()
        for i, b in enumerate([
            Behavior.WAVE, Behavior.SIT_DOWN, Behavior.STRETCH,
            Behavior.IDLE, Behavior.LOOK_AROUND, Behavior.DANCE,
        ]):
            memory.record_behavior(b, i)

        snapshot = memory.snapshot(10)

        self.assertEqual(snapshot.last_behavior, Behavior.DANCE)
        self.assertEqual(len(snapshot.last_5_behaviors), 5)
        self.assertNotIn(Behavior.WAVE, snapshot.last_5_behaviors)

    def test_repetition_rules(self):
        memory = BehaviorMemory()
        memory.record_behavior(Behavior.WAVE, 0)
        memory.record_behavior(Behavior.SIT_DOWN, 1)
        memory.record_behavior(Behavior.WAVE, 2)
        memory.record_behavior(Behavior.IDLE, 3)

        self.assertTrue(memory.is_repetitive(Behavior.IDLE))   # last one
        self.assertTrue(memory.is_repetitive(Behavior.WAVE))   # 2x in last 5
        self.assertFalse(memory.is_repetitive(Behavior.SIT_DOWN))
        self.assertFalse(memory.is_repetitive(Behavior.DANCE))

    def test_ignored_after_no_response(self):
        memory = BehaviorMemory(ignore_window_seconds=30)
        memory.record_behavior(Behavior.ASK_FOR_ATTENTION, 0)

        self.assertFalse(memory.recently_ignored(10))   # still waiting
        self.assertTrue(memory.recently_ignored(31))    # no response

    def test_interaction_after_request_is_not_ignored(self):
        memory = BehaviorMemory(ignore_window_seconds=30)
        memory.record_behavior(Behavior.ASK_FOR_ATTENTION, 0)
        memory.record_interaction(12)

        self.assertFalse(memory.recently_ignored(31))
        self.assertTrue(memory.recently_interacted_with(31))

    def test_ignored_feeling_wears_off(self):
        memory = BehaviorMemory(
            ignore_window_seconds=30,
            ignored_memory_seconds=300,
        )
        memory.record_behavior(Behavior.ASK_FOR_ATTENTION, 0)

        self.assertFalse(memory.recently_ignored(400))

    def test_engine_does_not_repeat_last_behavior(self):
        clock = FakeClock()
        engine = BehaviorEngine(
            rng=ChoiceRng(Behavior.STUDY_WITH_USER),
            clock=clock,
        )
        pet = PetState(energy=100)

        first = engine.decide(pet, CODING)
        self.assertEqual(first.behavior, Behavior.STUDY_WITH_USER)

        # Past commitment AND cooldown, so only memory can stop a repeat.
        clock.advance(60)
        second = engine.decide(pet, CODING)

        self.assertNotEqual(second.behavior, Behavior.STUDY_WITH_USER)

    def test_ignored_buddy_sulks_instead_of_nagging(self):
        clock = FakeClock()
        engine = BehaviorEngine(rng=ChoiceRng(), clock=clock)
        pet = PetState(attention=5)

        first = engine.decide(pet, BROWSING)
        self.assertEqual(first.behavior, Behavior.ASK_FOR_ATTENTION)

        clock.advance(40)  # nobody responded
        second = engine.decide(pet, BROWSING)

        self.assertEqual(second.behavior, Behavior.SIT_DOWN)
        self.assertIn("ignored", second.reason)


class FakeAwareness:
    def snapshot(self):
        return BROWSING


class BrainMemoryTests(unittest.TestCase):
    def test_feeding_and_interactions_count_as_attention(self):
        clock = FakeClock()
        engine = BehaviorEngine(clock=clock)
        brain = CompanionBrain(awareness=FakeAwareness(), behavior=engine)

        self.assertFalse(brain.update().memory.recently_interacted_with)

        brain.pet.hunger = 60
        brain.feed()
        self.assertTrue(brain.update().memory.recently_interacted_with)

        clock.advance(1000)
        self.assertFalse(brain.update().memory.recently_interacted_with)

        brain.apply_interaction(InteractionEffect(affection_delta=1))
        self.assertTrue(brain.update().memory.recently_interacted_with)


if __name__ == "__main__":
    unittest.main()
