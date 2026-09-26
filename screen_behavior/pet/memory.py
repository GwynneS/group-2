from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

from screen_behavior.pet.enums import Behavior


@dataclass(slots=True)
class MemorySnapshot:
    last_behavior: Behavior | None
    last_5_behaviors: list[Behavior]
    time_since_attention_request: float | None
    recently_ignored: bool
    recently_interacted_with: bool


class BehaviorMemory:
    """
    Short-term behavioral memory (not AI memory): what buddy did recently
    and whether the user responded.

    - Repetition: the last behavior, and anything done 2+ times in the last
      5, are avoided when other options exist.
    - Ignored: buddy asked for attention and the user didn't interact within
      `ignore_window_seconds`. Buddy then sulks instead of asking again.
    """

    def __init__(
        self,
        ignore_window_seconds: float = 30.0,
        ignored_memory_seconds: float = 300.0,
        interaction_memory_seconds: float = 120.0,
    ) -> None:
        self._ignore_window = ignore_window_seconds
        self._ignored_memory = ignored_memory_seconds
        self._interaction_memory = interaction_memory_seconds

        self._recent: deque[Behavior] = deque(maxlen=5)
        self._last_attention_request: float | None = None
        self._last_interaction: float | None = None

    def record_behavior(self, behavior: Behavior, now: float) -> None:
        self._recent.append(behavior)
        if behavior == Behavior.ASK_FOR_ATTENTION:
            self._last_attention_request = now

    def record_interaction(self, now: float) -> None:
        self._last_interaction = now

    def is_repetitive(self, behavior: Behavior) -> bool:
        if not self._recent:
            return False
        if self._recent[-1] == behavior:
            return True
        return Counter(self._recent)[behavior] >= 2

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

    def snapshot(self, now: float) -> MemorySnapshot:
        return MemorySnapshot(
            last_behavior=self._recent[-1] if self._recent else None,
            last_5_behaviors=list(self._recent),
            time_since_attention_request=(
                None if self._last_attention_request is None
                else max(0.0, now - self._last_attention_request)
            ),
            recently_ignored=self.recently_ignored(now),
            recently_interacted_with=self.recently_interacted_with(now),
        )
