from __future__ import annotations

import math
from time import monotonic
from typing import Callable

from screen_behavior.awareness.models import (
    ActivityClassification,
    ActivityType,
)


class EvidenceAccumulator:
    """
    Evidence decay + temporal context for activity scores.

    Each activity's score is an exponential moving average of the raw
    classifier scores, weighted by real elapsed time. With the default
    20-second time constant, the last ~60 seconds make up ~95% of the
    evidence, so a 5-second Alt-Tab from VS Code to Chrome barely moves
    the result, while a minute of browsing clearly wins.

    Exception: coming back from idle is unambiguous (the user touched the
    mouse/keyboard), so idle evidence is dropped immediately instead of
    fading out.
    """

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        time_constant_seconds: float = 20.0,
        idle_reset_below: float = 0.3,
    ) -> None:
        self._clock = clock
        self._tau = time_constant_seconds
        self._idle_reset_below = idle_reset_below
        self._scores: dict[ActivityType, float] | None = None
        self._last_update: float | None = None

    def update(
        self,
        raw: ActivityClassification,
    ) -> ActivityClassification:
        now = self._clock()

        if self._scores is None or self._last_update is None:
            self._scores = dict(raw.scores)
        else:
            dt = max(0.0, now - self._last_update)
            keep = math.exp(-dt / self._tau) if self._tau > 0 else 0.0

            for activity in set(self._scores) | set(raw.scores):
                old = self._scores.get(activity, 0.0)
                new = raw.scores.get(activity, 0.0)
                self._scores[activity] = keep * old + (1 - keep) * new

            if raw.scores.get(ActivityType.IDLE, 0.0) < self._idle_reset_below:
                self._scores[ActivityType.IDLE] = min(
                    self._scores.get(ActivityType.IDLE, 0.0),
                    raw.scores.get(ActivityType.IDLE, 0.0),
                )

        self._last_update = now

        leader = max(self._scores, key=lambda a: self._scores[a])
        return ActivityClassification(
            activity=leader,
            confidence=self._scores[leader],
            scores=dict(self._scores),
            reason=raw.reason,
        )
