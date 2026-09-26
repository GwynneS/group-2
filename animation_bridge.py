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
from UI.server import make_server

<<<<<<< HEAD
UI_DIRECTORY = Path(__file__).resolve().parent / "UI"
# The UI loads the buddy art and characters.js from here, under /extension/.
EXTENSION_DIRECTORY = Path(__file__).resolve().parent / "browser_extension"
ANIMATION_LABELS = {
    "lounging": "Lounging",
    "happy": "Happy",
    "sad": "Sad",
    "tired": "Tired",
    "angry": "Angry",
    "hungry": "Hungry",
    "encouragement": "You got this!",
}


def animation_for_update(update: Any) -> str:
    behavior = update.decision.behavior.value
    mood = update.pet.mood.value

    if behavior == "wave":
        return "encouragement"
    if behavior == "sleep" or mood == "tired" or update.pet.energy <= 15:
        return "tired"
    if mood == "hungry" or update.pet.hunger >= 70:
        return "hungry"
    if mood in {"mad", "annoyed"}:
        return "angry"
    if mood == "lonely" or behavior == "ask_for_attention":
        return "sad"
    if mood in {"happy", "excited"} or behavior in {"dance", "send_kiss"}:
        return "happy"
    return "lounging"


class _AnimationRequestHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args: Any,
        bridge: AnimationBridge,
        **kwargs: Any,
    ) -> None:
        self.bridge = bridge
        super().__init__(*args, directory=str(UI_DIRECTORY), **kwargs)

    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        if request_path == "/api/state":
            payload = json.dumps(self.bridge.snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        if request_path.startswith("/extension/"):
            self.directory = str(EXTENSION_DIRECTORY)
            self.path = self.path[len("/extension"):]
        elif request_path == "/":
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, format: str, *args: Any) -> None:
        return
=======
__all__ = ["ANIMATION_LABELS", "AnimationBridge", "animation_for_update"]
>>>>>>> 4c4be53baaa5a9f9b14e529463ac5dc625fcd7ff


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
