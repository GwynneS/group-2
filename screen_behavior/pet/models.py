from __future__ import annotations

from dataclasses import dataclass

from screen_behavior.pet.enums import BaseMood, Behavior, SpecialMood


def clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


@dataclass(slots=True)
class PetState:
    # Hunger convention:
    # 0 = completely full
    # 100 = extremely hungry
    hunger: float = 20.0
    energy: float = 80.0
    attention: float = 75.0
    affection: float = 50.0
    boredom: float = 20.0

    mood: BaseMood = BaseMood.NEUTRAL
    special_mood: SpecialMood | None = None
    current_behavior: Behavior = Behavior.IDLE

    play_dead_active: bool = False

    def clamp_all(self) -> None:
        self.hunger = clamp(self.hunger)
        self.energy = clamp(self.energy)
        self.attention = clamp(self.attention)
        self.affection = clamp(self.affection)
        self.boredom = clamp(self.boredom)
