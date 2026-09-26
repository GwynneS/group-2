from __future__ import annotations

from dataclasses import dataclass

from screen_behavior.awareness.models import (
    ActivityType,
    ScreenContext,
    UserState,
)
from screen_behavior.pet.enums import BaseMood, Behavior


@dataclass(slots=True)
class ScoringContext:
    """Everything the scorer looks at, gathered once per decision."""
    energy: float        # 0..1
    boredom: float       # 0..1
    loneliness: float    # 0..1 (1 - attention)
    affection: float     # 0..1
    mood: BaseMood
    working: bool
    idle: bool
    typing: bool
    mouse_moving: bool
    media: bool          # gaming or video on screen
    user_state: UserState | None
    activity_minutes: float
    budget_fraction: float
    recently_ignored: bool
    whim: float          # 0..1 random roll for rare behaviors


@dataclass(slots=True)
class ScoredBehavior:
    behavior: Behavior
    score: float
    reason: str


ENERGETIC = {Behavior.DANCE, Behavior.WAVE, Behavior.WALK_AROUND_CORNER}


def build_context(
    pet,
    screen: ScreenContext,
    budget_fraction: float,
    recently_ignored: bool,
    whim: float,
) -> ScoringContext:
    keyboard = screen.keyboard
    mouse = screen.mouse
    return ScoringContext(
        energy=pet.energy / 100,
        boredom=pet.boredom / 100,
        loneliness=1 - pet.attention / 100,
        affection=pet.affection / 100,
        mood=pet.mood,
        working=screen.user_is_working,
        idle=screen.user_is_idle,
        typing=bool(keyboard and keyboard.typing_active),
        mouse_moving=bool(mouse and mouse.moving),
        media=screen.activity in {ActivityType.GAMING, ActivityType.VIDEO},
        user_state=screen.user_state,
        activity_minutes=screen.activity_duration_seconds / 60,
        budget_fraction=budget_fraction,
        recently_ignored=recently_ignored,
        whim=whim,
    )


def base_score(behavior: Behavior, c: ScoringContext) -> tuple[float, str]:
    """Raw desire for a behavior before cross-cutting modifiers."""
    B = Behavior

    if behavior == B.IDLE:
        return 0.30, "nothing better to do"
    if behavior == B.LOOK_AROUND:
        return 0.40, "curious about surroundings"
    if behavior == B.SIT_DOWN:
        return 0.30 + 0.35 * (1 - c.energy), "resting"
    if behavior == B.STRETCH:
        long_session = c.working and c.activity_minutes >= 20
        return (
            0.30 + (0.15 if long_session else 0.0),
            "stretching during a long session" if long_session else "stretching",
        )
    if behavior == B.FOLLOW_MOUSE_WITH_EYES:
        return (
            0.30 + (0.30 if c.mouse_moving else 0.0),
            "watching the moving cursor" if c.mouse_moving else "watching the cursor",
        )
    if behavior == B.STUDY_WITH_USER:
        score = 0.10
        if c.working:
            score += 0.50
            if c.typing:
                score += 0.15
        return score, "keeping the user company while they work"
    if behavior == B.WATCH_SCREEN:
        score = 0.05 + (0.65 if c.media else 0.0)
        if c.user_state == UserState.PASSIVE:
            score += 0.10
        return score, "watching what's on screen"
    if behavior == B.WAVE:
        return (
            0.25 + 0.20 * c.boredom + (0.15 if c.idle else 0.0),
            "saying hi",
        )
    if behavior == B.DANCE:
        return (
            0.15 + 0.30 * c.energy + 0.25 * c.boredom,
            "full of energy",
        )
    if behavior == B.WALK_AROUND_CORNER:
        return (
            0.15 + 0.30 * c.boredom + 0.10 * c.energy,
            "bored; exploring",
        )
    if behavior == B.SEND_KISS:
        loving = c.energy >= 0.95 and c.affection >= 0.70
        return (
            0.05 + (0.60 if loving else 0.0),
            "energy and affection are both very high",
        )
    if behavior == B.PLAY_DEAD:
        # Rare: only a small random whim makes this competitive.
        return (
            0.02 + (0.80 if c.whim < 0.02 else 0.0),
            "rare autonomous play-dead behavior",
        )
    if behavior == B.ASK_FOR_ATTENTION:
        score = 0.05 + 0.60 * c.loneliness
        if c.typing or c.user_state == UserState.FOCUSED:
            score -= 0.30  # don't nag a busy user
        if c.recently_ignored:
            score -= 0.40
        return score, "lonely; wants attention"
    if behavior == B.SLEEP:
        score = max(0.0, (0.40 - c.energy) * 2)
        if c.idle:
            score += 0.20
        return score, "sleepy"

    return 0.0, "unscored"


def score_behavior(
    behavior: Behavior,
    c: ScoringContext,
    distracting: bool,
    repetitive: bool,
) -> ScoredBehavior:
    score, reason = base_score(behavior, c)

    if distracting:
        if c.working:
            score *= 0.35
        elif c.idle:
            score *= 1.2
        # A low budget makes distracting behaviors less attractive even
        # before they become unaffordable.
        score *= 0.5 + 0.5 * c.budget_fraction

    if c.mood == BaseMood.TIRED:
        if distracting or behavior in ENERGETIC:
            score *= 0.5
        if behavior in {Behavior.SLEEP, Behavior.SIT_DOWN}:
            score += 0.20
    elif c.mood == BaseMood.LONELY and behavior == Behavior.ASK_FOR_ATTENTION:
        score += 0.15
    elif c.mood in {BaseMood.HAPPY, BaseMood.EXCITED} and behavior in ENERGETIC:
        score += 0.10

    if repetitive:
        score *= 0.4
        reason += " (penalized: done recently)"

    return ScoredBehavior(behavior, max(0.0, score), reason)
