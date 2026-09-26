from __future__ import annotations

import argparse
import shlex

from screen_behavior.awareness.models import ActivityType, ScreenContext
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.pet.feeding import FoodType


HELP = """Commands:
  dry              feed dry food
  wet              feed wet food (must be earned first)
  work <minutes>   simulate coding for N minutes (earns wet food)
  play <minutes>   simulate browsing for N minutes (earns nothing)
  hungry           set hunger to 70 so buddy will eat
  status           show buddy's state
  help             show this list
  quit             exit
"""


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class ManualAwareness:
    def __init__(self) -> None:
        self.activity = ActivityType.OTHER

    def snapshot(self) -> ScreenContext:
        return ScreenContext(activity=self.activity)


def _simulate(brain, clock, awareness, activity, minutes):
    awareness.activity = activity
    # Step in 1-second ticks so hyper/needs/behavior evolve naturally.
    for _ in range(int(minutes * 60)):
        clock.value += 1
        brain.update()
    awareness.activity = ActivityType.OTHER


def _print_status(brain) -> None:
    update = brain.update()
    pet = update.pet
    feeding = update.feeding
    progress = (
        feeding.productive_seconds_toward_next_wet_food
        / feeding.productive_seconds_per_wet_food
    )
    print(
        f"  hunger={pet.hunger:5.1f}  energy={pet.energy:5.1f}  "
        f"affection={pet.affection:5.1f}  attention={pet.attention:5.1f}"
    )
    print(
        f"  mood={pet.mood.value}  special={pet.special_mood}  "
        f"behavior={update.decision.behavior.value}"
    )
    print(
        f"  wet food={feeding.wet_food_available}  "
        f"next wet food={progress:.0%}  "
        f"hyper={feeding.hyper_seconds_remaining:.0f}s"
    )


def _feed(brain, food) -> None:
    result = brain.feed(food)
    mark = "ate" if result.accepted else "REFUSED"
    print(f"  [{mark}] {result.reason}")
    _print_status(brain)


def interactive() -> None:
    clock = ManualClock()
    awareness = ManualAwareness()
    brain = CompanionBrain(awareness=awareness, clock=clock)

    print("Feeding demo (simulated time; no real screen reading)")
    print(HELP)
    _print_status(brain)

    while True:
        try:
            parts = shlex.split(input("\nfeed> "))
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not parts:
            continue

        cmd, args = parts[0].lower(), parts[1:]

        if cmd in {"quit", "exit", "q"}:
            return
        elif cmd == "dry":
            _feed(brain, FoodType.DRY)
        elif cmd == "wet":
            _feed(brain, FoodType.WET)
        elif cmd in {"work", "play"}:
            try:
                minutes = float(args[0]) if args else 25
            except ValueError:
                print("  usage: work <minutes>")
                continue
            activity = (
                ActivityType.CODING if cmd == "work"
                else ActivityType.BROWSING
            )
            _simulate(brain, clock, awareness, activity, minutes)
            print(f"  simulated {minutes:g} min of {activity.value}")
            _print_status(brain)
        elif cmd == "hungry":
            brain.pet.hunger = 70
            _print_status(brain)
        elif cmd == "status":
            _print_status(brain)
        else:
            print(HELP)


def scenarios() -> None:
    clock = ManualClock()
    awareness = ManualAwareness()
    brain = CompanionBrain(awareness=awareness, clock=clock)

    print("Feeding scenario demo\n")

    print("1. Buddy starts fairly full -> dry food")
    brain.pet.hunger = 5
    _feed(brain, FoodType.DRY)

    print("\n2. Buddy gets hungry -> dry food")
    brain.pet.hunger = 70
    _feed(brain, FoodType.DRY)

    print("\n3. Try wet food before earning any")
    _feed(brain, FoodType.WET)

    print("\n4. Work (coding) for 25 minutes")
    _simulate(brain, clock, awareness, ActivityType.CODING, 25)
    _print_status(brain)

    print("\n5. Buddy hungry again -> wet food")
    brain.pet.hunger = 70
    _feed(brain, FoodType.WET)

    print("\n6. One minute later (hyper wears off)")
    _simulate(brain, clock, awareness, ActivityType.BROWSING, 1)
    _print_status(brain)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", action="store_true")
    args = parser.parse_args()

    if args.scenarios:
        scenarios()
    else:
        interactive()


if __name__ == "__main__":
    main()
