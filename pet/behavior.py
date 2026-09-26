from __future__ import annotations

import random
from dataclasses import dataclass

from awareness.models import ScreenContext
from pet.models import PetState


@dataclass(slots=True)
class BehaviorDecision:
    behavior: str
    emotion: str
    reason: str
    dialogue_intent: str | None = None


class BehaviorEngine:
    """
    Converts pet needs + desktop context into a high-level action.

    It does NOT know anything about the final 3D model.
    The renderer/animation team only needs to map behavior names like
    "sleep", "walk", "study", "ask_attention" to animations.
    """

    def decide(self, pet: PetState, screen: ScreenContext) -> BehaviorDecision:
        # Strong needs win first.
        if pet.energy <= 18:
            return BehaviorDecision(
                behavior="sleep",
                emotion="sleepy",
                reason="energy is critically low",
            )

        if pet.hunger <= 18:
            return BehaviorDecision(
                behavior="ask_food",
                emotion="hungry",
                reason="hunger is critically low",
                dialogue_intent="ask_for_food",
            )

        if pet.attention <= 20:
            return BehaviorDecision(
                behavior="ask_attention",
                emotion="needy",
                reason="attention is critically low",
                dialogue_intent="ask_for_attention",
            )

        if pet.boredom >= 80:
            return BehaviorDecision(
                behavior="ask_play",
                emotion="bored",
                reason="boredom is very high",
                dialogue_intent="ask_to_play",
            )

        # Desktop awareness modifies normal behavior.
        if screen.idle_seconds >= 300:
            return BehaviorDecision(
                behavior="nap",
                emotion="calm",
                reason="user has been idle for at least five minutes",
            )

        if screen.activity_kind in {"coding", "school"}:
            return BehaviorDecision(
                behavior="study_with_user",
                emotion="focused",
                reason=f"user appears to be {screen.activity_kind}",
            )

        if screen.activity_kind == "gaming":
            return BehaviorDecision(
                behavior="watch_user",
                emotion="excited",
                reason="user appears to be gaming",
            )

        if screen.activity_kind == "video":
            return BehaviorDecision(
                behavior="watch_screen",
                emotion="curious",
                reason="video content appears active",
            )

        # Add a little life so the pet is not deterministic.
        roll = random.random()
        if roll < 0.55:
            behavior = "idle"
        elif roll < 0.82:
            behavior = "walk"
        else:
            behavior = "look_around"

        return BehaviorDecision(
            behavior=behavior,
            emotion=pet.mood,
            reason="no urgent need or strong desktop context",
        )
