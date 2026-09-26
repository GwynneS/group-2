from __future__ import annotations

import json
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


UI_DIRECTORY = Path(__file__).resolve().parent / "UI"
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

        if request_path == "/":
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, format: str, *args: Any) -> None:
        return


class AnimationBridge:
    """Serve the buddy UI and expose its current animation state to the page."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._state = {
            "animation": "lounging",
            "message": ANIMATION_LABELS["lounging"],
        }
        self._server: ThreadingHTTPServer | None = None
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
        animation = animation_for_update(update)
        self.set_animation(animation)
        return animation

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._state)

    def start(self, open_browser: bool = True) -> str:
        if self._server is None:
            handler = partial(_AnimationRequestHandler, bridge=self)
            self._server = ThreadingHTTPServer(
                (self.host, self.port),
                handler,
            )
            self._server.daemon_threads = True
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