from __future__ import annotations

from time import time

from pet.models import PetState


class NeedsSystem:
    """
    Changes the Tamagotchi values over time.

    Rates are intentionally exaggerated for prototype testing.
    Slow them down later for real gameplay.
    """

    def tick(self, state: PetState, dt_seconds: float) -> None:
        state.attention -= 0.045 * dt_seconds
        state.hunger -= 0.020 * dt_seconds
        state.energy -= 0.012 * dt_seconds
        state.boredom += 0.025 * dt_seconds

        state.clamp_all()
        self._update_mood(state)

    def pet(self, state: PetState) -> None:
        state.attention += 12
        state.affection += 3
        state.boredom -= 4
        state.total_pets += 1
        state.last_interaction_at = time()
        state.clamp_all()
        self._update_mood(state)

    def feed(self, state: PetState) -> None:
        state.hunger += 25
        state.affection += 1
        state.last_interaction_at = time()
        state.clamp_all()
        self._update_mood(state)

    def play(self, state: PetState) -> None:
        state.boredom -= 30
        state.attention += 8
        state.energy -= 8
        state.affection += 2
        state.last_interaction_at = time()
        state.clamp_all()
        self._update_mood(state)

    def _update_mood(self, state: PetState) -> None:
        if state.energy <= 18:
            state.mood = "sleepy"
        elif state.hunger <= 18:
            state.mood = "hungry"
        elif state.attention <= 20:
            state.mood = "needy"
        elif state.boredom >= 80:
            state.mood = "bored"
        elif state.affection >= 75 and state.attention >= 55:
            state.mood = "happy"
        else:
            state.mood = "content"
