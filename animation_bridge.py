"""
Drive the Buddy UI from any Python script.

This is a thin wrapper around the one app server (UI/server.py), so the page
it serves is the full Buddy app: character, chat, extension download, and the
detailed animation panel. The only difference from `python3 UI/server.py` is
who decides the state: your script (set_animation / update_from_brain)
instead of the server's own brain.

    from animation_bridge import AnimationBridge
    bridge = AnimationBridge()
    bridge.start()
    bridge.set_animation("encouragement", "You got this!")
"""
from __future__ import annotations

import threading
import webbrowser
from typing import Any

from screen_behavior.integration.presenter import (
    ANIMATIONS as ANIMATION_LABELS,
    animation_for_update,
    offline_state,
    present,
)

__all__ = ["ANIMATION_LABELS", "AnimationBridge", "animation_for_update"]


class AnimationBridge:
    """Serve the Buddy UI with state pushed from a Python script."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "animation": "lounging",
            "message": ANIMATION_LABELS["lounging"],
        }
        self._server = None
        self._thread: threading.Thread | None = None

    def set_animation(self, animation: str, message: str | None = None) -> None:
        if animation not in ANIMATION_LABELS:
            allowed = ", ".join(ANIMATION_LABELS)
            raise ValueError(f"Unknown animation {animation!r}; choose from {allowed}")

        with self._lock:
            self._state = {
                "animation": animation,
                "message": message or ANIMATION_LABELS[animation],
            }

    def update_from_brain(self, update: Any) -> str:
        """Publish a full BrainUpdate (animation, pose, needs, mood, ...)."""
        state = present(update)
        with self._lock:
            self._state = state
        return state["animation"]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _served_state(self) -> dict[str, Any]:
        state = self.snapshot()
        if "brain" not in state:
            # Manual set_animation(): fill in what the page's other parts read.
            base = offline_state(state["message"])
            base.update(state, brain="script")
            return base
        return state

    def start(self, open_browser: bool = True) -> str:
        if self._server is None:
            # Imported here so importing this module (companion.py does, for
            # animation_for_update) doesn't load the whole app server.
            from UI.server import make_server

            self._server = make_server(
                self.host,
                self.port,
                state_provider=self._served_state,
            )
            self.port = self._server.server_address[1]
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
            )
            self._thread.start()

        url = f"http://{self.host}:{self.port}/"
        if open_browser:
            webbrowser.open(url)
        return url

    def close(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None


if __name__ == "__main__":
    bridge = AnimationBridge()
    print(f"Buddy animation UI: {bridge.start()}")
    print("Use Ctrl+C to stop the UI bridge.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        bridge.close()
