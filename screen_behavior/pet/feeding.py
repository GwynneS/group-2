from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from screen_behavior.awareness.models import ScreenContext
from screen_behavior.pet.models import PetState


class FoodType(StrEnum):
    DRY = "dry"
    WET = "wet"


@dataclass(frozen=True, slots=True)
class FoodEffect:
    hunger_delta: float
    energy_delta: float
    affection_delta: float
    attention_delta: float
    hyper_seconds: float


@dataclass(frozen=True, slots=True)
class FeedingConfig:
    # Hunger convention matches PetState: 0 = full, 100 = starving.
    # Buddy refuses food at or below this hunger level.
    full_hunger_threshold: float = 10.0

    # Productive (coding/studying) seconds needed to earn one wet food.
    productive_seconds_per_wet_food: float = 25 * 60
    max_wet_food: int = 3

    dry: FoodEffect = FoodEffect(
        hunger_delta=-25.0,
        energy_delta=5.0,
        affection_delta=1.0,
        attention_delta=3.0,
        hyper_seconds=0.0,
    )
    wet: FoodEffect = FoodEffect(
        hunger_delta=-45.0,
        energy_delta=15.0,
        affection_delta=12.0,
        attention_delta=10.0,
        hyper_seconds=45.0,
    )


@dataclass(slots=True)
class FeedResult:
    food: FoodType
    accepted: bool
    reason: str


@dataclass(slots=True)
class FeedingStatus:
    """Read-only snapshot for other groups (UI shows food count, etc.)."""
    wet_food_available: int
    productive_seconds_toward_next_wet_food: float
    productive_seconds_per_wet_food: float
    hyper_seconds_remaining: float


class FeedingSystem:
    """
    Food rules only: what dry/wet food does to Tamagotchi state and how wet
    food is earned. Another group decides *when* the user feeds buddy
    (button, drag-and-drop, etc.) and calls CompanionBrain.feed().
    """

    def __init__(self, config: FeedingConfig | None = None) -> None:
        self.config = config or FeedingConfig()
        self.wet_food_available: int = 0
        self._productive_seconds: float = 0.0

    def tick(
        self,
        state: PetState,
        screen: ScreenContext,
        dt_seconds: float,
    ) -> None:
        dt = max(0.0, dt_seconds)
        c = self.config

        state.hyper_seconds_remaining = max(
            0.0,
            state.hyper_seconds_remaining - dt,
        )

        if not screen.user_is_working:
            return

        if self.wet_food_available >= c.max_wet_food:
            # Stash is full; don't bank progress toward more.
            self._productive_seconds = 0.0
            return

        self._productive_seconds += dt

        while (
            self._productive_seconds >= c.productive_seconds_per_wet_food
            and self.wet_food_available < c.max_wet_food
        ):
            self._productive_seconds -= c.productive_seconds_per_wet_food
            self.wet_food_available += 1

        if self.wet_food_available >= c.max_wet_food:
            self._productive_seconds = 0.0

    def feed(self, state: PetState, food: FoodType) -> FeedResult:
        c = self.config

        if state.hunger <= c.full_hunger_threshold:
            return FeedResult(food, False, "buddy is full and won't eat")

        if food == FoodType.WET:
            if self.wet_food_available <= 0:
                return FeedResult(
                    food,
                    False,
                    "no wet food earned yet; keep being productive",
                )
            self.wet_food_available -= 1
            effect = c.wet
        else:
            effect = c.dry

        state.hunger += effect.hunger_delta
        state.energy += effect.energy_delta
        state.affection += effect.affection_delta
        state.attention += effect.attention_delta
        state.hyper_seconds_remaining = max(
            state.hyper_seconds_remaining,
            effect.hyper_seconds,
        )
        state.clamp_all()

        return FeedResult(food, True, f"buddy ate {food.value} food")

    def status(self, state: PetState) -> FeedingStatus:
        return FeedingStatus(
            wet_food_available=self.wet_food_available,
            productive_seconds_toward_next_wet_food=self._productive_seconds,
            productive_seconds_per_wet_food=(
                self.config.productive_seconds_per_wet_food
            ),
            hyper_seconds_remaining=state.hyper_seconds_remaining,
        )
