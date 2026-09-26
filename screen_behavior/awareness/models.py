from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from screen_behavior.awareness.mouse import MouseActivity


class ActivityType(StrEnum):
    CODING = "coding"
    BROWSING = "browsing"
    GAMING = "gaming"
    STUDYING = "studying"
    VIDEO = "video"
    IDLE = "idle"
    OTHER = "other"


class UserState(StrEnum):
    """High-level, stable summary of what the user is doing."""
    FOCUSED = "focused"          # working (coding/studying) with recent input
    ACTIVE = "active"            # engaged but not working (browsing, gaming)
    PASSIVE = "passive"          # watching/reading, little input
    DISTRACTED = "distracted"    # app-hopping, or just drifted off work
    IDLE = "idle"                # no input for a minute or more
    AWAY = "away"                # long idle, or body tracking says not present


class Shortcut(StrEnum):
    """The only key combinations the keyboard monitor recognizes."""
    COPY = "copy"
    PASTE = "paste"
    UNDO = "undo"


@dataclass(slots=True)
class ScreenBounds:
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(slots=True)
class WindowInfo:
    title: str = ""
    app_name: str = ""
    process_name: str = ""
    pid: int | None = None
    bundle_id: str = ""
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def has_geometry(self) -> bool:
        return self.width > 0 and self.height > 0


@dataclass(slots=True)
class RawScreenSnapshot:
    cursor_x: int = 0
    cursor_y: int = 0
    idle_seconds: float = 0.0
    foreground: WindowInfo | None = None
    screen_bounds: ScreenBounds | None = None


@dataclass(slots=True)
class KeyboardActivity:
    monitoring_available: bool = False
    typing_active: bool = False
    keypresses_last_5_seconds: int = 0
    keypresses_last_30_seconds: int = 0
    typing_rate_per_minute: float = 0.0
    current_typing_burst_seconds: float = 0.0
    seconds_since_last_keypress: float | None = None
    current_no_typing_duration: float | None = None

    # Copy/paste/undo only. Counts only go up, so a consumer can compare
    # with the previous update to see exactly how many new ones happened.
    last_shortcut: Shortcut | None = None
    seconds_since_last_shortcut: float | None = None
    shortcut_counts: dict[Shortcut, int] = field(default_factory=dict)


@dataclass(slots=True)
class WindowEdgeAwareness:
    available: bool = False
    cursor_inside_foreground_window: bool = False
    cursor_near_window_edge: bool = False
    nearest_edge: str | None = None
    distance_to_nearest_edge_px: float | None = None


@dataclass(slots=True)
class ActivityClassification:
    """
    Candidate evidence for every activity.

    `scores` are evidence strengths in [0, 1], not calibrated probabilities.
    The highest-scoring candidate is `activity`, but the stability tracker may
    briefly keep the previous public activity to avoid flickering.
    """
    activity: ActivityType
    confidence: float
    scores: dict[ActivityType, float] = field(default_factory=dict)
    reason: str = ""


@dataclass(slots=True)
class ActivityTiming:
    activity: ActivityType
    previous_activity: ActivityType | None
    activity_changed: bool
    duration_seconds: float
    confidence: float
    pending_activity: ActivityType | None = None
    pending_seconds: float = 0.0


@dataclass(slots=True)
class ScreenContext:
    cursor_x: int = 0
    cursor_y: int = 0
    idle_seconds: float = 0.0

    activity: ActivityType = ActivityType.OTHER
    activity_confidence: float = 0.0
    activity_scores: dict[ActivityType, float] = field(default_factory=dict)
    activity_duration_seconds: float = 0.0
    previous_activity: ActivityType | None = None
    activity_changed: bool = False

    # Highest raw candidate before stability/hysteresis is applied.
    leading_activity: ActivityType | None = None
    leading_activity_confidence: float = 0.0
    pending_activity: ActivityType | None = None
    pending_activity_seconds: float = 0.0

    foreground: WindowInfo | None = None
    screen_bounds: ScreenBounds | None = None
    window_edge: WindowEdgeAwareness | None = None
    keyboard: KeyboardActivity | None = None
    mouse: MouseActivity | None = None

    # Fused state from activity + keyboard + mouse + idle (+ presence).
    # None when built by hand (tests/demos); properties fall back to activity.
    user_state: UserState | None = None
    user_state_seconds: float = 0.0
    user_present: bool | None = None

    @property
    def user_is_working(self) -> bool:
        work = self.activity in {ActivityType.CODING, ActivityType.STUDYING}
        if self.user_state is None:
            return work
        return work and self.user_state in {
            UserState.FOCUSED,
            UserState.PASSIVE,
        }

    @property
    def user_is_idle(self) -> bool:
        if self.user_state is None:
            return self.activity == ActivityType.IDLE
        return self.user_state in {UserState.IDLE, UserState.AWAY}
