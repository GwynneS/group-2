from __future__ import annotations

import time

from screen_behavior.awareness.models import ScreenContext
from screen_behavior.integration.brain import CompanionBrain
from screen_behavior.pet.enums import Behavior


class NoScreenAwareness:
    """Keeps this demo about the microphone only."""

    def snapshot(self) -> ScreenContext:
        return ScreenContext()


def _meter(level_db: float, floor_db: float) -> str:
    # -70 dB .. 0 dB mapped onto 40 characters.
    width = 40
    filled = int(max(0.0, min(1.0, (level_db + 70) / 70)) * width)
    floor_at = int(max(0.0, min(1.0, (floor_db + 70) / 70)) * width)
    bar = ["#" if i < filled else " " for i in range(width)]
    if 0 <= floor_at < width:
        bar[floor_at] = "|"
    return "".join(bar)


def main() -> None:
    brain = CompanionBrain(
        awareness=NoScreenAwareness(),
        enable_microphone=True,
    )

    first = brain.update()
    if not first.microphone.monitoring_available:
        print("Microphone unavailable.")
        print("Install:  pip install -r screen_behavior/requirements.txt")
        print("macOS:    System Settings > Privacy & Security > Microphone,")
        print("          allow Terminal / VS Code, then rerun.")
        print("Windows:  Settings > Privacy > Microphone, allow desktop apps.")
        brain.close()
        return

    print("Voice demo: only loudness is measured; no audio is recorded.")
    print("'|' marks background noise level. Ctrl+C to stop.\n")
    print("Buddy is playing dead. Talk normally, then YELL to wake it up.\n")

    brain.pet.play_dead_active = True

    try:
        while True:
            update = brain.update()
            mic = update.microphone
            state = (
                "LOUD!" if mic.loud_voice_detected
                else "talking" if mic.user_talking
                else "quiet"
            )
            print(
                f"\r[{_meter(mic.level_db, mic.noise_floor_db)}] "
                f"{mic.level_db:6.1f} dB  {state:8}  "
                f"buddy: {update.decision.behavior.value:12}",
                end="",
                flush=True,
            )

            if (
                not brain.pet.play_dead_active
                and update.decision.behavior == Behavior.WAVE
            ):
                print(
                    f"\n\nBuddy woke up! mood={update.decision.mood.value}, "
                    f"behavior={update.decision.behavior.value}"
                )
                print("Playing dead again in 3 seconds...\n")
                time.sleep(3)
                brain.pet.play_dead_active = True

            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    finally:
        brain.close()


if __name__ == "__main__":
    main()
