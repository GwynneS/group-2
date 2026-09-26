import random
import unittest

from screen_behavior.awareness.models import ActivityType, ScreenContext
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.pet.behavior import BehaviorEngine
from screen_behavior.pet.enums import BaseMood, Behavior
from screen_behavior.pet.feeding import FeedingSystem, FoodType
from screen_behavior.pet.models import PetState
from screen_behavior.pet.needs import NeedsSystem


CODING = ScreenContext(activity=ActivityType.CODING)
BROWSING = ScreenContext(activity=ActivityType.BROWSING)


class FakeAwareness:
    def __init__(self, screen):
        self.screen = screen

    def snapshot(self):
        return self.screen


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FeedingTests(unittest.TestCase):
    def test_dry_food_fills_hunger_and_gives_a_little_energy(self):
        feeding = FeedingSystem()
        pet = PetState(hunger=60, energy=50, affection=50)

        result = feeding.feed(pet, FoodType.DRY)

        self.assertTrue(result.accepted)
        self.assertEqual(pet.hunger, 35)
        self.assertEqual(pet.energy, 55)
        self.assertFalse(pet.is_hyper)

    def test_wet_food_is_better_than_dry_food(self):
        feeding = FeedingSystem()
        feeding.wet_food_available = 1
        dry_pet = PetState(hunger=60, energy=50, affection=50)
        wet_pet = PetState(hunger=60, energy=50, affection=50)

        feeding.feed(dry_pet, FoodType.DRY)
        feeding.feed(wet_pet, FoodType.WET)

        self.assertLess(wet_pet.hunger, dry_pet.hunger)
        self.assertGreater(wet_pet.energy, dry_pet.energy)
        self.assertGreater(wet_pet.affection, dry_pet.affection)

    def test_buddy_refuses_food_when_full(self):
        feeding = FeedingSystem()
        pet = PetState(hunger=5, energy=50)

        result = feeding.feed(pet, FoodType.DRY)

        self.assertFalse(result.accepted)
        self.assertEqual(pet.hunger, 5)
        self.assertEqual(pet.energy, 50)

    def test_wet_food_requires_being_earned(self):
        feeding = FeedingSystem()
        pet = PetState(hunger=60)

        result = feeding.feed(pet, FoodType.WET)

        self.assertFalse(result.accepted)
        self.assertEqual(pet.hunger, 60)

    def test_refused_wet_food_is_not_used_up(self):
        feeding = FeedingSystem()
        feeding.wet_food_available = 1
        pet = PetState(hunger=5)

        feeding.feed(pet, FoodType.WET)

        self.assertEqual(feeding.wet_food_available, 1)

    def test_productive_time_earns_wet_food(self):
        feeding = FeedingSystem()
        pet = PetState()
        per_food = feeding.config.productive_seconds_per_wet_food

        feeding.tick(pet, CODING, per_food - 1)
        self.assertEqual(feeding.wet_food_available, 0)

        feeding.tick(pet, CODING, 1)
        self.assertEqual(feeding.wet_food_available, 1)

    def test_non_productive_time_does_not_earn_wet_food(self):
        feeding = FeedingSystem()
        pet = PetState()

        feeding.tick(pet, BROWSING, 10 * 60 * 60)

        self.assertEqual(feeding.wet_food_available, 0)

    def test_wet_food_stash_is_capped(self):
        feeding = FeedingSystem()
        pet = PetState()

        feeding.tick(pet, CODING, 10 * 60 * 60)

        self.assertEqual(
            feeding.wet_food_available,
            feeding.config.max_wet_food,
        )

    def test_wet_food_makes_buddy_hyper_then_wears_off(self):
        feeding = FeedingSystem()
        feeding.wet_food_available = 1
        pet = PetState(hunger=60)

        feeding.feed(pet, FoodType.WET)
        self.assertTrue(pet.is_hyper)

        feeding.tick(pet, BROWSING, feeding.config.wet.hyper_seconds)
        self.assertFalse(pet.is_hyper)

    def test_hyper_buddy_is_excited(self):
        needs = NeedsSystem()
        pet = PetState(hunger=20, energy=60, hyper_seconds_remaining=30)

        needs.update_mood(pet)

        self.assertEqual(pet.mood, BaseMood.EXCITED)

    def test_hyper_buddy_prefers_energetic_behavior(self):
        engine = BehaviorEngine(rng=random.Random(1), clock=lambda: 0.0)
        pet = PetState(energy=90, hyper_seconds_remaining=30)

        decision = engine.decide(pet, BROWSING)

        self.assertIn(
            decision.behavior,
            {Behavior.DANCE, Behavior.WAVE, Behavior.WALK_AROUND_CORNER},
        )


class BrainFeedingTests(unittest.TestCase):
    def test_brain_feed_and_status(self):
        clock = FakeClock()
        brain = CompanionBrain(
            awareness=FakeAwareness(CODING),
            clock=clock,
        )
        brain.pet.hunger = 60

        clock.advance(brain.feeding.config.productive_seconds_per_wet_food)
        update = brain.update()
        self.assertEqual(update.feeding.wet_food_available, 1)

        result = brain.feed(FoodType.WET)

        self.assertTrue(result.accepted)
        self.assertEqual(brain.pet.mood, BaseMood.EXCITED)
        self.assertEqual(brain.update().feeding.wet_food_available, 0)


if __name__ == "__main__":
    unittest.main()
