from __future__ import annotations

from collections import deque
from time import monotonic
from typing import Callable

from screen_behavior.awareness.models import (
    ActivityType,
    ScreenContext,
    UserState,
)


WORK = {ActivityType.CODING, ActivityType.STUDYING}
LEISURE = {ActivityType.BROWSING, ActivityType.VIDEO, ActivityType.GAMING}


class UserStateTracker:
    """
    Fuses separate sensor facts (activity, typing, mouse, idle time, body
    presence) into one stable UserState.

    A new state must hold for `stable_seconds` before it's reported, so the
    behavior brain doesn't react to every tiny sensor change. Leaving or
    entering AWAY/IDLE is immediate: those are unambiguous.
    """

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        stable_seconds: float = 5.0,
        idle_after_seconds: float = 60.0,
        away_after_seconds: float = 300.0,
        recent_input_seconds: float = 15.0,
        thinking_seconds: float = 90.0,
        drift_window_seconds: float = 300.0,
        hopping_window_seconds: float = 120.0,
        hopping_switches: int = 3,
    ) -> None:
        self._clock = clock
        self._stable = stable_seconds
        self._idle_after = idle_after_seconds
        self._away_after = away_after_seconds
        self._recent_input = recent_input_seconds
        self._thinking = thinking_seconds
        self._drift_window = drift_window_seconds
        self._hopping_window = hopping_window_seconds
        self._hopping_switches = hopping_switches

        self._state: UserState | None = None
        self._since: float = 0.0
        self._candidate: UserState | None = None
        self._candidate_since: float = 0.0
        self._switches: deque[float] = deque()

    def update(
        self,
        screen: ScreenContext,
        present: bool | None = None,
    ) -> tuple[UserState, float]:
        now = self._clock()

        if screen.activity_changed:
            self._switches.append(now)
        while self._switches and now - self._switches[0] > self._hopping_window:
            self._switches.popleft()

        candidate = self.classify(screen, present)

        if self._state is None:
            self._state, self._since = candidate, now
        elif candidate == self._state:
            self._candidate = None
        elif self._immediate(self._state, candidate):
            self._state, self._since = candidate, now
            self._candidate = None
        else:
            if self._candidate != candidate:
                self._candidate, self._candidate_since = candidate, now
            if now - self._candidate_since >= self._stable:
                self._state, self._since = candidate, now
                self._candidate = None

        return self._state, max(0.0, now - self._since)

    def classify(
        self,
        screen: ScreenContext,
        present: bool | None = None,
    ) -> UserState:
        """The instantaneous state, before stability is applied."""
        idle = screen.idle_seconds

        if present is False or idle >= self._away_after:
            return UserState.AWAY
        if idle >= self._idle_after or screen.activity == ActivityType.IDLE:
            return UserState.IDLE

        if len(self._switches) >= self._hopping_switches:
            return UserState.DISTRACTED

        activity = screen.activity
        recent_input = idle < self._recent_input

        if activity in WORK:
            keyboard = screen.keyboard
            if keyboard and keyboard.monitoring_available:
                since_key = keyboard.seconds_since_last_keypress
                typed_recently = (
                    since_key is not None and since_key <= self._thinking
                )
            else:
                typed_recently = recent_input
            return UserState.FOCUSED if typed_recently else UserState.PASSIVE

        if (
            activity in LEISURE
            and screen.previous_activity in WORK
            and screen.activity_duration_seconds < self._drift_window
        ):
            return UserState.DISTRACTED

        if activity == ActivityType.VIDEO:
            return UserState.PASSIVE

        return UserState.ACTIVE if recent_input else UserState.PASSIVE

    @staticmethod
    def _immediate(current: UserState, candidate: UserState) -> bool:
        resting = {UserState.IDLE, UserState.AWAY}
        return candidate == UserState.AWAY or current in resting
