from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable

from screen_behavior.awareness.microphone import (
    MicrophoneActivity,
    MicrophoneMonitor,
)
from screen_behavior.awareness.models import ScreenContext
from screen_behavior.awareness.mouse import MouseActivity
from screen_behavior.awareness.service import AwarenessService
from screen_behavior.pet.behavior import (
    BehaviorDecision,
    BehaviorEngine,
    ExternalSignals,
)
from screen_behavior.pet.feeding import FeedingSystem, FeedResult
from screen_behavior.pet.memory import MemorySnapshot
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
    microphone: MicrophoneActivity
    memory: MemorySnapshot


class CompanionBrain:
    """
    Stable integration boundary for the rest of the project.
    """

    def __init__(
        self,
        awareness: AwarenessService | None = None,
        needs: NeedsSystem | None = None,
        behavior: BehaviorEngine | None = None,
        feeding: FeedingSystem | None = None,
        microphone: MicrophoneMonitor | None = None,
        enable_microphone: bool = False,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.awareness = awareness or AwarenessService()
        self.needs = needs or NeedsSystem()
        self.behavior = behavior or BehaviorEngine()
        self.feeding = feeding or FeedingSystem()

        # Microphone is opt-in: pass enable_microphone=True or a monitor.
        self.microphone = microphone
        if self.microphone is None and enable_microphone:
            self.microphone = MicrophoneMonitor()
            self.microphone.start()
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
        microphone = (
            self.microphone.snapshot() if self.microphone is not None
            else MicrophoneActivity(monitoring_available=False)
        )

        if microphone.loud_voice_detected:
            signals = ExternalSignals(loud_voice_detected=True)

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
            microphone=microphone,
            memory=self.behavior.memory_snapshot(),
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
        self.behavior.record_interaction()
        self.needs.update_mood(self.pet)

    def feed(self) -> FeedResult:
        """
        Give buddy a fish. Called by whichever group owns the feeding UI.
        Returns whether buddy ate, so the UI/voice can react to a refusal.
        """
        result = self.feeding.feed(self.pet)
        self.behavior.record_interaction()
        self.needs.update_mood(self.pet)
        return result

    def mouse(self) -> MouseActivity:
        """
        Latest cursor motion, refreshed ~30x/second in the background.
        Cheap to call every animation frame, unlike update().
        """
        monitor = getattr(self.awareness, "mouse_monitor", None)
        if monitor is None:
            return MouseActivity(monitoring_available=False)
        return monitor.snapshot()

    def add_mouse_listener(self, listener) -> None:
        """Call listener(x, y) every time the cursor moves."""
        monitor = getattr(self.awareness, "mouse_monitor", None)
        if monitor is not None:
            monitor.add_listener(listener)

    def close(self) -> None:
        close = getattr(self.awareness, "close", None)
        if callable(close):
            close()
        if self.microphone is not None:
            self.microphone.stop()
