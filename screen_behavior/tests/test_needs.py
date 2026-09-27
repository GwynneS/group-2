import unittest

from screen_behavior.pet.enums import Behavior
from screen_behavior.pet.models import PetState
from screen_behavior.pet.needs import NeedsSystem


class NeedsTests(unittest.TestCase):
    def test_hunger_causes_faster_energy_drain(self):
        needs = NeedsSystem()

        fed = PetState(
            hunger=10,
            energy=80,
        )
        hungry = PetState(
            hunger=90,
            energy=80,
        )

        needs.tick(fed, 100)
        needs.tick(hungry, 100)

        self.assertLess(
            hungry.energy,
            fed.energy,
        )

    def test_sleep_restores_energy(self):
        needs = NeedsSystem()

        pet = PetState(
            energy=10,
            current_behavior=Behavior.SLEEP,
        )

        needs.tick(pet, 100)

        self.assertGreater(pet.energy, 10)


if __name__ == "__main__":
    unittest.main()
