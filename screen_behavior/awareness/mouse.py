from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import monotonic
from typing import Callable


@dataclass(slots=True)
class LookDirection:
    """Where the pet should look to face the cursor."""
    dx: float           # unit vector, +x = right
    dy: float           # unit vector, +y = down (screen coordinates)
    distance_px: float
    angle_degrees: float  # 0 = right, 90 = down


@dataclass(slots=True)
class MouseActivity:
    monitoring_available: bool = False
    x: int = 0
    y: int = 0
    velocity_x: float = 0.0   # px/s
    velocity_y: float = 0.0   # px/s
    speed: float = 0.0        # px/s
    moving: bool = False
    seconds_since_move: float | None = None
    distance_last_5_seconds: float = 0.0

    def look_from(self, from_x: float, from_y: float) -> LookDirection:
        """
        Direction from a point (e.g. the pet's eyes) to the cursor. The
        renderer owns the pet's position, so it passes it in.
        """
        dx = self.x - from_x
        dy = self.y - from_y
        distance = math.hypot(dx, dy)
        if distance == 0:
            return LookDirection(0.0, 0.0, 0.0, 0.0)
        return LookDirection(
            dx=dx / distance,
            dy=dy / distance,
            distance_px=distance,
            angle_degrees=math.degrees(math.atan2(dy, dx)) % 360,
        )


class MouseMotionTracker:
    """
    Turns a stream of cursor positions into motion data.

    Only positions are used; no clicks, no content under the cursor.
    """

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        velocity_window_seconds: float = 0.15,
        moving_speed_px_per_second: float = 30.0,
        history_seconds: float = 5.0,
    ) -> None:
        self._clock = clock
        self._velocity_window = velocity_window_seconds
        self._moving_speed = moving_speed_px_per_second
        self._history_seconds = history_seconds

        self._samples: deque[tuple[float, int, int]] = deque()
        self._last_move: float | None = None
        self._monitoring_available = False
        self._lock = Lock()

    def set_monitoring_available(self, value: bool) -> None:
        with self._lock:
            self._monitoring_available = bool(value)

    def record_position(self, x: int, y: int) -> None:
        now = self._clock()
        with self._lock:
            if self._samples:
                _, last_x, last_y = self._samples[-1]
                if (x, y) != (last_x, last_y):
                    self._last_move = now
            self._samples.append((now, x, y))
            self._prune(now)

    def snapshot(self) -> MouseActivity:
        now = self._clock()

        with self._lock:
            self._prune(now)

            if not self._monitoring_available or not self._samples:
                return MouseActivity(monitoring_available=False)

            _, x, y = self._samples[-1]

            # Velocity over the most recent short window.
            recent = [
                s for s in self._samples
                if now - s[0] <= self._velocity_window
            ]
            vx = vy = 0.0
            if len(recent) >= 2:
                t0, x0, y0 = recent[0]
                t1, x1, y1 = recent[-1]
                elapsed = t1 - t0
                if elapsed > 0:
                    vx = (x1 - x0) / elapsed
                    vy = (y1 - y0) / elapsed
            speed = math.hypot(vx, vy)

            distance = 0.0
            previous = None
            for _, sx, sy in self._samples:
                if previous is not None:
                    distance += math.hypot(sx - previous[0], sy - previous[1])
                previous = (sx, sy)

            return MouseActivity(
                monitoring_available=True,
                x=x,
                y=y,
                velocity_x=vx,
                velocity_y=vy,
                speed=speed,
                moving=speed >= self._moving_speed,
                seconds_since_move=(
                    None if self._last_move is None
                    else max(0.0, now - self._last_move)
                ),
                distance_last_5_seconds=distance,
            )

    def _prune(self, now: float) -> None:
        cutoff = now - self._history_seconds
        # Keep at least the latest sample so position survives a still mouse.
        while len(self._samples) > 1 and self._samples[0][0] < cutoff:
            self._samples.popleft()


class ContinuousMouseMonitor:
    """
    Polls the cursor position on a background thread (default 30 times per
    second) so motion data is fresh between brain updates.

    Works on macOS and Windows through the awareness backend's cursor
    reader; reading the cursor position needs no special OS permission.

    `add_listener(fn)` calls fn(x, y) on every cursor change, for a renderer
    that wants to move the pet's eyes every frame.
    """

    def __init__(
        self,
        read_position: Callable[[], tuple[int, int]],
        tracker: MouseMotionTracker | None = None,
        hz: float = 30.0,
    ) -> None:
        self._read_position = read_position
        self.tracker = tracker or MouseMotionTracker()
        self._interval = 1.0 / hz
        self._listeners: list[Callable[[int, int], None]] = []
        self._stop = Event()
        self._thread: Thread | None = None
        self._last: tuple[int, int] | None = None

    def add_listener(self, listener: Callable[[int, int], None]) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[int, int], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def poll_once(self) -> None:
        x, y = self._read_position()
        self.tracker.record_position(x, y)

        if (x, y) != self._last:
            self._last = (x, y)
            for listener in list(self._listeners):
                try:
                    listener(x, y)
                except Exception:
                    # A broken listener must not stop tracking.
                    pass

    def start(self) -> None:
        if self._thread is not None:
            return

        try:
            self.poll_once()
        except Exception:
            self.tracker.set_monitoring_available(False)
            return

        self.tracker.set_monitoring_available(True)
        self._stop.clear()
        self._thread = Thread(
            target=self._run,
            name="mouse-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def snapshot(self) -> MouseActivity:
        return self.tracker.snapshot()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.poll_once()
            except Exception:
                continue
