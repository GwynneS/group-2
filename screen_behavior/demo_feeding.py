from __future__ import annotations

import argparse
import shlex

from screen_behavior.awareness.models import ScreenContext
from screen_behavior.integration.brain import CompanionBrain


HELP = """Commands:
  fish             give buddy a fish
  wait <minutes>   let time pass (buddy gets hungrier)
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


class NoScreenAwareness:
    def snapshot(self) -> ScreenContext:
        return ScreenContext()


def _wait(brain, clock, minutes):
    # Step in 1-second ticks so needs/behavior evolve naturally.
    for _ in range(int(minutes * 60)):
        clock.value += 1
        brain.update()


def _print_status(brain) -> None:
    update = brain.update()
    pet = update.pet
    print(
        f"  hunger={pet.hunger:5.1f}  energy={pet.energy:5.1f}  "
        f"affection={pet.affection:5.1f}  attention={pet.attention:5.1f}"
    )
    print(
        f"  mood={pet.mood.value}  special={pet.special_mood}  "
        f"behavior={update.decision.behavior.value}"
    )


def _feed(brain) -> None:
    result = brain.feed()
    mark = "ate" if result.accepted else "REFUSED"
    print(f"  [{mark}] {result.reason}")
    _print_status(brain)


def interactive() -> None:
    clock = ManualClock()
    brain = CompanionBrain(awareness=NoScreenAwareness(), clock=clock)

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
        elif cmd == "fish":
            _feed(brain)
        elif cmd == "wait":
            try:
                minutes = float(args[0]) if args else 10
            except ValueError:
                print("  usage: wait <minutes>")
                continue
            _wait(brain, clock, minutes)
            print(f"  {minutes:g} minutes passed")
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
    brain = CompanionBrain(awareness=NoScreenAwareness(), clock=clock)

    print("Feeding scenario demo\n")

    print("1. Buddy is full -> fish")
    brain.pet.hunger = 5
    _feed(brain)

    print("\n2. Buddy is hungry -> fish")
    brain.pet.hunger = 80
    _feed(brain)

    print("\n3. Another fish right away")
    _feed(brain)

    print("\n4. And another (now full)")
    _feed(brain)


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
