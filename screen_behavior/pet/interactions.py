from __future__ import annotations

from dataclasses import dataclass

from screen_behavior.pet.models import PetState


@dataclass(slots=True)
class InteractionEffect:
    """
    Generic hook for Person 6.

    This subsystem does NOT define petting, food items, menus, rewards, or
    interaction content. Another subsystem decides that an interaction occurred
    and may provide the numeric effect to apply.
    """

    energy_delta: float = 0.0
    hunger_delta: float = 0.0
    attention_delta: float = 0.0
    affection_delta: float = 0.0
    boredom_delta: float = 0.0
    # Make buddy hyper for this many seconds (0 = no change).
    hyper_seconds: float = 0.0


def apply_interaction_effect(
    state: PetState,
    effect: InteractionEffect,
) -> None:
    state.energy += effect.energy_delta
    state.hunger += effect.hunger_delta
    state.attention += effect.attention_delta
    state.affection += effect.affection_delta
    state.boredom += effect.boredom_delta
    state.hyper_seconds_remaining = max(
        state.hyper_seconds_remaining,
        effect.hyper_seconds,
    )
    state.clamp_all()
