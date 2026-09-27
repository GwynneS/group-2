from __future__ import annotations

from dataclasses import dataclass

from screen_behavior.pet.enums import Behavior


@dataclass(frozen=True, slots=True)
class NeedsConfig:
    hunger_per_second: float = 0.004
    base_energy_drain_per_second: float = 0.002
    attention_drain_per_second: float = 0.003
    boredom_gain_per_second: float = 0.003

    hungry_energy_multiplier: float = 1.6
    somewhat_hungry_energy_multiplier: float = 1.25

    sleep_energy_restore_per_second: float = 0.025


@dataclass(frozen=True, slots=True)
class BehaviorSpec:
    min_energy: float
    energy_cost: float
    commitment_seconds: float
    cooldown_seconds: float
    distracting: bool


BEHAVIOR_SPECS: dict[Behavior, BehaviorSpec] = {
    Behavior.IDLE: BehaviorSpec(0, 0.0, 8, 0, False),
    Behavior.WAVE: BehaviorSpec(8, 0.5, 4, 25, False),
    Behavior.DANCE: BehaviorSpec(55, 7.0, 8, 180, True),
    Behavior.STRETCH: BehaviorSpec(10, 0.5, 6, 45, False),
    Behavior.LOOK_AROUND: BehaviorSpec(0, 0.1, 6, 18, False),
    Behavior.SIT_DOWN: BehaviorSpec(0, 0.0, 15, 10, False),
    Behavior.SLEEP: BehaviorSpec(0, 0.0, 20, 10, False),
    Behavior.WALK_AROUND_CORNER: BehaviorSpec(28, 2.5, 10, 90, True),
    Behavior.ASK_FOR_ATTENTION: BehaviorSpec(5, 0.4, 8, 120, True),
    Behavior.FOLLOW_MOUSE_WITH_EYES: BehaviorSpec(0, 0.1, 10, 15, False),
    Behavior.SEND_KISS: BehaviorSpec(70, 0.8, 5, 300, False),
    Behavior.PLAY_DEAD: BehaviorSpec(35, 1.0, 15, 600, True),
    Behavior.STUDY_WITH_USER: BehaviorSpec(0, 0.0, 30, 5, False),
    Behavior.WATCH_SCREEN: BehaviorSpec(0, 0.0, 20, 10, False),
}
