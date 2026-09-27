import unittest

from screen_behavior.awareness.models import ScreenContext
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.pet.feeding import FeedingSystem
from screen_behavior.pet.models import PetState


class FakeAwareness:
    def snapshot(self):
        return ScreenContext()


class FeedingTests(unittest.TestCase):
    def test_fish_fills_hunger_and_gives_energy(self):
        feeding = FeedingSystem()
        pet = PetState(hunger=60, energy=50, affection=50)

        result = feeding.feed(pet)

        self.assertTrue(result.accepted)
        self.assertEqual(pet.hunger, 25)
        self.assertEqual(pet.energy, 60)
        self.assertEqual(pet.affection, 56)

    def test_buddy_refuses_fish_when_full(self):
        feeding = FeedingSystem()
        pet = PetState(hunger=5, energy=50)

        result = feeding.feed(pet)

        self.assertFalse(result.accepted)
        self.assertEqual(pet.hunger, 5)
        self.assertEqual(pet.energy, 50)

    def test_hunger_never_goes_below_zero(self):
        feeding = FeedingSystem()
        pet = PetState(hunger=20)

        feeding.feed(pet)

        self.assertEqual(pet.hunger, 0)

    def test_fish_can_be_fed_repeatedly_until_full(self):
        feeding = FeedingSystem()
        pet = PetState(hunger=90)

        results = [feeding.feed(pet).accepted for _ in range(4)]

        self.assertEqual(results, [True, True, True, False])


class BrainFeedingTests(unittest.TestCase):
    def test_brain_feed_updates_mood(self):
        brain = CompanionBrain(awareness=FakeAwareness())
        brain.pet.hunger = 80
        brain.needs.update_mood(brain.pet)
        self.assertEqual(brain.pet.mood.value, "hungry")

        result = brain.feed()

        self.assertTrue(result.accepted)
        self.assertNotEqual(brain.pet.mood.value, "hungry")


if __name__ == "__main__":
    unittest.main()
