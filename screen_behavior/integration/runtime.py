from __future__ import annotations

import threading
from typing import Any, Callable

from screen_behavior.integration.presenter import offline_state, present
from screen_behavior.pet.interactions import InteractionEffect


# Numeric effects for interactions that come from the UI or the extension.
# The UI decides *that* a headpat happened; the brain decides what it does.
INTERACTIONS: dict[str, InteractionEffect] = {
    "pet": InteractionEffect(
        attention_delta=12,
        affection_delta=4,
        boredom_delta=-8,
    ),
    "chat": InteractionEffect(
        attention_delta=8,
        affection_delta=2,
        boredom_delta=-5,
    ),
}


class BuddyRuntime:
    """
    Runs a CompanionBrain on a background thread and gives servers one
    thread-safe place to read state and send events.

    Everything that touches the brain goes through one lock, so HTTP
    handler threads and the update loop never interleave.
    """

    def __init__(
        self,
        brain_factory: Callable[[], Any] | None = None,
        interval_seconds: float = 1.0,
    ) -> None:
        if brain_factory is None:
            from screen_behavior.integration.brain import CompanionBrain
            brain_factory = CompanionBrain

        self.brain = brain_factory()
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = offline_state("Starting up...")
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    # --- lifecycle --------------------------------------------------------

    def start(self) -> "BuddyRuntime":
        if self._thread is None:
            self.tick()
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="buddy-brain",
                daemon=True,
            )
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        close = getattr(self.brain, "close", None)
        if callable(close):
            close()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception as exc:  # keep serving the last good state
                print(f"[brain] update failed: {exc!r}")

    # --- brain access -----------------------------------------------------

    def tick(self) -> dict[str, Any]:
        with self._lock:
            update = self.brain.update()
            state = present(update)
            self._state = state
        for listener in list(self._listeners):
            try:
                listener(state)
            except Exception:
                pass
        return state

    def state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def add_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        """Called with the presented state after every brain update."""
        self._listeners.append(listener)

    def feed(self) -> dict[str, Any]:
        with self._lock:
            result = self.brain.feed()
        return {"accepted": result.accepted, "reason": result.reason}

    def interact(self, kind: str) -> dict[str, Any]:
        effect = INTERACTIONS.get(kind)
        if effect is None:
            return {"ok": False, "error": f"unknown interaction {kind!r}"}
        with self._lock:
            self.brain.apply_interaction(effect)
        return {"ok": True}

    def browser_activity(self, payload: dict[str, Any]) -> dict[str, Any]:
        awareness = getattr(self.brain, "awareness", None)
        record = getattr(awareness, "record_browser_activity", None)
        if not callable(record):
            return {"ok": False, "error": "awareness does not accept browser data"}
        with self._lock:
            record(payload)
        return {"ok": True}
