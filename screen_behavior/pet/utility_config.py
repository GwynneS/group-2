"""
Tuning for the utility behavior brain. Everything we expect to adjust during
playtesting lives here; behavior.py and utility.py contain no magic numbers.

Scores are points on a rough 0-100 scale (not probabilities). A behavior's
utility = its profile's points for the current situation + global modifiers
(focus/distraction, repetition, recency, budget, variation, preference).

BehaviorSpec in config.py still owns the *hard* rules (min energy, energy
cost, commitment, cooldown, distracting flag). Hard rules exclude a behavior
before scoring; nothing here can override them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from screen_behavior.awareness.models import ActivityType
from screen_behavior.pet.enums import BaseMood, Behavior, SpecialMood


@dataclass(frozen=True, slots=True)
class BehaviorProfile:
    """How much one behavior 'wants' to happen in a situation."""
    description: str
    base: float = 20.0

    # Points when the user is doing this activity (scaled by confidence).
    activity: dict[ActivityType, float] = field(default_factory=dict)

    # Points per unit (0..1) of each need signal.
    energy: float = 0.0          # * energy
    tiredness: float = 0.0       # * (1 - energy)
    boredom: float = 0.0         # * boredom
    loneliness: float = 0.0      # * (1 - attention)
    affection: float = 0.0       # * affection
    hunger: float = 0.0          # * hunger

    # Points while the user is focused, scaled by focus strength (0..1).
    # Positive = good company during work, negative = distracting.
    focus: float = 0.0
    # Points while the user is idle/away.
    idle: float = 0.0
    # Points while the cursor is moving.
    mouse_moving: float = 0.0
    # Points while the pet is hyper.
    hyper: float = 0.0

    mood: dict[BaseMood, float] = field(default_factory=dict)
    special_mood: dict[SpecialMood, float] = field(default_factory=dict)

    # 0..1 chance per decision of a random "whim" bonus (rare behaviors).
    whim_chance: float = 0.0
    whim_points: float = 0.0


A = ActivityType
M = BaseMood
S = SpecialMood

DEFAULT_PROFILES: dict[Behavior, BehaviorProfile] = {
    Behavior.IDLE: BehaviorProfile(
        "nothing better to do",
        base=22,
    ),
    Behavior.LOOK_AROUND: BehaviorProfile(
        "curious about its surroundings",
        base=28,
        focus=8,
        boredom=6,
    ),
    Behavior.SIT_DOWN: BehaviorProfile(
        "resting quietly",
        base=22,
        tiredness=28,
        focus=22,
        mood={M.TIRED: 15},
    ),
    Behavior.STRETCH: BehaviorProfile(
        "stretching",
        base=20,
        focus=6,
        boredom=8,
    ),
    Behavior.FOLLOW_MOUSE_WITH_EYES: BehaviorProfile(
        "watching the cursor",
        base=20,
        focus=14,
        mouse_moving=22,
    ),
    Behavior.STUDY_WITH_USER: BehaviorProfile(
        "keeping the user company while they work",
        base=8,
        activity={A.CODING: 40, A.STUDYING: 40},
        focus=36,
        idle=-15,  # nobody to study with
    ),
    Behavior.WATCH_SCREEN: BehaviorProfile(
        "watching what's on screen with the user",
        base=6,
        activity={A.GAMING: 55, A.VIDEO: 60},
        focus=6,
        idle=-10,
    ),
    Behavior.WAVE: BehaviorProfile(
        "saying hi",
        base=18,
        boredom=10,
        affection=8,
        focus=-22,
        idle=12,
        mood={M.HAPPY: 6, M.EXCITED: 8},
        special_mood={S.CUTE: 8, S.AFFECTIONATE: 6},
    ),
    Behavior.DANCE: BehaviorProfile(
        "full of energy",
        base=8,
        energy=20,
        boredom=22,
        focus=-10,
        idle=8,
        hyper=28,
        mood={M.HAPPY: 8, M.EXCITED: 14, M.TIRED: -20},
        special_mood={S.CUTE: 5},
    ),
    Behavior.WALK_AROUND_CORNER: BehaviorProfile(
        "bored; exploring",
        base=8,
        energy=8,
        boredom=30,
        focus=-10,
        idle=8,
        hyper=18,
        mood={M.TIRED: -15},
    ),
    Behavior.SEND_KISS: BehaviorProfile(
        "full of love",
        base=2,
        affection=18,
        energy=8,
        focus=-10,
        idle=8,
        mood={M.HAPPY: 6, M.EXCITED: 6},
        special_mood={S.AFFECTIONATE: 32, S.CUTE: 8},
    ),
    Behavior.PLAY_DEAD: BehaviorProfile(
        "rare autonomous play-dead",
        base=1,
        focus=-20,
        idle=4,
        whim_chance=0.02,
        whim_points=70,
    ),
    Behavior.ASK_FOR_ATTENTION: BehaviorProfile(
        "lonely; wants attention",
        base=2,
        loneliness=65,
        hunger=18,
        focus=-40,
        idle=6,
        mood={M.LONELY: 15, M.HUNGRY: 8},
        special_mood={S.JEALOUS: 15},
    ),
    Behavior.SLEEP: BehaviorProfile(
        "sleepy",
        base=0,
        tiredness=45,
        idle=12,
        mood={M.TIRED: 20},
    ),
}


@dataclass(frozen=True, slots=True)
class UrgentThresholds:
    """Biological overrides. These beat utility and interrupt commitment."""
    sleep_at_energy: float = 18.0
    sleep_until_energy: float = 75.0      # stay asleep until rested
    # Autonomous naps (not urgent) are only possible below this energy.
    nap_below_energy: float = 45.0
    attention_critical: float = 18.0
    hunger_critical: float = 80.0
    play_dead_max_seconds: float = 90.0


@dataclass(frozen=True, slots=True)
class BehaviorUtilityConfig:
    profiles: dict[Behavior, BehaviorProfile] = field(
        default_factory=lambda: dict(DEFAULT_PROFILES)
    )
    urgent: UrgentThresholds = field(default_factory=UrgentThresholds)

    # --- Focus / distraction -------------------------------------------
    # Extra penalty for BehaviorSpec.distracting behaviors, * focus strength.
    distracting_focus_penalty: float = 35.0
    # Penalty for distracting behaviors as the distraction budget empties.
    low_budget_penalty: float = 25.0
    # Penalty per distracting behavior started within recent_distracting_window.
    recent_distracting_penalty: float = 8.0
    recent_distracting_window_seconds: float = 600.0

    # --- Memory ----------------------------------------------------------
    history_size: int = 12
    # Penalty per occurrence in history, and extra for being the last one.
    repetition_penalty: float = 9.0
    last_behavior_penalty: float = 20.0
    # Fading penalty for behaviors started within this many seconds.
    recency_window_seconds: float = 120.0
    recency_penalty: float = 12.0
    # After an attention request, discourage another one for this long.
    attention_request_cooldown_seconds: float = 300.0
    attention_request_penalty: float = 45.0
    # Penalty for asking again after being ignored.
    ignored_penalty: float = 30.0

    # --- Selection -------------------------------------------------------
    # Behaviors within this many points of the leader are candidates...
    near_best_margin: float = 12.0
    # ...but only if they reach this fraction of the leader's score.
    min_fraction_of_best: float = 0.6
    # Leader gets this many lottery tickets; the weakest candidate gets 1.
    max_tickets: int = 6
    # +/- random points per behavior per decision (personality).
    variation: float = 3.0

    # --- Future learned personalization ----------------------------------
    # A preference hook may add at most this many points (either sign).
    max_preference_bonus: float = 10.0
