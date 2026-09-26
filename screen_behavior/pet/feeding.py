from __future__ import annotations

from dataclasses import dataclass

from screen_behavior.pet.models import PetState


@dataclass(frozen=True, slots=True)
class FeedingConfig:
    # Hunger convention matches PetState: 0 = full, 100 = starving.
    # Buddy refuses fish at or below this hunger level.
    full_hunger_threshold: float = 10.0

    hunger_delta: float = -35.0
    energy_delta: float = 10.0
    affection_delta: float = 6.0
    attention_delta: float = 5.0


@dataclass(slots=True)
class FeedResult:
    accepted: bool
    reason: str


class FeedingSystem:
    """
    Fish is buddy's only food. This module owns what fish does to
    Tamagotchi state; another group decides *when* the user feeds buddy
    (button, drag-and-drop, etc.) and calls CompanionBrain.feed().
    """

    def __init__(self, config: FeedingConfig | None = None) -> None:
        self.config = config or FeedingConfig()

    def feed(self, state: PetState) -> FeedResult:
        c = self.config

        if state.hunger <= c.full_hunger_threshold:
            return FeedResult(False, "buddy is full and won't eat")

        state.hunger += c.hunger_delta
        state.energy += c.energy_delta
        state.affection += c.affection_delta
        state.attention += c.attention_delta
        state.clamp_all()

        return FeedResult(True, "buddy ate the fish")
