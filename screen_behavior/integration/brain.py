from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable

from screen_behavior.awareness.models import ScreenContext
from screen_behavior.awareness.service import AwarenessService
from screen_behavior.pet.behavior import (
    BehaviorDecision,
    BehaviorEngine,
    ExternalSignals,
)
from screen_behavior.pet.interactions import (
    InteractionEffect,
    apply_interaction_effect,
)
from screen_behavior.pet.models import PetState
from screen_behavior.pet.needs import NeedsSystem


@dataclass(slots=True)
class BrainUpdate:
    screen: ScreenContext
    pet: PetState
    decision: BehaviorDecision


class CompanionBrain:
    """
    Stable integration boundary for the rest of the project.
    """

    def __init__(
        self,
        awareness: AwarenessService | None = None,
        needs: NeedsSystem | None = None,
        behavior: BehaviorEngine | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.awareness = awareness or AwarenessService()
        self.needs = needs or NeedsSystem()
        self.behavior = behavior or BehaviorEngine()
        self.pet = PetState()

        self._clock = clock
        self._last_tick = clock()

    def update(
        self,
        signals: ExternalSignals | None = None,
    ) -> BrainUpdate:
        now = self._clock()
        dt = max(0.0, now - self._last_tick)
        self._last_tick = now

        screen = self.awareness.snapshot()

        self.needs.tick(
            self.pet,
            dt,
        )

        decision = self.behavior.decide(
            self.pet,
            screen,
            signals,
        )

        # Behavior start may spend energy, so update mood once more.
        self.needs.update_mood(self.pet)

        return BrainUpdate(
            screen=screen,
            pet=self.pet,
            decision=decision,
        )

    def apply_interaction(
        self,
        effect: InteractionEffect,
    ) -> None:
        """
        Generic Person-6 integration hook.

        Person 6 defines the content/interaction. We only apply the resulting
        numeric effect to Tamagotchi state.
        """
        apply_interaction_effect(
            self.pet,
            effect,
        )
        self.needs.update_mood(self.pet)

    def close(self) -> None:
        close = getattr(self.awareness, "close", None)
        if callable(close):
            close()
