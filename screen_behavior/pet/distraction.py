from __future__ import annotations

from dataclasses import dataclass, field

from screen_behavior.awareness.models import ScreenContext
from screen_behavior.pet.enums import Behavior


def _default_costs() -> dict[Behavior, float]:
    return {
        Behavior.DANCE: 35.0,
        Behavior.PLAY_DEAD: 30.0,
        Behavior.WALK_AROUND_CORNER: 25.0,
        Behavior.ASK_FOR_ATTENTION: 20.0,
        Behavior.SEND_KISS: 10.0,
        Behavior.WAVE: 8.0,
    }


@dataclass(frozen=True, slots=True)
class DistractionConfig:
    max_budget: float = 100.0

    # Budget regained per second, by what the user is doing.
    regen_focused: float = 0.05   # coding/studying: ~30 min to refill
    regen_normal: float = 0.3     # browsing, video, gaming, other
    regen_idle: float = 2.0       # user away: pet is free to act

    # Quiet behaviors (watch screen, study with user, sit, look around,
    # follow mouse, sleep, stretch, idle) cost nothing.
    costs: dict[Behavior, float] = field(default_factory=_default_costs)


class DistractionBudget:
    """
    Limits how often buddy does attention-grabbing things.

    Each distracting behavior spends budget; the budget refills slowly while
    the user is focused and quickly while they're idle, so buddy gives
    working users room without ever going completely quiet.
    """

    def __init__(self, config: DistractionConfig | None = None) -> None:
        self.config = config or DistractionConfig()
        self.value = self.config.max_budget

    def tick(self, screen: ScreenContext, dt_seconds: float) -> None:
        c = self.config
        if screen.user_is_idle:
            rate = c.regen_idle
        elif screen.user_is_working:
            rate = c.regen_focused
        else:
            rate = c.regen_normal

        self.value = min(
            c.max_budget,
            self.value + rate * max(0.0, dt_seconds),
        )

    def cost(self, behavior: Behavior) -> float:
        return self.config.costs.get(behavior, 0.0)

    def can_afford(self, behavior: Behavior) -> bool:
        return self.value >= self.cost(behavior)

    def spend(self, behavior: Behavior) -> None:
        # Urgent behaviors may be forced through; budget floors at zero.
        self.value = max(0.0, self.value - self.cost(behavior))
