from __future__ import annotations

import argparse
import platform
import random
import time

from screen_behavior.awareness.models import (
    ActivityType,
    KeyboardActivity,
    ScreenContext,
    WindowEdgeAwareness,
    WindowInfo,
)
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.pet.behavior import (
    BehaviorEngine,
    ExternalSignals,
)
from screen_behavior.pet.models import PetState
from screen_behavior.pet.needs import NeedsSystem


class ManualClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _top_scores(scores, count=3):
    ranked = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )
    return ", ".join(
        f"{activity.value}={score:.2f}"
        for activity, score in ranked[:count]
    )


def live_demo() -> None:
    brain = CompanionBrain()

    print(f"Platform: {platform.system()}")
    print("V0.5 live Screen Awareness + Tamagotchi Behavior demo")
    print("Candidate scoring + stable activity switching enabled.")
    print("No raw keystrokes are recorded.")
    print("Switch between apps. Ctrl+C to stop.\n")

    try:
        while True:
            update = brain.update()
            screen = update.screen
            pet = update.pet
            decision = update.decision

            fg = screen.foreground or WindowInfo()
            keyboard = screen.keyboard or KeyboardActivity()
            edge = screen.window_edge or WindowEdgeAwareness()

            app_name = (
                fg.app_name
                or fg.process_name
                or "unknown"
            )

            inactivity = (
                "N/A"
                if keyboard.current_no_typing_duration is None
                else f"{keyboard.current_no_typing_duration:.1f}s"
            )

            print(
                f"activity={screen.activity.value:9} "
                f"conf={screen.activity_confidence:.2f} "
                f"leader={(screen.leading_activity.value if screen.leading_activity else '-'):9} "
                f"leader_conf={screen.leading_activity_confidence:.2f} "
                f"duration={screen.activity_duration_seconds:6.1f}s | "
                f"app={app_name[:16]:16} | "
                f"typing={str(keyboard.typing_active):5} "
                f"no-type={inactivity:8} | "
                f"behavior={decision.behavior.value:22} "
                f"commit={decision.commitment_remaining_seconds:5.1f}s"
            )
            print(
                "  scores: "
                + _top_scores(screen.activity_scores)
            )

            if screen.pending_activity is not None:
                print(
                    f"  pending switch -> {screen.pending_activity.value} "
                    f"for {screen.pending_activity_seconds:.1f}s"
                )

            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        brain.close()


def scenario_demo() -> None:
    print("V0.5 behavior scenario demo\n")
    print(
        "Behavior commitment means the brain keeps the selected behavior "
        "for a minimum period instead of re-rolling every update.\n"
    )

    scenarios = [
        (
            "Coding",
            PetState(),
            ScreenContext(
                activity=ActivityType.CODING,
                activity_confidence=0.98,
            ),
        ),
        (
            "Studying",
            PetState(),
            ScreenContext(
                activity=ActivityType.STUDYING,
                activity_confidence=0.95,
            ),
        ),
        (
            "Gaming",
            PetState(),
            ScreenContext(
                activity=ActivityType.GAMING,
                activity_confidence=0.92,
            ),
        ),
        (
            "Very tired",
            PetState(energy=8),
            ScreenContext(activity=ActivityType.OTHER),
        ),
        (
            "Lonely",
            PetState(attention=8),
            ScreenContext(activity=ActivityType.OTHER),
        ),
    ]

    for index, (label, pet, screen) in enumerate(scenarios):
        clock = ManualClock(1000.0 + index * 100)
        needs = NeedsSystem()
        needs.update_mood(pet)

        engine = BehaviorEngine(
            rng=random.Random(index + 10),
            clock=clock,
        )

        decision = engine.decide(
            pet,
            screen,
        )

        print(label)
        print(f"  activity:   {screen.activity.value}")
        print(f"  mood:       {pet.mood.value}")
        print(f"  behavior:   {decision.behavior.value}")
        print(f"  reason:     {decision.reason}")
        print(
            f"  commitment: "
            f"{decision.commitment_remaining_seconds:.1f}s"
        )
        print()

    print("Behavior commitment / cooldown")
    clock = ManualClock(7000)
    pet = PetState(energy=100)
    engine = BehaviorEngine(
        rng=random.Random(4),
        clock=clock,
    )
    screen = ScreenContext(activity=ActivityType.OTHER)

    first = engine.decide(pet, screen)
    print(f"  first behavior: {first.behavior.value}")

    clock.advance(1)
    second = engine.decide(pet, screen)
    print(
        "  one second later: "
        f"{second.behavior.value} "
        "(minimum commitment keeps the current behavior)"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenarios",
        action="store_true",
        help="Run instant deterministic scenarios.",
    )
    args = parser.parse_args()

    if args.scenarios:
        scenario_demo()
    else:
        live_demo()


if __name__ == "__main__":
    main()
