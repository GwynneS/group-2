from __future__ import annotations

from time import monotonic
from typing import Callable

from screen_behavior.awareness.models import (
    ActivityClassification,
    ActivityTiming,
    ActivityType,
)


class ActivityStabilityTracker:
    """
    Converts raw candidate scores into a stable public activity.

    Why this exists:
    the strongest candidate can fluctuate by a tiny amount between polls.
    We do not want:
        coding -> browsing -> coding -> browsing
    every second.

    The current activity stays active unless a challenger:
      1. beats the current activity by `switch_margin`, and
      2. stays stronger for `switch_delay_seconds`.

    Very strong/obvious transitions can switch immediately.
    """

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        switch_margin: float = 0.08,
        switch_delay_seconds: float = 1.5,
        immediate_switch_confidence: float = 0.95,
        weak_current_threshold: float = 0.25,
    ) -> None:
        self._clock = clock
        self._switch_margin = switch_margin
        self._switch_delay = switch_delay_seconds
        self._immediate_confidence = immediate_switch_confidence
        self._weak_current_threshold = weak_current_threshold

        self._current: ActivityType | None = None
        self._previous: ActivityType | None = None
        self._started_at: float | None = None

        self._pending: ActivityType | None = None
        self._pending_since: float | None = None

    def update(
        self,
        classification: ActivityClassification,
    ) -> ActivityTiming:
        now = self._clock()
        scores = classification.scores
        leader = classification.activity

        if self._current is None:
            self._current = leader
            self._started_at = now
            return self._timing(
                now,
                activity_changed=False,
                confidence=scores.get(leader, classification.confidence),
            )

        current_score = scores.get(self._current, 0.0)
        leader_score = scores.get(leader, classification.confidence)

        if leader == self._current:
            self._clear_pending()
            return self._timing(
                now,
                activity_changed=False,
                confidence=current_score,
            )

        clearly_stronger = (
            leader_score >= current_score + self._switch_margin
        )
        immediate = (
            leader_score >= self._immediate_confidence
            and current_score <= self._weak_current_threshold
        )

        if not clearly_stronger:
            self._clear_pending()
            return self._timing(
                now,
                activity_changed=False,
                confidence=current_score,
            )

        if immediate:
            return self._switch(
                leader,
                leader_score,
                now,
            )

        if self._pending != leader:
            self._pending = leader
            self._pending_since = now
            return self._timing(
                now,
                activity_changed=False,
                confidence=current_score,
            )

        pending_since = (
            self._pending_since
            if self._pending_since is not None
            else now
        )
        pending_seconds = max(0.0, now - pending_since)

        if pending_seconds >= self._switch_delay:
            return self._switch(
                leader,
                leader_score,
                now,
            )

        return self._timing(
            now,
            activity_changed=False,
            confidence=current_score,
        )

    def _switch(
        self,
        activity: ActivityType,
        confidence: float,
        now: float,
    ) -> ActivityTiming:
        self._previous = self._current
        self._current = activity
        self._started_at = now
        self._clear_pending()

        return self._timing(
            now,
            activity_changed=True,
            confidence=confidence,
        )

    def _timing(
        self,
        now: float,
        activity_changed: bool,
        confidence: float,
    ) -> ActivityTiming:
        started = (
            self._started_at
            if self._started_at is not None
            else now
        )
        pending_since = (
            self._pending_since
            if self._pending_since is not None
            else now
        )

        return ActivityTiming(
            activity=self._current or ActivityType.OTHER,
            previous_activity=self._previous,
            activity_changed=activity_changed,
            duration_seconds=max(0.0, now - started),
            confidence=max(0.0, min(1.0, confidence)),
            pending_activity=self._pending,
            pending_seconds=(
                max(0.0, now - pending_since)
                if self._pending is not None
                else 0.0
            ),
        )

    def _clear_pending(self) -> None:
        self._pending = None
        self._pending_since = None


# Backward-compatible alias for code that imported the older V0.4 name.
ActivityDurationTracker = ActivityStabilityTracker
