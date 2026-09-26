from __future__ import annotations

import time

from screen_behavior.awareness.mouse import ContinuousMouseMonitor
from screen_behavior.awareness.service import AwarenessService


# Pretend the pet sits here; the real position comes from the renderer.
PET_X, PET_Y = 800, 500

ARROWS = ["→", "↘", "↓", "↙", "←", "↖", "↑", "↗"]


def main() -> None:
    backend = AwarenessService._build_backend()
    monitor = ContinuousMouseMonitor(
        AwarenessService._cursor_reader(backend),
    )
    monitor.start()

    if not monitor.snapshot().monitoring_available:
        print("Could not read the cursor position.")
        return

    print("Continuous mouse demo. Move your mouse. Ctrl+C to stop.")
    print(f"Pretend pet is at ({PET_X}, {PET_Y}); arrow = where its eyes look.\n")

    try:
        while True:
            m = monitor.snapshot()
            look = m.look_from(PET_X, PET_Y)
            arrow = ARROWS[int((look.angle_degrees + 22.5) // 45) % 8]
            still = (
                "-" if m.seconds_since_move is None
                else f"{m.seconds_since_move:4.1f}s"
            )
            print(
                f"\r  pos=({m.x:5},{m.y:5})  speed={m.speed:7.0f} px/s  "
                f"{'MOVING' if m.moving else 'still ':6}  "
                f"since move={still}  eyes {arrow} "
                f"({look.distance_px:5.0f}px)   ",
                end="",
                flush=True,
            )
            time.sleep(1 / 30)
    except KeyboardInterrupt:
        print()
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
