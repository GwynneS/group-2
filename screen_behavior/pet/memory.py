from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field

from screen_behavior.pet.enums import Behavior


@dataclass(slots=True)
class MemorySnapshot:
    last_behavior: Behavior | None
    last_5_behaviors: list[Behavior]
    time_since_attention_request: float | None
    recently_ignored: bool
    recently_interacted_with: bool
    recent_distracting_count: int = 0
    repetitions: dict[Behavior, int] = field(default_factory=dict)


class BehaviorMemory:
    """
    Short-term behavioral memory (not AI memory): what buddy did recently
    and whether the user responded. All history is bounded.

    - History: the last `history_size` behavior starts, with times.
    - Last start per behavior: used for cooldowns and recency penalties.
    - Ignored: buddy asked for attention and the user didn't interact within
      `ignore_window_seconds`. Buddy then sulks instead of asking again.
    """

    def __init__(
        self,
        history_size: int = 12,
        ignore_window_seconds: float = 30.0,
        ignored_memory_seconds: float = 300.0,
        interaction_memory_seconds: float = 120.0,
    ) -> None:
        self._ignore_window = ignore_window_seconds
        self._ignored_memory = ignored_memory_seconds
        self._interaction_memory = interaction_memory_seconds

        # (behavior, start time, distracting)
        self._history: deque[tuple[Behavior, float, bool]] = deque(
            maxlen=history_size
        )
        self._last_started: dict[Behavior, float] = {}
        self._last_attention_request: float | None = None
        self._last_interaction: float | None = None

    # --- recording --------------------------------------------------------

    def record_behavior(
        self,
        behavior: Behavior,
        now: float,
        distracting: bool = False,
    ) -> None:
        self._history.append((behavior, now, distracting))
        self._last_started[behavior] = now
        if behavior == Behavior.ASK_FOR_ATTENTION:
            self._last_attention_request = now

    def record_interaction(self, now: float) -> None:
        self._last_interaction = now

    # --- queries ----------------------------------------------------------

    @property
    def history(self) -> list[Behavior]:
        return [b for b, _, _ in self._history]

    def last_behavior(self) -> Behavior | None:
        return self._history[-1][0] if self._history else None

    def last_started(self, behavior: Behavior) -> float | None:
        return self._last_started.get(behavior)

    def seconds_since_started(
        self,
        behavior: Behavior,
        now: float,
    ) -> float | None:
        started = self._last_started.get(behavior)
        return None if started is None else max(0.0, now - started)

    def repetitions(self, behavior: Behavior) -> int:
        """How many times `behavior` appears in the bounded history."""
        return sum(1 for b, _, _ in self._history if b == behavior)

    def recent_distracting_count(self, now: float, window: float) -> int:
        return sum(
            1 for _, t, distracting in self._history
            if distracting and now - t <= window
        )

    def seconds_since_attention_request(self, now: float) -> float | None:
        if self._last_attention_request is None:
            return None
        return max(0.0, now - self._last_attention_request)

    def is_repetitive(self, behavior: Behavior) -> bool:
        """Last behavior, or done 2+ times in the last 5."""
        recent = self.history[-5:]
        if not recent:
            return False
        if recent[-1] == behavior:
            return True
        return Counter(recent)[behavior] >= 2

    def recently_interacted_with(self, now: float) -> bool:
        return (
            self._last_interaction is not None
            and now - self._last_interaction <= self._interaction_memory
        )

    def recently_ignored(self, now: float) -> bool:
        asked = self._last_attention_request
        if asked is None:
            return False

        since_ask = now - asked
        if since_ask < self._ignore_window:
            return False  # still waiting for the user to respond
        if since_ask > self._ignore_window + self._ignored_memory:
            return False  # buddy has gotten over it

        answered = (
            self._last_interaction is not None
            and self._last_interaction >= asked
        )
        return not answered

    def snapshot(
        self,
        now: float,
        distracting_window: float = 600.0,
    ) -> MemorySnapshot:
        history = self.history
        return MemorySnapshot(
            last_behavior=history[-1] if history else None,
            last_5_behaviors=history[-5:],
            time_since_attention_request=self.seconds_since_attention_request(now),
            recently_ignored=self.recently_ignored(now),
            recently_interacted_with=self.recently_interacted_with(now),
            recent_distracting_count=self.recent_distracting_count(
                now, distracting_window,
            ),
            repetitions=dict(Counter(history)),
        )
