from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from awareness.models import ScreenContext
from awareness.windows import ScreenAwarenessService
from pet.behavior import BehaviorDecision, BehaviorEngine
from pet.models import PetState
from pet.needs import NeedsSystem


@dataclass(slots=True)
class BrainUpdate:
    pet: PetState
    screen: ScreenContext
    decision: BehaviorDecision


class CompanionBrain:
    """
    Small integration layer shared by the screen-awareness and behavior teams.
    """

    def __init__(self) -> None:
        self.pet = PetState()
        self.awareness = ScreenAwarenessService()
        self.needs = NeedsSystem()
        self.behavior = BehaviorEngine()
        self._last_tick = monotonic()

    def update(self) -> BrainUpdate:
        now = monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        self.needs.tick(self.pet, dt)
        screen = self.awareness.snapshot()
        decision = self.behavior.decide(self.pet, screen)
        self.pet.current_behavior = decision.behavior

        return BrainUpdate(
            pet=self.pet,
            screen=screen,
            decision=decision,
        )

    def pet_character(self) -> None:
        self.needs.pet(self.pet)

    def feed_character(self) -> None:
        self.needs.feed(self.pet)

    def play_with_character(self) -> None:
        self.needs.play(self.pet)
