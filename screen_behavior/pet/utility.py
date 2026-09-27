"""
Utility scoring for autonomous behaviors.

Every eligible behavior gets a score (points, not a probability) built from
small labeled components, so each decision can be explained:

    study_with_user = 84.0
        base +8, context +38, focus +32, variation +1, recency +5 ...

All weights live in utility_config.py.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

from screen_behavior.awareness.models import (
    ActivityType,
    ScreenContext,
    UserState,
)
from screen_behavior.pet.config import BehaviorSpec
from screen_behavior.pet.enums import BaseMood, Behavior, SpecialMood
from screen_behavior.pet.memory import BehaviorMemory
from screen_behavior.pet.utility_config import (
    BehaviorProfile,
    BehaviorUtilityConfig,
)


@dataclass(slots=True)
class ScoringContext:
    """Everything the scorer looks at, gathered once per decision."""
    now: float
    energy: float          # 0..1
    boredom: float         # 0..1
    loneliness: float      # 0..1  (1 - attention)
    affection: float       # 0..1
    hunger: float          # 0..1
    mood: BaseMood
    special_mood: SpecialMood | None
    activity: ActivityType
    activity_confidence: float
    focus: float           # 0..1 how engaged the user is in work
    idle: float            # 0..1 how idle/away the user is
    mouse_moving: bool
    hyper: bool
    budget_fraction: float # 0..1

    @property
    def tiredness(self) -> float:
        return 1.0 - self.energy


@dataclass(slots=True)
class ScoreBreakdown:
    components: dict[str, float] = field(default_factory=dict)

    def add(self, label: str, points: float) -> None:
        if points:
            self.components[label] = self.components.get(label, 0.0) + points

    @property
    def total(self) -> float:
        return max(0.0, sum(self.components.values()))

    def rounded(self) -> dict[str, float]:
        return {k: round(v, 1) for k, v in self.components.items()}


@dataclass(slots=True)
class BehaviorScore:
    behavior: Behavior
    score: float
    breakdown: ScoreBreakdown
    reason: str


# A future learned-personalization layer can plug in here. Its output is
# clamped to +/- max_preference_bonus, so it can nudge but never override.
PreferenceBonus = Callable[[Behavior, ScoringContext], float]


# --- context helpers ---------------------------------------------------------

def focus_strength(screen: ScreenContext) -> float:
    """0 = not working, 1 = deeply engaged in coding/studying."""
    if not screen.user_is_working:
        return 0.0

    focus = 0.55
    keyboard = screen.keyboard
    if keyboard and keyboard.monitoring_available:
        if keyboard.typing_active:
            focus += 0.20
        elif (
            keyboard.seconds_since_last_keypress is not None
            and keyboard.seconds_since_last_keypress <= 60
        ):
            focus += 0.10
    if screen.activity_confidence >= 0.8:
        focus += 0.10
    if screen.activity_duration_seconds >= 600:
        focus += 0.10
    if screen.activity_duration_seconds >= 1800:
        focus += 0.05

    if screen.user_state == UserState.FOCUSED:
        focus = max(focus, 0.75)
    elif screen.user_state == UserState.PASSIVE:
        focus = min(focus, 0.6)
    return max(0.0, min(1.0, focus))


def idle_strength(screen: ScreenContext) -> float:
    """0 = user active, up to 1 = user long gone."""
    if not screen.user_is_idle:
        return 0.0
    return 0.5 + 0.5 * min(1.0, screen.idle_seconds / 300)


def build_context(
    pet,
    screen: ScreenContext,
    budget_fraction: float,
    now: float,
) -> ScoringContext:
    mouse = screen.mouse
    return ScoringContext(
        now=now,
        energy=pet.energy / 100,
        boredom=pet.boredom / 100,
        loneliness=1 - pet.attention / 100,
        affection=pet.affection / 100,
        hunger=pet.hunger / 100,
        mood=pet.mood,
        special_mood=pet.special_mood,
        activity=screen.activity,
        activity_confidence=screen.activity_confidence,
        focus=focus_strength(screen),
        idle=idle_strength(screen),
        mouse_moving=bool(mouse and mouse.moving),
        hyper=getattr(pet, "is_hyper", False),
        budget_fraction=max(0.0, min(1.0, budget_fraction)),
    )


# --- score components --------------------------------------------------------
# Each adds labeled points to the breakdown. Keep them small and independent.

def _profile_points(p: BehaviorProfile, c: ScoringContext, b: ScoreBreakdown) -> None:
    b.add("base", p.base)

    if c.activity in p.activity:
        # Full credit when the classifier is sure; half when it's guessing.
        b.add("context", p.activity[c.activity] * (0.5 + 0.5 * c.activity_confidence))

    b.add("energy", p.energy * c.energy)
    b.add("tiredness", p.tiredness * c.tiredness)
    b.add("boredom", p.boredom * c.boredom)
    # Needs only pull once they're actually felt (curves, not straight lines).
    b.add("loneliness", p.loneliness * max(0.0, c.loneliness - 0.3) / 0.7)
    b.add("affection", p.affection * c.affection)
    b.add("hunger", p.hunger * max(0.0, c.hunger - 0.4) / 0.6)

    b.add("mood", p.mood.get(c.mood, 0.0))
    if c.special_mood is not None:
        b.add("special_mood", p.special_mood.get(c.special_mood, 0.0))

    b.add("focus", p.focus * c.focus)
    b.add("idle", p.idle * c.idle)
    if c.mouse_moving:
        b.add("mouse", p.mouse_moving)
    if c.hyper:
        b.add("hyper", p.hyper)


def _distraction_points(
    spec: BehaviorSpec,
    c: ScoringContext,
    memory: BehaviorMemory,
    cfg: BehaviorUtilityConfig,
    b: ScoreBreakdown,
) -> None:
    if not spec.distracting:
        return
    penalty = cfg.distracting_focus_penalty * c.focus
    penalty += cfg.low_budget_penalty * (1 - c.budget_fraction)
    penalty += cfg.recent_distracting_penalty * memory.recent_distracting_count(
        c.now, cfg.recent_distracting_window_seconds,
    )
    b.add("distraction", -penalty)


def _memory_points(
    behavior: Behavior,
    c: ScoringContext,
    memory: BehaviorMemory,
    cfg: BehaviorUtilityConfig,
    b: ScoreBreakdown,
) -> None:
    repeats = memory.repetitions(behavior)
    penalty = cfg.repetition_penalty * repeats
    if memory.last_behavior() == behavior:
        penalty += cfg.last_behavior_penalty
    b.add("repetition", -penalty)

    since = memory.seconds_since_started(behavior, c.now)
    if since is not None and since < cfg.recency_window_seconds:
        fade = 1 - since / cfg.recency_window_seconds
        b.add("recency", -cfg.recency_penalty * fade)

    if behavior == Behavior.ASK_FOR_ATTENTION:
        since_ask = memory.seconds_since_attention_request(c.now)
        if since_ask is not None and since_ask < cfg.attention_request_cooldown_seconds:
            fade = 1 - since_ask / cfg.attention_request_cooldown_seconds
            b.add("attention_request", -cfg.attention_request_penalty * fade)
        if memory.recently_ignored(c.now):
            b.add("ignored", -cfg.ignored_penalty)


def _random_points(
    p: BehaviorProfile,
    rng: random.Random,
    cfg: BehaviorUtilityConfig,
    b: ScoreBreakdown,
) -> None:
    if p.whim_chance and rng.random() < p.whim_chance:
        b.add("whim", p.whim_points)
    if cfg.variation:
        b.add("variation", (rng.random() * 2 - 1) * cfg.variation)


def _reason(profile: BehaviorProfile, breakdown: ScoreBreakdown) -> str:
    drivers = sorted(
        ((k, v) for k, v in breakdown.components.items() if k != "base"),
        key=lambda kv: abs(kv[1]),
        reverse=True,
    )[:2]
    if not drivers:
        return profile.description
    detail = ", ".join(f"{k} {v:+.0f}" for k, v in drivers)
    return f"{profile.description} ({detail})"


class UtilityScorer:
    def __init__(
        self,
        config: BehaviorUtilityConfig | None = None,
        preference: PreferenceBonus | None = None,
    ) -> None:
        self.config = config or BehaviorUtilityConfig()
        self.preference = preference

    def score(
        self,
        behavior: Behavior,
        spec: BehaviorSpec,
        context: ScoringContext,
        memory: BehaviorMemory,
        rng: random.Random,
    ) -> BehaviorScore:
        cfg = self.config
        profile = cfg.profiles.get(behavior) or BehaviorProfile(behavior.value)
        breakdown = ScoreBreakdown()

        _profile_points(profile, context, breakdown)
        _distraction_points(spec, context, memory, cfg, breakdown)
        _memory_points(behavior, context, memory, cfg, breakdown)
        _random_points(profile, rng, cfg, breakdown)

        if self.preference is not None:
            bonus = self.preference(behavior, context)
            limit = cfg.max_preference_bonus
            breakdown.add("preference", max(-limit, min(limit, bonus)))

        return BehaviorScore(
            behavior=behavior,
            score=breakdown.total,
            breakdown=breakdown,
            reason=_reason(profile, breakdown),
        )

    def score_all(
        self,
        behaviors,
        specs: dict[Behavior, BehaviorSpec],
        context: ScoringContext,
        memory: BehaviorMemory,
        rng: random.Random,
    ) -> list[BehaviorScore]:
        """Scores, highest first."""
        scored = [
            self.score(b, specs[b], context, memory, rng)
            for b in behaviors
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def select(
        self,
        candidates: list[BehaviorScore],
        rng: random.Random,
    ) -> tuple[BehaviorScore, list[BehaviorScore]]:
        """
        Controlled variation: behaviors near the leader get lottery tickets
        in proportion to how close they are, then one ticket is drawn.
        Low scorers never compete with a clearly better behavior.
        """
        cfg = self.config
        best = candidates[0].score
        floor = max(best - cfg.near_best_margin, best * cfg.min_fraction_of_best)
        strong = [s for s in candidates if s.score >= floor]

        span = max(best - floor, 1e-9)
        tickets: list[Behavior] = []
        for s in strong:
            count = 1 + round((s.score - floor) / span * (cfg.max_tickets - 1))
            tickets.extend([s.behavior] * count)

        chosen = rng.choice(tickets)
        return next(s for s in strong if s.behavior == chosen), strong
