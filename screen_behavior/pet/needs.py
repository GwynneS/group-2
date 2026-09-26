from __future__ import annotations

from screen_behavior.pet.config import NeedsConfig
from screen_behavior.pet.enums import BaseMood, Behavior, SpecialMood
from screen_behavior.pet.models import PetState


class NeedsSystem:
    def __init__(self, config: NeedsConfig | None = None) -> None:
        self.config = config or NeedsConfig()

    def tick(self, state: PetState, dt_seconds: float) -> None:
        dt = max(0.0, dt_seconds)
        c = self.config

        state.hunger += c.hunger_per_second * dt
        state.attention -= c.attention_drain_per_second * dt
        state.boredom += c.boredom_gain_per_second * dt
        state.hyper_seconds_remaining = max(
            0.0,
            state.hyper_seconds_remaining - dt,
        )

        if state.current_behavior == Behavior.SLEEP:
            state.energy += c.sleep_energy_restore_per_second * dt
        else:
            if state.hunger >= 70:
                multiplier = c.hungry_energy_multiplier
            elif state.hunger >= 45:
                multiplier = c.somewhat_hungry_energy_multiplier
            else:
                multiplier = 1.0

            state.energy -= (
                c.base_energy_drain_per_second
                * multiplier
                * dt
            )

        state.clamp_all()
        self.update_mood(state)

    def update_mood(self, state: PetState) -> None:
        # Base mood priority.
        if state.energy <= 18:
            state.mood = BaseMood.TIRED
        elif state.hunger >= 75:
            state.mood = BaseMood.HUNGRY
        elif state.is_hyper:
            state.mood = BaseMood.EXCITED
        elif state.attention <= 18:
            state.mood = BaseMood.LONELY
        elif state.energy >= 82 and state.affection >= 70:
            state.mood = BaseMood.EXCITED
        elif state.affection >= 70 and state.attention >= 50:
            state.mood = BaseMood.HAPPY
        else:
            state.mood = BaseMood.NEUTRAL

        # Special mood can coexist with base mood.
        if state.affection >= 82 and state.attention >= 60:
            state.special_mood = SpecialMood.AFFECTIONATE
        elif state.affection >= 75 and state.attention <= 25:
            state.special_mood = SpecialMood.JEALOUS
        elif (
            state.affection >= 60
            and state.energy >= 60
            and state.attention >= 45
        ):
            state.special_mood = SpecialMood.CUTE
        else:
            state.special_mood = None
