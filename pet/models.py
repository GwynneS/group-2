from __future__ import annotations

from dataclasses import dataclass, field
from time import time


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class PetState:
    affection: float = 50.0
    attention: float = 75.0
    hunger: float = 80.0
    energy: float = 90.0
    boredom: float = 20.0

    mood: str = "content"
    current_behavior: str = "idle"

    last_interaction_at: float = field(default_factory=time)
    total_pets: int = 0

    def clamp_all(self) -> None:
        self.affection = clamp(self.affection)
        self.attention = clamp(self.attention)
        self.hunger = clamp(self.hunger)
        self.energy = clamp(self.energy)
        self.boredom = clamp(self.boredom)
