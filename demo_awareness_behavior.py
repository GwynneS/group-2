from __future__ import annotations

import time

from integration.brain import CompanionBrain


def main() -> None:
    brain = CompanionBrain()

    print("Screen-awareness + Tamagotchi behavior demo")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            update = brain.update()

            print(
                f"[{update.screen.activity_kind:8}] "
                f"app={update.screen.foreground.process_name or 'unknown':22} "
                f"idle={update.screen.idle_seconds:6.1f}s | "
                f"mood={update.pet.mood:8} "
                f"behavior={update.decision.behavior:16} "
                f"reason={update.decision.reason}"
            )

            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
