"""
Utility brain simulator: watch the behavior brain decide, cycle by cycle,
in hand-built situations. No UI, sensors, or animation needed.

    python3 -m screen_behavior.demo_brain                 # all scenarios
    python3 -m screen_behavior.demo_brain --scenario idle
    python3 -m screen_behavior.demo_brain --scenario coding --cycles 40 --scores 5
    python3 -m screen_behavior.demo_brain --list

Each row shows the decision that cycle. `src` says which stage decided:
utility, commitment (still doing the previous behavior), urgent, sleep,
play_dead, fallback. For utility decisions the top scores are shown.
"""
from __future__ import annotations

import argparse
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from screen_behavior.awareness.models import (
    ActivityType,
    KeyboardActivity,
    ScreenContext,
    UserState,
)
from screen_behavior.pet.behavior import BehaviorEngine
from screen_behavior.pet.config import BEHAVIOR_SPECS
from screen_behavior.pet.interactions import InteractionEffect, apply_interaction_effect
from screen_behavior.pet.models import PetState
from screen_behavior.pet.needs import NeedsSystem


def _coding(minutes: float) -> ScreenContext:
    return ScreenContext(
        activity=ActivityType.CODING,
        activity_confidence=0.95,
        activity_duration_seconds=minutes * 60,
        keyboard=KeyboardActivity(monitoring_available=True, typing_active=True),
        user_state=UserState.FOCUSED,
    )


def _idle(minutes: float) -> ScreenContext:
    return ScreenContext(
        activity=ActivityType.IDLE,
        idle_seconds=minutes * 60,
        user_state=UserState.AWAY if minutes >= 5 else UserState.IDLE,
    )


VIDEO = ScreenContext(
    activity=ActivityType.VIDEO,
    activity_confidence=0.92,
    user_state=UserState.PASSIVE,
)
BROWSING = ScreenContext(
    activity=ActivityType.BROWSING,
    activity_confidence=0.8,
    user_state=UserState.ACTIVE,
)


@dataclass
class Scenario:
    description: str
    pet: Callable[[], PetState]
    screen: Callable[[float], ScreenContext]  # minutes elapsed -> context
    cycles: int = 20
    step_seconds: float = 15.0
    setup: Callable[[PetState], None] | None = None
    notes: list[str] = field(default_factory=list)


SCENARIOS: dict[str, Scenario] = {
    "coding": Scenario(
        "A. user coding for a long period",
        pet=lambda: PetState(energy=85, attention=70),
        screen=lambda m: _coding(20 + m),
        cycles=24,
        step_seconds=30,
    ),
    "idle": Scenario(
        "B. user stops coding and goes idle",
        pet=lambda: PetState(energy=85, attention=70, boredom=40),
        screen=lambda m: _coding(30) if m < 3 else _idle(m - 3),
        cycles=24,
        step_seconds=20,
    ),
    "video": Scenario(
        "C. user watching a video",
        pet=lambda: PetState(energy=75),
        screen=lambda m: VIDEO,
        cycles=16,
        step_seconds=20,
    ),
    "bored": Scenario(
        "D. high boredom while the user browses",
        pet=lambda: PetState(energy=85, boredom=90),
        screen=lambda m: BROWSING,
        cycles=16,
        step_seconds=20,
    ),
    "lonely": Scenario(
        "E. low attention (lonely), user browsing",
        pet=lambda: PetState(attention=28),
        screen=lambda m: BROWSING,
        cycles=16,
        step_seconds=20,
    ),
    "tired": Scenario(
        "F. low energy while the user codes",
        pet=lambda: PetState(energy=22),
        screen=lambda m: _coding(15 + m),
        cycles=16,
        step_seconds=30,
    ),
    "hyper": Scenario(
        "G. hyper for 60s (e.g. a treat), user idle",
        pet=lambda: PetState(energy=90),
        screen=lambda m: _idle(1 + m),
        setup=lambda pet: apply_interaction_effect(
            pet, InteractionEffect(hyper_seconds=60)
        ),
        cycles=16,
        step_seconds=10,
    ),
    "affection": Scenario(
        "H. high affection and energy, user idle",
        pet=lambda: PetState(energy=98, affection=92, attention=85),
        screen=lambda m: _idle(2 + m),
        cycles=16,
        step_seconds=20,
    ),
    "cycles": Scenario(
        "I. many decision cycles in one steady context (repetition check)",
        pet=lambda: PetState(energy=85),
        screen=lambda m: _coding(10 + m),
        cycles=60,
        step_seconds=35,
    ),
}


def run(
    name: str,
    seed: int = 0,
    cycles: int | None = None,
    top_scores: int = 3,
    quiet: bool = False,
) -> dict:
    scenario = SCENARIOS[name]
    clock = [0.0]
    engine = BehaviorEngine(rng=random.Random(seed), clock=lambda: clock[0])
    needs = NeedsSystem()
    pet = scenario.pet()
    if scenario.setup:
        scenario.setup(pet)
    needs.update_mood(pet)

    total = cycles or scenario.cycles
    starts: Counter = Counter()
    distracting = 0
    longest_run = run_len = 0
    previous_start = None
    current = None

    if not quiet:
        print(f"\n=== {scenario.description} (seed {seed}) ===")
        print(
            f"{'time':>6} {'activity':9} {'nrg':>4} {'att':>4} {'hun':>4} "
            f"{'bor':>4} {'mood':9} {'behavior':23} {'src':10} top scores / reason"
        )

    for _ in range(total):
        minutes = clock[0] / 60
        screen = scenario.screen(minutes)
        decision = engine.decide(pet, screen)
        needs.update_mood(pet)

        if decision.behavior != current:
            current = decision.behavior
            starts[current] += 1
            if BEHAVIOR_SPECS[current].distracting:
                distracting += 1
            run_len = run_len + 1 if current == previous_start else 1
            longest_run = max(longest_run, run_len)
            previous_start = current

        if not quiet:
            if decision.behavior_scores:
                ranked = sorted(
                    decision.behavior_scores.items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:top_scores]
                detail = "  ".join(f"{b.value}={v:.0f}" for b, v in ranked)
                detail += f"  | {decision.reason}"
            else:
                detail = decision.reason
            mm, ss = divmod(int(clock[0]), 60)
            print(
                f"{mm:3d}:{ss:02d} {screen.activity.value:9} "
                f"{pet.energy:4.0f} {pet.attention:4.0f} {pet.hunger:4.0f} "
                f"{pet.boredom:4.0f} {pet.mood.value:9} "
                f"{decision.behavior.value:23} {decision.source:10} {detail}"
            )

        clock[0] += scenario.step_seconds
        needs.tick(pet, scenario.step_seconds)

    summary = {
        "starts": dict(starts),
        "distinct": len(starts),
        "distracting_starts": distracting,
        "longest_same_behavior_run": longest_run,
    }
    if not quiet:
        print(
            f"summary: {summary['distinct']} distinct behaviors, "
            f"{distracting} distracting starts, longest run of the same "
            f"behavior {longest_run}; " + ", ".join(
                f"{b.value}={n}" for b, n in starts.most_common()
            )
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Utility brain simulator")
    parser.add_argument("--scenario", default="all", choices=["all", *SCENARIOS])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cycles", type=int)
    parser.add_argument("--scores", type=int, default=3, help="top scores to show")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        for name, s in SCENARIOS.items():
            print(f"  {name:10} {s.description}")
        return

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    for name in names:
        run(name, seed=args.seed, cycles=args.cycles, top_scores=args.scores)


if __name__ == "__main__":
    main()
